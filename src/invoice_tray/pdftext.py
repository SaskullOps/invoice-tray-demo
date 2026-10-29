"""Text-layer extraction from PDFs. Scanned images are out of scope (no OCR)."""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader


def extract_text(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
    lines = [re.sub(r" {3,}", "   ", line).rstrip() for page in pages for line in page.splitlines()]
    return "\n".join(line for line in lines if line.strip())
