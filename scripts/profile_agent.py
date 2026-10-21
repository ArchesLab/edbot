#!/usr/bin/env python3
"""Profile synthetic conversations through the real Edbot service, with disposable state.

Run using the app environment. Start only the chat backend being measured; this
script neither launches servers nor changes the production model configuration.
"""
import argparse
import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from langchain_core.callbacks import BaseCallbackHandler
from deepagents.backends import FilesystemBackend
from edbot import model_config as config
from profile_inference import fetch_server_info, serving_configuration

CONVERSATION = (
    ("explanation", "Explain information hiding using a module that stores student records. Keep it concise."),
    ("practice", "Give me one short-answer application question about changing that module's storage implementation while preserving its public interface. Do not show the answer."),
    ("answer", "I would hide the storage representation inside the module and preserve the public operations and their behavior. Clients should not need to change when I replace the representation."),
)


class TurnTrace(BaseCallbackHandler):
    """Inclusive spans: a task tool contains its child model calls, so do not add them."""

    run_inline = True

    def __init__(self, started):
        self.started = started
        self.models = {}
        self.tools = {}

    def _start(self, spans, run_id, parent_run_id=None, name=None):
        spans[str(run_id)] = {
            "run_id": str(run_id), "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "name": name, "started_at_s": time.perf_counter() - self.started,
            "duration_s": None, "error": None,
        }

    def _end(self, spans, run_id, error=None):
        span = spans.get(str(run_id))
        if span is not None:
            span["duration_s"] = time.perf_counter() - self.started - span["started_at_s"]
            if error is not None:
                span["error"] = f"{type(error).__name__}: {error}"
        return span

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        self._start(self.models, run_id, parent_run_id, (serialized or {}).get("name"))
        self.models[str(run_id)].update(input_tokens=None, output_tokens=None, cached_input_tokens=None)

    def on_llm_new_token(self, token, *, run_id, chunk=None, **kwargs):
        # The service can reject a truncated reply as soon as its terminal chunk
        # arrives, cancelling the graph before on_llm_end. Keep that evidence.
        span = self.models.get(str(run_id))
        message = getattr(chunk, "message", None)
        metadata = getattr(message, "response_metadata", None) or {}
        reason = metadata.get("finish_reason", metadata.get("done_reason"))
        if span is not None and reason is not None:
            span["finish_reason"] = reason

    def on_llm_end(self, response, *, run_id, **kwargs):
        span = self._end(self.models, run_id)
        if span is None:
            return
        generation = next((group[0] for group in response.generations if group), None)
        message = getattr(generation, "message", None)
        usage = getattr(message, "usage_metadata", None) or {}
        metadata = getattr(message, "response_metadata", None) or {}
        fallback = (response.llm_output or {}).get("token_usage") or {}
        span["input_tokens"] = usage.get("input_tokens", fallback.get("prompt_tokens"))
        span["output_tokens"] = usage.get("output_tokens", fallback.get("completion_tokens"))
        span["cached_input_tokens"] = (usage.get("input_token_details") or {}).get("cache_read")
        span["finish_reason"] = metadata.get("finish_reason", metadata.get("done_reason")) or span.get("finish_reason")
        # Ollama reports nanoseconds; retaining these reveals reload/prefill/decode costs.
        for name in ("load_duration", "prompt_eval_duration", "eval_duration"):
            if isinstance(metadata.get(name), (int, float)):
                span[name + "_s"] = metadata[name] / 1_000_000_000

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._end(self.models, run_id, error)

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
        self._start(self.tools, run_id, parent_run_id, (serialized or {}).get("name"))

    def on_tool_end(self, output, *, run_id, **kwargs):
        self._end(self.tools, run_id)

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._end(self.tools, run_id, error)

    def report(self):
        models = list(self.models.values())
        result = {"model_call_count": len(models), "model_calls": models, "tools": list(self.tools.values())}
        for name in ("input_tokens", "output_tokens", "cached_input_tokens"):
            values = [span[name] for span in models]
            result[name] = sum(values) if values and all(value is not None for value in values) else None
        result["model_duration_sum_s"] = sum(span["duration_s"] or 0 for span in models)
        result["truncated_model_calls"] = sum(span.get("finish_reason") == "length" for span in models)
        return result


