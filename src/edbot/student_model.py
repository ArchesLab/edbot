# Reads and writes the student model in the LangGraph store: one StudentModelEntry per student
# per concept. The agent tools (tools/student_model.py) and service.py both go through these.
from datetime import datetime, timezone
from langgraph.store.base import BaseStore

from edbot.interface_def import BloomTier, Confidence, StudentModelEntry

def namespace(student_id: str) -> tuple[str, str, str]:
    """Where one student's entries live in the store. Keys inside it are concept IDs."""
    return ("students", student_id, "student_model")

def normalize_concept(concept: str) -> str:
    """So "Recursion" and "recursion " are the same key. Doesn't merge different IDs for one concept."""
    return concept.strip().lower()

async def load_entry(store: BaseStore, student_id: str, concept: str) -> StudentModelEntry | None:
    """The student's entry for this concept, or None if it was never assessed."""
    item = await store.aget(namespace(student_id), normalize_concept(concept))
    return StudentModelEntry.model_validate(item.value) if item else None

async def save_entry(
    store: BaseStore,
    student_id: str,
    concept: str,
    tier: BloomTier,
    confidence: Confidence,
    rationale: str,
    turn: int,
) -> StudentModelEntry:
    """Save a new assessment, replacing the previous one. Returns the saved entry."""
    key = normalize_concept(concept)
    previous = await load_entry(store, student_id, key)
    entry = StudentModelEntry(
        concept=key,
        tier=tier,
        confidence=confidence,
        rationale=rationale,
        assessed_at=datetime.now(timezone.utc),
        assessed_at_turn=turn,
        assessment_count=previous.assessment_count + 1 if previous else 1,
    )
    # The store only holds plain dicts, so convert (mode="json" turns the datetime into a string)
    await store.aput(namespace(student_id), key, entry.model_dump(mode="json"))
    return entry

async def load_all(store: BaseStore, student_id: str) -> dict[str, StudentModelEntry]:
    """Every assessed concept for one student, keyed by concept ID."""
    # asearch returns 10 items by default; a student won't have anywhere near 1000 concepts
    items = await store.asearch(namespace(student_id), limit=1000)
    return {item.key: StudentModelEntry.model_validate(item.value) for item in items}
