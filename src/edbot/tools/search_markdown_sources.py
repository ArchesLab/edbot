from langchain.tools import tool

from .markdown_embedding import SEBOOK_SUBDIR, load_sebook_store

SEBOOK_FOLDERS = [
    "architectural_styles", "designpatterns", "designprinciples", "development_practices",
    "process", "quality_attributes", "systems", "testing", "tools",
]

def _normalize_path_prefix(path_prefix: str) -> str:
    """Accept "SEBook/testing/", "/testing", "testing" etc. and return "testing"."""
    prefix = path_prefix.strip().strip("/")
    if prefix.lower().startswith(SEBOOK_SUBDIR.lower()):
        prefix = prefix[len(SEBOOK_SUBDIR):].lstrip("/")
    return prefix

def _format_chunks(docs: list) -> str:
    """Render retrieved chunks as one string, each with its source details for citing."""
    return "\n\n---\n\n".join(
        f"## Chunk {index}\n"
        f"Source: {doc.metadata.get('source', 'unknown')}\n"
        f"URL: {doc.metadata.get('url', 'unknown')}\n\n"
        f"{doc.page_content}" # already starts with its location, e.g. "SEBook > testing > Test Doubles > ..."
        for index, doc in enumerate(docs, start=1)
    )

@tool(parse_docstring=True)
def search_markdown_sources(query: str, path_prefix: str | None = None) -> str:
    """Search the SEBook (software engineering textbook) for content matching the query.

    Covers design patterns and principles, testing, software architecture, UML,
    requirements and user stories, development process, and tools (git, shell,
    Python, React, ...). Start without path_prefix; only add one to narrow a
    follow-up search once you know which part of the book is relevant, because a
    wrong prefix returns confident-looking results from the wrong topic.

    Args:
        query: Search query.
        path_prefix: Optional SEBook folder or page to search within. Folders:
            architectural_styles, designpatterns, designprinciples, development_practices,
            process, quality_attributes, systems, testing, tools. A folder also matches
            its overview page (e.g. "testing" matches testing.md and testing/...); a
            page path like "tools/git" searches only that page.

    Returns:
        The 4 most relevant chunks, each with its source path, URL, and location in the book.
    """
    vector_store = load_sebook_store()
    search_filter = None
    if path_prefix and (prefix := _normalize_path_prefix(path_prefix)):
        prefix = prefix.removesuffix(".md")
        search_filter = lambda doc: (
            doc.metadata["path"].startswith(prefix + "/") or doc.metadata["path"] == prefix + ".md"
        )
    retrieved_docs = vector_store.similarity_search(query, k=4, filter=search_filter)

    if not retrieved_docs:
        return (
            f"No SEBook content found under path_prefix '{path_prefix}'. "
            f"Valid folders: {', '.join(SEBOOK_FOLDERS)}. Retry without path_prefix."
        )
    return _format_chunks(retrieved_docs)