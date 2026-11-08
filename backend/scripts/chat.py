"""Chat with the assistant from the terminal (real model: costs ~USD 0.002 per turn).

    python -m scripts.chat "busco auriculares para videollamadas hasta 200 dólares"
    python -m scripts.chat "y con cancelación de ruido?" --conversation <id>
    python -m scripts.chat --verbose "..."     # also print the tool calls

Same code path as POST /api/chat. Each run is one turn; pass --conversation to continue.
"""

import argparse
import asyncio
import json
import sys
import uuid

from sqlalchemy import select

from app.agent.llm.base import LLMError
from app.agent.llm.factory import get_llm_provider
from app.agent.service import chat_turn
from app.config import get_settings
from app.db import get_session_factory
from app.domain.errors import DomainError
from app.models import ChatMessage, ToolCallLog
from app.retrieval.embeddings import get_embedder


def _summarize(result: dict) -> object:
    if "products" in result:
        return [p["name"] for p in result["products"]]
    if "product" in result:
        return f"{result['product']['name']} [{result['product']['status']}]"
    if "matches" in result:
        return [f"{m['name']} {m['sku']} [{m['status']}]" for m in result["matches"]]
    return result.get("error")


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("message")
    parser.add_argument("--conversation", type=uuid.UUID)
    parser.add_argument("--verbose", action="store_true", help="print tool calls and arguments")
    args = parser.parse_args(argv)

    settings = get_settings()
    llm = get_llm_provider(settings)
    if llm is None:
        print("OPENAI_API_KEY not set: the chat is disabled.", file=sys.stderr)
        return 1

    with get_session_factory()() as session:
        try:
            turn = await chat_turn(
                session, llm, get_embedder(settings), settings, args.message, args.conversation
            )
        except (DomainError, LLMError) as error:
            print(f"Error [{error.code}]: {error.message}", file=sys.stderr)
            return 1

        r, m = turn.response, turn.meta
        print(f"\n[{r.type}] {r.message}")
        if r.product_ids:
            print(f"  product_ids: {', '.join(r.product_ids)}")
        if r.suggested_replies:
            print(f"  sugerencias: {' | '.join(r.suggested_replies)}")
        print(
            f"\n  conversation: {turn.conversation_id}\n  steps={m.steps} stop={m.stop_reason} "
            f"tools={m.tools_used} tokens={m.input_tokens}+{m.output_tokens} {m.latency_ms} ms"
        )
        if args.verbose:
            last = session.scalar(
                select(ChatMessage.id)
                .where(ChatMessage.conversation_id == turn.conversation_id)
                .order_by(ChatMessage.id.desc())
                .limit(1)
            )
            for log in session.scalars(select(ToolCallLog).where(ToolCallLog.message_id == last)):
                print(f"  tool[{log.step}] {log.tool_name} {json.dumps(log.arguments)}")
                print(f"     -> ok={not log.is_error} {_summarize(log.result)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
