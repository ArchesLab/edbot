"""Code-owned assessment persistence must be exact, isolated and replay-safe."""
import asyncio
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import aiosqlite
from langchain.agents.middleware.types import ToolCallRequest
from langchain.tools import ToolRuntime
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.store.memory import InMemoryStore
from langgraph.store.sqlite.aio import AsyncSqliteStore
from langgraph.types import Command

from edbot import model_config, student_model
from edbot.interface_def import EdbotContext, Message
from test_sglang_integration import ScriptedServer, text_reply, tool_reply


OUTPUT = {"concept": "recursion", "prior_tier": None, "tier": "Understand", "confidence": "low",
          "rationale": "The learner explained why recursion needs a stopping case.",
          "answer_judgment": None, "next_probe_tier": None}


def middleware(test):
    path = Path(__file__).resolve().parents[1] / "src/edbot/middleware/assessment_result.py"
    test.assertTrue(path.exists(), "Deterministic assessment persistence is not implemented")
    return importlib.import_module("edbot.middleware.assessment_result").AssessmentResultMiddleware()


def request(store, *, student="alice", call_id="assessment-1", turn=1, concept="recursion"):
    call = {"name": "task", "id": call_id, "type": "tool_call", "args": {
        "subagent_type": "understanding-checking-agent", "description": json.dumps({
            "concept": concept, "invocation_context": "new_evidence"})}}
    conversation = [Message(role="student", content=f"Learner evidence {index}.") for index in range(turn)]
    state = {"conversation": conversation, "messages": [HumanMessage(content=conversation[-1].content, id=f"turn-{turn}")]}
    runtime = ToolRuntime(state=state, context=EdbotContext(student_id=student),
                          config={"configurable": {"thread_id": student}}, stream_writer=lambda _: None,
                          tool_call_id=call_id, store=store)
    return ToolCallRequest(tool_call=call, tool=None, state=state, runtime=runtime)


def result(req, output=OUTPUT, *, command=True, status="success", call_id=None):
    message = ToolMessage(content=json.dumps(output), name="task", status=status,
                          tool_call_id=call_id or req.tool_call["id"])
    return Command(update={"messages": [message], "conversation": req.state["conversation"]}) if command else message


async def no_generation(req):
    raise AssertionError("A completed task replay must not run the child again")


class AssessmentResultTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        self.flag = patch.object(model_config, "DETERMINISTIC_ASSESSMENT_SAVE", True, create=True)
        self.flag.start()
        self.addCleanup(self.flag.stop)

    async def test_exact_structured_result_is_saved_once_and_replayed_without_child(self):
        mw, store = middleware(self), InMemoryStore()
        req = request(store)

        async def child(checked):
            return result(checked)

        first = await mw.awrap_tool_call(req, child)
        saved = await student_model.load_entry(store, "alice", "recursion")
        self.assertEqual((saved.tier, saved.confidence, saved.rationale),
                         ("Understand", "low", OUTPUT["rationale"]))
        self.assertEqual((saved.assessment_count, saved.assessed_at_turn), (1, 1))
        self.assertEqual(json.loads(first.update["messages"][0].content), OUTPUT)
        replay = await mw.awrap_tool_call(req, no_generation)
        self.assertEqual(json.loads(replay.content), OUTPUT)
        self.assertEqual(await student_model.load_entry(store, "alice", "recursion"), saved)
        self.assertEqual(set(await student_model.load_all(store, "alice")), {"recursion"})

    async def test_task_retry_survives_sqlite_connection_restart_without_increment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "student-model.sqlite"
            async with aiosqlite.connect(path, isolation_level=None) as conn:
                store = AsyncSqliteStore(conn)
                await store.setup()
                req = request(store)
                async def child(checked):
                    return result(checked, command=False)
                await middleware(self).awrap_tool_call(req, child)
                saved = await student_model.load_entry(store, "alice", "recursion")
            # Simulate a process loss after the store write, before the parent checkpoint.
            async with aiosqlite.connect(path, isolation_level=None) as conn:
                store = AsyncSqliteStore(conn)
                await store.setup()
                replay = await middleware(self).awrap_tool_call(request(store), no_generation)
                self.assertEqual(json.loads(replay.content), OUTPUT)
                self.assertEqual(await student_model.load_entry(store, "alice", "recursion"), saved)

    async def test_same_id_is_isolated_by_student_and_cannot_be_reused_for_other_input(self):
        mw, store = middleware(self), InMemoryStore()
        async def child(req):
            return result(req)
        await mw.awrap_tool_call(request(store), child)
        await mw.awrap_tool_call(request(store, student="bob"), child)
        self.assertEqual((await student_model.load_entry(store, "bob", "recursion")).assessment_count, 1)
        with self.assertRaisesRegex(ValueError, "identity|input|collision"):
            await mw.awrap_tool_call(request(store, concept="queues"), no_generation)
        self.assertIsNone(await student_model.load_entry(store, "alice", "queues"))

    async def test_older_receipt_and_out_of_date_turn_cannot_overwrite_newer_assessment(self):
        mw, store = middleware(self), InMemoryStore()
        async def first(req):
            return result(req)
        await mw.awrap_tool_call(request(store), first)
        async def second(req):
            return result(req, {**OUTPUT, "prior_tier": "Understand", "tier": "Apply"})
        await mw.awrap_tool_call(request(store, call_id="assessment-2", turn=2), second)
        newest = await student_model.load_entry(store, "alice", "recursion")
        for stale in (request(store), request(store, call_id="old-unfinished")):
            with self.subTest(call=stale.tool_call["id"]), self.assertRaisesRegex(ValueError, "stale|newer"):
                await mw.awrap_tool_call(stale, no_generation)
        self.assertEqual(await student_model.load_entry(store, "alice", "recursion"), newest)
        self.assertEqual(newest.assessment_count, 2)

    async def test_parallel_same_concept_tasks_use_each_others_committed_prior(self):
        mw, store = middleware(self), InMemoryStore()
        observed = []
        async def child(req):
            prior = await student_model.load_entry(store, "alice", "recursion")
            observed.append(prior.assessment_count if prior else 0)
            await asyncio.sleep(0)
            return result(req, {**OUTPUT, "prior_tier": prior.tier if prior else None})
        await asyncio.gather(mw.awrap_tool_call(request(store), child),
                             mw.awrap_tool_call(request(store, call_id="assessment-2"), child))
        self.assertEqual(observed, [0, 1])
        self.assertEqual((await student_model.load_entry(store, "alice", "recursion")).assessment_count, 2)

    async def test_invalid_failed_mismatched_and_prior_inconsistent_results_never_write(self):
        bad = [({**OUTPUT, "concept": "queues"}, {}), ({**OUTPUT, "prior_tier": "Apply"}, {}),
               ({**OUTPUT, "rationale": ""}, {}), (OUTPUT, {"status": "error"}),
               (OUTPUT, {"call_id": "wrong-call"}), ({"tier": "Understand"}, {}),
               ({**OUTPUT, "answer_judgment": {"verdict": "correct", "note": "No submitted answer exists"}}, {})]
        for output, options in bad:
            with self.subTest(output=output, options=options):
                mw, store = middleware(self), InMemoryStore()
                async def child(req):
                    return result(req, output, **options)
                with self.assertRaises((ValueError, TypeError)):
                    await mw.awrap_tool_call(request(store), child)
                self.assertEqual(await student_model.load_all(store, "alice"), {})

    async def test_child_failure_and_missing_student_identity_do_not_write(self):
        mw, store = middleware(self), InMemoryStore()
        async def failed(req):
            raise RuntimeError("child failed")
        with self.assertRaisesRegex(RuntimeError, "child failed"):
            await mw.awrap_tool_call(request(store), failed)
        with self.assertRaisesRegex(ValueError, "student"):
            await mw.awrap_tool_call(request(store, student=""), no_generation)
        self.assertEqual(await student_model.load_all(store, "alice"), {})

    async def test_commit_acknowledgement_loss_replays_exact_receipt_without_reassessment(self):
        class LostAcknowledgement(InMemoryStore):
            lose_ack = True

            async def abatch(self, operations):
                from langgraph.store.base import PutOp
                operations = list(operations)
                result = await super().abatch(operations)
                if self.lose_ack and any(isinstance(op, PutOp) for op in operations):
                    self.lose_ack = False
                    raise OSError("commit acknowledgement lost")
                return result

        store, mw = LostAcknowledgement(), middleware(self)
        async def child(req):
            return result(req)
        with self.assertRaisesRegex(OSError, "acknowledgement lost"):
            await mw.awrap_tool_call(request(store), child)
        entry = await student_model.load_entry(store, "alice", "recursion")
        self.assertEqual(entry.assessment_count, 1)
        replay = await mw.awrap_tool_call(request(store), no_generation)
        self.assertEqual(json.loads(replay.content), OUTPUT)
        self.assertEqual(await student_model.load_entry(store, "alice", "recursion"), entry)

    async def test_corrupt_or_unsupported_receipt_fails_closed(self):
        for changes in ({"version": 99}, {"output": {**OUTPUT, "concept": "queues"}},
                        {"output": {**OUTPUT, "tier": "Create"}}):
            with self.subTest(changes=changes):
                store, mw = InMemoryStore(), middleware(self)
                async def child(req):
                    return result(req)
                await mw.awrap_tool_call(request(store), child)
                saved = await student_model.load_entry(store, "alice", "recursion")
                receipts = await store.asearch(("students", "alice", "assessment_receipts"))
                receipt = receipts[0]
                await store.aput(receipt.namespace, receipt.key, {**receipt.value, **changes})
                with self.assertRaisesRegex(ValueError, "receipt"):
                    await mw.awrap_tool_call(request(store), no_generation)
                self.assertEqual(await student_model.load_entry(store, "alice", "recursion"), saved)

    async def test_disabled_flag_and_other_tools_keep_existing_flow(self):
        mw, store = middleware(self), InMemoryStore()
        sentinel = ToolMessage(content="baseline result", tool_call_id="baseline")
        async def child(req):
            return sentinel
        with patch.object(model_config, "DETERMINISTIC_ASSESSMENT_SAVE", False):
            self.assertIs(await mw.awrap_tool_call(request(store), child), sentinel)
        req = request(store)
        req = req.override(tool_call={**req.tool_call, "name": "fetch_student_data"})
        self.assertIs(await mw.awrap_tool_call(req, child), sentinel)
        self.assertEqual(await student_model.load_all(store, "alice"), {})


