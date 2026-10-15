# Agent tools for the student model. The student ID always comes from runtime.context (set by
# chat_turn()), never from the model, so an agent can only touch the current student's entries.
# Only the UCA gets update_student_model (see subagents.yaml): it's the student model's single writer.
from langchain.tools import tool, ToolRuntime

from edbot.interface_def import BloomTier, Confidence
from edbot import student_model

def _student_id(runtime: ToolRuntime) -> str:
    """The current turn's student. Fails loudly rather than reading or writing a shared namespace."""
    student_id = getattr(runtime.context, "student_id", None)
    if not student_id:
        raise ValueError("No student_id in runtime context: run the agent with context=EdbotContext(...)")
    return student_id

def _student_turn(runtime: ToolRuntime) -> int:
    """How many messages the student has sent so far, from the conversation passed down in state."""
    conversation = runtime.state.get("conversation", [])
    return sum(1 for message in conversation if getattr(message, "role", None) == "student")

@tool(parse_docstring=True)
async def fetch_student_data(concept: str, runtime: ToolRuntime) -> str:
    """Look up the student's current Bloom's Taxonomy tier for a concept.

    Args:
        concept: Canonical concept ID, e.g. "recursion".

    Returns:
        The saved assessment (tier, confidence, rationale, when it was assessed), or a note
        that the concept has never been assessed for this student.
    """
    entry = await student_model.load_entry(runtime.store, _student_id(runtime), concept)
    if entry is None:
        return f"No prior assessment for '{student_model.normalize_concept(concept)}'."
    return entry.model_dump_json()

@tool(parse_docstring=True)
async def update_student_model(
    concept: str,
    tier: BloomTier,
    confidence: Confidence,
    rationale: str,
    runtime: ToolRuntime,
) -> str:
    """Save your assessment of the student for a concept, replacing the previous one.

    Args:
        concept: Canonical concept ID you assessed, e.g. "recursion".
        tier: Your Bloom's Taxonomy tier estimate.
        confidence: How confident you are in the estimate.
        rationale: 1-3 sentences tying the estimate to what the student said.

    Returns:
        Confirmation of what was saved.
    """
    entry = await student_model.save_entry(
        runtime.store, _student_id(runtime), concept, tier, confidence, rationale, _student_turn(runtime),
    )
    return f"Saved: {entry.concept} = {entry.tier} ({entry.confidence} confidence), assessment #{entry.assessment_count}."
