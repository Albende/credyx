# 🇨🇩 DR Congo — Guichet Unique / BCC (partial)

## Identifiers

- `COMPANY_NUMBER` → **RCCM** (Registre du Commerce et du Crédit
  Mobilier), OHADA-style format issued at registration. Example:
  `CD/KIN/RCCM/14-B-1234` (Kinshasa) or `CD/LSH/RCCM/16-B-0987`
  (Lubumbashi).
- `VAT` → **NIF** (Numéro d'Identification Fiscale), 14-character tax
  number assigned by the DGI. Example: `A0801234X`.

## Sources

- **Guichet Unique de Création d'Entreprise** —
  https://guichetunique.cd/
  One-stop portal for company creation (RCCM + NIF issuance). The public
  site is a JS-rendered marketing front-end; no documented REST API for
  search or lookup. Status confirmations are obtainable only via in-person
  counter visits or paid extract requests.
- **Banque Centrale du Congo (BCC)** — https://www.bcc.cd/
  Publishes macro-financial statistics and a register of supervised
  credit institutions (banks, microfinance). No per-company filings, no
  per-issuer financial statements.
- **Stock exchange** — none. DR Congo has no operating securities
  exchange; there is no equivalent of NSE / BVMAC.
- **OHADA** — DR Congo joined the Organisation pour l'Harmonisation en
  Afrique du Droit des Affaires in 2012, so RCCM format follows the
  OHADA pattern shared with 16 other West/Central African states. The
  OHADA regional digital registry pilot does not yet cover CD.

## Test companies (real)

| Name | Notes |
|------|-------|
| Société Commerciale des Transports et des Ports (SCTP) | Public-sector logistics operator (formerly ONATRA). |
| BIAC | Banque Internationale pour l'Afrique au Congo — historical commercial bank, BCC-supervised. |
| Bralima | Brasseries, Limonaderies et Malteries — Heineken subsidiary, largest brewer in DRC. |

## Status

🟡 **Partial / blocked** —

- `search_by_name`: ❌ raises `AdapterNotImplementedError` (no free
  machine-readable RCCM search).
- `lookup_by_identifier`: ❌ raises `AdapterNotImplementedError` for
  both RCCM and NIF (no free machine-readable endpoint).
- `fetch_financials`: 🟡 returns `[]` for every company (no free filings
  source — no stock exchange, BCC publishes only aggregate data).
- `health_check`: ✅ probes `guichetunique.cd` reachability.

## Recommended next step

1. Wire `OpenSanctions` and GLEIF as the fallback for name search until
   an official Guichet Unique API becomes available.
2. Track the OHADA regional digital registry rollout — once CD is in
   pilot, a single OHADA-wide adapter could replace the per-country
   stubs for CD, CM, CI, SN, etc.
3. Phase 2: build a Playwright-driven scraper for the Guichet Unique
   portal once it exposes a deterministic search form; gate behind the
   shared browser pool described in `CLAUDE.md` cross-cutting work.
4. For BCC-supervised banks specifically, ingest the published
   institutional list and link the annual prudential reports the BCC
   posts as PDFs — these are the only structured DRC financial documents
   freely available.
