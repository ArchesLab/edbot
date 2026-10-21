from datetime import datetime, timezone
from langgraph.store.base import BaseStore
import uuid 

from edbot.interface_def import AnswerJudgment, CGAOutput, QuestionLogEntry
from edbot.student_model import normalize_concept

def namespace(student_id: str) -> tuple[str, str, str]:
    """Where one student's logged questions live in the store. Keys inside it are question IDs."""
    return ("students", student_id, "question_log")

async def save_question(store: BaseStore, student_id: str, output: CGAOutput, turn: int) -> QuestionLogEntry:
    """Log a question the CGA generated. Returns the new entry, with its generated question_id."""
    # format and rubric are only set in generate_question mode
    if output.mode != "generate_question" or output.format is None or output.rubric is None:
        raise ValueError(f"Only generate_question output with a format and rubric can be logged, got mode={output.mode}")
    
    entry = QuestionLogEntry(
        question_id = f"q-{uuid.uuid4().hex[:8]}",
        concept = normalize_concept(output.concept),
        tier = output.target_tier,
        format = output.format,
        question_text = output.content,
        rubric=output.rubric,
        concept_tags=output.concept_tags or [],
        asked_at=datetime.now(timezone.utc),
        asked_at_turn=turn,
    )
    await store.aput(namespace(student_id), entry.question_id, entry.model_dump(mode="json"))
    return entry

async def load_question(store: BaseStore, student_id: str, question_id: str) -> QuestionLogEntry | None:
    """One logged question, or None if this student has no question with that ID."""
    item = await store.aget(namespace(student_id), question_id)
    return QuestionLogEntry.model_validate(item.value) if item else None

async def record_answer(store: BaseStore, student_id: str, question_id: str, student_answer: str, judgment: AnswerJudgment, turn: int) -> QuestionLogEntry | None:
    """Attach the student's answer and the UCA's verdict to a logged question.

    Returns the updated entry, or None if this student has no question with that ID.
    """
    entry = await load_question(store, student_id, question_id)
    if entry is None:
        return None
    # Entries are frozen, so build an updated copy instead of changing it in place
    updated = entry.model_copy(update={
        "student_answer": student_answer,
        "verdict": judgment.verdict,
        "judgment_note": judgment.note,
        "answered_at_turn": turn,
    })
    await store.aput(namespace(student_id), question_id, updated.model_dump(mode="json"))
    return updated

async def recent_questions(store: BaseStore, student_id: str, concept: str | None = None, limit: int = 5) -> list[QuestionLogEntry]:
    """This student's most recent questions, newest first, optionally only for one concept."""
    # filter matches fields of the stored value; None means every concept
    search_filter = {"concept": normalize_concept(concept)} if concept else None
    # asearch's order isn't guaranteed and it returns 10 items by default, so fetch them all and sort here
    items = await store.asearch(namespace(student_id), filter=search_filter, limit=1000)
    entries = [QuestionLogEntry.model_validate(item.value) for item in items]
    entries.sort(key=lambda entry: entry.asked_at, reverse=True)
    return entries[:limit]

