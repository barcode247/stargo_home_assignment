"""Owner routing (ql_standard.md section 5)."""

from stargo.domain.models import Status
from stargo.domain.qualification import ExclusionCode

TRIAGE = "Triage queue"
FOUNDERS = "Founders"

REGION_OWNERS = {
    "Benelux": "Dana",
    "Nordics": "Dana",
    "UK": "Leo",
    "DACH": "Leo",
    "Singapore": "Mei",
    "APAC": "Mei",
    "United States": "Sam",
    "Israel": "Noa",
}

_NO_OWNER_EXCLUSIONS = frozenset({"competitor_or_vendor", "job_seeker", "unsubscribe"})


def base_owner(
    region: str | None, commercial: ExclusionCode | None, crm_owner: str | None,
    is_investor: bool,
) -> str:
    """The owner the account or region would get, ignoring status."""
    if commercial in ("existing_customer", "preexisting_open_deal"):
        return crm_owner or TRIAGE
    if is_investor:
        return FOUNDERS
    return REGION_OWNERS.get(region or "", TRIAGE)


def route(status: Status, exclusion: ExclusionCode | None, base: str) -> str | None:
    if status in ("disqualified", "suppressed"):
        return None
    if status == "excluded" and exclusion in _NO_OWNER_EXCLUSIONS:
        return None
    return base
