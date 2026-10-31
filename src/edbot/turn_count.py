# One message counter per student, kept in the LangGraph store next to the student model. It never
# resets, even in a new chat, so the turn fields (assessed_at_turn, asked_at_turn, answered_at_turn)
# stay comparable across chats: the stale-assessment check and the cadence backstop rely on that.
import asyncio
from langgraph.store.base import BaseStore

from edbot import question_log, student_model

TURN_KEY = "turn_count"
_locks: dict[str, asyncio.Lock] = {} # one per student, so two chats at once can't take the same turn

def namespace(student_id: str) -> tuple[str, str, str]:
    """Where one student's counter lives in the store."""
    return ("students", student_id, "meta")

async def _highest_saved_turn(store: BaseStore, student_id: str) -> int:
    """Highest turn already saved for this student, from before the counter existed (0 if none)."""
    entries = await student_model.load_all(store, student_id)
    questions = await question_log.recent_questions(store, student_id, limit=1000)
    turns = [entry.assessed_at_turn for entry in entries.values()]
    turns += [turn for q in questions for turn in (q.asked_at_turn, q.answered_at_turn) if turn is not None]
    return max(turns, default=0)

async def next_turn(store: BaseStore, student_id: str) -> int:
    """Count one more message from this student and return its turn number, starting at 1."""
    async with _locks.setdefault(student_id, asyncio.Lock()):
        item = await store.aget(namespace(student_id), TURN_KEY)
        # First message since the counter was added: start after any turn already saved
        count = item.value["count"] if item else await _highest_saved_turn(store, student_id)
        await store.aput(namespace(student_id), TURN_KEY, {"count": count + 1})
        return count + 1

def current_turn(context, conversation) -> int:
    """This turn's number: the counter that chat_turn() put in the context.

    Runs without one (tests, evaluate_assessment.py) fall back to counting the student's messages
    in this conversation. conversation holds Message objects, or dicts after a checkpoint reload.
    """
    turn = getattr(context, "student_turn", None)
    if turn is not None:
        return turn
    return sum(1 for m in conversation if (m.get("role") if isinstance(m, dict) else getattr(m, "role", None)) == "student")
