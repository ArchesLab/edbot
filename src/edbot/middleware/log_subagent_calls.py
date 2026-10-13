import logging
import time
from langchain.agents.middleware import AgentMiddleware

# Logs when the orchestrator calls a subagent through task(), and when it finishes.
# Listed before validate_subagent_input so calls the validator rejects are logged too.
logger = logging.getLogger(__name__)

def _log_start(call) -> float:
    logger.info("Calling subagent %s", call["args"].get("subagent_type"))
    # DEBUG, not INFO: a UCA answer_submission input contains the student's answer
    logger.debug("Subagent input: %s", call["args"].get("description", ""))
    return time.monotonic()

def _log_end(call, result, start: float):
    name, elapsed = call["args"].get("subagent_type"), time.monotonic() - start
    # The validator returns an error ToolMessage; a real subagent run returns a Command
    if getattr(result, "status", None) == "error":
        logger.warning("Subagent %s rejected (invalid input) after %.0fs", name, elapsed)
    else:
        logger.info("Subagent %s finished in %.0fs", name, elapsed)

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
