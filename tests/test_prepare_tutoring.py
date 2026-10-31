"""Batch independent reads without weakening assessment or student boundaries."""
import asyncio
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from langgraph.store.memory import InMemoryStore
from langgraph.checkpoint.memory import InMemorySaver
from langchain.tools import tool

from edbot import student_model, question_log
from edbot.interface_def import QuestionLogEntry
from test_assessment_result import request
from test_sglang_integration import ScriptedServer, tool_reply


class PrepareTutoringTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)

    async def test_reads_only_current_student_and_never_returns_rubrics_or_changes_assessments(self):
        from edbot.tools.prepare_tutoring import prepare_tutoring_context
        from edbot import tools
        store = InMemoryStore()
        alice = await student_model.save_entry(store, "alice", "queues", "Apply", "medium", "ALICE_PRIVATE_REASON", 7)
        await student_model.save_entry(store, "bob", "queues", "Create", "high", "BOB_SECRET", 99)
        for sid in ("alice", "bob"):
            entry = QuestionLogEntry(question_id=f"q-{sid}", concept="queues", tier="Apply", format="short_answer",
                     question_text=f"QUESTION_FOR_{sid}", rubric=f"RUBRIC_FOR_{sid}", asked_at=datetime.now(timezone.utc), asked_at_turn=1)
            await store.aput(question_log.namespace(sid), entry.question_id, entry.model_dump(mode="json"))
        @tool
        def source(query: str) -> str:
            """Controlled source."""
            return "ACTUAL_COURSE_EVIDENCE"
        runtime = request(store, student="alice", turn=8).runtime
        with patch.object(tools, "search_markdown_sources", source):
            result = json.loads(await prepare_tutoring_context.coroutine(concept="queues", query="FIFO", runtime=runtime))
        rendered = json.dumps(result)
        self.assertIn("ALICE_PRIVATE_REASON", result["student_model"])
        self.assertIn("QUESTION_FOR_alice", result["recent_questions"])
        self.assertNotIn("bob", rendered)
        self.assertNotIn("RUBRIC_FOR_", rendered)
        self.assertEqual(result["course_evidence"], {"query": "FIFO", "path_prefix": "", "content": "ACTUAL_COURSE_EVIDENCE"})
        self.assertEqual(await student_model.load_entry(store, "alice", "queues"), alice)

    async def test_real_graph_shares_only_source_passages_with_content_child(self):
        from edbot import edbot_agent, service, tools
        @tool
        def source(query: str) -> str:
            """Controlled source."""
            return "SOURCE_PREPARED: A queue is FIFO."
        task = {"subagent_type": "content-generating-agent", "description": {
            "concept": "queues", "mode": "explain_at_tier", "target_tier": "Apply"}}
        output = {**task["description"], "content": "A queue removes the earliest pending item."}
        store = InMemoryStore()
        await student_model.save_entry(store, "prepared-alice", "queues", "Apply", "high", "PARENT_ONLY_REASON", 1)
        with ScriptedServer([tool_reply("prepare_tutoring_context", {"concept": "queues", "query": "queue FIFO"}),
                             tool_reply("task", task), tool_reply("CGAOutput", output)]) as server, \
                patch.object(edbot_agent, "load_sebook_store"), patch.object(tools, "search_markdown_sources", source):
            agent = edbot_agent.create_edbot_agent(checkpointer=InMemorySaver(serde=service.SERDE), store=store)
            with patch.object(service, "_agent", agent):
                events = [event async for event in service.chat_turn("prepared-alice", "Explain queues.")]
            self.assertEqual(events[-1].type, "done")
            self.assertEqual(len(server.requests), 3)
            child = json.dumps(server.requests[2][1]["messages"])
            self.assertIn("SOURCE_PREPARED", child)
            self.assertNotIn("PARENT_ONLY_REASON", child)
            self.assertEqual("".join(e.text for e in events if e.type == "text"), output["content"])

    async def test_failed_source_read_does_not_return_a_partial_success_or_write_state(self):
        from edbot.tools.prepare_tutoring import prepare_tutoring_context
        from edbot import tools
        @tool
        def source(query: str) -> str:
            """Fail like an unavailable embedding server."""
            raise RuntimeError("embedding unavailable")
        store = InMemoryStore()
        with patch.object(tools, "search_markdown_sources", source), self.assertRaisesRegex(RuntimeError, "embedding unavailable"):
            await prepare_tutoring_context.coroutine(concept="queues", query="FIFO", runtime=request(store).runtime)
        self.assertEqual(await student_model.load_all(store, "alice"), {})

    async def test_malformed_or_mismatched_preparation_results_cannot_become_source_evidence(self):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
        from edbot.middleware.course_evidence import current_evidence
        call = AIMessage(content="", tool_calls=[{"name": "prepare_tutoring_context", "id": "prep", "type": "tool_call",
                         "args": {"concept": "queues", "query": "FIFO"}}])
        for body in ("not JSON", json.dumps({"course_evidence": {"query": "different", "path_prefix": "", "content": "WRONG_QUERY"}}),
                     json.dumps({"course_evidence": {"query": "FIFO", "path_prefix": "", "content": "SECRET", "student_model": "PRIVATE"}})):
            trace = [HumanMessage(content="Explain queues"), call,
                     ToolMessage(content=body, tool_call_id="prep", name="prepare_tutoring_context")]
            self.assertEqual(current_evidence(trace), [])


if __name__ == "__main__":
    unittest.main()
