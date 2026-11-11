"""The evals' checks and case file, without the LLM or the DB (the evals themselves cost
credits and run by hand: python -m scripts.run_evals)."""

import pytest

from app.evals.cases import load_cases
from app.evals.checks import ProductFacts, ToolCallObs, TurnObservation, evaluate, normalize

HEADPHONES = ProductFacts("MN-HDP-1", "Quanta Quiet 638", "Headphones", 179.94, True, 7)
OUT = ProductFacts("MN-HDP-2", "Nimbus Sound 691", "Headphones", 124.0, True, 0)


def _obs(**overrides) -> TurnObservation:
    data = {
        "response": {
            "type": "recommendation",
            "message": "Te recomiendo el Quanta Quiet 638: tiene cancelación de ruido.",
            "product_ids": ["MN-HDP-1"],
            "pending_confirmation": None,
            "comparison_ids": [],
            "checkout": None,
        },
        "tools": [
            ToolCallObs(
                "search_products",
                {"category": "Headphones", "max_price": 200, "use_cases": ["calls"]},
            )
        ],
        "products": {"MN-HDP-1": HEADPHONES, "MN-HDP-2": OUT},
        "cart": {},
        "orders_created": 0,
        "stop_reason": "goal_reached",
    } | overrides
    return TurnObservation(**data)


def _failed(expect, obs=None) -> list[str]:
    return [r.name for r in evaluate(expect, obs or _obs()) if not r.ok]


def test_a_good_turn_passes_everything():
    expect = {
        "tool_called": ["search_products"],
        "tool_args": {
            "search_products": {
                "category": "headphones",  # strings compare case-insensitively
                "max_price": {"lte": 200},
                "use_cases": {"contains": "calls"},
            }
        },
        "response_type": ["recommendation", "comparison"],
        "products": {
            "min": 1,
            "max": 3,
            "all_price_lte": 200,
            "all_active": True,
            "all_in_stock": True,
            "category": "Headphones",
            "include": ["quanta quiet 638"],
            "exclude": ["Nimbus Sound 691"],
        },
        "message_contains_any": ["CANCELACIÓN"],  # accents and case do not matter
        "message_not_contains": ["comprado"],
        "no_tool": ["add_to_cart"],
        "pending_confirmation": False,
        "checkout": False,
        "comparison": False,
        "cart": {"empty": True},
        "orders_created": 0,
        "stop_reason": "goal_reached",
    }
    assert _failed(expect) == []


@pytest.mark.parametrize(
    ("expect", "failed"),
    [
        ({"tool_called": ["get_product"]}, "tool_called"),
        ({"no_tool": ["search_products"]}, "no_tool"),
        ({"no_tools": True}, "no_tools"),
        (
            {"tool_args": {"search_products": {"max_price": {"lte": 100}}}},
            "tool_args:search_products",
        ),
        ({"tool_args": {"get_product": {"name": "x"}}}, "tool_args:get_product"),  # never called
        ({"response_type": "clarification"}, "response_type"),
        ({"products": {"all_price_lte": 100}}, "products.all_price_lte"),
        ({"products": {"min": 2}}, "products.min"),
        ({"message_contains_any": ["discontinuado"]}, "message_contains_any"),
        ({"message_not_contains": ["quanta"]}, "message_not_contains"),
        ({"pending_confirmation": True}, "pending_confirmation"),
        ({"cart": {"Vector Air 690": 1}}, "cart[Vector Air 690]"),
        ({"error_code": "PICKUP_UNAVAILABLE"}, "error_code"),
        ({"checkout": {"delivery_method": "PICKUP"}}, "checkout"),
    ],
)
def test_each_check_fails_when_it_should(expect, failed):
    assert _failed(expect) == [failed]


def test_products_without_stock_or_inactive_are_caught():
    response = _obs().response | {"product_ids": ["MN-HDP-2"]}
    assert _failed({"products": {"all_in_stock": True}}, _obs(response=response)) == [
        "products.all_in_stock"
    ]


def test_tool_errors_and_checkout_details():
    obs = _obs(
        tools=[ToolCallObs("start_checkout", {"delivery_method": "PICKUP"}, "PICKUP_UNAVAILABLE")],
        response=_obs().response
        | {
            "checkout": {
                "delivery_method": "PICKUP",
                "pickup_warehouse": {"warehouse_id": "WH-MAL-001"},
            }
        },
    )
    expect = {
        "error_code": ["PICKUP_UNAVAILABLE"],
        "checkout": {"delivery_method": "PICKUP", "pickup_warehouse_id": "WH-MAL-001"},
    }
    assert _failed(expect, obs) == []


def test_unknown_expectations_are_rejected():
    with pytest.raises(ValueError):
        evaluate({"respone_type": "info"}, _obs())  # typo
    with pytest.raises(ValueError):
        evaluate({"products": {"cheap": True}}, _obs())


def test_normalize():
    assert normalize("Cancelación ÁÉÍÓÚ") == "cancelacion aeiou"


def test_the_case_file_is_valid():
    cases = load_cases()
    assert len(cases) >= 25
    categories = {c.category for c in cases}
    assert {"recomendacion", "aclaracion", "carrito", "checkout", "alcance"} <= categories
    for case in cases:
        assert any(t.expect for t in case.turns), f"{case.id} checks nothing"
