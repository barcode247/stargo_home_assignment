"""Core records after validation and normalization. All datetimes are timezone-aware."""

from datetime import date, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

Channel = Literal["email_reply", "form_fill", "linkedin_dm"]
Source = Literal[
    "event-email", "paid", "historical-reactivation", "new-connection", "warm-network",
    "organic/referral",
]
Decision = Literal["accepted", "rejected"]
PipelineEventType = Literal["meeting_booked", "meeting_held", "opportunity_created"]
Status = Literal[
    "QL candidate", "QL", "excluded", "disqualified", "nurture", "suppressed", "needs review",
]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CrmRecord(Frozen):
    record_id: str
    first_name: str | None
    last_name: str | None
    email: str | None
    job_title: str | None
    linkedin: str | None
    company_name: str | None
    company_domain: str | None
    country: str | None
    vertical: str | None
    employees: int | None
    lifecycle_stage: str | None
    lead_status: str | None
    is_customer: bool
    open_deal_id: str | None
    open_deal_created: date | None
    owner: str | None
    last_activity_date: date | None

    @property
    def full_name(self) -> str | None:
        name = " ".join(p for p in (self.first_name, self.last_name) if p)
        return name or None


class InboundMessage(Frozen):
    id: str
    channel: Channel
    source: Source | None
    received_at: AwareDatetime
    from_name: str | None
    email: str | None
    linkedin: str | None
    subject: str | None
    body: str

    @property
    def identity_keys(self) -> list[str]:
        return identity_keys(self.email, self.linkedin)


class SalesDecision(Frozen):
    id: str
    contact_key: str
    decision: Decision
    decided_by: str | None
    decided_at: AwareDatetime
    note: str | None
    origin: Literal["seed", "ui"]


class PipelineEvent(Frozen):
    id: str
    type: PipelineEventType
    contact_key: str
    occurred_at: AwareDatetime


class Rejection(Frozen):
    ref: str
    kind: Literal["inbound", "crm", "decision", "pipeline_event"]
    reasons: list[str]
    rejected_at: datetime


def identity_keys(email: str | None, linkedin: str | None) -> list[str]:
    """Keys that identify one person: normalized email and/or normalized LinkedIn URL."""
    keys = []
    if email:
        keys.append(f"email:{email}")
    if linkedin:
        keys.append(f"li:{linkedin}")
    return keys
