#!/usr/bin/env python3
"""Collect synthetic tutoring episodes for explicit semantic review, never auto-grade them."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "tests/fixtures/tutoring_cases.json"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))


def json_value(value):
    """Retain structured tool/checkpoint data, including LangChain and Pydantic objects."""
    if hasattr(value, "model_dump"):
        return json_value(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def digest(value):
    encoded = json.dumps(json_value(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def model_request_evidence(messages, invocation_params):
    """Record synthetic message/tool context, never provider credentials or headers."""
    scalar_fields = {"_type", "model", "model_name", "temperature", "top_p", "top_k", "stop",
                     "max_tokens", "max_completion_tokens", "max_output_tokens", "stream", "seed",
                     "frequency_penalty", "presence_penalty", "n", "reasoning_effort", "reasoning"}
    structured_fields = {"tools", "tool_choice", "parallel_tool_calls", "response_format", "stream_options"}

    def allowlisted(parameters):
        if not isinstance(parameters, dict):
            return {}
        selected = {key: json_value(value) for key, value in parameters.items()
                    if key in scalar_fields and (value is None or isinstance(value, (str, int, float, bool, list)))}
        selected.update({key: json_value(parameters[key]) for key in structured_fields if key in parameters})
        extras = parameters.get("extra_body")
        if isinstance(extras, dict):
            safe_extras = {}
            template = extras.get("chat_template_kwargs")
            if isinstance(template, dict) and "enable_thinking" in template:
                safe_extras["chat_template_kwargs"] = {"enable_thinking": template["enable_thinking"]}
            for key in ("top_k", "min_p", "repetition_penalty"):
                if key in extras and isinstance(extras[key], (int, float)):
                    safe_extras[key] = extras[key]
            if safe_extras:
                selected["extra_body"] = safe_extras
        return selected

    parameters = allowlisted(invocation_params)
    if isinstance(invocation_params, dict) and isinstance(invocation_params.get("model_kwargs"), dict):
        parameters["model_kwargs"] = allowlisted(invocation_params["model_kwargs"])
    tools = parameters.get("tools", parameters.get("model_kwargs", {}).get("tools", [])) or []
    names = {tool.get("function", {}).get("name", tool.get("name")) for tool in tools if isinstance(tool, dict)}
    if "UCAOutput" in names or "update_student_model" in names:
        role = "understanding-checking-agent"
    elif "CGAOutput" in names:
        role = "content-generating-agent"
    elif "task" in names:
        role = "orchestrator"
    else:
        role = "unknown"
    request = {"input_messages": json_value(messages), "invocation_params": parameters}
    return {**request, "tools": tools, "inferred_role": role, "request_sha256": digest(request)}


def validate_cases(cases):
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a nonempty list")
    seen = set()
    for case in cases:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            raise ValueError("each case needs a unique nonempty id")
        seen.add(case_id)
        for field in ("expectations", "critical_failures", "review_dimensions"):
            if not case.get(field) or not all(isinstance(item, str) and item.strip() for item in case[field]):
                raise ValueError(f"case {case_id}: {field} must contain review criteria")
        turns = case.get("turns")
        if not isinstance(turns, list) or not turns:
            raise ValueError(f"case {case_id}: turns must be a nonempty list")
        turn_ids = set()
        for turn in turns:
            turn_id = turn.get("id")
            if not isinstance(turn_id, str) or not turn_id.strip() or turn_id in turn_ids:
                raise ValueError(f"case {case_id}: each turn needs a unique id")
            turn_ids.add(turn_id)
            if not isinstance(turn.get("message"), str) or not turn["message"].strip():
                raise ValueError(f"case {case_id}: each turn needs a synthetic message")
    return cases


def load_cases(path=DEFAULT_CASES, case_ids=None):
    document = json.loads(Path(path).read_text())
    if document.get("schema_version") != 1:
        raise ValueError("unsupported case schema_version")
    cases = validate_cases(document["cases"])
    if case_ids:
        requested = set(case_ids)
        unknown = requested - {case["id"] for case in cases}
        if unknown:
            raise ValueError(f"unknown case ids: {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case["id"] in requested]
    return cases


def source_manifest(cases, fixture_path):
    paths = [ROOT / "pyproject.toml", ROOT / "uv.lock", Path(__file__),
             ROOT / "scripts/profile_agent.py", ROOT / "scripts/profile_inference.py", Path(fixture_path)]
    paths.extend(path for path in (ROOT / "src/edbot").rglob("*")
                 if path.is_file() and path.suffix in {".py", ".md", ".yaml", ".yml"})
    hashes = {}
    for path in sorted(set(paths)):
        if path.is_file():
            name = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path.resolve())
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"source_sha256": hashes, "selected_cases_sha256": digest(cases),
            "request_hash_scope": "Canonical JSON of actual model input messages and allowlisted callback invocation parameters; credentials and headers are excluded.",
            "course_source_scope": "Retrieved source text and output hashes are captured in tool events; the complete course corpus is not snapshotted."}


async def run_evaluation(cases, backend="sglang", repetitions=1, profile_module=None,
                         fixture_path=DEFAULT_CASES, label=None, on_progress=None):
    """Run one isolated profiler session per case. Call only in a standalone process."""
    validate_cases(cases)
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    # Set before importing the app: its dotenv loader does not override these values.
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    if profile_module is None:
        import profile_agent as profile_module
    from edbot import service, student_model

    # Never inspect or close another caller's real student session.
    if any(getattr(service, name) is not None for name in ("_agent", "_conn", "_store_conn", "_store")):
        raise RuntimeError("Run the evaluator in its own process; an Edbot service is already initialized")
    report = {"schema_version": 1, "kind": "synthetic_tutoring_evaluation",
              "started_at": datetime.now(timezone.utc).isoformat(), "label": label,
              "backend": backend, "repetitions": repetitions, "synthetic_only": True,
              "quality": "not_reviewed", "execution": "running", "error": None,
              "manifest": source_manifest(cases, fixture_path), "cases": [],
              "observation_limits": [
                  "Scripted learner messages are not real learning observations and may not fit every generated reply.",
                  "Execution success does not assess correctness, answer leakage, or pedagogical quality.",
                  "Evidence capture adds overhead; compare latency with the same harness configuration.",
                  "Checkpoint messages are captured after each turn; nested retrieval/tool outputs are captured by callbacks.",
                  "No research-condition assignment or production tutoring policy is changed by this harness.",
              ]}
    if on_progress:
        on_progress(report)
    original_paths = (service.CHECKPOINT_PATH, service.STORE_PATH)
    real_turn = service.chat_turn
    base_trace = profile_module.TurnTrace
    for case in cases:
        observations, traces = [], []
        episode = {"case": case, "quality": "not_reviewed", "review": None,
                   "request_sha256": digest(case["turns"]),
                   "expected_turns": len(case["turns"]) * repetitions,
                   "execution": "running", "profile": None, "observations": observations,
                   "error": None}
        report["cases"].append(episode)

        class ReviewTrace(base_trace):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                traces.append(self)

            def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
                super().on_chat_model_start(serialized, messages, run_id=run_id, **kwargs)
                self.models[str(run_id)].update(model_request_evidence(messages, kwargs.get("invocation_params")))

            def on_llm_end(self, response, *, run_id, **kwargs):
                super().on_llm_end(response, run_id=run_id, **kwargs)
                generation = next((group[0] for group in response.generations if group), None)
                # Retain malformed argument text too: the completion guard may
                # reject it before any child task result reaches the checkpoint.
                self.models[str(run_id)]["output_message"] = json_value(getattr(generation, "message", None))

            def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
                super().on_tool_start(serialized, input_str, run_id=run_id, **kwargs)
                self.tools[str(run_id)]["input"] = input_str

            def on_tool_end(self, output, *, run_id, **kwargs):
                super().on_tool_end(output, run_id=run_id, **kwargs)
                span = self.tools.get(str(run_id))
                if span is not None:
                    span["output"] = json_value(output)
                    span["output_sha256"] = digest(output)

        async def observed_turn(student_id, message):
            # Check BEFORE dispatch or observation, while run_profile's temporary paths are active.
            if (not student_id.startswith("profile-") or service.CHECKPOINT_PATH in original_paths
                    or service.STORE_PATH in original_paths):
                raise RuntimeError("Refusing to evaluate or capture nonisolated student state")
            observation = {"student_id": student_id, "prompt": message,
                           "prompt_sha256": hashlib.sha256(message.encode()).hexdigest(),
                           "messages": [], "assessment_state": None, "capture_error": None}
            observations.append(observation)
            try:
                async for event in real_turn(student_id, message):
                    yield event
            finally:
                try:
                    if service._agent is None or service._store is None:
                        raise RuntimeError("Isolated service unavailable for checkpoint capture")
                    snapshot = await service._agent.aget_state(service.config_for(student_id))
                    observation["messages"] = json_value(snapshot.values.get("messages", []))
                    entries = await student_model.load_all(service._store, student_id)
                    observation["assessment_state"] = json_value(entries)
                except Exception as exc:
                    observation["capture_error"] = f"{type(exc).__name__}: {exc}"

        conversation = tuple((f"{case['id']}/{turn['id']}", turn["message"]) for turn in case["turns"])
        try:
            with patch.object(profile_module, "TurnTrace", ReviewTrace), patch.object(service, "chat_turn", observed_turn):
                episode["profile"] = await profile_module.run_profile(
                    backend, repetitions=repetitions, warmups=0, conversation=conversation)
        except Exception as exc:
            episode["error"] = f"{type(exc).__name__}: {exc}"
            episode["partial_traces"] = [trace.report() for trace in traces]
        profile = episode["profile"] or {}
        turns = profile.get("turns", [])
        failed = (episode["error"] or profile.get("error") or len(turns) != episode["expected_turns"]
                  or any(not turn.get("success") for turn in turns)
                  or len(observations) != len(turns)
                  or any(observation["capture_error"] for observation in observations))
        episode["execution"] = "failed" if failed else "completed"
        if on_progress:
            on_progress(report)
    report["execution"] = "failed" if any(case["execution"] == "failed" for case in report["cases"]) else "completed"
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    if on_progress:
        on_progress(report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("sglang", "ollama"), default="sglang")
    parser.add_argument("--case", action="append", dest="case_ids", help="Repeat to select case ids; omitted means all")
    parser.add_argument("--cases-file", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--label", help="Descriptive baseline/candidate label; does not alter configuration")
    parser.add_argument("--list-cases", action="store_true")
    parser.add_argument("--output", type=Path, help="New JSON report in an existing directory")
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.cases_file, args.case_ids)
        if args.repetitions < 1:
            raise ValueError("repetitions must be positive")
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    if args.list_cases:
        for case in cases:
            print(f"{case['id']}: {case['title']} ({len(case['turns'])} turns)")
        return 0
    if args.output is None:
        parser.error("--output is required unless --list-cases is used")
    try:
        output = args.output.open("x", encoding="utf-8")
    except OSError as exc:
        parser.error(f"output must be a new file in an existing directory: {exc}")
    report = {"schema_version": 1, "synthetic_only": True, "quality": "not_reviewed",
              "execution": "running", "cases": []}

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
            report["execution"] = "failed"
            report["error"] = f"{type(exc).__name__}: {exc}"
        save(report)
    print(f"Wrote {args.output.resolve()}; execution={report['execution']}; quality=not_reviewed")
    return 0 if report["execution"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
