"""Decimal helpers and Spanish number formatting/parsing."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")

_ES_NUMBER = re.compile(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?|-?\d+,\d+|-?\d+\.\d+|-?\d+")


def to_decimal(value: float | int | str | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def format_es(value: Decimal | float, decimals: int = 2) -> str:
    text = f"{Decimal(str(value)):,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def parse_es_numbers(text: str) -> list[Decimal]:
    """Every number written in `text`, read the Spanish way (1.234,56) or plain (1234.56)."""
    numbers: list[Decimal] = []
    for match in _ES_NUMBER.findall(text or ""):
        if "," in match or re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", match):
            normalized = match.replace(".", "").replace(",", ".")
        else:
            normalized = match
        parsed = to_decimal(normalized)
        if parsed is not None:
            numbers.append(abs(parsed))
    return numbers
