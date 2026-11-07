"""Carry bounded, verbatim retrieval results to course specialists.

The parent captures its own search results each turn. With PREFETCH_COURSE_EVIDENCE, code also
searches before every subagent task and keeps a concept's passages across turns, so the UCA and
CGA start from the same evidence. With LIMIT_CHILD_SEARCHES, a child given evidence may search
once more.
"""
import asyncio
from dataclasses import replace
import json
from typing import Annotated, NotRequired

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.agents.middleware.types import PrivateStateAttr
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from edbot import model_config, question_log, student_model
from edbot.tools.search_markdown_sources import _format_chunks


MAX_EVIDENCE_CHARS = 12000
MAX_EVIDENCE_RESULTS = 2
PREFETCH_CHUNKS = 6 # more than the tool's 4, since code's query is blunter than a model's
MAX_SUPPLIED_CHARS = 16000 # everything a child receives: this turn's parent results plus the concept's pool
MAX_CHILD_SEARCHES = 1 # extra searches a child may make once evidence was supplied
_CHILDREN = {"understanding-checking-agent", "content-generating-agent"}
_SEARCH = "search_markdown_sources"


class CourseEvidenceState(AgentState):
    course_evidence: NotRequired[list[dict[str, str]]]


def _latest(old, new):
    """Last writer wins, so UCA and CGA tasks in one tool batch can both update the pool."""
    return new


class CarriedEvidenceState(CourseEvidenceState):
    # Parent only: {"concept", "turn_id", "evidence"}, kept until the concept changes.
    # Private, so DeepAgents doesn't copy it into children
    carried_evidence: NotRequired[Annotated[dict, PrivateStateAttr, _latest]]


def current_evidence(messages):
    """Keep complete results only; never truncate a source passage mid-claim."""
    start = next((i for i in range(len(messages) - 1, -1, -1)
                  if isinstance(messages[i], HumanMessage)), None)
    if start is None:
        return []
    calls, results = {}, []
    for message in messages[start + 1:]:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                if call["name"] == "search_markdown_sources" and call.get("id"):
                    calls[call["id"]] = call["args"]
        elif (isinstance(message, ToolMessage) and message.name == "search_markdown_sources"
              and message.status == "success" and isinstance(message.content, str) and message.content.strip()):
            args = calls.get(message.tool_call_id)
            if args and isinstance(args.get("query"), str):
                results.append({"query": args["query"], "path_prefix": args.get("path_prefix") or "",
                                "content": message.content})

    selected, seen, used = [], set(), 0
    for result in reversed(results):
        size = sum(len(value) for value in result.values())
        if result["content"] in seen or used + size > MAX_EVIDENCE_CHARS:
            continue
        selected.append(result)
        seen.add(result["content"])
        used += size
        if len(selected) == MAX_EVIDENCE_RESULTS:
            break
    return list(reversed(selected))


class CaptureCourseEvidence(AgentMiddleware):
    """Parent only: refresh from real tool messages, clearing it on every new turn."""
    state_schema = CourseEvidenceState

    def before_model(self, state, runtime):
        return {"course_evidence": current_evidence(state["messages"])
                if model_config.REUSE_COURSE_EVIDENCE else []}


def _within_budget(rows, limit=MAX_SUPPLIED_CHARS):
    """Whole rows, newest first until the budget is spent, returned oldest first; duplicates dropped."""
    selected, seen, used = [], set(), 0
    for row in reversed(rows):
        size = sum(len(value) for value in row.values())
        if row["content"] in seen or used + size > limit:
            continue
        selected.append(row)
        seen.add(row["content"])
        used += size
    return list(reversed(selected))


def _search(load_store, query, known):
    """Code's own search; drops chunks the evidence already holds."""
    docs = load_store().similarity_search(query, k=PREFETCH_CHUNKS)
    docs = [doc for doc in docs if not any(doc.page_content in text for text in known)]
    return {"query": query, "path_prefix": "", "content": _format_chunks(docs)} if docs else None


class PrefetchCourseEvidence(AgentMiddleware):
    """Parent task boundary: search once per student turn and concept, before the child starts.

    The query is the concept plus the student's latest message, or for a graded answer the logged
    question and the student's answer. Results join the concept's pool from earlier turns, which
    resets when the concept changes. Listed after validate_subagent_input, so descriptions are valid.
    """
    state_schema = CarriedEvidenceState

    def __init__(self, load_store):
        self._load_store = load_store # edbot_agent's, so its test patches cover this search too

    def wrap_tool_call(self, request, handler):
        # The question log and the embedding search are only wired for astream() (see service.chat_turn)
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        if not (model_config.PREFETCH_COURSE_EVIDENCE and model_config.REUSE_COURSE_EVIDENCE
                and call["name"] == "task" and call["args"].get("subagent_type") in _CHILDREN):
            return await handler(request)
        raw = call["args"]["description"]
        task = raw if isinstance(raw, dict) else json.loads(raw)
        concept = student_model.normalize_concept(task.get("concept") or "")
        latest = next((m for m in reversed(request.state.get("messages", [])) if isinstance(m, HumanMessage)), None)
        if not concept or latest is None:
            return await handler(request)

        carried = request.state.get("carried_evidence") or {}
        pool = carried.get("evidence", []) if carried.get("concept") == concept else []
        turn_rows = request.state.get("course_evidence") or []
        if carried.get("concept") != concept or carried.get("turn_id") != latest.id:
            query = await self._query(request, task, concept, latest)
            known = [row["content"] for row in [*pool, *turn_rows]]
            if row := await asyncio.to_thread(_search, self._load_store, query, known):
                pool = [*pool, row]
        # This turn's parent results join the pool too, so a later turn can reuse them
        pool = _within_budget([*pool, *turn_rows])

        state = {**request.state, "course_evidence": pool}
        result = await handler(request.override(state=state, runtime=replace(request.runtime, state=state)))
        if isinstance(result, Command) and isinstance(result.update, dict):
            carried = {"concept": concept, "turn_id": latest.id, "evidence": pool}
            result = replace(result, update={**result.update, "carried_evidence": carried})
        return result

    async def _query(self, request, task, concept, latest):
        if task.get("question_id") and request.runtime.store is not None:
            entry = await question_log.load_question(request.runtime.store, request.runtime.context.student_id,
                                                     task["question_id"])
            if entry is not None:
                return f"{concept}: {entry.question_text}\n\nStudent answer: {task.get('student_answer') or ''}"
        return f"{concept}: {latest.text}"


class LimitChildSearches(AgentMiddleware):
    """Child side: once course evidence was supplied, answer extra searches with a refusal.

    Refusing the call, rather than removing the tool, keeps the child's prompt prefix (and its
    cache) unchanged. Searches made without supplied evidence are not limited.
    """

    def _refusal(self, request):
        if not (model_config.LIMIT_CHILD_SEARCHES and request.tool_call["name"] == _SEARCH
                and request.state.get("course_evidence")):
            return None
        done = sum(isinstance(m, ToolMessage) and m.name == _SEARCH for m in request.state.get("messages", []))
        if done < MAX_CHILD_SEARCHES:
            return None
        return ToolMessage(
            content="Search limit reached: the supplied course_evidence and your earlier search are all the "
                    "retrieval for this task. Work from them, and say in your output what they don't cover.",
            # Not status="error": the UCA's completion guard treats any tool error as a failed assessment
            tool_call_id=request.tool_call["id"], name=_SEARCH)

    def wrap_tool_call(self, request, handler):
        return self._refusal(request) or handler(request)

    async def awrap_tool_call(self, request, handler):
        return self._refusal(request) or await handler(request)
