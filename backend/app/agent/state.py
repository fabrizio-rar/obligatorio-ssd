"""Execution state of a conversation (docs/PLAN.md §10.5). It is what the app keeps to
continue the conversation; business data (price, stock) is NOT here: tools read the DB."""

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Product

MAX_SEEN = 100


class LastTurn(BaseModel):
    steps: int = 0
    tools_used: list[str] = Field(default_factory=list)
    stop_reason: str | None = None


class AgentState(BaseModel):
    # Every product that came back from a tool: the only IDs the answer may reference
    seen_product_ids: list[str] = Field(default_factory=list)
    # Products in the last answer, in order: lets the user say "el segundo"
    last_shown: list[str] = Field(default_factory=list)
    last_turn: LastTurn = Field(default_factory=LastTurn)

    def remember(self, product_ids: list[str]) -> None:
        merged = list(dict.fromkeys([*self.seen_product_ids, *product_ids]))
        self.seen_product_ids = merged[-MAX_SEEN:]


def summary(state: AgentState, session: Session) -> str:
    """2-3 lines for the model instead of the whole state (context engineering)."""
    if not state.last_shown:
        return ""
    names = dict(
        session.execute(
            select(Product.id, Product.name).where(Product.id.in_(state.last_shown))
        ).all()
    )
    shown = "; ".join(
        f"{i}) {names.get(pid, '?')} ({pid})" for i, pid in enumerate(state.last_shown, 1)
    )
    return (
        f"Products shown in your previous answer, in order: {shown}. "
        "Their price and stock may have changed: search again before stating them."
    )
