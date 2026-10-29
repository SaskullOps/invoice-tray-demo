"""What the model must return. Every value comes with a verbatim quote from the document."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)


class QText(_Lenient):
    value: str | None = None
    quote: str | None = None


class QNumber(_Lenient):
    value: float | None = None
    quote: str | None = None


class VatLineRaw(_Lenient):
    rate: float | None = None
    base: QNumber = Field(default_factory=QNumber)
    vat: QNumber = Field(default_factory=QNumber)


class LineItemRaw(_Lenient):
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None
    quote: str | None = None


class RawExtraction(_Lenient):
    """Unknown keys (for example an injected "approved": true) are dropped on parse."""

    document_type: QText = Field(default_factory=QText)
    supplier_name: QText = Field(default_factory=QText)
    supplier_tax_id: QText = Field(default_factory=QText)
    invoice_number: QText = Field(default_factory=QText)
    issue_date: QText = Field(default_factory=QText)
    due_date: QText = Field(default_factory=QText)
    vat_lines: list[VatLineRaw] = Field(default_factory=list)
    irpf_rate: QNumber = Field(default_factory=QNumber)
    irpf_amount: QNumber = Field(default_factory=QNumber)
    total: QNumber = Field(default_factory=QNumber)
    iban: QText = Field(default_factory=QText)
    line_items: list[LineItemRaw] = Field(default_factory=list)
