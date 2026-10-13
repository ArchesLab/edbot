# Long-lived agent setup shared by every interface (the CLI now, Chainlit and FastAPI later)
import asyncio
import logging
from collections.abc import AsyncIterator
import aiosqlite
from pydantic import BaseModel
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from edbot import interface_def
from edbot.interface_def import Status, TextDelta, Done, Error, TurnEvent
from edbot.edbot_agent import ROOT_DIR, create_edbot_agent

logger = logging.getLogger(__name__)

# Saved conversations, one thread per student. src/.cache/ is gitignored
CHECKPOINT_PATH = ROOT_DIR.parent / ".cache" / "checkpoints.sqlite"

# LangGraph only rebuilds known-safe types when loading a checkpoint, and with an allowlist it
# drops everything else. Our schemas end up in state (Message in "conversation", subagent outputs
# like CGAOutput), so allow every model defined in interface_def, including ones added later
STATE_TYPES = [
    obj for obj in vars(interface_def).values()
    if isinstance(obj, type) and issubclass(obj, BaseModel) and obj.__module__ == interface_def.__name__
]
SERDE = JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES) # allowlist of classes it may rebuild when loading a checkpoint 

_agent = None
_conn: aiosqlite.Connection | None = None
_lock = asyncio.Lock() # so two students' first messages don't build the agent twice

async def get_agent():
    """Build the agent and open the checkpointer on first use, then reuse them for every turn."""
    global _agent, _conn # assignments change global level, instead of creating local variables
    async with _lock:
        if _agent is None:
            CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True) # src/.cache/ if doesn't exist
            _conn = await aiosqlite.connect(CHECKPOINT_PATH) # creates the databse file
            # Building syncs the SEBook and loads its embeddings, so run it off the event loop
            _agent = await asyncio.to_thread(create_edbot_agent, AsyncSqliteSaver(_conn, serde=SERDE)) # checkpointer that writes/reads conversation state in db
    return _agent

async def close():
    """Close the checkpointer's database connection. Call on shutdown."""
    global _agent, _conn
    if _conn is not None:
        await _conn.close()
    _agent = _conn = None

def config_for(student_id: str) -> dict:
    """Each student has one ongoing conversation, so the student ID is the thread ID."""
    return {"configurable": {"thread_id": student_id}}

async def saved_message_count(student_id: str) -> int:
    """How many messages are saved in this student's conversation (0 for a new student)."""
    agent = await get_agent()
    state = await agent.aget_state(config_for(student_id)) # loads latest checkpoint for that thread
    return len(state.values.get("messages", [])) # state.values is the saved state dict

# What the student sees while a tool runs. Never name the tool or a subagent
STATUS_FOR_TOOL = {
    "search_markdown_sources": "Looking through course material…",
    "task": "Working on your answer…",
}
DEFAULT_STATUS = "Thinking…"

# Tool calls only show up at the end of a model message, so text at the start of a message
# might be a preamble to a tool call ("Let me look that up") rather than the reply. Hold back
# this many characters of each message; drop them if a tool call follows, else start streaming
REPLY_HOLDBACK_CHARS = 200

TURN_TIMEOUT_SECONDS = 600 # a hung Ollama otherwise blocks the turn forever

ERROR_MESSAGE = "Sorry, something went wrong on my end. Please try sending your message again."

def _is_orchestrator_output(chunk, metadata) -> bool:
    """Only the orchestrator's own model output can reach the student.

    Excludes tool results (SEBook chunks, raw subagent output) and anything from a nested
    graph such as a subagent, whose namespace contains "|".
    """
    return (
        isinstance(chunk, AIMessageChunk)
        and metadata.get("langgraph_node") == "model"
        and "|" not in (metadata.get("langgraph_checkpoint_ns") or "")
    )

async def chat_turn(student_id: str, message: str) -> AsyncIterator[TurnEvent]:
    """Run one turn for one student, yielding only what the student should see.

    Yields Status events while tools run, TextDelta pieces of the final reply, then Done,
    or Error if the turn fails. Every interface (CLI, Chainlit, FastAPI) goes through this.
    """
    agent = await get_agent()
    last_status = DEFAULT_STATUS
    yield Status(text=last_status)

    message_id = None  # the orchestrator message currently streaming
    held = ""          # its text not yet sent to the student
    live = False       # True once it passed the holdback and is streaming as the reply
    calls_tools = False

    try:
        async with asyncio.timeout(TURN_TIMEOUT_SECONDS):
            # Only the new message: the checkpointer loads the rest of this student's conversation
            async for chunk, metadata in agent.astream(
                {"messages": [{"role": "user", "content": message}]},
                config=config_for(student_id),
                stream_mode="messages",
            ):
                if not _is_orchestrator_output(chunk, metadata):
                    continue

                if chunk.id != message_id:
                    # The previous message finished without a tool call, so short text it held was a reply
                    if held and not calls_tools:
                        yield TextDelta(text=held)
                    message_id, held, live, calls_tools = chunk.id, "", False, False

                if chunk.tool_call_chunks:
                    if live:
                        logger.warning("Orchestrator called a tool after its text was streamed to %s", student_id)
                    calls_tools, held = True, ""
                    for tool_call in chunk.tool_call_chunks:
                        # Tool calls stream in pieces; only the first piece of each carries the name
                        status = STATUS_FOR_TOOL.get(tool_call.get("name") or "", DEFAULT_STATUS)
                        if tool_call.get("name") and status != last_status:
                            last_status = status
                            yield Status(text=status)

                if calls_tools or not chunk.text:
                    continue
                if live:
                    yield TextDelta(text=chunk.text)
                    continue
                held += chunk.text
                if len(held) >= REPLY_HOLDBACK_CHARS:
                    yield TextDelta(text=held)
                    held, live = "", True

        if held and not calls_tools:
            yield TextDelta(text=held)
        yield Done()
    except TimeoutError:
        logger.error("Turn for %s timed out after %ss", student_id, TURN_TIMEOUT_SECONDS)
        yield Error(message=ERROR_MESSAGE)
    except Exception:
        logger.exception("Turn for %s failed", student_id)
        yield Error(message=ERROR_MESSAGE)
