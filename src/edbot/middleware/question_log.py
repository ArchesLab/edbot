# Keeps the question log in step with the orchestrator's subagent calls, so no agent copies rubrics around:
# - CGA generate_question: fills prior_questions from the log, then logs the new question and adds its
#   question_id to the result the orchestrator sees
# - UCA with a question_id: fills answer_submission (question text and rubric) from the log, then records
#   the student's answer and the UCA's verdict
# Listed after validate_subagent_input, so it only sees descriptions that already match the input schemas.
import json
import logging
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from pydantic import ValidationError

from edbot import question_log
from edbot.interface_def import AnswerSubmission, CGAOutput, UCAOutput
from edbot.middleware.validate_input import SUBAGENT_INPUT_SCHEMAS

logger = logging.getLogger(__name__)

# Subagent names, as in subagents.yaml
UCA_NAME = "understanding-checking-agent"
CGA_NAME = "content-generating-agent"
PRIOR_QUESTION_LIMIT = 5 # recent questions the CGA gets for its novelty check

def _student_turn(state) -> int:
    """How many messages the student has sent so far, from the conversation ConversationMiddleware saved."""
    return sum(1 for message in state.get("conversation", []) if message.role == "student")

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

async def _cga_call(request, handler, store, student_id):
    adapter = SUBAGENT_INPUT_SCHEMAS[CGA_NAME]
    cga_input = adapter.validate_json(request.tool_call["args"]["description"])
    if cga_input.mode != "generate_question":
        return await handler(request)

    if not cga_input.prior_questions:
        recent = await question_log.recent_questions(store, student_id, cga_input.concept, PRIOR_QUESTION_LIMIT)
        prior = tuple(
            AnswerSubmission(question_text=q.question_text, rubric=q.rubric, student_answer=q.student_answer or "(not answered yet)")
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
        entry = await question_log.save_question(store, student_id, output, _student_turn(request.state))
    except (ValidationError, ValueError) as e:
        logger.warning("CGA question not logged: %s", e)
        return result
    # The orchestrator passes this question_id to the UCA once the student answers
    return _with_output(result, json.dumps({**json.loads(content), "question_id": entry.question_id}))

async def _uca_call(request, handler, store, student_id):
    adapter = SUBAGENT_INPUT_SCHEMAS[UCA_NAME]
    uca_input = adapter.validate_json(request.tool_call["args"]["description"])
    if uca_input.question_id is None:
        return await handler(request)

    entry = await question_log.load_question(store, student_id, uca_input.question_id)
    if entry is None:
        return _error(request, f"No logged question with question_id '{uca_input.question_id}'. "
                               "Check the ID with fetch_recent_questions and call the UCA again.")
    submission = AnswerSubmission(question_text=entry.question_text, rubric=entry.rubric, student_answer=uca_input.student_answer)
    uca_input = uca_input.model_copy(update={"answer_submission": submission})
    # The UCA only needs answer_submission, as its prompt describes
    description = uca_input.model_dump_json(exclude={"question_id", "student_answer"})
    result = await handler(_with_description(request, description))

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
        store, student_id, entry.question_id, uca_input.student_answer, output.answer_judgment, _student_turn(request.state),
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
