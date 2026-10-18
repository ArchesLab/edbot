"""Bound Ollama's embedding allocation without silently dropping input text."""
from langchain_ollama import OllamaEmbeddings

from edbot import model_config as config


class StrictOllamaEmbeddings(OllamaEmbeddings):
    """Add the strict input-length option missing from langchain-ollama 1.1.0."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._client is None:
            raise RuntimeError("Ollama sync client is not initialized")
        return self._client.embed(
            self.model,
            texts,
            truncate=False,
            dimensions=self.dimensions,
            options=self._default_params,
            keep_alive=self.keep_alive,
        )["embeddings"]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._async_client is None:
            raise RuntimeError("Ollama async client is not initialized")
        return (await self._async_client.embed(
            self.model,
            texts,
            truncate=False,
            dimensions=self.dimensions,
            options=self._default_params,
            keep_alive=self.keep_alive,
        ))["embeddings"]


def create_embedding_model() -> OllamaEmbeddings:
    return StrictOllamaEmbeddings(
        model=config.EMBEDDING_MODEL_NAME,
        num_ctx=config.EMBEDDING_CONTEXT_LENGTH,
    )
