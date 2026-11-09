"""Demo / test tool (docs/PLAN.md §12.1): change a product's current price, to show that the
purchase revalidates prices (409 PRICE_CHANGED). The dataset prices never change by themselves.

    python -m scripts.simulate_price_change MN-HDP-0004 159.90
    python -m scripts.simulate_price_change MN-HDP-0004 --percent -10

`python -m scripts.ingest` restores the dataset prices.
"""

import argparse
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from app.db import get_session_factory
from app.domain.money import format_usd
from app.models import Price, Product


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("product_id")
    parser.add_argument("price", nargs="?", type=Decimal, help="new current price in USD")
    parser.add_argument("--percent", type=Decimal, help="change relative to the current price")
    args = parser.parse_args()
    if (args.price is None) == (args.percent is None):
        parser.error("give either a price or --percent")

    with get_session_factory()() as session:
        product = session.get(Product, args.product_id)
        price = session.scalars(select(Price).where(Price.product_id == args.product_id)).first()
        if product is None or price is None:
            raise SystemExit(f"Product {args.product_id} not found")
        old = price.current_price
        new = args.price if args.price is not None else old * (1 + args.percent / 100)
        new = new.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if new <= 0:
            raise SystemExit("The price must be positive")
        price.current_price = new
        # Keep the dataset rule current = list x (1 - discount) roughly true for the UI
        discount = (1 - new / price.list_price) * 100
        price.discount_percent = max(0, int(discount.quantize(Decimal("1"))))
        session.commit()
        print(f"{product.name}: {format_usd(old)} -> {format_usd(new)}")


if __name__ == "__main__":
    main()
