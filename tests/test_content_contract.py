"""Preserve missing-source evidence through the real subagent protocol."""
import asyncio
import json
import unittest
from unittest.mock import patch

from test_sglang_integration import ScriptedServer, text_reply, tool_reply


class ContentDeferralTests(unittest.TestCase):
    def test_sync_deferral_keeps_real_tools_and_usage_without_premature_output(self):
        from langchain.agents.middleware.types import ModelRequest, ModelResponse
        from langchain_core.messages import AIMessage, ToolMessage
        from edbot.interface_def import CGAOutput
        from edbot.middleware.direct_content import CompleteContentMiddleware

        output = CGAOutput(mode="explain_at_tier", concept="queues", target_tier="Apply",
                           content="Premature LIFO claim", sources=["Unseen source"])
        calls = [
            {"name": "search_markdown_sources", "args": {"query": "queues"}, "id": "search", "type": "tool_call"},
            {"name": "CGAOutput", "args": output.model_dump(), "id": "premature", "type": "tool_call"},
        ]
        original = AIMessage(content="Premature LIFO claim", tool_calls=calls, id="model-call",
                             additional_kwargs={"tool_calls": [{"id": "premature", "function": {"name": "CGAOutput"}}]},
                             response_metadata={"finish_reason": "tool_calls"},
                             usage_metadata={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30})
        response = ModelResponse(result=[original, ToolMessage(content="Premature LIFO claim",
                                 tool_call_id="premature", name="CGAOutput")], structured_response=output)
        middleware = CompleteContentMiddleware()
        normalized = middleware.wrap_model_call(ModelRequest(model=None, messages=[], state={}, tools=[]),
                                               lambda request: response)
        self.assertIsNone(normalized.structured_response)
        self.assertEqual(len(normalized.result), 1)
        message = normalized.result[0]
        self.assertEqual(message.tool_calls, [calls[0]])
        self.assertEqual(message.content, "")
        self.assertNotIn("tool_calls", message.additional_kwargs)
        self.assertEqual(message.id, "model-call")
        self.assertEqual(message.usage_metadata["output_tokens"], 20)
        self.assertEqual(message.response_metadata["edbot_deferred_output_tool_ids"], ["premature"])
        self.assertEqual(original.content, "Premature LIFO claim")  # Preserve the original model response for tracing.
        self.assertEqual(len(original.tool_calls), 2)
        truncated = AIMessage(content="", response_metadata={"finish_reason": "length"})
        with self.assertRaisesRegex(ValueError, "output limit"):
            middleware.after_model({"messages": [truncated]}, None)

    def test_invalid_child_tool_calls_cannot_complete_a_structured_result(self):
        from langchain_core.messages import AIMessage
        from edbot.middleware.direct_content import CompleteContentMiddleware

        invalid = AIMessage(content="Unverified answer", invalid_tool_calls=[{
            "name": "search_markdown_sources", "args": "not-json", "id": "bad-search",
            "error": "Invalid JSON", "type": "invalid_tool_call",
        }])
        with self.assertRaisesRegex(ValueError, "invalid tool call"):
            CompleteContentMiddleware().after_model({"messages": [invalid]}, None)


class ContentContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)

    async def test_invalid_search_alongside_structured_output_fails_without_delivering_it(self):
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.store.memory import InMemoryStore
        from edbot import edbot_agent, service

        task = {"subagent_type": "content-generating-agent", "description": json.dumps({
            "mode": "explain_at_tier", "concept": "queues", "target_tier": "Apply",
        })}
        output = {"mode": "explain_at_tier", "concept": "queues", "target_tier": "Apply",
                  "content": "PREMATURE: A queue is LIFO.", "sources": ["Unread synthetic source"]}
        invalid = {"finish_reason": "tool_calls", "deltas": [{"role": "assistant", "content": "",
                   "tool_calls": [
                       {"index": 0, "id": "bad-search", "type": "function", "function": {
                           "name": "search_markdown_sources", "arguments": "not-json"}},
                       {"index": 1, "id": "premature", "type": "function", "function": {
                           "name": "CGAOutput", "arguments": json.dumps(output)}},
                   ]}]}
        corrected = {**output, "content": "A queue is FIFO: the oldest pending item is removed first."}
        with ScriptedServer([tool_reply("task", task), invalid,
                             tool_reply("task", task), tool_reply("CGAOutput", corrected)]) as server, \
                patch.object(edbot_agent, "load_sebook_store"), patch.object(service.logger, "exception"):
            agent = edbot_agent.create_edbot_agent(checkpointer=InMemorySaver(serde=service.SERDE),
                                                  store=InMemoryStore())
            with patch.object(service, "_agent", agent):
                failed = [event async for event in service.chat_turn("invalid-child", "Explain queues.")]
                self.assertEqual(failed[-1].type, "error")
                self.assertFalse(any(event.type in {"text", "done"} for event in failed))
                retried = [event async for event in service.chat_turn("invalid-child", "Please try again.")]
                history = await service.get_history("invalid-child")
            self.assertEqual(retried[-1].type, "done")
            self.assertEqual("".join(event.text for event in retried if event.type == "text"), corrected["content"])
            self.assertNotIn("LIFO", "".join(message.content for message in history))
            self.assertEqual(len(server.requests), 4)

    async def test_parallel_searches_finish_before_child_can_submit_its_final_content(self):
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.store.memory import InMemoryStore
        from langchain_core.tools import tool
        from edbot import edbot_agent, service

        searched = []

        @tool
        def search_markdown_sources(query: str) -> str:
            """Return synthetic evidence for the cache-free contract test."""
            searched.append(query)
            return "RETRIEVED EVIDENCE: A queue is FIFO; clients use the public enqueue/dequeue interface."

        task = {"subagent_type": "content-generating-agent", "description": json.dumps({
            "mode": "explain_at_tier", "concept": "queues", "target_tier": "Apply",
        })}
        premature = {"mode": "explain_at_tier", "concept": "queues", "target_tier": "Apply",
                     "content": "PREMATURE: A queue is LIFO.", "sources": ["Synthetic source"]}
        mixed = {"finish_reason": "tool_calls", "deltas": [{"role": "assistant", "content": "Premature LIFO preamble",
                  "tool_calls": [
                      {"index": i, "id": name + str(i), "type": "function",
                       "function": {"name": name, "arguments": json.dumps(arguments)}}
                      for i, (name, arguments) in enumerate([
                          ("search_markdown_sources", {"query": "queue order"}),
                          ("search_markdown_sources", {"query": "queue interface"}),
                          ("CGAOutput", premature),
                      ])
                  ]}]}
        final = {**premature, "content": "A queue is FIFO: the oldest pending item is removed first."}
        with ScriptedServer([tool_reply("task", task), mixed, tool_reply("CGAOutput", final)]) as server, \
                patch.object(edbot_agent, "load_sebook_store"), \
                patch.object(edbot_agent.tools, "search_markdown_sources", search_markdown_sources):
            agent = edbot_agent.create_edbot_agent(checkpointer=InMemorySaver(), store=InMemoryStore())
            with patch.object(service, "_agent", agent):
                events = [event async for event in service.chat_turn("evidence-first", "Explain queues.")]
            self.assertEqual(events[-1].type, "done")
            visible = "".join(event.text for event in events if event.type == "text")
            self.assertEqual(visible, final["content"])
            self.assertNotIn("LIFO", "".join(event.model_dump_json() for event in events))
            self.assertCountEqual(searched, ["queue order", "queue interface"])
            self.assertEqual(len(server.requests), 3)
            reconsidered = server.requests[-1][1]["messages"]
            evidence = [message for message in reconsidered if message["role"] == "tool"]
            self.assertEqual(len(evidence), 2)
            self.assertTrue(all("RETRIEVED EVIDENCE" in message["content"] for message in evidence))
            self.assertNotIn("PREMATURE", json.dumps(reconsidered))
            self.assertNotIn("LIFO preamble", json.dumps(reconsidered))
            self.assertFalse(any(call["function"]["name"] == "CGAOutput"
                                 for message in reconsidered for call in message.get("tool_calls", [])))

    async def test_output_limited_child_cannot_be_delivered_as_a_complete_question(self):
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.store.memory import InMemoryStore
        from edbot import edbot_agent, service

        task = {"subagent_type": "content-generating-agent", "description": json.dumps({
            "mode": "generate_question", "concept": "queues", "target_tier": "Apply",
        })}
        output = {
            "mode": "generate_question", "concept": "queues", "target_tier": "Apply",
            "content": "UNFINISHED_QUESTION must not be shown.", "format": "short_answer",
            "rubric": "Private key", "concept_tags": ["queues"], "sources": ["Synthetic source"],
        }
        truncated = tool_reply("CGAOutput", output)
        truncated["finish_reason"] = "length"
        with ScriptedServer([tool_reply("task", task), truncated]), \
                patch.object(edbot_agent, "load_sebook_store"), \
                patch.object(service.logger, "exception"):
            agent = edbot_agent.create_edbot_agent(checkpointer=InMemorySaver(), store=InMemoryStore())
            with patch.object(service, "_agent", agent):
                events = [event async for event in service.chat_turn("truncated-child", "Give me a question.")]
            self.assertNotIn("UNFINISHED_QUESTION", "".join(event.model_dump_json() for event in events))
            self.assertEqual(events[-1].type, "error")

    async def test_source_gap_survives_child_validation_and_requires_parent_handling(self):
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.store.memory import InMemoryStore
        from edbot import edbot_agent, service

        gap = "The retrieved course passages do not define this storage contract."
        task = {"subagent_type": "content-generating-agent", "description": json.dumps({
            "mode": "explain_at_tier", "concept": "information-hiding", "target_tier": "Apply",
        })}
        output = {
            "mode": "explain_at_tier", "concept": "information-hiding", "target_tier": "Apply",
            "content": "I need the module's documented contract to answer this.",
            "sources": [], "coverage_gap": gap,
        }
        final = "Please share the module's documented interface so we can check that claim."
        with ScriptedServer([tool_reply("task", task), tool_reply("CGAOutput", output),
                             text_reply(final)]) as server, patch.object(edbot_agent, "load_sebook_store"):
            agent = edbot_agent.create_edbot_agent(checkpointer=InMemorySaver(), store=InMemoryStore())
            with patch.object(service, "_agent", agent):
                events = [event async for event in service.chat_turn("coverage-contract", "Explain this contract.")]
            self.assertEqual(events[-1].type, "done")
            self.assertEqual("".join(event.text for event in events if event.type == "text"), final)
            self.assertEqual(len(server.requests), 3)
            resumed_tools = [message for message in server.requests[-1][1]["messages"]
                             if message["role"] == "tool"]
            self.assertIn(gap, json.dumps(resumed_tools))
            self.assertNotIn(gap, "".join(event.model_dump_json() for event in events))


if __name__ == "__main__":
    unittest.main()
