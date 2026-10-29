"""Local review UI (Spanish copy). Decisions are stored in out/review.json."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from .checks import field_label
from .grounding import STATUS_LABELS_ES, GroundedDoc
from .money import format_es
from .pipeline import EDITABLE_FIELDS, Evaluated, Review, evaluate, load_extracted, write_outputs

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

STATUS_ES = {
    "ready": "Lista",
    "exception": "A revisar",
    "archived": "Archivada",
    "rejected": "Descartada",
}

AMOUNT_FIELDS = {"total", "irpf_amount"}


def _spans(doc: GroundedDoc) -> list[tuple[str, tuple[int, int]]]:
    spans = [(key, field.span) for key, field in doc.all_grounded() if field.span and field.ok]
    spans += [
        (f"line_{index}", line.span)
        for index, line in enumerate(doc.line_items)
        if line.span and line.status == "verified"
    ]
    return spans


def highlight(text: str, doc: GroundedDoc | None) -> Markup:
    if doc is None:
        return escape(text)
    spans = _spans(doc)
    cuts = sorted({0, len(text), *[p for _, span in spans for p in span]})
    parts = []
    for start, end in zip(cuts, cuts[1:], strict=False):
        keys = [key for key, (s, e) in spans if s <= start and end <= e]
        chunk = escape(text[start:end])
        parts.append(
            Markup(f'<mark data-keys="{" ".join(keys)}">{chunk}</mark>') if keys else chunk
        )
    return Markup("").join(parts)


def display(key: str, value) -> str:
    if value is None:
        return "—"
    if key in AMOUNT_FIELDS or key.startswith(("base_", "vat_")):
        return f"{format_es(value)} €"
    if key == "irpf_rate":
        return f"{float(value):g} %"
    if key == "issue_date" or key == "due_date":
        year, month, day = str(value).split("-")
        return f"{day}/{month}/{year}"
    return str(value)


class Store:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.review_path = out_dir / "review.json"
        self.extracted = load_extracted(out_dir / "extracted.json")

    def review(self) -> dict[str, dict]:
        if self.review_path.exists():
            return json.loads(self.review_path.read_text("utf-8"))
        return {}

    def docs(self) -> list[Evaluated]:
        return evaluate(self.extracted, self.review())

    def get(self, doc_id: str) -> Evaluated:
        for doc in self.docs():
            if doc.doc_id == doc_id:
                return doc
        raise HTTPException(404, "Documento no encontrado")

    def decide(self, doc_id: str, decision: Review | None) -> None:
        self.get(doc_id)
        review = self.review()
        if decision is None:
            review.pop(doc_id, None)
        else:
            review[doc_id] = decision.model_dump()
        self.review_path.write_text(json.dumps(review, indent=2, ensure_ascii=False), "utf-8")
        write_outputs(self.docs(), self.out_dir)


def create_app(out_dir: Path, samples_dir: Path) -> FastAPI:
    app = FastAPI(title="Bandeja de facturas", docs_url=None, redoc_url=None)
    store = Store(out_dir)
    env = TEMPLATES.env
    env.globals.update(
        STATUS_ES=STATUS_ES,
        STATUS_LABELS_ES=STATUS_LABELS_ES,
        display=display,
        field_label=field_label,
        format_es=format_es,
    )
    env.filters["highlight"] = lambda doc: highlight(doc.text, doc.grounded)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        docs = store.docs()
        counts = {key: sum(doc.status == key for doc in docs) for key in STATUS_ES}
        model = docs[0].model if docs else ""
        return TEMPLATES.TemplateResponse(
            request, "index.html", {"docs": docs, "counts": counts, "model": model}
        )

    @app.get("/doc/{doc_id}", response_class=HTMLResponse)
    def detail(request: Request, doc_id: str):
        docs = store.docs()
        doc = store.get(doc_id)
        queue = [d.doc_id for d in docs if d.status == "exception" and d.doc_id != doc_id]
        following = next((d for d in queue if d > doc_id), queue[0] if queue else None)
        return TEMPLATES.TemplateResponse(
            request,
            "detail.html",
            {"doc": doc, "editable": EDITABLE_FIELDS, "next_id": following},
        )

    def _back(doc_id: str) -> RedirectResponse:
        return RedirectResponse(f"/doc/{doc_id}", status_code=303)

    @app.post("/doc/{doc_id}/approve")
    async def approve(request: Request, doc_id: str):
        form = await request.form()
        store.decide(doc_id, Review(action="approve", note=str(form.get("note", ""))))
        return _back(doc_id)

    @app.post("/doc/{doc_id}/reject")
    async def reject(request: Request, doc_id: str):
        form = await request.form()
        store.decide(doc_id, Review(action="reject", note=str(form.get("note", ""))))
        return _back(doc_id)

    @app.post("/doc/{doc_id}/fix")
    async def fix(request: Request, doc_id: str):
        form = await request.form()
        doc = store.get(doc_id)
        keys = list(EDITABLE_FIELDS)
        if doc.grounded:
            keys += [
                key for key, _ in doc.grounded.all_grounded() if key.startswith(("base_", "vat_"))
            ]
        current = {key: display_raw(doc, key) for key in keys}
        fields = {
            key: str(form[key])
            for key in keys
            if key in form and str(form[key]).strip() and str(form[key]).strip() != current[key]
        }
        store.decide(doc_id, Review(action="fix", fields=fields, note=str(form.get("note", ""))))
        return _back(doc_id)

    @app.post("/doc/{doc_id}/undo")
    def undo(doc_id: str):
        store.decide(doc_id, None)
        return _back(doc_id)

    @app.get("/pdf/{doc_id}")
    def pdf(doc_id: str):
        doc = store.get(doc_id)
        return FileResponse(samples_dir / doc.file, media_type="application/pdf")

    @app.get("/export/ready.csv")
    def ready_csv():
        return FileResponse(out_dir / "ready.csv", media_type="text/csv", filename="ready.csv")

    env.globals["display_raw"] = display_raw
    return app


def display_raw(doc: Evaluated, key: str) -> str:
    """Value as typed in the fix form (empty when the field was discarded)."""
    if doc.grounded is None:
        return ""
    fields = dict(doc.grounded.all_grounded())
    field = fields.get(key)
    if field is None or not field.ok or field.value is None:
        return ""
    if isinstance(field.value, float):
        return format_es(field.value) if key != "irpf_rate" else f"{field.value:g}"
    return str(field.value)
