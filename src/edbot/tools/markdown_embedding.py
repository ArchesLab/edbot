import json
import logging
import os
import re
import subprocess
import time
from functools import lru_cache
from pathlib import Path

import yaml
from langchain_core.documents import Document
from langchain_core.load import dumpd
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

REPO_URL = "https://github.com/tobiasduerschmid/tobiasduerschmid.github.io.git"
REPO_BRANCH = "master"
SEBOOK_SUBDIR = "SEBook"
# Interactive tutorial, quiz, and flashcard content that the SEBook pages reference
DATA_SUBDIRS = ["_data/tutorials", "_data/quizzes", "_data/flashcards"]
SPARSE_PATHS = [SEBOOK_SUBDIR, *DATA_SUBDIRS] # tracks ony these directories to clone and fetch from

ROOT_DIR = Path(__file__).parent.parent.parent # src/
CACHE_DIR = ROOT_DIR / ".cache" / "sebook" 
CLONE_DIR = CACHE_DIR / "repo"
STORE_PATH = CACHE_DIR / "store.json" # dumped InMemoryVectorStore -> saving vector store as JSON from RAM
FINGERPRINT_PATH = CACHE_DIR / "fingerprint.json" # what STORE_PATH was built from

# Embedding settings: changing any of these invalidates the saved store
EMBEDDING_MODEL = "qwen3-embedding:8b"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
# Bump when the loading/cleaning/splitting code changes in a way that alters the chunks
PIPELINE_VERSION = 1

MIN_BODY_CHARS = 200 # pages with less text than this are stubs (course pages, tutorial launchers, ...)
MIN_CHUNK_CHARS = 50 # smaller chunks are leftovers like "---" separators or lone "**Liabilities**" lines
MAX_HEADER_LEVEL = 4 # split on # through ####; deeper headers stay inside their section
EMBED_BATCH_SIZE = 64 # chunks sent to Ollama per request, so progress can be logged

def _git(*args: str) -> str: # git runs from CLONE_DIR (/repo) directory
    result = subprocess.run(
        ["git", "-C", str(CLONE_DIR), *args],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip() # prints the captured output

def sync_repo() -> dict[str, str]:
    """Sparse, shallow-clone (or update) only SPARSE_PATHS from the repo.

    Returns:
        Tree SHA of each path in SPARSE_PATHS, which changes only when its contents change.
    """
    if not (CLONE_DIR / ".git").exists(): # if this is the first copy
        CACHE_DIR.mkdir(parents=True, exist_ok=True) # make the cache directory (/.cache/sebook)
        subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
             "--branch", REPO_BRANCH, REPO_URL, str(CLONE_DIR)],
            check=True, capture_output=True, text=True,
        ) # shallow copy entire repo, don't capture blobs
    else:
        try: # fetch latest commits and reset
            _git("fetch", "--depth", "1", "origin", REPO_BRANCH)
            _git("reset", "--hard", "FETCH_HEAD")
        except subprocess.CalledProcessError as e:
            # Offline or GitHub unreachable: keep using the existing clone
            logger.warning("Could not update %s, using cached copy: %s", SEBOOK_SUBDIR, e.stderr.strip())
    # Re-applied every run so an existing clone picks up changes to SPARSE_PATHS
    _git("sparse-checkout", "set", *SPARSE_PATHS)
    return {path: _git("rev-parse", f"HEAD:{path}") for path in SPARSE_PATHS} # tree SHAs to track for changes

def build_fingerprint(tree_shas: dict[str, str]) -> dict:
    """Everything the saved store depends on. Only SEBook is embedded, so _data SHAs are left out."""
    return {
        "sebook_sha": tree_shas[SEBOOK_SUBDIR],
        "embedding_model": EMBEDDING_MODEL,
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "pipeline_version": PIPELINE_VERSION,
    }

def store_is_current(fingerprint: dict) -> bool:
    """True if a saved store exists and was built from exactly this fingerprint."""
    if not STORE_PATH.exists() or not FINGERPRINT_PATH.exists():
        return False
    try:
        saved = json.loads(FINGERPRINT_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return False # unreadable fingerprint: treat as stale and rebuild
    return saved == fingerprint

def save_fingerprint(fingerprint: dict) -> None:
    """Record what the store was built from. Call only after the store itself is saved."""
    # Write to a temp file then rename, so a crash mid-write never leaves a half-written file
    tmp_path = FINGERPRINT_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(fingerprint, indent=2))
    os.replace(tmp_path, FINGERPRINT_PATH) # renames tmp to actual path, replacing old if existed

