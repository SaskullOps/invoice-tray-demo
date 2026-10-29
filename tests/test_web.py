import re
import shutil

import pytest
from fastapi.testclient import TestClient

from invoice_tray.llm import RECORDINGS_DIR, FakeLLM
from invoice_tray.pipeline import evaluate, extract_folder, save_extracted, write_outputs
from invoice_tray.web import create_app

ORIGIN = "http://127.0.0.1:8000"


def browser(app, **headers) -> TestClient:
    """A client that sends what a browser sends for a same-origin form post."""
    return TestClient(app, base_url=ORIGIN, headers=headers or {"Origin": ORIGIN})


def prepare(samples_dir, out):
    results = extract_folder(samples_dir, FakeLLM())
    save_extracted(results, out / "extracted.json")
    write_outputs(evaluate(results, {}), out)


@pytest.fixture
def client(samples_dir, tmp_path):
    prepare(samples_dir, tmp_path)
    return browser(create_app(tmp_path, samples_dir)), tmp_path


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


# TestClient decodes the path twice, so "%" is followed by a non-hex character here.
ODD_NAME = "09-o'brien#1?x=100%"
ODD_PATH = "09-o%27brien%231%3Fx%3D100%25"


@pytest.fixture
def odd_client(samples_dir, tmp_path):
    samples, recordings, out = tmp_path / "samples", tmp_path / "rec", tmp_path / "out"
    for folder in (samples, recordings, out):
        folder.mkdir()
    shutil.copy(samples_dir / "09-limpiezas-l-2026-310.pdf", samples / f"{ODD_NAME}.pdf")
    shutil.copy(RECORDINGS_DIR / "09-limpiezas-l-2026-310.json", recordings / f"{ODD_NAME}.json")
    results = extract_folder(samples, FakeLLM(recordings))
    save_extracted(results, out / "extracted.json")
    write_outputs(evaluate(results, {}), out)
    return browser(create_app(out, samples)), out


def test_file_name_with_quote_hash_question_mark_and_percent_renders_safely(odd_client):
    app, _ = odd_client
    page = app.get("/").text
    assert "onclick" not in page
    assert "o'brien" not in page
    assert f'href="/doc/{ODD_PATH}"' in page
    assert f'data-href="/doc/{ODD_PATH}"' in page

    detail = app.get(f"/doc/{ODD_PATH}")
    assert detail.status_code == 200
    assert "o&#39;brien#1?x=100%" in detail.text
    links = set(re.findall(r'(?:href|action)="(/[^"]*)"', detail.text))
    assert links >= {f"/pdf/{ODD_PATH}", f"/doc/{ODD_PATH}/fix", f"/doc/{ODD_PATH}/approve"}
    assert app.get(f"/pdf/{ODD_PATH}").status_code == 200


def test_actions_on_an_odd_file_name_redirect_back_to_its_page(odd_client):
    app, out = odd_client
    response = app.post(f"/doc/{ODD_PATH}/reject", data={"note": "x"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/doc/{ODD_PATH}"
    page = app.get(response.headers["location"]).text
    assert f'action="/doc/{ODD_PATH}/undo"' in page
    assert ODD_NAME in (out / "review.json").read_text()


def test_foreign_host_header_is_refused(client):
    app, _ = client
    assert app.get("/").status_code == 200
    assert TestClient(app.app, base_url="http://localhost:8000").get("/").status_code == 200
    assert TestClient(app.app, base_url="http://evil.test").get("/").status_code == 400


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://evil.test"},
        {"Sec-Fetch-Site": "cross-site", "Origin": "http://evil.test"},
        {"Sec-Fetch-Site": "same-site", "Origin": "http://127.0.0.1:3000"},
        {"Sec-Fetch-Site": "cross-site", "Origin": ORIGIN},
        {"Origin": "null"},
        {},
    ],
)
def test_cross_origin_post_is_refused_and_changes_nothing(client, headers):
    app, out = client
    before = (out / "exceptions.json").read_text()
    raw = TestClient(app.app, base_url=ORIGIN, headers=headers)
    response = raw.post(
        "/doc/09-limpiezas-l-2026-310/approve", data={"note": "x"}, follow_redirects=False
    )
    assert response.status_code == 403
    assert not (out / "review.json").exists()
    assert (out / "exceptions.json").read_text() == before


@pytest.mark.parametrize("headers", [{"Sec-Fetch-Site": "same-origin"}, {"Origin": ORIGIN}])
def test_same_origin_post_works(client, headers):
    app, out = client
    response = browser(app.app, **headers).post(
        "/doc/09-limpiezas-l-2026-310/approve", data={"note": "ok"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert "09-limpiezas" in (out / "review.json").read_text()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("issue_date", "31/02/2026", "no es una fecha válida"),
        ("total", "abc", "no es un importe válido"),
        ("iban", "---", "no tiene letras ni números"),
    ],
)
def test_unparseable_fix_shows_error_and_keeps_document(client, field, value, message):
    app, out = client
    before = (out / "exceptions.json").read_text()
    response = app.post(
        "/doc/09-limpiezas-l-2026-310/fix",
        data={field: value, "note": "intento"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert message in response.text
    assert f"«{value}»" in response.text
    assert not (out / "review.json").exists()
    assert (out / "exceptions.json").read_text() == before


def test_pages_make_no_outside_requests(client):
    app, _ = client
    for path in ("/", "/doc/11-logistica-lg-2026-077"):
        page = app.get(path).text
        assert not re.search(r'(?:src|href)="(?:https?:)?//', page), path
