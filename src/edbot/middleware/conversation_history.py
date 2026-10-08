# Shares the student-facing conversation with subagents through a "conversation" state key
from typing import NotRequired
from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from edbot.interface_def import Message

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
        elif isinstance(m, AIMessage) and m.text and not m.tool_calls:
            conversation.append(Message(role="edbot", content=m.text))
    return conversation

class ConversationMiddleware(AgentMiddleware):
    """Orchestrator side: saves the conversation into state once per student turn."""
    state_schema = ConversationState

    def before_agent(self, state, runtime):
        return {"conversation": extract_conversation(state["messages"])}

class InjectConversationMiddleware(AgentMiddleware):
    """Subagent side: adds the conversation passed down from the orchestrator to the system prompt.

    Must not rebuild the key itself: inside a subagent, state["messages"] only holds the task description.
    """
    state_schema = ConversationState # declares the key so the subagent doesn't drop it

    def wrap_model_call(self, request, handler):
        conversation = request.state.get("conversation")
        if not conversation:
            return handler(request)
        lines = "\n\n".join(f"**{m.role}:** {m.content}" for m in conversation)
        # Added per model call rather than written to state, so it never piles up in messages
        prompt = (request.system_prompt or "") + f"\n\n## Conversation so far (oldest first)\n\n{lines}"
        return handler(request.override(system_message=SystemMessage(content=prompt)))