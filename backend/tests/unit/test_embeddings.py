from types import SimpleNamespace

import httpx2
import openai
import pytest

from app.config import Settings
from app.retrieval.embeddings import (
    EmbeddingError,
    FakeEmbedder,
    OpenAIEmbedder,
    get_embedder,
)

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/embeddings")


class FakeClient:
    """Mimics client.embeddings.create. Always returns `dim`-sized vectors (whatever is
    requested) and the items in REVERSE order, on purpose."""

    def __init__(self, dim: int, error: Exception | None = None):
        self.dim = dim
        self.error = error
        self.calls: list[dict] = []
        self.embeddings = self

    def create(self, *, model, input, dimensions):
        self.calls.append({"model": model, "input": list(input), "dimensions": dimensions})
        if self.error:
            raise self.error
        data = [
            SimpleNamespace(index=i, embedding=[float(len(text))] * self.dim)
            for i, text in enumerate(input)
        ]
        return SimpleNamespace(
            data=list(reversed(data)), usage=SimpleNamespace(total_tokens=10 * len(input))
        )


def _embedder(client: FakeClient, batch_size: int = 2) -> OpenAIEmbedder:
    return OpenAIEmbedder(
        api_key="test", model="m", dim=client.dim, batch_size=batch_size, client=client
    )


def test_documents_are_sent_in_batches_and_keep_their_order():
    client = FakeClient(dim=3)
    result = _embedder(client, batch_size=2).embed_documents(["a", "bb", "ccc", "dddd", "e"])

    assert [len(call["input"]) for call in client.calls] == [2, 2, 1]
    assert [v[0] for v in result.vectors] == [1.0, 2.0, 3.0, 4.0, 1.0]
    assert result.tokens == 50
    assert all(call["dimensions"] == 3 and call["model"] == "m" for call in client.calls)


def test_embed_query_returns_one_vector():
    assert _embedder(FakeClient(dim=4)).embed_query("hola") == [4.0] * 4


def test_wrong_dimension_is_an_error():
    client = FakeClient(dim=3)
    embedder = OpenAIEmbedder(api_key="t", model="m", dim=5, client=client)
    with pytest.raises(EmbeddingError) as info:
        embedder.embed_query("x")
    assert info.value.code == "DIM_MISMATCH"


def test_invalid_key_is_not_retryable():
    error = openai.AuthenticationError(
        "bad key", response=httpx2.Response(401, request=REQUEST), body=None
    )
    with pytest.raises(EmbeddingError) as info:
        _embedder(FakeClient(dim=3, error=error)).embed_query("x")
    assert info.value.code == "AUTH"
    assert info.value.retryable is False


def test_rate_limit_after_sdk_retries_is_retryable():
    error = openai.RateLimitError(
        "slow down", response=httpx2.Response(429, request=REQUEST), body=None
    )
    with pytest.raises(EmbeddingError) as info:
        _embedder(FakeClient(dim=3, error=error)).embed_documents(["x"])
    assert info.value.code == "UNAVAILABLE"
    assert info.value.retryable is True


def test_connection_error_is_retryable():
    error = openai.APIConnectionError(request=REQUEST)
    with pytest.raises(EmbeddingError) as info:
        _embedder(FakeClient(dim=3, error=error)).embed_query("x")
    assert info.value.retryable is True


def test_fake_embedder_is_deterministic_and_normalized():
    fake = FakeEmbedder(dim=64)
    a = fake.embed_query("wireless headphones with ANC")
    assert a == fake.embed_query("wireless headphones with ANC")
    assert abs(sum(v * v for v in a) - 1.0) < 1e-9


def _settings(**overrides) -> Settings:
    return Settings(database_url="postgresql+psycopg://x@y/z", **overrides)


def test_no_api_key_means_no_embedder():
    assert get_embedder(_settings(openai_api_key=None)) is None
    assert get_embedder(_settings(openai_api_key="")) is None


def test_api_key_gives_openai_embedder():
    embedder = get_embedder(_settings(openai_api_key="sk-test", embedding_model="m"))
    assert isinstance(embedder, OpenAIEmbedder)
    assert embedder.model == "m"


def test_fake_provider_needs_no_key():
    embedder = get_embedder(_settings(embedding_provider="fake", openai_api_key=None))
    assert isinstance(embedder, FakeEmbedder)
