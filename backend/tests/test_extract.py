from __future__ import annotations

import pytest

from checker.extract import (
    NOT_A_PDF,
    PDF_NOT_FOUND,
    UNREADABLE_PDF,
    ExtractionError,
    extract_pdf_text,
)
from pdf_factory import blank_pdf, write_pdf


def test_text_pdf_is_extracted(tmp_path) -> None:
    path = tmp_path / "quote.pdf"
    write_pdf(path, ["Synthetic Fabrics Ltd", "Item A 100 piece 10.00 1,000.00"])
    text = extract_pdf_text(path)
    assert "Synthetic Fabrics Ltd" in text
    assert "Item A" in text


def test_blank_pdf_is_unreadable_not_guessed(tmp_path) -> None:
    path = tmp_path / "blank.pdf"
    blank_pdf(path)
    with pytest.raises(ExtractionError) as excinfo:
        extract_pdf_text(path)
    assert excinfo.value.code == UNREADABLE_PDF


def test_non_pdf_is_rejected(tmp_path) -> None:
    path = tmp_path / "quote.pdf"
    path.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(ExtractionError) as excinfo:
        extract_pdf_text(path)
    assert excinfo.value.code == NOT_A_PDF


def test_missing_file_is_reported(tmp_path) -> None:
    with pytest.raises(ExtractionError) as excinfo:
        extract_pdf_text(tmp_path / "gone.pdf")
    assert excinfo.value.code == PDF_NOT_FOUND
