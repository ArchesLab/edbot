"""Stop fruitless repeated retrieval without cutting off new source evidence."""
import asyncio
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.agents.middleware.types import ModelRequest
from test_sglang_integration import ScriptedServer, tool_reply


def messages(results):
    result = [HumanMessage(content="Internal content task")]
    for index, text in enumerate(results):
        result.extend([AIMessage(content="", tool_calls=[{"name": "search_markdown_sources", "id": str(index),
                       "args": {"query": f"query {index}"}, "type": "tool_call"}]),
                       ToolMessage(content=text, tool_call_id=str(index), name="search_markdown_sources")])
    return result


class RetrievalProgressTests(unittest.TestCase):
    def test_two_redundant_results_force_a_grounded_completion_or_coverage_gap(self):
        from edbot.middleware.retrieval_progress import RetrievalProgress
        a, b = "## Chunk 1\nSource: A\n\nOne fact.", "## Chunk 2\nSource: B\n\nAnother fact."
        trace = messages([a + "\n\n---\n\n" + b, b.replace("Chunk 2", "Chunk 1") + "\n\n---\n\n" + a.replace("Chunk 1", "Chunk 2"), a])
        request = ModelRequest(model=None, messages=trace, state={"messages": trace},
                               system_message=SystemMessage(content="Keep the answer private."),
                               tools=[{"name": "search_markdown_sources"}, {"name": "read_file"}])
        selected = RetrievalProgress().wrap_model_call(request, lambda captured: captured)
        self.assertEqual(selected.tools, [])
        self.assertIn("coverage_gap", selected.system_message.text)
        self.assertIn("Keep the answer private.", selected.system_message.text)
        self.assertIs(selected.messages, request.messages)
        self.assertEqual(len(request.tools), 2)

    def test_new_evidence_resets_stagnation_and_other_tools_or_old_turns_do_not_count(self):
        from edbot.middleware.retrieval_progress import RetrievalProgress
        for trace in (messages(["A", "A", "B", "B"]),
                      messages(["A", "A", "A"]) + [HumanMessage(content="New task")],
                      [HumanMessage(content="task"), ToolMessage(content="A", tool_call_id="unmatched", name="search_markdown_sources")]):
            request = ModelRequest(model=None, messages=trace, state={"messages": trace}, tools=[{"name": "search_markdown_sources"}])
            self.assertIs(RetrievalProgress().wrap_model_call(request, lambda captured: captured), request)

    def test_missing_paths_and_failed_searches_count_as_no_evidence_without_erasing_errors(self):
        from edbot.middleware.retrieval_progress import RetrievalProgress
        for trace in (messages([f"No SEBook content found under path_prefix '{path}'. Retry without path_prefix."
                                for path in ("first-missing", "second-missing")]), messages(["failure one", "failure two"])):
            if trace[-1].content == "failure two":
                for message in trace:
                    if isinstance(message, ToolMessage):
                        message.status = "error"
            request = ModelRequest(model=None, messages=trace, state={"messages": trace}, tools=[{"name": "search_markdown_sources"}])
            selected = RetrievalProgress().wrap_model_call(request, lambda captured: captured)
            self.assertEqual(selected.tools, [])
            self.assertIs(selected.messages, trace)


class RetrievalProgressGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_child_stops_research_loop_and_preserves_missing_source_handling(self):
        from edbot import edbot_agent, service
        from langchain_core.tools import tool
        from langgraph.store.memory import InMemoryStore
        from langgraph.checkpoint.memory import InMemorySaver
        from test_sglang_integration import text_reply
        searches = []
        @tool
        def search_markdown_sources(query: str) -> str:
            """Return the same incomplete course passage for each paraphrase."""
            searches.append(query)
            return "## Chunk 1\nSource: SEBook/queues.md\n\nA queue is FIFO."
        call = {"subagent_type": "content-generating-agent", "description": {
            "concept": "queues", "mode": "explain_at_tier", "target_tier": "Apply"}}
        searches_script = [tool_reply("search_markdown_sources", {"query": query}) for query in ("overflow", "capacity", "full queue")]
        for i, reply in enumerate(searches_script):
            reply["deltas"][1]["tool_calls"][0]["id"] = f"lookup-{i}"
        output = {"mode": "explain_at_tier", "concept": "queues", "target_tier": "Apply",
                  "content": "Please share the queue's overflow contract.", "coverage_gap": "Overflow behavior is not documented."}
        with ScriptedServer([tool_reply("task", call), *searches_script, tool_reply("CGAOutput", output),
                             text_reply(output["content"])]) as server, patch.object(edbot_agent, "load_sebook_store"), \
                patch.object(edbot_agent.tools, "search_markdown_sources", search_markdown_sources):
            agent = edbot_agent.create_edbot_agent(checkpointer=InMemorySaver(serde=service.SERDE), store=InMemoryStore())
            with patch.object(service, "_agent", agent):
                events = [event async for event in service.chat_turn("stagnant-search", "What happens if this queue is full?")]
            self.assertEqual(events[-1].type, "done")
            self.assertEqual(len(searches), 3)
            last_child = server.requests[4][1]
            self.assertEqual([t["function"]["name"] for t in last_child["tools"]], ["CGAOutput"])
            self.assertIn("coverage_gap", last_child["messages"][0]["content"])
            self.assertEqual("".join(e.text for e in events if e.type == "text"), output["content"])
            self.assertEqual(len(server.requests), 6, "The parent must still handle the source gap")


if __name__ == "__main__":
    unittest.main()
