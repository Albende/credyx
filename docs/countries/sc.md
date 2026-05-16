# Seychelles — FSA (paid) + MERJ Exchange (free, listed only)

## Identifiers

- `COMPANY_NUMBER` — FSA-issued International Business Company number.
  Free-form alphanumeric, typically 4–15 characters. Normalized to
  upper-case with whitespace and dashes stripped.

## Sources

- **FSA Seychelles** — https://fsaseychelles.sc/
  - The Financial Services Authority is the official regulator of
    Seychelles IBCs, CSLs (Companies Special Licence), and foundations.
  - The IBC database is **not publicly searchable**. Full registry
    extracts (Certificate of Good Standing, Memorandum & Articles,
    Register of Directors / Members) are issued only on payment per
    document, via a licensed Seychelles registered agent.
  - Beneficial-owner data is held privately under the Seychelles
    Beneficial Ownership Act 2020 — accessible to authorities, not the
    public.
  - Under the MVP's non-negotiable "no paid commercial APIs" rule, this
    source is **out of scope**.
- **MERJ Exchange** — https://merj.exchange/
  - Seychelles' licensed securities exchange (formerly Trop-X). Each
    listed issuer has a public profile page with downloadable annual
    reports. The listed universe is very small (a handful of issuers).
  - Used here only as a `document_url` link for the verified listed
    issuers — financials remain unstructured PDFs.

## Test companies

There are no publicly searchable test companies for non-listed SC IBCs
by design (the FSA database is closed). For MERJ-listed issuers, browse
https://merj.exchange/issuers and verify the slug exists before adding
to `_MERJ_ISSUER_SLUGS`.

## Status

**Wired with limitations.**

- `search_by_name` → `AdapterNotImplementedError` (no free name search).
- `lookup_by_identifier` → `AdapterNotImplementedError` (no free
  per-identifier lookup; FSA full extracts are paid per document).
- `fetch_financials` → returns MERJ issuer page link for known listed
  issuers; `[]` otherwise.
- `health_check` → probes `merj.exchange` for reachability. Reports
  `DEGRADED` even when the probe succeeds, because the underlying
  jurisdiction has no free general-purpose registry.

## Offshore notoriety

The Seychelles is one of the most-cited jurisdictions in international
offshore-leak datasets (Panama Papers, Paradise Papers, Pandora Papers)
and is regularly named in OFAC, EU, and UK sanctions designations
involving shell-company structures. Seychelles IBCs have historically
been used for sanctions evasion, anonymous beneficial ownership, and
trade-based money laundering.

**Operational rule for any SC counterparty:**

1. Run the company name and all known associated parties through
   `packages._global.opensanctions.OpenSanctionsClient.screen()` **before**
   the LLM sees the file. Any hit is an automatic red flag — surface it
   in `RiskAssessment.red_flags`.
2. Treat absence of registry data as a risk factor, not a neutral
   signal. The MVP's risk engine prompt should be told that SC data
   opacity is itself negative for the credit score.
3. Recommend `REVIEW` or `REJECT` by default for SC IBCs without
   substantive third-party evidence of operations (audited financials,
   confirmed banking, beneficial-owner declaration).

This is enforced operationally, not in the adapter — the adapter's job
is to return only what is true and free. The risk pipeline is
responsible for downgrading credit confidence on opacity.

## Phase-2 upgrade path

Paid integration via a licensed Seychelles registered agent (Sterling,
Vistra, Trident Trust, Appleby) can return structured extracts on demand
for ~USD 100–250 per document. Out of scope for the free MVP.
