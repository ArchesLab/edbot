"""Contracts for the standalone model-level profiling harness."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "profile_inference.py"


def load_profiler():
    spec = importlib.util.spec_from_file_location("edbot_profiling", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProfilingTests(unittest.TestCase):
    def setUp(self):
        self.profiler = load_profiler()

    def test_ollama_ttft_excludes_thinking_and_preserves_server_timings(self):
        stream = b"\n".join(json.dumps(record).encode() for record in [
            {"message": {"thinking": "private reasoning", "content": ""}, "done": False},
            {"message": {"content": "FIFO"}, "done": False},
            {"done": True, "done_reason": "stop", "load_duration": 100_000_000,
             "prompt_eval_duration": 200_000_000, "prompt_eval_count": 10,
             "eval_duration": 400_000_000, "eval_count": 8},
        ])
        with patch.object(self.profiler.urllib.request, "urlopen", return_value=io.BytesIO(stream)) as http:
            with patch.object(self.profiler.time, "perf_counter", side_effect=[0, 1, 2, 3, 4]):
                result = self.profiler.run_request("ollama", "http://localhost:11434", "baseline",
                                                   [{"role": "user", "content": "Test"}], 64, False, 30)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["ttft_visible_seconds"], 2)
        self.assertEqual(result["elapsed_seconds"], 4)
        self.assertEqual(result["output_text"], "FIFO")
        self.assertEqual(result["load_seconds"], 0.1)
        self.assertEqual(result["server_decode_tokens_per_second"], 20)
        self.assertEqual(result["raw_metadata"]["eval_count"], 8)
        request = http.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:11434/api/chat")
        payload = json.loads(request.data)
        self.assertFalse(payload["think"])
        self.assertEqual(payload["options"]["num_predict"], 64)
        self.assertNotIn("return_spec_tokens_details", payload)

    def test_sglang_sse_usage_is_optional_and_truncated_stream_fails(self):
        records = [
            {"choices": [{"delta": {"reasoning_content": "thinking"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "FIFO"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ]
        for usage in (None, {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14}):
            with self.subTest(usage=usage):
                data = list(records)
                if usage is not None:
                    data.append({"choices": [], "usage": usage})
                stream = ("".join(f"data: {json.dumps(item)}\n\n" for item in data) + "data: [DONE]\n\n").encode()
                with patch.object(self.profiler.urllib.request, "urlopen", return_value=io.BytesIO(stream)) as http:
                    result = self.profiler.run_request("sglang", "http://localhost:30000/v1", "optimized",
                                                       [{"role": "user", "content": "Test"}], 64, False, 30)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["completion_tokens"], None if usage is None else 2)
                self.assertIsNone(result["server_decode_tokens_per_second"])
                request = http.call_args.args[0]
                self.assertEqual(request.full_url, "http://localhost:30000/v1/chat/completions")
                self.assertEqual(json.loads(request.data)["chat_template_kwargs"], {"enable_thinking": False})

        incomplete = f"data: {json.dumps(records[1])}\n\n".encode()
        with patch.object(self.profiler.urllib.request, "urlopen", return_value=io.BytesIO(incomplete)):
            result = self.profiler.run_request("sglang", "http://localhost:30000/v1", "optimized", [], 64, False, 30)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["output_text"], "FIFO")
        self.assertIn("incomplete", result["error"].lower())

    def test_summary_excludes_initial_warmup_and_failed_runs(self):
        runs = [
            {"phase": "initial", "status": "ok", "elapsed_seconds": 100},
            {"phase": "warmup", "status": "ok", "elapsed_seconds": 50},
            {"phase": "warm", "status": "ok", "elapsed_seconds": 2, "ttft_visible_seconds": 0.2},
            {"phase": "warm", "status": "ok", "elapsed_seconds": 4, "ttft_visible_seconds": 0.4},
            {"phase": "warm", "status": "error", "elapsed_seconds": 90, "ttft_visible_seconds": 0.1},
        ]
        result = self.profiler.summarize(runs)
        self.assertEqual(result["successful_warm_runs"], 2)
        self.assertEqual(result["failed_warm_runs"], 1)
        self.assertEqual(result["medians"]["elapsed_seconds"], 3)
        self.assertAlmostEqual(result["medians"]["ttft_visible_seconds"], 0.3)
        self.assertIsNone(result["medians"]["server_decode_tokens_per_second"])

    def test_sglang_requests_and_preserves_terminal_speculation_details(self):
        details = {"spec_accept_rate": 0.75, "spec_accept_length": 3.25,
                   "spec_verify_ct": 4, "spec_num_correct_drafts": 9,
                   "spec_num_proposed_drafts": 12}
        records = [
            {"choices": [{"delta": {"content": "FIFO"}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 13},
             "sglext": {"spec_tokens_details": details}},
        ]
        stream = ("".join(f"data: {json.dumps(record)}\n\n" for record in records) + "data: [DONE]\n\n").encode()
        with patch.object(self.profiler.urllib.request, "urlopen", return_value=io.BytesIO(stream)) as http:
            result = self.profiler.run_request("sglang", "http://localhost:30000/v1", "test", [], 64, False, 30)
        self.assertIs(json.loads(http.call_args.args[0].data)["return_spec_tokens_details"], True)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["raw_metadata"]["sglext"]["spec_tokens_details"], details)
        self.assertEqual(result["completion_tokens"], 13)

    def test_optional_cached_prompt_counts_preserve_zero_and_ignore_missing_values_in_medians(self):
        runs = []
        for cached in (None, 0, 8):
            usage = {"prompt_tokens": 12, "completion_tokens": 2}
            if cached is not None:
                usage["prompt_tokens_details"] = {"cached_tokens": cached}
            stream = ("data: " + json.dumps({"choices": [{"delta": {"content": "FIFO"}, "finish_reason": "stop"}],
                                              "usage": usage}) + "\n\ndata: [DONE]\n\n").encode()
            with patch.object(self.profiler.urllib.request, "urlopen", return_value=io.BytesIO(stream)):
                result = self.profiler.run_request("sglang", "http://localhost:30000/v1", "test", [], 64, False, 30)
            self.assertEqual(result["cached_prompt_tokens"], cached)
            result["phase"] = "warm"
            runs.append(result)
        summary = self.profiler.summarize(runs)
        self.assertEqual(summary["medians"]["cached_prompt_tokens"], 4)
        self.assertEqual(summary["metric_sample_counts"]["cached_prompt_tokens"], 2)

    def test_cli_uses_matching_prompts_and_reports_failures_with_nonzero_exit(self):
        payloads = {}
        streams = {
            "ollama": b'{"message":{"content":"FIFO"},"done":true}\n',
            "sglang": b'data: {"choices":[{"delta":{"content":"FIFO"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        }
        for backend, stream in streams.items():
            with self.subTest(backend=backend):
                output = io.StringIO()
                with patch.object(self.profiler, "fetch_server_info", return_value={"status": "unavailable"}), \
                        patch.object(self.profiler.urllib.request, "urlopen",
                                  side_effect=[io.BytesIO(stream), io.BytesIO(stream), io.BytesIO(b"")]) as http:
                    with patch("sys.stdout", output), patch("sys.stderr", io.StringIO()):
                        status = self.profiler.main(["--backend", backend, "--prompt", "short",
                                                     "--max-tokens", "32", "--thinking", "on", "--repeats", "2"])
                report = json.loads(output.getvalue())
                self.assertEqual(status, 1)
                case = report["cases"]["short"]
                self.assertEqual([run["phase"] for run in case["runs"]], ["initial", "warm", "warm"])
                self.assertEqual(case["summary"]["successful_warm_runs"], 1)
                self.assertEqual(case["summary"]["failed_warm_runs"], 1)
                payloads[backend] = json.loads(http.call_args_list[0].args[0].data)
                self.assertNotIn("cache_salt", payloads[backend])
        self.assertEqual(payloads["ollama"]["messages"], payloads["sglang"]["messages"])
        self.assertEqual(payloads["ollama"]["options"]["num_predict"], 32)
        self.assertEqual(payloads["sglang"]["max_tokens"], 32)
        self.assertTrue(payloads["ollama"]["think"])
        self.assertTrue(payloads["sglang"]["chat_template_kwargs"]["enable_thinking"])

    def test_isolated_cache_requests_use_distinct_recorded_salts_without_changing_prompts(self):
        stream = b'data: {"choices":[{"delta":{"content":"FIFO"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        reports = {}
        payloads = {}
        for mode in ("reuse", "isolated"):
            output = io.StringIO()
            with patch.object(self.profiler, "fetch_server_info", return_value={"status": "unavailable"}), \
                    patch.object(self.profiler.urllib.request, "urlopen",
                                 side_effect=lambda *args, **kwargs: io.BytesIO(stream)) as http, \
                    patch("sys.stdout", output), patch("sys.stderr", io.StringIO()):
                status = self.profiler.main(["--backend", "sglang", "--prompt", "short", "--max-tokens", "32",
                                             "--repeats", "2", "--warmups", "2", "--cache-mode", mode])
            self.assertEqual(status, 0)
            reports[mode] = json.loads(output.getvalue())
            payloads[mode] = [json.loads(call.args[0].data) for call in http.call_args_list]
            self.assertEqual(len(payloads[mode]), 4)
            self.assertTrue(all(call.args[0].full_url.endswith("/chat/completions") for call in http.call_args_list))

        self.assertTrue(all("cache_salt" not in payload for payload in payloads["reuse"]))
        salts = [payload["cache_salt"] for payload in payloads["isolated"]]
        self.assertEqual(len(set(salts)), 4)  # Includes initial and warmup requests.
        self.assertTrue(all(UUID(salt).version == 4 for salt in salts))
        isolated = reports["isolated"]
        self.assertEqual(isolated["settings"]["cache_mode"], "isolated")
        self.assertEqual(isolated["settings"]["cache_condition"], "resident_model_prefix_miss")
        self.assertEqual([run["cache_salt"] for run in isolated["cases"]["short"]["runs"]], salts)
        for reused, separate in zip(payloads["reuse"], payloads["isolated"]):
            self.assertEqual(reused, {key: value for key, value in separate.items() if key != "cache_salt"})
        self.assertEqual(reports["reuse"]["cases"]["short"]["prompt_sha256"],
                         isolated["cases"]["short"]["prompt_sha256"])

    def test_isolated_cache_is_rejected_for_ollama_before_any_request(self):
        with patch.object(self.profiler.urllib.request, "urlopen", side_effect=AssertionError("unexpected request")), \
                patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                self.profiler.main(["--backend", "ollama", "--cache-mode", "isolated"])
            self.assertEqual(error.exception.code, 2)
            with self.assertRaisesRegex(ValueError, "SGLang"):
                self.profiler.run_request("ollama", "http://localhost", "test", [], 64, False, 30,
                                          cache_salt="isolated-request")

    def test_actual_server_metadata_normalizes_native_mtp_and_never_saves_secrets(self):
        configuration = {**self.profiler.CONFIG, **self.profiler.CONFIG["MODEL_PRESETS"]["flash-next"],
                         "MODEL_PRESET": "flash-next", "ENABLE_SPECULATION": True, "TOOL_STRICT_LEVEL": 2}
        actual = {
            "model_path": "nvidia/Qwen3.8-Flash-Next-NVFP4",
            "revision": "fc694b54fb0174e0913e6adf86691ef85a4ead47",
            "served_model_name": "Qwen3.8-Flash-Next-FP4-Local", "version": "0.5.21",
            "context_length": 32768, "speculative_algorithm": "EAGLE", "kv_cache_dtype": "bfloat16",
            "enable_cache_report": True,
            "speculative_draft_model_path": "nvidia/Qwen3.8-Flash-Next-NVFP4",
            "speculative_draft_model_revision": "fc694b54fb0174e0913e6adf86691ef85a4ead47",
            "api_key": "PRIVATE_API_KEY", "launch_command": "PRIVATE_LAUNCH_COMMAND",
            "internal_states": [{"potential_secret": "PRIVATE_INTERNAL_STATE"}],
        }
        live = {"model_path": actual["model_path"], "served_model_name": actual["served_model_name"]}
        with patch.object(self.profiler.urllib.request, "urlopen",
                          side_effect=[io.BytesIO(json.dumps(actual).encode()), io.BytesIO(json.dumps(live).encode())]) as http:
            result = self.profiler.fetch_server_info("http://localhost:30000/v1", configuration)
        self.assertEqual(result["mismatches"], [])
        self.assertEqual(result["observed"]["speculative_algorithm"], "EAGLE")
        self.assertTrue(result["observed"]["enable_cache_report"])
        self.assertNotIn("PRIVATE_", json.dumps(result))
        self.assertEqual(http.call_args_list[0].args[0].full_url, "http://localhost:30000/server_info")
        requested = self.profiler.serving_configuration(configuration)
        self.assertTrue(requested["ENABLE_SPECULATION"])
        self.assertEqual(requested["SPECULATIVE_ALGORITHM"], "NEXTN")
        self.assertEqual(requested["PLE_OFFLOAD_BACKEND"], "file")
        self.assertEqual(requested["TOOL_STRICT_LEVEL"], 2)

    def test_explicit_kv_token_budget_is_verified_but_automatic_budget_is_not_constrained(self):
        for configured, observed, mismatch in ((131072, 131072, False),
                                                (131072, 795904, True),
                                                (None, 795904, False)):
            with self.subTest(configured=configured, observed=observed):
                configuration = {**self.profiler.CONFIG, "MAX_TOTAL_TOKENS": configured}
                actual = {"max_total_tokens": observed}
                with patch.object(self.profiler.urllib.request, "urlopen",
                                  side_effect=[io.BytesIO(json.dumps(actual).encode()), io.BytesIO(b"{}")]):
                    result = self.profiler.fetch_server_info("http://localhost:30000/v1", configuration)
                self.assertEqual(self.profiler.serving_configuration(configuration)["MAX_TOTAL_TOKENS"], configured)
                self.assertEqual(result["observed"]["max_total_tokens"], observed)
                self.assertEqual(result["mismatches"],
                                 [{"field": "max_total_tokens", "expected": 131072, "observed": 795904}]
                                 if mismatch else [])
                self.assertEqual(result["status"], "mismatch" if mismatch else "partial")

    def test_mismatched_live_model_stops_benchmark_before_generation(self):
        actual = {"model_path": "some-other-model", "served_model_name": "some-other-model"}
        output = io.StringIO()
        with patch.object(self.profiler.urllib.request, "urlopen",
                          side_effect=[io.BytesIO(json.dumps(actual).encode()), io.BytesIO(json.dumps(actual).encode())]), \
                patch("sys.stdout", output), patch("sys.stderr", io.StringIO()):
            status = self.profiler.main(["--backend", "sglang", "--prompt", "short"])
        report = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(report["server_info"]["status"], "mismatch")
        self.assertEqual(report["cases"], {})
        self.assertIn("mismatch", report["error"].lower())

    def test_length_limited_outputs_are_explicitly_truncated_not_successful(self):
        streams = {
            "ollama": b'{"message":{"content":"Partial"},"done":true,"done_reason":"length","eval_count":64,"eval_duration":1000000000}\n',
            "sglang": b'data: {"choices":[{"delta":{"content":"Partial"},"finish_reason":"length"}]}\n\ndata: {"choices":[],"usage":{"completion_tokens":64}}\n\ndata: [DONE]\n\n',
        }
        for backend, stream in streams.items():
            with self.subTest(backend=backend):
                with patch.object(self.profiler.urllib.request, "urlopen", return_value=io.BytesIO(stream)):
                    result = self.profiler.run_request(backend, "http://localhost", "test", [], 64, False, 30)
                self.assertEqual(result["status"], "truncated")
                self.assertEqual(result["completion_tokens"], 64)
                self.assertEqual(result["output_text"], "Partial")
                result["phase"] = "warm"
                self.assertIsNone(self.profiler.summarize([result])["medians"]["elapsed_seconds"])

    def test_existing_output_is_rejected_before_any_request(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.json"
            output.write_text("preserve this report")
            with patch.object(self.profiler.urllib.request, "urlopen", side_effect=AssertionError("unexpected request")):
                with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as error:
                    self.profiler.main(["--backend", "sglang", "--prompt", "short", "--output", str(output)])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(output.read_text(), "preserve this report")


if __name__ == "__main__":
    unittest.main()
