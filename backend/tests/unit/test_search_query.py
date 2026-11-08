from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.retrieval.search import SearchQuery, rrf
from app.retrieval.vocabulary import SUBCATEGORIES, AvoidCase, Category, UseCase


def test_valid_query_with_all_filters():
    q = SearchQuery(
        query="  comfortable headphones  ",
        category="Headphones",
        subcategory="Over-Ear",
        min_price=50,
        max_price=200,
        use_cases=["calls"],
        exclude_use_cases=["air travel"],
    )
    assert q.query == "comfortable headphones"
    assert q.category is Category("Headphones")
    assert q.max_price == Decimal("200")
    assert q.use_cases == [UseCase("calls")]
    assert q.in_stock_only is True
    assert q.limit == 5


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": "   "},
        {"query": "x", "category": "Auriculares"},  # only dataset values (English)
        {"query": "x", "use_cases": ["videollamadas"]},
        {"query": "x", "use_cases": ["air travel"]},  # avoid-case, not a use case
        {"query": "x", "exclude_use_cases": ["calls"]},  # use case, not an avoid-case
        {"query": "x", "subcategory": "Gaming"},  # ambiguous without category
        {"query": "x", "category": "Headphones", "subcategory": "Gaming"},
        {"query": "x", "min_price": 300, "max_price": 100},
        {"query": "x", "max_price": -1},
        {"query": "x", "limit": 0},
        {"query": "x", "limit": 11},
        {"query": "x", "use_cases": ["calls"] * 6},
    ],
)
def test_invalid_queries_are_rejected(kwargs):
    with pytest.raises(ValidationError):
        SearchQuery(**kwargs)


def test_blank_brand_and_subcategory_become_none():
    q = SearchQuery(query="x", brand="  ", subcategory="", category="Mice")
    assert q.brand is None and q.subcategory is None


def test_vocabulary_is_loaded_from_json():
    assert len(Category) == 12
    assert len(UseCase) == 34
    assert len(AvoidCase) == 5
    assert SUBCATEGORIES["Headphones"] == ["Over-Ear", "On-Ear", "True Wireless"]
    assert sum(len(subs) for subs in SUBCATEGORIES.values()) == 37


def test_rrf_rewards_items_in_both_rankings():
    scores = rrf([["a", "b", "c"], ["c", "d"]], k=60)
    # c is 3rd in one list and 1st in the other: beats a, which is 1st in only one
    assert scores == pytest.approx({"a": 1 / 61, "b": 1 / 62, "c": 1 / 63 + 1 / 61, "d": 1 / 62})
    assert max(scores, key=scores.get) == "c"


def test_rrf_single_ranking_keeps_order():
    scores = rrf([["x", "y", "z"]])
    assert sorted(scores, key=scores.get, reverse=True) == ["x", "y", "z"]