# For parsing the SEBook markdown files, getting rid of titles and removing title-only markdowns
FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.S)
# Fenced code blocks (``` or ~~~), including mermaid/plantuml diagrams: left untouched by cleanup
CODE_FENCE_RE = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.S | re.M)
INLINE_CODE_RE = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)") # `code` or ``code with ` inside``
RAW_BLOCK_RE = re.compile(r"\{%-?\s*raw\s*-?%\}(.*?)\{%-?\s*endraw\s*-?%\}", re.S)
CITE_RE = re.compile(r"\{%-?\s*cite\s+([^%]+?)\s*-?%\}")
LIQUID_RE = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.S)
HTML_DROP_RE = re.compile(r"<!--.*?-->|<(script|style)\b.*?</\1>", re.S | re.I) # removed with their contents
HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>") # tag removed, inner text kept

def _clean_prose(text: str) -> str:
    """Clean Liquid and HTML out of text that is NOT inside a code fence or raw block."""
    text = CITE_RE.sub(lambda m: f"[{m.group(1)}]", text) # {% cite Key %} -> [Key]
    text = LIQUID_RE.sub("", text) # every other {% ... %} and {{ ... }}
    text = HTML_DROP_RE.sub("", text)
    text = HTML_TAG_RE.sub("", text)
    return text

def clean_markdown(body: str) -> str:
    """Strip Jekyll Liquid and HTML from a page body, leaving code fences and raw blocks as-is."""
    # Pull out the parts that must not be cleaned, swapping in placeholders
    protected: list[str] = []
    def protect(text: str) -> str:
        protected.append(text)
        return f"\x00{len(protected) - 1}\x00"
    body = RAW_BLOCK_RE.sub(lambda m: protect(m.group(1)), body) # {% raw %} contents are literal text
    body = CODE_FENCE_RE.sub(lambda m: protect(m.group(0)), body)
    body = INLINE_CODE_RE.sub(lambda m: protect(m.group(0)), body) # e.g. `List<String>`, `<div>`

    body = _clean_prose(body)

    # Loop because protected text can itself hold a placeholder (a raw block inside inline code)
    while "\x00" in body:
        body = re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], body)
    return re.sub(r"\n{3,}", "\n\n", body).strip() # collapse blank lines left behind by removed tags

def load_sebook_docs() -> list[Document]:
    """Load every non-stub SEBook page as a cleaned Document, one per file."""
    sebook_dir = CLONE_DIR / SEBOOK_SUBDIR
    commit_sha = _git("rev-parse", "HEAD")
    docs: list[Document] = []
    for file_path in sorted(sebook_dir.rglob("*.md")):
        text = file_path.read_text(encoding="utf-8")
        front_matter = {}
        if match := FRONT_MATTER_RE.match(text):
            front_matter = yaml.safe_load(match.group(1)) or {}
            text = text[match.end():]
        body = clean_markdown(text)
        if len(body) < MIN_BODY_CHARS:
            continue

        rel_path = file_path.relative_to(sebook_dir).as_posix() # e.g. "testing/tdd.md"
        docs.append(Document(page_content=body, metadata={
            "source": f"{SEBOOK_SUBDIR}/{rel_path}",
            "path": rel_path,
            "dirs": list(Path(rel_path).parent.parts), # e.g. ["testing"]; [] for top-level pages
            "title": front_matter.get("title", file_path.stem),
            "url": f"{REPO_URL.removesuffix('.git')}/blob/{commit_sha}/{SEBOOK_SUBDIR}/{rel_path}",
        }))
    return docs

HEADER_RE = re.compile(rf"^(#{{1,{MAX_HEADER_LEVEL}}})\s+(.+?)\s*#*\s*$")
FENCE_LINE_RE = re.compile(r"^\s*(```|~~~)")

