"""Agent B output contract: the auditable qualification record for one person."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from stargo.domain.models import Status

ConditionKey = Literal[
    "icp_fit", "relevant_buyer", "data_problem", "expressed_interest", "sales_acceptance",
]
ExclusionCode = Literal[
    "existing_customer", "preexisting_open_deal", "competitor_or_vendor", "investor",
    "job_seeker", "auto_reply", "unsubscribe",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConditionCheck(Strict):
    key: ConditionKey
    label: str
    met: bool | None  # None = unknown, never treated as met
    verified: bool
    evidence: list[str]


class ScoreFactor(Strict):
    name: str
    points: int
    max_points: int
    reason: str


class PriorityScore(Strict):
    total: int = Field(ge=0, le=100)
    band: Literal["A", "B", "nurture"]
    factors: list[ScoreFactor]


class Qualification(Strict):
    person_id: str
    name: str | None
    company: str | None
    region: str | None
    status: Status
    exclusion: ExclusionCode | None
    conditions: list[ConditionCheck]
    gate_1_to_4_met: bool
    review_flags: list[str]
    score: PriorityScore | None
    owner: str | None
    rationale: str
    first_inbound_id: str | None
    first_source: str | None
    message_ids: list[str]
    decision_ids: list[str]
