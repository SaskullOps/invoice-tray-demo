from invoice_tray.grounding import Status, find_span, ground
from invoice_tray.schema import QNumber, QText, RawExtraction, VatLineRaw

TEXT = """Suministros Ejemplo SL      FACTURA
NIF: B00123455      Nº factura: F-2026-0141
Fecha de emisión: 03/10/2026
   Base imponible 21 %:   300,00 €
   Cuota IVA 21 %:   63,00 €
   TOTAL FACTURA:   363,00 €
IBAN: ES12 9999 0001 0000 0000 0001"""


def raw(**overrides) -> RawExtraction:
    data = {
        "document_type": QText(value="factura", quote="FACTURA"),
        "supplier_name": QText(value="Suministros Ejemplo SL", quote="Suministros Ejemplo SL"),
        "supplier_tax_id": QText(value="B00123455", quote="NIF: B00123455"),
        "invoice_number": QText(value="F-2026-0141", quote="Nº factura: F-2026-0141"),
        "issue_date": QText(value="2026-10-03", quote="Fecha de emisión: 03/10/2026"),
        "vat_lines": [
            VatLineRaw(
                rate=21,
                base=QNumber(value=300.0, quote="Base imponible 21 %: 300,00 €"),
                vat=QNumber(value=63.0, quote="Cuota IVA 21 %: 63,00 €"),
            )
        ],
        "total": QNumber(value=363.0, quote="TOTAL FACTURA: 363,00 €"),
    }
    data.update(overrides)
    return RawExtraction(**data)


def test_find_span_ignores_whitespace_and_case():
    start, end = find_span(TEXT, "total   factura: 363,00 €")
    assert TEXT[start:end] == "TOTAL FACTURA:   363,00 €"


def test_find_span_missing_returns_none():
    assert find_span(TEXT, "TOTAL FACTURA: 999,00 €") is None


def test_verified_fields_keep_values_and_spans():
    doc = ground(raw(), TEXT)
    assert doc.supplier_tax_id.status == Status.VERIFIED
    assert doc.supplier_tax_id.value == "B00123455"
    assert doc.issue_date.value == "2026-10-03"
    assert doc.total.value == 363.0
    assert doc.total.span is not None
    assert doc.vat_lines[0].base.status == Status.VERIFIED


def test_field_whose_quote_is_not_in_document_is_nulled_and_flagged():
    doc = ground(raw(total=QNumber(value=0.0, quote="TOTAL: 0,00 €")), TEXT)
    assert doc.total.value is None
    assert doc.total.status == Status.QUOTE_NOT_FOUND


def test_field_without_quote_is_nulled():
    doc = ground(raw(iban=QText(value="ES1299990001000000000001", quote=None)), TEXT)
    assert doc.iban.value is None
    assert doc.iban.status == Status.NO_QUOTE


def test_value_not_supported_by_its_quote_is_nulled():
    doc = ground(raw(total=QNumber(value=999.0, quote="TOTAL FACTURA: 363,00 €")), TEXT)
    assert doc.total.value is None
    assert doc.total.status == Status.VALUE_NOT_IN_QUOTE


def test_date_must_match_quote():
    doc = ground(
        raw(issue_date=QText(value="2026-03-10", quote="Fecha de emisión: 03/10/2026")), TEXT
    )
    assert doc.issue_date.status == Status.VALUE_NOT_IN_QUOTE


def test_tax_id_and_iban_compared_without_formatting():
    doc = ground(
        raw(
            iban=QText(value="ES12 9999 0001 0000 0000 0001", quote="ES12 9999 0001 0000 0000 0001")
        ),
        TEXT,
    )
    assert doc.iban.status == Status.VERIFIED
    assert doc.iban.value == "ES1299990001000000000001"


def test_extra_keys_from_model_are_dropped():
    data = raw().model_dump()
    data["approved"] = True
    data["status"] = "aprobada"
    parsed = RawExtraction.model_validate(data)
    assert not hasattr(parsed, "approved")
