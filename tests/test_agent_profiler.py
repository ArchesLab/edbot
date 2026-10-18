"""The profiler must measure real service turns without retaining student state."""
import asyncio
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from test_sglang_integration import ScriptedServer, text_reply


def load_profiler(test):
    path = Path(__file__).resolve().parents[1] / "scripts/profile_agent.py"
    test.assertTrue(path.is_file(), "full-turn profiler is not implemented")
    spec = importlib.util.spec_from_file_location("profile_agent", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TraceTests(unittest.TestCase):
    def test_custom_scenarios_are_summarized_without_hiding_failed_measurements(self):
        profiler = load_profiler(self)
        summary = profiler.summarize([
            {"scenario": "socratic-hint", "warmup": True, "success": True,
             "total_s": 1, "visible_ttft_s": 0.5},
            {"scenario": "socratic-hint", "warmup": False, "success": True,
             "total_s": 12, "visible_ttft_s": 8},
            {"scenario": "socratic-hint", "warmup": False, "success": False,
             "total_s": 90, "visible_ttft_s": None},
        ])
        self.assertEqual(summary, {"socratic-hint": {
            "successful_turns": 1, "failed_turns": 1,
            "total_s_median": 12, "visible_ttft_s_median": 8,
        }})

    def test_nested_spans_and_missing_usage_are_not_reported_as_zero_tokens(self):
        profiler = load_profiler(self)
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, LLMResult

        with patch.object(profiler.time, "perf_counter", side_effect=[10, 11, 13, 15]):
            trace = profiler.TurnTrace(started=10)
            tool, model = uuid4(), uuid4()
            trace.on_tool_start({"name": "task"}, "private tool input", run_id=tool)
            trace.on_chat_model_start({}, [], run_id=model, parent_run_id=tool)
            trace.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content="Hi"))]]), run_id=model)
            trace.on_tool_end("private tool output", run_id=tool)
        metrics = trace.report()
        self.assertEqual(metrics["model_call_count"], 1)
        self.assertEqual(metrics["model_calls"][0]["duration_s"], 2)
        self.assertEqual(metrics["tools"][0]["duration_s"], 5)
        self.assertEqual(metrics["model_calls"][0]["parent_run_id"], str(tool))
        self.assertIsNone(metrics["input_tokens"])
        self.assertNotIn("private tool", str(metrics))

    def test_provider_usage_and_failed_call_are_preserved(self):
        profiler = load_profiler(self)
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, LLMResult

        trace = profiler.TurnTrace(started=0)
        success, failure = uuid4(), uuid4()
        trace.on_chat_model_start({}, [], run_id=success)
        trace.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(
            content="Hi", usage_metadata={"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
            response_metadata={"load_duration": 2000000000},
        ))]]), run_id=success)
        trace.on_chat_model_start({}, [], run_id=failure)
        trace.on_llm_error(RuntimeError("model failed"), run_id=failure)
        metrics = trace.report()
        self.assertEqual(metrics["model_call_count"], 2)
        self.assertEqual(metrics["model_calls"][0]["input_tokens"], 12)
        self.assertEqual(metrics["model_calls"][0]["load_duration_s"], 2)
        self.assertEqual(metrics["model_calls"][1]["error"], "RuntimeError: model failed")
        self.assertIsNone(metrics["input_tokens"])  # failed request's usage is unknown

    def test_report_refuses_to_replace_existing_results(self):
        profiler = load_profiler(self)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text("prior result")
            with self.assertRaises(FileExistsError):
                profiler.write_report(path, {"new": True})
            self.assertEqual(path.read_text(), "prior result")

    def test_cached_input_totals_require_every_call_to_report_its_cache_count(self):
        profiler = load_profiler(self)
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, LLMResult

        trace = profiler.TurnTrace(started=0)
        for cached in (0, 8, None):
            usage = {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16}
            if cached is not None:
                usage["input_token_details"] = {"cache_read": cached}
            run_id = uuid4()
            trace.on_chat_model_start({}, [], run_id=run_id)
            trace.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(
                content="Hi", usage_metadata=usage,
            ))]]), run_id=run_id)
            metrics = trace.report()
            self.assertEqual(metrics["model_calls"][-1]["cached_input_tokens"], cached)
            self.assertEqual(metrics["cached_input_tokens"], None if cached is None else cached)

    def test_complete_response_with_null_usage_preserves_finish_reason(self):
        profiler = load_profiler(self)
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, LLMResult

        trace = profiler.TurnTrace(started=0)
        run_id = uuid4()
        trace.on_chat_model_start({}, [], run_id=run_id)
        trace.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(
            content="Incomplete synthetic response", response_metadata={"finish_reason": "length"},
        ))]], llm_output={"token_usage": None}), run_id=run_id)
        metrics = trace.report()
        self.assertEqual(metrics["truncated_model_calls"], 1)
        self.assertIsNone(metrics["input_tokens"])
        self.assertIsNone(metrics["output_tokens"])


class FullTurnTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)

    async def test_real_service_records_callbacks_and_removes_its_temporary_databases(self):
        profiler = load_profiler(self)
        from edbot import edbot_agent, service

        original_paths = (service.CHECKPOINT_PATH, service.STORE_PATH)
        observed_paths = []
        original_build = service.create_edbot_agent

        def build(*args):
            observed_paths.extend((service.CHECKPOINT_PATH, service.STORE_PATH))
            return original_build(*args)

        with ScriptedServer([text_reply("First reply."), text_reply("Second reply.")]), \
                patch.object(edbot_agent, "load_sebook_store"), \
                patch.object(service, "create_edbot_agent", side_effect=build):
            report = await profiler.run_profile("sglang", repetitions=1, warmups=1,
                                                conversation=(("explanation", "Explain encapsulation."),))
        self.assertEqual(len(report["turns"]), 2)
        self.assertEqual([turn["warmup"] for turn in report["turns"]], [True, False])
        self.assertEqual(report["turns"][1]["response"], "Second reply.")
        self.assertEqual(report["turns"][1]["metrics"]["model_call_count"], 1)
        self.assertTrue(report["requested_configuration"]["buffer_tool_responses"])
        self.assertTrue(report["requested_configuration"]["require_content_after_assessment"])
        self.assertTrue(report["requested_configuration"]["serial_child_tool_calls"])
        self.assertGreaterEqual(report["turns"][1]["total_s"], report["turns"][1]["visible_ttft_s"])
        self.assertNotEqual(report["turns"][0]["student_id"], report["turns"][1]["student_id"])
        self.assertEqual((service.CHECKPOINT_PATH, service.STORE_PATH), original_paths)
        self.assertTrue(observed_paths)
        self.assertTrue(all(path not in original_paths and not path.exists() for path in observed_paths))
        self.assertIsNone(service._agent)

    async def test_agent_filesystem_writes_are_isolated_and_cleaned_up(self):
        profiler = load_profiler(self)
        from edbot import edbot_agent, service

        original_backend = edbot_agent.backend
        original_build = service.create_edbot_agent
        instructions = edbot_agent.ROOT_DIR / "AGENTS.md"
        original_instructions = instructions.read_bytes()
        skills = {path.relative_to(edbot_agent.ROOT_DIR): path.read_bytes()
                  for path in (edbot_agent.ROOT_DIR / "skills").rglob("*") if path.is_file()}
        workspaces = []

        def build(*args):
            backend = edbot_agent.backend
            workspace = backend.cwd
            # Fail safely before attempting writes if isolation regresses.
            self.assertNotEqual(workspace, edbot_agent.ROOT_DIR.resolve())
            self.assertTrue(workspace.is_relative_to(service.CHECKPOINT_PATH.parent.resolve()))
            self.assertTrue(backend.virtual_mode)
            workspaces.append(workspace)
            self.assertEqual((workspace / "AGENTS.md").read_bytes(), original_instructions)
            for path, content in skills.items():
                self.assertEqual((workspace / path).read_bytes(), content)
            written = backend.write("/synthetic-notes.txt", "Disposable student notes")
            self.assertIsNone(written.error)
            self.assertEqual((workspace / "synthetic-notes.txt").read_text(), "Disposable student notes")
            edited = backend.edit("/AGENTS.md", original_instructions.decode(), "Synthetic run instructions")
            self.assertIsNone(edited.error)
            self.assertEqual((workspace / "AGENTS.md").read_text(), "Synthetic run instructions")
            self.assertEqual(instructions.read_bytes(), original_instructions)
            return original_build(*args)

        with ScriptedServer([text_reply("Isolated reply.")]), \
                patch.object(edbot_agent, "load_sebook_store"), \
                patch.object(service, "create_edbot_agent", side_effect=build):
            report = await profiler.run_profile("sglang", repetitions=1, warmups=0,
                                                conversation=(("explanation", "Explain encapsulation."),))
        self.assertIsNone(report["error"])
        self.assertTrue(report["turns"][0]["success"])
        self.assertTrue(workspaces)
        self.assertTrue(all(not path.exists() for path in workspaces))
        self.assertEqual(instructions.read_bytes(), original_instructions)
        self.assertIs(edbot_agent.backend, original_backend)
        self.assertIsNone(service._agent)

    async def test_mismatched_server_stops_before_retrieval_or_student_state_is_opened(self):
        profiler = load_profiler(self)
        from edbot import service

        with patch.object(profiler, "fetch_server_info", return_value={"status": "mismatch", "mismatches": [{"field": "revision"}]}), \
                patch.object(service, "get_agent", side_effect=AssertionError("startup must not run")):
            report = await profiler.run_profile("sglang", repetitions=1, warmups=0)
        self.assertEqual(report["turns"], [])
        self.assertIn("mismatch", report["error"].lower())
        self.assertEqual(report["requested_configuration"]["serving"]["SPECULATIVE_ALGORITHM"],
                         profiler.config.SPECULATIVE_ALGORITHM)
        self.assertIsNone(report["startup_s"])

    async def test_failed_live_turn_is_not_counted_as_a_successful_latency_sample(self):
        profiler = load_profiler(self)
        from edbot import edbot_agent

        with ScriptedServer([{"error": "fixture model failure"}]), \
                patch.object(edbot_agent, "load_sebook_store"), \
                self.assertLogs("edbot.service", level="ERROR"):
            report = await profiler.run_profile("sglang", repetitions=1, warmups=0,
                                                conversation=(("explanation", "Explain encapsulation."),))
        turn = report["turns"][0]
        self.assertFalse(turn["success"])
        self.assertIsNone(turn["visible_ttft_s"])
        self.assertTrue(turn["metrics"]["model_calls"][0]["error"])
        self.assertEqual(report["summary"]["explanation"]["failed_turns"], 1)
        self.assertIsNone(report["summary"]["explanation"]["total_s_median"])

    async def test_output_limited_reply_is_excluded_from_successful_latency_samples(self):
        profiler = load_profiler(self)
        from edbot import edbot_agent

        reply = text_reply("An incomplete explanation")
        reply["finish_reason"] = "length"
        with ScriptedServer([reply]), patch.object(edbot_agent, "load_sebook_store"):
            report = await profiler.run_profile("sglang", repetitions=1, warmups=0,
                                                conversation=(("explanation", "Explain encapsulation."),))
        self.assertFalse(report["turns"][0]["success"])
        self.assertEqual(report["turns"][0]["metrics"]["truncated_model_calls"], 1)
        self.assertIsNone(report["summary"]["explanation"]["total_s_median"])

    async def test_whitespace_only_stream_is_not_visible_text(self):
        profiler = load_profiler(self)
        from edbot import edbot_agent

        with ScriptedServer([text_reply(" \n ")]), patch.object(edbot_agent, "load_sebook_store"):
            report = await profiler.run_profile("sglang", repetitions=1, warmups=0,
                                                conversation=(("explanation", "Explain encapsulation."),))
        self.assertFalse(report["turns"][0]["success"])
        self.assertIsNone(report["turns"][0]["visible_ttft_s"])


if __name__ == "__main__":
    unittest.main()
