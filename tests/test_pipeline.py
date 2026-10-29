import csv
import json

from invoice_tray.export import CSV_COLUMNS
from invoice_tray.llm import RECORDINGS_DIR, FakeLLM
from invoice_tray.pipeline import evaluate, extract_folder, write_outputs


def run(samples_dir, tmp_path, review=None):
    results = extract_folder(samples_dir, FakeLLM(RECORDINGS_DIR))
    evaluated = evaluate(results, review or {})
    write_outputs(evaluated, tmp_path)
    return evaluated


def test_fake_run_routes_each_sample_as_the_manifest_expects(samples_dir, tmp_path):
    manifest = json.loads((samples_dir / "manifest.json").read_text())
    evaluated = {doc.doc_id: doc for doc in run(samples_dir, tmp_path)}
    for sample in manifest:
        doc = evaluated[sample["sample_id"]]
        if sample["expected_reasons"]:
            assert doc.status == "exception", doc.doc_id
            assert set(sample["expected_reasons"]) <= {r.code for r in doc.reasons}, doc.doc_id
        else:
            assert doc.status == "ready", (doc.doc_id, [r.message for r in doc.reasons])


def test_injected_instructions_are_ignored_in_fake_mode(samples_dir, tmp_path):
    doc = next(d for d in run(samples_dir, tmp_path) if d.doc_id.startswith("11-"))
    assert doc.grounded.total.value == 560.84
    assert doc.grounded.iban.value == "ES3899990011161122334455"
    assert doc.status == "exception"
    assert "embedded_instructions" in {r.code for r in doc.reasons}


def test_ready_csv_has_documented_columns_and_values(samples_dir, tmp_path):
    run(samples_dir, tmp_path)
    with (tmp_path / "ready.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        assert reader.fieldnames == CSV_COLUMNS
        rows = {row["document_id"]: row for row in reader}
    assert set(rows) == {
        "01-suministros-f2026-0141",
        "02-distribuciones-a-7731",
        "03-alimentacion-fa-2026-118",
        "04-traducciones-2026-027",
    }
    row = rows["04-traducciones-2026-027"]
    assert row["supplier_tax_id"] == "Y0012345P"
    assert row["base_21"] == "498.00"
    assert row["vat_21"] == "104.58"
    assert row["irpf_rate"] == "15"
    assert row["irpf_amount"] == "74.70"
    assert row["total"] == "527.88"
    assert row["issue_date"] == "2026-10-10"
    assert row["review"] == "auto"


def test_exceptions_json_lists_reasons(samples_dir, tmp_path):
    run(samples_dir, tmp_path)
    exceptions = json.loads((tmp_path / "exceptions.json").read_text())
    assert len(exceptions) == 7
    assert all(item["reasons"] for item in exceptions)
    assert all({"code", "message"} <= set(item["reasons"][0]) for item in exceptions)


def test_human_fix_moves_exception_to_ready(samples_dir, tmp_path):
    review = {
        "09-limpiezas-l-2026-310": {
            "action": "fix",
            "fields": {"iban": "ES9121000418450200051332"},
            "note": "IBAN confirmado por teléfono",
        }
    }
    evaluated = {d.doc_id: d for d in run(samples_dir, tmp_path, review)}
    assert evaluated["09-limpiezas-l-2026-310"].status == "ready"
    rows = (tmp_path / "ready.csv").read_text().splitlines()
    assert any(
        line.startswith("09-limpiezas") and line.endswith("manual;09-limpiezas-l-2026-310.pdf")
        for line in rows
    )


def test_approving_a_delivery_note_archives_it_without_export(samples_dir, tmp_path):
    review = {"10-suministros-albaran-ab-5521": {"action": "approve", "note": "cruzado"}}
    evaluated = {d.doc_id: d for d in run(samples_dir, tmp_path, review)}
    assert evaluated["10-suministros-albaran-ab-5521"].status == "archived"
    assert "10-suministros" not in (tmp_path / "ready.csv").read_text()
