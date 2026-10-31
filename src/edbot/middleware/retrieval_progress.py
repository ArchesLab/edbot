"""End repeated source lookups that add no evidence; preserve uncertainty."""
import re

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


_COMPLETION = (
    "Course retrieval has twice returned no new passages. Finish this task using only the evidence "
    "actually available and explicit scenario premises. Do not invent a factual bridge or an answer. "
    "If a necessary fact remains unsupported, state that limitation in content, ask for the missing "
    "source or contract, and set coverage_gap. Missing an identical worked example is not itself a "
    "gap. Preserve the student's language, brevity and any no-answer contract."
)


def _stagnant(messages):
    start = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)), -1)
    if start < 0:
        return False
    calls, seen, repeated = set(), set(), 0
    for message in messages[start + 1:]:
        if isinstance(message, AIMessage):
            calls.update(call["id"] for call in message.tool_calls if call["name"] == "search_markdown_sources")
        elif (isinstance(message, ToolMessage) and message.tool_call_id in calls
              and message.name == "search_markdown_sources"
              and isinstance(message.content, str)):
            # Chunk ranks can change across paraphrases; their text and source
            # identity, not the displayed rank or query, determine novelty.
            chunks = set() if (message.status == "error" or message.content.startswith("No SEBook content found")) else {
                      re.sub(r"^## Chunk \d+\s*\n", "", part).strip()
                      for part in message.content.split("\n\n---\n\n") if part.strip()}
            if chunks - seen:
                repeated = 0
            else:
                repeated += 1
            seen.update(chunks)
    return repeated >= 2


class RetrievalProgress(AgentMiddleware):
    """CGA only. Keep the registered output schema and all existing guards.

    New source passages reset the counter; there is no fixed cap on useful
    retrieval. After two redundant results only the structured output tool is
    offered, requiring an evidence-bounded completion or an explicit gap.
    """

    @staticmethod
    def _request(request):
        if not _stagnant(request.messages):
            return request
        system = request.system_message
        if system is None:
            system = SystemMessage(content=_COMPLETION)
        elif isinstance(system.content, str):
            system = system.model_copy(update={"content": system.content + "\n\n" + _COMPLETION})
        else:
            system = system.model_copy(update={"content": [*system.content, {"type": "text", "text": _COMPLETION}]})
        return request.override(tools=[], system_message=system)

    def wrap_model_call(self, request, handler):
        return handler(self._request(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._request(request))
