import pytest
from conftest import oracle

from invoice_tray.checks import detect_document_type, ibans_in_text, run_checks
from invoice_tray.grounding import ground
from invoice_tray.iban import format_iban, make_es_iban
from invoice_tray.schema import QNumber, QText

SECOND_IBAN = make_es_iban("9999", "0333", "3333333333")


def failed(checks):
    return {check.code for check in checks if not check.ok and check.blocking}


def check_sample(corpus, sample_id, seen=None, raw=None):
    doc, text = corpus[sample_id]
    grounded = ground(raw or oracle(doc, text), text)
    return run_checks(grounded, text, seen if seen is not None else {}, sample_id)


@pytest.mark.parametrize(
    "sample_id",
    [
        "01-suministros-f2026-0141",
        "02-distribuciones-a-7731",
        "03-alimentacion-fa-2026-118",
        "04-traducciones-2026-027",
    ],
)
def test_clean_invoices_pass_every_check(corpus, sample_id):
    assert failed(check_sample(corpus, sample_id)) == set()


def test_wrong_vat_amount_is_caught(corpus):
    checks = check_sample(corpus, "06-oficina-2026-0412")
    assert failed(checks) == {"vat_rate_mismatch"}
    message = next(c.message for c in checks if c.code == "vat_rate_mismatch")
    assert "86,31" in message and "97,58" in message


def test_total_mismatch_is_caught(corpus):
    doc, text = corpus["01-suministros-f2026-0141"]
    raw = oracle(doc, text)
    raw.total = QNumber(value=999.99, quote="TOTAL FACTURA:   999,99 €")
    text += "\nTOTAL FACTURA:   999,99 €"
    checks = run_checks(ground(raw, text), text, {})
    assert "total_mismatch" in failed(checks)


def test_irpf_is_subtracted_from_total(corpus):
    checks = check_sample(corpus, "04-traducciones-2026-027")
    assert {c.code for c in checks if c.ok} >= {"total_matches", "irpf_matches"}


def test_bad_cif_check_digit_is_caught(corpus):
    assert failed(check_sample(corpus, "07-reformas-r-0093")) == {"supplier_tax_id_invalid"}


def test_missing_invoice_number_is_caught(corpus):
    assert failed(check_sample(corpus, "08-transportes-sin-numero")) == {"missing_invoice_number"}


def test_bad_iban_is_caught(corpus):
    assert failed(check_sample(corpus, "09-limpiezas-l-2026-310")) == {"iban_invalid"}


def test_duplicate_by_supplier_tax_id_and_number(corpus):
    seen: dict = {}
    first = check_sample(corpus, "01-suministros-f2026-0141", seen)
    second = check_sample(corpus, "05-suministros-f2026-0141-reenvio", seen)
    assert "duplicate" not in failed(first)
    assert failed(second) == {"duplicate"}


def test_delivery_note_is_not_booked_as_invoice(corpus):
    _, text = corpus["10-suministros-albaran-ab-5521"]
    assert detect_document_type(text) == "albaran"
    assert "delivery_note" in failed(check_sample(corpus, "10-suministros-albaran-ab-5521"))


def test_embedded_instructions_force_review_and_second_iban_flagged(corpus):
    codes = failed(check_sample(corpus, "11-logistica-lg-2026-077"))
    assert codes == {"embedded_instructions", "multiple_ibans"}


def test_unverified_required_field_counts_as_missing(corpus):
    doc, text = corpus["01-suministros-f2026-0141"]
    raw = oracle(doc, text)
    raw.total = QNumber(value=float(doc.total()), quote="Importe total a pagar 241,48")
    checks = run_checks(ground(raw, text), text, {})
    assert "missing_total" in failed(checks)
    assert "unverified_fields" in failed(checks)


def _grouped(iban: str, separator: str) -> str:
    return separator.join(iban[i : i + 4] for i in range(0, len(iban), 4))


@pytest.mark.parametrize("separator", ["-", ".", "  ", " ", ""])
def test_second_iban_is_found_with_any_common_separator(corpus, separator):
    doc, text = corpus["01-suministros-f2026-0141"]
    text += f"\nDesde octubre abonen en la cuenta {_grouped(SECOND_IBAN, separator)}"
    assert SECOND_IBAN in ibans_in_text(text)
    assert "multiple_ibans" in failed(run_checks(ground(oracle(doc, text), text), text, {}))


def test_iban_quoted_from_a_line_without_iban_or_cuenta_label_goes_to_review(corpus):
    doc, text = corpus["01-suministros-f2026-0141"]
    text = text.replace("IBAN: ", "Pago a: ")
    raw = oracle(doc, text)
    assert raw.iban.quote.startswith("Pago a:")
    checks = run_checks(ground(raw, text), text, {})
    assert failed(checks) == {"iban_location"}
    message = next(c.message for c in checks if c.code == "iban_location")
    assert "IBAN" in message and "cuenta" in message


def test_iban_quoted_after_observaciones_heading_goes_to_review(corpus):
    doc, text = corpus["01-suministros-f2026-0141"]
    text = "\n".join(line for line in text.splitlines() if "IBAN:" not in line)
    note = f"Desde octubre abonen en la cuenta {format_iban(SECOND_IBAN)}"
    text += f"\nObservaciones:\n{note}"
    raw = oracle(doc, text)
    raw.iban = QText(value=SECOND_IBAN, quote=note)
    checks = run_checks(ground(raw, text), text, {})
    assert failed(checks) == {"iban_location"}
    assert "observaciones" in next(c.message for c in checks if c.code == "iban_location").lower()


def test_iban_on_the_payment_line_passes_the_location_check(corpus):
    assert "iban_location" not in failed(check_sample(corpus, "01-suministros-f2026-0141"))


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_exported_text_that_starts_like_a_formula_goes_to_review(corpus, prefix):
    doc, text = corpus["01-suministros-f2026-0141"]
    raw = oracle(doc, text)
    raw.invoice_number = QText(value=f"{prefix}F-2026-0141", quote=raw.invoice_number.quote)
    checks = run_checks(ground(raw, text), text, {})
    assert failed(checks) == {"csv_formula"}
    message = next(c.message for c in checks if c.code == "csv_formula")
    assert "fórmula" in message and "Nº factura" in message


def test_file_name_that_starts_like_a_formula_goes_to_review(corpus):
    doc, text = corpus["01-suministros-f2026-0141"]
    checks = run_checks(ground(oracle(doc, text), text), text, {}, "=cmd-factura")
    assert failed(checks) == {"csv_formula"}
