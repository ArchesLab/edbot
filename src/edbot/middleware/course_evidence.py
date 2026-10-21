"""Carry bounded, verbatim retrieval results from this turn to course specialists."""
from typing import NotRequired

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from edbot import model_config


MAX_EVIDENCE_CHARS = 12000
MAX_EVIDENCE_RESULTS = 2


class CourseEvidenceState(AgentState):
    course_evidence: NotRequired[list[dict[str, str]]]


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
