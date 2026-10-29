"""Verify that every extracted value is backed by a verbatim quote from the document.

A field survives only if (1) its quote is found in the document text, ignoring case and
whitespace, and (2) its value can be read back out of that quote. Otherwise the value is
nulled and the reason recorded. The model never decides confidence; this code does.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field

from .money import cents, parse_es_numbers, to_decimal
from .schema import LineItemRaw, QNumber, QText, RawExtraction


class Status(StrEnum):
    VERIFIED = "verified"
    MISSING = "missing"
    NO_QUOTE = "no_quote"
    QUOTE_NOT_FOUND = "quote_not_found"
    VALUE_NOT_IN_QUOTE = "value_not_in_quote"
    CORRECTED = "corrected"


STATUS_LABELS_ES = {
    Status.VERIFIED: "Cita verificada",
    Status.MISSING: "No encontrado",
    Status.NO_QUOTE: "Sin cita · descartado",
    Status.QUOTE_NOT_FOUND: "Cita no encontrada · descartado",
    Status.VALUE_NOT_IN_QUOTE: "Valor no coincide con la cita · descartado",
    Status.CORRECTED: "Corregido por una persona",
}


class Grounded(BaseModel):
    value: str | float | None = None
    quote: str | None = None
    claimed: str | float | None = None
    status: Status = Status.MISSING
    span: tuple[int, int] | None = None

    @property
    def ok(self) -> bool:
        return self.status in (Status.VERIFIED, Status.CORRECTED)


class GroundedVat(BaseModel):
    rate: float | None
    base: Grounded
    vat: Grounded


class GroundedLine(BaseModel):
    description: str | None
    quantity: float | None
    unit_price: float | None
    amount: float | None
    quote: str | None
    status: Status
    span: tuple[int, int] | None = None


class GroundedDoc(BaseModel):
    document_type: Grounded
    supplier_name: Grounded
    supplier_tax_id: Grounded
    invoice_number: Grounded
    issue_date: Grounded
    due_date: Grounded
    vat_lines: list[GroundedVat] = Field(default_factory=list)
    irpf_rate: Grounded
    irpf_amount: Grounded
    total: Grounded
    iban: Grounded
    line_items: list[GroundedLine] = Field(default_factory=list)

    def scalar_fields(self) -> dict[str, Grounded]:
        return {
            "document_type": self.document_type,
            "supplier_name": self.supplier_name,
            "supplier_tax_id": self.supplier_tax_id,
            "invoice_number": self.invoice_number,
            "issue_date": self.issue_date,
            "due_date": self.due_date,
            "irpf_rate": self.irpf_rate,
            "irpf_amount": self.irpf_amount,
            "total": self.total,
            "iban": self.iban,
        }

    def all_grounded(self) -> list[tuple[str, Grounded]]:
        items = list(self.scalar_fields().items())
        for line in self.vat_lines:
            rate = f"{line.rate:g}" if line.rate is not None else "?"
            items.append((f"base_{rate}", line.base))
            items.append((f"vat_{rate}", line.vat))
        return items


def _fold(char: str) -> str:
    decomposed = unicodedata.normalize("NFKD", char.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    out: list[str] = []
    index_map: list[int] = []
    previous_space = True
    for index, char in enumerate(text):
        if char.isspace():
            if not previous_space:
                out.append(" ")
                index_map.append(index)
            previous_space = True
            continue
        for folded in _fold(char):
            out.append(folded)
            index_map.append(index)
        previous_space = False
    if out and out[-1] == " ":
        out.pop()
        index_map.pop()
    return "".join(out), index_map


def normalize(text: str) -> str:
    return _normalize_with_map(text)[0]


def find_span(text: str, quote: str) -> tuple[int, int] | None:
    needle = normalize(quote or "")
    if not needle:
        return None
    haystack, index_map = _normalize_with_map(text)
    position = haystack.find(needle)
    if position < 0:
        return None
    return index_map[position], index_map[position + len(needle) - 1] + 1


def _alnum(text: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", normalize(text).upper())


def _supports_text(value: str, quote: str) -> bool:
    return normalize(value) in normalize(quote)


def _supports_code(value: str, quote: str) -> bool:
    code = _alnum(value)
    return bool(code) and code in _alnum(quote)


def _supports_date(value: str, quote: str) -> bool:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    for match in re.finditer(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", quote):
        day, month, year = (int(part) for part in match.groups())
        if (year, month, day) == (parsed.year, parsed.month, parsed.day):
            return True
    return value in quote


def _supports_number(value: float, quote: str) -> bool:
    amount = to_decimal(value)
    if amount is None:
        return False
    return cents(abs(amount)) in {cents(number) for number in parse_es_numbers(quote)}


def _supports_document_type(value: str, quote: str) -> bool:
    folded = normalize(quote)
    return {"factura": "factura", "albaran": "albaran"}.get(normalize(value), "\0") in folded


def _ground(field: QText | QNumber, text: str, supports) -> Grounded:
    value, quote = field.value, field.quote
    if value is None or (isinstance(value, str) and not value.strip()):
        return Grounded(quote=quote, status=Status.MISSING)
    if not quote or not quote.strip():
        return Grounded(claimed=value, status=Status.NO_QUOTE)
    span = find_span(text, quote)
    if span is None:
        return Grounded(claimed=value, quote=quote, status=Status.QUOTE_NOT_FOUND)
    if not supports(value, quote):
        return Grounded(claimed=value, quote=quote, status=Status.VALUE_NOT_IN_QUOTE, span=span)
    return Grounded(value=value, quote=quote, claimed=value, status=Status.VERIFIED, span=span)


def _ground_code(field: QText, text: str, strip_country: bool = False) -> Grounded:
    grounded = _ground(field, text, _supports_code)
    if grounded.ok:
        code = _alnum(str(grounded.value))
        if strip_country and code.startswith("ES") and len(code) == 11:
            code = code[2:]
        grounded.value = code
    return grounded


def _ground_line(line: LineItemRaw, text: str) -> GroundedLine:
    span = find_span(text, line.quote or "")
    status = Status.VERIFIED
    if not line.quote:
        status = Status.NO_QUOTE
    elif span is None:
        status = Status.QUOTE_NOT_FOUND
    elif line.amount is None or not _supports_number(line.amount, line.quote):
        status = Status.VALUE_NOT_IN_QUOTE
    verified = status == Status.VERIFIED
    return GroundedLine(
        description=line.description if verified else None,
        quantity=line.quantity if verified else None,
        unit_price=line.unit_price if verified else None,
        amount=line.amount if verified else None,
        quote=line.quote,
        status=status,
        span=span,
    )


def ground(raw: RawExtraction, text: str) -> GroundedDoc:
    vat_lines = []
    for line in raw.vat_lines:
        base = _ground(line.base, text, _supports_number)
        vat = _ground(line.vat, text, _supports_number)
        rate_backed = (
            line.rate is not None and base.ok and _supports_number(line.rate, line.base.quote)
        )
        if base.ok and not rate_backed:
            base = Grounded(
                claimed=base.value,
                quote=base.quote,
                status=Status.VALUE_NOT_IN_QUOTE,
                span=base.span,
            )
        vat_lines.append(GroundedVat(rate=line.rate, base=base, vat=vat))

    document_type = _ground(raw.document_type, text, _supports_document_type)
    if document_type.ok:
        document_type.value = normalize(str(document_type.value))

    return GroundedDoc(
        document_type=document_type,
        supplier_name=_ground(raw.supplier_name, text, _supports_text),
        supplier_tax_id=_ground_code(raw.supplier_tax_id, text, strip_country=True),
        invoice_number=_ground(raw.invoice_number, text, _supports_code),
        issue_date=_ground(raw.issue_date, text, _supports_date),
        due_date=_ground(raw.due_date, text, _supports_date),
        vat_lines=vat_lines,
        irpf_rate=_ground(raw.irpf_rate, text, _supports_number),
        irpf_amount=_ground(raw.irpf_amount, text, _supports_number),
        total=_ground(raw.total, text, _supports_number),
        iban=_ground_code(raw.iban, text),
        line_items=[_ground_line(line, text) for line in raw.line_items],
    )
