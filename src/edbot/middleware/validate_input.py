from copy import deepcopy
import json
from typing import Literal

from pydantic import BaseModel, TypeAdapter, ValidationError
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_ollama import ChatOllama

from edbot import model_config
from edbot.interface_def import CGAInput, UCAInput

# Filled by load_subagents() in edbot_agent.py from each subagent's input_schema in subagents.yaml
SUBAGENT_INPUT_SCHEMAS: dict[str, TypeAdapter] = {}


class _AssessmentTask(BaseModel):
    subagent_type: Literal["understanding-checking-agent"]
    description: UCAInput


class _ContentTask(BaseModel):
    subagent_type: Literal["content-generating-agent"]
    description: CGAInput


# QuestionLogMiddleware fills prior_questions from the log, and only when it is empty, and answer_feedback
# from this turn's graded UCA result. Hide both from the parent so it never spends a generation copying
# rubrics or verdicts into the CGA input, and can't supply a verdict the UCA didn't give.
_FILLED_BY_CODE = {"prior_questions", "answer_feedback"}


def _without_filled_fields(schema):
    """The schema with every property named in _FILLED_BY_CODE removed, at any depth."""
    if isinstance(schema, list):
        return [_without_filled_fields(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    result = {key: _without_filled_fields(value) for key, value in schema.items()}
    if isinstance(result.get("properties"), dict):
        result["properties"] = {name: value for name, value in result["properties"].items() if name not in _FILLED_BY_CODE}
        if "required" in result:
            result["required"] = [name for name in result["required"] if name not in _FILLED_BY_CODE]
    return result


# Correlate the outer role and input; an independent description union permits
# CGA-shaped UCA calls. Public conversion inlines references for serving grammars.
_TASK_PARAMETERS = {"anyOf": [_without_filled_fields(convert_to_openai_tool(schema)["function"]["parameters"])
                              for schema in (_AssessmentTask, _ContentTask)]}

# The executable task(description: str, subagent_type: str) stays unchanged.
# Validate both typed model output and legacy JSON strings before child dispatch.

def _check_subagent_input(request):
    """Return the request with a normalized description, or an error ToolMessage if it's invalid."""
    call = request.tool_call
    if call["name"] != "task":
        return request
    adapter = SUBAGENT_INPUT_SCHEMAS.get(call["args"].get("subagent_type"))
    if adapter is None:
        if model_config.REDUCED_TUTOR_HARNESS:
            return ToolMessage(
                content="Unsupported course specialist. Choose one of: " + ", ".join(sorted(SUBAGENT_INPUT_SCHEMAS)),
                tool_call_id=call["id"],
                status="error",
            )
        return request

    description = call["args"].get("description", "")
    try:
        # Some models (e.g. qwen via Ollama) send the description as a JSON object instead of a string
        if isinstance(description, str):
            description = json.loads(description)
        if isinstance(description, dict) and call["args"].get("subagent_type") == "content-generating-agent":
            # The legacy string schema can't hide these fields; drop them so the question log fills them
            description = {key: value for key, value in description.items() if key not in _FILLED_BY_CODE}
        validated = adapter.validate_python(description)
    except (ValidationError, ValueError) as e:
        return ToolMessage(
            content=f"Invalid task description for {call['args']['subagent_type']}:\n{e}",
            tool_call_id=call["id"],
            status="error",
        )
    # Pass the subagent a normalized JSON string: task() expects a string, and defaults get filled in
    args = {**call["args"], "description": adapter.dump_json(validated).decode()}
    return request.override(tool_call={**call, "args": args})


def _with_declared_specialists(request):
    """Advertise the same supported routes that the tool-call guard enforces."""
    if not model_config.REDUCED_TUTOR_HARNESS:
        return request
    description = (
        "Delegate to one of the course specialists listed below. Follow the routing policy and JSON input "
        "contracts in the system instructions. Set description to that JSON input; conversation history "
        "is supplied automatically. Keep assessments, answer keys, rubrics, and other internal metadata private.\n\n"
        "Available course specialists:\n" + "\n".join(f"- {name}" for name in sorted(SUBAGENT_INPUT_SCHEMAS))
    )
    # Copy only the model-facing descriptor; never replace the registered dispatch
    # tool, whose string API receives the normalized input from the tool wrapper.
    tools = []
    for tool in request.tools:
        descriptor = convert_to_openai_tool(tool)
        if descriptor.get("function", {}).get("name") == "task":
            descriptor = deepcopy(descriptor)
            descriptor["function"]["description"] = description
            if isinstance(request.model, ChatOllama):
                # Ollama's public Parameters model drops root anyOf. Keep the
                # executable string schema and validate the JSON before dispatch.
                descriptor["function"]["parameters"]["properties"]["subagent_type"]["enum"] = sorted(SUBAGENT_INPUT_SCHEMAS)
            else:
                descriptor["function"]["parameters"] = deepcopy(_TASK_PARAMETERS)
            tools.append(descriptor)
        else:
            tools.append(tool)
    return request.override(tools=tools)


class ValidateSubagentInput(AgentMiddleware):
    def wrap_model_call(self, request, handler):
        return handler(_with_declared_specialists(request))

    async def awrap_model_call(self, request, handler):
        return await handler(_with_declared_specialists(request))

    # Both versions are needed: invoke()/stream() use the sync one, ainvoke()/astream() the async one
    def wrap_tool_call(self, request, handler):
        checked = _check_subagent_input(request)
        return checked if isinstance(checked, ToolMessage) else handler(checked)

    async def awrap_tool_call(self, request, handler):
        checked = _check_subagent_input(request)
        return checked if isinstance(checked, ToolMessage) else await handler(checked)

validate_subagent_input = ValidateSubagentInput()
