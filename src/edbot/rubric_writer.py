"""Write a practice question's rubric in the background, off the student's critical path.

The CGA returns only the question, so the student sees it without waiting for the answer key. This
module writes the rubric with one more model call while the student reads, and saves it to the
question log. The UCA only needs the rubric once the student answers: ensure_rubric() waits for a
pending write, or writes the rubric then if none is running (after a restart, or a failed write).
"""
import asyncio
import json
import logging
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from edbot import question_log
from edbot.chat_model import create_chat_model
from edbot.interface_def import QuestionLogEntry
from edbot.tools.markdown_embedding import load_sebook_store
from edbot.tools.search_markdown_sources import _format_chunks

logger = logging.getLogger(__name__)

PROMPT = (Path(__file__).parent / "prompts" / "rubric_prompt.md").read_text()
EVIDENCE_CHUNKS = 4
WAIT_TIMEOUT_S = 180 # how long an answer turn waits for a background write before writing its own

# Running writes, keyed by (student_id, question_id). Holding the task here also keeps it from being
# garbage-collected before it finishes
_pending: dict[tuple[str, str], asyncio.Task] = {}
_model = None


def _chat_model():
    global _model
    if _model is None:
        _model = create_chat_model()
    return _model


def _evidence(entry: QuestionLogEntry) -> str:
    """Course passages for the question, found by code instead of a model tool call."""
    docs = load_sebook_store().similarity_search(f"{entry.concept}: {entry.question_text}", k=EVIDENCE_CHUNKS)
    return _format_chunks(docs) if docs else "(no matching course material)"


async def write_rubric(entry: QuestionLogEntry) -> str:
    """One model call that writes the rubric for a logged question."""
    evidence = await asyncio.to_thread(_evidence, entry) # the embedding search blocks
    task = {"concept": entry.concept, "target_tier": entry.tier, "format": entry.format,
            "question_text": entry.question_text}
    reply = await _chat_model().ainvoke([
        SystemMessage(content=PROMPT),
        HumanMessage(content=f"{json.dumps(task, ensure_ascii=False)}\n\ncourse_evidence:\n{evidence}"),
    ])
    rubric = reply.content.strip() if isinstance(reply.content, str) else ""
    if reply.response_metadata.get("finish_reason") == "length" or not rubric:
        raise ValueError(f"No complete rubric for question {entry.question_id}")
    return rubric


async def _write_and_save(store: BaseStore, student_id: str, entry: QuestionLogEntry) -> None:
    rubric = await write_rubric(entry)
    await question_log.save_rubric(store, student_id, entry.question_id, rubric)


def start(store: BaseStore, student_id: str, entry: QuestionLogEntry) -> None:
    """Begin writing a just-logged question's rubric in the background."""
    key = (student_id, entry.question_id)

    def finished(task: asyncio.Task) -> None:
        _pending.pop(key, None)
        if not task.cancelled() and task.exception() is not None:
            logger.warning("Background rubric for %s failed: %s", entry.question_id, task.exception())

    task = asyncio.create_task(_write_and_save(store, student_id, entry))
    _pending[key] = task
    task.add_done_callback(finished)


async def ensure_rubric(store: BaseStore, student_id: str, entry: QuestionLogEntry) -> QuestionLogEntry:
    """The entry with its rubric, waiting for or writing it if needed. Raises if none can be written."""
    if entry.rubric:
        return entry
    task = _pending.get((student_id, entry.question_id))
    if task is not None:
        try:
            # shield: a timeout here shouldn't cancel the write itself
            await asyncio.wait_for(asyncio.shield(task), WAIT_TIMEOUT_S)
        except Exception as e:
            logger.warning("Waiting for the rubric of %s failed: %s", entry.question_id, e)
    current = await question_log.load_question(store, student_id, entry.question_id)
    if current is not None and current.rubric:
        return current
    # No background write ran (e.g. after a restart) or it failed: write the rubric now
    await _write_and_save(store, student_id, entry)
    current = await question_log.load_question(store, student_id, entry.question_id)
    if current is None or not current.rubric:
        raise ValueError(f"No rubric saved for question {entry.question_id}")
    return current
