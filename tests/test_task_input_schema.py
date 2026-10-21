"""Typed model descriptions must preserve the existing executable task boundary."""
import asyncio
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import httpx
from jsonschema import Draft202012Validator
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_ollama import ChatOllama
from langgraph.store.memory import InMemoryStore
from pydantic import TypeAdapter

from edbot import model_config, student_model
from edbot.interface_def import CGAInput, UCAInput
from edbot.middleware.assessment_result import AssessmentResultMiddleware
from edbot.middleware.content_after_assessment import RequireContentAfterAssessment
from edbot.middleware.direct_content import CompleteContentMiddleware
from edbot.middleware.validate_input import SUBAGENT_INPUT_SCHEMAS, ValidateSubagentInput
from test_assessment_result import OUTPUT, no_generation, request as assessment_request, result as assessment_result
from test_content_after_assessment import ASSESSMENT, CONTENT, assessed, task_message
from test_sglang_integration import ScriptedServer, text_reply, tool_reply

UCA, CGA = "understanding-checking-agent", "content-generating-agent"
UCA_INPUT = {"concept": "recursion", "invocation_context": "new_evidence"}
CGA_INPUT = {"concept": "recursion", "target_tier": "Understand", "mode": "explain_at_tier"}


@tool
def task(description: str, subagent_type: str) -> str:
    """Dispatch a specialist using the existing string-valued input API."""
    return description


def model_request(messages=None, tools=None):
    messages = messages or []
    return ModelRequest(model=None, messages=messages, state={"messages": messages},
                        tools=[task] if tools is None else tools, model_settings={"temperature": 0})


def task_args(role, value, *, legacy=False):
    return {"subagent_type": role, "description": json.dumps(value) if legacy else deepcopy(value)}


class TaskSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        for change in (patch.object(model_config, "REDUCED_TUTOR_HARNESS", True),
                       patch.object(model_config, "REQUIRE_CONTENT_AFTER_ASSESSMENT", True),
                       patch.object(model_config, "DETERMINISTIC_ASSESSMENT_SAVE", True),
                       patch.dict(SUBAGENT_INPUT_SCHEMAS, {UCA: TypeAdapter(UCAInput), CGA: TypeAdapter(CGAInput)}, clear=True)):
            change.start()
            self.addCleanup(change.stop)

    async def advertised(self, request, *, sync=False, constrained=False):
        seen = []
        response = ModelResponse(result=[task_message(CGA, "content")])
        def handler(checked):
            seen.append(checked)
            return response
        async def async_handler(checked):
            return handler(checked)
        middleware = ValidateSubagentInput()
        if sync:
            wrapped = (lambda checked: RequireContentAfterAssessment().wrap_model_call(checked, handler)) if constrained else handler
            self.assertIs(middleware.wrap_model_call(request, wrapped), response)
        else:
            async def wrapped(checked):
                return await RequireContentAfterAssessment().awrap_model_call(checked, async_handler)
            self.assertIs(await middleware.awrap_model_call(request, wrapped if constrained else async_handler), response)
        return seen[0]

    async def test_schema_pairs_each_role_with_its_own_input_without_mutating_dispatch_tool(self):
        original_schema = task.args_schema
        original_descriptor = deepcopy(convert_to_openai_tool(task))
        for sync in (False, True):
            for model_tool in (task, deepcopy(original_descriptor)):
                with self.subTest(sync=sync, dictionary=isinstance(model_tool, dict)):
                    request = model_request(tools=[model_tool])
                    changed = await self.advertised(request, sync=sync)
                    schema = convert_to_openai_tool(changed.tools[0])["function"]["parameters"]
                    self.assertIn("anyOf", schema)
                    self.assertNotIn("$ref", json.dumps(schema))
                    self.assertNotIn("$defs", json.dumps(schema))
                    validator = Draft202012Validator(schema)
                    for role, value in ((UCA, UCA_INPUT), (CGA, CGA_INPUT),
                                        (CGA, {"concept": "recursion", "target_tier": "Apply"})):
                        self.assertTrue(validator.is_valid(task_args(role, value)))
                    for role, value in ((UCA, CGA_INPUT), (CGA, UCA_INPUT),
                                        (UCA, {"concept": "recursion"}), ("general-purpose", UCA_INPUT)):
                        self.assertFalse(validator.is_valid(task_args(role, value)))
                    self.assertEqual(convert_to_openai_tool(request.tools[0]), original_descriptor)
        self.assertIs(task.args_schema, original_schema)
        self.assertEqual(convert_to_openai_tool(task), original_descriptor)

    async def test_disabled_harness_retains_original_model_request(self):
        with patch.object(model_config, "REDUCED_TUTOR_HARNESS", False):
            for sync in (False, True):
                request = model_request()
                self.assertIs(await self.advertised(request, sync=sync), request)

    async def test_ollama_wire_retains_legacy_task_schema_and_post_assessment_guard(self):
        # Use the real public ChatOllama -> Ollama Client -> HTTP serialization.
        # Ollama's Parameters model drops root anyOf, even with type=object.
        for sync in (False, True):
            for constrained in (False, True):
                with self.subTest(sync=sync, constrained=constrained):
                    requests = []
                    def respond(request):
                        requests.append(json.loads(request.content))
                        return httpx.Response(200, json={"model": "fixture", "done": True,
                            "done_reason": "stop", "message": {"role": "assistant", "content": "",
                            "tool_calls": [{"function": {"name": "task",
                                "arguments": task_args(CGA, CGA_INPUT, legacy=True)}}]}})
                    model = ChatOllama(model="fixture", base_url="http://ollama.test", temperature=0,
                                       client_kwargs={"transport": httpx.MockTransport(respond)})
                    messages = assessed() if constrained else [HumanMessage(content="Help me study.")]
                    request = model_request(messages).override(model=model, model_settings={})
                    original = deepcopy(convert_to_openai_tool(task))
                    seen = []
                    def handler(checked):
                        seen.append(checked)
                        message = checked.model.bind_tools(checked.tools, tool_choice=checked.tool_choice,
                            **checked.model_settings).invoke(checked.messages, stream=False)
                        return ModelResponse(result=[message])
                    async def async_handler(checked):
                        seen.append(checked)
                        message = await checked.model.bind_tools(checked.tools, tool_choice=checked.tool_choice,
                            **checked.model_settings).ainvoke(checked.messages, stream=False)
                        return ModelResponse(result=[message])
                    guard = RequireContentAfterAssessment()
                    if sync:
                        wrapped = (lambda checked: guard.wrap_model_call(checked, handler)) if constrained else handler
                        result = ValidateSubagentInput().wrap_model_call(request, wrapped)
                    else:
                        async def wrapped(checked):
                            return await guard.awrap_model_call(checked, async_handler)
                        result = await ValidateSubagentInput().awrap_model_call(request, wrapped if constrained else async_handler)
                    self.assertEqual(len(requests), 1)
                    descriptor = requests[0]["tools"][0]["function"]
                    schema = descriptor["parameters"]
                    self.assertEqual(schema["type"], "object")
                    self.assertEqual(schema["properties"]["description"]["type"], "string")
                    self.assertEqual(schema["properties"]["subagent_type"]["enum"],
                                     [CGA] if constrained else sorted([UCA, CGA]))
                    self.assertEqual(set(schema["required"]), {"description", "subagent_type"})
                    self.assertNotIn("anyOf", schema)
                    self.assertIn(CGA, descriptor["description"])
                    self.assertNotIn("parallel_tool_calls", seen[0].model_settings)
                    self.assertNotIn("tool_choice", requests[0], "Installed ChatOllama ignores this hint")
                    if constrained:
                        self.assertEqual(seen[0].tool_choice, {"type": "function", "function": {"name": "task"}})
                    # ChatOllama parses nested JSON strings; the existing task
                    # validator already normalizes this object back to a string.
                    self.assertEqual(result.result[0].tool_calls[0]["args"], task_args(CGA, CGA_INPUT))
                    self.assertEqual(convert_to_openai_tool(task), original)
                    self.assertEqual(request.model_settings, {})

    async def test_ollama_child_wrapper_invokes_client_without_parallel_keyword(self):
        for sync in (False, True):
            with self.subTest(sync=sync), patch.object(model_config, "SERIAL_CHILD_TOOL_CALLS", True):
                requests = []
                def respond(request):
                    requests.append(json.loads(request.content))
                    return httpx.Response(200, json={"model": "fixture", "done": True,
                        "done_reason": "stop", "message": {"role": "assistant", "content": "Complete."}})
                model = ChatOllama(model="fixture", base_url="http://ollama.test", temperature=0,
                                   client_kwargs={"transport": httpx.MockTransport(respond)})
                request = model_request([HumanMessage(content="Explain recursion.")]).override(
                    model=model, model_settings={})
                def handler(checked):
                    return ModelResponse(result=[checked.model.bind_tools(checked.tools,
                        **checked.model_settings).invoke(checked.messages, stream=False)])
                async def async_handler(checked):
                    return ModelResponse(result=[await checked.model.bind_tools(checked.tools,
                        **checked.model_settings).ainvoke(checked.messages, stream=False)])
                middleware = CompleteContentMiddleware()
                result = (middleware.wrap_model_call(request, handler) if sync else
                          await middleware.awrap_model_call(request, async_handler))
                self.assertEqual(result.result[0].content, "Complete.")
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0]["options"]["temperature"], 0)

    async def test_ollama_ignored_tool_choice_still_rejects_terminal_parent_output(self):
        for sync in (False, True):
            with self.subTest(sync=sync):
                def respond(request):
                    return httpx.Response(200, json={"model": "fixture", "done": True,
                        "done_reason": "stop", "message": {"role": "assistant", "content": "Bypass CGA."}})
                model = ChatOllama(model="fixture", base_url="http://ollama.test",
                                   client_kwargs={"transport": httpx.MockTransport(respond)})
                request = model_request(assessed()).override(model=model, model_settings={})
                def handler(checked):
                    return ModelResponse(result=[checked.model.bind_tools(checked.tools,
                        tool_choice=checked.tool_choice, **checked.model_settings).invoke(checked.messages, stream=False)])
                async def async_handler(checked):
                    return ModelResponse(result=[await checked.model.bind_tools(checked.tools,
                        tool_choice=checked.tool_choice, **checked.model_settings).ainvoke(checked.messages, stream=False)])
                guard = RequireContentAfterAssessment()
                with self.assertRaisesRegex(ValueError, "complete content-specialist task"):
                    if sync:
                        ValidateSubagentInput().wrap_model_call(request,
                            lambda checked: guard.wrap_model_call(checked, handler))
                    else:
                        async def wrapped(checked):
                            return await guard.awrap_model_call(checked, async_handler)
                        await ValidateSubagentInput().awrap_model_call(request, wrapped)

    async def test_object_and_legacy_string_calls_reach_same_string_tool_with_same_id(self):
        for sync in (False, True):
            for legacy in (False, True):
                for role, value, expected in (
                    (UCA, UCA_INPUT, {**UCA_INPUT, "answer_submission": None}),
                    (CGA, CGA_INPUT, CGA_INPUT),
                    (CGA, {"concept": "recursion", "target_tier": "Apply"},
                     {"concept": "recursion", "target_tier": "Apply", "mode": "generate_question",
                      "format_constraint": None, "prior_questions": []}),
                ):
                    with self.subTest(sync=sync, legacy=legacy, role=role, value=value):
                        call = {"name": "task", "id": "stable-task-id", "type": "tool_call",
                                "args": task_args(role, value, legacy=legacy)}
                        original = deepcopy(call)
                        request = ToolCallRequest(tool_call=call, tool=task, state={}, runtime=None)
                        def handler(checked):
                            self.assertIs(checked.tool, task)
                            self.assertEqual(checked.tool_call["id"], "stable-task-id")
                            self.assertIsInstance(checked.tool_call["args"]["description"], str)
                            return task.invoke(checked.tool_call)
                        async def async_handler(checked):
                            return handler(checked)
                        mw = ValidateSubagentInput()
                        result = (mw.wrap_tool_call(request, handler) if sync else
                                  await mw.awrap_tool_call(request, async_handler))
                        self.assertEqual(json.loads(result.content), expected)
                        self.assertEqual(result.tool_call_id, "stable-task-id")
                        self.assertEqual(call, original)

    async def test_crossed_route_from_noncompliant_server_never_dispatches_child(self):
        for sync in (False, True):
            for legacy in (False, True):
                for role, value in ((UCA, CGA_INPUT), (CGA, UCA_INPUT)):
                    with self.subTest(sync=sync, legacy=legacy, role=role):
                        request = ToolCallRequest(tool_call={"name": "task", "id": "rejected",
                            "type": "tool_call", "args": task_args(role, value, legacy=legacy)},
                            tool=task, state={}, runtime=None)
                        def handler(_):
                            self.fail("Crossed input reached the executable task")
                        async def async_handler(checked):
                            return handler(checked)
                        mw = ValidateSubagentInput()
                        result = (mw.wrap_tool_call(request, handler) if sync else
                                  await mw.awrap_tool_call(request, async_handler))
                        self.assertEqual((result.status, result.tool_call_id), ("error", "rejected"))

    async def test_pending_assessment_selects_complete_cga_branch_sync_and_async(self):
        for sync in (False, True):
            with self.subTest(sync=sync):
                changed = await self.advertised(model_request(assessed()), sync=sync, constrained=True)
                schema = changed.tools[0]["function"]["parameters"]
                self.assertEqual(schema["properties"]["subagent_type"].get("const"), CGA)
                validator = Draft202012Validator(schema)
                self.assertTrue(validator.is_valid(task_args(CGA, CGA_INPUT)))
                self.assertFalse(validator.is_valid(task_args(UCA, UCA_INPUT)))
                self.assertFalse(validator.is_valid(task_args(CGA, UCA_INPUT)))
                self.assertEqual(changed.tool_choice, {"type": "function", "function": {"name": "task"}})
                self.assertFalse(changed.model_settings["parallel_tool_calls"])

    async def test_pending_assessment_rejects_missing_or_ambiguous_cga_branch(self):
        branch = {"type": "object", "properties": {"subagent_type": {"const": CGA}}}
        for branches in ([], [branch, deepcopy(branch)]):
            with self.subTest(branches=branches):
                descriptor = {"type": "function", "function": {"name": "task",
                              "parameters": {"anyOf": branches}}}
                request = model_request(assessed(), tools=[descriptor])
                with self.assertRaisesRegex(ValueError, "CGA branch"):
                    RequireContentAfterAssessment().wrap_model_call(request,
                        lambda _: self.fail("Ambiguous schema reached the model"))

    async def test_object_then_legacy_replay_keeps_assessment_receipt_identity(self):
        store = InMemoryStore()
        original = assessment_request(store)
        object_call = deepcopy(original.tool_call)
        object_call["args"]["description"] = json.loads(object_call["args"]["description"])
        object_request = original.override(tool_call=object_call)
        mw, persistence = ValidateSubagentInput(), AssessmentResultMiddleware()
        async def child(checked):
            self.assertEqual(checked.tool_call["id"], original.tool_call["id"])
            return assessment_result(checked)
        async def persist(checked):
            return await persistence.awrap_tool_call(checked, child)
        await mw.awrap_tool_call(object_request, persist)
        saved = await student_model.load_entry(store, "alice", "recursion")
        async def replay(checked):
            return await persistence.awrap_tool_call(checked, no_generation)
        result = await mw.awrap_tool_call(original, replay)
        self.assertEqual(json.loads(result.content), OUTPUT)
        self.assertEqual(await student_model.load_entry(store, "alice", "recursion"), saved)
        self.assertEqual(saved.assessment_count, 1)
        self.assertEqual(len(await store.asearch(("students", "alice", "assessment_receipts"))), 1)

    async def test_real_http_schema_and_object_dispatch_preserve_forced_cga_and_legacy_calls(self):
        from edbot import edbot_agent
        from edbot.interface_def import EdbotContext
        from langchain_core.messages import HumanMessage
        for legacy in (False, True):
            with self.subTest(legacy=legacy), ScriptedServer([
                tool_reply("task", task_args(UCA, UCA_INPUT, legacy=legacy)),
                tool_reply("UCAOutput", ASSESSMENT),
                tool_reply("task", task_args(CGA, CGA_INPUT, legacy=legacy)),
                tool_reply("CGAOutput", CONTENT), text_reply("One final question.")
            ]) as server, patch.object(edbot_agent, "load_sebook_store"):
                graph = edbot_agent.create_edbot_agent(store=InMemoryStore())
                result = await graph.ainvoke({"messages": [HumanMessage(content="Give me a hint.")]},
                    config={"configurable": {"thread_id": "typed-task-test"}},
                    context=EdbotContext(student_id="typed-task-test"))
                self.assertEqual(result["messages"][-1].content, "One final question.")
                self.assertEqual(len(server.requests), 5)
                initial = next(t for t in server.requests[0][1]["tools"] if t["function"]["name"] == "task")
                schema = initial["function"]["parameters"]
                self.assertIn("anyOf", schema)
                self.assertNotIn("$ref", json.dumps(schema))
                validator = Draft202012Validator(schema)
                self.assertTrue(validator.is_valid(task_args(UCA, UCA_INPUT)))
                self.assertFalse(validator.is_valid(task_args(UCA, CGA_INPUT)))
                constrained = server.requests[2][1]
                self.assertEqual([t["function"]["name"] for t in constrained["tools"]], ["task"])
                schema = constrained["tools"][0]["function"]["parameters"]
                self.assertEqual(schema["properties"]["subagent_type"]["const"], CGA)
                self.assertTrue(Draft202012Validator(schema).is_valid(task_args(CGA, CGA_INPUT)))
                self.assertEqual(constrained["tool_choice"], {"type": "function", "function": {"name": "task"}})
                for index, expected in ((1, {**UCA_INPUT, "answer_submission": None}), (3, CGA_INPUT)):
                    self.assertEqual(json.loads(server.requests[index][1]["messages"][-1]["content"]), expected)

    async def test_sync_graph_dispatches_typed_and_legacy_content_without_replacing_task_api(self):
        from edbot import edbot_agent
        from edbot.interface_def import EdbotContext
        from langchain_core.messages import HumanMessage
        for legacy in (False, True):
            with self.subTest(legacy=legacy), ScriptedServer([
                tool_reply("task", task_args(CGA, CGA_INPUT, legacy=legacy)),
                tool_reply("CGAOutput", CONTENT)
            ]) as server, patch.object(edbot_agent, "load_sebook_store"):
                graph = edbot_agent.create_edbot_agent()
                result = await asyncio.to_thread(graph.invoke,
                    {"messages": [HumanMessage(content="Explain recursion.")]},
                    context=EdbotContext(student_id="typed-sync-test"))
                self.assertEqual(result["messages"][-1].content, CONTENT["content"])
                self.assertEqual(len(server.requests), 2)
                self.assertEqual(json.loads(server.requests[1][1]["messages"][-1]["content"]), CGA_INPUT)


if __name__ == "__main__":
    unittest.main()
