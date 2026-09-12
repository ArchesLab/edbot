import os
from pathlib import Path
import yaml
import tools as tools

from deepagents import create_deep_agent
from langchain_ollama import ChatOllama

ROOT_DIR = Path(__file__).parent # src/edbot

system_prompt = """You are the orchestrator for edbot, an educational content system.
Your job is to coordinate specialist subagents to produce assessment materials
for students, grounded strictly in course source material.

## Delegation policy
- For any request to generate a question, quiz item, or practice problem,
  delegate to the question-generator subagent via the task() tool. Do not
  attempt to write questions yourself.
- Do not fabricate source content — all factual claims must trace back to
  material retrieved by a subagent's retrieve_sources call.

## Your role
- Interpret the student's request (topic, difficulty, question count, format)
  and pass clear, complete instructions to the question-generator subagent.
- Once the subagent returns its output, relay it to the user exactly as
  given — the full question text, answer choices, correct answer, and
  rationale. Do not summarize, critique, grade, or add commentary of your
  own on top of it.
- If a request doesn't match any available subagent's capability, say so
  rather than guessing.
"""

def load_subagents(config_path: Path) -> list:
    """Load subagent definitions from YAML and wire up tools.
    NOTE: This is a custom utility for this example. Unlike `memory` and `skills`,
    deepagents doesn't natively load subagents from files - they're normally
    defined inline in the create_deep_agent() call. We externalize to YAML here
    to keep configuration separate from code.
    """

    # Map tool names to actual tool objects
    available_tools = {
        "search_sources": tools.search_sources
    }

    # Load in subagents configuration file. Used to modularize subagent config
    with open(config_path) as f:
        config = yaml.safe_load(f)

    subagents = []
    for name, spec in config.items():
        subagent = {
            "name": name,
            "description": spec["description"],
            "system_prompt": spec["system_prompt"]
        }

        if "model" in spec:
            subagent["model"] = spec["model"]
        if "tools" in spec:
            subagent["tools"] = [ available_tools[t] for t in spec["tools"]]
        
        subagents.append(subagent)
    return subagents

def create_edbot_agent():
    """Create orchestrator agent configured by filesystem files."""
    model = ChatOllama(model="qwen3:8b", num_ctx=32768)
    return create_deep_agent(
        memory=["./AGENTS.md"],
        skills=["./skills/"],
        subagents=load_subagents(ROOT_DIR / "subagents.yaml"),
        backend=tools.backend,
        system_prompt=system_prompt,
        model=model
    )

def main():
    print("Creating agent...")
    agent = create_edbot_agent()
    print("Agent created!")

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Ask me a question on CPU scheduling."}]}
    )

    print(result["messages"][-1].content)

main()