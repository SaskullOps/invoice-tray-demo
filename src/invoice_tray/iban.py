"""IBAN validation (ISO 13616 mod-97) and Spanish IBAN generation for synthetic samples."""

from __future__ import annotations

import re
from dataclasses import dataclass

COUNTRY_LENGTHS = {"ES": 24, "PT": 25, "FR": 27, "DE": 22, "IT": 27, "GB": 22, "NL": 18}


@dataclass(frozen=True)
class IbanResult:
    value: str
    valid: bool
    reason: str = ""


def normalize_iban(value: str) -> str:
    return re.sub(r"\s", "", value or "").upper()


def _mod97(iban: str) -> int:
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(char, 36)) for char in rearranged)
    return int(numeric) % 97


def validate_iban(value: str) -> IbanResult:
    iban = normalize_iban(value)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        return IbanResult(iban, False, "Formato de IBAN no válido")
    expected_length = COUNTRY_LENGTHS.get(iban[:2])
    if expected_length and len(iban) != expected_length:
        return IbanResult(iban, False, f"Longitud de IBAN incorrecta para {iban[:2]}")
    if _mod97(iban) != 1:
        return IbanResult(iban, False, "Dígitos de control del IBAN incorrectos (mod-97)")
    return IbanResult(iban, True)


def _ccc_digit(digits: str) -> str:
    weights = [1, 2, 4, 8, 5, 10, 9, 7, 3, 6]
    total = sum(int(d) * w for d, w in zip(digits.zfill(10), weights, strict=True))
    digit = 11 - total % 11
    return {10: "1", 11: "0"}.get(digit, str(digit))


def make_es_iban(bank: str, branch: str, account: str) -> str:
    national = f"{bank}{branch}{_ccc_digit('00' + bank + branch)}{_ccc_digit(account)}{account}"
    check = 98 - _mod97(f"ES00{national}")
    return f"ES{check:02d}{national}"


def format_iban(iban: str) -> str:
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))
