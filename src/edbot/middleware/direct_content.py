"""Deliver a complete CGA-only reply without a redundant parent model generation."""
import json
from dataclasses import replace

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_ollama import ChatOllama
from langgraph.types import Command
from pydantic import TypeAdapter, ValidationError

from edbot import model_config
from edbot.interface_def import CGAInput, CGAOutput


_CGA_INPUT = TypeAdapter(CGAInput)
_CGA_NAME = "content-generating-agent"


def _direct_content(request) -> AIMessage | None:
    """Fail closed to ordinary synthesis unless this turn has one complete CGA task.

    Read actual graph messages, never student-supplied JSON or a summarization's
    approximation of the turn. Assessment and multi-task turns still need the
    parent's synthesis. The original tool result remains in the checkpoint so
    its private rubric is available for a later answer submission.

    DeepAgents does not expose the child's finish reason in its task result.
    Schema validation here cannot certify generation completeness or pedagogy;
    those remain properties to check in child execution and quality evaluation.
    """
    if not model_config.DIRECT_CONTENT_DELIVERY:
        return None
    messages = request.state.get("messages", [])
    start = next((i for i in range(len(messages) - 1, -1, -1)
                  if isinstance(messages[i], HumanMessage)), None)
    if start is None:
        return None
    current = messages[start + 1:]
    if len(current) < 2 or not isinstance(current[-1], ToolMessage) or not isinstance(current[-2], AIMessage):
        return None

    parent, result = current[-2:]
    if len(parent.tool_calls) != 1 or parent.invalid_tool_calls:
        return None
    call = parent.tool_calls[0]
    if (call["name"] != "task" or call["args"].get("subagent_type") != _CGA_NAME
            or not call.get("id") or result.tool_call_id != call["id"] or result.status != "success"
            or result.name not in (None, "task")):
        return None
    # Earlier tasks may contain assessment feedback or content to combine. Even
    # a failed task is left to the parent, which owns correction and recovery.
    task_calls = [tool_call for message in current if isinstance(message, AIMessage)
                  for tool_call in message.tool_calls if tool_call["name"] == "task"]
    if len(task_calls) != 1:
        return None
    if any(isinstance(message, AIMessage) and (
        message.invalid_tool_calls or message.response_metadata.get("finish_reason") == "length"
    ) for message in current):
        return None
    if any(isinstance(message, ToolMessage) and message.status != "success" for message in current):
        return None

    try:
        raw_input = call["args"].get("description")
        if isinstance(raw_input, str):
            raw_input = json.loads(raw_input)
        if not isinstance(raw_input, dict) or set(call["args"]) != {"subagent_type", "description"}:
            return None
        cga_input = _CGA_INPUT.validate_python(raw_input)
        if set(raw_input) - set(type(cga_input).model_fields):
            return None
        if not isinstance(result.content, str):
            return None
        raw_output = json.loads(result.content)
        if not isinstance(raw_output, dict) or set(raw_output) - set(CGAOutput.model_fields):
            return None
        output = CGAOutput.model_validate(raw_output)
    except (ValidationError, ValueError, TypeError):
        return None

    if ((output.mode, output.concept, output.target_tier)
            != (cga_input.mode, cga_input.concept, cga_input.target_tier)):
        return None
    if (not output.content.strip() or output.coverage_gap is not None or not output.sources
            or any(not source.strip() for source in output.sources)):
        return None
    if output.mode == "generate_question":
        if (output.format is None or not output.rubric or not output.rubric.strip()
                or not output.concept_tags or output.concept not in output.concept_tags
                or any(not tag.strip() for tag in output.concept_tags)):
            return None
        if cga_input.format_constraint is not None and output.format != cga_input.format_constraint:
            return None
    elif any(value is not None for value in (output.format, output.rubric, output.concept_tags)):
        return None

    # Return a normal assistant message from the model node: LangGraph persists
    # and streams it, and the public history uses the same exact content.
    return AIMessage(content=output.content)


