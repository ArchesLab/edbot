#!/usr/bin/env python3
"""Probe parent-prefix retention on the currently configured SGLang server.

Compare A -> A-extension with A -> B -> A-extension using synthetic prompts.
Optional rounds extend each branch before returning to the parent prefix.
This standard-library script never changes serving settings or starts services.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_inference import CONFIG, NOTES, fetch_server_info, positive_int, run_request, serving_configuration


# Approximately 8K parent and 6K child tokens with the selected tokenizer. Only
# server-reported usage below is an actual token count. The distinct system
# prefixes mimic switching agent roles without using any real student content.
PARENT = [
    {"role": "system", "content": "Parent tutor cache probe. Read these synthetic course notes.\n\n"
     + NOTES * 80 + "\nFor every request, respond with exactly ACK and nothing else."},
    {"role": "user", "content": "Acknowledge the notes."},
]
CHILD = [
    {"role": "system", "content": "Child content tutor cache probe. Read these synthetic course notes.\n\n"
     + NOTES * 56 + "\nFor every request, respond with exactly ACK and nothing else."},
    {"role": "user", "content": "Acknowledge the notes independently."},
]
# The transcript is predetermined. Never substitute a sampled result from A:
# doing so would change the measured extension between paired sequences.
PARENT_EXTENSION = PARENT + [
    {"role": "assistant", "content": "ACK"},
    {"role": "user", "content": "Keep the same notes in mind and acknowledge this follow-up."},
]
SEQUENCES = {
    "parent_only": (("parent", PARENT), ("parent_extension", PARENT_EXTENSION)),
    "interleaved_child": (("parent", PARENT), ("child", CHILD), ("parent_extension", PARENT_EXTENSION)),
}
SUMMARY_METRICS = ("elapsed_seconds", "ttft_visible_seconds", "prompt_tokens", "cached_prompt_tokens")


def build_sequences(parent_rounds, child_rounds):
    """Build fixed transcripts shared by both conditions, never sampled outputs.

    The longer variant approximates parent prompts of 8K, 8.8K, 8.9K, then
    9.5K tokens and child prompts of 5.7K, 7.7K, 9.7K, then 11.7K tokens.
    Default rounds retain the original probe's messages byte for byte.
    """
    parents = [("parent", PARENT)]
    for round_number in range(2, parent_rounds + 1):
        extra_notes = NOTES * (7 if round_number == 2 else 1)
        messages = parents[-1][1] + [
            {"role": "assistant", "content": "ACK"},
            {"role": "user", "content": "Read these additional parent notes.\n\n" + extra_notes
             + "\nAcknowledge the accumulated notes."},
        ]
        parents.append((f"parent_round_{round_number}", messages))
    if parent_rounds == 1:
        extension = PARENT_EXTENSION
    else:
        extension = parents[-1][1] + [
            {"role": "assistant", "content": "ACK"},
            {"role": "user", "content": "Read these final parent notes.\n\n" + NOTES * 5
             + "\nKeep all notes in mind and acknowledge this follow-up."},
        ]
    children = [("child", CHILD)]
    for round_number in range(2, child_rounds + 1):
        messages = children[-1][1] + [
            {"role": "assistant", "content": "ACK"},
            {"role": "user", "content": "Read these additional child notes.\n\n" + NOTES * 20
             + "\nAcknowledge the accumulated notes independently."},
        ]
        children.append((f"child_round_{round_number}", messages))
    final = [("parent_extension", extension)]
    return {"parent_only": tuple(parents + final),
            "interleaved_child": tuple(parents + children + final)}


def payload_hash(payload):
    """Hash canonical JSON, independent of dictionary insertion order."""
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def request_payload(messages, max_tokens, cache_salt):
    """Record the synthetic payload sent by profile_inference.run_request.

    The HTTP-fixture test compares this record with the actual wire payload so
    changes to the shared helper cannot silently invalidate reproduction hashes.
    """
    return {
        "model": CONFIG["MODEL_NAME"], "messages": messages, "stream": True,
        "max_tokens": max_tokens, "temperature": 0, "seed": 42,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": CONFIG["ENABLE_THINKING"]},
        "return_spec_tokens_details": True, "cache_salt": cache_salt,
    }


def summarize(sequences):
    """Summarize extensions only when every request in their sequence succeeded."""
    result = {}
    for condition in SEQUENCES:
        selected = [sequence for sequence in sequences if sequence["condition"] == condition]
        successful = [sequence["requests"][-1] for sequence in selected if sequence["success"]]
        medians, counts = {}, {}
        for metric in SUMMARY_METRICS:
            values = [row[metric] for row in successful if isinstance(row.get(metric), (int, float))]
            medians[metric] = statistics.median(values) if values else None
            counts[metric] = len(values)
        result[condition] = {"successful_sequences": len(successful),
                             "failed_sequences": len(selected) - len(successful),
                             "medians": medians, "metric_sample_counts": counts}
    return result


def paired_differences(sequences):
    """Missing counts stay unknown; positive cached-token loss favors the control."""
    result = []
    for repetition in sorted({sequence["repetition"] for sequence in sequences}):
        pair = {sequence["condition"]: sequence for sequence in sequences
                if sequence["repetition"] == repetition and sequence["success"]}
        if len(pair) != 2:
            continue
        control = pair["parent_only"]["requests"][-1]
        interleaved = pair["interleaved_child"]["requests"][-1]
        row = {"repetition": repetition}
        for metric, name, sign in (
            ("cached_prompt_tokens", "cached_tokens_lost_after_child", -1),
            ("elapsed_seconds", "extension_elapsed_increase_seconds", 1),
            ("ttft_visible_seconds", "extension_ttft_increase_seconds", 1),
        ):
            left, right = control.get(metric), interleaved.get(metric)
            row[name] = sign * (right - left) if left is not None and right is not None else None
        result.append(row)
    return result


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects even a report created after main's preflight.
    with path.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, ensure_ascii=False)
        output.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("EDBOT_CHAT_BASE_URL", CONFIG["BASE_URL"]),
                        help="SGLang endpoint including /v1 (default: shared configuration)")
    parser.add_argument("--repetitions", type=positive_int, default=3)
    parser.add_argument("--parent-rounds", type=int, choices=(1, 2, 3), default=1,
                        help="Parent requests before the final extension (default: 1)")
    parser.add_argument("--child-rounds", type=int, choices=(1, 2, 3, 4), default=1,
                        help="Intervening requests extending the child branch (default: 1)")
    parser.add_argument("--max-tokens", type=int, choices=(16, 32), default=16)
    parser.add_argument("--timeout", type=positive_int, default=120)
    parser.add_argument("--output", type=Path, help="New JSON report path; otherwise write to stdout")
    args = parser.parse_args(argv)
    if args.output and os.path.lexists(args.output):
        parser.error(f"Output already exists: {args.output}; choose a new report filename")
    base_url = args.base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        parser.error("SGLang base URL must include /v1")
    sequences = build_sequences(args.parent_rounds, args.child_rounds)
    report = {
        "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "synthetic_parent_child_prefix_retention", "base_url": base_url,
        "settings": {"repetitions": args.repetitions, "max_tokens": args.max_tokens,
                     "parent_rounds": args.parent_rounds, "child_rounds": args.child_rounds,
                     "temperature": 0, "seed": 42, "thinking": CONFIG["ENABLE_THINKING"],
                     "timeout_seconds": args.timeout},
        "serving_config": serving_configuration(), "server_info": fetch_server_info(base_url),
        "notes": [
            "Synthetic prompts only. No student conversations, retrieval, or app state are accessed.",
            "A-extension is predetermined and identical across comparisons; sampled A output is never reused.",
            "Every parent request is identical across paired conditions apart from cache_salt. Branch extensions use fixed ACKs and provided notes.",
            "prompt_sha256 hashes message JSON; prefix_prompt_sha256 hashes the preceding request's complete messages within the same role.",
            "Each sequence has a unique cache_salt, shared by every request in that sequence. No shared cache is flushed.",
            "Pair order alternates per repetition. All repetitions are retained; the first can include kernel warmup effects.",
            "Prompt sizes are approximate; prompt_tokens and cached_prompt_tokens come from API usage, not local estimates.",
            "Missing cache counts remain null. Failed or truncated priming invalidates the complete sequence for summaries.",
            "TTFT measures first non-whitespace text. Small output limits can truncate; inspect every status and finish reason.",
            "Observed configuration is allowlisted separately from local intent; mismatches stop inference, absent fields stay unverified.",
            "A lower cache hit after B demonstrates lost reuse; it does not identify Mamba eviction as the cause.",
            "Salted sequences still consume shared capacity. Record other workloads; this probe is not a complete-agent benchmark.",
        ],
        "sequences": [], "error": None,
    }
    failed = report["server_info"]["status"] == "mismatch"
    if failed:
        report["error"] = "Running SGLang configuration mismatch; no benchmark requests were sent"
    else:
        for repetition in range(args.repetitions):
            conditions = list(sequences)
            if repetition % 2:
                conditions.reverse()
            for condition in conditions:
                sequence = {"repetition": repetition + 1, "condition": condition,
                            "cache_salt": str(uuid4()), "requests": [], "success": True}
                for stage, messages in sequences[condition]:
                    print(f"Pair {repetition + 1}/{args.repetitions}: {condition} / {stage}",
                          file=sys.stderr, flush=True)
                    payload = request_payload(messages, args.max_tokens, sequence["cache_salt"])
                    row = run_request("sglang", base_url, CONFIG["MODEL_NAME"], messages, args.max_tokens,
                                      CONFIG["ENABLE_THINKING"], args.timeout, cache_salt=sequence["cache_salt"])
                    row.update(stage=stage, payload=payload, payload_sha256=payload_hash(payload),
                               unsalted_payload_sha256=payload_hash({key: value for key, value in payload.items()
                                                                    if key != "cache_salt"}),
                               prompt_sha256=payload_hash(messages),
                               prefix_message_count=len(messages) - 2,
                               prefix_prompt_sha256=payload_hash(messages[:-2]) if len(messages) > 2 else None)
                    sequence["requests"].append(row)
                    sequence["success"] &= row["status"] == "ok"
                report["sequences"].append(sequence)
                failed |= not sequence["success"]
    report["summary"] = summarize(report["sequences"])
    report["paired_differences"] = paired_differences(report["sequences"])
    if args.output:
        write_report(args.output, report)
        print(f"Saved {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