def profiling_model(backend):
    """The baseline switch exists only in this profiling process."""
    if backend == "sglang":
        from edbot.chat_model import create_chat_model
        model = create_chat_model()
        # Request terminal usage for calls that still stream. Complete responses
        # already carry usage; keep this off the per-call API kwargs.
        model.stream_usage = True
        model.temperature = 0
        return model
    if backend != "ollama":
        raise ValueError(f"Unsupported backend: {backend}")
    from langchain_ollama import ChatOllama
    return ChatOllama(
        model=config.OLLAMA_BASELINE_MODEL,
        base_url=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
        num_ctx=config.CONTEXT_LENGTH, num_predict=config.MAX_OUTPUT_TOKENS,
        reasoning=config.ENABLE_THINKING, temperature=0, keep_alive=-1,
        client_kwargs={"timeout": 120},
        profile={"max_input_tokens": config.CONTEXT_LENGTH, "max_output_tokens": config.MAX_OUTPUT_TOKENS,
                 "tool_calling": True},
    )


def summarize(turns):
    """Summarize only successful measured turns; retain errors and warmups in raw data."""
    result = {}
    for scenario in dict.fromkeys(turn["scenario"] for turn in turns):
        measured = [turn for turn in turns if turn["scenario"] == scenario and not turn["warmup"]]
        successful = [turn for turn in measured if turn["success"]]
        if not measured:
            continue
        result[scenario] = {"successful_turns": len(successful), "failed_turns": len(measured) - len(successful)}
        for key in ("total_s", "visible_ttft_s"):
            values = [turn[key] for turn in successful if turn[key] is not None]
            result[scenario][key + "_median"] = statistics.median(values) if values else None
    return result


