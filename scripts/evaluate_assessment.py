#!/usr/bin/env python3
"""Observe the production UCA in isolation; bypass routing and never score pedagogy.

Run in a standalone process. Only the named child uses inference. Its normal
prompts, middleware, structured output, retrieval, and student-model tools remain
intact; a deterministic parent dispatches one task and emits no student answer.
"""
import argparse
import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "tests/fixtures/assessment_cases.json"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from evaluate_tutoring import digest, json_value, model_request_evidence, source_manifest


def validate_cases(cases):
    from edbot.interface_def import Message, StudentModelEntry, UCAInput
    from edbot.student_model import normalize_concept

    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a nonempty list")
    seen = set()
    for case in cases:
        identifier = case.get("id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise ValueError("each case needs a unique nonempty id")
        seen.add(identifier)
        request = UCAInput.model_validate(case["uca_input"])
        concept = normalize_concept(request.concept)
        if not concept or concept != normalize_concept(case["concept"]):
            raise ValueError(f"case {identifier}: concept must match UCAInput")
        conversation = [Message.model_validate(item) for item in case["conversation"]]
        if not conversation or conversation[-1].role != "student" or any(not item.content.strip() for item in conversation):
            raise ValueError(f"case {identifier}: conversation must be nonempty and end with a student message")
        if case.get("prior_entry") is not None:
            prior = StudentModelEntry.model_validate(case["prior_entry"])
            if normalize_concept(prior.concept) != concept:
                raise ValueError(f"case {identifier}: prior concept must match UCAInput")
    return cases


def load_cases(path=DEFAULT_CASES, case_ids=None):
    document = json.loads(Path(path).read_text())
    if document.get("schema_version") != 1 or document.get("suite_kind") != "uca_component":
        raise ValueError("unsupported assessment fixture schema")
    cases = validate_cases(document["cases"])
    if case_ids:
        unknown = set(case_ids) - {case["id"] for case in cases}
        if unknown:
            raise ValueError(f"unknown case ids: {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case["id"] in case_ids]
    return cases


def persistence_check(case, before, after, output, tools, *, writes=None):
    """Mechanical agreement only: these checks make no judgment about understanding."""
    from edbot.student_model import normalize_concept

    key = normalize_concept(case["concept"])
    prior, saved = before.get(key), after.get(key)
    updates = [span for span in tools if span["name"] == "update_student_model"]
    checks = {
        "one_update": len(writes) == 1 if writes is not None else len(updates) == 1,
        "entry_saved": saved is not None,
        "output_present": output is not None,
        "only_target_concept": set(after) == {key},
        "assessment_count": saved is not None and saved["assessment_count"] == (prior["assessment_count"] if prior else 0) + 1,
        "student_turn": saved is not None and saved["assessed_at_turn"] == sum(item["role"] == "student" for item in case["conversation"]),
        "output_matches_store": bool(saved and output and normalize_concept(output["concept"]) == key
                                     and all(saved[field] == output[field] for field in ("tier", "confidence", "rationale"))),
        "prior_tier": output is not None and output["prior_tier"] == (prior["tier"] if prior else None),
    }
    return {"consistent": all(checks.values()), "checks": checks, "update_call_count": len(updates),
            "student_model_write_count": len(writes) if writes is not None else None}


async def run_evaluation(cases, backend="sglang", repetitions=1, *, fixture_path=DEFAULT_CASES,
                         label=None, on_progress=None):
    validate_cases(cases)
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    from deepagents.backends import FilesystemBackend
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.utils.function_calling import convert_to_openai_tool
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore
    from langgraph.store.base import PutOp
    from edbot import edbot_agent, model_config, service, student_model
    from edbot.interface_def import EdbotContext, StudentModelEntry, UCAInput, UCAOutput
    from profile_agent import TurnTrace, profiling_model
    from profile_inference import fetch_server_info

    class ObservedStore(InMemoryStore):
        """Observe committed synthetic writes, including writes made without an LLM tool."""
        def __init__(self):
            super().__init__()
            self.writes = []

        async def abatch(self, ops):
            ops = list(ops)
            result = await super().abatch(ops)
            self.writes.extend({"namespace": list(op.namespace), "key": op.key, "value": json_value(op.value)}
                               for op in ops if isinstance(op, PutOp))
            return result

    if any(getattr(service, name) is not None for name in ("_agent", "_conn", "_store_conn", "_store")):
        raise RuntimeError("Run the evaluator in its own process; an Edbot service is already initialized")

    class AssessmentDriver(BaseChatModel):
        task_json: str
        call_id: str

        @property
        def _llm_type(self):
            return "synthetic-assessment-driver"

        def bind_tools(self, tools, **kwargs):
            return self.bind(tools=[convert_to_openai_tool(tool) for tool in tools], **kwargs)

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            finished = any(isinstance(message, ToolMessage) and message.tool_call_id == self.call_id for message in messages)
            result = AIMessage(content="", tool_calls=[] if finished else [{
                "name": "task", "id": self.call_id,
                "args": {"subagent_type": "understanding-checking-agent", "description": self.task_json},
            }])
            return ChatResult(generations=[ChatGeneration(message=result)])

    class AssessmentTrace(TurnTrace):
        def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
            super().on_chat_model_start(serialized, messages, run_id=run_id, **kwargs)
            self.models[str(run_id)].update(model_request_evidence(messages, kwargs.get("invocation_params")))

        def on_llm_end(self, response, *, run_id, **kwargs):
            super().on_llm_end(response, run_id=run_id, **kwargs)
            generation = next((group[0] for group in response.generations if group), None)
            self.models[str(run_id)]["output_message"] = json_value(getattr(generation, "message", None))

        def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
            super().on_tool_start(serialized, input_str, run_id=run_id, **kwargs)
            self.tools[str(run_id)]["input"] = input_str

        def on_tool_end(self, output, *, run_id, **kwargs):
            super().on_tool_end(output, run_id=run_id, **kwargs)
            self.tools[str(run_id)].update(output=json_value(output), output_sha256=digest(output))

    report = {"schema_version": 1, "kind": "synthetic_assessment_evaluation", "component_only": True,
              "orchestrator_routing_evaluated": False, "synthetic_only": True,
              "started_at": datetime.now(timezone.utc).isoformat(), "backend": backend, "label": label,
              "requested_configuration": {"deterministic_assessment_save": model_config.DETERMINISTIC_ASSESSMENT_SAVE,
                                          "prefetch_assessment_prior": model_config.PREFETCH_ASSESSMENT_PRIOR,
                                          "reuse_course_evidence": model_config.REUSE_COURSE_EVIDENCE,
                                          "require_content_after_assessment": False},
              "quality": "not_reviewed", "execution": "running", "error": None, "cases": [],
              "manifest": source_manifest(cases, fixture_path), "server_info": None,
              "observation_limits": [
                  "A deterministic parent dispatches one UCA task. Routing, condition gating, active-question handoff, and student-facing replies are not evaluated.",
                  "REQUIRE_CONTENT_AFTER_ASSESSMENT is disabled only inside this component evaluation because its synthetic parent emits no tutoring reply.",
                  "Actual named UCA prompts, tools, middleware, runtime context, and output schema are retained; no research condition or tutoring policy is changed.",
                  "Every observation uses a fresh in-memory store/checkpointer and temporary filesystem. Course retrieval uses the normal shared source/index cache.",
                  "Synthetic parent calls are excluded from model metrics. assessment_s is the inclusive task span; total_s also includes graph overhead, excluding startup.",
                  "Execution and persistence checks do not score pedagogy, Bloom calibration, or learning. All quality remains not_reviewed.",
                  "Student-model writes are observed after successful store batches, excluding fixture setup and replay receipts. Model update-tool calls are reported separately.",
              ]}
    report["manifest"]["source_sha256"]["scripts/evaluate_assessment.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if on_progress:
        on_progress(report)
    if backend == "sglang":
        report["server_info"] = await asyncio.to_thread(
            fetch_server_info, os.environ.get("EDBOT_CHAT_BASE_URL", model_config.BASE_URL), vars(model_config))
        if report["server_info"]["status"] == "mismatch":
            report.update(execution="failed", error="Running SGLang configuration mismatch; no assessment requests were sent")
            if on_progress:
                on_progress(report)
            return report
    child_model = profiling_model(backend)
    real_load = edbot_agent.load_subagents

    def load_subagents(path):
        # Public raw-subagent model override preserves the real child while replacing its parent.
        return [{**spec, "model": child_model} for spec in real_load(path)]

    for case in cases:
        episode = {"case": case, "quality": "not_reviewed", "review": None, "observations": []}
        report["cases"].append(episode)
        for repetition in range(repetitions):
            student_id = f"assessment-{uuid4()}"
            request = UCAInput.model_validate(case["uca_input"])
            store = ObservedStore()
            if case.get("prior_entry") is not None:
                prior = StudentModelEntry.model_validate(case["prior_entry"])
                await store.aput(student_model.namespace(student_id), student_model.normalize_concept(prior.concept), prior.model_dump(mode="json"))
            store.writes.clear()  # Fixture setup is not an assessment write.
            row = {"student_id": student_id, "repetition": repetition, "execution": "running", "error": None,
                   "store_before": json_value(await student_model.load_all(store, student_id)),
                   "store_after": None, "student_model_writes": [], "uca_output": None, "messages": [], "startup_s": None,
                   "assessment_s": None, "total_s": None, "metrics": None,
                   "input_sha256": digest({"uca_input": request, "conversation": case["conversation"]})}
            episode["observations"].append(row)
            trace, graph = None, None
            run_config = {"configurable": {"thread_id": student_id}}
            with tempfile.TemporaryDirectory(prefix="edbot-assessment-") as directory, ExitStack() as patches:
                workspace = Path(directory)
                shutil.copy2(edbot_agent.ROOT_DIR / "AGENTS.md", workspace / "AGENTS.md")
                shutil.copytree(edbot_agent.ROOT_DIR / "skills", workspace / "skills")
                driver = AssessmentDriver(task_json=request.model_dump_json(), call_id=f"uca-{uuid4()}", profile=child_model.profile)
                patches.enter_context(patch.object(edbot_agent, "backend", FilesystemBackend(root_dir=workspace, virtual_mode=True)))
                patches.enter_context(patch.object(edbot_agent, "create_chat_model", lambda: driver))
                patches.enter_context(patch.object(edbot_agent, "load_subagents", load_subagents))
                patches.enter_context(patch.object(model_config, "REQUIRE_CONTENT_AFTER_ASSESSMENT", False))
                started = time.perf_counter()
                try:
                    graph = edbot_agent.create_edbot_agent(checkpointer=InMemorySaver(serde=service.SERDE), store=store)
                    row["startup_s"] = time.perf_counter() - started
                    started = time.perf_counter()
                    trace = AssessmentTrace(started)
                    run_config["callbacks"] = [trace]
                    messages = [(HumanMessage if item["role"] == "student" else AIMessage)(content=item["content"])
                                for item in case["conversation"]]
                    async with asyncio.timeout(service.TURN_TIMEOUT_SECONDS):
                        async for _ in graph.astream({"messages": messages}, config=run_config,
                                                     context=EdbotContext(student_id=student_id), stream_mode="messages"):
                            pass  # Component evidence only; never render a tutor response.
                    snapshot = await graph.aget_state(run_config)
                    row["messages"] = json_value(snapshot.values.get("messages", []))
                    outputs = [message for message in snapshot.values.get("messages", [])
                               if isinstance(message, ToolMessage) and message.tool_call_id == driver.call_id
                               and message.name == "task" and message.status == "success"]
                    if len(outputs) != 1:
                        raise ValueError("Expected one successful UCA task result")
                    row["uca_output"] = UCAOutput.model_validate_json(outputs[0].content).model_dump(mode="json")
                except Exception as exc:
                    row["error"] = f"{type(exc).__name__}: {exc}"
                finally:
                    row["total_s"] = time.perf_counter() - started if trace else None
                    row["store_after"] = json_value(await student_model.load_all(store, student_id))
                    row["student_model_writes"] = [write for write in store.writes
                                                  if tuple(write["namespace"]) == student_model.namespace(student_id)]
                    if graph is not None and not row["messages"]:
                        snapshot = await graph.aget_state(run_config)
                        row["messages"] = json_value(snapshot.values.get("messages", []))
            if trace:
                # Remove only our known synthetic driver; retain unexpected model calls as evidence.
                trace.models = {key: span for key, span in trace.models.items() if span["name"] != "AssessmentDriver"}
                row["metrics"] = trace.report()
                tasks = [span for span in trace.tools.values() if span["name"] == "task"]
                row["assessment_s"] = tasks[0]["duration_s"] if len(tasks) == 1 else None
            tools = (row["metrics"] or {}).get("tools", [])
            row["persistence"] = persistence_check(case, row["store_before"], row["store_after"], row["uca_output"], tools,
                                                   writes=row["student_model_writes"])
            failed = row["error"] or not row["persistence"]["consistent"] or (row["metrics"] or {}).get("truncated_model_calls")
            row["execution"] = "failed" if failed else "completed"
            if on_progress:
                on_progress(report)
        episode["execution"] = "failed" if any(row["execution"] == "failed" for row in episode["observations"]) else "completed"
    report["execution"] = "failed" if any(case["execution"] == "failed" for case in report["cases"]) else "completed"
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    if on_progress:
        on_progress(report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("sglang", "ollama"), default="sglang")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--cases-file", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--label")
    parser.add_argument("--list-cases", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.cases_file, args.case_ids)
        if args.repetitions < 1:
            raise ValueError("repetitions must be positive")
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    if args.list_cases:
        for case in cases:
            print(f"{case['id']}: {case['title']}")
        return 0
    if args.output is None:
        parser.error("--output is required unless --list-cases is used")
    try:
        output = args.output.open("x", encoding="utf-8")
    except OSError as exc:
        parser.error(f"output must be a new file in an existing directory: {exc}")
    report = {"schema_version": 1, "component_only": True, "quality": "not_reviewed", "execution": "running", "cases": []}

    def save(current):
        nonlocal report
        report = current
        output.seek(0)
        json.dump(json_value(report), output, ensure_ascii=False, indent=2)
        output.write("\n")
        output.truncate()
        output.flush()

    with output:
        save(report)
        try:
            report = asyncio.run(run_evaluation(cases, args.backend, args.repetitions,
                                               fixture_path=args.cases_file, label=args.label, on_progress=save))
        except (Exception, KeyboardInterrupt) as exc:
            report.update(execution="failed", error=f"{type(exc).__name__}: {exc}")
        save(report)
    print(f"Wrote {args.output.resolve()}; execution={report['execution']}; quality=not_reviewed; component_only=True")
    return 0 if report["execution"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
