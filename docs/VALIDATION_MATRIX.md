# Credyx — Full Validation Matrix

Run: `python scripts/validate_all.py` — 111 countries. Summary: {'BROKEN': 68, 'PARTIAL': 22, 'WORKING': 20, 'NOT_IMPLEMENTED': 1}

| CC | Company | Verdict | Search | Lookup | Financials | DL | DL check | Error |
|----|---------|---------|--------|--------|------------|----|----------|-------|
| AE | Emaar Properties | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| AL | ONE Telecommunications | **PARTIAL** | empty | pass | empty |  |  |  |
| AM | Ardshinbank CJSC | **BROKEN** | empty | not_found | not_impl |  |  |  |
| AO | Sonangol | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| AR | YPF S.A | **BROKEN** | not_impl | not_found | empty |  |  |  |
| AT | OMV AG | **BROKEN** | not_impl | not_found | empty |  |  |  |
| AU | BHP Group Limited | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | not_impl |  |  | FAIL:AdapterError:Missing env var AU_ABN_LOOKUP_GUID |
| AZ | SOCAR | **BROKEN** | not_impl | not_found | not_impl |  |  |  |
| BA | Elektroprivreda BiH | **BROKEN** | empty | no_id_testdata | no_id_testdata |  |  |  |
| BD | Grameenphone Ltd | **WORKING** | pass | pass | pass(3) |  |  |  |
| BE | Anheuser-Busch InBev | **WORKING** | pass | pass | pass(12) | ✓ | OK application/octet-str |  |
| BG | **Sopharma AD** | **PARTIAL** | empty | pass | pass(4) | ✓ | OK application/pdf |  |
| BH | Bahrain Telecommunicatio | **BROKEN** | not_impl | not_impl | empty |  |  |  |
| BO | YPFB | **PARTIAL** | not_impl | not_impl | pass(3) |  |  |  |
| BR | Petrobras | **WORKING** | pass | pass | pass(3) | ✓ | FAIL ReadError |  |
| BW | First National Bank Bots | **PARTIAL** | not_impl | not_impl | pass(1) |  |  |  |
| BY | Belaruskali OAO | **BROKEN** | TIMEOUT | TIMEOUT | empty |  |  |  |
| CA | Shopify Inc | **PARTIAL** | empty | pass | empty |  |  |  |
| CD | SCTP | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| CH | Nestlé S.A | **BROKEN** | FAIL:AdapterError:Missing Ze | FAIL:AdapterError:Missing Ze | empty |  |  | FAIL:AdapterError:Missing Zefix credentials. Zefix PublicREST requires free regi |
| CI | Orange Cote d'Ivoire | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| CL | Empresas COPEC S.A | **PARTIAL** | not_impl | FAIL:BlockedByRegistryError: | pass(3) |  |  | FAIL:BlockedByRegistryError:SII transport error for RUT 90.690.000-9: [Errno 110 |
| CM | SAFACAM | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| CO | **Ecopetrol S.A.** | **BROKEN** | empty | not_found | empty |  |  |  |
| CR | **Instituto Costarricens | **PARTIAL** | not_impl | not_found | pass(3) |  |  |  |
| CY | Bank of Cyprus Public Co | **BROKEN** | empty | not_found | empty |  |  |  |
| CZ | ČEZ | **WORKING** | pass | pass | pass(3) | ✓ | OK text/html [Veřejný re |  |
| DE | BMW | **NOT_IMPLEMENTED** | not_impl | not_impl | not_impl |  |  |  |
| DK | A.P. Møller - Mærsk A/S | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en |  |  | FAIL:AdapterError:Missing env var DK_VIRK_USERNAME |
| DO | Banco Popular Dominicano | **BROKEN** | not_impl | not_found | empty |  |  |  |
| DZ | **Alliance Assurances** | **BROKEN** | not_impl | FAIL:InvalidIdentifierError: | empty |  |  | FAIL:InvalidIdentifierError:Algeria NIF must be exactly 15 digits, got: ALL |
| EC | **Banco Pichincha C.A.** | **BROKEN** | TIMEOUT | TIMEOUT | TIMEOUT |  |  |  |
| EE | Bolt Technology OÜ | **WORKING** | pass | pass | pass(3) | ✓ | OK application/pdf |  |
| EG | Commercial International | **BROKEN** | not_impl | not_impl | empty |  |  |  |
| ES | Inditex | **PARTIAL** | pass | pass | empty |  |  |  |
| ET | Ethiopian Airlines | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| FI | Nokia | **PARTIAL** | pass | pass | empty |  |  |  |
| FR | TotalEnergies | **WORKING** | pass | pass | pass(6) |  |  |  |
| GB | BP | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en |  |  | FAIL:AdapterError:Missing env var UK_COMPANIES_HOUSE_API_KEY |
| GE | Bank of Georgia JSC | **BROKEN** | FAIL:BlockedByRegistryError: | not_found | empty |  |  | FAIL:BlockedByRegistryError:enreg.reestri.gov.ge search form not found — page ma |
| GH | MTN Ghana | **BROKEN** | not_impl | FAIL:InvalidIdentifierError: | empty |  |  | FAIL:InvalidIdentifierError:RGD registration number must look like CS123456789 ( |
| GR | Hellenic Telecommunicati | **PARTIAL** | pass | FAIL:RateLimitError:GEMI pub | pass(3) | ✓ | HTTP 429 | FAIL:RateLimitError:GEMI publicity portal rate-limited the lookup (429) — back o |
| HK | HSBC Holdings plc | **BROKEN** | not_impl | not_impl | empty |  |  |  |
| HR | INA d.d | **BROKEN** | FAIL:AdapterError:Croatian s | FAIL:AdapterError:Croatian s | not_impl |  |  | FAIL:AdapterError:Croatian sudreg open-data API requires OAuth2 client credentia |
| HU | **OTP Bank Nyrt.** | **PARTIAL** | FAIL:HTTPError:e-beszamolo s | pass | pass(6) |  |  | FAIL:HTTPError:e-beszamolo search rejected: A keresés nem járt eredménnyel.
    |
| ID | PT Bank Mandiri (Persero | **BROKEN** | not_impl | not_impl | empty |  |  |  |
| IE | Ryanair Holdings plc | **BROKEN** | FAIL:AdapterError:Missing CR | FAIL:AdapterError:Missing CR | FAIL:AdapterError:Missing CR |  |  | FAIL:AdapterError:Missing CRO credentials: set IE_CRO_API_USERNAME and IE_CRO_AP |
| IL | Teva Pharmaceutical Indu | **PARTIAL** | empty | pass | empty |  |  |  |
| IN | Reliance Industries Limi | **BROKEN** | not_impl | not_found | empty |  |  |  |
| IQ | Asiacell Communications  | **BROKEN** | not_impl | not_impl | empty |  |  |  |
| IS | Marel hf. | **BROKEN** | not_impl | not_impl | empty |  |  |  |
| IT | Eni | **WORKING** | pass | pass | pass(3) | ✓ | OK application/xhtml+xml |  |
| JO | Arab Bank PLC | **PARTIAL** | not_impl | FAIL:InvalidIdentifierError: | pass(3) |  |  | FAIL:InvalidIdentifierError:Jordan CCD company number must be up to 10 digits, g |
| JP | Toyota Motor Corporation | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en |  |  | FAIL:AdapterError:Missing env var JP_HOJIN_BANGO_APP_ID |
| KE | Safaricom PLC | **BROKEN** | not_impl | FAIL:InvalidIdentifierError: | empty |  |  | FAIL:InvalidIdentifierError:BRS registration number format unrecognized: SCOM |
| KG | Kyrgyzaltyn OJSC | **BROKEN** | FAIL:HTTPStatusError:Client  | FAIL:HTTPStatusError:Client  | empty |  |  | FAIL:HTTPStatusError:Client error '403 Forbidden' for url 'https://register.minj |
| KH | ACLEDA Bank Plc | **BROKEN** | empty | FAIL:InvalidIdentifierError: | FAIL:InvalidIdentifierError: |  |  | FAIL:InvalidIdentifierError:Cambodia MoC number must be 1–10 digits; got: ABC |
| KR | Samsung Electronics Co., | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en |  |  | FAIL:AdapterError:Missing env var KR_OPENDART_API_KEY |
| KW | National Bank of Kuwait | **BROKEN** | not_impl | not_impl | empty |  |  |  |
| KZ | КазМунайГаз | **WORKING** | pass | pass | pass(3) |  |  |  |
| LK | John Keells Holdings PLC | **WORKING** | pass | pass | pass(4) | ✓ | OK application/pdf |  |
| LT | Ignitis | **BROKEN** | empty | not_found | empty |  |  |  |
| LU | ArcelorMittal S.A | **BROKEN** | empty | not_found | empty |  |  |  |
| LV | AS "Latvenergo" | **BROKEN** | empty | not_found | empty |  |  |  |
| MA | Maroc Telecom | **BROKEN** | not_impl | not_impl | empty |  |  |  |
| MD | Moldovagaz SA | **BROKEN** | FAIL:HTTPStatusError:Client  | FAIL:HTTPStatusError:Client  | empty |  |  | FAIL:HTTPStatusError:Client error '403 Forbidden' for url 'https://www.idno.md/s |
| ME | Crnogorski Telekom | **BROKEN** | empty | no_id_testdata | no_id_testdata |  |  |  |
| MG | Telma | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| MK | Komercijalna Banka AD Sk | **BROKEN** | TIMEOUT | TIMEOUT | empty |  |  |  |
| MM | First Myanmar Investment | **BROKEN** | empty | not_found | empty |  |  |  |
| MT | Bank of Valletta plc | **PARTIAL** | empty | not_found | pass(1) |  |  |  |
| MU | MCB Group Limited | **WORKING** | pass | pass | pass(3) |  |  |  |
| MX | Petróleos Mexicanos (Pem | **BROKEN** | not_impl | FAIL:BlockedByRegistryError: | empty |  |  | FAIL:BlockedByRegistryError:SAT RFC verifier is CAPTCHA-protected; cannot resolv |
| MY | Petroliam Nasional Berha | **BROKEN** | not_impl | not_impl | empty |  |  |  |
| MZ | Hidroelectrica de Cahora | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| NG | Dangote Cement Plc | **BROKEN** | TIMEOUT | TIMEOUT | empty |  |  |  |
| NL | ASML | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | empty |  |  | FAIL:AdapterError:Missing env var NL_KVK_API_KEY |
| NO | Equinor | **WORKING** | pass | pass | pass(1) |  |  |  |
| NP | Nabil Bank Limited | **WORKING** | pass | pass | pass(3) |  |  |  |
| NZ | Fonterra Co-operative Gr | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en |  |  | FAIL:AdapterError:Missing env var NZ_NZBN_API_KEY |
| PE | Credicorp Capital S.A | **BROKEN** | not_impl | FAIL:BlockedByRegistryError: | empty |  |  | FAIL:BlockedByRegistryError:SUNAT JSP requires CAPTCHA token; direct HTTP lookup |
| PH | SM Investments Corporati | **BROKEN** | empty | not_found | empty |  |  |  |
| PK | Habib Bank Limited | **WORKING** | pass | pass | pass(3) | ✓ | OK application/pdf |  |
| PL | Orlen | **WORKING** | pass | pass | pass(3) | ✓ | OK application/octet-str |  |
| PT | EDP | **WORKING** | pass | pass | pass(3) | ✓ | OK application/xhtml+xml |  |
| PY | Banco Continental | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| QA | Qatar National Bank | **PARTIAL** | not_impl | FAIL:InvalidIdentifierError: | pass(4) |  |  | FAIL:InvalidIdentifierError:Qatar CR must be 4-10 digits, got: QNBK |
| RO | OMV Petrom S.A. | **PARTIAL** | empty | pass | pass(3) | ✓ | OK application/json |  |
| RS | NIS | **BROKEN** | FAIL:RemoteProtocolError:Ser | FAIL:RemoteProtocolError:Ser | empty |  |  | FAIL:RemoteProtocolError:Server disconnected without sending a response. |
| RU | Sberbank PAO | **PARTIAL** | empty | pass | empty |  |  |  |
| SA | Saudi Arabian Oil Compan | **PARTIAL** | not_impl | pass | empty |  |  |  |
| SC | SACOS Group | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| SE | Volvo | **WORKING** | pass | pass | pass(3) | ✓ | OK application/zip |  |
| SG | DBS Group Holdings Ltd | **BROKEN** | FAIL:AdapterError:data.gov.s | FAIL:AdapterError:data.gov.s | FAIL:AdapterError:data.gov.s |  |  | FAIL:AdapterError:data.gov.sg ACRA resource not found — set SG_ACRA_RESOURCE_ID  |
| SI | Krka | **WORKING** | pass | pass | pass(3) | ✓ | OK application/pdf |  |
| SK | Volkswagen Slovakia, a.s | **WORKING** | pass | pass | pass(12) | ✓ | OK application/pdf |  |
| SN | Sonatel | **BROKEN** | not_impl | FAIL:InvalidIdentifierError: | empty |  |  | FAIL:InvalidIdentifierError:Senegalese RCCM must match SN-LOC-YYYY-X-NNN: SNTS |
| TH | PTT Public Company Limit | **BROKEN** | FAIL:HTTPStatusError:Client  | not_found | empty |  |  | FAIL:HTTPStatusError:Client error '403 Forbidden' for url 'https://datawarehouse |
| TN | **Banque de Tunisie** | **BROKEN** | not_impl | FAIL:InvalidIdentifierError: | FAIL:InvalidIdentifierError: |  |  | FAIL:InvalidIdentifierError:Tunisia Matricule Fiscal must be 7 digits + 3 letter |
| TR | Turk Hava Yollari | **PARTIAL** | pass | not_impl | not_impl |  |  |  |
| TW | TSMC | **PARTIAL** | empty | pass | pass(1) |  |  |  |
| TZ | **CRDB Bank PLC** | **PARTIAL** | not_impl | not_impl | pass(1) |  |  |  |
| UA | Naftogaz of Ukraine | **WORKING** | pass | pass | pass(3) | ✓ | OK text/html [Регулярна  |  |
| US | Apple | **WORKING** | pass | pass | pass(3) | ✓ | OK text/html [aapl-20250 |  |
| UY | ANCAP | **PARTIAL** | not_impl | not_found | pass(3) |  |  |  |
| UZ | Uzbekneftegaz | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| VN | Vinamilk | **BROKEN** | FAIL:HTTPStatusError:Client  | not_found | empty |  |  | FAIL:HTTPStatusError:Client error '403 Forbidden' for url 'https://thongtindoanh |
| XK | Raiffeisen Bank Kosovo | **BROKEN** | empty | no_id_testdata | no_id_testdata |  |  |  |
| ZA | Naspers Limited | **BROKEN** | not_impl | not_found | empty |  |  |  |
| ZM | Zambia National Commerci | **BROKEN** | not_impl | not_impl | empty |  |  |  |
| ZW | Econet Wireless Zimbabwe | **BROKEN** | not_impl | not_impl | FAIL:HTTPStatusError:Client  |  |  | FAIL:HTTPStatusError:Client error '404 Not Found' for url 'https://www.zse.co.zw |
