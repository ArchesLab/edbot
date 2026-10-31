# Keeps the question log in step with the orchestrator's subagent calls, so no agent copies rubrics around:
# - CGA generate_question: fills prior_questions from the log, then logs the new question, starts writing
#   its rubric in the background (rubric_writer), and adds its question_id to the result the orchestrator sees
# - CGA after a graded UCA this turn: fills answer_feedback with the UCA's verdict
# - UCA with a question_id: fills answer_submission (question text and rubric, waiting for the rubric if
#   it's still being written) from the log, then records the student's answer and the UCA's verdict
# Listed after validate_subagent_input, so it only sees descriptions that already match the input schemas.
import json
import logging
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command
from pydantic import ValidationError

from edbot import model_config, question_log, rubric_writer, turn_count
from edbot.interface_def import AnswerJudgment, AnswerSubmission, CGAOutput, UCAOutput
from edbot.middleware.validate_input import SUBAGENT_INPUT_SCHEMAS

logger = logging.getLogger(__name__)

# Subagent names, as in subagents.yaml
UCA_NAME = "understanding-checking-agent"
CGA_NAME = "content-generating-agent"
PRIOR_QUESTION_LIMIT = 5 # recent questions the CGA gets for its novelty check

def _student_turn(request) -> int:
    """How many messages the student has sent so far, across every chat."""
    return turn_count.current_turn(request.runtime.context, request.state.get("conversation", []))

def _with_description(request, description: str):
    call = request.tool_call
    return request.override(tool_call={**call, "args": {**call["args"], "description": description}})

def _error(request, message: str) -> ToolMessage:
    return ToolMessage(content=message, tool_call_id=request.tool_call["id"], status="error")

def _subagent_output(result) -> str | None:
    """The subagent's JSON output from a finished task() call, or None if the call failed."""
    # A real subagent run returns a Command whose only message is the output; errors are a bare ToolMessage
    if not isinstance(result, Command):
        return None
    messages = result.update.get("messages", [])
    return messages[-1].content if messages else None

def _with_output(result: Command, content: str) -> Command:
    """The same task() result, with the subagent's output replaced by content."""
    old = result.update["messages"][-1]
    message = ToolMessage(content=content, tool_call_id=old.tool_call_id)
    return Command(update={**result.update, "messages": [*result.update["messages"][:-1], message]})

def _turn_judgment(state) -> AnswerJudgment | None:
    """The answer_judgment from this turn's successful UCA task, if it graded an answer."""
    messages = state.get("messages", [])
    start = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)), None)
    if start is None:
        return None
    current = messages[start + 1:]
    uca_ids = {call["id"] for message in current if isinstance(message, AIMessage)
               for call in message.tool_calls
               if call["name"] == "task" and call["args"].get("subagent_type") == UCA_NAME}
    results = [message for message in current
               if isinstance(message, ToolMessage) and message.tool_call_id in uca_ids]
    # More than one assessment this turn is ambiguous; leave feedback to the parent's synthesis
    if len(results) != 1 or results[0].status != "success" or not isinstance(results[0].content, str):
        return None
    try:
        return UCAOutput.model_validate_json(results[0].content).answer_judgment
    except ValidationError:
        return None

async def _cga_call(request, handler, store, student_id):
    adapter = SUBAGENT_INPUT_SCHEMAS[CGA_NAME]
    cga_input = adapter.validate_json(request.tool_call["args"]["description"])
    if model_config.CGA_ANSWER_FEEDBACK and (judgment := _turn_judgment(request.state)):
        cga_input = cga_input.model_copy(update={"answer_feedback": judgment})
        request = _with_description(request, adapter.dump_json(cga_input).decode())
    if cga_input.mode != "generate_question":
        return await handler(request)

    if not cga_input.prior_questions:
        recent = await question_log.recent_questions(store, student_id, cga_input.concept, PRIOR_QUESTION_LIMIT)
        prior = tuple(
            AnswerSubmission(question_text=q.question_text, rubric=q.rubric or "", student_answer=q.student_answer or "(not answered yet)")
            for q in recent
        )
        cga_input = cga_input.model_copy(update={"prior_questions": prior})
        request = _with_description(request, adapter.dump_json(cga_input).decode())

    result = await handler(request)
    content = _subagent_output(result)
    if content is None:
        return result
    try:
        output = CGAOutput.model_validate_json(content)
        entry = await question_log.save_question(store, student_id, output, _student_turn(request))
    except (ValidationError, ValueError) as e:
        logger.warning("CGA question not logged: %s", e)
        return result
    rubric_writer.start(store, student_id, entry)
    # The orchestrator passes this question_id to the UCA once the student answers
    return _with_output(result, json.dumps({**json.loads(content), "question_id": entry.question_id}))

async def _uca_call(request, handler, store, student_id):
    adapter = SUBAGENT_INPUT_SCHEMAS[UCA_NAME]
    uca_input = adapter.validate_json(request.tool_call["args"]["description"])
    # The UCA only ever sees answer_submission, as its prompt describes
    hidden = {"question_id", "student_answer"}
    if uca_input.question_id is None:
        return await handler(_with_description(request, uca_input.model_dump_json(exclude=hidden)))

    entry = await question_log.load_question(store, student_id, uca_input.question_id)
    if entry is None:
        return _error(request, f"No logged question with question_id '{uca_input.question_id}'. "
                               "Check the ID with fetch_recent_questions and call the UCA again.")
    try:
        entry = await rubric_writer.ensure_rubric(store, student_id, entry)
    except Exception as e:
        logger.warning("No rubric for question %s: %s", entry.question_id, e)
        return _error(request, "The answer key for this question isn't available, so it can't be graded right now. "
                               "Respond to the student without grading the answer.")
    submission = AnswerSubmission(question_text=entry.question_text, rubric=entry.rubric, student_answer=uca_input.student_answer)
    uca_input = uca_input.model_copy(update={"answer_submission": submission})
    result = await handler(_with_description(request, uca_input.model_dump_json(exclude=hidden)))

    content = _subagent_output(result)
    if content is None:
        return result
    try:
        output = UCAOutput.model_validate_json(content)
    except ValidationError as e:
        logger.warning("UCA verdict not logged: %s", e)
        return result
    if output.answer_judgment is None:
        logger.warning("UCA returned no answer_judgment for question %s", entry.question_id)
        return result
    await question_log.record_answer(
        store, student_id, entry.question_id, uca_input.student_answer, output.answer_judgment, _student_turn(request),
    )
    return result

class QuestionLogMiddleware(AgentMiddleware):
    def wrap_tool_call(self, request, handler):
        # The log's store calls are async, and edbot only runs the agent with astream() (see service.chat_turn)
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        if call["name"] != "task":
            return await handler(request)
        store, student_id = request.runtime.store, request.runtime.context.student_id
        subagent = call["args"].get("subagent_type")
        if subagent == CGA_NAME:
            return await _cga_call(request, handler, store, student_id)
        if subagent == UCA_NAME:
            return await _uca_call(request, handler, store, student_id)
        return await handler(request)

question_log_middleware = QuestionLogMiddleware()
