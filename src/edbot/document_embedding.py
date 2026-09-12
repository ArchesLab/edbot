from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_ollama import OllamaEmbeddings # https://docs.langchain.com/oss/python/integrations/embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from pathlib import Path

ROOT_DIR = Path(__file__).parent # src/edbot
DOC_PATHS = [ ROOT_DIR / "readings" ]

def load_langchain_docs(doc_paths: list[str] | None = None) -> list[Document]:
    """Fetch PDF files in ./readings as Documents"""
    docs: list[Document] = []
    for dir_path in doc_paths:
        for path in dir_path.glob("*.pdf"):
            # Read the PDF
            reader = PdfReader(path)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            docs.append(Document(page_content=text, metadata={"source": str(path)}))
    print(f"Loaded {len(docs)} documentation pages")
    return docs

def split_docs(docs: list[Document]):
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    all_splits = text_splitter.split_documents(docs)
    print(f"Split documentation into {len(all_splits)} chunks.")
    return all_splits

def embed_chunks(all_splits: list[Document]):
    # https://docs.langchain.com/oss/python/integrations/embeddings/ollama
    embeddings = OllamaEmbeddings(model="qwen3-embedding:4b")
    vector_store = InMemoryVectorStore(embeddings)
    vector_store.add_documents(documents=all_splits)
    print(f"Indexed {len(all_splits)} chunks.")
    return vector_store

def load_vector_store():
    docs = load_langchain_docs(DOC_PATHS)
    all_splits = split_docs(docs)
    return embed_chunks(all_splits)
