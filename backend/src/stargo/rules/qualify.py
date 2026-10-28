"""Agent B, deterministic part: the QL gate, exclusions, status, owner and score.

Inputs are validated Agent A extractions plus CRM facts. Message text is only
read here by the injection detector, which can push a lead to `needs review`
but can never qualify it.
"""

from dataclasses import dataclass
from datetime import datetime

from stargo.agents.injection import detect_injection
from stargo.agents.schemas import INTEREST_INTENTS, Extraction, ExtractionResult
from stargo.config import REPORT_TZ
from stargo.domain.accounts import Account
from stargo.domain.identity import Person
from stargo.domain.models import InboundMessage, SalesDecision, Status
from stargo.domain.normalize import ICP_REGIONS, ICP_VERTICALS, region_for_country
from stargo.domain.qualification import (
    ConditionCheck,
    ExclusionCode,
    Qualification,
)
from stargo.rules.buyer import is_relevant_buyer, seniority
from stargo.rules.routing import base_owner, route
from stargo.rules.scoring import priority_score

MIN_EMPLOYEES = 20


@dataclass
class LeadContext:
    person: Person
    messages: list[InboundMessage]
    results: dict[str, ExtractionResult]
    account: Account | None
    decisions: list[SalesDecision]


@dataclass(frozen=True)
class Fact:
    value: object
    verified: bool
    source: str

    def describe(self) -> str:
        return f"{self.value} ({self.source}{'' if self.verified else ', unverified'})"


UNKNOWN = Fact(None, False, "unknown")


def _effective_decisions(decisions: list[SalesDecision], as_of: datetime) -> list[SalesDecision]:
    return sorted((d for d in decisions if d.decided_at <= as_of),
                  key=lambda d: (d.decided_at, d.id))


def commercial_exclusion(
    person: Person, account: Account | None, first_inbound_at: datetime | None,
    first_acceptance_at: datetime | None,
) -> ExclusionCode | None:
    """Existing customer, or an open deal created before first inbound and acceptance.

    Deal dates are day-precision, so a deal created on the same Israel-time day as the
    inbound or acceptance counts as pre-existing (the conservative reading).
    """
    crm = person.crm
    if (crm and crm.is_customer) or (account and account.is_customer):
        return "existing_customer"
    if crm and crm.open_deal_id and crm.open_deal_created:
        deal_day = crm.open_deal_created

        def deal_first(ts: datetime | None) -> bool:
            return ts is None or deal_day <= ts.astimezone(REPORT_TZ).date()

        if deal_first(first_inbound_at) and deal_first(first_acceptance_at):
            return "preexisting_open_deal"
    return None


def _firmographic_facts(ctx: LeadContext, extractions: list[Extraction]) -> dict[str, Fact]:
    crm, account = ctx.person.crm, ctx.account

    def from_crm(field: str) -> Fact | None:
        for holder, label in ((account, "CRM account"), (crm, "CRM contact")):
            value = getattr(holder, field, None) if holder else None
            if value is not None:
                return Fact(value, True, label)
        return None

    def stated(field: str) -> Fact | None:
        for extraction in reversed(extractions):
            value = getattr(extraction.company_facts, field)
            if value is not None:
                return Fact(value, False, "stated in message")
        return None

    facts = {f: from_crm(f) or stated(f) or UNKNOWN for f in ("vertical", "employees", "country")}
    country = facts["country"]
    facts["region"] = (Fact(region_for_country(country.value), country.verified, country.source)
                       if country.value else UNKNOWN)
    if crm and crm.job_title:
        facts["title"] = Fact(crm.job_title, True, "CRM contact")
    else:
        role = next((e.buyer_role for e in reversed(extractions) if e.buyer_role), None)
        facts["title"] = Fact(role, False, "stated in message") if role else UNKNOWN
    name = (account.name if account else None) or next(
        (e.company_facts.company_name for e in reversed(extractions)
         if e.company_facts.company_name), None)
    facts["company"] = Fact(name, account is not None, "CRM account" if account else "stated")
    return facts


def _icp_condition(facts: dict[str, Fact]) -> ConditionCheck:
    vertical, employees, region = facts["vertical"], facts["employees"], facts["region"]
    checks: list[bool | None] = []
    evidence = []
    if vertical.value is None:
        checks.append(None)
        evidence.append("vertical unknown")
    else:
        checks.append(vertical.value in ICP_VERTICALS)
        evidence.append(f"vertical {vertical.describe()}")
    if employees.value is None:
        checks.append(None)
        evidence.append("employee count unknown")
    else:
        checks.append(employees.value >= MIN_EMPLOYEES)
        evidence.append(f"employees {employees.describe()}")
    if region.value is None:
        checks.append(None)
        evidence.append("region unknown")
    else:
        checks.append(region.value in ICP_REGIONS)
        evidence.append(f"region {region.describe()}")
    met = False if False in checks else None if None in checks else True
    verified = all(f.verified for f in (vertical, employees, region))
    return ConditionCheck(key="icp_fit", label="Company fit (ICP)", met=met, verified=verified,
                          evidence=evidence)


