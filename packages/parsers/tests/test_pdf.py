"""Tests for the PDF text extractor.

Generates tiny PDFs in-process with pypdf so no fixture files need to ship.
"""
from __future__ import annotations

import io
import zipfile

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from packages.parsers.pdf import (
    PDFExtractError,
    extract_key_numbers,
    extract_pages,
    extract_text,
    find_financial_sections,
)
from packages.parsers.pdf import _normalize_amount, _unwrap_if_zip


def _build_pdf(pages_text: list[str], *, page_size: tuple[int, int] = (300, 400)) -> bytes:
    """Build a minimal but real PDF containing `pages_text`, one page per entry."""
    writer = PdfWriter()
    font_dict = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    font_ref = writer._add_object(font_dict)

    for text in pages_text:
        page = writer.add_blank_page(width=page_size[0], height=page_size[1])
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref}),
        })
        # Each line gets emitted with a (...) Tj instruction; line breaks via T*.
        lines = text.splitlines() or [""]
        body = b"BT\n/F1 12 Tf\n50 " + str(page_size[1] - 30).encode() + b" Td\n"
        for i, line in enumerate(lines):
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            body += b"(" + escaped.encode("latin-1", errors="replace") + b") Tj\n"
            if i < len(lines) - 1:
                body += b"0 -15 Td\n"
        body += b"ET\n"

        stream = DecodedStreamObject()
        stream.set_data(body)
        page[NameObject("/Contents")] = writer._add_object(stream)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_extract_text_round_trip():
    pdf = _build_pdf(["Hello CreditLens"])
    text = extract_text(pdf)
    assert "Hello CreditLens" in text


def test_extract_pages_count_and_truncation():
    pdf = _build_pdf([f"Page {i}" for i in range(5)])
    pages = extract_pages(pdf, max_pages=3)
    assert len(pages) == 3
    assert "Page 0" in pages[0]
    assert "Page 2" in pages[2]


def test_extract_text_on_empty_bytes_raises():
    with pytest.raises(PDFExtractError):
        extract_text(b"")


def test_extract_text_on_garbage_raises():
    with pytest.raises(PDFExtractError):
        extract_text(b"this is not a pdf, not even close")


def test_find_financial_sections_balance_sheet():
    pages = [
        "Cover page — Annual Report 2024",
        "Letter from the CEO",
        "Balance Sheet\nTotal assets 12,345,678 EUR\nTotal liabilities 9,876,543 EUR",
        "Notes to the balance sheet continue here",
        "Income Statement\nRevenue 50,000,000\nNet income 2,500,000",
        "Cash flow statement\nOperating cash flow 3,000,000",
    ]
    sections = find_financial_sections(pages)
    assert "balance_sheet" in sections
    assert "Balance Sheet" in sections["balance_sheet"]
    assert "income_statement" in sections
    assert "Revenue 50,000,000" in sections["income_statement"]
    assert "cash_flow" in sections
    assert "Operating cash flow" in sections["cash_flow"]


def test_find_financial_sections_multilang():
    pages_de = ["Bilanz\nSumme Aktiva 1.000.000"]
    sections = find_financial_sections(pages_de)
    assert "balance_sheet" in sections

    pages_fr = ["Compte de résultat\nChiffre d'affaires 5 000 000"]
    sections = find_financial_sections(pages_fr)
    assert "income_statement" in sections

    pages_no = ["Resultatregnskap\nDriftsinntekter 4 500 000"]
    sections = find_financial_sections(pages_no)
    assert "income_statement" in sections


def test_find_financial_sections_empty():
    assert find_financial_sections([]) == {}
    assert find_financial_sections(["just a cover page with no headings"]) == {}


def test_extract_key_numbers_basic():
    text = (
        "Balance Sheet                       2024\n"
        "Total assets        12,345,678 EUR\n"
        "Total liabilities    9,876,543\n"
        "Total equity         2,469,135\n"
        "Income Statement\n"
        "Revenue             50,000,000\n"
        "Net income           2,500,000\n"
    )
    nums = extract_key_numbers(text)
    assert nums["total_assets"] == 12_345_678
    assert nums["total_liabilities"] == 9_876_543
    assert nums["total_equity"] == 2_469_135
    assert nums["revenue"] == 50_000_000
    assert nums["net_income"] == 2_500_000


def test_extract_key_numbers_handles_parens_as_negative():
    text = "Net loss   (1,234,567)"
    nums = extract_key_numbers(text)
    assert nums["net_income"] == -1_234_567


def test_extract_key_numbers_no_match_returns_empty():
    assert extract_key_numbers("") == {}
    assert extract_key_numbers("This text mentions nothing financial.") == {}


def test_normalize_amount_handles_locales():
    assert _normalize_amount("12,345.67") == 12345.67  # US
    assert _normalize_amount("12.345,67") == 12345.67  # EU
    assert _normalize_amount("12 345,67") == 12345.67  # FR
    assert _normalize_amount("12345") == 12345.0
    assert _normalize_amount("0,5") == 0.5
    assert _normalize_amount("xx") is None


def test_unwrap_zip_extracts_inner_pdf():
    pdf = _build_pdf(["Inside zip"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("report.pdf", pdf)
    zip_bytes = buf.getvalue()

    unwrapped = _unwrap_if_zip(zip_bytes, content_type="application/zip")
    assert unwrapped[:4] == b"%PDF"
    assert "Inside zip" in extract_text(unwrapped)


def test_unwrap_zip_passthrough_when_not_zip():
    pdf = _build_pdf(["plain"])
    assert _unwrap_if_zip(pdf, content_type="application/pdf") is pdf
