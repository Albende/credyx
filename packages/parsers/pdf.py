"""PDF text extraction for filing documents.

Uses `pypdf` (pure Python, no system deps). Designed for annual reports from
European registries — many of which are PDF-only (Bundesanzeiger, Pappers,
NBB, Brønnøysund). Caps at `max_pages` because reports run 200+ pages and
only the financial section is interesting to the LLM.

If the PDF is encrypted, scanned (no text layer), or otherwise unparseable
we raise `PDFExtractError`. We never invent content.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from typing import Iterable

import httpx
from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)


class PDFExtractError(Exception):
    """Raised when a PDF cannot be parsed (encrypted, scanned, corrupt)."""


# Section headings across EN/FR/DE/ES/IT/PT/NL. Match-anywhere case-insensitive.
_BALANCE_HEADINGS = (
    "balance sheet",
    "statement of financial position",
    "consolidated balance sheet",
    "bilan",
    "bilan consolidé",
    "etat de la situation financière",
    "état de la situation financière",
    "bilanz",
    "konzernbilanz",
    "vermögenslage",
    "balance",
    "balance de situación",
    "stato patrimoniale",
    "balanço",
    "balanço patrimonial",
    "balans",
    "geconsolideerde balans",
)

_INCOME_HEADINGS = (
    "income statement",
    "statement of profit or loss",
    "statement of comprehensive income",
    "profit and loss",
    "profit & loss",
    "p&l",
    "p & l",
    "compte de résultat",
    "compte de resultat",
    "résultat consolidé",
    "gewinn- und verlustrechnung",
    "gewinn und verlustrechnung",
    "gewinnausweis",
    "cuenta de resultados",
    "cuenta de pérdidas y ganancias",
    "conto economico",
    "demonstração de resultados",
    "demonstracao de resultados",
    "winst-en-verliesrekening",
    "winst en verliesrekening",
    "resultatregnskap",  # Norwegian
)

_CASHFLOW_HEADINGS = (
    "cash flow statement",
    "statement of cash flows",
    "cash flows",
    "tableau des flux de trésorerie",
    "tableau de flux de tresorerie",
    "kapitalflussrechnung",
    "geldflussrechnung",
    "estado de flujos de efectivo",
    "rendiconto finanziario",
    "demonstração dos fluxos de caixa",
    "kasstroomoverzicht",
    "kontantstrømoppstilling",  # Norwegian
)


def extract_text(pdf_bytes: bytes, *, max_pages: int = 50) -> str:
    """Extract plain text from a PDF byte stream.

    Pages beyond `max_pages` are skipped. Raises `PDFExtractError` for
    encrypted or unreadable documents.
    """
    pages = extract_pages(pdf_bytes, max_pages=max_pages)
    return "\n\n".join(pages).strip()


def extract_pages(pdf_bytes: bytes, *, max_pages: int = 50) -> list[str]:
    """Per-page text list. Length is bounded by `max_pages`."""
    if not pdf_bytes:
        raise PDFExtractError("empty pdf bytes")
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except PdfReadError as exc:
        raise PDFExtractError(f"pypdf cannot read document: {exc}") from exc
    except Exception as exc:  # pypdf raises a grab-bag of errors on malformed PDFs
        raise PDFExtractError(f"unreadable pdf: {exc}") from exc

    if reader.is_encrypted:
        # Try empty password (common for "encrypted with no password" PDFs).
        try:
            if not reader.decrypt(""):
                raise PDFExtractError("pdf is encrypted")
        except Exception as exc:
            raise PDFExtractError(f"pdf is encrypted: {exc}") from exc

    pages: list[str] = []
    total = min(len(reader.pages), max_pages)
    for i in range(total):
        try:
            text = reader.pages[i].extract_text() or ""
        except Exception as exc:
            logger.warning("page %d extraction failed: %s", i, exc)
            text = ""
        pages.append(text)

    if not any(p.strip() for p in pages):
        raise PDFExtractError(
            "no extractable text — pdf is likely scanned (needs OCR) or image-only"
        )
    return pages


async def extract_from_url(
    url: str,
    *,
    http_client: httpx.AsyncClient | None = None,
    max_pages: int = 50,
    max_bytes: int = 50 * 1024 * 1024,
) -> str:
    """Download `url` then extract text. Handles plain PDF and ZIP-wrapped PDF.

    Pass an existing `http_client` for connection reuse and to share rate
    limits; otherwise a one-shot client is built. Refuses payloads larger
    than `max_bytes` (default 50 MiB).
    """
    own_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=60.0, follow_redirects=True)
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        body = resp.content
        if len(body) > max_bytes:
            raise PDFExtractError(
                f"payload too large: {len(body)} bytes exceeds {max_bytes}"
            )
        content_type = (resp.headers.get("content-type") or "").lower()
    finally:
        if own_client:
            await client.aclose()

    pdf_bytes = _unwrap_if_zip(body, content_type=content_type)
    return extract_text(pdf_bytes, max_pages=max_pages)


def find_financial_sections(pages: list[str]) -> dict[str, str]:
    """Heuristically locate balance sheet / income statement / cash flow sections.

    A section spans from the page that first mentions one of the known
    headings to either the next-section heading or 3 pages later, whichever
    is sooner. Returned dict only contains keys we actually found — callers
    should treat missing keys as "not detected, not empty".
    """
    if not pages:
        return {}

    headings_by_section: dict[str, tuple[str, ...]] = {
        "balance_sheet": _BALANCE_HEADINGS,
        "income_statement": _INCOME_HEADINGS,
        "cash_flow": _CASHFLOW_HEADINGS,
    }

    starts: dict[str, int] = {}
    for section, headings in headings_by_section.items():
        idx = _first_page_matching(pages, headings)
        if idx is not None:
            starts[section] = idx

    if not starts:
        return {}

    sorted_starts = sorted(starts.items(), key=lambda kv: kv[1])
    out: dict[str, str] = {}
    for i, (section, start_idx) in enumerate(sorted_starts):
        next_boundary = (
            sorted_starts[i + 1][1] if i + 1 < len(sorted_starts) else len(pages)
        )
        end_idx = min(start_idx + 3, next_boundary, len(pages))
        slice_pages = pages[start_idx:end_idx]
        out[section] = "\n\n".join(slice_pages).strip()
    return out


# Examples it catches (whitespace-tolerant, comma or dot thousand sep, optional currency):
#   Total assets ........ 12,345,678 EUR
#   Total liabilities    9 876 543
#   Net income/(loss)    (1.234.567)
_NUMBER_PATTERNS: dict[str, tuple[str, ...]] = {
    "total_assets": (
        r"total\s+assets",
        r"total\s+actif",
        r"summe\s+aktiva",
        r"bilanzsumme",
        r"total\s+activo",
        r"totale\s+attivo",
        r"sum\s+eiendeler",
    ),
    "total_liabilities": (
        r"total\s+liabilities",
        r"total\s+passif",
        r"summe\s+passiva",
        r"summe\s+verbindlichkeiten",
        r"total\s+pasivo",
        r"totale\s+passivo",
        r"sum\s+gjeld",
    ),
    "total_equity": (
        r"total\s+equity",
        r"shareholders[''’]?\s+equity",
        r"capitaux\s+propres",
        r"eigenkapital",
        r"patrimonio\s+neto",
        r"patrimonio\s+netto",
        r"sum\s+egenkapital",
    ),
    "revenue": (
        r"total\s+revenue",
        r"net\s+revenue",
        r"net\s+sales",
        r"^\s*revenue\b",
        r"turnover",
        r"chiffre\s+d[''’]?affaires",
        r"umsatzerlöse",
        r"umsatzerloese",
        r"ingresos",
        r"ricavi",
        r"driftsinntekter",
    ),
    "net_income": (
        r"net\s+income",
        r"net\s+profit",
        r"net\s+loss",
        r"profit\s+for\s+the\s+(year|period)",
        r"résultat\s+net",
        r"resultat\s+net",
        r"jahresüberschuss",
        r"jahresueberschuss",
        r"jahresfehlbetrag",
        r"resultado\s+neto",
        r"utile\s+netto",
        r"årsresultat",
    ),
}

_AMOUNT_RE = re.compile(
    r"[\(\-]?\s*"          # optional opening paren or minus
    r"\d{1,3}"             # leading digits
    r"(?:[ \u00a0.,]\d{3})*"   # grouped thousands
    r"(?:[.,]\d+)?"        # optional decimal
    r"\s*\)?"              # optional closing paren
)


def extract_key_numbers(text: str) -> dict[str, float]:
    """Best-effort regex extraction of headline financial totals.

    Returns a partial dict mapping canonical keys (`total_assets`,
    `total_liabilities`, `total_equity`, `revenue`, `net_income`) to floats
    when a confident match is found on the same line. Never invents numbers
    — keys absent from the dict mean "not detected".
    """
    if not text:
        return {}

    out: dict[str, float] = {}
    lines = text.splitlines()
    for line in lines:
        lower = line.lower()
        for key, patterns in _NUMBER_PATTERNS.items():
            if key in out:
                continue
            for pat in patterns:
                m = re.search(pat, lower)
                if not m:
                    continue
                tail = line[m.end():]
                amounts = _extract_amounts(tail)
                if not amounts:
                    continue
                out[key] = amounts[0]
                break
    return out


def _extract_amounts(s: str) -> list[float]:
    """Pull plausible numeric tokens out of a fragment, in source order."""
    results: list[float] = []
    for raw in _AMOUNT_RE.findall(s):
        cleaned = raw.strip()
        if not any(ch.isdigit() for ch in cleaned):
            continue
        negative = cleaned.startswith("(") and cleaned.endswith(")") or cleaned.startswith("-")
        normalized = _normalize_amount(cleaned.strip("()- "))
        if normalized is None:
            continue
        results.append(-normalized if negative else normalized)
    return results


def _normalize_amount(token: str) -> float | None:
    """Convert "12,345.67", "12.345,67", "12 345,67", "12345" → float."""
    t = token.replace("\u00a0", " ").replace(" ", "")
    if not t:
        return None
    has_dot = "." in t
    has_comma = "," in t
    try:
        if has_dot and has_comma:
            # The rightmost separator is the decimal mark.
            if t.rfind(",") > t.rfind("."):
                t = t.replace(".", "").replace(",", ".")
            else:
                t = t.replace(",", "")
        elif has_comma:
            # Comma is either thousands grouping (12,345) or decimal (12,5).
            parts = t.split(",")
            if len(parts) == 2 and len(parts[1]) != 3:
                t = parts[0] + "." + parts[1]
            else:
                t = t.replace(",", "")
        # `.`-only and bare-digit tokens parse straight.
        return float(t)
    except ValueError:
        return None


def _first_page_matching(pages: list[str], needles: Iterable[str]) -> int | None:
    needle_list = [n.lower() for n in needles]
    for idx, page in enumerate(pages):
        lower = page.lower()
        if any(n in lower for n in needle_list):
            return idx
    return None


def _unwrap_if_zip(body: bytes, *, content_type: str) -> bytes:
    """If `body` is a ZIP, pull the first .pdf entry out of it.

    EU registries (e.g. Bundesanzeiger) occasionally serve annual reports as
    zipped PDFs. We accept either content-type-based or magic-byte detection.
    """
    is_zip_ct = "zip" in content_type
    is_zip_magic = body[:2] == b"PK"
    if not (is_zip_ct or is_zip_magic):
        return body
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            pdf_names = [n for n in zf.namelist() if n.lower().endswith(".pdf")]
            if not pdf_names:
                raise PDFExtractError("zip contains no pdf entry")
            with zf.open(pdf_names[0]) as fh:
                return fh.read()
    except zipfile.BadZipFile as exc:
        # Magic bytes lied; treat as plain body.
        if is_zip_magic and not is_zip_ct:
            return body
        raise PDFExtractError(f"bad zip: {exc}") from exc
