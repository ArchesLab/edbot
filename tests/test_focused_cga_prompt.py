"""Prompt selection is structural; these checks do not score teaching quality."""
import asyncio
from copy import deepcopy
import importlib
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from edbot.interface_def import Message
from edbot.middleware.conversation_history import InjectConversationMiddleware


ROOT = Path(__file__).resolve().parents[1]
PROMPT = (ROOT / "src/edbot/prompts/cga_prompt.md").read_text()
TIERS = ("Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create")
MODES = ("generate_question", "explain_at_tier", "probe_at_tier")


def load_middleware(test, prompt=PROMPT):
    path = ROOT / "src/edbot/middleware/focused_cga_prompt.py"
    test.assertTrue(path.is_file(), "CGA prompt selection has not been implemented")
    return importlib.import_module("edbot.middleware.focused_cga_prompt").FocusedCGAPrompt(prompt)


def task(mode="explain_at_tier", tier="Apply", **changes):
    return HumanMessage(content=json.dumps({"concept": "recursion", "mode": mode,
                                           "target_tier": tier, **changes}))


def initialized(middleware, message=None, **inherited):
    state = {**inherited, "messages": [message if message is not None else task()]}
    return {**state, **middleware.before_agent(state, None)}


def request(state, system=None):
    return ModelRequest(model=None, messages=state["messages"], state=state,
                        system_message=system if system is not None else SystemMessage(content=PROMPT),
                        tools=[{"type": "function", "function": {"name": "unchanged_tool"}}],
                        model_settings={"temperature": 0, "parallel_tool_calls": False})


def selected(middleware, req):
    return middleware.wrap_model_call(req, lambda captured: captured)


