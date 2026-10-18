"""Read-only model tools with DeepAgents' normal context recovery intact."""
from deepagents import FilesystemMiddleware, MemoryMiddleware
from deepagents.backends.protocol import BackendProtocol
from langchain.agents.middleware import AgentMiddleware


def tutor_middleware(backend: BackendProtocol, *, include_memory: bool = False) -> list[AgentMiddleware]:
    """Replace built-ins by name, retaining internal backend writes for offload.

    Call separately for the parent and each named child. Only the parent
    loads AGENTS.md; its existing course context remains available without
    instructions to rewrite shared files during student conversations.
    """
    result: list[AgentMiddleware] = [
        FilesystemMiddleware(backend=backend, tools=["ls", "read_file", "glob", "grep"]),
    ]
    if include_memory:
        result.append(MemoryMiddleware(
            backend=backend,
            sources=["./AGENTS.md"],
            add_cache_control=True,
            system_prompt="<course_context>\n{agent_memory}\n</course_context>",
        ))
    return result
