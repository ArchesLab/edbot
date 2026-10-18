"""Smoke reports must retain failed checks and never mask server strictness."""
import importlib.util
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, AIMessageChunk


def load_checker():
    path = Path(__file__).resolve().parents[1] / "scripts/check_sglang.py"
    spec = importlib.util.spec_from_file_location("check_sglang", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SyntheticModel:
    """Replace only remote inference; validation/reporting use production code."""

    def __init__(self, prior_tier=None, stream_error=False):
        self.prior_tier = prior_tier
        self.stream_error = stream_error
        self.bindings = []

    async def astream(self, prompt):
        yield AIMessageChunk(content=" ")
        if self.stream_error:
            raise RuntimeError("Synthetic stream failure")
        yield AIMessageChunk(content="A base case stops recursion.")

    def bind_tools(self, tools, **kwargs):
        self.bindings.append(kwargs)
        model = self
        name = tools[0].__name__

        class Bound:
            async def ainvoke(self, prompt):
                if name == "UCAOutput":
                    args = {"concept": "recursion", "prior_tier": model.prior_tier,
                            "tier": "Understand", "confidence": "medium", "rationale": "Explains stopping.",
                            "answer_judgment": {"verdict": "correct", "note": "Meets the rubric."},
                            "next_probe_tier": None}
                else:
                    args = {"mode": "generate_question", "concept": "recursion", "target_tier": "Apply",
                            "content": "Which condition should stop counting down?", "format": "short_answer",
                            "rubric": "Stop at zero.", "concept_tags": ["recursion"],
                            "sources": ["Synthetic recursion note"]}
                return AIMessage(content="", tool_calls=[{"id": "synthetic", "name": name, "args": args}],
                                 response_metadata={"finish_reason": "tool_calls"})

        return Bound()


class SmokeReportTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(redirect_stderr(io.StringIO()))

    def test_invalid_null_is_recorded_and_cga_still_runs_without_client_strictness(self):
        checker = load_checker()
        model = SyntheticModel(prior_tier="None")
        self.assertTrue(hasattr(checker, "run_checks"), "Independent durable smoke checks are not implemented")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "smoke.json"
            with patch.object(checker, "create_chat_model", return_value=model):
                code = checker.main(["--output", str(output)])
            report = json.loads(output.read_text())
        self.assertEqual(code, 1)
        self.assertFalse(report["success"])
        self.assertEqual([check["name"] for check in report["checks"]], ["streamed_chat", "UCAOutput", "CGAOutput"])
        self.assertEqual([check["success"] for check in report["checks"]], [True, False, True])
        self.assertEqual(report["checks"][1]["tool_calls"][0]["args"]["prior_tier"], "None")
        self.assertIn("prior_tier", report["checks"][1]["error"])
        self.assertEqual(model.bindings, [{"tool_choice": "UCAOutput"}, {"tool_choice": "CGAOutput"}])
        self.assertTrue(all(check["elapsed_seconds"] >= 0 for check in report["checks"]))

    def test_valid_null_passes_and_existing_report_is_rejected_before_inference(self):
        checker = load_checker()
        self.assertTrue(hasattr(checker, "run_checks"), "Independent durable smoke checks are not implemented")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "smoke.json"
            with patch.object(checker, "create_chat_model", return_value=SyntheticModel()):
                self.assertEqual(checker.main(["--output", str(output)]), 0)
            saved = output.read_bytes()
            report = json.loads(saved)
            self.assertTrue(report["success"])
            self.assertIsNone(report["checks"][1]["tool_calls"][0]["args"]["prior_tier"])
            self.assertIsNotNone(report["checks"][0]["visible_ttft_seconds"])
            with patch.object(checker, "create_chat_model", side_effect=AssertionError("Inference must not start")):
                with self.assertRaises(SystemExit) as error:
                    checker.main(["--output", str(output)])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(output.read_bytes(), saved)

    def test_stream_failure_does_not_prevent_structured_checks(self):
        checker = load_checker()
        self.assertTrue(hasattr(checker, "run_checks"), "Independent durable smoke checks are not implemented")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "smoke.json"
            with patch.object(checker, "create_chat_model", return_value=SyntheticModel(stream_error=True)):
                self.assertEqual(checker.main(["--output", str(output)]), 1)
            report = json.loads(output.read_text())
        self.assertEqual([check["success"] for check in report["checks"]], [False, True, True])
        self.assertIn("Synthetic stream failure", report["checks"][0]["error"])
        self.assertIsNone(report["checks"][0]["visible_ttft_seconds"])
