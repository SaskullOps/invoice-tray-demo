from pathlib import Path

import pytest

from invoice_tray.iban import format_iban
from invoice_tray.money import format_es
from invoice_tray.pdftext import extract_text
from invoice_tray.samples import SampleDoc, build_samples, generate
from invoice_tray.schema import LineItemRaw, QNumber, QText, RawExtraction, VatLineRaw


def _line_with(text: str, needle: str, after: str = "") -> str | None:
    lines = text.splitlines()
    for line in lines:
        if needle in line and after in line:
            return line.strip()
    return None


def oracle(doc: SampleDoc, text: str) -> RawExtraction:
    """What a perfect model would answer: true values, each quoting the line it came from."""
    vat_lines = []
    if doc.doc_type == "factura":
        for rate, base in doc.bases().items():
            vat = doc.vats()[rate]
            vat_lines.append(
                VatLineRaw(
                    rate=rate,
                    base=QNumber(
                        value=float(base), quote=_line_with(text, f"Base imponible {rate} %")
                    ),
                    vat=QNumber(value=float(vat), quote=_line_with(text, f"Cuota IVA {rate} %")),
                )
            )
    lines = [
        LineItemRaw(
            description=line.description,
            quantity=float(line.quantity),
            unit_price=float(line.unit_price),
            amount=float(line.amount),
            quote=_line_with(text, line.description),
        )
        for line in doc.lines
    ]
    title = "FACTURA" if doc.doc_type == "factura" else "ALBARÁN"
    return RawExtraction(
        document_type=QText(value=doc.doc_type, quote=_line_with(text, title)),
        supplier_name=QText(value=doc.supplier.name, quote=_line_with(text, doc.supplier.name)),
        supplier_tax_id=QText(
            value=doc.supplier.tax_id, quote=_line_with(text, doc.supplier.tax_id)
        ),
        invoice_number=QText(
            value=doc.number, quote=_line_with(text, doc.number) if doc.number else None
        ),
        issue_date=QText(
            value=doc.issue_date.isoformat(), quote=_line_with(text, "Fecha de emisión")
        ),
        vat_lines=vat_lines,
        irpf_rate=QNumber(
            value=doc.irpf_rate or None,
            quote=_line_with(text, "Retención IRPF") if doc.irpf_rate else None,
        ),
        irpf_amount=QNumber(
            value=float(doc.irpf_amount()) or None,
            quote=_line_with(text, "Retención IRPF") if doc.irpf_rate else None,
        ),
        total=QNumber(
            value=float(doc.total()) if doc.doc_type == "factura" else None,
            quote=_line_with(text, "TOTAL FACTURA") if doc.doc_type == "factura" else None,
        ),
        iban=QText(
            value=doc.iban, quote=_line_with(text, format_iban(doc.iban)) if doc.iban else None
        ),
        line_items=lines,
    )


@pytest.fixture(scope="session")
def samples_dir(tmp_path_factory) -> Path:
    directory = tmp_path_factory.mktemp("samples")
    generate(directory)
    return directory


@pytest.fixture(scope="session")
def corpus(samples_dir) -> dict[str, tuple[SampleDoc, str]]:
    return {
        doc.sample_id: (doc, extract_text(samples_dir / doc.filename)) for doc in build_samples()
    }


__all__ = ["format_es", "oracle"]
