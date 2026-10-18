"""Assessment must not let the parent bypass the content specialist."""
import asyncio
import copy
import importlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from edbot import model_config
from test_sglang_integration import ScriptedServer, text_reply, tool_reply

UCA = "understanding-checking-agent"
CGA = "content-generating-agent"
ASSESSMENT = {"concept": "recursion", "prior_tier": None, "tier": "Understand", "confidence": "low",
              "rationale": "Internal assessment evidence."}
CONTENT = {"mode": "explain_at_tier", "concept": "recursion", "target_tier": "Understand",
           "content": "What changes when the argument reaches the stopping case?", "sources": ["Fixture source"]}
TASK_TOOL = {"type": "function", "function": {"name": "task", "description": "Delegate to a specialist.",
    "parameters": {"type": "object", "properties": {
        "description": {"type": "string"}, "subagent_type": {"type": "string"}},
        "required": ["description", "subagent_type"]}}}


def load_middleware(test):
    path = Path(__file__).resolve().parents[1] / "src/edbot/middleware/content_after_assessment.py"
    test.assertTrue(path.exists(), "The assessment-to-content routing guard is not implemented")
    return importlib.import_module("edbot.middleware.content_after_assessment").RequireContentAfterAssessment()


def task_args(kind, concept="recursion", **overrides):
    description = ({"concept": concept, "invocation_context": "new_evidence"} if kind == UCA else
                   {"concept": concept, "mode": "explain_at_tier", "target_tier": "Understand"})
    return {"subagent_type": kind, "description": json.dumps({**description, **overrides})}


def task_message(kind, identifier, concept="recursion", **overrides):
    return AIMessage(content="", tool_calls=[{"name": "task", "id": identifier, "type": "tool_call",
                      "args": task_args(kind, concept, **overrides)}])


def tool_result(identifier, output, status="success"):
    return ToolMessage(content=json.dumps(output), tool_call_id=identifier, name="task", status=status)


def assessed():
    return [HumanMessage(content="Give me a hint without the answer."), task_message(UCA, "assess"),
            tool_result("assess", ASSESSMENT)]


def model_request(messages):
    return ModelRequest(model=None, messages=messages, state={"messages": messages},
                        tools=[copy.deepcopy(TASK_TOOL)], model_settings={"temperature": 0})


