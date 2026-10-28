"""Agent A output contract. Any extractor (rules or LLM) must pass validate_extraction
before its output reaches the qualification rules."""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Intent = Literal[
    "demo", "pricing", "pilot", "not_interested", "unsubscribe", "auto_reply", "partnership",
    "investor", "job_seeker", "other",
]
ProblemCategory = Literal[
    "rate_quoting", "document_extraction", "invoice_reconciliation", "trade_document_checking",
]
INTEREST_INTENTS = frozenset({"demo", "pricing", "pilot"})
# A closed list, so a model's free text ("Spedition", "logistics co.") cannot slip past ICP checks.
Vertical = Literal[
    "freight-forwarder", "carrier", "3pl", "trucking", "air-cargo", "ground-handling",
    "customs-broker", "shipper", "trade-finance", "software-vendor", "investor", "other",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StatedCompanyFacts(Strict):
    company_name: str | None = Field(default=None, max_length=120)
    vertical: Vertical | None = None
    employees: int | None = Field(default=None, ge=1, le=10_000_000)
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")


class DataProblem(Strict):
    category: ProblemCategory
    summary: str = Field(max_length=300)


class Extraction(Strict):
    language: str = Field(pattern=r"^([a-z]{2}|unknown)$")
    intent: Intent
    buyer_role: str | None = Field(default=None, max_length=120)
    data_problem: DataProblem | None = None
    company_facts: StatedCompanyFacts = StatedCompanyFacts()
    evidence: list[str] = Field(default_factory=list, max_length=6)


class ExtractionResult(Strict):
    message_id: str
    extractor: str
    status: Literal["ok", "failed"]
    extraction: Extraction | None = None
    error: str | None = None


class InvalidExtraction(Exception):
    """Output failed the schema or quoted text that is not in the message."""


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def validate_extraction(raw: Any, body: str) -> Extraction:
    try:
        extraction = (
            Extraction.model_validate_json(raw) if isinstance(raw, str | bytes)
            else Extraction.model_validate(raw)
        )
    except ValidationError as exc:
        raise InvalidExtraction(f"schema validation failed ({exc.error_count()} errors)") from None
    haystack = _squash(body)
    for quote in extraction.evidence:
        if not quote.strip() or _squash(quote) not in haystack:
            raise InvalidExtraction("evidence quote is not verbatim from the message")
    return extraction
