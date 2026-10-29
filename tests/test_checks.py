import pytest
from conftest import oracle

from invoice_tray.checks import detect_document_type, run_checks
from invoice_tray.grounding import ground
from invoice_tray.schema import QNumber


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
