"""The smaller tutor harness must retain reading and recovery, but reject writes."""
import asyncio
import importlib
from pathlib import Path
import tempfile
import unittest

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field


COURSE_RULE = "COURSE_RULE: keep answer keys private until the learner answers."
SKILL_RULE = "SKILL_RULE: ask for one prediction before revealing the explanation."


class ScriptedModel(FakeMessagesListChatModel):
    requests: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.requests.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{
        "name": name, "args": args, "id": call_id, "type": "tool_call",
    }])


def load_helper(test):
    path = Path(__file__).resolve().parents[1] / "src/edbot/tutor_harness.py"
    test.assertTrue(path.is_file(), "the reduced tutoring harness is not implemented")
    return importlib.import_module("edbot.tutor_harness").tutor_middleware


class TutorHarnessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        self.tutor_middleware = load_helper(self)
        self.directory = tempfile.TemporaryDirectory(prefix="edbot-tutor-harness-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "AGENTS.md").write_text(COURSE_RULE)
        skill = self.root / "skills" / "lesson"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: lesson\ndescription: Teach using one prepared example.\n---\n" + SKILL_RULE,
        )
        self.backend = FilesystemBackend(root_dir=self.root)

    def build(self, model, **kwargs):
        return create_deep_agent(
            model=model, backend=self.backend,
            middleware=self.tutor_middleware(self.backend, include_memory=True),
            memory=["./AGENTS.md"], skills=["./skills/"], **kwargs,
        )

    async def test_parent_and_child_cannot_mutate_shared_course_instructions(self):
        for child in (False, True):
            with self.subTest(child=child):
                mutations = [
                    call("write_file", {"file_path": "/AGENTS.md", "content": "Replaced"}, "write-attempt"),
                    call("edit_file", {"file_path": "/AGENTS.md", "old_string": COURSE_RULE,
                                       "new_string": "Edited"}, "edit-attempt"),
                    call("delete", {"file_path": "/AGENTS.md"}, "delete-attempt"),
                ]
                responses = mutations + [AIMessage(content="Finished safely.")]
                if child:
                    responses = [call("task", {"subagent_type": "lesson-writer", "description": "Write a lesson"},
                                      "child-task"), *responses, AIMessage(content="Parent reply.")]
                model = ScriptedModel(responses=responses)
                agent = self.build(model, subagents=[{
                    "name": "lesson-writer", "description": "Write course content", "system_prompt": "Teach",
                    "tools": [], "middleware": self.tutor_middleware(self.backend),
                }])
                await agent.ainvoke({"messages": [HumanMessage(content="A synthetic test request")]})
                observed = {message.tool_call_id: message for messages in model.requests
                            for message in messages if isinstance(message, ToolMessage)}
                for call_id in ("write-attempt", "edit-attempt", "delete-attempt"):
                    self.assertEqual(observed[call_id].status, "error")
                self.assertEqual((self.root / "AGENTS.md").read_text(), COURSE_RULE)
                self.assertTrue((self.root / "skills" / "lesson" / "SKILL.md").is_file())

    async def test_course_context_and_indexed_skill_remain_available(self):
        model = ScriptedModel(responses=[
            call("read_file", {"file_path": "/skills/lesson/SKILL.md"}, "skill-read"),
            AIMessage(content="What do you predict?"),
        ])
        agent = self.build(model, checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "skill-reader"}}
        result = await agent.ainvoke({"messages": [HumanMessage(content="Help me learn")]}, config)
        context = "\n".join(message.text for message in model.requests[0] if isinstance(message, SystemMessage))
        self.assertIn(COURSE_RULE, context)
        self.assertIn("/skills/lesson/SKILL.md", context)
        read = next(message for message in result["messages"]
                    if isinstance(message, ToolMessage) and message.tool_call_id == "skill-read")
        self.assertEqual(read.status, "success")
        self.assertIn(SKILL_RULE, read.text)
        state = await agent.aget_state(config)
        self.assertEqual(state.values["messages"][-1].text, "What do you predict?")

    async def test_read_only_directory_and_search_tools_still_work(self):
        model = ScriptedModel(responses=[
            call("ls", {"path": "/skills"}, "list-skills"),
            call("glob", {"pattern": "**/SKILL.md", "path": "/skills"}, "find-skills"),
            call("grep", {"pattern": "SKILL_RULE", "path": "/skills", "output_mode": "content"}, "search-skills"),
            AIMessage(content="Located the teaching procedure."),
        ])
        result = await self.build(model).ainvoke({"messages": [HumanMessage(content="Find the lesson procedure")]})
        results = {message.tool_call_id: message for message in result["messages"] if isinstance(message, ToolMessage)}
        for call_id in ("list-skills", "find-skills", "search-skills"):
            self.assertEqual(results[call_id].status, "success")
        self.assertIn("SKILL.md", results["find-skills"].text)
        self.assertIn("SKILL_RULE", results["search-skills"].text)

    async def test_oversized_course_evidence_is_offloaded_and_recoverable(self):
        body = ("Course evidence remains available after offloading. " * 3 + "\n") * 1500
        body += "FINAL_SOURCE_SENTINEL: preserve this evidence."

        @tool
        def read_course_source() -> str:
            """Return prepared course evidence."""
            return body

        model = ScriptedModel(responses=[
            call("read_course_source", {}, "course-source"),
            call("read_file", {"file_path": "/large_tool_results/course-source", "offset": 1500,
                               "limit": 2}, "recover-source"),
            AIMessage(content="Explanation grounded in recovered evidence."),
        ])
        result = await self.build(model, tools=[read_course_source]).ainvoke({
            "messages": [HumanMessage(content="Use the course evidence")],
        })
        self.assertEqual((self.root / "large_tool_results" / "course-source").read_text(), body)
        recovery = next(message for message in result["messages"]
                        if isinstance(message, ToolMessage) and message.tool_call_id == "recover-source")
        self.assertEqual(recovery.status, "success")
        self.assertIn("FINAL_SOURCE_SENTINEL", recovery.text)

    async def test_summarization_offloads_recoverable_history_and_keeps_raw_checkpoint(self):
        from deepagents.middleware.summarization import SummarizationMiddleware

        model = ScriptedModel(responses=[
            AIMessage(content="Earlier lessons covered the interface boundary."),
            call("read_file", {"file_path": "/conversation_history/history-reader.md"}, "recover-history"),
            AIMessage(content="Continuing from the earlier lesson."),
        ])
        agent = create_deep_agent(
            model=model, backend=self.backend, checkpointer=InMemorySaver(), middleware=[
                *self.tutor_middleware(self.backend),
                SummarizationMiddleware(model=model, backend=self.backend,
                                        trigger=("messages", 6), keep=("messages", 2)),
            ],
        )
        history = []
        for index in range(4):
            history.extend([HumanMessage(content=f"Earlier question {index}"),
                            AIMessage(content=f"Earlier explanation {index}")])
        history.append(HumanMessage(content="Continue the lesson"))
        config = {"configurable": {"thread_id": "history-reader"}}
        result = await agent.ainvoke({"messages": history}, config)
        archive = self.root / "conversation_history" / "history-reader.md"
        self.assertIn("Earlier question 0", archive.read_text())
        recovery = next(message for message in result["messages"]
                        if isinstance(message, ToolMessage) and message.tool_call_id == "recover-history")
        self.assertEqual(recovery.status, "success")
        self.assertIn("Earlier question 0", recovery.text)
        state = await agent.aget_state(config)
        saved_questions = [message.text for message in state.values["messages"] if isinstance(message, HumanMessage)]
        self.assertEqual(saved_questions, ["Earlier question 0", "Earlier question 1", "Earlier question 2",
                                           "Earlier question 3", "Continue the lesson"])
        self.assertEqual(state.values["messages"][-1].text, "Continuing from the earlier lesson.")


if __name__ == "__main__":
    unittest.main()
