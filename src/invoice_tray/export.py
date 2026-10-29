"""ERP import file. One row per booked invoice; see README for the column contract."""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from .money import cents, to_decimal

if TYPE_CHECKING:
    from .pipeline import Evaluated

CSV_COLUMNS = [
    "document_id",
    "supplier_tax_id",
    "supplier_name",
    "invoice_number",
    "issue_date",
    "due_date",
    "base_21",
    "vat_21",
    "base_10",
    "vat_10",
    "base_4",
    "vat_4",
    "base_other",
    "vat_other",
    "irpf_rate",
    "irpf_amount",
    "total",
    "iban",
    "currency",
    "review",
    "source_file",
]


def _money(value: Decimal | None) -> str:
    return f"{cents(value):.2f}" if value is not None else ""


def to_row(doc: Evaluated) -> dict[str, str]:
    grounded = doc.grounded
    assert grounded is not None
    buckets = {key: Decimal("0") for key in ("21", "10", "4", "other")}
    vat_buckets = dict(buckets)
    for line in grounded.vat_lines:
        key = f"{line.rate:g}" if line.rate in (21, 10, 4) else "other"
        buckets[key] += to_decimal(line.base.value) or Decimal("0")
        vat_buckets[key] += to_decimal(line.vat.value) or Decimal("0")

    def scalar(name: str) -> str:
        field = getattr(grounded, name)
        return "" if field.value is None else str(field.value)

    irpf_rate = to_decimal(grounded.irpf_rate.value)
    row = {
        "document_id": doc.doc_id,
        "supplier_tax_id": scalar("supplier_tax_id"),
        "supplier_name": scalar("supplier_name"),
        "invoice_number": scalar("invoice_number"),
        "issue_date": scalar("issue_date"),
        "due_date": scalar("due_date"),
        "irpf_rate": f"{float(irpf_rate):g}" if irpf_rate else "",
        "irpf_amount": _money(to_decimal(grounded.irpf_amount.value)),
        "total": _money(to_decimal(grounded.total.value)),
        "iban": scalar("iban"),
        "currency": "EUR",
        "review": "manual" if doc.review else "auto",
        "source_file": doc.file,
    }
    for key in buckets:
        has = any(
            (f"{line.rate:g}" if line.rate in (21, 10, 4) else "other") == key
            for line in grounded.vat_lines
        )
        row[f"base_{key}"] = _money(buckets[key]) if has else ""
        row[f"vat_{key}"] = _money(vat_buckets[key]) if has else ""
    return {column: row[column] for column in CSV_COLUMNS}


def write_csv(docs: list[Evaluated], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, delimiter=";")
        writer.writeheader()
        for doc in docs:
            writer.writerow(to_row(doc))
