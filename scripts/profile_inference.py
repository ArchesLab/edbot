#!/usr/bin/env python3
"""Compare model-level streaming latency; requires only the Python standard library.

This sends synthetic prompts to an already running Ollama or SGLang server. It
never starts/stops servers, unloads models, or claims a first request is cold.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import runpy
import statistics
import sys
import time
import urllib.request
import urllib.error
import uuid


CONFIG = runpy.run_path(Path(__file__).resolve().parents[1] / "src/edbot/model_config.py")
SYSTEM = "You are a computer science tutor. Answer clearly and accurately in at most 150 words."
NOTES = """A queue is first-in, first-out. A stack is last-in, first-out.
An array-backed queue can use a circular buffer with head and tail indices.
A producer adds work while a consumer removes work. A bounded queue has finite capacity.
When a bounded queue is full, adding an item requires an explicit policy such as blocking
the producer, rejecting the item, or dropping an older item. These policies have different
consequences for reliability. Concurrent updates require appropriate synchronization.
"""
PROMPTS = {
    "short": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "Explain why a queue is useful for handling incoming print jobs. "
         "Give one concrete example and one limitation."},
    ],
    "long": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "Use the following course notes.\n\n" + NOTES * 64
         + "\nExplain why a bounded queue can help a web server handle a burst of requests. "
         "Describe what should happen when the queue is full and justify your policy."},
    ],
}
METRICS = (
    "ttft_visible_seconds", "elapsed_seconds", "prompt_tokens", "cached_prompt_tokens", "completion_tokens",
    "completion_tokens_per_elapsed_second", "load_seconds", "prompt_eval_seconds",
    "decode_seconds", "server_prompt_tokens_per_second", "server_decode_tokens_per_second",
)


def serving_configuration(configuration=CONFIG):
    """Serializable local intent, including which kind of speculation is selected."""
    keys = ("MODEL_PRESET", "MODEL_NAME", "MODEL_PATH", "MODEL_REVISION", "DRAFT_MODEL_PATH",
            "DRAFT_MODEL_REVISION", "SGLANG_VERSION", "SGLANG_SOURCE_REVISION",
            "FLASHINFER_VERSION", "FLASHINFER_CACHE_PACKAGE", "ENABLE_SPECULATION",
            "SPECULATIVE_ALGORITHM", "MEM_FRACTION_STATIC", "MAX_RUNNING_REQUESTS", "MAX_TOTAL_TOKENS", "CONTEXT_LENGTH",
            "CHUNKED_PREFILL_SIZE", "KV_CACHE_DTYPE", "MAMBA_RADIX_CACHE_STRATEGY",
            "MAMBA_CACHE_SLOTS_PER_REQUEST", "ENABLE_THINKING", "COMPILER_JOBS", "TOOL_STRICT_LEVEL")
    result = {key: configuration.get(key) for key in keys}
    result["ACTIVE_SPECULATIVE_ALGORITHM"] = (result["SPECULATIVE_ALGORITHM"]
                                                if result["ENABLE_SPECULATION"] else None)
    result["MAMBA_SSM_DTYPE"] = "float32"
    result["PLE_OFFLOAD_BACKEND"] = "file" if result["MODEL_PRESET"] == "flash-next" else None
    result["PLE_DIRECTORY_POLICY"] = "fresh owned directory per launch" if result["PLE_OFFLOAD_BACKEND"] else None
    return result


def fetch_server_info(base_url, configuration=CONFIG, timeout=5):
    """Read only an allowlist of startup settings and current model identity.

    SGLang's full server_info contains its launch command and can contain keys.
    Never save that full payload. Missing endpoints are explicit unverified data;
    contradictory observed values are a benchmark-blocking mismatch.
    """
    root = base_url.rstrip("/").removesuffix("/v1")
    result = {"status": "unavailable", "observed": {}, "mismatches": [], "missing_fields": [], "error": None}

    def read(endpoint):
        request = urllib.request.Request(root + endpoint, headers={
            "Authorization": "Bearer " + os.environ.get("EDBOT_CHAT_API_KEY", "sglang-local"),
        })
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(1_048_577)
        if len(data) > 1_048_576:
            raise ValueError("Server metadata exceeded the 1 MiB limit")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("Server metadata was not a JSON object")
        return value

    try:
        try:
            raw = read("/server_info")
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            raw = read("/get_server_info")
        arguments = {**raw, **raw.get("server_args", {})} if isinstance(raw.get("server_args"), dict) else raw
        allowed = {
            "model_path", "revision", "served_model_name", "version", "context_length",
            "speculative_algorithm", "speculative_num_steps", "speculative_eagle_topk",
            "speculative_num_draft_tokens", "speculative_dspark_block_size",
            "speculative_draft_model_path", "speculative_draft_model_revision", "kv_cache_dtype",
            "mamba_ssm_dtype", "mamba_radix_cache_strategy", "max_mamba_cache_size",
            "mem_fraction_static", "max_running_requests", "max_total_tokens", "chunked_prefill_size", "page_size",
            "moe_runner_backend", "fp4_gemm_runner_backend", "attention_backend",
            "ple_offload_embedding", "ple_offload_backend", "cuda_graph_max_bs_decode", "cuda_graph_max_bs",
            "enable_cache_report",
        }
        observed = {key: value for key, value in arguments.items() if key in allowed}
        result["observed"] = observed
        try:
            live = read("/model_info")
            result["live_model"] = {key: live[key] for key in ("model_path", "served_model_name") if key in live}
            observed.update(result["live_model"])
        except (OSError, ValueError, TypeError) as error:
            result["live_model_error"] = f"{type(error).__name__}: {error}"
        expected = {
            "model_path": configuration["MODEL_PATH"], "revision": configuration["MODEL_REVISION"],
            "served_model_name": configuration["MODEL_NAME"], "version": configuration["SGLANG_VERSION"],
            "context_length": configuration["CONTEXT_LENGTH"], "mem_fraction_static": configuration["MEM_FRACTION_STATIC"],
            "max_running_requests": configuration["MAX_RUNNING_REQUESTS"],
            "chunked_prefill_size": configuration["CHUNKED_PREFILL_SIZE"], "mamba_ssm_dtype": "float32",
            "mamba_radix_cache_strategy": configuration["MAMBA_RADIX_CACHE_STRATEGY"],
            "max_mamba_cache_size": configuration["MAMBA_CACHE_SLOTS_PER_REQUEST"] * configuration["MAX_RUNNING_REQUESTS"],
            "speculative_algorithm": configuration["SPECULATIVE_ALGORITHM"] if configuration["ENABLE_SPECULATION"] else None,
        }
        if configuration["KV_CACHE_DTYPE"] != "auto":
            expected["kv_cache_dtype"] = configuration["KV_CACHE_DTYPE"]
        if configuration.get("MAX_TOTAL_TOKENS") is not None:
            expected["max_total_tokens"] = configuration["MAX_TOTAL_TOKENS"]
        if configuration["MODEL_PRESET"] == "flash-next":
            expected.update(ple_offload_embedding=True, ple_offload_backend="file", page_size=64,
                            moe_runner_backend="flashinfer_cutlass", fp4_gemm_runner_backend="flashinfer_cutlass")
        if configuration["ENABLE_SPECULATION"]:
            native = configuration["SPECULATIVE_ALGORITHM"] == "NEXTN"
            expected.update(
                speculative_num_steps=3 if native else 1, speculative_eagle_topk=1,
                speculative_draft_model_path=configuration["MODEL_PATH"] if native else configuration["DRAFT_MODEL_PATH"],
                speculative_draft_model_revision=configuration["MODEL_REVISION"] if native else configuration["DRAFT_MODEL_REVISION"],
            )
            expected["speculative_num_draft_tokens" if native else "speculative_dspark_block_size"] = 4 if native else 7
        for key, value in expected.items():
            if key not in observed:
                result["missing_fields"].append(key)
                continue
            actual = observed[key]
            # Qwen NEXTN is normalized to EAGLE by SGLang's argument resolver.
            if key == "speculative_algorithm" and value == "NEXTN" and actual == "EAGLE":
                continue
            if actual != value:
                result["mismatches"].append({"field": key, "expected": value, "observed": actual})
        result["status"] = ("mismatch" if result["mismatches"] else "partial"
                            if result["missing_fields"] or result.get("live_model_error") else "verified")
    except (OSError, ValueError, TypeError) as error:
        result["error"] = f"{type(error).__name__}: {error}"
    return result


def _records(response, backend):
    if backend == "ollama":
        for line in response:
            if line.strip():
                yield json.loads(line)
        return
    data = []
    for raw in response:
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line and data:
            value = "\n".join(data)
            data = []
            yield {"_stream_done": True} if value == "[DONE]" else json.loads(value)
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
    if data:
        value = "\n".join(data)
        yield {"_stream_done": True} if value == "[DONE]" else json.loads(value)


def _rate(count, seconds):
    return count / seconds if isinstance(count, (int, float)) and seconds and seconds > 0 else None


def run_request(backend, base_url, model, messages, max_tokens, thinking, timeout, cache_salt=None):
    """Measure one stream; errors retain partial output and never become successful runs."""
    if cache_salt is not None and backend != "sglang":
        raise ValueError("Cache isolation requires SGLang")
    if backend == "ollama":
        url = base_url.rstrip("/") + "/api/chat"
        payload = {
            "model": model, "messages": messages, "stream": True, "think": thinking,
            "options": {"num_ctx": CONFIG["CONTEXT_LENGTH"], "num_predict": max_tokens,
                        "temperature": 0, "seed": 42},
        }
    elif backend == "sglang":
        url = base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": model, "messages": messages, "stream": True, "max_tokens": max_tokens,
            "temperature": 0, "seed": 42, "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": thinking},
            "return_spec_tokens_details": True,
        }
        if cache_salt is not None:
            payload["cache_salt"] = cache_salt
    else:
        raise ValueError(f"Unknown backend: {backend}")
    headers = {"Content-Type": "application/json"}
    if backend == "sglang":
        headers["Authorization"] = "Bearer " + os.environ.get("EDBOT_CHAT_API_KEY", "sglang-local")
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    result = {name: None for name in METRICS}
    result.update(status="error", output_text="", reasoning_characters=0, raw_metadata={}, error=None,
                  cache_salt=cache_salt)
    finished = False
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for record in _records(response, backend):
                elapsed = time.perf_counter() - started
                if elapsed > timeout:
                    raise TimeoutError(f"Stream exceeded the {timeout:g}-second run limit")
                if record.get("error"):
                    raise RuntimeError(str(record["error"]))
                result["raw_metadata"].update({key: value for key, value in record.items()
                                               if key not in {"message", "choices", "_stream_done"}})
                if backend == "ollama":
                    delta = record.get("message") or {}
                    reasoning = delta.get("thinking") or ""
                    finished = bool(record.get("done"))
                    result["finish_reason"] = record.get("done_reason", result.get("finish_reason"))
                else:
                    choices = record.get("choices") or []
                    delta = choices[0].get("delta", {}) if choices else {}
                    reasoning = delta.get("reasoning_content") or ""
                    finished = bool(record.get("_stream_done"))
                    if choices and choices[0].get("finish_reason") is not None:
                        result["finish_reason"] = choices[0]["finish_reason"]
                content = delta.get("content") or ""
                if content.strip() and result["ttft_visible_seconds"] is None:
                    result["ttft_visible_seconds"] = elapsed
                result["output_text"] += content
                result["reasoning_characters"] += len(reasoning)
                if finished:
                    break
        if not finished:
            raise RuntimeError("Incomplete stream: no successful terminal marker received")
        if result["ttft_visible_seconds"] is None:
            raise RuntimeError("Stream completed without visible answer text")
        if result.get("finish_reason") == "length":
            result["status"] = "truncated"
            result["error"] = "Output reached the token limit; exclude from successful completion medians"
        else:
            result["status"] = "ok"
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    result["elapsed_seconds"] = time.perf_counter() - started
    metadata = result["raw_metadata"]
    if backend == "ollama":
        result["prompt_tokens"] = metadata.get("prompt_eval_count")
        result["completion_tokens"] = metadata.get("eval_count")
        for target, source in (("load_seconds", "load_duration"),
                               ("prompt_eval_seconds", "prompt_eval_duration"),
                               ("decode_seconds", "eval_duration")):
            if isinstance(metadata.get(source), (int, float)):
                result[target] = metadata[source] / 1_000_000_000
        result["server_prompt_tokens_per_second"] = _rate(result["prompt_tokens"], result["prompt_eval_seconds"])
        result["server_decode_tokens_per_second"] = _rate(result["completion_tokens"], result["decode_seconds"])
    else:
        usage = metadata.get("usage") or {}
        result["prompt_tokens"] = usage.get("prompt_tokens")
        result["cached_prompt_tokens"] = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
        result["completion_tokens"] = usage.get("completion_tokens")
    result["completion_tokens_per_elapsed_second"] = _rate(result["completion_tokens"], result["elapsed_seconds"])
    return result


def summarize(runs):
    warm = [run for run in runs if run["phase"] == "warm"]
    successful = [run for run in warm if run["status"] == "ok"]
    medians = {}
    samples = {}
    for metric in METRICS:
        values = [run[metric] for run in successful if isinstance(run.get(metric), (int, float))]
        medians[metric] = statistics.median(values) if values else None
        samples[metric] = len(values)
    return {"successful_warm_runs": len(successful), "failed_warm_runs": len(warm) - len(successful),
            "medians": medians, "metric_sample_counts": samples}


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("ollama", "sglang"), required=True)
    parser.add_argument("--base-url", help="Override backend URL; SGLang URL must include /v1")
    parser.add_argument("--prompt", choices=(*PROMPTS, "all"), default="all")
    parser.add_argument("--cache-mode", choices=("reuse", "isolated"), default="reuse",
                        help="Reuse prefixes, or isolate every request with a fresh SGLang cache salt")
    parser.add_argument("--repeats", type=positive_int, default=3, help="Measured warm runs per prompt (default: 3)")
    parser.add_argument("--warmups", type=positive_int, default=1,
                        help="Unmeasured runs per prompt, including the initial request (default: 1)")
    parser.add_argument("--max-tokens", type=positive_int, default=min(256, CONFIG["MAX_OUTPUT_TOKENS"]))
    parser.add_argument("--thinking", choices=("on", "off"),
                        default="on" if CONFIG["ENABLE_THINKING"] else "off")
    parser.add_argument("--timeout", type=positive_int, default=120, help="Seconds per request/stream (default: 120)")
    parser.add_argument("--output", type=Path, help="Write JSON here instead of stdout")
    args = parser.parse_args(argv)
    if args.cache_mode == "isolated" and args.backend != "sglang":
        parser.error("--cache-mode isolated requires SGLang")
    if args.max_tokens >= CONFIG["CONTEXT_LENGTH"]:
        parser.error("--max-tokens must be smaller than the configured context window")
    if args.output and os.path.lexists(args.output):
        parser.error(f"Output already exists: {args.output}; choose a new report filename")
    model = CONFIG["MODEL_NAME"] if args.backend == "sglang" else CONFIG["OLLAMA_BASELINE_MODEL"]
    base_url = args.base_url or (os.environ.get("EDBOT_CHAT_BASE_URL", CONFIG["BASE_URL"])
                                 if args.backend == "sglang" else "http://127.0.0.1:11434")
    report = {
        "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "model_stream_only", "backend": args.backend, "base_url": base_url, "model": model,
        "settings": {"max_tokens": args.max_tokens, "thinking": args.thinking == "on", "temperature": 0,
                     "seed": 42, "context_length": CONFIG["CONTEXT_LENGTH"], "warmups": args.warmups,
                     "repeats": args.repeats, "timeout_seconds": args.timeout, "cache_mode": args.cache_mode,
                     "cache_condition": ("resident_model_prefix_miss" if args.cache_mode == "isolated"
                                         else "prefix_reuse_permitted")},
        "serving_config": serving_configuration() if args.backend == "sglang" else None,
        "server_info": fetch_server_info(base_url) if args.backend == "sglang" else None,
        "error": None,
        "notes": [
            "Initial requests are separated, but are not necessarily cold: residency and prefix cache state are unknown.",
            ("Isolated runs use a fresh cache_salt per request: resident-model prefix misses, not cold model loads. Warm refers to model/kernel warmup, not prefix reuse. No shared caches are flushed."
             if args.cache_mode == "isolated" else
             "Warm runs reuse each prompt, so prefix caching may contribute. No cache flush, unload, or server restart is performed."),
            "TTFT starts at the HTTP request and ends at the first non-whitespace answer text; reasoning is excluded.",
            "Completion tokens can include reasoning. Completion tokens per elapsed second includes load/prefill/network time; it is not decode throughput.",
            "Usage and server timings are nullable when omitted. Medians exclude failed, truncated, and warmup runs; sample counts show missing metrics.",
            "Local serving intent and allowlisted actual server metadata are separate; missing fields remain unverified. Observed mismatches stop generation. Record other GPU workloads separately.",
            "Equal output budgets do not guarantee equal output lengths or quality. This does not measure retrieval, agent loops, or complete Edbot replies.",
        ],
        "cases": {},
    }
    phases = ["initial"] + ["warmup"] * (args.warmups - 1) + ["warm"] * args.repeats
    names = list(PROMPTS) if args.prompt == "all" else [args.prompt]
    failed = bool(report["server_info"] and report["server_info"]["status"] == "mismatch")
    if failed:
        report["error"] = "Running SGLang configuration mismatch; no benchmark requests were sent"
        names = []
    for name in names:
        messages = PROMPTS[name]
        runs = []
        for index, phase in enumerate(phases, 1):
            print(f"{args.backend} {name}: {phase} {index}/{len(phases)}", file=sys.stderr, flush=True)
            result = run_request(args.backend, base_url, model, messages, args.max_tokens,
                                 args.thinking == "on", args.timeout,
                                 cache_salt=str(uuid.uuid4()) if args.cache_mode == "isolated" else None)
            result.update(phase=phase, index=index)
            runs.append(result)
            failed |= result["status"] != "ok"
        report["cases"][name] = {"messages": messages,
                                  "prompt_sha256": hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest(),
                                  "runs": runs, "summary": summarize(runs)}
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also protects a report created after the initial preflight.
        with args.output.open("x", encoding="utf-8") as output:
            output.write(encoded)
        print(f"Saved {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(encoded)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
