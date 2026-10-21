# Read-only agent tool for the question log. QuestionLogMiddleware does all the writing, from the
# orchestrator's subagent calls. Rubrics are left out: the middleware hands them to the UCA itself.
from langchain.tools import tool, ToolRuntime

from edbot import question_log
from edbot.tools.student_model import _student_id

@tool(parse_docstring=True)
async def fetch_recent_questions(runtime: ToolRuntime, concept: str | None = None) -> str:
    """List the most recent practice questions asked to the student, newest first.

    Args:
        concept: Canonical concept ID to filter by, e.g. "recursion". Leave out for every concept.

    Returns:
        One JSON object per line: question_id, concept, tier, format, question_text, and the
        verdict (null if the student hasn't answered yet), or a note that there are none.
    """
    entries = await question_log.recent_questions(runtime.store, _student_id(runtime), concept)
    if not entries:
        return "No questions asked yet."
    fields = {"question_id", "concept", "tier", "format", "question_text", "verdict"}
    return "\n".join(entry.model_dump_json(include=fields) for entry in entries)