class AssessmentCompletionTests(unittest.TestCase):
    def test_sync_passthrough_preserves_legacy_and_non_assessment_tool_apis(self):
        mw = middleware(self)
        store = InMemoryStore()
        sentinel = ToolMessage(content="baseline result", tool_call_id="baseline")
        with patch.object(model_config, "DETERMINISTIC_ASSESSMENT_SAVE", False):
            self.assertIs(mw.wrap_tool_call(request(store), lambda _: sentinel), sentinel)
        with patch.object(model_config, "DETERMINISTIC_ASSESSMENT_SAVE", True):
            req = request(store)
            other = req.override(tool_call={**req.tool_call, "args": {**req.tool_call["args"],
                                  "subagent_type": "content-generating-agent"}})
            self.assertIs(mw.wrap_tool_call(other, lambda _: sentinel), sentinel)
            with self.assertRaisesRegex(NotImplementedError, "async|ainvoke|astream"):
                mw.wrap_tool_call(req, lambda _: sentinel)

    def test_uca_output_is_deferred_until_pending_lookup_finishes(self):
        from langchain.agents.middleware.types import ModelRequest, ModelResponse
        from langchain_core.messages import AIMessage
        from edbot.interface_def import UCAOutput
        from edbot.middleware.direct_content import CompleteContentMiddleware
        self.assertIn("output_tool", __import__("inspect").signature(CompleteContentMiddleware).parameters,
                      "Completion guard is not configurable for the assessment output")
        mw = CompleteContentMiddleware(output_tool="UCAOutput", reject_tool_errors=True)
        calls = [{"name": "fetch_student_data", "args": {"concept": "recursion"}, "id": "fetch", "type": "tool_call"},
                 {"name": "UCAOutput", "args": OUTPUT, "id": "output", "type": "tool_call"}]
        response = ModelResponse(result=[AIMessage(content="", tool_calls=calls),
                                        ToolMessage(content="Premature", tool_call_id="output", name="UCAOutput")],
                                 structured_response=UCAOutput.model_validate(OUTPUT))
        deferred = mw.wrap_model_call(ModelRequest(model=None, messages=[], state={}, tools=[]), lambda _: response)
        self.assertIsNone(deferred.structured_response)
        self.assertEqual(deferred.result[0].tool_calls, [calls[0]])
        self.assertEqual(len(deferred.result), 1)
        for latest in (AIMessage(content="", response_metadata={"finish_reason": "length"}),
                       AIMessage(content="", invalid_tool_calls=[{"name": "fetch_student_data", "args": "{",
                                 "id": "broken", "error": "Invalid JSON", "type": "invalid_tool_call"}])):
            with self.assertRaises(ValueError):
                mw.after_model({"messages": [latest]}, None)
        with self.assertRaisesRegex(ValueError, "tool.*fail|failed.*tool"):
            mw.after_model({"messages": [ToolMessage(content="fetch failed", tool_call_id="fetch", status="error"),
                                         AIMessage(content="", tool_calls=[calls[1]])]}, None)
        failed = Command(update={"messages": [ToolMessage(content="fetch failed", tool_call_id="fetch", status="error")]})
        with self.assertRaisesRegex(ValueError, "tool.*fail|failed.*tool"):
            mw.wrap_tool_call(None, lambda _: failed)
        self.assertIs(CompleteContentMiddleware().wrap_tool_call(None, lambda _: failed), failed)


class AssessmentGraphTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)

    async def run_graph(self, responses, *, enabled=True, student="assessment-integration"):
        from langgraph.checkpoint.memory import InMemorySaver
        from edbot import edbot_agent, service

        store = InMemoryStore()
        # This component fixture checks persistence independently of parent tutoring routing.
        with ScriptedServer(responses) as server, patch.object(edbot_agent, "load_sebook_store"), \
                patch.object(model_config, "DETERMINISTIC_ASSESSMENT_SAVE", enabled), \
                patch.object(model_config, "REQUIRE_CONTENT_AFTER_ASSESSMENT", False), \
                patch.object(service.logger, "exception"):
            agent = edbot_agent.create_edbot_agent(checkpointer=InMemorySaver(serde=service.SERDE), store=store)
            with patch.object(service, "_agent", agent):
                events = [event async for event in service.chat_turn(student, "Recursion needs a stopping case.")]
            snapshot = await agent.aget_state(service.config_for(student))
        return events, store, snapshot, server

    async def test_real_child_returns_one_assessment_without_model_write_and_parent_sees_saved_exact_result(self):
        task = {"subagent_type": "understanding-checking-agent", "description": json.dumps({
            "concept": "recursion", "invocation_context": "new_evidence"})}
        events, store, snapshot, server = await self.run_graph([
            tool_reply("task", task), tool_reply("fetch_student_data", {"concept": "recursion"}),
            tool_reply("UCAOutput", OUTPUT), text_reply("Let's test that idea with one example.")])
        self.assertEqual(events[-1].type, "done", events)
        entry = await student_model.load_entry(store, "assessment-integration", "recursion")
        self.assertIsNotNone(entry, "The complete UCA result must be saved by code")
        self.assertEqual((entry.assessment_count, entry.rationale), (1, OUTPUT["rationale"]))
        self.assertEqual(len(server.requests), 4)
        for _, payload in server.requests[1:3]:
            self.assertNotIn("update_student_model", [tool["function"]["name"] for tool in payload["tools"]])
        parent_input = server.requests[-1][1]["messages"]
        private = next(message["content"] for message in parent_input if message["role"] == "tool")
        self.assertEqual(json.loads(private), OUTPUT)
        self.assertFalse(any(OUTPUT["rationale"] in event.text for event in events if event.type == "text"))

    async def test_truncated_valid_output_and_failed_tool_never_save(self):
        task = {"subagent_type": "understanding-checking-agent", "description": json.dumps({
            "concept": "recursion", "invocation_context": "new_evidence"})}
        truncated = tool_reply("UCAOutput", OUTPUT)
        truncated["finish_reason"] = "length"
        for responses in ([tool_reply("task", task), truncated],
                          [tool_reply("task", task), tool_reply("nonexistent_tool", {})]):
            with self.subTest(responses=responses):
                events, store, _, server = await self.run_graph(responses)
                self.assertEqual(events[-1].type, "error")
                self.assertEqual(await student_model.load_all(store, "assessment-integration"), {})
                self.assertEqual(len(server.requests), len(responses), "The guard must fail before parent synthesis")

    async def test_final_assessment_waits_for_simultaneous_prior_lookup(self):
        task = {"subagent_type": "understanding-checking-agent", "description": json.dumps({
            "concept": "recursion", "invocation_context": "new_evidence"})}
        simultaneous = {"finish_reason": "tool_calls", "deltas": [{"role": "assistant", "content": "",
            "tool_calls": [
                {"index": 0, "id": "lookup", "type": "function", "function": {
                    "name": "fetch_student_data", "arguments": json.dumps({"concept": "recursion"})}},
                {"index": 1, "id": "premature", "type": "function", "function": {
                    "name": "UCAOutput", "arguments": json.dumps({**OUTPUT, "rationale": "PREMATURE"})}},
            ]}]}
        events, store, _, server = await self.run_graph([
            tool_reply("task", task), simultaneous, tool_reply("UCAOutput", OUTPUT), text_reply("One example next.")])
        self.assertEqual(events[-1].type, "done")
        entry = await student_model.load_entry(store, "assessment-integration", "recursion")
        self.assertEqual((entry.rationale, entry.assessment_count), (OUTPUT["rationale"], 1))
        second_child_request = server.requests[2][1]["messages"]
        self.assertTrue(any(message["role"] == "tool" and "No prior assessment" in message["content"]
                            for message in second_child_request))
        self.assertNotIn("PREMATURE", json.dumps(second_child_request))

    async def test_baseline_flag_retains_model_owned_write_tool(self):
        task = {"subagent_type": "understanding-checking-agent", "description": json.dumps({
            "concept": "recursion", "invocation_context": "new_evidence"})}
        write = {key: OUTPUT[key] for key in ("concept", "tier", "confidence", "rationale")}
        events, store, _, server = await self.run_graph([
            tool_reply("task", task), tool_reply("update_student_model", write),
            tool_reply("UCAOutput", OUTPUT), text_reply("Let's test that idea.")], enabled=False)
        self.assertEqual(events[-1].type, "done")
        self.assertIn("update_student_model", [tool["function"]["name"] for tool in server.requests[1][1]["tools"]])
        self.assertEqual((await student_model.load_entry(store, "assessment-integration", "recursion")).assessment_count, 1)


if __name__ == "__main__":
    unittest.main()