def qualify(ctx: LeadContext, *, now: datetime) -> Qualification:
    person = ctx.person
    messages = sorted(ctx.messages, key=lambda m: (m.received_at, m.id))
    flags = list(person.flags)
    extractions: list[tuple[InboundMessage, Extraction]] = []
    for message in messages:
        result = ctx.results.get(message.id)
        if result is None or result.status != "ok" or result.extraction is None:
            error = result.error if result else "not analysed"
            flags.append(f"analysis failed for {message.id} ({error})")
        else:
            extractions.append((message, result.extraction))
        if hits := detect_injection(message.subject, message.body):
            flags.append(f"{message.id} tries to instruct the system ({', '.join(hits)})")

    intents = [e.intent for _, e in extractions]
    substantive = [(m, e) for m, e in extractions if e.intent != "auto_reply"]
    ext_only = [e for _, e in extractions]

    decisions = _effective_decisions(ctx.decisions, now)
    latest = decisions[-1] if decisions else None
    acceptances = [d for d in decisions if d.decision == "accepted"]
    first_inbound_at = messages[0].received_at if messages else None
    first_acceptance_at = acceptances[0].decided_at if acceptances else None

    facts = _firmographic_facts(ctx, ext_only)
    crm_owner = (person.crm.owner if person.crm else None) or (
        ctx.account.owner if ctx.account else None)

    # Conditions 1 to 5
    c1 = _icp_condition(facts)
    title = facts["title"]
    buyer_met, buyer_reason = is_relevant_buyer(title.value, facts["employees"].value)
    c2 = ConditionCheck(key="relevant_buyer", label="Relevant buyer", met=buyer_met,
                        verified=title.verified,
                        evidence=[f"{buyer_reason} [{title.source}]"])
    problems = [(m, e) for m, e in substantive if e.data_problem]
    if problems:
        m, e = problems[0]
        c3 = ConditionCheck(key="data_problem", label="Specific data problem", met=True,
                            verified=True,
                            evidence=[f"{e.data_problem.category} [{m.id}]: "
                                      f"\"{e.data_problem.summary}\""])
    else:
        c3 = ConditionCheck(key="data_problem", label="Specific data problem",
                            met=False if substantive else None, verified=True,
                            evidence=["no specific data problem stated" if substantive
                                      else "no inbound message on record"])
    latest_intent = substantive[-1][1].intent if substantive else None
    interested = [(m, e) for m, e in substantive if e.intent in INTEREST_INTENTS]
    if interested:
        # Interest, once expressed, stays a fact: a later decline is shown, not erased, so
        # a past week's QL does not disappear when the lead goes cold.
        m, e = interested[0]
        quote = next((q for q in e.evidence if q not in (e.data_problem.summary
                                                         if e.data_problem else "")),
                     e.evidence[-1] if e.evidence else "")
        evidence = [f"{e.intent} [{m.id}]: \"{quote}\""]
        if latest_intent == "not_interested":
            evidence.append(f"latest message [{substantive[-1][0].id}] declines")
        c4 = ConditionCheck(key="expressed_interest", label="Expressed interest", met=True,
                            verified=True, evidence=evidence)
    else:
        c4 = ConditionCheck(key="expressed_interest", label="Expressed interest",
                            met=False if substantive else None, verified=True,
                            evidence=[f"latest intent: {latest_intent}" if substantive
                                      else "no inbound message on record"])
    if latest is None:
        c5 = ConditionCheck(key="sales_acceptance", label="Recorded sales acceptance", met=None,
                            verified=True, evidence=["no sales decision yet"])
    else:
        c5 = ConditionCheck(
            key="sales_acceptance", label="Recorded sales acceptance",
            met=latest.decision == "accepted", verified=True,
            evidence=[f"{latest.decision} by {latest.decided_by or 'unknown'} at "
                      f"{latest.decided_at.astimezone(REPORT_TZ):%Y-%m-%d %H:%M} [{latest.id}]"])
    conditions = [c1, c2, c3, c4, c5]
    gate_values = [c.met for c in conditions[:4]]

    # Status
    commercial = commercial_exclusion(person, ctx.account, first_inbound_at, first_acceptance_at)
    is_investor = "investor" in intents or facts["vertical"].value == "investor"
    exclusion: ExclusionCode | None = None
    status: Status
    if "unsubscribe" in intents:
        status, exclusion = "suppressed", "unsubscribe"
    elif flags:
        status = "needs review"
    else:
        if commercial:
            exclusion = commercial
        elif (ctx.account and ctx.account.is_competitor) or (
                person.crm and (person.crm.lead_status or "").lower() == "competitor") or (
                facts["vertical"].value == "software-vendor"):
            exclusion = "competitor_or_vendor"
        elif is_investor:
            exclusion = "investor"
        elif "job_seeker" in intents:
            exclusion = "job_seeker"
        elif extractions and not substantive:
            exclusion = "auto_reply"

        if exclusion:
            status = "excluded"
        elif latest and latest.decision == "rejected" or c1.met is False or c2.met is False:
            status = "disqualified"
        elif c3.met is False or c4.met is False:
            status = "nurture"
        elif None in gate_values:
            status = "needs review"
            missing = [c.label for c in conditions[:4] if c.met is None]
            flags.append(f"cannot confirm: {', '.join(missing)}")
        else:
            status = "QL" if c5.met else "QL candidate"

    gate_passed = all(v is True for v in gate_values) and exclusion is None and not flags
    base = base_owner(facts["region"].value, commercial, crm_owner, is_investor)
    owner = route(status, exclusion, base)

    score = None
    if extractions:
        best_intent = max(intents, key=lambda i: {"pilot": 3, "demo": 3, "pricing": 2,
                                                  "other": 1}.get(i, 0))
        score = priority_score(
            intent=None if exclusion else best_intent,
            problem_category=problems[0][1].data_problem.category if problems else None,
            problem_text=problems[0][1].data_problem.summary if problems else None,
            buyer_met=buyer_met,
            buyer_level=seniority(title.value) if title.value else None,
            buyer_verified=title.verified,
            vertical=(facts["vertical"].value, facts["vertical"].verified),
            employees=(facts["employees"].value, facts["employees"].verified),
            region=(facts["region"].value, facts["region"].verified),
            substantive_messages=len(substantive),
            channels=len({m.channel for m, _ in substantive}),
        )

    name = (person.crm.full_name if person.crm else None) or next(
        (m.from_name for m in messages if m.from_name), None)
    first = messages[0] if messages else None
    return Qualification(
        person_id=person.person_id,
        name=name,
        company=facts["company"].value,
        region=facts["region"].value,
        status=status,
        exclusion=exclusion,
        conditions=conditions,
        gate_1_to_4_met=gate_passed,
        review_flags=flags,
        score=score,
        owner=owner,
        rationale=_rationale(status, exclusion, conditions, flags, latest),
        first_inbound_id=first.id if first else None,
        first_source=first.source if first else None,
        message_ids=[m.id for m in messages],
        decision_ids=[d.id for d in decisions],
    )


