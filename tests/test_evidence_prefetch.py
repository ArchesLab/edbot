"""Code-owned retrieval before child tasks, carried across same-concept turns, and the child search limit."""
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import MagicMock, patch

from langchain.tools import ToolRuntime
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from edbot import model_config
from edbot.interface_def import EdbotContext, QuestionLogEntry
from edbot.middleware.course_evidence import (MAX_CHILD_SEARCHES, LimitChildSearches, PrefetchCourseEvidence,
                                              _within_budget)
from edbot.question_log import namespace


def store_returning(*contents):
    store = MagicMock()
    store.similarity_search.return_value = [Document(page_content=text) for text in contents]
    return store


def task_request(state, description, subagent="content-generating-agent", store=None):
    call = {"name": "task", "id": "task-1", "type": "tool_call",
            "args": {"subagent_type": subagent, "description": json.dumps(description)}}
    runtime = ToolRuntime(state=state, context=EdbotContext(student_id="s1"), config={}, stream_writer=None,
                          tool_call_id="task-1", store=store)
    return ToolCallRequest(tool_call=call, tool=None, state=state, runtime=runtime)


class Child:
    """Records the state the child would start from and returns a task-shaped Command."""

    def __init__(self):
        self.states = []

    async def __call__(self, request):
        self.states.append(request.runtime.state)
        return Command(update={"messages": [ToolMessage(content="{}", tool_call_id="task-1")]})


EXPLAIN = {"mode": "explain_at_tier", "concept": "queues", "target_tier": "Apply"}


class PrefetchTests(unittest.IsolatedAsyncioTestCase):
    async def run_task(self, middleware, state, description=EXPLAIN, **kwargs):
        child = Child()
        result = await middleware.awrap_tool_call(task_request(state, description, **kwargs), child)
        return child.states[0], result.update.get("carried_evidence")

    async def test_child_starts_with_code_search_and_the_turns_parent_results(self):
        store = store_returning("PREFETCHED")
        state = {"messages": [HumanMessage(content="How do queues work?", id="m1")],
                 "course_evidence": [{"query": "parent", "path_prefix": "", "content": "PARENT_RESULT"}]}
        child_state, carried = await self.run_task(PrefetchCourseEvidence(lambda: store), state)
        store.similarity_search.assert_called_once()
        self.assertEqual(store.similarity_search.call_args.args[0], "queues: How do queues work?")
        contents = [row["content"] for row in child_state["course_evidence"]]
        self.assertTrue(any("PREFETCHED" in text for text in contents))
        self.assertIn("PARENT_RESULT", contents)
        self.assertEqual(carried["concept"], "queues")
        self.assertEqual(carried["evidence"], child_state["course_evidence"])

    async def test_second_task_in_a_turn_reuses_the_pool_without_searching(self):
        store = store_returning("PREFETCHED")
        middleware = PrefetchCourseEvidence(lambda: store)
        state = {"messages": [HumanMessage(content="Quiz me on queues", id="m1")]}
        _, carried = await self.run_task(middleware, state)
        child_state, _ = await self.run_task(middleware, {**state, "carried_evidence": carried},
                                             subagent="understanding-checking-agent",
                                             description={"concept": "queues", "invocation_context": "practice_request"})
        store.similarity_search.assert_called_once()
        self.assertEqual(child_state["course_evidence"], carried["evidence"])

    async def test_later_same_concept_turn_adds_to_the_pool_and_a_new_concept_resets_it(self):
        store = store_returning("FIRST")
        middleware = PrefetchCourseEvidence(lambda: store)
        _, carried = await self.run_task(middleware, {"messages": [HumanMessage(content="Explain queues", id="m1")]})
        store.similarity_search.return_value = [Document(page_content="FIRST"), Document(page_content="SECOND")]
        later = {"messages": [HumanMessage(content="And priority queues?", id="m2")], "carried_evidence": carried}
        child_state, carried = await self.run_task(middleware, later)
        text = json.dumps(child_state["course_evidence"])
        self.assertIn("FIRST", text)
        self.assertIn("SECOND", text)
        self.assertEqual(text.count("FIRST"), 1, "a chunk already in the pool is not supplied twice")

        store.similarity_search.return_value = [Document(page_content="STACKS")]
        other = {"messages": [HumanMessage(content="Now stacks", id="m3")], "carried_evidence": carried}
        child_state, carried = await self.run_task(middleware, other, description={**EXPLAIN, "concept": "stacks"})
        text = json.dumps(child_state["course_evidence"])
        self.assertIn("STACKS", text)
        self.assertNotIn("FIRST", text)
        self.assertEqual(carried["concept"], "stacks")

    async def test_answer_submission_query_uses_the_logged_question(self):
        store = store_returning("PASSAGE")
        log = InMemoryStore()
        entry = QuestionLogEntry(question_id="q-1", concept="queues", tier="Apply", format="short_answer",
                                 question_text="Which end does dequeue remove from?",
                                 asked_at=datetime.now(timezone.utc), asked_at_turn=1)
        await log.aput(namespace("s1"), "q-1", entry.model_dump(mode="json"))
        state = {"messages": [HumanMessage(content="the front", id="m1")]}
        await self.run_task(PrefetchCourseEvidence(lambda: store), state, store=log,
                            subagent="understanding-checking-agent",
                            description={"concept": "queues", "invocation_context": "answer_submission",
                                         "question_id": "q-1", "student_answer": "the front"})
        query = store.similarity_search.call_args.args[0]
        self.assertIn("Which end does dequeue remove from?", query)
        self.assertIn("the front", query)

    async def test_disabled_flag_or_other_tools_pass_through_untouched(self):
        store = store_returning("PREFETCHED")
        state = {"messages": [HumanMessage(content="Explain queues", id="m1")]}
        with patch.object(model_config, "PREFETCH_COURSE_EVIDENCE", False):
            child_state, carried = await self.run_task(PrefetchCourseEvidence(lambda: store), state)
        self.assertNotIn("course_evidence", child_state)
        self.assertIsNone(carried)
        store.similarity_search.assert_not_called()

    def test_budget_keeps_newest_whole_rows_without_duplicates(self):
        rows = [{"query": "q", "path_prefix": "", "content": text} for text in ("old", "dup", "dup", "new")]
        self.assertEqual([row["content"] for row in _within_budget(rows)], ["old", "dup", "new"])
        self.assertEqual([row["content"] for row in _within_budget(rows, limit=5)], ["new"])


