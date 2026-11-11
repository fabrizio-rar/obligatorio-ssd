"""What an eval case expects, checked against what really happened in a turn. Pure: the
runner gathers the observation (response, tool calls, products, cart, orders) and this module
only compares, so it is tested without the LLM or the DB (tests/unit/test_eval_checks.py)."""

import unicodedata
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCallObs:
    name: str
    arguments: dict[str, Any] | None
    error_code: str | None = None  # the tool returned {"ok": false, "error": {...}}


@dataclass
class ProductFacts:
    """Current DB data of a product the answer shows as a card."""

    product_id: str
    name: str
    category: str
    price: float
    active: bool
    available: int


@dataclass
class TurnObservation:
    response: dict[str, Any]  # AgentResponse as JSON
    tools: list[ToolCallObs]
    products: dict[str, ProductFacts]  # facts of response.product_ids
    cart: dict[str, int]  # product name -> quantity, after the turn
    orders_created: int  # orders of the user created during the case
    stop_reason: str


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class _Ctx:
    obs: TurnObservation
    results: list[CheckResult] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append(CheckResult(name, ok, "" if ok else detail))


def normalize(text: str) -> str:
    """Lowercase, no accents: 'Discontinuado' matches 'discontinuado'."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else [value]


def _op_ok(op: str, actual: Any, expected: Any) -> bool:
    if op == "null":
        return (actual is None) == expected
    if actual is None:
        return False
    if op == "lte":
        return float(actual) <= expected
    if op == "gte":
        return float(actual) >= expected
    if op == "in":
        return normalize(str(actual)) in [normalize(str(e)) for e in expected]
    if op == "contains":  # the argument is a list
        return normalize(str(expected)) in [normalize(str(a)) for a in actual]
    raise ValueError(f"unknown operator {op!r}")


def _matches(actual: Any, spec: Any) -> bool:
    """A value spec: a literal (strings compare case-insensitively) or an operator dict:
    {"lte": n}, {"gte": n}, {"in": [...]}, {"contains": x} (list argument), {"null": bool}."""
    if isinstance(spec, dict):
        return all(_op_ok(op, actual, expected) for op, expected in spec.items())
    if isinstance(spec, str) and isinstance(actual, str):
        return normalize(actual) == normalize(spec)
    return actual == spec


# --- One function per expectation key ------------------------------------------------------------


def _response_type(c: _Ctx, spec) -> None:
    actual = c.obs.response.get("type")
    c.add("response_type", actual in _as_list(spec), f"type={actual!r}, expected {spec!r}")


def _tool_called(c: _Ctx, spec) -> None:
    called = {t.name for t in c.obs.tools}
    missing = [n for n in _as_list(spec) if n not in called]
    c.add("tool_called", not missing, f"not called: {missing}; called: {sorted(called)}")


def _tool_called_any(c: _Ctx, spec) -> None:
    called = {t.name for t in c.obs.tools}
    c.add("tool_called_any", bool(called & set(spec)), f"none of {spec}; called: {sorted(called)}")


def _no_tool(c: _Ctx, spec) -> None:
    bad = sorted({t.name for t in c.obs.tools if t.name in _as_list(spec)})
    c.add("no_tool", not bad, f"called: {bad}")


def _no_tools(c: _Ctx, spec) -> None:
    called = [t.name for t in c.obs.tools]
    c.add("no_tools", (not called) == spec, f"called: {called}")


def _tool_args(c: _Ctx, spec: dict) -> None:
    """Some call of each tool has ALL the listed argument values."""
    for tool, wanted in spec.items():
        calls = [t.arguments or {} for t in c.obs.tools if t.name == tool]
        ok = any(all(_matches(args.get(k), v) for k, v in wanted.items()) for args in calls)
        c.add(f"tool_args:{tool}", ok, f"wanted {wanted}; calls: {calls}")


def _error_code(c: _Ctx, spec) -> None:
    codes = [t.error_code for t in c.obs.tools if t.error_code]
    ok = any(code in _as_list(spec) for code in codes)
    c.add("error_code", ok, f"tool errors: {codes}, expected one of {spec}")


def _products(c: _Ctx, spec: dict) -> None:
    ids = c.obs.response.get("product_ids") or []
    facts = [c.obs.products[i] for i in ids if i in c.obs.products]
    names = [normalize(f.name) for f in facts]
    for key, value in spec.items():
        if key == "min":
            c.add("products.min", len(ids) >= value, f"{len(ids)} products, min {value}")
        elif key == "max":
            c.add("products.max", len(ids) <= value, f"{len(ids)} products, max {value}")
        elif key == "all_price_lte":
            bad = [f.name for f in facts if f.price > value]
            c.add("products.all_price_lte", not bad, f"over {value}: {bad}")
        elif key == "all_active":
            bad = [f.name for f in facts if not f.active]
            c.add("products.all_active", not bad, f"inactive: {bad}")
        elif key == "all_in_stock":
            bad = [f.name for f in facts if f.available <= 0]
            c.add("products.all_in_stock", not bad, f"without stock: {bad}")
        elif key == "category":
            bad = [f.name for f in facts if f.category != value]
            c.add("products.category", not bad, f"not {value}: {bad}")
        elif key == "include":
            missing = [n for n in _as_list(value) if normalize(n) not in names]
            c.add("products.include", not missing, f"missing: {missing}")
        elif key == "exclude":
            present = [n for n in _as_list(value) if normalize(n) in names]
            c.add("products.exclude", not present, f"present: {present}")
        else:
            raise ValueError(f"unknown products check {key!r}")


def _message_contains_any(c: _Ctx, spec) -> None:
    text = normalize(c.obs.response.get("message") or "")
    ok = any(normalize(s) in text for s in _as_list(spec))
    c.add("message_contains_any", ok, f"none of {spec} in the message")


def _message_not_contains(c: _Ctx, spec) -> None:
    text = normalize(c.obs.response.get("message") or "")
    found = [s for s in _as_list(spec) if normalize(s) in text]
    c.add("message_not_contains", not found, f"found {found}")


def _pending_confirmation(c: _Ctx, spec: bool) -> None:
    pending = c.obs.response.get("pending_confirmation")
    c.add("pending_confirmation", (pending is not None) == spec, f"pending={pending}")


def _checkout(c: _Ctx, spec) -> None:
    handoff = c.obs.response.get("checkout")
    if isinstance(spec, bool):
        c.add("checkout", (handoff is not None) == spec, f"checkout={handoff}")
        return
    if handoff is None:
        c.add("checkout", False, "no checkout card")
        return
    for key, value in spec.items():
        actual = (
            (handoff.get("pickup_warehouse") or {}).get("warehouse_id")
            if key == "pickup_warehouse_id"
            else handoff.get(key)
        )
        c.add(f"checkout.{key}", _matches(actual, value), f"{key}={actual!r}, expected {value!r}")


def _comparison(c: _Ctx, spec: bool) -> None:
    ids = c.obs.response.get("comparison_ids") or []
    c.add("comparison", bool(ids) == spec, f"comparison_ids={ids}")


def _cart(c: _Ctx, spec: dict) -> None:
    cart = {normalize(k): v for k, v in c.obs.cart.items()}
    for key, value in spec.items():
        if key == "empty":
            c.add("cart.empty", (not cart) == value, f"cart={c.obs.cart}")
        elif key == "items":
            c.add("cart.items", len(cart) == value, f"cart={c.obs.cart}")
        else:  # a product name -> exact quantity (0 = not in the cart)
            actual = cart.get(normalize(key), 0)
            c.add(f"cart[{key}]", actual == value, f"{key}: {actual}, expected {value}")


def _orders_created(c: _Ctx, spec: int) -> None:
    c.add("orders_created", c.obs.orders_created == spec, f"{c.obs.orders_created} orders created")


def _stop_reason(c: _Ctx, spec) -> None:
    c.add("stop_reason", c.obs.stop_reason in _as_list(spec), f"stop_reason={c.obs.stop_reason}")


CHECKS = {
    "response_type": _response_type,
    "tool_called": _tool_called,
    "tool_called_any": _tool_called_any,
    "no_tool": _no_tool,
    "no_tools": _no_tools,
    "tool_args": _tool_args,
    "error_code": _error_code,
    "products": _products,
    "message_contains_any": _message_contains_any,
    "message_not_contains": _message_not_contains,
    "pending_confirmation": _pending_confirmation,
    "checkout": _checkout,
    "comparison": _comparison,
    "cart": _cart,
    "orders_created": _orders_created,
    "stop_reason": _stop_reason,
}


def evaluate(expect: dict[str, Any], obs: TurnObservation) -> list[CheckResult]:
    ctx = _Ctx(obs)
    for key, spec in expect.items():
        if key not in CHECKS:
            raise ValueError(f"unknown expectation {key!r}")
        CHECKS[key](ctx, spec)
    return ctx.results