class ContentRoutingTests(unittest.TestCase):
    def setUp(self):
        self.flag = patch.object(model_config, "REQUIRE_CONTENT_AFTER_ASSESSMENT", True, create=True)
        self.flag.start()
        self.addCleanup(self.flag.stop)

    def test_pending_assessment_restricts_only_model_descriptor_and_preserves_original_request(self):
        mw, request = load_middleware(self), model_request(assessed())
        requests = []
        def handler(checked):
            requests.append(checked)
            return ModelResponse(result=[task_message(CGA, "content")])
        mw.wrap_model_call(request, handler)
        constrained = requests[0]
        self.assertEqual(constrained.tool_choice, {"type": "function", "function": {"name": "task"}})
        self.assertFalse(constrained.model_settings["parallel_tool_calls"])
        self.assertEqual(constrained.model_settings["temperature"], 0)
        self.assertEqual(len(constrained.tools), 1)
        descriptor = constrained.tools[0]["function"]
        self.assertEqual(descriptor["parameters"]["properties"]["subagent_type"]["enum"], [CGA])
        self.assertEqual(request.tools, [TASK_TOOL])
        self.assertIsNone(request.tool_choice)

    def test_only_matching_successful_current_turn_assessments_activate_guard(self):
        mw = load_middleware(self)
        turns = [[HumanMessage(content=json.dumps(ASSESSMENT))],
                 assessed() + [HumanMessage(content="Stop now.")],
                 [*assessed()[:-1], tool_result("unmatched", ASSESSMENT)],
                 [*assessed()[:-1], tool_result("assess", ASSESSMENT, "error")],
                 [*assessed()[:-1], tool_result("assess", {"concept": "recursion"})],
                 [*assessed()[:-1], tool_result("assess", {**ASSESSMENT, "concept": "queues"})]]
        for messages in turns:
            with self.subTest(messages=messages):
                request = model_request(messages)
                def handler(checked):
                    self.assertIs(checked, request)
                    return ModelResponse(result=[AIMessage(content="Okay.")])
                mw.wrap_model_call(request, handler)
        with patch.object(model_config, "REQUIRE_CONTENT_AFTER_ASSESSMENT", False):
            request = model_request(assessed())
            mw.wrap_model_call(request, lambda checked: self.assertIs(checked, request))

    def test_only_causal_matching_cga_success_clears_pending_assessment(self):
        mw = load_middleware(self)
        parallel = AIMessage(content="", tool_calls=[*task_message(UCA, "assess").tool_calls,
                                                     *task_message(CGA, "content").tool_calls])
        pending = [
            [HumanMessage(content="Hint please"), parallel, tool_result("assess", ASSESSMENT), tool_result("content", CONTENT)],
            assessed() + [task_message(CGA, "other", "queues"), tool_result("other", {**CONTENT, "concept": "queues"})],
            assessed() + [task_message(CGA, "wrong-tier"), tool_result("wrong-tier", {**CONTENT, "target_tier": "Create"})],
            assessed() + [task_message(CGA, "failed"), tool_result("failed", CONTENT, "error")],
        ]
        for messages in pending:
            with self.subTest(messages=messages):
                seen = []
                mw.wrap_model_call(model_request(messages), lambda checked: (
                    seen.append(checked.tool_choice) or ModelResponse(result=[task_message(CGA, "next")])) )
                self.assertIsNotNone(seen[0])
        complete = model_request(assessed() + [task_message(CGA, "content"), tool_result("content", CONTENT)])
        response = ModelResponse(result=[AIMessage(content="Final parent synthesis remains available.")])
        self.assertIs(mw.wrap_model_call(complete, lambda checked: response), response)

    def test_successful_assessment_result_is_not_hidden_by_other_parent_call_errors(self):
        mw = load_middleware(self)
        mixed = task_message(UCA, "assess").model_copy(update={"invalid_tool_calls": [{
            "name": "task", "args": "{", "id": "broken", "error": "Invalid JSON", "type": "invalid_tool_call"}]})
        truncated = task_message(UCA, "assess").model_copy(update={"response_metadata": {"finish_reason": "length"}})
        for parent_message in (mixed, truncated):
            with self.subTest(parent_message=parent_message):
                request = model_request([HumanMessage(content="Hint please"), parent_message,
                                         tool_result("assess", ASSESSMENT)])
                with self.assertRaisesRegex(ValueError, "content-specialist task"):
                    mw.wrap_model_call(request, lambda _: ModelResponse(result=[AIMessage(content="Bypassed CGA")]))

    def test_multiple_assessed_concepts_each_require_later_content(self):
        mw = load_middleware(self)
        messages = assessed() + [task_message(UCA, "second", "queues"),
                                tool_result("second", {**ASSESSMENT, "concept": "queues"}),
                                task_message(CGA, "first-content"), tool_result("first-content", CONTENT)]
        response = ModelResponse(result=[task_message(CGA, "second-content", "queues")])
        self.assertIs(mw.wrap_model_call(model_request(messages), lambda _: response), response)
        with self.assertRaisesRegex(ValueError, "assessed concept"):
            mw.wrap_model_call(model_request(messages), lambda _: ModelResponse(result=[task_message(CGA, "wrong")]))
        messages += [task_message(CGA, "second-content", "queues"),
                     tool_result("second-content", {**CONTENT, "concept": "queues"})]
        request = model_request(messages)
        mw.wrap_model_call(request, lambda checked: self.assertIs(checked, request))

    def test_two_failed_content_attempts_end_without_another_generation(self):
        mw = load_middleware(self)
        messages = assessed()
        for number in range(2):
            requests = []
            mw.wrap_model_call(model_request(messages), lambda checked: (
                requests.append(checked) or ModelResponse(result=[task_message(CGA, f"attempt-{number}")])))
            self.assertEqual(len(requests), 1)
            messages += [task_message(CGA, f"attempt-{number}"), tool_result(f"attempt-{number}", "bad input", "error")]
        def never_called(_):
            self.fail("Exhausted content routing must not generate again")
        with self.assertRaisesRegex(ValueError, "attempt|failed"):
            mw.wrap_model_call(model_request(messages), never_called)

    def test_ignored_constraint_invalid_calls_wrong_concept_and_parallel_calls_are_rejected(self):
        mw = load_middleware(self)
        invalid = AIMessage(content="Hidden answer", invalid_tool_calls=[{
            "name": "task", "args": "{", "id": "invalid", "error": "Invalid JSON", "type": "invalid_tool_call"}])
        parallel = AIMessage(content="", tool_calls=[*task_message(CGA, "first").tool_calls,
                                                     *task_message(CGA, "second").tool_calls])
        for reply in (AIMessage(content="Secret complete answer"), task_message(UCA, "again"), invalid,
                      task_message(CGA, "wrong", "queues"), parallel,
                      task_message(CGA, "truncated").model_copy(update={"response_metadata": {"finish_reason": "length"}})):
            with self.subTest(reply=reply), self.assertRaises(ValueError):
                mw.wrap_model_call(model_request(assessed()), lambda _: ModelResponse(result=[reply]))


