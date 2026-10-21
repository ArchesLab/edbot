# Shares the student-facing conversation with subagents through a "conversation" state key
import json
from dataclasses import replace
from typing import NotRequired
from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.types import Command, Overwrite
from edbot import model_config
from edbot.interface_def import Message
from edbot.middleware.course_evidence import CourseEvidenceState

class ConversationState(AgentState):
    # Student and edbot messages only, oldest first. deepagents copies every state key
    # except messages/todos/structured_response into subagents, so this one is passed down
    conversation: NotRequired[list[Message]]

def extract_conversation(messages) -> list[Message]:
    """Keep what the student typed and edbot's final replies, dropping tool calls and tool results."""
    conversation = []
    for m in messages:
        if isinstance(m, HumanMessage):
            conversation.append(Message(role="student", content=m.text))
        elif (isinstance(m, AIMessage) and m.text and not m.tool_calls and not m.invalid_tool_calls
              and m.response_metadata.get("finish_reason") != "length"):
            conversation.append(Message(role="edbot", content=m.text))
    return conversation


def _parent_task_result(request, result):
    """Inherited context is read-only in children; only the parent refreshes it."""
    if request.tool_call["name"] == "task" and isinstance(result, Command) and isinstance(result.update, dict):
        update = {key: value for key, value in result.update.items()
                  if key not in {"conversation", "course_evidence"}}
        if len(update) != len(result.update):
            return replace(result, update=update)
    return result


class ConversationMiddleware(AgentMiddleware):
    """Orchestrator side: saves the conversation into state once per student turn."""
    state_schema = ConversationState

    def before_agent(self, state, runtime):
        return {"conversation": extract_conversation(state["messages"])}

    def wrap_tool_call(self, request, handler):
        return _parent_task_result(request, handler(request))

    async def awrap_tool_call(self, request, handler):
        return _parent_task_result(request, await handler(request))

class ChildContextState(ConversationState, CourseEvidenceState):
    """Declare both inherited context fields without a flag that could return to the parent."""


class InjectConversationMiddleware(AgentMiddleware):
    """Seed fresh child context as messages before normal context management runs.

    DeepAgents starts each task with one HumanMessage containing its description.
    Its task result excludes child messages, so this does not rewrite the parent
    checkpoint. Existing child transcripts are left intact on re-entry.
    """
    state_schema = ChildContextState

    def before_agent(self, state, runtime):
        messages = state.get("messages", [])
        if len(messages) != 1 or not isinstance(messages[0], HumanMessage):
            return None
        context = [HumanMessage(content=message.content) if message.role == "student"
                   else AIMessage(content=message.content)
                   for message in state.get("conversation", [])]
        evidence = state.get("course_evidence")
        if model_config.REUSE_COURSE_EVIDENCE and evidence:
            context.append(HumanMessage(content=json.dumps({"course_evidence": evidence}, ensure_ascii=False)))
        if not context:
            return None
        # Overwrite preserves chronological order instead of appending the
        # context after the task. The original task and future tool pairs stay
        # intact, and the summarizer can count/offload all supplied context.
        return {"messages": Overwrite(value=[*context, *messages])}
