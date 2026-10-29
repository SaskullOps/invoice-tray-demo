"""Spanish tax id validation (NIF, NIE, CIF) using the official check-digit algorithms."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

NIF_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
CIF_CONTROL_LETTERS = "JABCDEFGHI"
CIF_ORG_LETTERS = "ABCDEFGHJNPQRSUVW"
CIF_DIGIT_ONLY = "ABEH"
CIF_LETTER_ONLY = "KNPQRSW"
NIE_PREFIX = {"X": "0", "Y": "1", "Z": "2"}


class TaxIdKind(StrEnum):
    NIF = "NIF"
    NIE = "NIE"
    CIF = "CIF"
    UNKNOWN = "desconocido"


@dataclass(frozen=True)
class TaxIdResult:
    value: str
    kind: TaxIdKind
    valid: bool
    reason: str = ""


def normalize_tax_id(value: str) -> str:
    cleaned = re.sub(r"[\s.\-/]", "", value or "").upper()
    if cleaned.startswith("ES") and len(cleaned) == 11:
        cleaned = cleaned[2:]
    return cleaned


def _cif_control_digit(digits: str) -> int:
    total = 0
    for index, char in enumerate(digits):
        number = int(char)
        if index % 2 == 0:
            doubled = number * 2
            total += doubled // 10 + doubled % 10
        else:
            total += number
    return (10 - total % 10) % 10


def make_nif(digits: str) -> str:
    return f"{digits}{NIF_LETTERS[int(digits) % 23]}"


def make_nie(prefix: str, digits: str) -> str:
    return f"{prefix}{digits}{NIF_LETTERS[int(NIE_PREFIX[prefix] + digits) % 23]}"


def make_cif(letter: str, digits: str) -> str:
    control = _cif_control_digit(digits)
    if letter in CIF_LETTER_ONLY:
        return f"{letter}{digits}{CIF_CONTROL_LETTERS[control]}"
    return f"{letter}{digits}{control}"


def validate_tax_id(value: str) -> TaxIdResult:
    tax_id = normalize_tax_id(value)
    if re.fullmatch(r"\d{8}[A-Z]", tax_id):
        expected = NIF_LETTERS[int(tax_id[:8]) % 23]
        if tax_id[8] != expected:
            return TaxIdResult(tax_id, TaxIdKind.NIF, False, "Letra de control del NIF incorrecta")
        return TaxIdResult(tax_id, TaxIdKind.NIF, True)

    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", tax_id):
        expected = NIF_LETTERS[int(NIE_PREFIX[tax_id[0]] + tax_id[1:8]) % 23]
        if tax_id[8] != expected:
            return TaxIdResult(tax_id, TaxIdKind.NIE, False, "Letra de control del NIE incorrecta")
        return TaxIdResult(tax_id, TaxIdKind.NIE, True)

    if re.fullmatch(rf"[{CIF_ORG_LETTERS}]\d{{7}}[0-9A-J]", tax_id):
        control = _cif_control_digit(tax_id[1:8])
        letter, given = tax_id[0], tax_id[8]
        as_digit, as_letter = str(control), CIF_CONTROL_LETTERS[control]
        if letter in CIF_DIGIT_ONLY:
            allowed = {as_digit}
        elif letter in CIF_LETTER_ONLY:
            allowed = {as_letter}
        else:
            allowed = {as_digit, as_letter}
        if given not in allowed:
            return TaxIdResult(tax_id, TaxIdKind.CIF, False, "Dígito de control del CIF incorrecto")
        return TaxIdResult(tax_id, TaxIdKind.CIF, True)

    return TaxIdResult(tax_id, TaxIdKind.UNKNOWN, False, "Formato de NIF/NIE/CIF no reconocido")