async def run_profile(backend, repetitions=3, warmups=1, conversation=CONVERSATION):
    if repetitions < 1 or warmups < 0:
        raise ValueError("repetitions must be positive and warmups nonnegative")
    # This command is standalone. Refuse to borrow an app instance with real student state.
    from edbot import edbot_agent, service
    if any(getattr(service, name) is not None for name in ("_agent", "_conn", "_store_conn", "_store")):
        raise RuntimeError("Run the profiler in its own process; an Edbot service is already initialized")
    report = {
        "schema_version": 1, "started_at": datetime.now(timezone.utc).isoformat(), "backend": backend,
        "platform": platform.platform(), "python": platform.python_version(),
        "versions": {name: version(name) for name in ("deepagents", "langchain-core", "langchain-openai", "langchain-ollama")},
        "requested_configuration": {
            "model": config.MODEL_NAME if backend == "sglang" else config.OLLAMA_BASELINE_MODEL,
            "context_length": config.CONTEXT_LENGTH, "max_output_tokens": config.MAX_OUTPUT_TOKENS,
            "thinking": config.ENABLE_THINKING, "temperature": 0,
            "buffer_tool_responses": backend == "sglang" and config.BUFFER_TOOL_RESPONSES,
            "direct_content_delivery": config.DIRECT_CONTENT_DELIVERY,
            "reduced_tutor_harness": config.REDUCED_TUTOR_HARNESS,
            "reuse_course_evidence": config.REUSE_COURSE_EVIDENCE,
            "deterministic_assessment_save": config.DETERMINISTIC_ASSESSMENT_SAVE,
            "prefetch_assessment_prior": config.PREFETCH_ASSESSMENT_PRIOR,
            "require_content_after_assessment": config.REQUIRE_CONTENT_AFTER_ASSESSMENT,
            "serial_child_tool_calls": config.SERIAL_CHILD_TOOL_CALLS,
            "serving": serving_configuration(vars(config)) if backend == "sglang" else None,
            "sglang_stream_usage": backend == "sglang",
        },
        "notes": [
            "Local serving intent and allowlisted actual server metadata are separate; missing fields remain unverified. Observed mismatches stop generation.",
            "Startup includes real SEBook sync/embedding cache loading; it is excluded from turn timing.",
            "Student state and the agent's writable filesystem are temporary; the SEBook checkout/index cache is shared with the app.",
            "Visible TTFT includes service holdback and agent/tool work before student-visible text.",
            "Model and tool spans are inclusive and may overlap; their sums are not a latency breakdown.",
            "Unknown token counts are null. Model callbacks count logical calls, not hidden HTTP retries.",
            "Warmups are retained but excluded from medians; each repetition has fresh student state.",
            "A turn containing any output-limited model generation is excluded from successful latency summaries.",
            "Responses and agent paths can differ; compare quality, token counts, and call counts alongside latency.",
        ],
        "startup_s": None, "sebook_startup_s": None, "turns": [], "error": None, "server_info": None,
    }
    if backend == "sglang":
        report["server_info"] = await asyncio.to_thread(
            fetch_server_info, os.environ.get("EDBOT_CHAT_BASE_URL", config.BASE_URL), vars(config),
        )
        if report["server_info"]["status"] == "mismatch":
            report["error"] = "Running SGLang configuration mismatch; no benchmark requests were sent"
            report["summary"] = {}
            return report
    try:
        report["git_commit"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                              capture_output=True, check=True, timeout=5).stdout.strip()
        report["git_dirty"] = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True,
                                                   capture_output=True, check=True, timeout=5).stdout)
    except (OSError, subprocess.SubprocessError):
        report["git_commit"] = None
    real_load = edbot_agent.load_sebook_store

    def timed_load():
        started = time.perf_counter()
        try:
            return real_load()
        finally:
            report["sebook_startup_s"] = time.perf_counter() - started

    with tempfile.TemporaryDirectory(prefix="edbot-profile-") as directory, ExitStack() as patches:
        workspace = Path(directory) / "workspace"
        workspace.mkdir()
        shutil.copy2(edbot_agent.ROOT_DIR / "AGENTS.md", workspace / "AGENTS.md")
        shutil.copytree(edbot_agent.ROOT_DIR / "skills", workspace / "skills")
        patches.enter_context(patch.object(edbot_agent, "backend",
                                           FilesystemBackend(root_dir=workspace, virtual_mode=True)))
        patches.enter_context(patch.object(service, "CHECKPOINT_PATH", Path(directory) / "checkpoints.sqlite"))
        patches.enter_context(patch.object(service, "STORE_PATH", Path(directory) / "student_model.sqlite"))
        patches.enter_context(patch.object(service, "_turn_locks", {}))
        patches.enter_context(patch.object(edbot_agent, "create_chat_model", lambda: profiling_model(backend)))
        patches.enter_context(patch.object(edbot_agent, "load_sebook_store", timed_load))
        startup = time.perf_counter()
        try:
            await service.get_agent()
            report["startup_s"] = time.perf_counter() - startup
            for repetition in range(warmups + repetitions):
                student = f"profile-{uuid4()}"
                for scenario, prompt in conversation:
                    started = time.perf_counter()
                    trace = TurnTrace(started)
                    row = {"scenario": scenario, "repetition": repetition, "warmup": repetition < warmups,
                           "student_id": student, "prompt": prompt, "response": "", "visible_ttft_s": None,
                           "success": False, "error": None}
                    original_config = service.config_for

                    def traced_config(student_id):
                        return {**original_config(student_id), "callbacks": [trace]}

                    with patch.object(service, "config_for", traced_config):
                        async for event in service.chat_turn(student, prompt):
                            if event.type == "text" and event.text:
                                if row["visible_ttft_s"] is None and event.text.strip():
                                    row["visible_ttft_s"] = time.perf_counter() - started
                                row["response"] += event.text
                            elif event.type == "error":
                                row["error"] = event.message
                            elif event.type == "done":
                                row["success"] = True
                    row["total_s"] = time.perf_counter() - started
                    row["metrics"] = trace.report()
                    if not row["response"].strip() and row["success"]:
                        row.update(success=False, error="Turn completed without visible text")
                    if row["metrics"]["truncated_model_calls"]:
                        row["success"] = False
                        row["error"] = row["error"] or "At least one model generation reached its output limit"
                    report["turns"].append(row)
                    print(f"{'warmup' if row['warmup'] else 'measured'} {scenario}: {row['total_s']:.2f}s, "
                          f"{row['metrics']['model_call_count']} model calls, success={row['success']}", file=sys.stderr)
                    if not row["success"]:
                        break  # Later turns depend on the previous conversation succeeding.
        except Exception as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if report["startup_s"] is None:
                report["startup_s"] = time.perf_counter() - startup
            await service.close()
    report["summary"] = summarize(report["turns"])
    return report


def write_report(path, report):
    with Path(path).open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, ensure_ascii=False)
        output.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("sglang", "ollama"), default="sglang")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True, help="New JSON result path; existing files are never replaced")
    args = parser.parse_args()
    if args.repetitions < 1 or args.warmups < 0:
        parser.error("repetitions must be positive and warmups nonnegative")
    if args.output.exists() or not args.output.parent.is_dir():
        parser.error("output must be a new file in an existing directory")
    # Keep synthetic traces local even when the app's .env normally enables LangSmith.
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    report = asyncio.run(run_profile(args.backend, args.repetitions, args.warmups))
    write_report(args.output, report)
    print(f"Wrote {args.output.resolve()}")
    if report["error"] or any(not turn["success"] for turn in report["turns"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
