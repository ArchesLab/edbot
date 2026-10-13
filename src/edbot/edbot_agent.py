from dotenv import load_dotenv
load_dotenv() # before langchain imports, so LANGSMITH_* settings from .env are set when tracing starts

import argparse
import asyncio
import logging
from pathlib import Path
import yaml
from pydantic import TypeAdapter
from edbot import tools, middleware, interface_def
from edbot.tools.markdown_embedding import load_sebook_store

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_ollama import ChatOllama
from langchain.agents.structured_output import ToolStrategy

ROOT_DIR = Path(__file__).parent # src/edbot
MODEL_NAME = "qwen3.8:27b" # Shared by the orchestrator and all subagents
NUM_CTX = 32768 # Ollama context window, in tokens
backend = FilesystemBackend(root_dir=ROOT_DIR)

# ollama serve
# ollama pull <model>
# ollama list
# ollama run <name-of-model>

def load_subagents(config_path: Path) -> list:
    """Load subagent definitions from YAML and wire up tools."""

    # Map tool names to actual tool objects
    available_tools = {
        "search_markdown_sources": tools.search_markdown_sources,
        "get_conversation_history": tools.get_conversation_history
    }

    schemas = {
        "OrchestratorAgentInput": interface_def.OrchestratorAgentInput,
        "UCAInput": interface_def.UCAInput,
        "UCAOutput": interface_def.UCAOutput,
        "CGAInput": interface_def.CGAInput,
        "CGAOutput": interface_def.CGAOutput,
    }

    # Load in subagents configuration file. Used to modularize subagent config
    with open(config_path) as f:
        config = yaml.safe_load(f)

    subagents = []
    for name, spec in config.items():
        subagent = {
            "name": name,
            "description": spec["description"],
            "system_prompt": (ROOT_DIR / spec["system_prompt_path"]).read_text(),
            "response_format": ToolStrategy(schemas[spec["response_format"]]),
            # Shows the subagent the student conversation passed down from the orchestrator
            "middleware": [middleware.InjectConversationMiddleware()]
        }

        if "tools" in spec:
            subagent["tools"] = [ available_tools[t] for t in spec["tools"]]
        if "input_schema" in spec:
            middleware.SUBAGENT_INPUT_SCHEMAS[name] = TypeAdapter(schemas[spec["input_schema"]])

        subagents.append(subagent)
    return subagents

def create_edbot_agent(checkpointer=None):
    """Create orchestrator agent configured by filesystem files.

    Pass a checkpointer to save conversations between turns (see service.get_agent).
    """
    # ChatOllama has no built-in profile, so without max_input_tokens deepagents assumes a
    # 170k-token window and never summarizes before Ollama silently truncates the prompt
    model = ChatOllama(model=MODEL_NAME, num_ctx=NUM_CTX, profile={"max_input_tokens": NUM_CTX})
    # Sync SEBook and load (or rebuild) its embeddings now, so the first search doesn't wait on it
    load_sebook_store()

    # Conversation is stored as state, fetched by middleware, instead of passing as input to subagents
    # Middleware validates subagent inputs for each tool call
    return create_deep_agent(
        memory=["./AGENTS.md"],
        skills=["./skills/"],
        subagents=load_subagents(ROOT_DIR / "subagents.yaml"),
        backend=backend,
        tools=[tools.search_markdown_sources],
        system_prompt=(ROOT_DIR / "prompts" / "orchestrator_prompt.md").read_text(), # switch to orchestrator prompt later
        middleware=[middleware.ConversationMiddleware(), middleware.log_subagent_calls, middleware.validate_subagent_input],
        model=model,
        checkpointer=checkpointer,
    )

async def run_cli(student_id: str):
    """Terminal chat. Shows exactly what a student sees in any other interface, via chat_turn()."""
    from edbot import service # imported here because service imports this module

    saved = await service.saved_message_count(student_id)
    print(f"Student: {student_id} ({f'continuing, {saved} saved messages' if saved else 'new conversation'})")

    try:
        while True:
            try:
                # input() blocks, so run it in a thread to keep the event loop free
                user_input = (await asyncio.to_thread(input, "\nYou: ")).strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit"):
                break

            replying = False # whether "edbot: " has been printed for this turn
            async for event in service.chat_turn(student_id, user_input):
                if event.type == "status":
                    print(f"  ({event.text})", flush=True)
                elif event.type == "text":
                    if not replying:
                        print("\nedbot: ", end="", flush=True)
                        replying = True
                    print(event.text, end="", flush=True)
                elif event.type == "error":
                    print(f"\nedbot: {event.message}", flush=True)
            print()
    finally:
        await service.close()

    print("Goodbye!")

def setup_logging(verbosity: int):
    """Send logs to stderr. edbot's own loggers get the chosen level; libraries stay at WARNING
    (httpx alone would log every Ollama request at INFO)."""
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    level = {0: logging.WARNING, 1: logging.INFO}.get(verbosity, logging.DEBUG)
    logging.getLogger("edbot").setLevel(level)

def main():
    parser = argparse.ArgumentParser(description="Chat with edbot in the terminal")
    parser.add_argument("--student", default="dev-cli", help="student ID; each student has one ongoing conversation")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="-v shows subagent calls and timings, -vv also shows subagent inputs")
    args = parser.parse_args()
    setup_logging(args.verbose)
    asyncio.run(run_cli(args.student))

if __name__ == "__main__":
    main()
