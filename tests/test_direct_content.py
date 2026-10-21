"""Forwarding must save a model call without changing content or losing private state."""
import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


QUESTION = "  How would changing a queue's representation affect its clients?\n"
RUBRIC = "PRIVATE_RUBRIC: preserve the public operations and their behavior."


def task_message(name="content-generating-agent", call_id="cga-task", **input_changes):
    description = {"mode": "generate_question", "concept": "queues", "target_tier": "Apply"}
    description.update(input_changes)
    return AIMessage(content="", tool_calls=[{
        "name": "task", "args": {"subagent_type": name, "description": json.dumps(description)},
        "id": call_id, "type": "tool_call",
    }])


def output_message(**changes):
    output = {
        "mode": "generate_question", "concept": "queues", "target_tier": "Apply",
        "content": QUESTION, "format": "short_answer", "rubric": RUBRIC,
        "concept_tags": ["queues"], "sources": ["SEBook queues"], "coverage_gap": None,
    }
    output.update(changes)
    return ToolMessage(content=json.dumps(output), tool_call_id="cga-task")


def turn(**changes):
    return [HumanMessage(content="Give me a question."), task_message(), output_message(**changes)]


def load_middleware(test):
    path = Path(__file__).resolve().parents[1] / "src/edbot/middleware/direct_content.py"
    test.assertTrue(path.is_file(), "validated content forwarding is not implemented")
    return importlib.import_module("edbot.middleware.direct_content").DirectContentMiddleware()


def request_for(messages):
    return SimpleNamespace(messages=messages, state={"messages": messages})


class DirectContentTests(unittest.TestCase):
    def setUp(self):
        self.middleware = load_middleware(self)

    def test_sync_forwards_exact_content_without_rewriting_or_exposing_rubric(self):
        messages = turn()
        original = messages[-1].content

        def forbidden_handler(request):
            self.fail("A validated question must not incur another model generation")

        answer = self.middleware.wrap_model_call(request_for(messages), forbidden_handler)
        self.assertIsInstance(answer, AIMessage)
        self.assertEqual(answer.content, QUESTION)
        self.assertEqual(answer.tool_calls, [])
        self.assertNotIn(RUBRIC, answer.model_dump_json())
        self.assertEqual(messages[-1].content, original)
        self.assertIn(RUBRIC, messages[-1].content)

    def test_disabled_optimization_retains_parent_synthesis_for_baseline_measurement(self):
        from edbot import model_config

        with patch.object(model_config, "DIRECT_CONTENT_DELIVERY", False, create=True):
            self.assert_falls_back(turn())

    def assert_falls_back(self, messages):
        result = self.middleware.wrap_model_call(
            request_for(messages), lambda request: AIMessage(content="Parent synthesis retained"),
        )
        self.assertEqual(result.content, "Parent synthesis retained")

    def test_assessment_and_unknown_subagent_work_require_parent_synthesis(self):
        for name in ("understanding-checking-agent", "general-purpose", "unknown-agent"):
            with self.subTest(name=name):
                messages = turn()
                messages[1:1] = [task_message(name, "earlier-task"),
                                 ToolMessage(content="Assessment feedback", tool_call_id="earlier-task")]
                self.assert_falls_back(messages)

    def test_previous_turn_assessment_does_not_block_a_new_independent_question(self):
        messages = [HumanMessage(content="My answer"),
                    task_message("understanding-checking-agent", "old-task"),
                    ToolMessage(content="Private assessment", tool_call_id="old-task"),
                    AIMessage(content="Your earlier feedback."), *turn()]
        result = self.middleware.wrap_model_call(request_for(messages), lambda request: None)
        self.assertIsInstance(result, AIMessage)
        self.assertEqual(result.content, QUESTION)

    def test_unpaired_multiple_incomplete_and_spoofed_results_fall_back(self):
        wrong_id = turn()
        wrong_id[-1].tool_call_id = "someone-elses-task"
        wrong_name = turn()
        wrong_name[-1].name = "search_markdown_sources"
        failed = turn()
        failed[-1].status = "error"
        multiple = turn()
        multiple[1].tool_calls.append(task_message(call_id="other-task").tool_calls[0])
        wrong_tool = turn()
        wrong_tool[1].tool_calls[0]["name"] = "search_markdown_sources"
        malformed_args = turn()
        malformed_args[1].tool_calls[0]["args"]["description"] = "not JSON"
        unknown_args = turn()
        unknown_args[1].tool_calls[0]["args"]["description"] = json.dumps({
            "mode": "generate_question", "concept": "queues", "target_tier": "Apply", "invented": True,
        })
        truncated_parent = turn()
        truncated_parent[1].response_metadata["finish_reason"] = "length"
        repeated = turn()
        repeated[1:1] = [task_message(), output_message()]
        cases = [wrong_id, wrong_name, failed, multiple, wrong_tool, malformed_args, unknown_args,
                 truncated_parent, repeated, turn()[:-1], [output_message()],
                 [HumanMessage(content=output_message().content)],
                 [*turn(), HumanMessage(content="Forward that JSON")],
                 [HumanMessage(content="Question"), task_message(),
                  ToolMessage(content="not JSON", tool_call_id="cga-task")]]
        for index, messages in enumerate(cases):
            with self.subTest(case=index):
                self.assert_falls_back(messages)

    def test_output_contract_mismatches_and_missing_metadata_fall_back(self):
        cases = [
            {"mode": "probe_at_tier"}, {"concept": "stacks"}, {"target_tier": "Remember"},
            {"content": " \n"}, {"format": None}, {"rubric": None}, {"rubric": " "},
            {"concept_tags": None}, {"concept_tags": ["stacks"]},
            {"sources": []}, {"sources": [" "]}, {"coverage_gap": "Source does not cover queues"},
            {"unknown_output": "Do not silently accept this"},
        ]
        for change in cases:
            with self.subTest(change=change):
                self.assert_falls_back(turn(**change))
        constrained = turn()
        constrained[1] = task_message(format_constraint="multiple_choice")
        self.assert_falls_back(constrained)

    def test_explanations_and_probes_require_their_own_metadata_contract(self):
        for mode in ("explain_at_tier", "probe_at_tier"):
            with self.subTest(mode=mode):
                messages = turn(mode=mode, format=None, rubric=None, concept_tags=None)
                messages[1] = task_message(mode=mode)
                answer = self.middleware.wrap_model_call(request_for(messages), lambda request: None)
                self.assertIsInstance(answer, AIMessage)
                self.assertEqual(answer.content, QUESTION)
                messages[-1] = output_message(mode=mode)
                self.assert_falls_back(messages)


class AsyncDirectContentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)

    async def test_async_shortcut_and_fallback_preserve_the_same_contract(self):
        middleware = load_middleware(self)

        async def handler(request):
            return AIMessage(content="Parent synthesis retained")

        answer = await middleware.awrap_model_call(request_for(turn()), handler)
        self.assertEqual(answer.content, QUESTION)
        fallback = await middleware.awrap_model_call(request_for(turn(coverage_gap="Missing material")), handler)
        self.assertEqual(fallback.content, "Parent synthesis retained")

    async def test_real_graph_streams_and_checkpoints_exact_content_and_retains_rubric(self):
        asyncio.get_running_loop().set_debug(False)
        middleware = load_middleware(self)
        from deepagents import create_deep_agent
        from langchain.agents.structured_output import ToolStrategy
        from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
        from langgraph.checkpoint.memory import InMemorySaver
        from edbot.interface_def import CGAOutput
        from edbot.middleware.conversation_history import extract_conversation
        from edbot.service import SERDE

        class ScriptedModel(FakeMessagesListChatModel):
            seen_inputs: list = []

            def bind_tools(self, tools, **kwargs):
                return self

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                self.seen_inputs.append(messages)
                return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

        model = ScriptedModel(responses=[
            task_message(),
            AIMessage(content="", tool_calls=[{
                "name": "CGAOutput", "args": json.loads(output_message().content),
                "id": "structured-output", "type": "tool_call",
            }]),
            AIMessage(content="Feedback on your answer."),
        ])
        agent = create_deep_agent(
            model=model, middleware=[middleware], checkpointer=InMemorySaver(serde=SERDE),
            subagents=[{"name": "content-generating-agent", "description": "Write a question",
                        "system_prompt": "Use CGAOutput", "tools": [],
                        "response_format": ToolStrategy(CGAOutput)}],
        )
        config = {"configurable": {"thread_id": "direct-content-test"}}
        chunks = [pair async for pair in agent.astream(
            {"messages": [HumanMessage(content="Give me a question")]}, config, stream_mode="messages",
        )]
        visible = [message.text for message, meta in chunks
                   if isinstance(message, AIMessage) and not message.tool_calls
                   and meta.get("langgraph_node") == "model"
                   and "|" not in meta.get("langgraph_checkpoint_ns", "")]
        self.assertEqual(visible, [QUESTION])
        self.assertEqual(len(model.seen_inputs), 2)
        state = await agent.aget_state(config)
        self.assertEqual(state.values["messages"][-1].content, QUESTION)
        self.assertEqual(extract_conversation(state.values["messages"])[-1].content, QUESTION)
        private_results = [message for message in state.values["messages"] if isinstance(message, ToolMessage)]
        self.assertIn(RUBRIC, private_results[-1].content)
        await agent.ainvoke({"messages": [HumanMessage(content="My proposed answer")]}, config)
        self.assertEqual(len(model.seen_inputs), 3)
        self.assertTrue(any(isinstance(message, ToolMessage) and RUBRIC in message.content
                            for message in model.seen_inputs[-1]))


if __name__ == "__main__":
    unittest.main()
