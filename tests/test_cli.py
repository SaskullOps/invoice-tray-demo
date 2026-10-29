import shutil

import pytest
from fastapi.testclient import TestClient

from invoice_tray import cli


@pytest.fixture
def one_sample(samples_dir, tmp_path):
    folder = tmp_path / "samples"
    folder.mkdir()
    shutil.copy(samples_dir / "01-suministros-f2026-0141.pdf", folder)
    return folder


def test_model_line_names_the_endpoint_host(one_sample, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("INVOICE_TRAY_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://not-read.invalid:1/v1")
    cli.main(["process", "--samples", str(one_sample), "--out", str(tmp_path / "out")])
    out = capsys.readouterr().out
    assert "Modelo: openai-compatible:qwen3:14b en 127.0.0.1:9\n" in out
    assert "not-read" not in out


def test_fake_model_line_has_no_endpoint(one_sample, tmp_path, capsys):
    cli.main(["process", "--fake-llm", "--samples", str(one_sample), "--out", str(tmp_path / "o")])
    assert "Modelo: respuestas grabadas de qwen3:14b\n" in capsys.readouterr().out


def _serve(monkeypatch, tmp_path, samples, *flags):
    cli.main(["process", "--fake-llm", "--samples", str(samples), "--out", str(tmp_path / "o")])
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app, **kwargs))
    cli.main(["serve", "--samples", str(samples), "--out", str(tmp_path / "o"), *flags])
    return captured


def test_non_loopback_host_prints_a_warning_and_is_an_allowed_host(
    one_sample, tmp_path, monkeypatch, capsys
):
    captured = _serve(monkeypatch, tmp_path, one_sample, "--host", "10.0.0.5")
    err = capsys.readouterr().err
    assert "AVISO" in err and "10.0.0.5" in err
    assert captured["host"] == "10.0.0.5"
    app = captured["app"]
    assert TestClient(app, base_url="http://10.0.0.5:8000").get("/").status_code == 200
    assert TestClient(app, base_url="http://127.0.0.1:8000").get("/").status_code == 200
    assert TestClient(app, base_url="http://evil.test").get("/").status_code == 400


def test_loopback_host_prints_no_warning(one_sample, tmp_path, monkeypatch, capsys):
    _serve(monkeypatch, tmp_path, one_sample)
    assert capsys.readouterr().err == ""
