"""Structured output of every turn (docs/PLAN.md §10.6), in two layers:

- ModelResponse: what the MODEL writes (its JSON schema is the one sent to OpenAI).
- AgentResponse: what the API returns = ModelResponse + fields the BACKEND fills from the
  tool results (ui_actions, pending_confirmation). They are not in the model's schema, so
  the model cannot invent a confirmation card or a "cart changed" signal.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ResponseType = Literal[
    "recommendation", "comparison", "clarification", "info", "cart_update", "error"
]
UiAction = Literal["refresh_cart"]


class ModelResponse(BaseModel):
    """Every field is required (strict mode); "nothing" is an empty list or null."""

    model_config = ConfigDict(extra="forbid")

    type: ResponseType = Field(
        description=(
            "recommendation: you recommend products; comparison: you compared products; "
            "clarification: you need more info "
            "before acting; info: an answer without recommending; cart_update: you changed "
            "the cart; error: you could not help"
        )
    )
    message: str = Field(description="Reply to the user, in Spanish")
    product_ids: list[str] = Field(
        description="IDs of the products you recommend or mention, best first. "
        "Only IDs returned by a tool. Empty if none."
    )
    clarifying_question: str | None = Field(
        description="The question you ask when type is clarification, otherwise null"
    )
    suggested_replies: list[str] = Field(
        description="0-3 short replies the user could send next, in Spanish"
    )


class PendingAction(BaseModel):
    """Level-3 action waiting for the user's click (docs/PLAN.md §10.4.1). The button calls
    the REST endpoint directly: the LLM never executes it."""

    action: Literal["remove_item", "clear_cart"]
    product_id: str | None  # remove_item only
    summary: str  # built by the backend with DB data: "¿Quitar X × 2 (USD ...)?"


class AgentResponse(ModelResponse):
    ui_actions: list[UiAction] = Field(default_factory=list)
    pending_confirmation: PendingAction | None = None
    # Products of the last compare_products in the turn: the UI draws the table with
    # GET /api/products/compare?ids=...
    comparison_ids: list[str] = Field(default_factory=list)


FALLBACK_MESSAGES = {
    "format": "No pude procesar la consulta. ¿Podés reformularla?",
    "max_steps": "No llegué a una respuesta a tiempo. ¿Podés reformular o acotar la consulta?",
    "budget": "La consulta se hizo demasiado larga. ¿Podés reformularla de forma más concreta?",
    "loop": "Me trabé buscando. ¿Podés reformular la consulta con otras palabras?",
}


CART_CHANGED_NOTE = " Igual, ya hice cambios en tu carrito: revisalo en pantalla."


def fallback(reason: str, cart_changed: bool = False) -> AgentResponse:
    """Controlled answer when the turn cannot finish. It never pretends an action was done,
    and never hides one that WAS done (e.g. the cart changed before the turn was cut)."""
    note = CART_CHANGED_NOTE if cart_changed else ""
    return AgentResponse(
        type="error",
        message=FALLBACK_MESSAGES[reason] + note,
        product_ids=[],
        clarifying_question=None,
        suggested_replies=[],
    )
