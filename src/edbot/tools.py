import requests
import uuid
from typing import Literal
from pathlib import Path
from deepagents.backends import FilesystemBackend
from langchain.tools import tool

from document_embedding import load_vector_store

ROOT_DIR = Path(__file__).parent # src/edbot
backend = FilesystemBackend(root_dir=ROOT_DIR)

# ollama serve
# ollama pull <model>
# ollama list
# ollama run <name-of-model>
@tool(parse_docstring=True)
def search_sources(query: str) -> list:
    """Search the local document index for content matching the query.

    Args:
        query: Search query.

    Returns:
        File paths where retrieved chunks were saved under /retrieved/.
    """
    vector_store = load_vector_store()
    retrieved_docs = vector_store.similarity_search(query, k=4) # list[Document]
    batch_id = uuid.uuid4().hex[:8]
    uploads: list[tuple[str, bytes]] = []
    saved_paths: list[str] = []

    for index, doc in enumerate(retrieved_docs, start=1):
        path = f"/retrieved/{batch_id}/chunk_{index}.md" # Saving retrieved chunks as a pathname /retrieved/batch_id so it doesn't need to save entire chunks (bloating context window & tokens)
        content = (
            f"# Source: {doc.metadata.get('source', 'unknown')}\n\n"
            f"{doc.page_content}"
        )
        uploads.append((path, content.encode("utf-8")))
        saved_paths.append(path)
    
    backend.upload_files(uploads)
    return (
        f"Saved {len(saved_paths)} reading chunks:\n"
        + "\n".join(saved_paths)
    )
