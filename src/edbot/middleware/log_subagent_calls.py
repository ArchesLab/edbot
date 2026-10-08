import time
from langchain.agents.middleware import AgentMiddleware

# Prints when the orchestrator calls a subagent through task(), and when it finishes.
# Listed before validate_subagent_input so calls the validator rejects are printed too.

def _log_start(call) -> float:
    print(f"\n[calling subagent {call['args'].get('subagent_type')}...]", flush=True)
    print(f"[input: {call['args'].get('description', '')}]", flush=True)
    return time.monotonic()

def _log_end(call, result, start: float):
    # The validator returns an error ToolMessage; a real subagent run returns a Command
    status = "rejected (invalid input)" if getattr(result, "status", None) == "error" else "finished"
    print(f"[subagent {call['args'].get('subagent_type')} {status} in {time.monotonic() - start:.0f}s]", flush=True)

class LogSubagentCalls(AgentMiddleware):
    # Both versions are needed: invoke()/stream() use the sync one, ainvoke()/astream() the async one
    def wrap_tool_call(self, request, handler):
        call = request.tool_call
        if call["name"] != "task":
            return handler(request)
        start = _log_start(call)
        result = handler(request)
        _log_end(call, result, start)
        return result

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        if call["name"] != "task":
            return await handler(request)
        start = _log_start(call)
        result = await handler(request)
        _log_end(call, result, start)
        return result

log_subagent_calls = LogSubagentCalls()
