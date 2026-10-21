"""Evaluation reports preserve evidence; they must not manufacture quality scores."""
import asyncio
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_agent_profiler import load_profiler
from test_sglang_integration import ScriptedServer, text_reply, tool_reply


ROOT = Path(__file__).resolve().parents[1]


def load_evaluator(test):
    path = ROOT / "scripts/evaluate_tutoring.py"
    test.assertTrue(path.is_file(), "synthetic tutoring evaluator is not implemented")
    spec = importlib.util.spec_from_file_location("evaluate_tutoring", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def case(case_id="sample", prompts=("Explain information hiding.",)):
    return {
        "id": case_id, "title": "Synthetic example", "mode": "explanation",
        "turns": [{"id": f"turn-{index + 1}", "message": prompt} for index, prompt in enumerate(prompts)],
        "expectations": ["Use accurate, bounded claims."],
        "critical_failures": ["Confident false feedback."],
        "review_dimensions": ["accuracy"],
    }


class InputTests(unittest.TestCase):
    def test_request_evidence_keeps_dynamic_system_and_tools_but_excludes_credentials(self):
        evaluator = load_evaluator(self)
        from langchain_core.messages import SystemMessage, HumanMessage

        self.assertTrue(hasattr(evaluator, "model_request_evidence"), "model request evidence capture is missing")
        messages = [[SystemMessage(content="Synthetic dynamic system context"), HumanMessage(content="A question")]]
        parameters = {"model": "fixture", "temperature": 0, "api_key": "SECRET_KEY",
                      "default_headers": {"Authorization": "SECRET_HEADER"},
                      "extra_body": {"chat_template_kwargs": {"enable_thinking": False, "api_key": "SECRET_NESTED"}},
                      "tools": [{"type": "function", "function": {"name": "CGAOutput",
                                 "description": "Synthetic output", "parameters": {"type": "object"}}}]}
        evidence = evaluator.model_request_evidence(messages, parameters)
        encoded = json.dumps(evidence)
        self.assertIn("Synthetic dynamic system context", encoded)
        self.assertNotIn("SECRET", encoded)
        self.assertEqual(evidence["inferred_role"], "content-generating-agent")
        self.assertEqual(evidence["invocation_params"]["temperature"], 0)
        self.assertEqual(evidence["tools"][0]["function"]["name"], "CGAOutput")
        changed = evaluator.model_request_evidence([[SystemMessage(content="Changed context")]], parameters)
        self.assertNotEqual(evidence["request_sha256"], changed["request_sha256"])

    def test_unknown_case_and_invalid_repeat_count_fail_before_inference(self):
        evaluator = load_evaluator(self)
        with self.assertRaisesRegex(ValueError, "unknown"):
            evaluator.load_cases(case_ids=["does-not-exist"])
        with self.assertRaisesRegex(ValueError, "positive"):
            asyncio.run(evaluator.run_evaluation([case()], repetitions=0))

    def test_case_selection_retains_multiturn_expectations(self):
        evaluator = load_evaluator(self)
        selected = evaluator.load_cases(case_ids=["socratic-pressure"])
        self.assertEqual([item["id"] for item in selected], ["socratic-pressure"])
        self.assertGreaterEqual(len(selected[0]["turns"]), 2)
        self.assertTrue(selected[0]["expectations"])
        self.assertTrue(selected[0]["critical_failures"])

    def test_existing_report_is_not_replaced_or_used_for_inference(self):
        evaluator = load_evaluator(self)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            output.write_text("prior evidence")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                evaluator.main(["--output", str(output), "--case", "concise-explanation"])
            self.assertEqual(raised.exception.code, 2)
            self.assertEqual(output.read_text(), "prior evidence")


class EvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)

    async def test_real_profile_captures_private_tool_evidence_and_cleans_isolated_state(self):
        evaluator, profiler = load_evaluator(self), load_profiler(self)
        from edbot import edbot_agent, service

        private_rubric = "SYNTHETIC_PRIVATE_RUBRIC: preserve public behavior."
        task = {"subagent_type": "content-generating-agent", "description": json.dumps({
            "mode": "generate_question", "concept": "information-hiding", "target_tier": "Apply",
        })}
        generated = {"mode": "generate_question", "concept": "information-hiding", "target_tier": "Apply",
                     "content": "Which client assumption would you test?", "format": "short_answer",
                     "rubric": private_rubric, "concept_tags": ["information-hiding"],
                     "sources": ["Synthetic source used only by the test"]}
        original_paths = (service.CHECKPOINT_PATH, service.STORE_PATH)
        observed_paths = []
        original_build = service.create_edbot_agent

        def build(*args):
            observed_paths.extend((service.CHECKPOINT_PATH, service.STORE_PATH))
            self.assertNotIn(service.CHECKPOINT_PATH, original_paths)
            self.assertNotIn(service.STORE_PATH, original_paths)
            return original_build(*args)

        with ScriptedServer([tool_reply("task", task), tool_reply("CGAOutput", generated)]), \
                patch.object(edbot_agent, "load_sebook_store"), \
                patch.object(service, "create_edbot_agent", side_effect=build):
            report = await evaluator.run_evaluation([case()], profile_module=profiler)
        self.assertEqual(report["execution"], "completed")
        self.assertEqual(report["quality"], "not_reviewed")
        episode = report["cases"][0]
        self.assertEqual(episode["quality"], "not_reviewed")
        self.assertEqual(episode["profile"]["turns"][0]["response"], generated["content"])
        self.assertIn(private_rubric, json.dumps(episode["observations"]))
        self.assertIn("Synthetic source", json.dumps(episode["profile"]["turns"][0]["metrics"]["tools"]))
        self.assertEqual(episode["observations"][0]["assessment_state"], {})
        model_calls = episode["profile"]["turns"][0]["metrics"]["model_calls"]
        self.assertTrue(all(len(call["request_sha256"]) == 64 for call in model_calls))
        self.assertTrue(all(call["input_messages"][0][0]["type"] == "system" for call in model_calls))
        self.assertEqual(model_calls[0]["inferred_role"], "orchestrator")
        self.assertIn("content-generating-agent", [call["inferred_role"] for call in model_calls])
        children = [call for call in model_calls if call["inferred_role"] == "content-generating-agent"]
        self.assertTrue(all(call["output_message"] for call in children))
        self.assertEqual(len(episode["request_sha256"]), 64)
        self.assertIn("src/edbot/prompts/cga_prompt.md", report["manifest"]["source_sha256"])
        self.assertTrue(observed_paths)
        self.assertTrue(all(not path.exists() for path in observed_paths))
        self.assertEqual((service.CHECKPOINT_PATH, service.STORE_PATH), original_paths)
        self.assertIsNone(service._agent)

    async def test_repetitions_and_cases_never_share_a_student_checkpoint(self):
        evaluator, profiler = load_evaluator(self), load_profiler(self)
        from edbot import edbot_agent

        with ScriptedServer([text_reply(str(i)) for i in range(4)]), patch.object(edbot_agent, "load_sebook_store"):
            report = await evaluator.run_evaluation([case("first"), case("second")],
                                                    repetitions=2, profile_module=profiler)
        observations = [entry for episode in report["cases"] for entry in episode["observations"]]
        self.assertEqual(len(observations), 4)
        self.assertEqual(len({entry["student_id"] for entry in observations}), 4)
        self.assertTrue(all(len(entry["messages"]) == 2 for entry in observations))

    async def test_assessment_snapshot_contains_actual_tool_update(self):
        from edbot import model_config
        baseline = patch.object(model_config, "DETERMINISTIC_ASSESSMENT_SAVE", False)
        baseline.start()
        self.addCleanup(baseline.stop)
        evaluator, profiler = load_evaluator(self), load_profiler(self)
        from edbot import edbot_agent

        assessment = {"concept": "information-hiding", "tier": "Understand", "confidence": "low",
                      "rationale": "Synthetic evidence only: the learner named a public guarantee."}
        task = {"subagent_type": "understanding-checking-agent", "description": json.dumps({
            "concept": "information-hiding", "invocation_context": "new_evidence",
        })}
        result = {**assessment, "prior_tier": None, "answer_judgment": None, "next_probe_tier": None}
        content = {"mode": "explain_at_tier", "concept": "information-hiding", "target_tier": "Understand",
                   "content": "Which public guarantee must stay stable?", "sources": ["Synthetic course source"]}
        content_task = tool_reply("task", {"subagent_type": "content-generating-agent", "description": json.dumps({
            key: content[key] for key in ("mode", "concept", "target_tier")})})
        content_task["deltas"][1]["tool_calls"][0]["id"] = "content-after-assessment"
        with ScriptedServer([tool_reply("task", task), tool_reply("update_student_model", assessment),
                             tool_reply("UCAOutput", result), content_task, tool_reply("CGAOutput", content),
                             text_reply("A synthetic follow-up.")]), \
                patch.object(edbot_agent, "load_sebook_store"):
            report = await evaluator.run_evaluation([case()], profile_module=profiler)
        self.assertEqual(report["execution"], "completed")
        saved = report["cases"][0]["observations"][0]["assessment_state"]["information-hiding"]
        self.assertEqual(saved["rationale"], assessment["rationale"])
        self.assertEqual(saved["tier"], "Understand")
        self.assertEqual(saved["assessment_count"], 1)

    async def test_initialized_service_is_never_borrowed_or_closed(self):
        evaluator, profiler = load_evaluator(self), load_profiler(self)
        from edbot import service

        sentinel = object()
        with patch.object(service, "_agent", sentinel):
            with self.assertRaisesRegex(RuntimeError, "already initialized"):
                await evaluator.run_evaluation([case()], profile_module=profiler)
            self.assertIs(service._agent, sentinel)

    async def test_real_failed_turn_retains_prior_reply_and_incomplete_episode(self):
        evaluator, profiler = load_evaluator(self), load_profiler(self)
        from edbot import edbot_agent

        with ScriptedServer([text_reply("First reply survives."), {"error": "synthetic failure"}]), \
                patch.object(edbot_agent, "load_sebook_store"), self.assertLogs("edbot.service", level="ERROR"):
            report = await evaluator.run_evaluation([case(prompts=("First", "Second", "Third"))],
                                                    profile_module=profiler)
        self.assertEqual(report["execution"], "failed")
        episode = report["cases"][0]
        self.assertEqual(episode["expected_turns"], 3)
        self.assertEqual(episode["profile"]["turns"][0]["response"], "First reply survives.")
        self.assertEqual(len(episode["profile"]["turns"]), 2)
        self.assertFalse(episode["profile"]["turns"][1]["success"])
        self.assertEqual(report["quality"], "not_reviewed")


class CommandTests(unittest.TestCase):
    def test_failed_inference_writes_partial_report_and_returns_nonzero(self):
        evaluator = load_evaluator(self)
        from edbot import edbot_agent

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "failed.json"
            with ScriptedServer([text_reply("First case completed."), {"error": "synthetic failure"}]), \
                    patch.object(edbot_agent, "load_sebook_store"), \
                    self.assertLogs("edbot.service", level="ERROR"), contextlib.redirect_stdout(io.StringIO()):
                code = evaluator.main(["--output", str(output), "--case", "concise-explanation",
                                       "--case", "single-practice", "--repetitions", "1"])
            self.assertEqual(code, 1)
            result = json.loads(output.read_text())
            self.assertEqual(result["execution"], "failed")
            self.assertEqual(result["cases"][0]["profile"]["turns"][0]["response"], "First case completed.")
            self.assertEqual(result["quality"], "not_reviewed")


if __name__ == "__main__":
    unittest.main()
