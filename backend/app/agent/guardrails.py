"""Output guardrails (docs/PLAN.md §10.7.4): what does NOT depend on the model obeying."""

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.response_schema import ModelResponse
from app.models import Product

MAX_PRODUCT_IDS = 5


def parse_response(message_texts: list[str]) -> tuple[ModelResponse | None, str | None]:
    """Parse the structured output from the message items, last one first (the model may
    add an extra message item). Returns (response, last validation error)."""
    error = None
    for text in reversed(message_texts):
        try:
            return ModelResponse.model_validate_json(text), None
        except ValidationError as exc:
            error = str(exc)
    return None, error or "the answer had no message"


def check_product_ids[R: ModelResponse](
    response: R, seen_ids: set[str], session: Session
) -> tuple[R, list[str]]:
    """Keep only product IDs that came from a tool result in this conversation AND are
    active in the DB. A card can never show a product the model made up.
    Returns (clean response, dropped ids)."""
    unique = list(dict.fromkeys(response.product_ids))
    candidates = [pid for pid in unique if pid in seen_ids]
    active = set(
        session.scalars(
            select(Product.id).where(Product.id.in_(candidates), Product.active.is_(True))
        )
    )
    kept = [pid for pid in candidates if pid in active][:MAX_PRODUCT_IDS]
    dropped = [pid for pid in unique if pid not in kept]
    return response.model_copy(update={"product_ids": kept}), dropped
