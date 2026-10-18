"""Parallel specialists may read parent context but must not write it back."""
import asyncio
from copy import deepcopy
import json
import sys
import unittest
from unittest.mock import patch

import httpx
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command, Send

from edbot import model_config, student_model
from edbot.middleware.conversation_history import ConversationMiddleware
from test_sglang_integration import complete_message, text_reply

UCA, CGA = "understanding-checking-agent", "content-generating-agent"
ASSESSMENT = {"concept": "recursion", "prior_tier": None, "tier": "Understand", "confidence": "low",
              "rationale": "PRIVATE_ASSESSMENT: the learner identified a stopping case."}
CONTENT = {"concept": "recursion", "mode": "explain_at_tier", "target_tier": "Understand",
           "content": "PRIVATE_PARALLEL_CONTENT", "sources": []}


def request(name="task"):
    return ToolCallRequest(tool_call={"name": name, "id": "original-call", "type": "tool_call",
                                     "args": {}}, tool=None, state={}, runtime=None)


def calls_reply(calls):
    return {"finish_reason": "tool_calls", "deltas": [{"role": "assistant", "content": "",
        "tool_calls": [{"index": index, "id": identifier, "type": "function", "function": {
            "name": name, "arguments": json.dumps(arguments)}}
            for index, (name, identifier, arguments) in enumerate(calls)]}]}


class ParentContextResultTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, req, output, *, sync):
        def handler(checked):
            self.assertIs(checked, req, "The child must receive the unchanged parent context")
            return output
        async def async_handler(checked):
            return handler(checked)
        mw = ConversationMiddleware()
        return mw.wrap_tool_call(req, handler) if sync else await mw.awrap_tool_call(req, async_handler)

    async def test_strips_only_inherited_context_without_mutating_command_or_other_fields(self):
        message = ToolMessage(content=json.dumps(ASSESSMENT), tool_call_id="original-call", name="task")
        output = Command(graph=Command.PARENT, update={
            "conversation": ["parent conversation"], "course_evidence": [{"content": "parent evidence"}],
            "messages": [message], "files": {"/new.txt": {"content": ["retained"]}},
            "structured_response": {"assessment": "retained"}, "future_state": {"value": 3}},
            resume={"interrupt-id": "resume-value"}, goto=[Send("next-node", {"value": 4})])
        original = deepcopy(output)
        for sync in (False, True):
            with self.subTest(sync=sync):
                result = await self.invoke(request(), output, sync=sync)
                self.assertIsNot(result, output)
                self.assertEqual(set(result.update), {"messages", "files", "structured_response", "future_state"})
                self.assertEqual(output, original)
                for key, value in result.update.items():
                    self.assertIs(value, output.update[key])
                for field in ("graph", "resume", "goto"):
                    self.assertIs(getattr(result, field), getattr(output, field))
                self.assertIs(result.update["messages"][0], message)
                self.assertEqual(message.tool_call_id, "original-call")

    async def test_non_task_and_other_result_forms_are_returned_unchanged(self):
        cases = [("search_markdown_sources", Command(update={"conversation": ["owned by this tool"]})),
                 ("task", ToolMessage(content="legacy text", tool_call_id="original-call")),
                 ("task", Command(update=[("conversation", ["non-dictionary command"])])),
                 ("task", Command(update={"files": {"/retained": "value"}})),
                 ("task", Command(update=None)), ("task", {"conversation": ["ordinary result"]})]
        for sync in (False, True):
            for name, output in cases:
                with self.subTest(sync=sync, name=name, output=output):
                    self.assertIs(await self.invoke(request(name), output, sync=sync), output)


class ParallelChildContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)

    async def test_parallel_typed_and_legacy_tasks_keep_context_and_require_causal_content(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                await self.run_parallel_turn(legacy)

    async def run_parallel_turn(self, legacy):
        from edbot import edbot_agent, service
        requests, child_requests, parent_requests, errors = [], [], [], []
        sibling_started = asyncio.Event()
        store = InMemoryStore()
        passages = {"recursion": "SOURCE_RECURSION: recurse on a smaller input.",
                    "base case": "SOURCE_STOP: handle a stopping case."}

        @tool
        def search_markdown_sources(query: str) -> str:
            """Return one of two distinct synthetic course passages."""
            return passages[query]

        def task_args(role):
            description = ({"concept": "recursion", "invocation_context": "new_evidence"} if role == UCA
                           else {"concept": "recursion", "target_tier": "Understand", "mode": "explain_at_tier"})
            return {"subagent_type": role, "description": json.dumps(description) if legacy else description}

        async def handler(request):
            payload = json.loads(request.content)
            requests.append(payload)
            names = {item.get("function", {}).get("name") for item in payload.get("tools", [])}
            self.assertFalse(payload["stream"])
            if names & {"UCAOutput", "CGAOutput"}:
                child_requests.append(payload)
                # Both original siblings must enter generation before either
                # returns; avoid relying on task/thread scheduling order.
                if len(child_requests) <= 2:
                    if len(child_requests) == 2:
                        sibling_started.set()
                    await asyncio.wait_for(sibling_started.wait(), timeout=3)
                if "UCAOutput" in names:
                    reply = calls_reply([("UCAOutput", "assessment-output", ASSESSMENT)])
                else:
                    reply = calls_reply([("CGAOutput", f"content-output-{len(child_requests)}",
                        {**CONTENT, "content": "FRESH_CONTENT" if len(child_requests) == 3 else CONTENT["content"]})])
            else:
                parent_requests.append(payload)
                stage = len(parent_requests)
                if stage == 1:
                    reply = text_reply("Earlier public reply.")
                elif stage == 2:
                    reply = calls_reply([("search_markdown_sources", "search-recursion", {"query": "recursion"}),
                                         ("search_markdown_sources", "search-stop", {"query": "base case"})])
                elif stage == 3:
                    reply = calls_reply([("task", "parallel-uca", task_args(UCA)),
                                         ("task", "parallel-cga", task_args(CGA))])
                elif stage == 4:
                    reply = calls_reply([("task", "causal-cga", task_args(CGA))])
                elif stage == 5:
                    reply = text_reply("What changes when recursion reaches its stopping case?")
                else:
                    raise AssertionError("Unexpected extra parent generation")
            return httpx.Response(200, json={"id": f"fixture-{len(requests)}", "object": "chat.completion",
                "created": 1, "model": model_config.MODEL_NAME,
                "choices": [{"index": 0, "message": complete_message(reply), "finish_reason": reply["finish_reason"]}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            model = ChatOpenAI(model=model_config.MODEL_NAME, base_url="http://parallel-test.invalid/v1",
                api_key="local-test", http_async_client=http, use_responses_api=False,
                disable_streaming="tool_calling", max_retries=0)
            with patch.object(edbot_agent, "create_chat_model", return_value=model), \
                    patch.object(edbot_agent, "load_sebook_store"), \
                    patch.object(edbot_agent.tools, "search_markdown_sources", search_markdown_sources), \
                    patch.object(model_config, "REDUCED_TUTOR_HARNESS", True), \
                    patch.object(model_config, "REUSE_COURSE_EVIDENCE", True), \
                    patch.object(model_config, "DETERMINISTIC_ASSESSMENT_SAVE", True), \
                    patch.object(model_config, "REQUIRE_CONTENT_AFTER_ASSESSMENT", True), \
                    patch.object(service.logger, "exception", side_effect=lambda *args, **kwargs: errors.append(sys.exc_info()[1])):
                graph = edbot_agent.create_edbot_agent(checkpointer=InMemorySaver(serde=service.SERDE), store=store)
                with patch.object(service, "_agent", graph):
                    earlier = [event async for event in service.chat_turn("parallel-student", "Earlier public question.")]
                    self.assertEqual(earlier[-1].type, "done")
                    events = [event async for event in service.chat_turn("parallel-student", "Recursion needs a stopping case.")]
                    self.assertEqual(events[-1].type, "done", [str(error) for error in errors] or events)
                    history = await service.get_history("parallel-student")
                snapshot = await graph.aget_state(service.config_for("parallel-student"))

        self.assertTrue(sibling_started.is_set())
        self.assertEqual(len(child_requests), 3, "A parallel CGA cannot discharge the post-assessment obligation")
        self.assertEqual(len(parent_requests), 5)
        self.assertNotEqual(parent_requests[2].get("parallel_tool_calls"), False)
        constrained = parent_requests[3]
        self.assertEqual(constrained["tool_choice"], {"type": "function", "function": {"name": "task"}})
        self.assertEqual(constrained["tools"][0]["function"]["parameters"]["properties"]["subagent_type"]["const"], CGA)
        expected_public = ["Earlier public question.", "Earlier public reply.", "Recursion needs a stopping case."]
        expected_evidence = [{"query": query, "path_prefix": "", "content": content} for query, content in passages.items()]
        for child in child_requests:
            messages = child["messages"]
            self.assertEqual([message["role"] for message in messages[1:4]], ["user", "assistant", "user"])
            self.assertEqual([message["content"] for message in messages[1:4]], expected_public)
            self.assertEqual(json.loads(messages[4]["content"]), {"course_evidence": expected_evidence})
        self.assertEqual([message.content for message in snapshot.values["conversation"]], expected_public)
        self.assertEqual(snapshot.values["course_evidence"], expected_evidence)
        self.assertEqual([message.content for message in history], [*expected_public,
            "What changes when recursion reaches its stopping case?"])
        self.assertNotIn("PRIVATE_", "".join(event.model_dump_json() for event in events))
        tool_results = {message.tool_call_id: message for message in snapshot.values["messages"] if isinstance(message, ToolMessage)}
        self.assertTrue({"parallel-uca", "parallel-cga", "causal-cga"}.issubset(tool_results))
        self.assertEqual(json.loads(tool_results["parallel-uca"].content)["rationale"], ASSESSMENT["rationale"])
        self.assertEqual(json.loads(tool_results["parallel-cga"].content)["content"], CONTENT["content"])
        self.assertEqual(json.loads(tool_results["causal-cga"].content)["content"], "FRESH_CONTENT")
        saved = await student_model.load_entry(store, "parallel-student", "recursion")
        self.assertEqual((saved.assessment_count, saved.rationale), (1, ASSESSMENT["rationale"]))


if __name__ == "__main__":
    unittest.main()
