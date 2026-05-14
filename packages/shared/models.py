"""Shared Pydantic v2 models used across adapters, backend, and risk engine.

These are the contract every country adapter must speak. Keep this file
provider-agnostic — no HTTP, no DB, no LLM concerns.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class IdentifierType(str, Enum):
    """Registry identifier classes used across jurisdictions."""

    VAT = "VAT"
    LEI = "LEI"
    COMPANY_NUMBER = "COMPANY_NUMBER"
    REGON = "REGON"
    KRS = "KRS"
    NIP = "NIP"
    SIREN = "SIREN"
    SIRET = "SIRET"
    HRB = "HRB"
    KVK = "KVK"
    CIF = "CIF"
    NIF = "NIF"
    CIK = "CIK"
    EIN = "EIN"
    MERSIS = "MERSIS"
    VKN = "VKN"
    ICO = "ICO"
    CVR = "CVR"
    ORG_NR = "ORG_NR"
    BUSINESS_ID = "BUSINESS_ID"
    OTHER = "OTHER"


class FilingType(str, Enum):
    ANNUAL_REPORT = "annual_report"
    BALANCE_SHEET = "balance_sheet"
    PROFIT_AND_LOSS = "p&l"
    CASH_FLOW = "cash_flow"
    DIRECTORS_REPORT = "directors_report"
    AUDIT_REPORT = "audit_report"


class Recommendation(str, Enum):
    APPROVE = "APPROVE"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


class AdapterStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    NOT_IMPLEMENTED = "not_implemented"
    BLOCKED = "blocked"
    ERROR = "error"


class RegistryIdentifier(BaseModel):
    type: IdentifierType
    value: str
    label: str | None = None


class Director(BaseModel):
    name: str
    role: str | None = None
    appointed_on: date | None = None
    resigned_on: date | None = None
    nationality: str | None = None


class Shareholder(BaseModel):
    name: str
    percent: float | None = None
    shares: int | None = None


class CompanyMatch(BaseModel):
    """Lightweight result of a name search."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Adapter-local stable id (often the primary identifier)")
    name: str
    country: str  # ISO 3166-1 alpha-2 upper
    identifiers: list[RegistryIdentifier] = Field(default_factory=list)
    address: str | None = None
    status: str | None = None  # active/dissolved/etc.
    source_url: str | None = None


class CompanyDetails(BaseModel):
    """Full registry record for a company."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    country: str
    legal_form: str | None = None
    status: str | None = None
    incorporation_date: date | None = None
    dissolution_date: date | None = None
    registered_address: str | None = None
    capital_amount: float | None = None
    capital_currency: str | None = None
    sic_codes: list[str] = Field(default_factory=list)
    nace_codes: list[str] = Field(default_factory=list)
    identifiers: list[RegistryIdentifier] = Field(default_factory=list)
    directors: list[Director] = Field(default_factory=list)
    shareholders: list[Shareholder] = Field(default_factory=list)
    website: str | None = None
    phone: str | None = None
    email: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict, description="Source-specific raw payload")
    source_url: str | None = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class FinancialFiling(BaseModel):
    """A single filed financial document."""

    model_config = ConfigDict(extra="ignore")

    id: UUID = Field(default_factory=uuid4)
    company_id: str
    year: int
    type: FilingType
    period_end: date | None = None
    currency: str | None = None
    structured_data: dict[str, Any] | None = None
    document_url: str | None = None
    document_format: str | None = None  # "pdf", "xbrl", "html", "json"
    source_url: str | None = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class FinancialRatios(BaseModel):
    """Deterministic ratios computed by the risk engine before the LLM sees the data."""

    year: int
    current_ratio: float | None = None
    quick_ratio: float | None = None
    debt_to_equity: float | None = None
    debt_to_assets: float | None = None
    roe: float | None = None
    roa: float | None = None
    gross_margin: float | None = None
    net_margin: float | None = None
    working_capital: float | None = None
    altman_z_score: float | None = None
    revenue_growth_yoy: float | None = None


class RiskAssessment(BaseModel):
    """Structured output of the credit risk engine."""

    model_config = ConfigDict(extra="ignore")

    id: UUID = Field(default_factory=uuid4)
    company_id: str
    score: int = Field(ge=0, le=100)
    recommendation: Recommendation
    recommended_credit_limit_eur: float = Field(ge=0)
    reasoning: str
    key_signals: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    ratios: list[FinancialRatios] = Field(default_factory=list)
    model_used: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AdapterHealth(BaseModel):
    country_code: str
    name: str
    status: AdapterStatus
    capabilities: dict[str, bool] = Field(
        default_factory=lambda: {"search": False, "lookup": False, "financials": False}
    )
    requires_api_key: bool = False
    api_key_present: bool = False
    rate_limit_per_minute: int | None = None
    last_checked_at: datetime = Field(default_factory=datetime.utcnow)
    notes: str | None = None
