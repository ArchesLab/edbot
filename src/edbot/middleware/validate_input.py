from copy import deepcopy
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


# Correlate the outer role and input; an independent description union permits
# CGA-shaped UCA calls. Public conversion inlines references for serving grammars.
_TASK_PARAMETERS = {"anyOf": [convert_to_openai_tool(schema)["function"]["parameters"]
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
        if isinstance(description, dict):
            validated = adapter.validate_python(description)
        else:
            validated = adapter.validate_json(description)
    except ValidationError as e:
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
