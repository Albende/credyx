# Credyx — Full Validation Matrix

Run: `python scripts/validate_all.py` — 75 countries. Summary: {'PARTIAL': 27, 'BROKEN': 43, 'WORKING': 4, 'NOT_IMPLEMENTED': 1}

| CC | Company | Verdict | Search | Lookup | Financials | DL | Error |
|----|---------|---------|--------|--------|------------|----|-------|
| AL | ONE Telecommunications | **PARTIAL** | empty | pass | empty |  |  |
| AM | Ardshinbank CJSC | **BROKEN** | empty | not_found | not_impl |  |  |
| AR | YPF S.A | **BROKEN** | not_impl | not_found | empty |  |  |
| AT | OMV AG | **BROKEN** | not_impl | not_found | empty |  |  |
| AU | BHP Group Limited | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | not_impl |  | FAIL:AdapterError:Missing env var AU_ABN_LOOKUP_GUID |
| AZ | SOCAR | **BROKEN** | not_impl | not_found | not_impl |  |  |
| BE | Anheuser-Busch InBev | **WORKING** | pass | pass | pass(12) | ✓ |  |
| BG | **Sopharma AD** | **PARTIAL** | not_impl | pass | pass(1) | ✓ |  |
| BR | Petrobras | **PARTIAL** | not_impl | pass | pass(3) | ✓ |  |
| BY | Belaruskali OAO | **BROKEN** | TIMEOUT | TIMEOUT | empty |  |  |
| CA | Shopify Inc | **PARTIAL** | empty | pass | empty |  |  |
| CH | Nestlé S.A | **BROKEN** | FAIL:AdapterError:Missing Ze | FAIL:AdapterError:Missing Ze | empty |  | FAIL:AdapterError:Missing Zefix credentials. Zefix PublicREST requires free regi |
| CL | Empresas COPEC S.A | **PARTIAL** | not_impl | FAIL:BlockedByRegistryError: | pass(3) | ✓ | FAIL:BlockedByRegistryError:SII RUT verifier requires CAPTCHA. Direct HTTP looku |
| CO | **Ecopetrol S.A.** | **BROKEN** | empty | not_found | empty |  |  |
| CR | **Instituto Costarricens | **PARTIAL** | not_impl | not_found | pass(3) | ✓ |  |
| CY | Bank of Cyprus Public Co | **BROKEN** | empty | not_found | empty |  |  |
| CZ | ČEZ | **PARTIAL** | pass | pass | empty |  |  |
| DE | BMW | **NOT_IMPLEMENTED** | not_impl | not_impl | not_impl |  |  |
| DK | A.P. Møller - Mærsk A/S | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en |  | FAIL:AdapterError:Missing env var DK_VIRK_USERNAME |
| DO | Banco Popular Dominicano | **BROKEN** | not_impl | not_found | empty |  |  |
| EC | **Banco Pichincha C.A.** | **BROKEN** | TIMEOUT | TIMEOUT | TIMEOUT |  |  |
| EE | Bolt Technology OÜ | **PARTIAL** | empty | pass | empty |  |  |
| EG | Commercial International | **BROKEN** | not_impl | not_impl | empty |  |  |
| ES | Inditex | **PARTIAL** | not_impl | pass | empty |  |  |
| FI | Nokia | **PARTIAL** | pass | pass | empty |  |  |
| FR | TotalEnergies | **PARTIAL** | pass | pass | empty |  |  |
| GB | BP | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en |  | FAIL:AdapterError:Missing env var UK_COMPANIES_HOUSE_API_KEY |
| GE | Bank of Georgia JSC | **BROKEN** | FAIL:BlockedByRegistryError: | not_found | empty |  | FAIL:BlockedByRegistryError:enreg.reestri.gov.ge search form not found — page ma |
| GR | Hellenic Telecommunicati | **PARTIAL** | pass | FAIL:RateLimitError:GEMI pub | empty |  | FAIL:RateLimitError:GEMI publicity portal rate-limited the lookup (429) — back o |
| HK | HSBC Holdings plc | **BROKEN** | not_impl | not_impl | empty |  |  |
| HR | INA d.d | **BROKEN** | FAIL:AdapterError:Croatian s | FAIL:AdapterError:Croatian s | not_impl |  | FAIL:AdapterError:Croatian sudreg open-data API requires OAuth2 client credentia |
| HU | OTP Bank Nyrt | **PARTIAL** | not_impl | pass | empty |  |  |
| ID | PT Bank Mandiri (Persero | **BROKEN** | not_impl | not_impl | empty |  |  |
| IE | Ryanair Holdings plc | **BROKEN** | FAIL:AdapterError:Missing CR | FAIL:AdapterError:Missing CR | FAIL:AdapterError:Missing CR |  | FAIL:AdapterError:Missing CRO credentials: set IE_CRO_API_USERNAME and IE_CRO_AP |
| IL | Teva Pharmaceutical Indu | **PARTIAL** | empty | pass | empty |  |  |
| IN | Reliance Industries Limi | **BROKEN** | not_impl | not_found | empty |  |  |
| IS | Marel hf. | **BROKEN** | not_impl | not_impl | empty |  |  |
| IT | Eni | **PARTIAL** | not_impl | not_found | pass(3) | ✓ |  |
| JP | Toyota Motor Corporation | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en |  | FAIL:AdapterError:Missing env var JP_HOJIN_BANGO_APP_ID |
| KG | Kyrgyzaltyn OJSC | **BROKEN** | FAIL:HTTPStatusError:Client  | FAIL:HTTPStatusError:Client  | empty |  | FAIL:HTTPStatusError:Client error '403 Forbidden' for url 'https://register.minj |
| KR | Samsung Electronics Co., | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en |  | FAIL:AdapterError:Missing env var KR_OPENDART_API_KEY |
| KZ | KazMunayGas | **PARTIAL** | not_impl | not_found | pass(1) | ✓ |  |
| LK | John Keells Holdings PLC | **PARTIAL** | pass | pass | FAIL:HTTPStatusError:Client  |  | FAIL:HTTPStatusError:Client error '400 ' for url 'https://www.cse.lk/api/company |
| LT | Ignitis | **BROKEN** | empty | not_found | empty |  |  |
| LU | ArcelorMittal S.A | **BROKEN** | empty | not_found | empty |  |  |
| LV | AS "Latvenergo" | **BROKEN** | empty | not_found | empty |  |  |
| MA | Maroc Telecom | **BROKEN** | not_impl | not_impl | empty |  |  |
| MD | Moldovagaz SA | **BROKEN** | FAIL:HTTPStatusError:Client  | FAIL:HTTPStatusError:Client  | empty |  | FAIL:HTTPStatusError:Client error '403 Forbidden' for url 'https://www.idno.md/s |
| MK | Komercijalna Banka AD Sk | **BROKEN** | TIMEOUT | TIMEOUT | empty |  |  |
| MT | Bank of Valletta plc | **PARTIAL** | empty | not_found | pass(1) | ✓ |  |
| MX | Petróleos Mexicanos (Pem | **BROKEN** | not_impl | FAIL:BlockedByRegistryError: | empty |  | FAIL:BlockedByRegistryError:SAT RFC verifier is CAPTCHA-protected; cannot resolv |
| MY | Petroliam Nasional Berha | **BROKEN** | not_impl | not_impl | empty |  |  |
| NG | Dangote Cement Plc | **BROKEN** | TIMEOUT | TIMEOUT | empty |  |  |
| NL | ASML | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | empty |  | FAIL:AdapterError:Missing env var NL_KVK_API_KEY |
| NO | Equinor | **WORKING** | pass | pass | pass(1) | ✓ |  |
| NZ | Fonterra Co-operative Gr | **BROKEN** | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en | FAIL:AdapterError:Missing en |  | FAIL:AdapterError:Missing env var NZ_NZBN_API_KEY |
| PE | Credicorp Capital S.A | **BROKEN** | not_impl | FAIL:BlockedByRegistryError: | empty |  | FAIL:BlockedByRegistryError:SUNAT JSP requires CAPTCHA token; direct HTTP lookup |
| PH | SM Investments Corporati | **BROKEN** | empty | not_found | empty |  |  |
| PL | Orlen | **PARTIAL** | FAIL:TimeoutError:Locator.fi | pass | pass(3) | ✓ | FAIL:TimeoutError:Locator.fill: Timeout 30000ms exceeded.
Call log:
  - waiting  |
| RO | OMV Petrom S.A. | **PARTIAL** | not_impl | pass | empty |  |  |
| RS | NIS | **BROKEN** | FAIL:RemoteProtocolError:Ser | FAIL:RemoteProtocolError:Ser | empty |  | FAIL:RemoteProtocolError:Server disconnected without sending a response. |
| RU | Sberbank PAO | **PARTIAL** | empty | pass | empty |  |  |
| SA | Saudi Arabian Oil Compan | **PARTIAL** | not_impl | pass | empty |  |  |
| SE | Volvo | **PARTIAL** | not_impl | pass | pass(3) | ✓ |  |
| SG | DBS Group Holdings Ltd | **BROKEN** | FAIL:AdapterError:data.gov.s | FAIL:AdapterError:data.gov.s | FAIL:AdapterError:data.gov.s |  | FAIL:AdapterError:data.gov.sg ACRA resource not found — set SG_ACRA_RESOURCE_ID  |
| SI | Krka | **PARTIAL** | pass | pass | not_impl |  |  |
| SK | Volkswagen Slovakia, a.s | **WORKING** | pass | pass | pass(12) | ✓ |  |
| TH | PTT Public Company Limit | **BROKEN** | FAIL:HTTPStatusError:Client  | not_found | empty |  | FAIL:HTTPStatusError:Client error '403 Forbidden' for url 'https://datawarehouse |
| TR | Turk Hava Yollari | **PARTIAL** | pass | not_impl | not_impl |  |  |
| TW | TSMC | **PARTIAL** | not_impl | pass | empty |  |  |
| UA | Naftogaz of Ukraine | **BROKEN** | TIMEOUT | TIMEOUT | empty |  |  |
| US | Apple | **WORKING** | pass | pass | pass(3) | ✓ |  |
| UY | ANCAP | **PARTIAL** | not_impl | not_found | pass(3) | ✓ |  |
| VN | Vinamilk | **BROKEN** | FAIL:HTTPStatusError:Client  | not_found | empty |  | FAIL:HTTPStatusError:Client error '403 Forbidden' for url 'https://thongtindoanh |
| ZA | Naspers Limited | **BROKEN** | not_impl | not_found | empty |  |  |