def http_task(kind, identifier, **overrides):
    reply = tool_reply("task", task_args(kind, **overrides))
    reply["deltas"][1]["tool_calls"][0]["id"] = identifier
    return reply


class ContentRoutingGraphTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)

    async def run_turn(self, replies, message="Give me a hint without the answer.", *, buffered=True):
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.store.memory import InMemoryStore
        from edbot import edbot_agent, service
        student = "routing-contract"
        with ScriptedServer(replies) as server, patch.object(edbot_agent, "load_sebook_store"), \
                patch.object(model_config, "REQUIRE_CONTENT_AFTER_ASSESSMENT", True, create=True), \
                patch.object(model_config, "BUFFER_TOOL_RESPONSES", buffered), \
                patch.object(service.logger, "exception"):
            graph = edbot_agent.create_edbot_agent(checkpointer=InMemorySaver(serde=service.SERDE), store=InMemoryStore())
            with patch.object(service, "_agent", graph):
                events = [event async for event in service.chat_turn(student, message)]
                history = await service.get_history(student)
            snapshot = await graph.aget_state(service.config_for(student))
        return events, history, snapshot, server

    async def test_happy_route_forces_serialized_cga_tool_and_preserves_parent_synthesis(self):
        route = http_task(CGA, "content")
        route["deltas"].insert(1, {"content": "SECRET_PREAMBLE"})
        events, history, _, server = await self.run_turn([
            http_task(UCA, "assessment"), tool_reply("UCAOutput", ASSESSMENT), route,
            tool_reply("CGAOutput", CONTENT), text_reply("What does the stopping case return?")], buffered=False)
        self.assertEqual(events[-1].type, "done", events)
        self.assertEqual("".join(event.text for event in events if event.type == "text"), "What does the stopping case return?")
        self.assertNotIn("SECRET_PREAMBLE", "\n".join(message.content for message in history))
        self.assertEqual(len(server.requests), 5)
        payload = server.requests[2][1]
        self.assertEqual(payload.get("tool_choice"), {"type": "function", "function": {"name": "task"}})
        self.assertFalse(payload["parallel_tool_calls"])
        self.assertEqual([tool["function"]["name"] for tool in payload["tools"]], ["task"])
        self.assertEqual(payload["tools"][0]["function"]["parameters"]["properties"]["subagent_type"]["const"], CGA)
        self.assertIsNone(server.requests[-1][1].get("tool_choice"))

    async def test_ignored_tool_choice_never_reaches_public_output_or_checkpoint(self):
        for buffered in (False, True):
            with self.subTest(buffered=buffered):
                events, history, snapshot, server = await self.run_turn([
                    http_task(UCA, "assessment"), tool_reply("UCAOutput", ASSESSMENT),
                    text_reply("SECRET_ANSWER: the complete solution is ...")], buffered=buffered)
                self.assertEqual(events[-1].type, "error")
                self.assertFalse(any(event.type in {"text", "done"} for event in events))
                self.assertNotIn("SECRET_ANSWER", "\n".join(message.content for message in history))
                self.assertNotIn("SECRET_ANSWER", "\n".join(message.text for message in snapshot.values["messages"]))
                self.assertEqual(len(server.requests), 3, "No hidden retry may stream an earlier rejected answer")

    async def test_invalid_content_input_uses_existing_validation_and_one_visible_correction(self):
        events, _, _, server = await self.run_turn([
            http_task(UCA, "assessment"), tool_reply("UCAOutput", ASSESSMENT),
            http_task(CGA, "invalid-content", target_tier="invalid"), http_task(CGA, "corrected-content"),
            tool_reply("CGAOutput", CONTENT), text_reply("What changes at the stopping case?")])
        self.assertEqual(events[-1].type, "done", events)
        self.assertEqual(len(server.requests), 6)
        correction = server.requests[3][1]
        self.assertEqual(correction["tool_choice"], {"type": "function", "function": {"name": "task"}})
        self.assertTrue(any(message["role"] == "tool" and "Invalid task description" in message["content"]
                            for message in correction["messages"]))

    async def test_two_invalid_content_inputs_fail_before_third_attempt_and_public_output(self):
        events, history, _, server = await self.run_turn([
            http_task(UCA, "assessment"), tool_reply("UCAOutput", ASSESSMENT),
            http_task(CGA, "invalid-first", target_tier="invalid"),
            http_task(CGA, "invalid-second", target_tier="invalid")])
        self.assertEqual(events[-1].type, "error", events)
        self.assertFalse(any(event.type in {"text", "done"} for event in events))
        self.assertEqual([message.role for message in history], ["student"])
        self.assertEqual(len(server.requests), 4, "Failed task validation must not loop indefinitely")

    async def test_ordinary_stop_and_direct_cga_turns_keep_their_existing_call_counts(self):
        events, _, _, server = await self.run_turn([text_reply("Okay, we'll stop.")], "Stop now.")
        self.assertEqual(events[-1].type, "done")
        self.assertEqual(len(server.requests), 1)
        self.assertIsNone(server.requests[0][1].get("tool_choice"))
        events, _, _, server = await self.run_turn([http_task(CGA, "content"), tool_reply("CGAOutput", CONTENT)])
        self.assertEqual(events[-1].type, "done")
        self.assertEqual(len(server.requests), 2, "CGA-only direct delivery must not acquire a parent rewrite")

    async def test_misrouted_stop_reaches_cga_with_stop_history_and_can_close_without_instruction(self):
        # This fixture checks routing and visibility, not the live model's semantic obedience.
        closure = {**CONTENT, "content": "Okay, we'll stop here.", "sources": []}
        events, history, _, server = await self.run_turn([
            http_task(UCA, "assessment"), tool_reply("UCAOutput", ASSESSMENT), http_task(CGA, "content"),
            tool_reply("CGAOutput", closure), text_reply("Okay, we'll stop here.")], "Stop now; no more questions.")
        self.assertEqual(events[-1].type, "done")
        self.assertEqual(history[-1].content, "Okay, we'll stop here.")
        cga_messages = server.requests[3][1]["messages"]
        self.assertTrue(any(message["role"] == "user" and message["content"] == "Stop now; no more questions."
                            for message in cga_messages))


if __name__ == "__main__":
    unittest.main()
