"""search() against the real dataset in Postgres, indexed with FakeEmbedder (no OpenAI).

The catalog is loaded and indexed once for the whole module; tests only read it
(the few that change something restore it).
"""

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.domain.errors import DomainError
from app.models import Category as CategoryModel
from app.models import Price, Product, ProductEmbedding, Subcategory
from app.models.retrieval import EMBEDDING_COLUMN_DIM
from app.retrieval.embeddings import EmbeddingError, FakeEmbedder
from app.retrieval.indexer import index_products
from app.retrieval.search import SearchQuery, search
from app.retrieval.vocabulary import SUBCATEGORIES, AvoidCase, UseCase, use_case_categories

pytestmark = pytest.mark.integration

EMBEDDER = FakeEmbedder(dim=EMBEDDING_COLUMN_DIM)


@pytest.fixture(scope="module")
def db(catalog_db) -> Session:
    return catalog_db


def _search(db: Session, embedder=EMBEDDER, **kwargs):
    return search(db, SearchQuery(**kwargs), embedder)


def _product(db: Session, product_id: str) -> Product:
    return db.get(Product, product_id)


# --- Vocabulary JSON == dataset ---------------------------------------------------------


def test_categories_json_matches_db(db):
    rows = db.execute(
        select(CategoryModel.name, Subcategory.name).join(
            Subcategory, Subcategory.category_id == CategoryModel.id
        )
    ).all()
    from_db: dict[str, set[str]] = {}
    for category, subcategory in rows:
        from_db.setdefault(category, set()).add(subcategory)
    assert from_db == {cat: set(subs) for cat, subs in SUBCATEGORIES.items()}


def test_use_cases_json_matches_db(db):
    recommended = set(db.scalars(text("SELECT DISTINCT unnest(recommended_for) FROM products")))
    avoid = set(db.scalars(text("SELECT DISTINCT unnest(not_recommended_for) FROM products")))
    assert recommended == {u.value for u in UseCase}
    assert avoid == {a.value for a in AvoidCase}


def test_use_case_categories_tells_calls_from_video_calls(db):
    mapping = use_case_categories(db)
    assert "Headphones" in mapping["calls"]
    assert "Headphones" not in mapping["video calls"]


# --- Hard filters -----------------------------------------------------------------------


def test_category_and_price_filters(db):
    result = _search(db, query="headphones", category="Headphones", max_price=200, limit=10)

    assert result.semantic_used is True
    assert result.total_candidates == 23  # active, in stock, <= 200 (checked in the DB)
    assert len(result.hits) == 10
    assert all(h.category == "Headphones" and h.current_price <= 200 for h in result.hits)


def test_subcategory_brand_and_min_price(db):
    result = _search(
        db,
        query="monitor",
        category="Monitors",
        subcategory="Gaming",
        brand="flux",  # case-insensitive
        min_price=100,
        limit=10,
    )
    assert result.hits
    for hit in result.hits:
        assert (hit.subcategory, hit.brand) == ("Gaming", "Flux")
        assert hit.current_price >= 100


def test_inactive_products_are_never_returned(db):
    inactive = db.scalars(select(Product).where(Product.active.is_(False))).all()
    assert len(inactive) == 17
    for product in inactive[:5]:
        # Searching by its exact name: it would be the nearest vector, but must not appear
        result = _search(db, query=product.name, in_stock_only=False, limit=10)
        assert product.id not in {h.product_id for h in result.hits}


def test_out_of_stock_only_when_asked(db):
    nimbus = db.scalar(select(Product).where(Product.name == "Nimbus Sound 691"))
    in_stock = _search(db, query="Nimbus Sound 691", category="Headphones", limit=10)
    assert nimbus.id not in {h.product_id for h in in_stock.hits}

    with_out = _search(db, query="Nimbus Sound 691", in_stock_only=False)
    assert with_out.hits[0].product_id == nimbus.id
    assert with_out.hits[0].available == 0
    assert with_out.hits[0].stock_status == "Out of stock"


def test_exclude_use_cases(db):
    result = _search(
        db, query="headphones for travel", category="Headphones", exclude_use_cases=["air travel"]
    )
    assert result.hits
    for hit in result.hits:
        assert "air travel" not in _product(db, hit.product_id).not_recommended_for


def test_unknown_brand_is_a_typed_error(db):
    with pytest.raises(DomainError) as info:
        _search(db, query="mouse", brand="Logitech")
    assert info.value.code == "UNKNOWN_BRAND"
    assert "Flux" in info.value.details["valid_brands"]
    assert info.value.to_dict()["ok"] is False


def test_impossible_filters_return_empty_not_error(db):
    result = _search(db, query="headphones", category="Headphones", max_price=5)
    assert result.hits == []
    assert result.total_candidates == 0


# --- Use cases: ranking signal, not filter -------------------------------------------------


