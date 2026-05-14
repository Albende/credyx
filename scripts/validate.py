"""End-to-end validation harness.

For each canonical test company in the spec, runs:

  1. search by name  → confirms the correct entity appears
  2. lookup by identifier
  3. fetch financials (just counts what was returned)
  4. run risk analysis via the engine (if KIE_AI_API_KEY is set)

Writes a matrix to docs/VALIDATION_REPORT.md. Skips steps with reason when
the adapter is not implemented or credentials are missing.

Run:

    python scripts/validate.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.adapters._base.errors import AdapterNotImplementedError  # noqa: E402
from packages.adapters.registry import get_adapter  # noqa: E402
from packages.risk import get_risk_engine  # noqa: E402
from packages.shared.models import IdentifierType  # noqa: E402


TEST_COMPANIES = [
    # (country, search_name, id_type, id_value, expected_substr)
    ("GB", "BP", IdentifierType.COMPANY_NUMBER, "00102498", "BP"),
    ("DE", "BMW", IdentifierType.HRB, "42243", "BMW"),
    ("FR", "TotalEnergies", IdentifierType.SIREN, "542051180", "TOTAL"),
    ("PL", "Orlen", IdentifierType.KRS, "0000028860", "ORLEN"),
    ("NL", "ASML", IdentifierType.KVK, "17014545", "ASML"),
    ("ES", "Inditex", IdentifierType.CIF, "A15022510", "INDITEX"),
    ("IT", "Eni", IdentifierType.VAT, "00484960588", "Eni"),
    ("SE", "Volvo", IdentifierType.ORG_NR, "5560125790", "Volvo"),
    ("TR", "Turk Hava Yollari", IdentifierType.VKN, "8350023902", "Hava"),
    ("US", "Apple", IdentifierType.CIK, "0000320193", "Apple"),
    # bonus countries we implemented:
    ("CZ", "ČEZ", IdentifierType.ICO, "45274649", "ČEZ"),
    ("NO", "Equinor", IdentifierType.ORG_NR, "923609016", "Equinor"),
    ("FI", "Nokia", IdentifierType.BUSINESS_ID, "0112038-9", "Nokia"),
]

STEPS = ["search", "lookup", "financials", "risk"]


async def run_for(company) -> dict[str, str]:
    country, search_name, id_type, id_value, expected_substr = company
    row: dict[str, str] = {
        "country": country,
        "search_name": search_name,
        "id_type": id_type.value,
        "id_value": id_value,
        "search": "skip",
        "lookup": "skip",
        "financials": "skip",
        "risk": "skip",
        "notes": "",
    }

    adapter = get_adapter(country)
    if adapter is None:
        row["notes"] = "no adapter"
        return row

    # 1. Search.
    try:
        results = await adapter.search_by_name(search_name, limit=5)
        if any(expected_substr.lower() in (r.name or "").lower() for r in results):
            row["search"] = "pass"
        elif results:
            row["search"] = f"partial({len(results)} results, no obvious match)"
        else:
            row["search"] = "empty"
    except AdapterNotImplementedError as exc:
        row["search"] = "not_implemented"
        row["notes"] = str(exc)[:100]
    except Exception as exc:
        row["search"] = f"error: {type(exc).__name__}"
        row["notes"] = str(exc)[:200]

    # 2. Lookup.
    details = None
    try:
        details = await adapter.lookup_by_identifier(id_type, id_value)
        row["lookup"] = "pass" if details else "not_found"
    except AdapterNotImplementedError:
        row["lookup"] = "not_implemented"
    except Exception as exc:
        row["lookup"] = f"error: {type(exc).__name__}"
        if not row["notes"]:
            row["notes"] = str(exc)[:200]

    # 3. Financials.
    filings = []
    try:
        filings = await adapter.fetch_financials(id_value, years=5)
        row["financials"] = f"pass ({len(filings)})" if filings else "empty"
    except AdapterNotImplementedError:
        row["financials"] = "not_implemented"
    except Exception as exc:
        row["financials"] = f"error: {type(exc).__name__}"

    # 4. Risk analysis — only if we have details and a KIE_AI key.
    if not os.getenv("KIE_AI_API_KEY"):
        row["risk"] = "skip (no KIE_AI_API_KEY)"
    elif details:
        try:
            engine = get_risk_engine()
            assessment = await engine.analyze(details, filings)
            row["risk"] = f"pass (score={assessment.score} rec={assessment.recommendation.value})"
        except Exception as exc:
            row["risk"] = f"error: {type(exc).__name__}"
            if not row["notes"]:
                row["notes"] = str(exc)[:200]
    else:
        row["risk"] = "skip (no details)"

    return row


async def main(out_path: Path) -> int:
    rows: list[dict[str, str]] = []
    for company in TEST_COMPANIES:
        print(f"-> {company[0]}: {company[1]} ({company[3]})", flush=True)
        t0 = time.monotonic()
        row = await run_for(company)
        row["elapsed"] = f"{time.monotonic() - t0:.1f}s"
        rows.append(row)
        print(
            f"  search={row['search']}  lookup={row['lookup']}  "
            f"financials={row['financials']}  risk={row['risk']}  ({row['elapsed']})"
        )

    md = ["# CreditLens — Validation Report", "", "Run: `python scripts/validate.py`", "",
          "| Country | Search | Lookup | Financials | Risk | Notes |",
          "|---------|:------:|:------:|:----------:|:----:|-------|"]
    for r in rows:
        md.append(
            f"| {r['country']} ({r['search_name']}) | {r['search']} | {r['lookup']} | "
            f"{r['financials']} | {r['risk']} | {r['notes'][:120]} |"
        )

    md.append("")
    counts = {"pass": 0, "not_implemented": 0, "error": 0, "skip": 0, "empty": 0}
    for r in rows:
        for step in STEPS:
            v = r[step]
            if v.startswith("pass"):
                counts["pass"] += 1
            elif v.startswith("not_implemented"):
                counts["not_implemented"] += 1
            elif v.startswith("error"):
                counts["error"] += 1
            elif v.startswith("skip"):
                counts["skip"] += 1
            elif v.startswith("empty") or v.startswith("not_found") or v.startswith("partial"):
                counts["empty"] += 1
    total = len(rows) * len(STEPS)
    md += [
        "## Summary",
        "",
        f"- Steps run: **{total}**",
        f"- ✅ pass: **{counts['pass']}**",
        f"- 🟡 partial / empty / not_found: **{counts['empty']}**",
        f"- ⚪ not_implemented: **{counts['not_implemented']}**",
        f"- ⚪ skipped: **{counts['skip']}**",
        f"- 🔴 errors: **{counts['error']}**",
    ]
    out_path.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="docs/VALIDATION_REPORT.md")
    args = parser.parse_args()
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    sys.exit(asyncio.run(main(out)))
