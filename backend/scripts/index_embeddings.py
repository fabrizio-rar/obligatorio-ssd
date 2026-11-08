"""Compute the product embeddings and store them in product_embeddings.

    python -m scripts.index_embeddings            # embed only new/changed products
    python -m scripts.index_embeddings --force    # re-embed everything
    python -m scripts.index_embeddings --query "auriculares para videollamadas"
                                                  # debug: top 5 by cosine distance

Without OPENAI_API_KEY it does nothing (exit 0): semantic search stays disabled and
search falls back to full-text + SQL filters.
"""

import argparse
import json
import sys

from app.config import get_settings
from app.db import get_session_factory
from app.retrieval.embeddings import EmbeddingError, get_embedder
from app.retrieval.indexer import index_products, nearest_products


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="re-embed every product")
    parser.add_argument("--query", help="print the nearest products to this text and exit")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)

    embedder = get_embedder(settings)
    if embedder is None:
        print("OPENAI_API_KEY not set: skipping embeddings (semantic search disabled).")
        return 0

    with get_session_factory()() as session:
        try:
            if args.query:
                for pid, name, active, dist in nearest_products(
                    session, embedder, args.query, args.limit
                ):
                    flag = "" if active else "  [inactive]"
                    print(f"{dist:.4f}  {pid}  {name}{flag}")
                return 0

            report = index_products(
                session,
                embedder,
                force=args.force,
                usd_per_1m_tokens=settings.embedding_usd_per_1m_tokens,
                batch_size=settings.embedding_batch_size,
            )
        except EmbeddingError as error:
            print(f"Embeddings failed [{error.code}]: {error.message}", file=sys.stderr)
            return 1

    path = settings.ingest_report_path.parent / "embeddings_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.model_dump(mode="json"), indent=2))
    print(report.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
