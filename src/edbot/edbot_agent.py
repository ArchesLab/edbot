import os
from pathlib import Path
from urllib import response
from typing import Union
import yaml
import tools as tools
import interface_def as interface_def

from deepagents import create_deep_agent
from langchain_ollama import ChatOllama
from langchain.agents.structured_output import ToolStrategy

ROOT_DIR = Path(__file__).parent # src/edbot

def load_subagents(config_path: Path) -> list:
    """Load subagent definitions from YAML and wire up tools.
    NOTE: This is a custom utility for this example. Unlike `memory` and `skills`,
    deepagents doesn't natively load subagents from files - they're normally
    defined inline in the create_deep_agent() call. We externalize to YAML here
    to keep configuration separate from code.
    """

    # Map tool names to actual tool objects
    available_tools = {
        "search_sources": tools.search_sources,
        "get_conversation_history": tools.get_conversation_history
    }

    response_formats = {
        "OrchestratorAgentInput": interface_def.OrchestratorAgentInput,
        "UCAInput": interface_def.UCAInput,
        "CGAInput": interface_def.CGAInput
    }

    # Load in subagents configuration file. Used to modularize subagent config
    with open(config_path) as f:
        config = yaml.safe_load(f)

    subagents = []
    for name, spec in config.items():
        subagent = {
            "name": name,
            "description": spec["description"],
            "system_prompt": spec["system_prompt"],
            "response_format": ToolStrategy(Union[tuple(response_formats[r] for r in spec["response_format"])])
        }

        if "model" in spec:
            subagent["model"] = spec["model"]
        if "tools" in spec:
            subagent["tools"] = [ available_tools[t] for t in spec["tools"]]
        
        subagents.append(subagent)
    return subagents

# TODO(review): validate task() descriptions against the subagent input schemas.
# The orchestrator calls subagents via task(description: str, subagent_type: str),
# so UCAInput/CGAInput can't be enforced by response_format. This middleware
# checks the description JSON before the subagent runs and, on failure, returns
# the validation error to the orchestrator so it can retry the call.
#
# from pydantic import TypeAdapter, ValidationError
# from langchain.agents.middleware import wrap_tool_call
# from langchain_core.messages import ToolMessage
#
# # Keys must match the subagent names in subagents.yaml ("content-generating-agent" is a placeholder)
# SUBAGENT_INPUT_SCHEMAS = {
#     "understanding-checking-agent": TypeAdapter(interface_def.UCAInput),
#     "content-generating-agent": TypeAdapter(interface_def.CGAInput),
# }
#
# @wrap_tool_call
# def validate_subagent_input(request, handler):
#     call = request.tool_call
#     if call["name"] == "task":
#         adapter = SUBAGENT_INPUT_SCHEMAS.get(call["args"].get("subagent_type"))
#         if adapter is not None:
#             try:
#                 adapter.validate_json(call["args"].get("description", ""))
#             except ValidationError as e:
#                 return ToolMessage(
#                     content=f"Invalid task description for {call['args']['subagent_type']}:\n{e}",
#                     tool_call_id=call["id"],
#                     status="error",
#                 )
#     return handler(request)

def create_edbot_agent():
    """Create orchestrator agent configured by filesystem files."""
    model = ChatOllama(model="qwen3.8:27b", num_ctx=32768)
    return create_deep_agent(
        memory=["./AGENTS.md"],
        skills=["./skills/"],
        subagents=load_subagents(ROOT_DIR / "subagents.yaml"),
        backend=tools.backend,
        tools=[tools.search_sources],
        system_prompt=(ROOT_DIR / "prompts" / "system_prompt.md").read_text(),
        # TODO(review): switch to the orchestrator prompt once subagents are wired up
        # system_prompt=(ROOT_DIR / "prompts" / "orchestrator.md").read_text(),
        # middleware=[validate_subagent_input],
        model=model,
        response_format=ToolStrategy(
            Union[interface_def.ChatBotOutput]
        )
        # TODO(review): subagents are now called via task(), so the orchestrator's
        # final output is always the student-facing reply
        # response_format=ToolStrategy(interface_def.ChatBotOutput)
    )

def main():
    # print("Creating agent...")
    agent = create_edbot_agent()
    # print("Agent created!")

    # Full conversation history, passed back in each turn so the agent remembers context
    messages = []

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            break

        messages.append({"role": "user", "content": user_input})
        result = agent.invoke({"messages": messages})
        messages = result["messages"]

        # With response_format set, the parsed output lands in structured_response
        response = result.get("structured_response")
        print(f"\nedbot: {response if response is not None else messages[-1].content}")

    print("Goodbye!")

if __name__ == "__main__":
    main()