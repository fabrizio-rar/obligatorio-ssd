"""Try the product search by hand, with the same arguments the agent's tool will pass.

    python -m scripts.search "comfortable headphones for video calls" \
        --category Headphones --max-price 200 --use calls
"""

import argparse
import sys
from decimal import Decimal

from pydantic import ValidationError

from app.config import get_settings
from app.db import get_session_factory
from app.domain.errors import DomainError
from app.retrieval.embeddings import get_embedder
from app.retrieval.search import SearchQuery, search


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("query")
    parser.add_argument("--category")
    parser.add_argument("--subcategory")
    parser.add_argument("--brand")
    parser.add_argument("--min-price", type=Decimal)
    parser.add_argument("--max-price", type=Decimal)
    parser.add_argument("--use", action="append", default=[], help="use case (repeatable)")
    parser.add_argument("--avoid", action="append", default=[], help="avoid case (repeatable)")
    parser.add_argument("--include-out-of-stock", action="store_true")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)

    try:
        q = SearchQuery(
            query=args.query,
            category=args.category,
            subcategory=args.subcategory,
            brand=args.brand,
            min_price=args.min_price,
            max_price=args.max_price,
            use_cases=args.use,
            exclude_use_cases=args.avoid,
            in_stock_only=not args.include_out_of_stock,
            limit=args.limit,
        )
    except ValidationError as error:
        print(f"Invalid arguments: {error}", file=sys.stderr)
        return 1

    with get_session_factory()() as session:
        try:
            result = search(session, q, get_embedder(get_settings()))
        except DomainError as error:
            print(error.to_dict(), file=sys.stderr)
            return 1

    mode = "semantic + use cases" if result.semantic_used else "FALLBACK (no embeddings)"
    print(f"{result.total_candidates} candidates after filters | ranking: {mode}")
    for hit in result.hits:
        uses = f"  uses: {', '.join(hit.matched_use_cases)}" if hit.matched_use_cases else ""
        print(
            f"  {hit.product_id}  {hit.name:<30} {hit.category:<12} "
            f"USD {hit.current_price:>7}  stock {hit.available:>3}  ★{hit.rating}{uses}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
