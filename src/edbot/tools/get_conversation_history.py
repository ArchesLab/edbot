from langchain.tools import tool, ToolRuntime
from edbot.interface_def import Message

@tool # Tool called by agents before returning conversation history
def get_conversation_history(runtime: ToolRuntime) -> list[Message]:
    """Fetches all conversation messages between user and AI.

    Args:
        runtime: Agent's runtime information from LangChain

    Returns:
        Array of Messages between the user and AI
    """
    # Saved by ConversationMiddleware. Reading state["messages"] instead would break inside a
    # subagent, where it only holds the task description
    return runtime.state.get("conversation", [])