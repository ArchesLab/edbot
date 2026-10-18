"""The component runner exercises the real named UCA without grading its pedagogy."""
import asyncio
import contextlib
import importlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_sglang_integration import ScriptedServer, tool_reply

ROOT = Path(__file__).resolve().parents[1]


def load_runner(test):
    path = ROOT / "scripts/evaluate_assessment.py"
    test.assertTrue(path.is_file(), "isolated UCA evaluator is not implemented")
    spec = importlib.util.spec_from_file_location("evaluate_assessment", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def case(case_id="fixture", prior=True):
    return {
        "id": case_id, "title": "Synthetic contract reasoning", "concept": "information-hiding",
        "prior_entry": {"concept": "information-hiding", "tier": "Understand", "confidence": "low",
                        "rationale": "Earlier synthetic evidence.", "assessed_at": "2026-01-01T00:00:00Z",
                        "assessed_at_turn": 0, "assessment_count": 1} if prior else None,
        "uca_input": {"concept": "information-hiding", "invocation_context": "answer_submission",
                      "answer_submission": {"question_text": "How can storage change safely?",
                                            "rubric": "Preserve the public contract.",
                                            "student_answer": "Keep public behavior unchanged."}},
        "conversation": [{"role": "student", "content": "Give me a practice question."},
                         {"role": "edbot", "content": "How can storage change safely?"},
                         {"role": "student", "content": "Keep public behavior unchanged."}],
        "expectations": {"critical_failures": ["REVIEW_ONLY_SENTINEL_812"]},
    }


ASSESSMENT = {"concept": "information-hiding", "tier": "Apply", "confidence": "medium",
              "rationale": "The learner proposed preserving public behavior during the change."}


def replies(prior=True, *, result=None, write=True):
    sequence = [tool_reply("fetch_student_data", {"concept": "information-hiding"}),
                tool_reply("search_markdown_sources", {"query": "information hiding contract"})]
    if write:
        sequence.append(tool_reply("update_student_model", ASSESSMENT))
    sequence.append(tool_reply("UCAOutput", result or {
        **ASSESSMENT, "prior_tier": "Understand" if prior else None,
        "answer_judgment": {"verdict": "correct", "note": "Names the public contract."}}))
    return sequence


@contextlib.contextmanager
def fixture_sources(*, deterministic_save=False):
    from edbot import edbot_agent, model_config
    from langchain_core.documents import Document
    from langchain_core.embeddings import DeterministicFakeEmbedding
    from langchain_core.vectorstores import InMemoryVectorStore
    search = importlib.import_module("edbot.tools.search_markdown_sources")
    store = InMemoryVectorStore.from_documents([
        Document(page_content="FIXTURE_RETRIEVAL_904: Preserve the stable public contract.",
                 metadata={"source": "synthetic/contract.md", "url": "https://example.test/contract", "path": "contract.md"})
    ], DeterministicFakeEmbedding(size=8))
    with patch.object(edbot_agent, "load_sebook_store", return_value=store), \
            patch.object(search, "load_sebook_store", return_value=store), \
            patch.object(model_config, "DETERMINISTIC_ASSESSMENT_SAVE", deterministic_save):
        yield


class AssessmentInputTests(unittest.TestCase):
    def test_consistency_counts_actual_store_writes_independently_of_model_tool_calls(self):
        runner = load_runner(self)
        fixture = case()
        prior = fixture["prior_entry"]
        saved = {**prior, **ASSESSMENT, "assessment_count": 2, "assessed_at_turn": 2}
        output = {**ASSESSMENT, "prior_tier": "Understand"}
        write = {"key": "information-hiding", "value": saved}
        result = runner.persistence_check(fixture, {"information-hiding": prior},
                                          {"information-hiding": saved}, output, [], writes=[write])
        self.assertTrue(result["consistent"])
        self.assertEqual(result["update_call_count"], 0)
        self.assertEqual(result["student_model_write_count"], 1)
        for writes in ([], [write, write]):
            result = runner.persistence_check(fixture, {"information-hiding": prior},
                                              {"information-hiding": saved}, output, [], writes=writes)
            self.assertFalse(result["checks"]["one_update"])

    def test_fixture_selection_and_invalid_inputs_fail_before_execution(self):
        runner = load_runner(self)
        self.assertEqual(len(runner.load_cases()), 8)
        self.assertEqual([item["id"] for item in runner.load_cases(case_ids=["valid-map-copy"])], ["valid-map-copy"])
        with self.assertRaisesRegex(ValueError, "unknown"):
            runner.load_cases(case_ids=["does-not-exist"])
        for invalid in ({**case(), "concept": "other"}, {**case(), "conversation": []},
                        {**case(), "prior_entry": {**case()["prior_entry"], "concept": "other"}}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                asyncio.run(runner.run_evaluation([invalid]))
        with self.assertRaisesRegex(ValueError, "positive"):
            asyncio.run(runner.run_evaluation([case()], repetitions=0))

    def test_existing_report_cannot_be_overwritten(self):
        runner = load_runner(self)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.json"
            output.write_text("prior evidence")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                runner.main(["--output", str(output), "--case", "valid-map-copy"])
            self.assertEqual(output.read_text(), "prior evidence")


class AssessmentEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)

    async def test_code_owned_persistence_is_observed_without_a_model_write_call(self):
        runner = load_runner(self)
        with ScriptedServer(replies(write=False)) as server, fixture_sources(deterministic_save=True):
            report = await runner.run_evaluation([case()])
        observation = report["cases"][0]["observations"][0]
        self.assertEqual(report["execution"], "completed", observation)
        self.assertEqual(len(server.requests), 3)
        self.assertEqual(observation["persistence"]["update_call_count"], 0)
        self.assertEqual(observation["persistence"]["student_model_write_count"], 1)
        self.assertEqual(len(observation["student_model_writes"]), 1, "Private receipts are not assessment writes")
        self.assertEqual(observation["uca_output"]["rationale"],
                         observation["store_after"]["information-hiding"]["rationale"])
        for _, request in server.requests:
            self.assertNotIn("update_student_model", {item["function"]["name"] for item in request["tools"]})

    async def test_actual_named_child_reads_and_writes_disposable_state_with_exact_input(self):
        runner = load_runner(self)
        from edbot import edbot_agent, service, model_config
        original_backend = edbot_agent.backend
        original_paths = (service.CHECKPOINT_PATH, service.STORE_PATH)
        original_flags = (model_config.REDUCED_TUTOR_HARNESS, model_config.DIRECT_CONTENT_DELIVERY,
                          model_config.REQUIRE_CONTENT_AFTER_ASSESSMENT)
        with ScriptedServer(replies()) as server, fixture_sources():
            report = await runner.run_evaluation([case()])
        self.assertEqual(report["execution"], "completed", report)
        self.assertTrue(report["component_only"])
        self.assertFalse(report["orchestrator_routing_evaluated"])
        self.assertFalse(report["requested_configuration"]["require_content_after_assessment"])
        self.assertEqual(report["requested_configuration"]["prefetch_assessment_prior"],
                         model_config.PREFETCH_ASSESSMENT_PRIOR)
        self.assertIn("synthetic parent emits no tutoring reply", " ".join(report["observation_limits"]))
        self.assertEqual(report["quality"], "not_reviewed")
        observation = report["cases"][0]["observations"][0]
        self.assertEqual(observation["uca_output"]["rationale"], ASSESSMENT["rationale"])
        self.assertTrue(observation["persistence"]["consistent"], observation["persistence"])
        before, after = observation["store_before"], observation["store_after"]
        self.assertEqual(before["information-hiding"]["tier"], "Understand")
        self.assertEqual(after["information-hiding"]["assessment_count"], 2)
        self.assertEqual(after["information-hiding"]["assessed_at_turn"], 2)
        self.assertEqual(after["information-hiding"]["tier"], "Apply")
        self.assertNotEqual(after["information-hiding"]["assessed_at"], before["information-hiding"]["assessed_at"])
        self.assertEqual(len(server.requests), 4, "Only real UCA calls should use HTTP")
        self.assertEqual(server.replies, [])
        for _, request in server.requests:
            self.assertEqual(request["stream"], not model_config.BUFFER_TOOL_RESPONSES)
            names = {tool["function"]["name"] for tool in request["tools"]}
            self.assertIn("UCAOutput", names)
            self.assertIn("update_student_model", names)
            self.assertNotIn("task", names)
            self.assertNotIn("REVIEW_ONLY_SENTINEL", json.dumps(request))
        first = server.requests[0][1]["messages"]
        self.assertIn("pure assessment function", first[0]["content"])
        self.assertNotIn("Give me a practice question.", first[0]["content"])
        self.assertEqual(first[1], {"role": "user", "content": "Give me a practice question."})
        self.assertEqual(first[2], {"role": "assistant", "content": "How can storage change safely?"})
        self.assertEqual(first[3], {"role": "user", "content": "Keep public behavior unchanged."})
        self.assertEqual(json.loads(first[-1]["content"]), case()["uca_input"])
        metrics = observation["metrics"]
        self.assertEqual(metrics["model_call_count"], 4)
        self.assertEqual({span["inferred_role"] for span in metrics["model_calls"]}, {"understanding-checking-agent"})
        self.assertTrue(all(span["output_message"] and len(span["request_sha256"]) == 64 for span in metrics["model_calls"]))
        self.assertIn("FIXTURE_RETRIEVAL_904", json.dumps(metrics["tools"]))
        self.assertEqual(observation["persistence"]["update_call_count"], 1)
        self.assertEqual(observation["persistence"]["student_model_write_count"], 1)
        self.assertEqual(observation["student_model_writes"][0]["value"], after["information-hiding"])
        self.assertGreater(observation["assessment_s"], 0)
        self.assertNotIn("response", observation)
        self.assertIn("scripts/evaluate_assessment.py", report["manifest"]["source_sha256"])
        self.assertIs(edbot_agent.backend, original_backend)
        self.assertEqual((service.CHECKPOINT_PATH, service.STORE_PATH), original_paths)
        self.assertEqual((model_config.REDUCED_TUTOR_HARNESS, model_config.DIRECT_CONTENT_DELIVERY,
                          model_config.REQUIRE_CONTENT_AFTER_ASSESSMENT), original_flags)
        self.assertIsNone(service._agent)

    async def test_repetitions_are_independent_and_missing_write_is_reported(self):
        runner = load_runner(self)
        with ScriptedServer(replies(False) * 2 + replies(False, write=False)), fixture_sources():
            report = await runner.run_evaluation([case(prior=False)], repetitions=3)
        observations = report["cases"][0]["observations"]
        self.assertEqual(len({item["student_id"] for item in observations}), 3)
        self.assertTrue(all(item["store_before"] == {} for item in observations))
        self.assertEqual([item["execution"] for item in observations], ["completed", "completed", "failed"])
        self.assertEqual(observations[0]["store_after"]["information-hiding"]["assessment_count"], 1)
        self.assertFalse(observations[-1]["persistence"]["consistent"])
        self.assertEqual(observations[-1]["persistence"]["update_call_count"], 0)
        self.assertEqual(report["execution"], "failed")
        self.assertEqual(report["quality"], "not_reviewed")

    async def test_failed_child_retains_actual_write_and_error_evidence(self):
        runner = load_runner(self)
        with ScriptedServer(replies()[:-1] + [{"error": "fixture child failure"}]), fixture_sources():
            report = await runner.run_evaluation([case()])
        observation = report["cases"][0]["observations"][0]
        self.assertEqual(observation["execution"], "failed")
        self.assertIn("fixture child failure", observation["error"])
        self.assertIsNone(observation["uca_output"])
        self.assertEqual(observation["store_after"]["information-hiding"]["tier"], "Apply")
        self.assertTrue(any(call["error"] for call in observation["metrics"]["model_calls"]))

    async def test_valid_but_inconsistent_or_truncated_output_is_not_successful_evidence(self):
        runner = load_runner(self)
        mismatch = replies(result={**ASSESSMENT, "prior_tier": "Understand", "tier": "Create"})
        truncated = replies()
        truncated[-1]["finish_reason"] = "length"
        with ScriptedServer(mismatch + truncated), fixture_sources():
            report = await runner.run_evaluation([case("mismatch"), case("truncated")])
        first, second = [episode["observations"][0] for episode in report["cases"]]
        self.assertEqual(first["execution"], "failed")
        self.assertEqual(first["uca_output"]["tier"], "Create")
        self.assertEqual(first["store_after"]["information-hiding"]["tier"], "Apply")
        self.assertFalse(first["persistence"]["checks"]["output_matches_store"])
        self.assertEqual(second["execution"], "failed")
        self.assertEqual(second["metrics"]["truncated_model_calls"], 1)
        self.assertEqual(report["quality"], "not_reviewed")

    async def test_initialized_service_is_refused(self):
        runner = load_runner(self)
        from edbot import service
        sentinel = object()
        with patch.object(service, "_agent", sentinel), self.assertRaisesRegex(RuntimeError, "already initialized"):
            await runner.run_evaluation([case()])
        self.assertIsNone(service._agent)


class AssessmentCommandTests(unittest.TestCase):
    def test_failed_inference_leaves_a_new_partial_report_with_review_unset(self):
        runner = load_runner(self)
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "cases.json"
            fixture.write_text(json.dumps({"schema_version": 1, "suite_kind": "uca_component", "cases": [case()]}))
            output = Path(directory) / "failed.json"
            with ScriptedServer(replies()[:-1] + [{"error": "fixture CLI failure"}]), fixture_sources(), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = runner.main(["--cases-file", str(fixture), "--output", str(output)])
            self.assertEqual(code, 1)
            result = json.loads(output.read_text())
            self.assertEqual(result["execution"], "failed")
            self.assertEqual(result["quality"], "not_reviewed")
            self.assertIsNone(result["cases"][0]["review"])
            observed = result["cases"][0]["observations"][0]
            self.assertIn("fixture CLI failure", observed["error"])
            self.assertEqual(observed["store_after"]["information-hiding"]["tier"], "Apply")


if __name__ == "__main__":
    unittest.main()
