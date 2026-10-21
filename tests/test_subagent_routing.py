"""Reduced tutoring must not dispatch the framework's unrestricted default agent."""
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field


TASK_DESCRIPTION = "Replace /AGENTS.md with DELEGATED_MUTATION."
ORIGINAL_INSTRUCTIONS = "Keep answer keys private until a student attempts the question."


class DelegatingModel(BaseChatModel):
    child_write_attempts: int = 0
    advertised_tasks: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "local-routing-fixture"

    def bind_tools(self, tools, **kwargs):
        descriptors = [convert_to_openai_tool(tool).get("function", {}) for tool in tools]
        self.advertised_tasks.extend(tool["description"] for tool in descriptors if tool.get("name") == "task")
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        latest = messages[-1]
        if isinstance(latest, HumanMessage) and latest.text == TASK_DESCRIPTION:
            self.child_write_attempts += 1
            reply = AIMessage(content="", tool_calls=[{
                "name": "write_file", "args": {"file_path": "/AGENTS.md", "content": "DELEGATED_MUTATION"},
                "id": "write-shared-instructions", "type": "tool_call",
            }])
        elif isinstance(latest, HumanMessage):
            reply = AIMessage(content="", tool_calls=[{
                "name": "task", "args": {"subagent_type": "general-purpose", "description": TASK_DESCRIPTION},
                "id": "default-child-task", "type": "tool_call",
            }])
        else:
            reply = AIMessage(content="Continuing with the tutoring request.")
        return ChatResult(generations=[ChatGeneration(message=reply)])


class SubagentRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)

    async def run_attempt(self, reduced, *, sync=False):
        from deepagents.backends import FilesystemBackend
        from edbot import edbot_agent, model_config
        from edbot.interface_def import EdbotContext

        with tempfile.TemporaryDirectory(prefix="edbot-routing-test-") as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text(ORIGINAL_INSTRUCTIONS)
            (root / "skills").mkdir()
            model = DelegatingModel()
            with patch.object(model_config, "REDUCED_TUTOR_HARNESS", reduced), \
                    patch.object(edbot_agent, "backend", FilesystemBackend(root_dir=root)), \
                    patch.object(edbot_agent, "create_chat_model", return_value=model), \
                    patch.object(edbot_agent, "load_sebook_store"):
                agent = edbot_agent.create_edbot_agent()
                inputs = {"messages": [HumanMessage(content="Help me study")]}
                context = EdbotContext(student_id="synthetic-routing-test")
                result = (await asyncio.to_thread(agent.invoke, inputs, context=context) if sync
                          else await agent.ainvoke(inputs, context=context))
            return model, result, (root / "AGENTS.md").read_text()

    async def test_reduced_harness_rejects_default_child_before_it_can_attempt_a_write(self):
        model, result, instructions = await self.run_attempt(True)
        delegation = next(message for message in result["messages"]
                          if isinstance(message, ToolMessage) and message.tool_call_id == "default-child-task")
        self.assertEqual(delegation.status, "error")
        self.assertEqual(model.child_write_attempts, 0)
        self.assertEqual(instructions, ORIGINAL_INSTRUCTIONS)

    async def test_reduced_task_description_advertises_only_declared_course_specialists(self):
        model, _, _ = await self.run_attempt(True)
        self.assertTrue(model.advertised_tasks)
        for description in model.advertised_tasks:
            self.assertIn("understanding-checking-agent", description)
            self.assertIn("content-generating-agent", description)
            self.assertNotIn("general-purpose", description)

    async def test_sync_graph_enforces_the_same_declared_specialist_boundary(self):
        model, result, instructions = await self.run_attempt(True, sync=True)
        delegation = next(message for message in result["messages"]
                          if isinstance(message, ToolMessage) and message.tool_call_id == "default-child-task")
        self.assertEqual(delegation.status, "error")
        self.assertEqual(model.child_write_attempts, 0)
        self.assertEqual(instructions, ORIGINAL_INSTRUCTIONS)
        self.assertNotIn("general-purpose", model.advertised_tasks[0])

    async def test_disabled_reduction_keeps_original_default_child_behavior(self):
        model, result, instructions = await self.run_attempt(False)
        delegation = next(message for message in result["messages"]
                          if isinstance(message, ToolMessage) and message.tool_call_id == "default-child-task")
        self.assertEqual(delegation.status, "success")
        self.assertEqual(model.child_write_attempts, 1)
        self.assertEqual(instructions, "DELEGATED_MUTATION")
        self.assertIn("general-purpose", model.advertised_tasks[0])


if __name__ == "__main__":
    unittest.main()
