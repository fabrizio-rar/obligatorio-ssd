"""Structured output of every turn (docs/PLAN.md §10.6). Only the fields the current tools
can fill; cart, comparison and checkout fields arrive with their tools."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ResponseType = Literal["recommendation", "clarification", "info", "error"]


class AgentResponse(BaseModel):
    """Every field is required (strict mode); "nothing" is an empty list or null."""

    model_config = ConfigDict(extra="forbid")

    type: ResponseType = Field(
        description=(
            "recommendation: you recommend products; clarification: you need more info "
            "before searching; info: an answer without recommending; error: you could not help"
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


FALLBACK_MESSAGES = {
    "format": "No pude procesar la consulta. ¿Podés reformularla?",
    "max_steps": "No llegué a una respuesta a tiempo. ¿Podés reformular o acotar la consulta?",
    "budget": "La consulta llevó demasiado tiempo. ¿Podés reformularla de forma más concreta?",
    "loop": "Me trabé buscando. ¿Podés reformular la consulta con otras palabras?",
}


def fallback(reason: str) -> AgentResponse:
    """Controlled answer when the turn cannot finish. Never pretends an action was done."""
    return AgentResponse(
        type="error",
        message=FALLBACK_MESSAGES[reason],
        product_ids=[],
        clarifying_question=None,
        suggested_replies=[],
    )