_EXCLUSION_TEXT = {
    "existing_customer": "existing customer, reported as expansion",
    "preexisting_open_deal": "open deal pre-dates this inbound; routed to deal owner",
    "competitor_or_vendor": "competitor or vendor",
    "investor": "investor enquiry, routed to Founders",
    "job_seeker": "job seeker or student",
    "auto_reply": "auto-reply only",
    "unsubscribe": "asked to unsubscribe; suppressed, no outreach",
}


def _rationale(status, exclusion, conditions, flags, latest) -> str:
    if status == "needs review":
        return f"Needs review: {flags[0]}."
    if exclusion:
        note = f" Sales {latest.decision} it; kept on record." if latest else ""
        return f"{status.capitalize()}: {_EXCLUSION_TEXT[exclusion]}.{note}"
    failing = [c for c in conditions[:4] if c.met is False]
    if latest and latest.decision == "rejected":
        return f"Disqualified: rejected by sales ({conditions[4].evidence[0]})."
    if failing:
        detail = "; ".join(f"{c.label}: {c.evidence[0]}" for c in failing)
        accepted = " Sales accepted it, but acceptance does not override the gate." if (
            latest and latest.decision == "accepted") else ""
        return f"{status.capitalize()}: fails {detail}.{accepted}"
    problem = conditions[2].evidence[0]
    interest = conditions[3].evidence[0]
    tail = "accepted by sales" if status == "QL" else "awaiting sales acceptance"
    return f"{status}: conditions 1-4 met; {problem}; {interest}; {tail}."