def test_requested_use_case_boosts_matching_products(db):
    result = _search(db, query="headphones", category="Headphones", use_cases=["sports"], limit=6)
    sports = {
        p.id
        for p in db.scalars(
            select(Product)
            .join(Subcategory)
            .join(CategoryModel)
            .where(CategoryModel.name == "Headphones", Product.active.is_(True))
            .where(Product.recommended_for.contains(["sports"]))
        )
    }
    sports_in_stock = {h.product_id for h in result.hits if "sports" in h.matched_use_cases}
    assert sports_in_stock  # boosted into the top 6
    assert sports_in_stock <= sports


def test_wrong_use_case_does_not_empty_the_result(db):
    # Headphones use "calls", not "video calls": this was the 0-results case
    result = _search(
        db, query="headphones for video calls", category="Headphones", use_cases=["video calls"]
    )
    assert len(result.hits) == 5
    assert all(h.matched_use_cases == [] for h in result.hits)


# --- Data comes from the DB, fallbacks -------------------------------------------------------


def test_price_comes_from_the_db_not_the_index(db):
    top = _search(db, query="headphones", category="Headphones").hits[0]
    original = db.get(Price, top.product_id).current_price
    db.execute(update(Price).where(Price.product_id == top.product_id).values(current_price=1))
    db.commit()
    try:
        again = _search(db, query="headphones", category="Headphones", limit=10)
        hit = next(h for h in again.hits if h.product_id == top.product_id)
        assert hit.current_price == 1
    finally:
        db.execute(
            update(Price).where(Price.product_id == top.product_id).values(current_price=original)
        )
        db.commit()


def test_embedding_failure_falls_back_to_use_cases_and_rating(db):
    class Broken(FakeEmbedder):
        def embed_query(self, text: str) -> list[float]:
            raise EmbeddingError("UNAVAILABLE", "OpenAI down", retryable=True)

    result = _search(
        db,
        embedder=Broken(dim=EMBEDDING_COLUMN_DIM),
        query="headphones",
        category="Headphones",
        use_cases=["calls"],
    )
    assert result.semantic_used is False
    assert len(result.hits) == 5
    assert all("calls" in h.matched_use_cases for h in result.hits)


def test_without_embedder_ranks_by_rating(db):
    result = _search(db, embedder=None, query="anything", category="Mice", limit=10)
    assert result.semantic_used is False
    ratings = [(h.rating, h.review_count) for h in result.hits]
    assert ratings == sorted(ratings, reverse=True)


def test_product_without_embedding_is_not_hidden(db):
    filters = {"query": "gaming mouse", "category": "Mice", "subcategory": "Gaming", "limit": 10}
    before = _search(db, **filters)
    assert 1 < before.total_candidates <= 10  # small enough to see every candidate
    victim = before.hits[0].product_id
    db.execute(ProductEmbedding.__table__.delete().where(ProductEmbedding.product_id == victim))
    db.commit()
    try:
        after = _search(db, **filters)
        ids = [h.product_id for h in after.hits]
        assert after.total_candidates == before.total_candidates
        assert victim in ids  # still there...
        assert ids[0] != victim  # ...but no longer first: it has no semantic score
    finally:
        index_products(db, EMBEDDER)


# --- Nothing within the budget -----------------------------------------------------------------


def _cheapest_in_stock(db: Session, category: str, n: int = 3) -> list[str]:
    return list(
        db.scalars(
            text(
                "SELECT p.id FROM products p JOIN prices pr ON pr.product_id = p.id "
                "JOIN product_availability a ON a.product_id = p.id "
                "JOIN subcategories s ON s.id = p.subcategory_id "
                "JOIN categories c ON c.id = s.category_id "
                "WHERE p.active AND a.available > 0 AND c.name = :cat "
                "ORDER BY pr.current_price, p.id LIMIT :n"
            ),
            {"cat": category, "n": n},
        )
    )


def test_nothing_within_budget_returns_the_cheapest_by_price(db):
    result = _search(db, query="headphones", category="Headphones", max_price=20)
    assert result.hits == [] and result.total_candidates == 0
    cheapest = result.cheapest_above_budget
    assert [h.product_id for h in cheapest] == _cheapest_in_stock(db, "Headphones")
    prices = [h.current_price for h in cheapest]
    assert prices == sorted(prices) and prices[0] > 20
    assert all(h.available > 0 for h in cheapest)  # the other filters still apply


def test_cheapest_above_budget_keeps_the_other_filters(db):
    result = _search(
        db, query="gaming laptop", category="Laptops", subcategory="Gaming", max_price=400
    )
    assert result.cheapest_above_budget
    assert {h.subcategory for h in result.cheapest_above_budget} == {"Gaming"}


def test_no_cheapest_list_when_there_are_results_or_no_budget(db):
    within = _search(db, query="headphones", category="Headphones", max_price=200)
    assert within.hits and within.cheapest_above_budget == []
    # No budget: an empty result is not about the price, nothing to suggest
    none = _search(db, query="headphones", category="Headphones", min_price=5000)
    assert none.hits == [] and none.cheapest_above_budget == []
