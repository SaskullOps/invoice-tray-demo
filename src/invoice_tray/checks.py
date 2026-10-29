"""Deterministic checks in plain code. No model is involved in any of these decisions."""

from __future__ import annotations

import re
from decimal import Decimal

from pydantic import BaseModel

from .export import looks_like_formula
from .grounding import Grounded, GroundedDoc, Status, _alnum, normalize
from .iban import validate_iban
from .money import CENT, cents, format_es, to_decimal
from .taxid import validate_tax_id

KNOWN_VAT_RATES = {Decimal(rate) for rate in ("0", "4", "5", "10", "21")}
TOTAL_TOLERANCE = Decimal("0.02")

REQUIRED_FIELDS_ES = {
    "supplier_name": "el nombre del proveedor",
    "supplier_tax_id": "el NIF/CIF del proveedor",
    "invoice_number": "el número de factura",
    "issue_date": "la fecha de emisión",
    "total": "el total",
}

FIELD_LABELS_ES = {
    "document_type": "Tipo de documento",
    "supplier_name": "Proveedor",
    "supplier_tax_id": "NIF/CIF proveedor",
    "invoice_number": "Nº factura",
    "issue_date": "Fecha de emisión",
    "due_date": "Vencimiento",
    "irpf_rate": "IRPF %",
    "irpf_amount": "Retención IRPF",
    "total": "Total",
    "iban": "IBAN",
}

INJECTION_PATTERNS = [
    r"ignora\w* (?:\w+ ){0,3}instrucciones",
    r"ignore (?:\w+ ){0,3}instructions",
    r"sistema automatico",
    r"asistente de ia",
    r"no la envies a revision",
    r"you are (?:an?|the) (?:ai|assistant|model)",
    r"system prompt",
]

IBAN_IN_TEXT = re.compile(
    r"\b[A-Z]{2}\d{2}(?:[\s.\-]?[A-Z0-9]{4}){4,7}(?:[\s.\-]?[A-Z0-9]{1,4})?\b"
)
IBAN_LINE_LABELS = ("iban", "cuenta")
NOTES_HEADING = "observaciones"
EXPORTED_TEXT_FIELDS = (
    "supplier_name",
    "supplier_tax_id",
    "invoice_number",
    "issue_date",
    "due_date",
    "iban",
)


def field_label(key: str) -> str:
    if key.startswith("base_"):
        return f"Base {key[5:]} %"
    if key.startswith("vat_"):
        return f"IVA {key[4:]} %"
    return FIELD_LABELS_ES.get(key, key)


class Check(BaseModel):
    code: str
    ok: bool
    message: str
    blocking: bool = True


def _pass(code: str, message: str) -> Check:
    return Check(code=code, ok=True, message=message)


def _fail(code: str, message: str, blocking: bool = True) -> Check:
    return Check(code=code, ok=False, message=message, blocking=blocking)


def _amount(field: Grounded) -> Decimal | None:
    return to_decimal(field.value) if field.ok else None


def detect_document_type(text: str) -> str:
    folded = normalize(text)
    if "albaran" in folded:
        return "albaran"
    if "factura" in folded:
        return "factura"
    return "desconocido"


def duplicate_key(doc: GroundedDoc) -> tuple[str, str] | None:
    if not (doc.supplier_tax_id.ok and doc.invoice_number.ok):
        return None
    return _alnum(str(doc.supplier_tax_id.value)), _alnum(str(doc.invoice_number.value))


def ibans_in_text(text: str) -> set[str]:
    flattened = re.sub(r"\s+", " ", text.upper())
    return {re.sub(r"[\s.\-]", "", match) for match in IBAN_IN_TEXT.findall(flattened)}


