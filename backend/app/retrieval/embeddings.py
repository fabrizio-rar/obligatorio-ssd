"""Embedders behind one interface (docs/PLAN.md §9.3).

- OpenAIEmbedder: the real one (OpenAI embeddings API).
- FakeEmbedder: deterministic vectors for tests. Never calls the network.

The rest of the app only sees `Embedder`; switching providers (e.g. a local model)
means writing another class, not touching the indexer or the search.
"""

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any, Protocol

import openai

from app.config import Settings


class EmbeddingError(Exception):
    """Embedding failed. `retryable` = False for errors that retrying cannot fix."""

    def __init__(self, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    tokens: int  # billed input tokens (0 for the fake)


class Embedder(Protocol):
    model: str
    dim: int

    def embed_documents(self, texts: list[str]) -> EmbeddingBatch: ...

    def embed_query(self, text: str) -> list[float]: ...


class OpenAIEmbedder:
    """Retries on 429 / 5xx / timeout are done by the SDK (max_retries, with backoff)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        dim: int,
        batch_size: int = 100,
        timeout: float = 60,
        max_retries: int = 2,
        client: Any = None,  # injectable for tests
    ) -> None:
        self.model = model
        self.dim = dim
        self.batch_size = batch_size
        self._client = client or openai.OpenAI(
            api_key=api_key, timeout=timeout, max_retries=max_retries
        )

    def embed_documents(self, texts: list[str]) -> EmbeddingBatch:
        vectors: list[list[float]] = []
        tokens = 0
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            response = self._create(batch)
            # The API returns one item per input with its index; keep the input order
            items = sorted(response.data, key=lambda item: item.index)
            vectors.extend(self._checked(item.embedding) for item in items)
            tokens += response.usage.total_tokens
        return EmbeddingBatch(vectors=vectors, tokens=tokens)

    def embed_query(self, text: str) -> list[float]:
        response = self._create([text])
        return self._checked(response.data[0].embedding)

    def _create(self, texts: list[str]) -> Any:
        try:
            return self._client.embeddings.create(
                model=self.model, input=texts, dimensions=self.dim
            )
        except openai.AuthenticationError as error:
            raise EmbeddingError(
                "AUTH", "OpenAI rejected the API key (401): check OPENAI_API_KEY", False
            ) from error
        except openai.PermissionDeniedError as error:
            raise EmbeddingError(
                "FORBIDDEN", f"No access to embedding model {self.model} (403)", False
            ) from error
        except openai.BadRequestError as error:
            raise EmbeddingError(
                "BAD_REQUEST", f"OpenAI rejected the request: {error}", False
            ) from error
        except (
            openai.RateLimitError,
            openai.APIConnectionError,  # includes timeouts
            openai.InternalServerError,
        ) as error:
            # The SDK already retried with backoff: give up for now, can be retried later
            raise EmbeddingError(
                "UNAVAILABLE", f"OpenAI embeddings unavailable: {error}", True
            ) from error

    def _checked(self, vector: list[float]) -> list[float]:
        if len(vector) != self.dim:
            raise EmbeddingError(
                "DIM_MISMATCH", f"expected {self.dim} dimensions, got {len(vector)}", False
            )
        return vector


class FakeEmbedder:
    """Bag of hashed words, L2-normalized. Texts that share words get closer vectors,
    which is enough to test the index and nearest-neighbor queries without an API."""

    def __init__(self, dim: int, model: str = "fake-embedder") -> None:
        self.model = model
        self.dim = dim
        self.calls = 0  # number of texts embedded (tests use it to check caching)

    def embed_documents(self, texts: list[str]) -> EmbeddingBatch:
        self.calls += len(texts)
        return EmbeddingBatch(vectors=[self._vector(t) for t in texts], tokens=0)

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for word in re.findall(r"\w+", text.lower()):
            bucket = int(hashlib.sha256(word.encode()).hexdigest(), 16) % self.dim
            vector[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


def get_embedder(settings: Settings) -> Embedder | None:
    """None when embeddings are not configured (no API key): callers fall back."""
    if settings.embedding_provider == "fake":
        return FakeEmbedder(dim=settings.embedding_dim)
    if not settings.openai_configured:
        return None
    return OpenAIEmbedder(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.embedding_model,
        dim=settings.embedding_dim,
        batch_size=settings.embedding_batch_size,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