def split_by_headers(text: str) -> list[tuple[list[str], str]]:
    """Split markdown into (header path, section text) pairs.

    LangChain's MarkdownHeaderTextSplitter strips every line, which flattens the
    indentation of code blocks, so this keeps lines exactly as written instead.
    Header lines themselves are left out of the section text.
    """
    sections: list[tuple[list[str], str]] = []
    header_path: list[str] = []
    lines: list[str] = []
    open_fence = None # "```" or "~~~" while inside a code block, so "# comment" lines aren't headers

    def flush():
        if content := "\n".join(lines).strip():
            sections.append((list(header_path), content))
        lines.clear()

    for line in text.splitlines():
        if fence := FENCE_LINE_RE.match(line):
            if open_fence is None:
                open_fence = fence.group(1)
            elif fence.group(1) == open_fence:
                open_fence = None
        elif open_fence is None and (header := HEADER_RE.match(line)):
            flush()
            level = len(header.group(1))
            header_path[level - 1:] = [header.group(2)] # replace this level, drop deeper ones
            continue
        lines.append(line)
    flush()
    return sections

def split_sebook_docs(docs: list[Document]) -> list[Document]:
    """Split each page by markdown headers, then split long sections to CHUNK_SIZE.

    Each chunk keeps its page metadata plus "headers": the header path it sits under.
    """
    size_splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    chunks: list[Document] = []
    for doc in docs:
        for headers, section in split_by_headers(doc.page_content):
            for piece in size_splitter.split_text(section):
                if len(piece) < MIN_CHUNK_CHARS:
                    continue
                chunks.append(Document(page_content=piece, metadata={**doc.metadata, "headers": headers}))
    return chunks

def add_location_prefix(chunks: list[Document]) -> list[Document]:
    """Start each chunk's text with where it sits, e.g. "SEBook > testing > Test Doubles > Why test doubles exist".

    Only page_content is embedded (metadata is not), so this is what lets the vector
    capture the chunk's topic even when the paragraph itself never names it.
    """
    for chunk in chunks:
        location = " > ".join([SEBOOK_SUBDIR, *chunk.metadata["dirs"], chunk.metadata["title"], *chunk.metadata["headers"]])
        chunk.page_content = f"{location}\n\n{chunk.page_content}"
    return chunks

def build_store(chunks: list[Document], embeddings: OllamaEmbeddings) -> InMemoryVectorStore:
    """Embed every chunk into a new in-memory vector store."""
    vector_store = InMemoryVectorStore(embeddings)
    start = time.monotonic()
    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        vector_store.add_documents(chunks[i:i + EMBED_BATCH_SIZE])
        done = min(i + EMBED_BATCH_SIZE, len(chunks))
        logger.info("Embedded %d/%d SEBook chunks (%.0fs)", done, len(chunks), time.monotonic() - start)
    return vector_store

def save_store(vector_store: InMemoryVectorStore) -> None:
    """Write the store to STORE_PATH via a temp file, so a crash mid-write never leaves a half-written store."""
    # Same format as vector_store.dump(), but without indent=2, which puts every float on its own line
    tmp_path = STORE_PATH.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(dumpd(vector_store.store), f)
    os.replace(tmp_path, STORE_PATH)

@lru_cache(maxsize=1) # calls to this function with same argument returns cached results without rerunning
def load_sebook_store() -> InMemoryVectorStore:
    """Return the SEBook vector store, re-embedding only if SEBook or the embedding settings changed.

    Cached, so the work (git sync, then load or rebuild) happens once per process.
    """
    fingerprint = build_fingerprint(sync_repo())
    embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL)

    if store_is_current(fingerprint):
        try:
            vector_store = InMemoryVectorStore.load(str(STORE_PATH), embeddings)
            logger.info("Loaded saved SEBook store (%d chunks)", len(vector_store.store))
            return vector_store
        except (OSError, ValueError) as e: # ValueError covers corrupt JSON
            logger.warning("Saved SEBook store unreadable, rebuilding: %s", e)

    logger.info("SEBook or embedding settings changed, rebuilding store")
    chunks = add_location_prefix(split_sebook_docs(load_sebook_docs()))
    vector_store = build_store(chunks, embeddings)
    save_store(vector_store)
    save_fingerprint(fingerprint) # last, so it only ever describes a fully saved store
    return vector_store
