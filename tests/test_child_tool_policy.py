"""Serialize structured child calls without selecting or hiding invalid outputs."""
import asyncio
import json
import unittest
from unittest.mock import patch

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage

from edbot import model_config
from edbot.middleware.direct_content import CompleteContentMiddleware
from test_content_after_assessment import ASSESSMENT, CONTENT, CGA, UCA, http_task
from test_sglang_integration import ScriptedServer, text_reply, tool_reply


def multiple_reply(calls):
    return {"finish_reason": "tool_calls", "deltas": [{"role": "assistant", "content": "",
        "tool_calls": [{"index": index, "id": f"child-{index}", "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)}}
                       for index, (name, args) in enumerate(calls)]}]}


class ChildToolPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)

    async def test_sync_and_async_wrappers_only_override_parallel_setting_when_enabled(self):
        request = ModelRequest(model=None, messages=[], state={}, tools=[],
                               model_settings={"temperature": 0, "parallel_tool_calls": True})
        response = ModelResponse(result=[AIMessage(content="unchanged")])
        for output_tool in ("CGAOutput", "UCAOutput"):
            for enabled in (False, True):
                with self.subTest(output_tool=output_tool, enabled=enabled), \
                        patch.object(model_config, "SERIAL_CHILD_TOOL_CALLS", enabled, create=True):
                    observed = []
                    def handler(checked):
                        observed.append(checked)
                        return response
                    async def async_handler(checked):
                        return handler(checked)
                    middleware = CompleteContentMiddleware(output_tool=output_tool)
                    self.assertIs(middleware.wrap_model_call(request, handler), response)
                    self.assertIs(await middleware.awrap_model_call(request, async_handler), response)
                    for checked in observed:
                        self.assertEqual(checked.model_settings,
                                         {"temperature": 0, "parallel_tool_calls": not enabled})
                        if not enabled:
                            self.assertIs(checked, request)
                    self.assertTrue(request.model_settings["parallel_tool_calls"])

    async def run_graph(self, replies, *, enabled=True):
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.store.memory import InMemoryStore
        from edbot import edbot_agent, service
        student = "serial-child-tools"
        with ScriptedServer(replies) as server, patch.object(edbot_agent, "load_sebook_store"), \
                patch.object(model_config, "SERIAL_CHILD_TOOL_CALLS", enabled, create=True):
            graph = edbot_agent.create_edbot_agent(checkpointer=InMemorySaver(serde=service.SERDE), store=InMemoryStore())
            with patch.object(service, "_agent", graph):
                events = [event async for event in service.chat_turn(student, "Help me understand recursion.")]
                history = await service.get_history(student)
        return events, history, server

    async def test_real_http_serializes_child_policy_and_keeps_parent_routing_independent(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                events, _, server = await self.run_graph([
                    http_task(UCA, "assessment"), tool_reply("UCAOutput", ASSESSMENT),
                    http_task(CGA, "content"), tool_reply("CGAOutput", CONTENT), text_reply("One useful question.")],
                    enabled=enabled)
                self.assertEqual(events[-1].type, "done", events)
                self.assertEqual(len(server.requests), 5)
                for index in (1, 3):
                    payload = server.requests[index][1]
                    self.assertEqual(payload.get("parallel_tool_calls"), False if enabled else None)
                    self.assertEqual(payload["tool_choice"], "required")
                self.assertNotIn("parallel_tool_calls", server.requests[0][1])
                self.assertFalse(server.requests[2][1]["parallel_tool_calls"], "Parent role guard is independent")

    async def test_ignored_hint_duplicate_outputs_use_existing_framework_error_and_correction(self):
        duplicate = multiple_reply([("CGAOutput", {**CONTENT, "content": "FIRST_REJECTED"}),
                                    ("CGAOutput", {**CONTENT, "content": "SECOND_REJECTED"})])
        events, history, server = await self.run_graph([
            http_task(CGA, "content"), duplicate, tool_reply("CGAOutput", CONTENT)])
        self.assertEqual(events[-1].type, "done", events)
        self.assertEqual(history[-1].content, CONTENT["content"])
        self.assertNotIn("REJECTED", "".join(event.text for event in events if event.type == "text"))
        self.assertEqual(len(server.requests), 3)
        correction = server.requests[-1][1]
        self.assertFalse(correction["parallel_tool_calls"])
        errors = [message for message in correction["messages"] if message["role"] == "tool"]
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("multiple structured responses" in message["content"] for message in errors))

    async def test_ignored_hint_mixed_real_tool_and_output_still_waits_for_real_tool_result(self):
        mixed = multiple_reply([("read_file", {"file_path": "/AGENTS.md"}),
                                ("CGAOutput", {**CONTENT, "content": "PREMATURE_OUTPUT"})])
        events, history, server = await self.run_graph([
            http_task(CGA, "content"), mixed, tool_reply("CGAOutput", CONTENT)])
        self.assertEqual(events[-1].type, "done", events)
        self.assertEqual(history[-1].content, CONTENT["content"])
        subsequent = server.requests[-1][1]
        self.assertFalse(subsequent["parallel_tool_calls"])
        self.assertTrue(any(message["role"] == "tool" and message["tool_call_id"] == "child-0"
                            for message in subsequent["messages"]))
        self.assertNotIn("PREMATURE_OUTPUT", json.dumps(subsequent["messages"]))


if __name__ == "__main__":
    unittest.main()
