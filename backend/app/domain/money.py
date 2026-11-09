"""Amounts in texts the backend writes (messages, errors): the same es-UY format as the UI."""

from decimal import Decimal


def format_usd(amount: Decimal) -> str:
    """USD 1.234,56"""
    us = f"{amount:,.2f}"  # 1,234.56
    return "USD " + us.replace(",", "_").replace(".", ",").replace("_", ".")
