"""Validate and normalize raw records. Invalid input becomes a list of readable
reasons; it never raises past this module."""

from datetime import date, datetime
from typing import Any

from stargo.config import CHANNELS, MAX_BODY_CHARS, REPORT_TZ, SOURCES
from stargo.domain.models import (
    CrmRecord,
    InboundMessage,
    PipelineEvent,
    SalesDecision,
    identity_keys,
)
from stargo.domain.normalize import (
    NormalizationError,
    normalize_country,
    normalize_domain,
    normalize_email,
    normalize_linkedin,
    normalize_vertical,
)


class RecordRejected(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_timestamp(value: Any, *, field: str, default: datetime | None = None) -> datetime:
    """ISO-8601 timestamp. A value without an offset is read as Israel time."""
    if isinstance(value, datetime):
        parsed = value
    elif _text(value) is None:
        if default is None:
            raise RecordRejected([f"{field} is required"])
        parsed = default
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            raise RecordRejected([f"{field} is not a valid ISO-8601 timestamp"]) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=REPORT_TZ)
    return parsed


def _try(reasons: list[str], label: str, fn, value):
    try:
        return fn(value)
    except NormalizationError as exc:
        reasons.append(f"{label}: {exc}")
        return None


def validate_inbound(raw: dict[str, Any], *, message_id: str, now: datetime) -> InboundMessage:
    reasons: list[str] = []
    email = _try(reasons, "email", normalize_email, raw.get("from_email"))
    linkedin = _try(reasons, "linkedin_url", normalize_linkedin, raw.get("linkedin_url"))
    if not reasons and not (email or linkedin):
        reasons.append("either an email address or a LinkedIn profile URL is required")

    channel = _text(raw.get("channel"))
    if channel not in CHANNELS:
        reasons.append(f"channel must be one of {', '.join(CHANNELS)}")

    source = _text(raw.get("source"))
    if source is not None and source not in SOURCES:
        reasons.append(f"source must be blank or one of {', '.join(SOURCES)}")

    body = _text(raw.get("body"))
    if body is None:
        reasons.append("message text is empty")
    elif len(body) > MAX_BODY_CHARS:
        reasons.append(f"message text is longer than {MAX_BODY_CHARS} characters")

    try:
        received_at = parse_timestamp(raw.get("received_at"), field="received_at", default=now)
    except RecordRejected as exc:
        reasons.extend(exc.reasons)
        received_at = now
    if received_at > now:
        reasons.append("received_at is in the future")

    if reasons:
        raise RecordRejected(reasons)
    return InboundMessage(
        id=message_id,
        channel=channel,
        source=source,
        received_at=received_at,
        from_name=_text(raw.get("from_name")),
        email=email,
        linkedin=linkedin,
        subject=_text(raw.get("subject")),
        body=body,
    )


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _int(value: Any, label: str, reasons: list[str]) -> int | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return int(text.replace(",", ""))
    except ValueError:
        reasons.append(f"{label} is not a number")
        return None


def _date(value: Any, label: str, reasons: list[str]) -> date | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        reasons.append(f"{label} is not a valid date")
        return None


def validate_crm_row(row: dict[str, Any]) -> CrmRecord:
    reasons: list[str] = []
    record_id = _text(row.get("record_id"))
    if record_id is None:
        reasons.append("record_id is required")
    email = _try(reasons, "email", normalize_email, row.get("email"))
    linkedin = _try(reasons, "linkedin_url", normalize_linkedin, row.get("linkedin_url"))
    domain = _try(reasons, "company_domain", normalize_domain, row.get("company_domain"))
    record = dict(
        employees=_int(row.get("employees"), "employees", reasons),
        open_deal_created=_date(row.get("open_deal_created"), "open_deal_created", reasons),
        last_activity_date=_date(row.get("last_activity_date"), "last_activity_date", reasons),
    )
    if reasons:
        raise RecordRejected(reasons)
    return CrmRecord(
        record_id=record_id,
        first_name=_text(row.get("first_name")),
        last_name=_text(row.get("last_name")),
        email=email,
        job_title=_text(row.get("job_title")),
        linkedin=linkedin,
        company_name=_text(row.get("company_name")),
        company_domain=domain,
        country=normalize_country(row.get("country")),
        vertical=normalize_vertical(row.get("vertical")),
        lifecycle_stage=_text(row.get("lifecycle_stage")),
        lead_status=_text(row.get("lead_status")),
        is_customer=_bool(row.get("is_customer")),
        open_deal_id=_text(row.get("open_deal_id")),
        owner=_text(row.get("owner")),
        **record,
    )


def contact_key(email: Any = None, linkedin: Any = None) -> str:
    """Identity key for a decision or pipeline event; raises RecordRejected."""
    reasons: list[str] = []
    norm_email = _try(reasons, "contact_email", normalize_email, email)
    norm_li = _try(reasons, "contact_linkedin", normalize_linkedin, linkedin)
    keys = identity_keys(norm_email, norm_li)
    if reasons or not keys:
        raise RecordRejected(reasons or ["a contact email or LinkedIn URL is required"])
    return keys[0]


def validate_decision(raw: dict[str, Any], *, origin: str, now: datetime) -> SalesDecision:
    key = raw.get("contact_key") or contact_key(raw.get("contact_email"),
                                                 raw.get("contact_linkedin"))
    decision = _text(raw.get("decision"))
    if decision not in ("accepted", "rejected"):
        raise RecordRejected(["decision must be 'accepted' or 'rejected'"])
    return SalesDecision(
        id=str(raw["id"]),
        contact_key=key,
        decision=decision,
        decided_by=_text(raw.get("decided_by")),
        decided_at=parse_timestamp(raw.get("decided_at"), field="decided_at", default=now),
        note=_text(raw.get("note")),
        origin=origin,
    )


def validate_pipeline_event(raw: dict[str, Any]) -> PipelineEvent:
    event_type = _text(raw.get("type"))
    if event_type not in ("meeting_booked", "meeting_held", "opportunity_created"):
        raise RecordRejected([f"unknown pipeline event type {event_type!r}"])
    return PipelineEvent(
        id=str(raw["id"]),
        type=event_type,
        contact_key=contact_key(raw.get("contact_email"), raw.get("contact_linkedin")),
        occurred_at=parse_timestamp(raw.get("occurred_at"), field="occurred_at"),
    )