class ChildSearchLimitTests(unittest.TestCase):
    def request(self, messages, evidence=True):
        state = {"messages": messages, "course_evidence": [{"content": "E"}] if evidence else []}
        call = {"name": "search_markdown_sources", "id": "s-next", "args": {"query": "q"}, "type": "tool_call"}
        return ToolCallRequest(tool_call=call, tool=None, state=state, runtime=None)

    def searched(self, count):
        return [ToolMessage(content="chunk", name="search_markdown_sources", tool_call_id=f"s{i}")
                for i in range(count)]

    def test_search_within_the_limit_runs(self):
        handler = MagicMock(return_value="RAN")
        self.assertEqual(LimitChildSearches().wrap_tool_call(self.request(self.searched(MAX_CHILD_SEARCHES - 1)), handler), "RAN")

    def test_search_past_the_limit_is_refused_without_a_tool_error(self):
        handler = MagicMock()
        result = LimitChildSearches().wrap_tool_call(self.request(self.searched(MAX_CHILD_SEARCHES)), handler)
        handler.assert_not_called()
        self.assertIsInstance(result, ToolMessage)
        self.assertEqual(result.status, "success") # the UCA's completion guard fails on any tool error
        self.assertEqual(result.tool_call_id, "s-next")

    def test_no_supplied_evidence_or_disabled_flag_means_no_limit(self):
        handler = MagicMock(return_value="RAN")
        many = self.searched(MAX_CHILD_SEARCHES + 2)
        self.assertEqual(LimitChildSearches().wrap_tool_call(self.request(many, evidence=False), handler), "RAN")
        with patch.object(model_config, "LIMIT_CHILD_SEARCHES", False):
            self.assertEqual(LimitChildSearches().wrap_tool_call(self.request(many), handler), "RAN")


if __name__ == "__main__":
    unittest.main()
