"""Two stages: extract (model + quote grounding, slow) and evaluate (plain code, instant).

Evaluation is re-run on every review decision, so a human fix goes through the same checks.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from .checks import Check, field_label, run_checks
from .export import write_csv
from .grounding import Grounded, GroundedDoc, Status, _alnum, ground
from .llm import LLM
from .money import parse_es_numbers
from .pdftext import extract_text
from .schema import RawExtraction

NUMERIC_FIELDS = {"irpf_rate", "irpf_amount", "total"}
DATE_FIELDS = {"issue_date", "due_date"}
CODE_FIELDS = {"supplier_tax_id", "iban"}
EDITABLE_FIELDS = [
    "supplier_name",
    "supplier_tax_id",
    "invoice_number",
    "issue_date",
    "due_date",
    "total",
    "irpf_rate",
    "irpf_amount",
    "iban",
]


class Extracted(BaseModel):
    doc_id: str
    file: str
    text: str
    model: str
    grounded: GroundedDoc | None = None
    error: str | None = None
    seconds: float = 0
    stats: dict = Field(default_factory=dict)


class Review(BaseModel):
    action: Literal["approve", "fix", "reject"]
    fields: dict[str, str] = Field(default_factory=dict)
    note: str = ""


class Evaluated(Extracted):
    checks: list[Check] = Field(default_factory=list)
    reasons: list[Check] = Field(default_factory=list)
    warnings: list[Check] = Field(default_factory=list)
    status: Literal["ready", "exception", "archived", "rejected"] = "exception"
    confidence: Literal["alta", "media", "baja", "revisada"] = "baja"
    review: Review | None = None


def extract_one(path: Path, llm: LLM, attempts: int = 2) -> Extracted:
    doc_id = path.stem
    text = extract_text(path)
    started = time.monotonic()
    error = None
    for _ in range(attempts):
        try:
            raw = RawExtraction.model_validate_json(llm.extract(doc_id, text))
            grounded = ground(raw, text)
        except (ValidationError, ValueError, ArithmeticError) as exc:
            error = f"Respuesta del modelo no válida: {exc.__class__.__name__}"
            continue
        except Exception as exc:  # noqa: BLE001 - surface any transport failure as an exception item
            error = f"Error del modelo: {exc}"
            break
        return Extracted(
            doc_id=doc_id,
            file=path.name,
            text=text,
            model=llm.name,
            grounded=grounded,
            seconds=round(time.monotonic() - started, 1),
            stats=getattr(llm, "last_stats", {}) or {},
        )
    return Extracted(
        doc_id=doc_id,
        file=path.name,
        text=text,
        model=llm.name,
        error=error,
        seconds=round(time.monotonic() - started, 1),
    )


def extract_folder(
    folder: Path, llm: LLM, on_progress: Callable[[Extracted], None] | None = None
) -> list[Extracted]:
    results = []
    for path in sorted(folder.glob("*.pdf")):
        result = extract_one(path, llm)
        if on_progress:
            on_progress(result)
        results.append(result)
    return results


def _parse_fix(name: str, value: str) -> str | float | None:
    value = value.strip()
    if not value:
        return None
    if name in NUMERIC_FIELDS or name.startswith(("base_", "vat_")):
        numbers = parse_es_numbers(value)
        return float(numbers[0]) if numbers else None
    if name in DATE_FIELDS:
        match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
        if match:
            day, month, year = (int(part) for part in match.groups())
            return date(year, month, day).isoformat()
        return date.fromisoformat(value).isoformat()
    if name in CODE_FIELDS:
        return _alnum(value)
    return value


def fix_errors(fields: dict[str, str]) -> list[str]:
    """Spanish messages for every typed value the fix form cannot read; empty when all parse."""
    errors = []
    for name, raw_value in fields.items():
        if not raw_value.strip():
            continue
        try:
            value = _parse_fix(name, raw_value)
        except ValueError:
            value = None
        if value is not None and value != "":
            continue
        if name in DATE_FIELDS:
            problem = "no es una fecha válida (dd/mm/aaaa)"
        elif name in CODE_FIELDS:
            problem = "no tiene letras ni números"
        elif name in NUMERIC_FIELDS or name.startswith(("base_", "vat_")):
            problem = "no es un importe válido"
        else:
            problem = "no es un valor válido"
        errors.append(f"{field_label(name)}: «{raw_value.strip()}» {problem}")
    return errors


def apply_fix(doc: GroundedDoc, fields: dict[str, str]) -> GroundedDoc:
    fixed = doc.model_copy(deep=True)
    for name, raw_value in fields.items():
        try:
            value = _parse_fix(name, raw_value)
        except ValueError:
            continue
        if value is None:
            continue
        corrected = Grounded(value=value, claimed=value, status=Status.CORRECTED)
        if name in fixed.scalar_fields():
            original = getattr(fixed, name)
            corrected.quote, corrected.span = original.quote, original.span
            setattr(fixed, name, corrected)
            continue
        for line in fixed.vat_lines:
            rate = f"{line.rate:g}" if line.rate is not None else "?"
            if name == f"base_{rate}":
                line.base = corrected
            elif name == f"vat_{rate}":
                line.vat = corrected
    return fixed


def _confidence(doc: GroundedDoc | None, checks: list[Check]) -> str:
    failed = {check.code for check in checks if not check.ok}
    if (
        doc is None
        or "unverified_fields" in failed
        or any(c.startswith("missing_") for c in failed)
    ):
        return "baja"
    return "media" if failed else "alta"


def evaluate(results: list[Extracted], review: dict[str, dict | Review]) -> list[Evaluated]:
    seen: dict[tuple[str, str], str] = {}
    evaluated = []
    for result in sorted(results, key=lambda item: item.doc_id):
        decision = review.get(result.doc_id)
        if isinstance(decision, dict):
            decision = Review.model_validate(decision)
        grounded = result.grounded
        if grounded is not None and decision and decision.action == "fix":
            grounded = apply_fix(grounded, decision.fields)
        if grounded is None:
            checks = [Check(code="model_error", ok=False, message=result.error or "Sin respuesta")]
        else:
            checks = run_checks(grounded, result.text, seen, result.doc_id)
        reasons = [check for check in checks if not check.ok and check.blocking]
        warnings = [check for check in checks if not check.ok and not check.blocking]
        status = "exception" if reasons else "ready"
        confidence = _confidence(grounded, checks)
        if decision:
            confidence = "revisada"
            if decision.action == "approve" and grounded is not None:
                is_note = any(check.code == "delivery_note" for check in checks)
                status = "archived" if is_note else "ready"
            elif decision.action == "reject":
                status = "rejected"
        evaluated.append(
            Evaluated(
                **{**result.model_dump(), "grounded": grounded},
                checks=checks,
                reasons=reasons,
                warnings=warnings,
                status=status,
                confidence=confidence,
                review=decision,
            )
        )
    return evaluated


def write_outputs(evaluated: list[Evaluated], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv([doc for doc in evaluated if doc.status == "ready"], out_dir / "ready.csv")
    exceptions = [
        {
            "document_id": doc.doc_id,
            "file": doc.file,
            "supplier": doc.grounded.supplier_name.value if doc.grounded else None,
            "invoice_number": doc.grounded.invoice_number.value if doc.grounded else None,
            "confidence": doc.confidence,
            "reasons": [{"code": r.code, "message": r.message} for r in doc.reasons],
            "warnings": [{"code": w.code, "message": w.message} for w in doc.warnings],
        }
        for doc in evaluated
        if doc.status == "exception"
    ]
    (out_dir / "exceptions.json").write_text(
        json.dumps(exceptions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def save_extracted(results: list[Extracted], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [result.model_dump(mode="json") for result in results]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_extracted(path: Path) -> list[Extracted]:
    return [Extracted.model_validate(item) for item in json.loads(path.read_text("utf-8"))]
