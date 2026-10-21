"""Cache-retention comparisons must vary only the intervening child request."""
from contextlib import redirect_stdout, redirect_stderr
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/profile_cache.py"


def load_profiler(test):
    test.assertTrue(SCRIPT.is_file(), "cache-retention profiler is not implemented")
    spec = importlib.util.spec_from_file_location("profile_cache", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CacheServer:
    """Serve metadata and short SSE replies; retain requests at the HTTP boundary."""

    def __init__(self, config, finishes=(), cached=(), model_path=None):
        self.requests = []
        self.gets = []
        self.finishes = iter(finishes)
        self.cached = iter(cached)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.gets.append(self.path)
                data = {"model_path": model_path or config["MODEL_PATH"],
                        "served_model_name": config["MODEL_NAME"]}
                if self.path == "/server_info":
                    algorithm = config["SPECULATIVE_ALGORITHM"] if config["ENABLE_SPECULATION"] else None
                    data.update(version=config["SGLANG_VERSION"],
                                speculative_algorithm="EAGLE" if algorithm == "NEXTN" else algorithm,
                                max_mamba_cache_size=config["MAMBA_CACHE_SLOTS_PER_REQUEST"] * config["MAX_RUNNING_REQUESTS"],
                                max_total_tokens=config["MAX_TOTAL_TOKENS"],
                                api_key="do-not-save-secret", launch_command="do-not-save-command")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append(payload)
                index = len(owner.requests)
                finish = next(owner.finishes, "stop")
                cached = next(owner.cached, 0)
                usage = {"prompt_tokens": 8000 + index, "completion_tokens": 2}
                if cached is not None:
                    usage["prompt_tokens_details"] = {"cached_tokens": cached}
                records = [
                    {"choices": [{"delta": {"content": f"GENERATED-{index}"}, "finish_reason": finish}]},
                    {"choices": [], "usage": usage,
                     "sglext": {"spec_tokens_details": {"spec_accept_rate": 0.5}}},
                ]
                stream = "".join(f"data: {json.dumps(record)}\n\n" for record in records)
                if finish != "incomplete":
                    stream += "data: [DONE]\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(stream.encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class CacheProfilerTests(unittest.TestCase):
    def run_cli(self, profiler, server, *args):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            status = profiler.main(["--base-url", server.url, *args])
        return status, json.loads(output.getvalue())

    def test_paired_sequences_retain_identical_parent_prefixes_and_isolate_salts(self):
        profiler = load_profiler(self)
        with CacheServer(profiler.CONFIG) as server:
            status, report = self.run_cli(profiler, server, "--repetitions", "2")
        self.assertEqual(status, 0)
        self.assertEqual(len(server.requests), 10)
        sequences = report["sequences"]
        self.assertEqual([s["condition"] for s in sequences],
                         ["parent_only", "interleaved_child", "interleaved_child", "parent_only"])
        self.assertEqual(len({s["cache_salt"] for s in sequences}), 4)
        controls = [s for s in sequences if s["condition"] == "parent_only"]
        interleaved = [s for s in sequences if s["condition"] == "interleaved_child"]
        for control in controls:
            other = next(s for s in interleaved if s["repetition"] == control["repetition"])
            self.assertEqual([r["stage"] for r in control["requests"]], ["parent", "parent_extension"])
            self.assertEqual([r["stage"] for r in other["requests"]], ["parent", "child", "parent_extension"])
            self.assertEqual(control["requests"][-1]["unsalted_payload_sha256"],
                             other["requests"][-1]["unsalted_payload_sha256"])
        recorded = []
        for sequence in sequences:
            first, last = sequence["requests"][0], sequence["requests"][-1]
            self.assertEqual(first["payload"]["messages"], last["payload"]["messages"][:2])
            self.assertEqual(last["payload"]["messages"][2]["role"], "assistant")
            self.assertNotIn("GENERATED-", json.dumps(last["payload"]))
            for row in sequence["requests"]:
                payload = row["payload"]
                self.assertEqual(payload["cache_salt"], sequence["cache_salt"])
                canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                self.assertEqual(row["payload_sha256"], hashlib.sha256(canonical.encode()).hexdigest())
                recorded.append(payload)
        self.assertEqual(recorded, server.requests)
        self.assertTrue(all(p["max_tokens"] in (16, 32) for p in server.requests))

    def test_real_http_metrics_preserve_unknown_zero_actual_config_and_acceptance(self):
        profiler = load_profiler(self)
        with CacheServer(profiler.CONFIG, cached=(None, 7808, 0, 0, 0)) as server:
            status, report = self.run_cli(profiler, server, "--repetitions", "1")
        self.assertEqual(status, 0)
        self.assertEqual(report["server_info"]["mismatches"], [])  # Native NEXTN is reported as EAGLE.
        self.assertEqual(report["server_info"]["observed"]["max_mamba_cache_size"],
                         profiler.CONFIG["MAMBA_CACHE_SLOTS_PER_REQUEST"] * profiler.CONFIG["MAX_RUNNING_REQUESTS"])
        self.assertNotIn("do-not-save", json.dumps(report))
        rows = [r for s in report["sequences"] for r in s["requests"]]
        self.assertEqual([r["prompt_tokens"] for r in rows], [8001, 8002, 8003, 8004, 8005])
        self.assertEqual([r["cached_prompt_tokens"] for r in rows], [None, 7808, 0, 0, 0])
        self.assertTrue(all(r["elapsed_seconds"] >= r["ttft_visible_seconds"] >= 0 for r in rows))
        self.assertEqual(rows[-1]["raw_metadata"]["sglext"]["spec_tokens_details"]["spec_accept_rate"], 0.5)
        self.assertEqual(report["paired_differences"][0]["cached_tokens_lost_after_child"], 7808)

    def test_default_prompt_hashes_match_the_original_live_probe(self):
        profiler = load_profiler(self)
        # Captured from cache-mtp-10-states.json, not generated by this profiler.
        original = {
            "parent": "973461b47ee8c7c8c28396a5ac7f491b84536ee6826ba2ad6d2fd582c9191a9d",
            "child": "cd4efd515014aab33025c9d571b57068dc047e964d1f25260a526780832792c3",
            "parent_extension": "6e12b4d750c5ab080ad6c7408717593a2999a117100e6583c996321da6693b84",
        }
        with CacheServer(profiler.CONFIG) as server:
            status, report = self.run_cli(profiler, server, "--repetitions", "1")
        self.assertEqual(status, 0)
        self.assertEqual(report["settings"]["parent_rounds"], 1)
        self.assertEqual(report["settings"]["child_rounds"], 1)
        for sequence in report["sequences"]:
            for row in sequence["requests"]:
                self.assertEqual(row["prompt_sha256"], original[row["stage"]])

    def test_multiple_rounds_preserve_all_parent_requests_and_each_role_prefix(self):
        profiler = load_profiler(self)
        with CacheServer(profiler.CONFIG) as server:
            status, report = self.run_cli(profiler, server, "--repetitions", "1",
                                          "--parent-rounds", "3", "--child-rounds", "4")
        self.assertEqual(status, 0)
        self.assertEqual(len(server.requests), 12)
        self.assertEqual(report["settings"]["parent_rounds"], 3)
        self.assertEqual(report["settings"]["child_rounds"], 4)
        control, interleaved = report["sequences"]
        self.assertEqual([row["stage"] for row in control["requests"]],
                         ["parent", "parent_round_2", "parent_round_3", "parent_extension"])
        self.assertEqual([row["stage"] for row in interleaved["requests"]],
                         ["parent", "parent_round_2", "parent_round_3", "child", "child_round_2",
                          "child_round_3", "child_round_4", "parent_extension"])
        other_parents = [row for row in interleaved["requests"] if row["stage"].startswith("parent")]
        for left, right in zip(control["requests"], other_parents):
            self.assertEqual(left["unsalted_payload_sha256"], right["unsalted_payload_sha256"])
            self.assertEqual(left["payload"]["messages"], right["payload"]["messages"])
        for sequence in report["sequences"]:
            previous = {}
            for row in sequence["requests"]:
                role = "child" if row["stage"].startswith("child") else "parent"
                messages = row["payload"]["messages"]
                self.assertNotIn("GENERATED-", json.dumps(messages))
                self.assertEqual(row["payload"]["cache_salt"], sequence["cache_salt"])
                if role in previous:
                    before = previous[role]
                    self.assertEqual(messages[:-2], before["payload"]["messages"])
                    self.assertEqual(messages[-2], {"role": "assistant", "content": "ACK"})
                    self.assertEqual(row["prefix_prompt_sha256"], before["prompt_sha256"])
                    self.assertEqual(row["prefix_message_count"], len(messages) - 2)
                else:
                    self.assertIsNone(row["prefix_prompt_sha256"])
                previous[role] = row

    def test_failed_intermediate_round_invalidates_the_complete_comparison(self):
        profiler = load_profiler(self)
        with CacheServer(profiler.CONFIG, finishes=("stop", "length", "stop", "stop")) as server:
            status, report = self.run_cli(profiler, server, "--repetitions", "1",
                                          "--parent-rounds", "3", "--child-rounds", "4")
        self.assertEqual(status, 1)
        self.assertFalse(report["sequences"][0]["success"])
        self.assertTrue(report["sequences"][1]["success"])
        self.assertEqual(report["sequences"][0]["requests"][1]["status"], "truncated")
        self.assertEqual(report["paired_differences"], [])
        self.assertEqual(report["summary"]["parent_only"]["successful_sequences"], 0)

    def test_failed_or_truncated_priming_does_not_count_as_a_successful_sequence(self):
        profiler = load_profiler(self)
        with CacheServer(profiler.CONFIG, finishes=("length", "stop", "stop", "incomplete", "stop")) as server:
            status, report = self.run_cli(profiler, server, "--repetitions", "1")
        self.assertEqual(status, 1)
        self.assertEqual(len(server.requests), 5)
        self.assertEqual(report["sequences"][0]["requests"][0]["status"], "truncated")
        self.assertEqual(report["sequences"][1]["requests"][1]["status"], "error")
        self.assertTrue(all(not s["success"] for s in report["sequences"]))
        self.assertEqual(report["paired_differences"], [])
        self.assertIsNone(report["summary"]["parent_only"]["medians"]["elapsed_seconds"])

    def test_model_mismatch_stops_before_any_generation(self):
        profiler = load_profiler(self)
        with CacheServer(profiler.CONFIG, model_path="different-checkpoint") as server:
            status, report = self.run_cli(profiler, server, "--repetitions", "1")
        self.assertEqual(status, 1)
        self.assertEqual(server.requests, [])
        self.assertEqual(report["sequences"], [])
        self.assertEqual(report["server_info"]["status"], "mismatch")
        self.assertIn("mismatch", report["error"])

    def test_existing_report_causes_no_metadata_or_generation_requests(self):
        profiler = load_profiler(self)
        with tempfile.TemporaryDirectory() as directory, CacheServer(profiler.CONFIG) as server:
            path = Path(directory) / "prior.json"
            path.write_text("keep prior result")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                profiler.main(["--base-url", server.url, "--output", str(path)])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(path.read_text(), "keep prior result")
            self.assertEqual(server.gets, [])
            self.assertEqual(server.requests, [])
            with self.assertRaises(FileExistsError):
                profiler.write_report(path, {"replacement": True})
            self.assertEqual(path.read_text(), "keep prior result")


if __name__ == "__main__":
    unittest.main()
