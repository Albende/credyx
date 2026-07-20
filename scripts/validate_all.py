"""Full-coverage validation harness — every real adapter, live sources.

For each country with a real adapter, picks a canonical test company from
docs/countries/{cc}.md ("## Test companies" section) and runs:

  1. search_by_name
  2. lookup_by_identifier (primary identifier type)
  3. fetch_financials (records filing count + whether any document_url
     is present, i.e. a downloadable report)

Countries run concurrently (bounded), each step under a hard timeout, so a
full sweep of ~110 registries completes in minutes. Writes:

  - docs/VALIDATION_MATRIX.md   (human-readable matrix)
  - docs/validation_matrix.json (machine-readable, used for triage)

Run:

    python scripts/validate_all.py
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.adapters._base.errors import AdapterNotImplementedError  # noqa: E402
from packages.adapters.registry import get_adapter_registry  # noqa: E402

STEP_TIMEOUT = 45.0
CONCURRENCY = 10

ID_TOKEN = re.compile(r"[0-9][0-9A-Za-z.\-/]{2,}|\b[A-Z]{1,4}[0-9][0-9A-Za-z.\-/]*")

# Known-good seed data (from scripts/validate.py + country docs) — wins over
# whatever the doc parser extracts.
OVERRIDES: dict[str, tuple[str, str]] = {
    "GB": ("BP", "00102498"),
    "DE": ("BMW", "42243"),
    "FR": ("TotalEnergies", "542051180"),
    "PL": ("Orlen", "0000028860"),
    "NL": ("ASML", "17014545"),
    "ES": ("Inditex", "A15022510"),
    "IT": ("Eni", "00484960588"),
    "SE": ("Volvo", "5560125790"),
    "US": ("Apple", "0000320193"),
    "CZ": ("ČEZ", "45274649"),
    "NO": ("Equinor", "923609016"),
    "FI": ("Nokia", "0112038-9"),
    "LT": ("Ignitis", "301844044"),
    "SI": ("Krka", "5043611000"),
    "RS": ("NIS", "20084693"),
    "TR": ("Turk Hava Yollari", "8760047464"),
    # From country docs, formats the parser can't extract:
    "BO": ("YPFB", "1020601022"),
    "PT": ("EDP", "500697256"),
    "SN": ("Sonatel", "SNTS"),
    "MM": ("First Myanmar Investment", "FMI"),
    # Name-only (docs list no free identifier) — search coverage only:
    "AE": ("Emaar Properties", None),
    "AO": ("Sonangol", None),
    "BA": ("Elektroprivreda BiH", None),
    "CD": ("SCTP", None),
    "CI": ("Orange Cote d'Ivoire", None),
    "CM": ("SAFACAM", None),
    "ET": ("Ethiopian Airlines", None),
    "ME": ("Crnogorski Telekom", None),
    "MG": ("Telma", None),
    "MZ": ("Hidroelectrica de Cahora Bassa", None),
    "PY": ("Banco Continental", None),
    "SC": ("SACOS Group", None),
    "UZ": ("Uzbekneftegaz", None),
    "XK": ("Raiffeisen Bank Kosovo", None),
}


def _pick_id(fragment: str) -> str | None:
    ticked = re.findall(r"`([^`]+)`", fragment)
    for t in ticked:
        if any(c.isdigit() for c in t):
            return t.strip()
    if ticked:  # ticker-style IDs (e.g. `BATELCO`) have no digits
        return ticked[0].strip()
    tokens = ID_TOKEN.findall(fragment)
    return tokens[-1].strip() if tokens else None


def _parse_section(section: str):
    for line in section.splitlines():
        s = line.strip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) < 2 or not cells[0]:
                continue
            if set(cells[0]) <= set("-: ") or cells[0].lower() in ("company", "name"):
                continue
            # first ID-bearing cell wins — later columns are usually VAT variants
            for cell in cells[1:]:
                ident = _pick_id(cell)
                if ident:
                    yield cells[0], ident
                    break
        elif s.startswith("-"):
            frag = s.lstrip("- ").split(";")[0]
            ident = _pick_id(frag)
            name = re.split(r"[—–(`]", frag)[0].strip(" -.—")
            if ident and len(name) >= 2:
                yield name, ident


def load_test_companies() -> dict[str, tuple[str, str]]:
    """country -> (search_name, identifier) parsed from docs/countries."""
    out: dict[str, tuple[str, str]] = {}
    for doc in sorted((ROOT / "docs" / "countries").glob("*.md")):
        cc = doc.stem.upper()
        text = doc.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"##\s*Test [Cc]ompanies[^\n]*\n(.*?)(?:\n##|\Z)", text, re.S)
        if not m:
            continue
        for name, ident in _parse_section(m.group(1)):
            out[cc] = (name, ident)
            break
    out["GB"] = out.get("GB") or out.get("UK", ("BP", "00102498"))
    out.update(OVERRIDES)
    return out


async def verify_download(url: str) -> str:
    """GET the first bytes of a filing document — proves a user actually
    receives a real file, not just that a URL string exists."""
    from packages.adapters._base.http import build_http_client

    if url.startswith("/"):
        # App-relative: served by our own API (e.g. PL MSiG PDF slicing) —
        # requires an authenticated session; verified separately.
        return "APP ENDPOINT"
    try:
        async with build_http_client(timeout=25.0) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    return f"HTTP {resp.status_code}"
                ctype = (resp.headers.get("content-type") or "?").split(";")[0]
                body = b""
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) >= 4096:
                        break
                if not body:
                    return "EMPTY BODY"
                if ctype == "text/html":
                    m = re.search(rb"<title[^>]*>([^<]{0,90})", body, re.I)
                    title = (m.group(1).decode("utf-8", "replace").strip() if m else "")
                    return f"OK text/html [{title}]"
                return f"OK {ctype}"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL {type(exc).__name__}"


def classify(exc: Exception) -> str:
    if isinstance(exc, AdapterNotImplementedError):
        return "not_impl"
    if isinstance(exc, asyncio.TimeoutError):
        return "TIMEOUT"
    return f"FAIL:{type(exc).__name__}:{str(exc)[:140]}"


async def run_country(cc: str, adapter, name: str, ident: str, sem: asyncio.Semaphore) -> dict:
    row = {
        "country": cc,
        "adapter": type(adapter).__name__,
        "company": name,
        "identifier": ident,
        "id_type": getattr(adapter.primary_identifier, "value", str(adapter.primary_identifier)),
        "search": "",
        "lookup": "",
        "financials": "",
        "filings": 0,
        "has_download": False,
        "dl_check": "",
        "top_result": "",
        "error_detail": "",
    }
    async with sem:
        t0 = time.monotonic()
        try:
            results = await asyncio.wait_for(adapter.search_by_name(name, limit=5), STEP_TIMEOUT)
            if results:
                row["search"] = "pass"
                row["top_result"] = (results[0].name or "")[:60]
            else:
                row["search"] = "empty"
        except Exception as exc:  # noqa: BLE001 — harness records everything
            row["search"] = classify(exc)

        if ident is None:
            row["lookup"] = "no_id_testdata"
            row["financials"] = "no_id_testdata"
            row["elapsed"] = round(time.monotonic() - t0, 1)
            print(f"{cc}: search={row['search'][:30]} (name-only test) ({row['elapsed']}s)", flush=True)
            return row

        try:
            details = await asyncio.wait_for(
                adapter.lookup_by_identifier(adapter.primary_identifier, ident), STEP_TIMEOUT
            )
            row["lookup"] = "pass" if details else "not_found"
        except Exception as exc:  # noqa: BLE001
            row["lookup"] = classify(exc)

        try:
            filings = await asyncio.wait_for(adapter.fetch_financials(ident, years=3), STEP_TIMEOUT)
            row["filings"] = len(filings)
            row["has_download"] = any(getattr(f, "document_url", None) for f in filings)
            row["financials"] = f"pass({len(filings)})" if filings else "empty"
            if row["has_download"]:
                url = next(f.document_url for f in filings if getattr(f, "document_url", None))
                row["dl_check"] = await verify_download(url)
        except Exception as exc:  # noqa: BLE001
            row["financials"] = classify(exc)

        for step in ("search", "lookup", "financials"):
            if str(row[step]).startswith("FAIL") and not row["error_detail"]:
                row["error_detail"] = str(row[step])
        row["elapsed"] = round(time.monotonic() - t0, 1)
    print(
        f"{cc}: search={row['search'][:30]} lookup={row['lookup'][:30]} "
        f"financials={row['financials'][:30]} dl={row['has_download']} ({row['elapsed']}s)",
        flush=True,
    )
    return row


def verdict(row: dict) -> str:
    ok = [str(row[s]).startswith("pass") for s in ("search", "lookup", "financials")]
    ni = [str(row[s]) == "not_impl" for s in ("search", "lookup", "financials")]
    if all(ok):
        return "WORKING"
    if any(ok):
        return "PARTIAL"
    if all(ni):
        return "NOT_IMPLEMENTED"
    return "BROKEN"


async def main(only: set[str] | None = None) -> None:
    tests = load_test_companies()
    registry = get_adapter_registry()
    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = []
    missing_testdata = []
    for cc, adapter in sorted(registry.items()):
        if type(adapter).__name__ == "NotImplementedAdapter":
            continue
        if cc == "UK":  # alias of GB
            continue
        if only and cc not in only:
            continue
        if cc not in tests:
            missing_testdata.append(cc)
            continue
        name, ident = tests[cc]
        tasks.append(run_country(cc, adapter, name, ident, sem))

    print(f"validating {len(tasks)} countries (no test data: {missing_testdata})", flush=True)
    rows = await asyncio.gather(*tasks)
    rows = sorted(rows, key=lambda r: r["country"])
    for r in rows:
        r["verdict"] = verdict(r)

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    if only:  # partial run: merge over the previous full matrix
        prev_path = ROOT / "docs" / "validation_matrix.json"
        if prev_path.exists():
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
            merged = {r["country"]: r for r in prev.get("rows", [])}
            for r in rows:
                merged[r["country"]] = r
            rows = sorted(merged.values(), key=lambda r: r["country"])
            counts = {}
            for r in rows:
                counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    (ROOT / "docs" / "validation_matrix.json").write_text(
        json.dumps({"counts": counts, "missing_testdata": missing_testdata, "rows": rows}, indent=1),
        encoding="utf-8",
    )

    md = [
        "# Credyx — Full Validation Matrix",
        "",
        f"Run: `python scripts/validate_all.py` — {len(rows)} countries. Summary: {counts}",
        "",
        "| CC | Company | Verdict | Search | Lookup | Financials | DL | DL check | Error |",
        "|----|---------|---------|--------|--------|------------|----|----------|-------|",
    ]
    for r in rows:
        md.append(
            f"| {r['country']} | {r['company'][:24]} | **{r['verdict']}** | {r['search'][:28]} | "
            f"{r['lookup'][:28]} | {r['financials'][:28]} | {'✓' if r['has_download'] else ''} | "
            f"{r['dl_check'][:24]} | {r['error_detail'][:80]} |"
        )
    (ROOT / "docs" / "VALIDATION_MATRIX.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nSummary: {counts}", flush=True)
    print("wrote docs/VALIDATION_MATRIX.md + docs/validation_matrix.json", flush=True)


if __name__ == "__main__":
    only_arg = set(a.upper() for a in sys.argv[1].split(",")) if len(sys.argv) > 1 else None
    asyncio.run(main(only_arg))