class DirectContentMiddleware(AgentMiddleware):
    """Parent-only shortcut; it does not alter routing, tools, or child output."""

    def wrap_model_call(self, request, handler):
        answer = _direct_content(request)
        return answer if answer is not None else handler(request)

    async def awrap_model_call(self, request, handler):
        answer = _direct_content(request)
        return answer if answer is not None else await handler(request)


class CompleteContentMiddleware(AgentMiddleware):
    """Require completed tool work and a complete CGA generation before delivery.

    DeepAgents serializes the structured result without the model's finish
    metadata. A valid JSON object alone therefore cannot authorize delivery.
    """

    def __init__(self, output_tool="CGAOutput", *, reject_tool_errors=False):
        self.output_tool = output_tool
        self.reject_tool_errors = reject_tool_errors

    def _model_request(self, request):
        # Installed Ollama clients have no parallel_tool_calls parameter. The
        # result guards below still handle mixed or duplicate output calls.
        if model_config.SERIAL_CHILD_TOOL_CALLS and not isinstance(request.model, ChatOllama):
            return request.override(model_settings={**request.model_settings, "parallel_tool_calls": False})
        return request

    def _defer_pending_tools(self, response: ModelResponse) -> ModelResponse:
        latest = next((message for message in reversed(response.result)
                       if isinstance(message, AIMessage)), None)
        if latest is None:
            return response
        outputs = [call for call in latest.tool_calls if call["name"] == self.output_tool]
        pending = [call for call in latest.tool_calls if call["name"] != self.output_tool]
        if not outputs or not pending:
            return response

        # The handler has already applied ToolStrategy: it returns an AIMessage,
        # a synthetic CGAOutput ToolMessage, and structured_response. Remove all
        # three representations of the premature result before graph routing.
        # Keeping the real tools forces the child to read their results and make
        # a new generation. Leave original response objects intact for tracing.
        deferred_ids = [call["id"] for call in outputs]
        rewritten = AIMessage(
            content="", id=latest.id, name=latest.name, tool_calls=pending,
            invalid_tool_calls=latest.invalid_tool_calls,
            additional_kwargs={key: value for key, value in latest.additional_kwargs.items()
                               if key not in {"tool_calls", "function_call"}},
            response_metadata={**latest.response_metadata,
                               "edbot_deferred_output_tool_ids": deferred_ids,
                               "edbot_deferred_output_reason": "awaiting_tool_results"},
            usage_metadata=latest.usage_metadata,
        )
        messages = [rewritten if message is latest else message for message in response.result
                    if not (isinstance(message, ToolMessage) and message.tool_call_id in deferred_ids)]
        return replace(response, result=messages, structured_response=None)

    def wrap_model_call(self, request, handler):
        return self._defer_pending_tools(handler(self._model_request(request)))

    async def awrap_model_call(self, request, handler):
        return self._defer_pending_tools(await handler(self._model_request(request)))

    def _check_tool_result(self, result):
        messages = result.update.get("messages", []) if isinstance(result, Command) and isinstance(result.update, dict) else [result]
        if self.reject_tool_errors and any(isinstance(message, ToolMessage) and message.status == "error"
                                           for message in messages):
            raise ValueError("Assessment tool failed; no complete assessment is available")
        return result

    def wrap_tool_call(self, request, handler):
        return self._check_tool_result(handler(request))

    async def awrap_tool_call(self, request, handler):
        return self._check_tool_result(await handler(request))

    def after_model(self, state, runtime):
        latest = next((message for message in reversed(state["messages"])
                       if isinstance(message, AIMessage)), None)
        if latest is not None and latest.response_metadata.get("finish_reason") == "length":
            raise ValueError("Content generation reached its output limit; no complete reply is available")
        if latest is not None and latest.invalid_tool_calls:
            # Invalid calls are absent from tool_calls, so a valid CGAOutput can
            # otherwise finish while an intended evidence lookup never ran.
            raise ValueError("Content generation returned an invalid tool call; no complete reply is available")
        if self.reject_tool_errors and any(isinstance(message, ToolMessage) and message.status == "error"
                                           for message in state["messages"]):
            raise ValueError("Assessment tool failed; no complete assessment is available")

    async def aafter_model(self, state, runtime):
        return self.after_model(state, runtime)
