from dotenv import load_dotenv
load_dotenv() # before langchain imports, so LANGSMITH_* settings from .env are set when tracing starts

import argparse
import asyncio
import logging
from pathlib import Path
import yaml
from pydantic import TypeAdapter
from edbot import tools, middleware, interface_def, model_config
from edbot.tools.markdown_embedding import load_sebook_store

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from edbot.chat_model import create_chat_model
from edbot.middleware.direct_content import CompleteContentMiddleware, DirectContentMiddleware
from edbot.middleware.assessment_result import AssessmentResultMiddleware, assessment_prompt
from edbot.middleware.assessment_prior import PrefetchAssessmentPrior
from edbot.middleware.content_after_assessment import RequireContentAfterAssessment
from edbot.middleware.course_evidence import CaptureCourseEvidence
from edbot.middleware.focused_cga_prompt import FocusedCGAPrompt
from edbot.tutor_harness import tutor_middleware
from langchain.agents.structured_output import ToolStrategy

ROOT_DIR = Path(__file__).parent # src/edbot
backend = FilesystemBackend(root_dir=ROOT_DIR)

def load_subagents(config_path: Path) -> list:
    """Load subagent definitions from YAML and wire up tools."""

    # Map tool names to actual tool objects
    available_tools = {
        "search_markdown_sources": tools.search_markdown_sources,
        "get_conversation_history": tools.get_conversation_history,
        "fetch_student_data": tools.fetch_student_data,
        "update_student_model": tools.update_student_model, # UCA only: the student model's single writer
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
            "middleware": [middleware.InjectConversationMiddleware(),
                           *(tutor_middleware(backend) if model_config.REDUCED_TUTOR_HARNESS else [])]
        }

        if "tools" in spec:
            subagent["tools"] = [ available_tools[t] for t in spec["tools"]]
        if "input_schema" in spec:
            middleware.SUBAGENT_INPUT_SCHEMAS[name] = TypeAdapter(schemas[spec["input_schema"]])

        if name == "content-generating-agent":
            if model_config.REDUCED_TUTOR_HARNESS:
                subagent["middleware"].insert(0, FocusedCGAPrompt(subagent["system_prompt"]))
            subagent["middleware"].append(CompleteContentMiddleware())
        elif name == "understanding-checking-agent" and model_config.DETERMINISTIC_ASSESSMENT_SAVE:
            subagent["tools"] = [tool for tool in subagent["tools"] if tool.name != "update_student_model"]
            subagent["system_prompt"] = assessment_prompt(subagent["system_prompt"])
            if model_config.PREFETCH_ASSESSMENT_PRIOR:
                subagent["middleware"][0] = PrefetchAssessmentPrior(subagent["system_prompt"])
            subagent["middleware"].append(CompleteContentMiddleware(output_tool="UCAOutput", reject_tool_errors=True))

        subagents.append(subagent)
    return subagents

def create_edbot_agent(checkpointer=None, store=None):
    """Create orchestrator agent configured by filesystem files.

    Pass a checkpointer to save conversations between turns, and a store for the student model
    (see service.get_agent). Runs must pass context=EdbotContext(student_id=...).
    """
    # One client and context profile are inherited by every subagent.
    model = create_chat_model()
    # Sync SEBook and load (or rebuild) its embeddings now, so the first search doesn't wait on it
    load_sebook_store()

    # Conversation is stored as state, fetched by middleware, instead of passing as input to subagents
    # Middleware validates subagent inputs for each tool call
    return create_deep_agent(
        memory=["./AGENTS.md"],
        skills=["./skills/"],
        subagents=load_subagents(ROOT_DIR / "subagents.yaml"),
        backend=backend,
        # The orchestrator reads the student model but never writes it
        tools=[tools.search_markdown_sources, tools.fetch_student_data],
        system_prompt=(ROOT_DIR / "prompts" / "orchestrator_prompt.md").read_text(), # switch to orchestrator prompt later
        middleware=[*(tutor_middleware(backend, include_memory=True) if model_config.REDUCED_TUTOR_HARNESS else []),
                    middleware.ConversationMiddleware(), CaptureCourseEvidence(), middleware.log_subagent_calls,
                    middleware.validate_subagent_input, AssessmentResultMiddleware(),
                    RequireContentAfterAssessment(), DirectContentMiddleware()],
        model=model,
        checkpointer=checkpointer,
        store=store,
        context_schema=interface_def.EdbotContext, # type of runtime.context in every tool
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
    (httpx alone would log every model request at INFO)."""
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
