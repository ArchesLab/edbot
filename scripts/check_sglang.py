#!/usr/bin/env python3
"""Check streaming and both structured outputs using synthetic inputs and server-default tool strictness."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from edbot.chat_model import create_chat_model
from edbot.interface_def import CGAOutput, UCAOutput
from edbot import model_config as config


STRUCTURED_CHECKS = (
    (UCAOutput,
     "Return a UCAOutput for concept 'recursion', with no prior assessment. "
     "Course material: a base case stops recursion; recursive calls approach that case. "
     "Question: Why is a base case needed? Rubric: explains that it stops recursion. "
     "Student answer: 'It stops recursive calls when the smallest case is reached.' "
     "Use only this evidence; select a supported tier and explain uncertainty."),
    (CGAOutput,
     "Return a CGAOutput in generate_question mode for concept 'recursion', target tier Apply, "
     "with one short_answer question, its rubric, concept tags and sources. "
     "Use only this synthetic source, titled 'Synthetic recursion note': "
     "A countdown function stops at zero and otherwise calls itself with n - 1. "
     "Ask the learner to identify the base case for that function. "
     "Keep the answer in the rubric, separate from the student-facing question."),
)


async def run_checks() -> dict:
    model = create_chat_model()
    report = {
        "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "model": config.MODEL_NAME, "tool_schema_policy": "server_default",
        "expected_server_tool_strict_level": getattr(config, "TOOL_STRICT_LEVEL", None),
        "notes": [
            "Inputs are synthetic; this does not access Edbot student state or retrieval.",
            "No per-request strict override is sent. Expected server strictness is local intent, not observed server configuration.",
            "Passing validates these samples, not assessment quality or universal schema enforcement.",
        ],
        "checks": [], "success": False,
    }
    chat = {"name": "streamed_chat", "success": False, "error": None, "response": "",
            "visible_ttft_seconds": None, "finish_reason": None}
    start = time.perf_counter()
    try:
        async for chunk in model.astream("In one sentence, explain why recursion needs a base case."):
            text = chunk.text
            if text.strip() and chat["visible_ttft_seconds"] is None:
                chat["visible_ttft_seconds"] = time.perf_counter() - start
            chat["response"] += text
            chat["finish_reason"] = chunk.response_metadata.get("finish_reason", chat["finish_reason"])
        if not chat["response"].strip():
            raise RuntimeError("The chat stream returned no visible text")
        if chat["finish_reason"] == "length":
            raise RuntimeError("The chat response reached its output limit")
        chat["success"] = True
    except Exception as exc:
        chat["error"] = f"{type(exc).__name__}: {exc}"
    chat["elapsed_seconds"] = time.perf_counter() - start
    report["checks"].append(chat)

    for schema, prompt in STRUCTURED_CHECKS:
        check = {"name": schema.__name__, "success": False, "error": None, "prompt": prompt,
                 "tool_calls": [], "invalid_tool_calls": [], "finish_reason": None}
        start = time.perf_counter()
        try:
            # Do not set strict=True here: this checks the launcher's server policy.
            response = await model.bind_tools([schema], tool_choice=schema.__name__).ainvoke(prompt)
            check["tool_calls"] = response.tool_calls
            check["invalid_tool_calls"] = response.invalid_tool_calls
            check["finish_reason"] = response.response_metadata.get("finish_reason")
            if check["finish_reason"] == "length":
                raise RuntimeError("Structured response reached its output limit")
            if (response.invalid_tool_calls or len(response.tool_calls) != 1
                    or response.tool_calls[0]["name"] != schema.__name__):
                raise RuntimeError(f"Expected exactly one valid {schema.__name__} tool call")
            parsed = schema.model_validate(response.tool_calls[0]["args"])
            if schema is UCAOutput and parsed.prior_tier is not None:
                raise ValueError("Synthetic student has no prior assessment; prior_tier must be null")
            if schema is CGAOutput and parsed.mode != "generate_question":
                raise ValueError("Expected generate_question mode for the synthetic CGA case")
            check["success"] = True
        except Exception as exc:
            check["error"] = f"{type(exc).__name__}: {exc}"
        check["elapsed_seconds"] = time.perf_counter() - start
        report["checks"].append(check)
    report["success"] = all(check["success"] for check in report["checks"])
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Save all checks to a new JSON file; existing reports are never replaced")
    args = parser.parse_args(argv)
    if args.output and (os.path.lexists(args.output) or not args.output.parent.is_dir()):
        parser.error("output must be a new file in an existing directory")
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    report = asyncio.run(run_checks())
    for check in report["checks"]:
        print(f"{check['name']}: {'OK' if check['success'] else 'FAILED'}, {check['elapsed_seconds']:.2f}s")
        if check["name"] == "streamed_chat" and check["visible_ttft_seconds"] is not None:
            print(f"  First visible text: {check['visible_ttft_seconds']:.2f}s")
        if check["error"]:
            print(f"  {check['error']}", file=sys.stderr)
    if args.output:
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2, ensure_ascii=False)
            output.write("\n")
        print(f"Wrote {args.output.resolve()}")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"SGLang smoke check failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        sys.exit(1)
