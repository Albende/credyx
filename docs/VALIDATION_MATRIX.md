# Credyx — Full Validation Matrix

Run: `python scripts/validate_all.py` — 111 countries. Summary: {'BROKEN': 49, 'WORKING': 48, 'PARTIAL': 13, 'NOT_IMPLEMENTED': 1}

| CC | Company | Verdict | Search | Lookup | Financials | DL | DL check | Error |
|----|---------|---------|--------|--------|------------|----|----------|-------|
| AE | Emaar Properties | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| AL | ONE ALBANIA | **WORKING** | pass | pass | pass(3) | ✓ | OK application/vnd.openx |  |
| AM | Ardshinbank CJSC | **BROKEN** | empty | not_found | not_impl |  |  |  |
| AO | Sonangol | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| AR | YPF S.A | **WORKING** | pass | pass | pass(3) | ✓ | OK text/html [Presentaci |  |
| AT | OMV AG | **BROKEN** | not_impl | not_found | empty |  |  |  |
| AU | BHP Group Limited | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | not_impl |  |  | FAIL:AdapterError:Missing env var AU_ABN_LOOKUP_GUID |
| AZ | SOCAR | **BROKEN** | not_impl | not_found | not_impl |  |  |  |
| BA | Elektroprivreda BiH | **BROKEN** | empty | no_id_testdata | no_id_testdata |  |  |  |
| BD | Grameenphone Ltd | **WORKING** | pass | pass | pass(3) |  |  |  |
| BE | Anheuser-Busch InBev | **WORKING** | pass | pass | pass(12) | ✓ | OK application/octet-str |  |
| BG | Sopharma | **PARTIAL** | empty | FAIL:AssertionError: | pass(4) | ✓ | OK application/pdf | FAIL:AssertionError: |
| BH | Bahrain Telecommunicatio | **BROKEN** | not_impl | not_impl | empty |  |  |  |
| BO | YPFB | **PARTIAL** | pass | not_found | empty |  |  |  |
| BR | Petrobras | **WORKING** | pass | pass | pass(3) | ✓ | FAIL ReadError |  |
| BW | Sefalana | **PARTIAL** | pass | pass | empty |  |  |  |
| BY | Belaruskali OAO | **BROKEN** | TIMEOUT | TIMEOUT | empty |  |  |  |
| CA | Shopify Inc | **WORKING** | pass | pass | pass(3) | ✓ | OK text/html [shop-20251 |  |
| CD | SCTP | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| CH | Nestlé S.A | **BROKEN** | FAIL:AdapterError:Missing Ze | FAIL:AdapterError:Missing Ze | empty |  |  | FAIL:AdapterError:Missing Zefix credentials. Zefix PublicREST requires free regi |
| CI | Orange Cote d'Ivoire | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| CL | **Banco de Chile | **WORKING** | pass | pass | pass(3) | ✓ | OK text/html [] |  |
| CM | SAFACAM | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| CO | Alpina | **WORKING** | pass | pass | pass(3) | ✓ | OK application/json |  |
| CR | **Florida Ice and Farm C | **WORKING** | pass | pass | pass(3) | ✓ | OK application/pdf |  |
| CY | Bank of Cyprus Public Co | **BROKEN** | empty | not_found | empty |  |  |  |
| CZ | ČEZ | **WORKING** | pass | pass | pass(3) | ✓ | OK text/html [Veřejný re |  |
| DE | BMW | **NOT_IMPLEMENTED** | not_impl | not_impl | not_impl |  |  |  |
| DK | A.P. Møller - Mærsk A/S | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en |  |  | FAIL:AdapterError:Missing env var DK_VIRK_USERNAME |
| DO | Banco Popular Dominicano | **BROKEN** | not_impl | not_found | empty |  |  |  |
| DZ | **Alliance Assurances** | **BROKEN** | not_impl | FAIL:InvalidIdentifierError: | empty |  |  | FAIL:InvalidIdentifierError:Algeria NIF must be exactly 15 digits, got: ALL |
| EC | **Banco Pichincha C.A.** | **BROKEN** | TIMEOUT | TIMEOUT | TIMEOUT |  |  |  |
| EE | Bolt Technology OÜ | **WORKING** | pass | pass | pass(3) | ✓ | OK application/pdf |  |
| EG | Commercial International | **WORKING** | pass | pass | pass(3) | ✓ | HTTP 403 |  |
| ES | Telefonica | **WORKING** | pass | pass | pass(3) | ✓ | OK application/zip |  |
| ET | Ethiopian Airlines | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| FI | Asuntotekniikka | **WORKING** | pass | pass | pass(3) | ✓ | OK text/xml |  |
| FR | TotalEnergies | **WORKING** | pass | pass | pass(6) |  |  |  |
| GB | BP | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en |  |  | FAIL:AdapterError:Missing env var UK_COMPANIES_HOUSE_API_KEY |
| GE | Silknet | **WORKING** | pass | pass | pass(3) |  |  |  |
| GH | MTN Ghana | **BROKEN** | not_impl | FAIL:InvalidIdentifierError: | empty |  |  | FAIL:InvalidIdentifierError:RGD registration number must look like CS123456789 ( |
| GR | Hellenic Telecommunicati | **PARTIAL** | pass | FAIL:RateLimitError:GEMI pub | FAIL:RateLimitError:GEMI pub |  |  | FAIL:RateLimitError:GEMI publicity portal rate-limited the lookup (429) — back o |
| HK | Tencent Holdings Ltd | **WORKING** | pass | pass | pass(3) | ✓ | OK application/pdf |  |
| HR | INA d.d | **BROKEN** | FAIL:AdapterError:Croatian s | FAIL:AdapterError:Croatian s | not_impl |  |  | FAIL:AdapterError:Croatian sudreg open-data API requires OAuth2 client credentia |
| HU | **OTP Bank Nyrt.** | **PARTIAL** | FAIL:HTTPError:e-beszamolo s | pass | pass(6) |  |  | FAIL:HTTPError:e-beszamolo search rejected: A keresés nem járt eredménnyel.
    |
| ID | PT Bank Mandiri (Persero | **WORKING** | pass | pass | pass(3) | ✓ | HTTP 403 |  |
| IE | Ryanair Holdings plc | **BROKEN** | FAIL:AdapterError:Missing CR | FAIL:AdapterError:Missing CR | FAIL:AdapterError:Missing CR |  |  | FAIL:AdapterError:Missing CRO credentials: set IE_CRO_API_USERNAME and IE_CRO_AP |
| IL | Teva | **WORKING** | pass | pass | pass(3) |  |  |  |
| IN | Reliance Industries Limi | **WORKING** | pass | pass | pass(3) | ✓ | HTTP 403 |  |
| IQ | Asiacell Communications  | **BROKEN** | not_impl | not_impl | empty |  |  |  |
| IS | Marel hf. | **BROKEN** | not_impl | not_impl | empty |  |  |  |
| IT | Eni | **WORKING** | pass | pass | pass(3) | ✓ | OK application/xhtml+xml |  |
| JO | Jordan Phosphate | **PARTIAL** | pass | not_found | pass(3) | ✓ | OK application/zip |  |
| JP | Toyota Motor Corporation | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en |  |  | FAIL:AdapterError:Missing env var JP_HOJIN_BANGO_APP_ID |
| KE | Safaricom PLC | **WORKING** | pass | pass | pass(3) | ✓ | OK application/pdf |  |
| KG | Kyrgyzaltyn OJSC | **BROKEN** | FAIL:HTTPStatusError:Client  | FAIL:HTTPStatusError:Client  | empty |  |  | FAIL:HTTPStatusError:Client error '403 Forbidden' for url 'https://register.minj |
| KH | ACLEDA Bank Plc | **BROKEN** | empty | FAIL:InvalidIdentifierError: | FAIL:InvalidIdentifierError: |  |  | FAIL:InvalidIdentifierError:Cambodia MoC number must be 1–10 digits; got: ABC |
| KR | Samsung Electronics Co., | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en |  |  | FAIL:AdapterError:Missing env var KR_OPENDART_API_KEY |
| KW | National Bank of Kuwait | **BROKEN** | not_impl | not_impl | empty |  |  |  |
| KZ | КазМунайГаз | **WORKING** | pass | pass | pass(3) |  |  |  |
| LK | John Keells Holdings PLC | **WORKING** | pass | pass | pass(4) | ✓ | OK application/pdf |  |
| LT | Ignitis | **PARTIAL** | pass | TIMEOUT | pass(3) |  |  |  |
| LU | ArcelorMittal S.A | **BROKEN** | empty | not_found | empty |  |  |  |
| LV | Latvenergo | **PARTIAL** | pass | TIMEOUT | TIMEOUT |  |  |  |
| MA | Maroc Telecom | **BROKEN** | not_impl | not_impl | empty |  |  |  |
| MD | Moldovagaz | **WORKING** | pass | pass | pass(3) | ✓ | OK application/json |  |
| ME | Crnogorski Telekom | **BROKEN** | empty | no_id_testdata | no_id_testdata |  |  |  |
| MG | Telma | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| MK | Komercijalna Banka AD Sk | **BROKEN** | TIMEOUT | TIMEOUT | empty |  |  |  |
| MM | First Myanmar Investment | **BROKEN** | empty | not_found | empty |  |  |  |
| MT | Bank of Valletta | **WORKING** | pass | pass | pass(3) | ✓ | OK application/zip |  |
| MU | MCB Group Limited | **WORKING** | pass | pass | pass(3) |  |  |  |
| MX | America Movil | **WORKING** | pass | pass | pass(3) | ✓ | OK text/html [] |  |
| MY | Public Bank Berhad | **WORKING** | pass | pass | pass(3) | ✓ | HTTP 403 |  |
| MZ | Hidroelectrica de Cahora | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| NG | Dangote Cement Plc | **BROKEN** | TIMEOUT | TIMEOUT | empty |  |  |  |
| NL | ASML | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | empty |  |  | FAIL:AdapterError:Missing env var NL_KVK_API_KEY |
| NO | Equinor | **WORKING** | pass | pass | pass(1) |  |  |  |
| NP | Nabil Bank Limited | **WORKING** | pass | pass | pass(3) |  |  |  |
| NZ | Fonterra Co-operative Gr | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en |  |  | FAIL:AdapterError:Missing env var NZ_NZBN_API_KEY |
| PE | Compañía de Minas Buenav | **WORKING** | pass | pass | pass(3) |  |  |  |
| PH | SM Investments Corporati | **WORKING** | pass | pass | pass(2) | ✓ | OK application/octet-str |  |
| PK | Habib Bank Limited | **WORKING** | pass | pass | pass(3) | ✓ | OK application/pdf |  |
| PL | Orlen | **WORKING** | pass | pass | pass(3) | ✓ | OK application/octet-str |  |
| PT | EDP | **WORKING** | pass | pass | pass(3) | ✓ | OK application/xhtml+xml |  |
| PY | Banco Continental | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| QA | Qatar National Bank | **PARTIAL** | pass | pass | empty |  |  |  |
| RO | OMV Petrom S.A. | **PARTIAL** | empty | pass | pass(3) | ✓ | OK application/json |  |
| RS | NIS | **WORKING** | pass | pass | pass(1) |  |  |  |
| RU | Сбербанк | **WORKING** | pass | pass | pass(3) |  |  |  |
| SA | Saudi Telecom Company (S | **WORKING** | pass | pass | pass(3) |  |  |  |
| SC | SACOS Group | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| SE | Volvo | **WORKING** | pass | pass | pass(3) | ✓ | OK application/zip |  |
| SG | DBS Group Holdings Ltd | **WORKING** | pass | pass | pass(3) | ✓ | OK application/pdf |  |
| SI | Krka | **WORKING** | pass | pass | pass(3) | ✓ | OK application/pdf |  |
| SK | Volkswagen Slovakia, a.s | **WORKING** | pass | pass | pass(12) | ✓ | OK application/pdf |  |
| SN | Sonatel | **BROKEN** | not_impl | FAIL:InvalidIdentifierError: | empty |  |  | FAIL:InvalidIdentifierError:Senegalese RCCM must match SN-LOC-YYYY-X-NNN: SNTS |
| TH | PTT Public Company Limit | **BROKEN** | FAIL:HTTPStatusError:Client  | not_found | empty |  |  | FAIL:HTTPStatusError:Client error '403 Forbidden' for url 'https://datawarehouse |
| TN | **Banque de Tunisie** | **BROKEN** | not_impl | FAIL:InvalidIdentifierError: | FAIL:InvalidIdentifierError: |  |  | FAIL:InvalidIdentifierError:Tunisia Matricule Fiscal must be 7 digits + 3 letter |
| TR | Turk Hava Yollari | **PARTIAL** | pass | not_impl | not_impl |  |  |  |
| TW | TSMC | **PARTIAL** | empty | pass | pass(1) |  |  |  |
| TZ | CRDB Bank | **PARTIAL** | pass | pass | FAIL:HTTPStatusError:Server  |  |  | FAIL:HTTPStatusError:Server error '500 Internal Server Error' for url 'https://d |
| UA | Naftogaz of Ukraine | **WORKING** | pass | pass | pass(3) | ✓ | OK text/html [Регулярна  |  |
| US | Apple | **WORKING** | pass | pass | pass(3) | ✓ | OK text/html [aapl-20250 |  |
| UY | PAMER | **WORKING** | pass | pass | pass(13) | ✓ | OK application/pdf |  |
| UZ | Uzbekneftegaz | **BROKEN** | not_impl | no_id_testdata | no_id_testdata |  |  |  |
| VN | Vinamilk | **WORKING** | pass | pass | pass(3) |  |  |  |
| XK | Raiffeisen Bank Kosovo | **BROKEN** | empty | no_id_testdata | no_id_testdata |  |  |  |
| ZA | Sasol Limited | **WORKING** | pass | pass | pass(3) | ✓ | OK text/html [Sasol Limi |  |
| ZM | Zambia National Commerci | **BROKEN** | not_impl | not_impl | empty |  |  |  |
| ZW | Econet Wireless Zimbabwe | **BROKEN** | not_impl | not_impl | FAIL:HTTPStatusError:Client  |  |  | FAIL:HTTPStatusError:Client error '404 Not Found' for url 'https://www.zse.co.zw |
