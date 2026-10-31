"""Batch independent parent reads; assessment remains a separate fresh task."""
import asyncio
import json

from langchain.tools import tool, ToolRuntime

from edbot.tools.student_model import fetch_student_data
from edbot.tools.question_log import fetch_recent_questions


@tool(parse_docstring=True)
async def prepare_tutoring_context(concept: str, query: str, runtime: ToolRuntime) -> str:
    """Read course passages, the current student's prior, and recent questions together.

    Prefer this for a course-content turn that needs scope and routing context.
    It does not assess the student, write state, or return question rubrics.

    Args:
        concept: Candidate canonical concept ID for this turn.
        query: Focused course search query for the student's current request.

    Returns:
        JSON with student_model, recent_questions, and verbatim course_evidence.
    """
    from edbot import tools
    prior, questions, evidence = await asyncio.gather(
        fetch_student_data.coroutine(concept=concept, runtime=runtime),
        fetch_recent_questions.coroutine(concept=concept, runtime=runtime),
        tools.search_markdown_sources.ainvoke({"query": query}, config=runtime.config),
    )
    return json.dumps({"student_model": prior, "recent_questions": questions,
                       "course_evidence": {"query": query, "path_prefix": "", "content": evidence}},
                      ensure_ascii=False)
