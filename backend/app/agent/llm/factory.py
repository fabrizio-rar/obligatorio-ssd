from app.agent.llm.base import LLMProvider
from app.agent.llm.openai_provider import OpenAIResponsesProvider
from app.config import Settings


def get_llm_provider(settings: Settings) -> LLMProvider | None:
    """None without OPENAI_API_KEY: the chat is disabled, the rest of the app works."""
    if not settings.openai_configured:
        return None
    return OpenAIResponsesProvider(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.llm_model,
        reasoning_effort=settings.llm_reasoning_effort,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
