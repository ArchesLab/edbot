from pydantic import TypeAdapter, ValidationError
from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage

# Filled by load_subagents() in edbot_agent.py from each subagent's input_schema in subagents.yaml
SUBAGENT_INPUT_SCHEMAS: dict[str, TypeAdapter] = {}

# validate task() descriptions against the subagent input schemas.
# The orchestrator calls subagents via task(description: str, subagent_type: str),
# so UCAInput/CGAInput can't be enforced by response_format. This middleware
# checks the description JSON before the subagent runs and, on failure, returns
# the validation error to the orchestrator so it can retry the call.

@wrap_tool_call
def validate_subagent_input(request, handler):
    call = request.tool_call
    if call["name"] == "task":
        adapter = SUBAGENT_INPUT_SCHEMAS.get(call["args"].get("subagent_type"))
        if adapter is not None:
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
            request = request.override(tool_call={**call, "args": args})
    return handler(request)