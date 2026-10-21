# Long-lived agent setup shared by every interface (the CLI now, Chainlit and FastAPI later)
import asyncio
import logging
from collections.abc import AsyncIterator
import aiosqlite
from pydantic import BaseModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore

from edbot import interface_def, student_model
from edbot.interface_def import EdbotContext, Message, StudentModelEntry, Status, TextDelta, Done, Error, TurnEvent
from edbot.middleware.conversation_history import extract_conversation
from edbot.edbot_agent import ROOT_DIR, create_edbot_agent

logger = logging.getLogger(__name__)

# Saved conversations, one thread per student. src/.cache/ is gitignored
CHECKPOINT_PATH = ROOT_DIR.parent / ".cache" / "checkpoints.sqlite"
# The store: the student model, one entry per student per concept (see student_model.py)
STORE_PATH = ROOT_DIR.parent / ".cache" / "student_model.sqlite"

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
_store_conn: aiosqlite.Connection | None = None
_store: AsyncSqliteStore | None = None
_lock = asyncio.Lock() # so two students' first messages don't build the agent twice

async def get_agent():
    """Build the agent and open the checkpointer and store on first use, then reuse them for every turn."""
    global _agent, _conn, _store_conn, _store # assignments change global level, instead of creating local variables
    async with _lock:
        if _agent is None:
            CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True) # src/.cache/ if doesn't exist
            _conn = await aiosqlite.connect(CHECKPOINT_PATH) # creates the databse file
            # isolation_level=None: the store runs its own BEGIN/COMMIT, which collides with
            # Python's default of starting transactions automatically
            _store_conn = await aiosqlite.connect(STORE_PATH, isolation_level=None)
            _store = AsyncSqliteStore(_store_conn)
            await _store.setup() # creates the store's tables on first run, no-op after
            # Building syncs the SEBook and loads its embeddings, so run it off the event loop
            _agent = await asyncio.to_thread(
                create_edbot_agent,
                AsyncSqliteSaver(_conn, serde=SERDE), # checkpointer that writes/reads conversation state in db
                _store,
            )
    return _agent

async def close():
    """Close the checkpointer's and store's database connections. Call on shutdown."""
    global _agent, _conn, _store_conn, _store
    for conn in (_conn, _store_conn):
        if conn is not None:
            await conn.close()
    _agent = _conn = _store_conn = _store = None

def config_for(student_id: str) -> dict:
    """Each student has one ongoing conversation, so the student ID is the thread ID."""
    return {"configurable": {"thread_id": student_id}}

async def saved_message_count(student_id: str) -> int:
    """How many messages are saved in this student's conversation (0 for a new student)."""
    agent = await get_agent()
    state = await agent.aget_state(config_for(student_id)) # loads latest checkpoint for that thread
    return len(state.values.get("messages", [])) # state.values is the saved state dict

async def get_history(student_id: str) -> list[Message]:
    """The student's saved conversation as they saw it: their messages and edbot's final replies.

    Tool calls, tool results, and subagent output are dropped, same as in chat_turn().
    """
    agent = await get_agent()
    state = await agent.aget_state(config_for(student_id))
    return extract_conversation(state.values.get("messages", []))

async def get_student_model(student_id: str) -> dict[str, StudentModelEntry]:
    """Every concept the UCA has assessed for this student, keyed by concept ID. Never shown to students."""
    await get_agent() # opens the store
    return await student_model.load_all(_store, student_id)

# What the student sees while a tool runs. Never name the tool or a subagent
STATUS_FOR_TOOL = {
    "search_markdown_sources": "Looking through course material…",
    "task": "Working on your answer…",
}
DEFAULT_STATUS = "Thinking…"

# Tool calls can arrive after an arbitrarily long parent preamble. Hold the
# complete message until its tool status and finish reason are known.

TURN_TIMEOUT_SECONDS = 600 # a hung Ollama otherwise blocks the turn forever

ERROR_MESSAGE = "Sorry, something went wrong on my end. Please try sending your message again."

_turn_locks: dict[str, asyncio.Lock] = {} # one per student ID, created on their first turn

def _is_orchestrator_output(chunk, metadata) -> bool:
    """Only the orchestrator's own model output can reach the student.

    Excludes tool results (SEBook chunks, raw subagent output) and anything from a nested
    graph such as a subagent, whose namespace contains "|".
    """
    return (
        isinstance(chunk, AIMessage)
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
    calls_tools = False

    try:
        # One turn at a time per student (two tabs, a double-send): concurrent turns on the same
        # thread would both write checkpoints. A second message waits here, showing "Thinking…"
        async with asyncio.timeout(TURN_TIMEOUT_SECONDS), _turn_locks.setdefault(student_id, asyncio.Lock()):
            # Only the new message: the checkpointer loads the rest of this student's conversation
            async for chunk, metadata in agent.astream(
                {"messages": [{"role": "user", "content": message}]},
                config=config_for(student_id),
                # The one place the student ID enters a run: tools read it as runtime.context.student_id
                context=EdbotContext(student_id=student_id),
                stream_mode="messages",
            ):
                if not _is_orchestrator_output(chunk, metadata):
                    continue

                if chunk.response_metadata.get("finish_reason") == "length":
                    raise ValueError("Reply reached its output limit; no complete reply is available")
                # A complete middleware/model message can carry invalid calls
                # without stream fragments. Partial chunks may still become
                # valid JSON, so only reject complete messages here.
                if not isinstance(chunk, AIMessageChunk) and chunk.invalid_tool_calls:
                    raise ValueError("Reply returned an invalid tool call; no complete reply is available")

                if chunk.id != message_id:
                    # Only a completed, tool-free parent message is public.
                    if held and not calls_tools:
                        yield TextDelta(text=held)
                    message_id, held, calls_tools = chunk.id, "", False

                tool_calls = getattr(chunk, "tool_call_chunks", None) or chunk.tool_calls
                if tool_calls:
                    calls_tools, held = True, ""
                    for tool_call in tool_calls:
                        # Tool calls stream in pieces; only the first piece of each carries the name
                        status = STATUS_FOR_TOOL.get(tool_call.get("name") or "", DEFAULT_STATUS)
                        if tool_call.get("name") and status != last_status:
                            last_status = status
                            yield Status(text=status)

                if calls_tools or not chunk.text:
                    continue
                held += chunk.text

        if held and not calls_tools:
            yield TextDelta(text=held)
        yield Done()
    except TimeoutError:
        logger.error("Turn for %s timed out after %ss", student_id, TURN_TIMEOUT_SECONDS)
        yield Error(message=ERROR_MESSAGE)
    except Exception:
        logger.exception("Turn for %s failed", student_id)
        yield Error(message=ERROR_MESSAGE)