def run_checks(
    doc: GroundedDoc, text: str, seen: dict[tuple[str, str], str], doc_id: str = ""
) -> list[Check]:
    checks: list[Check] = []

    detected = detect_document_type(text)
    if detected == "albaran":
        checks.append(
            _fail(
                "delivery_note", "Es un albarán, no una factura: archivar y cruzar con su factura"
            )
        )
    elif detected != "factura":
        checks.append(_fail("unknown_document_type", "No parece una factura"))
    else:
        checks.append(_pass("document_type", "Documento de tipo factura"))
    if doc.document_type.ok and doc.document_type.value != detected and detected != "desconocido":
        checks.append(
            _fail("document_type_disagrees", "El modelo y las reglas no coinciden en el tipo")
        )

    unverified = [
        field_label(name)
        for name, field in doc.all_grounded()
        if field.status not in (Status.VERIFIED, Status.MISSING, Status.CORRECTED)
    ]
    unverified += [
        f"línea «{(line.quote or '?')[:30]}»"
        for line in doc.line_items
        if line.status != Status.VERIFIED
    ]
    if unverified:
        checks.append(
            _fail(
                "unverified_fields",
                "Campos descartados por no tener cita verificable: " + ", ".join(unverified),
            )
        )

    if detected != "albaran":
        for name, label in REQUIRED_FIELDS_ES.items():
            if not getattr(doc, name).ok:
                checks.append(_fail(f"missing_{name}", f"Falta {label}"))
        if not doc.vat_lines:
            checks.append(_fail("missing_vat_lines", "No hay desglose de IVA"))

    checks.extend(_tax_id_checks(doc))
    checks.extend(_vat_checks(doc))
    checks.extend(_iban_checks(doc, text))
    checks.extend(_injection_checks(text))
    checks.extend(_formula_checks(doc, doc_id))

    key = duplicate_key(doc)
    if key is not None and detected != "albaran":
        if key in seen and seen[key] != doc_id:
            checks.append(
                _fail("duplicate", f"Duplicada: mismo proveedor y número que {seen[key]}")
            )
        else:
            seen.setdefault(key, doc_id)
            checks.append(_pass("not_duplicate", "No está duplicada en este lote"))
    return checks


def _tax_id_checks(doc: GroundedDoc) -> list[Check]:
    if not doc.supplier_tax_id.ok:
        return []
    result = validate_tax_id(str(doc.supplier_tax_id.value))
    if not result.valid:
        return [_fail("supplier_tax_id_invalid", f"{result.value}: {result.reason}")]
    return [_pass("supplier_tax_id_valid", f"{result.kind} {result.value} con control correcto")]


def _vat_checks(doc: GroundedDoc) -> list[Check]:
    checks: list[Check] = []
    bases = Decimal("0")
    vats = Decimal("0")
    complete = bool(doc.vat_lines)
    for line in doc.vat_lines:
        rate = to_decimal(line.rate)
        base, vat = _amount(line.base), _amount(line.vat)
        if rate is None or base is None or vat is None:
            complete = False
            continue
        bases += base
        vats += vat
        rate_label = f"{float(rate):g} %"
        if rate not in KNOWN_VAT_RATES:
            checks.append(
                _fail("vat_rate_unknown", f"Tipo de IVA {rate_label} no habitual en España")
            )
        expected = cents(base * rate / 100)
        if abs(expected - vat) > CENT:
            checks.append(
                _fail(
                    "vat_rate_mismatch",
                    f"IVA {rate_label}: {format_es(base)} × {rate_label} = "
                    f"{format_es(expected)} €, "
                    f"la factura indica {format_es(vat)} €",
                )
            )
        else:
            checks.append(_pass("vat_rate_matches", f"IVA {rate_label} cuadra con su base"))

    irpf = _amount(doc.irpf_amount) or Decimal("0")
    irpf_rate = _amount(doc.irpf_rate)
    if irpf_rate and complete:
        expected_irpf = cents(bases * irpf_rate / 100)
        if abs(expected_irpf - irpf) > CENT:
            checks.append(
                _fail(
                    "irpf_mismatch",
                    f"IRPF {float(irpf_rate):g} %: se esperaban {format_es(expected_irpf)} €, "
                    f"la factura indica {format_es(irpf)} €",
                )
            )
        else:
            checks.append(_pass("irpf_matches", f"Retención IRPF {float(irpf_rate):g} % cuadra"))

    total = _amount(doc.total)
    if complete and total is not None:
        expected_total = bases + vats - irpf
        if abs(expected_total - total) > TOTAL_TOLERANCE:
            checks.append(
                _fail(
                    "total_mismatch",
                    f"Bases + IVA − IRPF = {format_es(expected_total)} €, "
                    f"el total indica {format_es(total)} €",
                )
            )
        else:
            checks.append(_pass("total_matches", "Bases + IVA − IRPF = total"))

    lines = doc.line_items
    if complete and lines and all(line.status == Status.VERIFIED for line in lines):
        line_sum = sum((to_decimal(line.amount) or Decimal("0")) for line in lines)
        if abs(line_sum - bases) > TOTAL_TOLERANCE:
            checks.append(
                _fail(
                    "lines_mismatch",
                    f"Las líneas suman {format_es(line_sum)} €, las bases {format_es(bases)} €",
                )
            )
        else:
            checks.append(_pass("lines_match", "Las líneas suman la base imponible"))
    return checks


