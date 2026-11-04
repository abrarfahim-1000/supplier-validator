"""PDF to text. No OCR and no vision models: a scanned PDF is unreadable by design.

pdfplumber is the primary reader, pypdf the fallback. Both are wrapped so a malformed
file becomes an :class:`ExtractionError` instead of a stack trace in the job runner.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber
from pdfminer.pdfexceptions import PDFException
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from checker.file_types import PDF_MAGIC

UNREADABLE_PDF = "EDGE-UNREADABLE-PDF"
NOT_A_PDF = "EDGE-NOT-A-PDF"
PDF_NOT_FOUND = "EDGE-PDF-NOT-FOUND"


class ExtractionError(Exception):
    """The document cannot be turned into text."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _pdfplumber_text(path: Path) -> str:
    try:
        with pdfplumber.open(path) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
    except (PDFException, OSError, ValueError):
        return ""


def _pypdf_text(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            return ""
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except (PyPdfError, OSError, ValueError):
        return ""


def extract_pdf_text(path: Path) -> str:
    if not path.is_file():
        raise ExtractionError(PDF_NOT_FOUND, "the uploaded PDF is no longer available")
    try:
        header = path.read_bytes()[: len(PDF_MAGIC)]
    except OSError as exc:
        raise ExtractionError(PDF_NOT_FOUND, "the uploaded PDF could not be opened") from exc
    if header != PDF_MAGIC:
        raise ExtractionError(NOT_A_PDF, "the file is not a PDF")

    text = _pdfplumber_text(path).strip()
    if text:
        return text
    text = _pypdf_text(path).strip()
    if text:
        return text
    raise ExtractionError(
        UNREADABLE_PDF,
        "no text could be extracted; the PDF may be scanned, encrypted or empty"
        " (OCR is not used, so a person must check it)",
    )
