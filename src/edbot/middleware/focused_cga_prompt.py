"""Select existing CGA instructions without another model call or mode inference."""
import json
import re
from typing import Annotated, NotRequired

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.agents.middleware.types import PrivateStateAttr
from langchain_core.messages import HumanMessage
from pydantic import TypeAdapter, ValidationError

from edbot.interface_def import CGAInput


_INPUT = TypeAdapter(CGAInput)
_TIERS = ("Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create")
_MODES = ("generate_question", "explain_at_tier", "probe_at_tier")
_SHARED = ("Role", "Teaching contract", "Input", "Tools", "Output", "Constraints")
_SECTIONS = (
    "Role", "Teaching contract", "Bloom's Taxonomy tiers", "Input", "Tools",
    *(f"Mode: `{mode}`" for mode in _MODES), "Novelty check", "Format selection", "Output", "Constraints",
)
_TIER_INTRO = "Use exactly these six tiers, lowest to highest."


class FocusedCGAState(AgentState):
    # Omitted from graph input/output; DeepAgents also excludes agent-private
    # state when crossing a task boundary. Never share this with another child.
    cga_prompt_selection: NotRequired[Annotated[dict[str, str] | None, PrivateStateAttr]]


def _variants(prompt: str) -> dict[tuple[str, str], str]:
    """Recognize the canonical layout or retain the complete original prompt.

    Selection removes whole unused mode sections and tier rows, not clauses in
    the shared contract. Unexpected headings/table structure disable selection
    so a future prompt edit cannot silently lose an unrecognized instruction.
    """
    headings = list(re.finditer(r"^## (.+)\n", prompt, re.M))
    if tuple(match[1] for match in headings) != _SECTIONS:
        return {}
    sections = {
        match[1]: prompt[match.start():headings[index + 1].start() if index + 1 < len(headings) else len(prompt)]
        for index, match in enumerate(headings)
    }
    bloom = sections["Bloom's Taxonomy tiers"]
    lines = bloom.splitlines(keepends=True)
    table = [(index, line) for index, line in enumerate(lines) if line.startswith("|")]
    if len(table) != 8 or [index for index, _ in table] != list(range(table[0][0], table[0][0] + 8)):
        return {}
    cells = [line.rstrip("\n").split("|")[1:-1] for _, line in table]
    if (any(len(row) != 4 for row in cells)
            or [value.strip() for value in cells[0]] != ["Tier", "Content asks the student to…", "Question templates", "Explanation style"]
            or [value.strip() for value in cells[1]] != ["---"] * 4
            or [row[0].strip() for row in cells[2:]] != [f"`{tier}`" for tier in _TIERS]
            or bloom.count(_TIER_INTRO) != 1):
        return {}
    format_lines = sections["Format selection"].splitlines(keepends=True)
    bullets = [line for line in format_lines if line.startswith("- ")]
    if len(bullets) != 6 or [re.match(r"^- `([^`]+)`: ", line).group(1)
            if re.match(r"^- `([^`]+)`: ", line) else None for line in bullets] != list(_TIERS):
        return {}

    # The unchanged shared contract is a stable prefix for all 18 variants.
    # This structure allows caching; actual cache reuse/latency is not promised.
    prefix = prompt[:headings[0].start()] + "".join(sections[name] for name in _SHARED)
    result = {}
    for mode in _MODES:
        for tier_index, tier in enumerate(_TIERS):
            selected_rows = [cells[0], cells[1], cells[tier_index + 2]]
            if mode != "explain_at_tier":
                selected_rows = [row[:3] for row in selected_rows]
            selected_table = "".join("|" + "|".join(row) + "|\n" for row in selected_rows)
            focused_bloom = ("".join(lines[:table[0][0]]) + selected_table
                             + "".join(lines[table[-1][0] + 1:]))
            focused_bloom = focused_bloom.replace(_TIER_INTRO, f"The supplied tier is `{tier}`.")
            selected_modes = (mode, "probe_at_tier") if mode == "explain_at_tier" else (mode,)
            focused = prefix + focused_bloom + "".join(sections[f"Mode: `{item}`"] for item in selected_modes)
            focused += sections["Novelty check"]
            if mode == "generate_question":
                focused += "".join(line for line in format_lines if line not in bullets or line.startswith(f"- `{tier}`:"))
            result[(mode, tier)] = focused
    return result


def _replace_span(system, original: str, focused: str):
    """Replace one exact text span while preserving rich system-message data."""
    if system is None:
        return None
    content = system.content
    if isinstance(content, str):
        if content.count(original) != 1:
            return None
        return system.model_copy(update={"content": content.replace(original, focused, 1)})
    if not isinstance(content, list):
        return None
    matches = []
    for index, block in enumerate(content):
        text = block if isinstance(block, str) else (
            block.get("text") if isinstance(block, dict) and block.get("type") == "text" else None)
        if isinstance(text, str) and original in text:
            matches.extend((index, text) for _ in range(text.count(original)))
    if len(matches) != 1:
        return None
    index, text = matches[0]
    changed = list(content)
    text = text.replace(original, focused, 1)
    changed[index] = text if isinstance(content[index], str) else {**content[index], "text": text}
    return system.model_copy(update={"content": changed})


class FocusedCGAPrompt(AgentMiddleware):
    """CGA only; install before InjectConversationMiddleware.

    DeepAgents supplies one internal HumanMessage per fresh task. Capture its
    validated mode/tier before student history is added, and retain that choice
    across the child's tool steps. This does not choose a teaching condition or
    certify the generated content. Malformed tasks always use the full prompt.
    """
    state_schema = FocusedCGAState

    def __init__(self, system_prompt: str):
        self._original = system_prompt
        self._variants = _variants(system_prompt)

    def before_agent(self, state, runtime):
        selection = None
        messages = state.get("messages", [])
        if len(messages) == 1 and isinstance(messages[0], HumanMessage) and isinstance(messages[0].content, str):
            try:
                raw = json.loads(messages[0].content)
                if isinstance(raw, dict) and {"mode", "concept", "target_tier"} <= raw.keys():
                    validated = _INPUT.validate_python(raw)
                    if not raw.keys() - type(validated).model_fields.keys():
                        selection = {"mode": validated.mode, "tier": validated.target_tier}
            except (ValidationError, ValueError, TypeError):
                pass
        # A new/re-entered child may carry old state. Always clear on fallback;
        # never scan history, tool output, or student JSON to recover a choice.
        return {"cga_prompt_selection": selection}

    async def abefore_agent(self, state, runtime):
        return self.before_agent(state, runtime)

    def _request(self, request):
        selection = request.state.get("cga_prompt_selection")
        if not isinstance(selection, dict) or set(selection) != {"mode", "tier"}:
            return request
        mode, tier = selection["mode"], selection["tier"]
        if not isinstance(mode, str) or not isinstance(tier, str):
            return request
        focused = self._variants.get((mode, tier))
        if focused is None:
            return request
        system = _replace_span(request.system_message, self._original, focused)
        return request.override(system_message=system) if system is not None else request

    def wrap_model_call(self, request, handler):
        return handler(self._request(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._request(request))
