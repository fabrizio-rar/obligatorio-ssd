"""Embedding index against a real Postgres + pgvector, with FakeEmbedder (no OpenAI)."""

import re

import pytest
from sqlalchemy import func, select, update

from app.ingest.pipeline import ingest_records
from app.models import Product, ProductEmbedding
from app.models.retrieval import EMBEDDING_COLUMN_DIM
from app.retrieval.embeddings import EmbeddingBatch, EmbeddingError, FakeEmbedder
from app.retrieval.indexer import index_products, nearest_products
from tests.factories import make_records

pytestmark = pytest.mark.integration


def _fake(model: str = "fake-embedder") -> FakeEmbedder:
    return FakeEmbedder(dim=EMBEDDING_COLUMN_DIM, model=model)


def _count(session) -> int:
    return session.scalar(select(func.count()).select_from(ProductEmbedding))


def test_full_catalog_is_indexed_including_inactive(session, dataset_records):
    ingest_records(session, dataset_records, "dataset")
    report = index_products(session, _fake())

    assert report.products == report.embedded == 360
    assert _count(session) == 360
    inactive_indexed = session.scalar(
        select(func.count())
        .select_from(ProductEmbedding)
        .join(Product, Product.id == ProductEmbedding.product_id)
        .where(Product.active.is_(False))
    )
    assert inactive_indexed == 17


def test_stored_content_has_no_dynamic_data(session, dataset_records):
    ingest_records(session, dataset_records, "dataset")
    index_products(session, _fake())

    # Whole words: "operating system" must not count as "rating"
    forbidden = re.compile(r"\b(price|prices|stock|rating|usd)\b", re.IGNORECASE)
    for content in session.scalars(select(ProductEmbedding.content)):
        assert not forbidden.search(content), content


def test_second_run_embeds_nothing(session):
    ingest_records(session, make_records(), "mini")
    index_products(session, _fake())

    embedder = _fake()
    report = index_products(session, embedder)
    assert report.embedded == 0
    assert report.unchanged == 2
    assert embedder.calls == 0  # no API calls at all


def test_changed_product_is_reembedded(session):
    ingest_records(session, make_records(), "mini")
    index_products(session, _fake())

    session.execute(
        update(Product).where(Product.id == "MN-HDP-0001").values(description="Brand new text")
    )
    session.commit()
    embedder = _fake()
    report = index_products(session, embedder)

    assert report.embedded == 1
    assert embedder.calls == 1
    content = session.get(ProductEmbedding, "MN-HDP-0001").content
    assert "Description: Brand new text" in content


def test_model_change_reembeds_everything(session):
    ingest_records(session, make_records(), "mini")
    index_products(session, _fake("model-a"))

    report = index_products(session, _fake("model-b"))
    assert report.embedded == 2
    session.expire_all()
    assert set(session.scalars(select(ProductEmbedding.model))) == {"model-b"}


def test_force_reembeds_everything(session):
    ingest_records(session, make_records(), "mini")
    index_products(session, _fake())
    assert index_products(session, _fake(), force=True).embedded == 2


def test_wrong_dimension_fails_before_calling_the_api(session):
    ingest_records(session, make_records(), "mini")
    embedder = FakeEmbedder(dim=8)
    with pytest.raises(EmbeddingError) as info:
        index_products(session, embedder)
    assert info.value.code == "DIM_MISMATCH"
    assert embedder.calls == 0
    assert _count(session) == 0


def test_failure_halfway_keeps_finished_batches(session):
    ingest_records(session, make_records(), "mini")

    class FailsOnSecondBatch(FakeEmbedder):
        def embed_documents(self, texts: list[str]) -> EmbeddingBatch:
            if self.calls >= 1:
                raise EmbeddingError("UNAVAILABLE", "OpenAI down", retryable=True)
            return super().embed_documents(texts)

    with pytest.raises(EmbeddingError):
        index_products(session, FailsOnSecondBatch(dim=EMBEDDING_COLUMN_DIM), batch_size=1)
    assert _count(session) == 1

    # Next run only does the missing one
    report = index_products(session, _fake())
    assert (report.embedded, report.unchanged) == (1, 1)


def test_cost_is_estimated_from_tokens(session):
    ingest_records(session, make_records(), "mini")

    class Billed(FakeEmbedder):
        def embed_documents(self, texts: list[str]) -> EmbeddingBatch:
            return EmbeddingBatch(super().embed_documents(texts).vectors, tokens=500_000)

    report = index_products(session, Billed(dim=EMBEDDING_COLUMN_DIM), usd_per_1m_tokens=0.02)
    assert report.tokens == 500_000
    assert report.estimated_cost_usd == pytest.approx(0.01)


def test_nearest_products_uses_cosine_distance(session):
    ingest_records(session, make_records(), "mini")
    embedder = _fake()
    index_products(session, embedder)

    results = nearest_products(session, embedder, "headphones calls video calls anc", limit=2)
    assert [r[0] for r in results] == ["MN-HDP-0001", "MN-MOU-0001"]
    assert results[0][3] < results[1][3]
