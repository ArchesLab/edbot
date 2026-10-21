"""Require the content specialist after assessment, without choosing study policy.

This enforces a role boundary, not semantic teaching quality. In particular, an
already-misrouted stop still reaches CGA, whose existing contract requires closure.
Post-CGA parent synthesis remains available. Rejected terminal output raises
inside the model wrapper, before graph state commits it; there is no hidden
generation retry that could flush an earlier streamed answer into public output.
"""
from copy import deepcopy
import json

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ExtendedModelResponse, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_ollama import ChatOllama
from pydantic import TypeAdapter, ValidationError

from edbot import model_config
from edbot.interface_def import CGAInput, CGAOutput, UCAInput, UCAOutput
from edbot.student_model import normalize_concept

_UCA, _CGA = "understanding-checking-agent", "content-generating-agent"
_INPUTS = {_UCA: TypeAdapter(UCAInput), _CGA: TypeAdapter(CGAInput)}


def _input(call):
    if call.get("name") != "task":
        return None
    args = call.get("args", {})
    adapter = _INPUTS.get(args.get("subagent_type"))
    if adapter is None:
        return None
    raw = args.get("description")
    try:
        return adapter.validate_json(raw) if isinstance(raw, str) else adapter.validate_python(raw)
    except (ValidationError, ValueError, TypeError):
        return None


def _pending(messages):
    """Match real task/result pairs; a parallel CGA cannot observe its sibling UCA."""
    start = next((index for index in range(len(messages) - 1, -1, -1)
                  if isinstance(messages[index], HumanMessage)), None)
    if start is None:
        return None
    calls, pending = {}, {}
    for index in range(start + 1, len(messages)):
        message = messages[index]
        if isinstance(message, AIMessage):
            # A completed task remains authoritative even if its parent also
            # emitted an invalid sibling call or reported a length limit.
            for call in message.tool_calls:
                if call.get("name") != "task" or not call.get("id"):
                    continue
                task = _input(call)
                calls[call["id"]] = (index, call["args"].get("subagent_type"), task)
                if call["args"].get("subagent_type") == _CGA:
                    # Successful matching results clear their pending entry
                    # below, so only failed/unresolved attempts retain this count.
                    for concept, item in pending.items():
                        if task is None or normalize_concept(task.concept) == concept:
                            item["attempts"] += 1
        elif (isinstance(message, ToolMessage) and message.status == "success"
              and message.name in (None, "task") and isinstance(message.content, str)):
            matched = calls.pop(message.tool_call_id, None)
            if matched is None:
                continue
            origin, kind, task = matched
            if task is None or kind not in _INPUTS:
                continue
            try:
                output = (_UCA_OUTPUT if kind == _UCA else _CGA_OUTPUT).validate_json(message.content)
            except (ValidationError, ValueError, TypeError):
                continue
            concept = normalize_concept(task.concept)
            if not concept or normalize_concept(output.concept) != concept:
                continue
            if kind == _UCA:
                pending[concept] = {"after": index, "attempts": 0}
            elif (concept in pending and origin > pending[concept]["after"] and output.content.strip()
                  and (output.mode, output.target_tier) == (task.mode, task.target_tier)):
                del pending[concept]
    return min(pending.items(), key=lambda item: item[1]["after"]) if pending else None


_UCA_OUTPUT, _CGA_OUTPUT = TypeAdapter(UCAOutput), TypeAdapter(CGAOutput)


def _constrain(request):
    if not model_config.REQUIRE_CONTENT_AFTER_ASSESSMENT:
        return request, None
    pending = _pending(request.state.get("messages", []))
    if pending is None:
        return request, None
    concept, status = pending
    if status["attempts"] >= 2:
        raise ValueError("Content generation failed after two attempts following assessment")
    for tool in request.tools:
        descriptor = deepcopy(convert_to_openai_tool(tool))
        if descriptor.get("function", {}).get("name") == "task":
            break
    else:
        raise ValueError("Assessment requires the content specialist, but task is unavailable")
    function = descriptor["function"]
    parameters = function["parameters"]
    if "anyOf" in parameters:
        branches = [branch for branch in parameters["anyOf"]
                    if branch.get("properties", {}).get("subagent_type", {}).get("const") == _CGA]
        if len(branches) != 1:
            raise ValueError("Assessment requires exactly one typed CGA branch")
        function["parameters"] = branches[0]
    else:
        # Legacy/non-reduced callers still advertise a string description.
        parameters["properties"]["subagent_type"]["enum"] = [_CGA]
    function["description"] = (
        f"Generate student-facing content for assessed concept {json.dumps(concept)}. "
        "Use the content-generating-agent and a JSON description matching CGAInput. "
        "Choose its mode and target tier under the existing tutoring rules. Honor the "
        "student's conversation and assistance contract, including requests to stop."
    )
    settings = request.model_settings
    # ChatOllama ignores tool_choice and its client rejects parallel_tool_calls.
    # Keep the named request and enforce the same causal boundary in _check.
    if not isinstance(request.model, ChatOllama):
        settings = {**settings, "parallel_tool_calls": False}
    return request.override(tools=[descriptor], tool_choice={"type": "function", "function": {"name": "task"}},
                            model_settings=settings), concept


def _check(response, concept):
    if concept is None:
        return response
    inner = response.model_response if isinstance(response, ExtendedModelResponse) else response
    messages = inner.result if isinstance(inner, ModelResponse) else [inner]
    if len(messages) != 1 or not isinstance(messages[0], AIMessage):
        raise ValueError("Assessment must be followed by one content-specialist task")
    message = messages[0]
    if (message.invalid_tool_calls or message.response_metadata.get("finish_reason") == "length"
            or len(message.tool_calls) != 1):
        raise ValueError("Assessment must be followed by one complete content-specialist task")
    call = message.tool_calls[0]
    if (call["name"] != "task" or not call.get("id") or call["args"].get("subagent_type") != _CGA
            or set(call["args"]) != {"subagent_type", "description"}):
        raise ValueError("Assessment requires the content specialist before a terminal reply")
    task = _input(call)
    if task is not None and normalize_concept(task.concept) != concept:
        raise ValueError("Content task must address the assessed concept")
    # Malformed CGAInput still reaches the existing tool validator. Its error
    # becomes an observable failed attempt, allowing at most one corrected call.
    return response


class RequireContentAfterAssessment(AgentMiddleware):
    def wrap_model_call(self, request, handler):
        checked, concept = _constrain(request)
        return _check(handler(checked), concept)

    async def awrap_model_call(self, request, handler):
        checked, concept = _constrain(request)
        return _check(await handler(checked), concept)
