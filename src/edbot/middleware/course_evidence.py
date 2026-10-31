"""Carry bounded, verbatim retrieval results from this turn to course specialists."""
import json
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
                if call["name"] in {"search_markdown_sources", "prepare_tutoring_context"} and call.get("id"):
                    calls[call["id"]] = call
        elif (isinstance(message, ToolMessage) and message.name in {"search_markdown_sources", "prepare_tutoring_context"}
              and message.status == "success" and isinstance(message.content, str) and message.content.strip()):
            call = calls.get(message.tool_call_id)
            if not call or call["name"] != message.name:
                continue
            args = call["args"]
            if message.name == "prepare_tutoring_context":
                try:
                    result = json.loads(message.content)["course_evidence"]
                except (ValueError, KeyError, TypeError):
                    continue
                if (isinstance(result, dict) and set(result) == {"query", "path_prefix", "content"}
                        and all(isinstance(value, str) for value in result.values())
                        and result["query"] == args.get("query") and result["content"].strip()):
                    # Student priors and recent-question records remain private
                    # to the parent; only the actual course lookup is inherited.
                    results.append(result)
            elif isinstance(args.get("query"), str):
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
