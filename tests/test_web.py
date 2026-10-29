import pytest
from fastapi.testclient import TestClient

from invoice_tray.llm import FakeLLM
from invoice_tray.pipeline import evaluate, extract_folder, save_extracted, write_outputs
from invoice_tray.web import create_app


@pytest.fixture
def client(samples_dir, tmp_path):
    results = extract_folder(samples_dir, FakeLLM())
    save_extracted(results, tmp_path / "extracted.json")
    write_outputs(evaluate(results, {}), tmp_path)
    return TestClient(create_app(tmp_path, samples_dir)), tmp_path


def test_index_lists_documents_in_spanish(client):
    app, _ = client
    page = app.get("/").text
    assert "Bandeja de facturas" in page
    assert "Suministros Ejemplo SL" in page
    assert "listas para el ERP" in page


def test_detail_highlights_quotes(client):
    app, _ = client
    page = app.get("/doc/01-suministros-f2026-0141").text
    assert '<mark data-keys="total"' in page
    assert "Cita verificada" in page


def test_detail_shows_discarded_fields_for_delivery_note(client):
    app, _ = client
    page = app.get("/doc/10-suministros-albaran-ab-5521").text
    assert "no coincide con la cita" in page


def test_fix_moves_exception_to_ready_csv(client):
    app, out = client
    response = app.post(
        "/doc/09-limpiezas-l-2026-310/fix",
        data={"iban": "ES9121000418450200051332", "note": "Confirmado por teléfono"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "09-limpiezas-l-2026-310" in (out / "ready.csv").read_text()
    assert "09-limpiezas" not in (out / "exceptions.json").read_text()


def test_reject_and_undo(client):
    app, out = client
    app.post("/doc/05-suministros-f2026-0141-reenvio/reject", data={"note": "duplicada"})
    assert "05-suministros" not in (out / "exceptions.json").read_text()
    app.post("/doc/05-suministros-f2026-0141-reenvio/undo")
    assert "05-suministros" in (out / "exceptions.json").read_text()


def test_unknown_document_is_404(client):
    app, _ = client
    assert app.get("/doc/nope").status_code == 404
