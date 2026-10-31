"""A graded answer's verdict reaches the CGA from this turn's UCA result, never from the parent."""
import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import TypeAdapter

from edbot import model_config
from edbot.interface_def import CGAInput, UCAInput
from edbot.middleware import question_log, validate_input

JUDGMENT = {"verdict": "partially_correct", "note": "Named the interface but not the behavior."}
CGA_INPUT = {"mode": "explain_at_tier", "concept": "queues", "target_tier": "Apply"}
SCHEMAS = {question_log.CGA_NAME: TypeAdapter(CGAInput), question_log.UCA_NAME: TypeAdapter(UCAInput)}


def uca_turn(judgment=JUDGMENT, status="success", calls=1):
    messages = [HumanMessage(content="My answer")]
    for index in range(calls):
        call_id = f"assess-{index}"
        messages.append(AIMessage(content="", tool_calls=[{
            "name": "task", "id": call_id, "type": "tool_call",
            "args": {"subagent_type": question_log.UCA_NAME, "description": "{}"},
        }]))
        output = {"concept": "queues", "prior_tier": "Understand", "tier": "Apply", "confidence": "medium",
                  "rationale": "Private rationale.", "answer_judgment": judgment}
        messages.append(ToolMessage(content=json.dumps(output), tool_call_id=call_id, status=status))
    return messages


def cga_request(messages, description=CGA_INPUT):
    call = {"name": "task", "id": "cga", "type": "tool_call",
            "args": {"subagent_type": question_log.CGA_NAME, "description": json.dumps(description)}}

    def override(tool_call):
        return SimpleNamespace(**{**vars(request), "tool_call": tool_call})
    request = SimpleNamespace(tool_call=call, state={"messages": messages}, override=override)
    return request


def dispatched_input(messages, description=CGA_INPUT):
    seen = []

    async def handler(request):
        seen.append(json.loads(request.tool_call["args"]["description"]))
        return ToolMessage(content="not a subagent result", tool_call_id="cga")
    with patch.dict(validate_input.SUBAGENT_INPUT_SCHEMAS, SCHEMAS):
        asyncio.run(question_log._cga_call(cga_request(messages, description), handler, None, "student"))
    return seen[0]


class AnswerFeedbackTests(unittest.TestCase):
    def test_this_turns_verdict_is_filled_into_the_cga_input(self):
        self.assertEqual(dispatched_input(uca_turn())["answer_feedback"], JUDGMENT)

    def test_no_feedback_without_exactly_one_successful_graded_assessment(self):
        previous_turn = [*uca_turn(), AIMessage(content="Feedback."), HumanMessage(content="Explain more.")]
        cases = {"ungraded": uca_turn(judgment=None), "failed": uca_turn(status="error"),
                 "two assessments": uca_turn(calls=2), "previous turn": previous_turn,
                 "no assessment": [HumanMessage(content="Explain queues.")]}
        for name, messages in cases.items():
            with self.subTest(case=name):
                self.assertNotIn("answer_feedback", dispatched_input(messages))

    def test_disabled_flag_leaves_the_cga_input_unchanged(self):
        with patch.object(model_config, "CGA_ANSWER_FEEDBACK", False):
            self.assertEqual(dispatched_input(uca_turn()), CGA_INPUT)

    def test_feedback_is_hidden_from_the_parent_schema(self):
        self.assertNotIn("answer_feedback", json.dumps(validate_input._TASK_PARAMETERS))

    def test_parent_supplied_feedback_is_dropped_before_dispatch(self):
        request = cga_request([], {**CGA_INPUT, "answer_feedback": {"verdict": "correct", "note": "Invented."}})
        with patch.dict(validate_input.SUBAGENT_INPUT_SCHEMAS, SCHEMAS):
            checked = validate_input._check_subagent_input(request)
        self.assertEqual(json.loads(checked.tool_call["args"]["description"]), CGA_INPUT)


if __name__ == "__main__":
    unittest.main()