def _iban_checks(doc: GroundedDoc, text: str) -> list[Check]:
    checks: list[Check] = []
    if doc.iban.ok:
        result = validate_iban(str(doc.iban.value))
        if result.valid:
            checks.append(_pass("iban_valid", "IBAN con dígitos de control correctos"))
        else:
            checks.append(_fail("iban_invalid", f"{result.value}: {result.reason}"))
    elif detect_document_type(text) == "factura":
        checks.append(_fail("iban_missing", "Sin IBAN: confirmar forma de pago", blocking=False))
    checks.extend(_iban_location_checks(doc.iban, text))
    found = ibans_in_text(text)
    if len(found) > 1:
        checks.append(
            _fail(
                "multiple_ibans",
                f"El documento contiene {len(found)} IBAN distintos: confirmar cuál es el bueno",
            )
        )
    return checks


def _iban_location_checks(iban: Grounded, text: str) -> list[Check]:
    """A model-picked IBAN must come from a payment line, not from free text such as a note."""
    if iban.status != Status.VERIFIED or iban.span is None:
        return []
    start, end = iban.span
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    lines = normalize(text[line_start : line_end if line_end >= 0 else len(text)])
    if NOTES_HEADING in normalize(text[:start]):
        return [
            _fail(
                "iban_location",
                "El IBAN extraído aparece después de «Observaciones», no en los datos de pago: "
                "confirmar la cuenta",
            )
        ]
    if not any(label in lines for label in IBAN_LINE_LABELS):
        return [
            _fail(
                "iban_location",
                "El IBAN extraído no está en una línea con la etiqueta IBAN o cuenta: "
                "confirmar la cuenta",
            )
        ]
    return []


def _formula_checks(doc: GroundedDoc, doc_id: str) -> list[Check]:
    fields = [
        field_label(name)
        for name in EXPORTED_TEXT_FIELDS
        if getattr(doc, name).ok and looks_like_formula(str(getattr(doc, name).value))
    ]
    if looks_like_formula(doc_id):
        fields.append("Nombre del archivo")
    if not fields:
        return []
    return [
        _fail(
            "csv_formula",
            "Texto que una hoja de cálculo trataría como fórmula (empieza por =, +, -, @, "
            "tabulador o retorno de carro) en: " + ", ".join(fields),
        )
    ]


def _injection_checks(text: str) -> list[Check]:
    folded = normalize(text)
    hits = [pattern for pattern in INJECTION_PATTERNS if re.search(pattern, folded)]
    if hits:
        return [
            _fail(
                "embedded_instructions",
                "El documento contiene instrucciones dirigidas a un sistema automático: "
                "se ignoran y la factura pasa a revisión",
            )
        ]
    return []
