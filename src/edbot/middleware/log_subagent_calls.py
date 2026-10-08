import time
from langchain.agents.middleware import wrap_tool_call

# Prints when the orchestrator calls a subagent through task(), and when it finishes.
# Listed before validate_subagent_input so calls the validator rejects are printed too.
@wrap_tool_call
def log_subagent_calls(request, handler):
    call = request.tool_call
    if call["name"] != "task":
        return handler(request)

    name = call["args"].get("subagent_type")
    print(f"\n[calling subagent {name}...]", flush=True)
    print(f"[input: {call['args'].get('description', '')}]", flush=True)
    start = time.monotonic()
    result = handler(request)
    # The validator returns an error ToolMessage; a real subagent run returns a Command
    status = "rejected (invalid input)" if getattr(result, "status", None) == "error" else "finished"
    print(f"[subagent {name} {status} in {time.monotonic() - start:.0f}s]", flush=True)
    return result
