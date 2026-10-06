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
            try:
                adapter.validate_json(call["args"].get("description", ""))
            except ValidationError as e:
                return ToolMessage(
                    content=f"Invalid task description for {call['args']['subagent_type']}:\n{e}",
                    tool_call_id=call["id"],
                    status="error",
                )
    return handler(request)