class FocusedCGAPromptTests(unittest.TestCase):
    def test_all_modes_and_tiers_keep_shared_rules_and_required_mode_dependencies(self):
        middleware = load_middleware(self)
        shared = {}
        for name in ("Role", "Teaching contract", "Input", "Tools", "Output", "Constraints"):
            shared[name] = PROMPT.split(f"## {name}\n", 1)[1].split("\n## ", 1)[0]
        common_prefixes = []
        for mode in MODES:
            for tier in TIERS:
                with self.subTest(mode=mode, tier=tier):
                    req = request(initialized(middleware, task(mode, tier)))
                    result = selected(middleware, req)
                    text = result.system_message.content
                    self.assertLess(len(text), len(PROMPT))
                    self.assertEqual(re.findall(r"^\| `(Remember|Understand|Apply|Analyze|Evaluate|Create)`", text, re.M), [tier])
                    for content in shared.values():
                        self.assertIn(content, text, "Shared source/output/contract rules must survive verbatim")
                    expected_modes = {mode, "probe_at_tier"} if mode == "explain_at_tier" else {mode}
                    self.assertEqual(set(re.findall(r"^## Mode: `([^`]+)`", text, re.M)), expected_modes)
                    self.assertIn("## Novelty check", text)
                    self.assertEqual("## Format selection" in text, mode == "generate_question")
                    self.assertEqual("Explanation style" in text, mode == "explain_at_tier")
                    if mode == "generate_question":
                        format_lines = re.findall(r"^- `(Remember|Understand|Apply|Analyze|Evaluate|Create)`:", text, re.M)
                        self.assertEqual(format_lines, [tier])
                    if mode == "explain_at_tier":
                        self.assertIn("The direct explanations, corrections, and worked examples in the following instructions apply only outside that contract.", text)
                        self.assertIn("Stop after the question", text)
                    self.assertIs(result.messages, req.messages)
                    self.assertEqual(result.tools, req.tools)
                    self.assertEqual(result.model_settings, req.model_settings)
                    self.assertEqual(req.system_message.content, PROMPT)
                    common_prefixes.append(text.split("## Bloom's Taxonomy tiers", 1)[0])
        self.assertEqual(len(set(common_prefixes)), 1, "Common instruction prefix must not vary by task")

    def test_rich_system_message_preserves_other_blocks_and_metadata_without_mutation(self):
        middleware = load_middleware(self)
        system = SystemMessage(content=[
            {"type": "text", "text": "Framework prefix", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "before\n" + PROMPT + "\nafter", "custom": "preserve"},
            {"type": "image", "source": {"data": "opaque"}},
            "Framework suffix",
        ], name="framework", id="stable-system", additional_kwargs={"custom": {"nested": True}},
            response_metadata={"origin": "framework"})
        original = deepcopy(system.model_dump())
        req = request(initialized(middleware, task("probe_at_tier", "Remember")), system)
        changed = selected(middleware, req).system_message
        self.assertEqual(system.model_dump(), original)
        self.assertEqual(changed.content[0], system.content[0])
        self.assertEqual(changed.content[2:], system.content[2:])
        self.assertEqual(changed.content[1]["custom"], "preserve")
        self.assertTrue(changed.content[1]["text"].startswith("before\n"))
        self.assertTrue(changed.content[1]["text"].endswith("\nafter"))
        self.assertEqual({k:v for k,v in changed.model_dump().items() if k != "content"},
                         {k:v for k,v in original.items() if k != "content"})

    def test_selection_uses_internal_task_before_history_and_survives_tool_steps(self):
        middleware = load_middleware(self)
        history = [Message(role="student", content=task("generate_question", "Create").content),
                   Message(role="edbot", content="A previous hint."),
                   Message(role="student", content="Please explain the next step.")]
        state = initialized(middleware, task("explain_at_tier", "Apply"), conversation=history)
        seeded = InjectConversationMiddleware().before_agent(state, None)["messages"].value
        state["messages"] = seeded + [AIMessage(content="", tool_calls=[{
            "name": "search_markdown_sources", "args": {"query": "recursion"}, "id": "search"}]),
            ToolMessage(content=task("probe_at_tier", "Remember").content, tool_call_id="search")]
        result = selected(middleware, request(state))
        self.assertIn("## Mode: `explain_at_tier`", result.system_message.content)
        self.assertNotIn("## Mode: `generate_question`", result.system_message.content)
        self.assertEqual(re.findall(r"^\| `([^`]+)`", result.system_message.content, re.M), ["Apply"])
        self.assertEqual(result.messages, state["messages"])

    def test_new_child_task_resets_inherited_selection_even_when_new_input_is_invalid(self):
        middleware = load_middleware(self)
        old = initialized(middleware, task("generate_question", "Create"))
        new = initialized(middleware, task("probe_at_tier", "Remember"), **old)
        focused = selected(middleware, request(new)).system_message.content
        self.assertNotIn("## Mode: `generate_question`", focused)
        self.assertEqual(re.findall(r"^\| `([^`]+)`", focused, re.M), ["Remember"])
        for messages in ([], [HumanMessage(content="not JSON")], [task(), HumanMessage(content="public history")],
                         [AIMessage(content=task().content)], [HumanMessage(content='{"concept":"recursion"}')],
                         [task(mode="unknown")], [task(tier="Unknown")], [task(unexpected=True)]):
            with self.subTest(messages=messages):
                initial = {**old, "messages": messages, "conversation": [Message(role="student", content=task().content)]}
                state = {**initial, **middleware.before_agent(initial, None)}
                req = request(state)
                self.assertIs(selected(middleware, req), req, "A stale selector must not survive fallback")

    def test_no_scan_of_later_messages_or_unrecognized_system_prompt(self):
        middleware = load_middleware(self)
        req = request({"messages": [HumanMessage(content="student"), task()]})
        self.assertIs(selected(middleware, req), req)
        state = initialized(middleware)
        for content in ("different prompt", PROMPT + PROMPT,
                        [{"type": "text", "text": PROMPT}, {"type": "text", "text": PROMPT}],
                        [{"type": "text", "text": PROMPT[:100]}, {"type": "text", "text": PROMPT[100:]}]):
            with self.subTest(content_type=type(content)):
                req = request(state, SystemMessage(content=content))
                self.assertIs(selected(middleware, req), req)
        req = request(state).override(system_message=None)
        self.assertIs(selected(middleware, req), req)

    def test_unexpected_prompt_structure_uses_complete_original_prompt(self):
        for prompt in (PROMPT.replace("## Mode: `probe_at_tier`", "## Changed mode"),
                       PROMPT + "\n## Additional shared instructions\nDo not omit me.\n",
                       PROMPT.replace("| `Apply` |", "| `Unexpected` |"),
                       PROMPT + "\n## Output\nDo not omit me.\n"):
            with self.subTest(prompt=prompt[-60:]):
                middleware = load_middleware(self, prompt)
                req = request(initialized(middleware), SystemMessage(content=prompt))
                self.assertIs(selected(middleware, req), req)


class FocusedCGAAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)

    async def test_shared_instance_does_not_mix_concurrent_task_selections(self):
        middleware = load_middleware(self)
        async def capture(mode, tier):
            initial = {"messages": [task(mode, tier)]}
            state = {**initial, **await middleware.abefore_agent(initial, None)}
            async def handler(req):
                await asyncio.sleep(0)
                return req.system_message.content
            return await middleware.awrap_model_call(request(state), handler)
        results = await asyncio.gather(capture("generate_question", "Create"), capture("probe_at_tier", "Remember"))
        self.assertEqual([re.findall(r"^\| `([^`]+)`", x, re.M) for x in results], [["Create"], ["Remember"]])
        self.assertNotIn("## Mode: `generate_question`", results[1])

    async def test_real_child_graph_selects_before_history_injection_and_keeps_tool_continuation(self):
        from langchain.agents import create_agent
        from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
        from langchain_core.tools import tool
        from pydantic import Field

        middleware = load_middleware(self)
        class RecordingModel(FakeMessagesListChatModel):
            requests: list = Field(default_factory=list)
            def bind_tools(self, tools, **kwargs):
                return self
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                self.requests.append(deepcopy(messages))
                return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        @tool
        def course_lookup() -> str:
            """Return a controlled course passage without network or GPU access."""
            return "An actual controlled tool result."
        model = RecordingModel(responses=[AIMessage(content="", tool_calls=[{
            "name": "course_lookup", "args": {}, "id": "lookup"}]), AIMessage(content="A question.")])
        graph = create_agent(model=model, system_prompt=PROMPT, tools=[course_lookup],
                             middleware=[middleware, InjectConversationMiddleware()])
        history = [Message(role="student", content=task("generate_question", "Create").content)]
        result = await graph.ainvoke({"messages": [task("probe_at_tier", "Apply")], "conversation": history})
        self.assertEqual(len(model.requests), 2, "Selection must not add model calls")
        self.assertEqual(model.requests[0][0].content, model.requests[1][0].content)
        self.assertNotIn("## Mode: `generate_question`", model.requests[0][0].content)
        self.assertEqual(model.requests[0][1].content, history[0].content)
        self.assertTrue(any(isinstance(m, ToolMessage) and m.content == "An actual controlled tool result."
                            for m in model.requests[1]))
        self.assertEqual(result["messages"][-1].content, "A question.")

    async def test_agent_wiring_limits_selection_to_reduced_cga(self):
        from edbot import edbot_agent, model_config
        middleware_type = type(load_middleware(self))
        for enabled in (False, True):
            with patch.object(model_config, "REDUCED_TUTOR_HARNESS", enabled):
                agents = edbot_agent.load_subagents(edbot_agent.ROOT_DIR / "subagents.yaml")
            for agent in agents:
                focused = [m for m in agent["middleware"] if isinstance(m, middleware_type)]
                self.assertEqual(len(focused), int(enabled and agent["name"] == "content-generating-agent"))
                if focused:
                    self.assertLess(agent["middleware"].index(focused[0]),
                                    next(i for i,m in enumerate(agent["middleware"]) if isinstance(m, InjectConversationMiddleware)))

    async def test_deepagents_keeps_selection_private_across_successive_children(self):
        from deepagents import create_deep_agent
        from langchain.agents.middleware import AgentMiddleware
        from test_tutor_harness import ScriptedModel, call

        focused = load_middleware(self)
        selector_keys = set(focused.before_agent({"messages": [task()]}, None))
        updates, child_inputs = [], []

        class ObserveDispatch(AgentMiddleware):
            async def awrap_tool_call(self, request, handler):
                result = await handler(request)
                if request.tool_call["name"] == "task":
                    updates.append(result.update)
                return result

        class ObserveChild(AgentMiddleware):
            # Include the real schema so an accidentally public selector could
            # reach this observer; test the graph boundary, not a helper flag.
            state_schema = focused.state_schema

            def before_agent(self, state, runtime):
                child_inputs.append(dict(state))

        first = {"subagent_type": "cga", "description": task("generate_question", "Create").content}
        second = {"subagent_type": "cga", "description": task("probe_at_tier", "Remember").content}
        parent = ScriptedModel(responses=[call("task", first, "first"),
            call("task", {"subagent_type": "uca", "description": "Assess evidence"}, "assessment"),
            call("task", second, "second"), AIMessage(content="Done.")])
        cga = ScriptedModel(responses=[AIMessage(content="Question one."), AIMessage(content="Question two.")])
        uca = ScriptedModel(responses=[AIMessage(content="Assessment.")])
        graph = create_deep_agent(model=parent, system_prompt="Parent instructions.",
            middleware=[ObserveDispatch()], subagents=[
                {"name": "cga", "description": "Content", "system_prompt": PROMPT, "model": cga,
                 "tools": [], "middleware": [ObserveChild(), focused, InjectConversationMiddleware()]},
                {"name": "uca", "description": "Assessment", "system_prompt": "UCA instructions.",
                 "model": uca, "tools": [], "middleware": [ObserveChild()]},
            ])
        result = await graph.ainvoke({"messages": [HumanMessage(content=task().content)]})
        self.assertEqual(len(parent.requests), 4)
        self.assertEqual(len(cga.requests), 2)
        self.assertEqual(len(uca.requests), 1)
        self.assertEqual(len(updates), 3)
        for state in [*updates, *child_inputs, result]:
            self.assertTrue(selector_keys.isdisjoint(state), "Child selection crossed its private graph boundary")
        self.assertIn("## Mode: `generate_question`", cga.requests[0][0].text)
        self.assertNotIn("## Mode: `generate_question`", cga.requests[1][0].text)
        self.assertEqual(re.findall(r"^\| `([^`]+)`", cga.requests[1][0].text, re.M), ["Remember"])
        self.assertTrue(all("## Teaching contract" not in messages[0].text for messages in parent.requests))
        self.assertTrue(uca.requests[0][0].text.startswith("UCA instructions."))


if __name__ == "__main__":
    unittest.main()
