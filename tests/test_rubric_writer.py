"""A practice question's rubric is written after the question is shown, and is ready before grading."""
import asyncio
import json
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage
from pydantic import TypeAdapter
from types import SimpleNamespace
from langgraph.store.memory import InMemoryStore

from edbot import question_log, rubric_writer
from edbot.interface_def import CGAInput, QuestionLogEntry, UCAInput
from edbot.middleware import question_log as question_log_middleware
from edbot.middleware import validate_input

STUDENT = "student"


def entry(question_id="q-1", rubric=None):
    return QuestionLogEntry(question_id=question_id, concept="queues", tier="Apply", format="short_answer",
                            question_text="Which public operation must keep its behavior?", rubric=rubric,
                            asked_at=datetime.now(timezone.utc), asked_at_turn=1)


async def logged(store, item):
    await store.aput(question_log.namespace(STUDENT), item.question_id, item.model_dump(mode="json"))
    return item


class FakeModel:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return self.reply


class WriteRubricTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_the_model_text_and_gives_it_the_question_and_evidence(self):
        model = FakeModel(AIMessage(content="  Correct if: names dequeue.  ", response_metadata={"finish_reason": "stop"}))
        with patch.object(rubric_writer, "_chat_model", return_value=model), \
                patch.object(rubric_writer, "_evidence", return_value="EVIDENCE_PASSAGE"):
            self.assertEqual(await rubric_writer.write_rubric(entry()), "Correct if: names dequeue.")
        task = model.calls[0][-1].content
        self.assertIn("Which public operation must keep its behavior?", task)
        self.assertIn("EVIDENCE_PASSAGE", task)

    async def test_truncated_or_empty_replies_are_rejected(self):
        for reply in (AIMessage(content="Correct if", response_metadata={"finish_reason": "length"}),
                      AIMessage(content="  ", response_metadata={"finish_reason": "stop"})):
            with self.subTest(reply=reply.content), \
                    patch.object(rubric_writer, "_chat_model", return_value=FakeModel(reply)), \
                    patch.object(rubric_writer, "_evidence", return_value=""):
                with self.assertRaises(ValueError):
                    await rubric_writer.write_rubric(entry())


class BackgroundRubricTests(unittest.IsolatedAsyncioTestCase):
    async def test_grading_waits_for_the_background_write(self):
        store, release = InMemoryStore(), asyncio.Event()

        async def slow_write(item):
            await release.wait()
            return "Background rubric"
        item = await logged(store, entry())
        with patch.object(rubric_writer, "write_rubric", side_effect=slow_write) as write:
            rubric_writer.start(store, STUDENT, item)
            waiting = asyncio.create_task(rubric_writer.ensure_rubric(store, STUDENT, item))
            await asyncio.sleep(0)
            self.assertFalse(waiting.done())
            release.set()
            ready = await waiting
        self.assertEqual(ready.rubric, "Background rubric")
        self.assertEqual(write.call_count, 1, "Grading must reuse the running write, not start another")
        self.assertEqual((await question_log.load_question(store, STUDENT, "q-1")).rubric, "Background rubric")
        self.assertEqual(rubric_writer._pending, {})

    async def test_rubric_is_written_on_demand_after_a_restart_or_failed_write(self):
        store = InMemoryStore()
        item = await logged(store, entry())
        with patch.object(rubric_writer, "write_rubric", side_effect=[ValueError("server down"), "Retried rubric"]):
            rubric_writer.start(store, STUDENT, item)
            with self.assertLogs(rubric_writer.logger, "WARNING"):
                ready = await rubric_writer.ensure_rubric(store, STUDENT, item)
        self.assertEqual(ready.rubric, "Retried rubric")

        restarted = await logged(store, entry("q-2"))
        with patch.object(rubric_writer, "write_rubric", return_value="On-demand rubric"):
            self.assertEqual((await rubric_writer.ensure_rubric(store, STUDENT, restarted)).rubric, "On-demand rubric")

    async def test_an_existing_rubric_needs_no_model_call(self):
        item = entry(rubric="Already written")
        with patch.object(rubric_writer, "write_rubric") as write:
            self.assertIs(await rubric_writer.ensure_rubric(InMemoryStore(), STUDENT, item), item)
        write.assert_not_called()

    async def test_a_rubric_that_cannot_be_written_raises(self):
        store = InMemoryStore()
        item = await logged(store, entry())
        with patch.object(rubric_writer, "write_rubric", side_effect=ValueError("server down")):
            with self.assertRaises(ValueError):
                await rubric_writer.ensure_rubric(store, STUDENT, item)


def uca_request(store):
    description = {"concept": "queues", "invocation_context": "answer_submission",
                   "question_id": "q-1", "student_answer": "Keep dequeue's behavior."}
    call = {"name": "task", "id": "assess", "type": "tool_call",
            "args": {"subagent_type": question_log_middleware.UCA_NAME, "description": json.dumps(description)}}
    request = SimpleNamespace(tool_call=call, state={"messages": []},
                              runtime=SimpleNamespace(store=store, context=SimpleNamespace(student_id=STUDENT)))
    request.override = lambda tool_call: SimpleNamespace(**{**vars(request), "tool_call": tool_call})
    return request


class GradingMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    SCHEMAS = {question_log_middleware.CGA_NAME: TypeAdapter(CGAInput),
               question_log_middleware.UCA_NAME: TypeAdapter(UCAInput)}

    async def grade(self, store, **write):
        seen = []

        async def handler(request):
            seen.append(json.loads(request.tool_call["args"]["description"]))
            return ToolMessage(content="not a subagent result", tool_call_id="assess")
        with patch.dict(validate_input.SUBAGENT_INPUT_SCHEMAS, self.SCHEMAS), \
                patch.object(rubric_writer, "write_rubric", **write):
            result = await question_log_middleware.question_log_middleware.awrap_tool_call(uca_request(store), handler)
        return result, seen

    async def test_the_uca_grades_against_the_rubric_written_for_the_question(self):
        store = InMemoryStore()
        await logged(store, entry())
        _, seen = await self.grade(store, return_value="Correct if: dequeue keeps FIFO order.")
        self.assertEqual(seen[0]["answer_submission"]["rubric"], "Correct if: dequeue keeps FIFO order.")

    async def test_no_rubric_returns_an_error_instead_of_grading_without_one(self):
        store = InMemoryStore()
        await logged(store, entry())
        with self.assertLogs(question_log_middleware.logger, "WARNING"):
            result, seen = await self.grade(store, side_effect=ValueError("server down"))
        self.assertEqual(seen, [])
        self.assertEqual(result.status, "error")


if __name__ == "__main__":
    unittest.main()
