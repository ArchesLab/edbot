from pathlib import Path
import yaml
from pydantic import TypeAdapter
import tools
import middleware
import interface_def as interface_def
from tools.markdown_embedding import load_sebook_store

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_ollama import ChatOllama
from langchain.agents.structured_output import ToolStrategy

ROOT_DIR = Path(__file__).parent # src/edbot
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
            "system_prompt": (ROOT_DIR / spec["system_prompt_path"]).read_text(),
            "response_format": ToolStrategy(schemas[spec["response_format"]]),
            # Shows the subagent the student conversation passed down from the orchestrator
            "middleware": [middleware.InjectConversationMiddleware()]
        }

        if "model" in spec:
            subagent["model"] = spec["model"]
        if "tools" in spec:
            subagent["tools"] = [ available_tools[t] for t in spec["tools"]]
        if "input_schema" in spec:
            middleware.SUBAGENT_INPUT_SCHEMAS[name] = TypeAdapter(schemas[spec["input_schema"]])

        subagents.append(subagent)
    return subagents

def create_edbot_agent():
    """Create orchestrator agent configured by filesystem files."""
    model = ChatOllama(model="qwen3.8:27b", num_ctx=32768)
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
        system_prompt=(ROOT_DIR / "prompts" / "system_prompt.md").read_text(), # switch to orchestrator prompt later
        middleware=[middleware.ConversationMiddleware(), middleware.validate_subagent_input],
        model=model,
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
        print("\nedbot: ", end="", flush=True)
        last_message_id = None
        mid_line = False # Used for formatting newlines

        # "messages" yields LLM tokens as they're generated; "values" yields the full state after each step
        for mode, data in agent.stream({"messages": messages}, stream_mode=["messages", "values"]):
            if mode == "values":
                messages = data["messages"] # keep the latest full history for the next turn
                continue
            chunk, metadata = data

            # Only the orchestrator's own model calls: skips tool results and middleware model calls
            if metadata.get("langgraph_node") != "model":
                continue

            # Tool calls stream in pieces; only the first piece of each call carries the tool name
            for tool_call in getattr(chunk, "tool_call_chunks", None) or []:
                if tool_call.get("name") == "search_markdown_sources":
                    if mid_line:
                        print()
                    print("[searching SEBook...]", flush=True)
                    mid_line = False
            if not chunk.text:
                continue
            if mid_line and chunk.id != last_message_id:
                print("\n", flush=True) # a new model reply right after earlier reply text
            last_message_id = chunk.id
            print(chunk.text, end="", flush=True)
            mid_line = True
        print()

    print("Goodbye!")

if __name__ == "__main__":
    main()