"""Weekly KPI pack (ql_standard.md section 6).

Recomputed from stored decisions, events and qualifications every time. Every
number carries the records behind it, and an unreceived feed is reported as
unknown (None), never 0.
"""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from stargo.config import REPORT_TZ, SOURCES, WEEKLY_TARGETS
from stargo.domain.identity import IdentityIndex, Person
from stargo.domain.models import PipelineEvent, SalesDecision
from stargo.domain.qualification import ExclusionCode, Qualification
from stargo.kpi.window import ReportingWindow

NOT_RECORDED = "source not recorded"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KpiRecord(Strict):
    person_id: str
    name: str | None
    company: str | None
    refs: list[str]
    note: str | None = None


class KpiLine(Strict):
    key: str
    label: str
    actual: int | None
    target: int | None
    records: list[KpiRecord]


class SourceLine(Strict):
    source: str
    feed: str
    count: int | None
    records: list[KpiRecord]


class KpiPack(Strict):
    week_start: str
    week_end: str
    week_label: str
    timezone: str
    computed_at: str
    acquisition: list[KpiLine]
    qls_by_source: list[SourceLine]
    expansion: list[KpiLine]
    not_counted: list[KpiRecord]
    data_notes: list[str]


@dataclass
class KpiInputs:
    index: IdentityIndex
    qualifications: dict[str, Qualification]
    commercial: dict[str, ExclusionCode | None]
    decisions: list[SalesDecision]
    events: list[PipelineEvent]
    feed_status: dict[str, str]
    first_inbound_at: dict[str, datetime]


def _local(ts: datetime) -> str:
    return f"{ts.astimezone(REPORT_TZ):%a %d %b %H:%M}"


def _record(person: Person | None, q: Qualification | None, refs: list[str],
            note: str | None = None, fallback_id: str = "unmatched") -> KpiRecord:
    return KpiRecord(
        person_id=person.person_id if person else fallback_id,
        name=q.name if q else (person.crm.full_name if person and person.crm else None),
        company=q.company if q else (person.crm.company_name if person and person.crm else None),
        refs=refs,
        note=note,
    )


def compute_kpi_pack(window: ReportingWindow, data: KpiInputs, *, computed_at: datetime) -> KpiPack:
    notes: list[str] = []
    not_counted: list[KpiRecord] = []

    by_person: dict[str, list[SalesDecision]] = {}
    for decision in data.decisions:
        person = data.index.person_for_key(decision.contact_key)
        if person is None:
            notes.append(f"Decision {decision.id} matches no known person; not counted.")
            continue
        if decision.decided_at < window.end:
            by_person.setdefault(person.person_id, []).append(decision)

    qls: list[tuple[KpiRecord, str]] = []
    expansion_accepts: list[KpiRecord] = []
    for person_id, decisions in sorted(by_person.items()):
        decisions.sort(key=lambda d: (d.decided_at, d.id))
        person = data.index.people[person_id]
        q = data.qualifications.get(person_id)
        accepted = [d for d in decisions if d.decision == "accepted"]
        in_window = [d for d in accepted if window.contains(d.decided_at)]
        if not in_window:
            continue
        refs = [d.id for d in in_window]
        dup = " (duplicate acceptance entries counted once)" if len(in_window) > 1 else ""
        if decisions[-1].decision == "rejected":
            rejected_at = _local(decisions[-1].decided_at)
            not_counted.append(_record(person, q, refs + [decisions[-1].id],
                                       f"accepted, then rejected {rejected_at}"))
        elif accepted[0].decided_at < window.start:
            not_counted.append(_record(person, q, [accepted[0].id] + refs,
                                       f"first accepted {_local(accepted[0].decided_at)}, "
                                       "counted in that week"))
        elif data.commercial.get(person_id) == "existing_customer":
            expansion_accepts.append(_record(person, q, refs, "existing customer" + dup))
        elif data.commercial.get(person_id) == "preexisting_open_deal":
            not_counted.append(_record(person, q, refs, "open deal pre-dates the lead"))
        elif q is None or not q.gate_1_to_4_met:
            reason = q.rationale if q else "no qualification on record"
            not_counted.append(_record(person, q, refs, f"accepted but not a QL: {reason}"))
        else:
            source = q.first_source or NOT_RECORDED
            refs = refs + ([q.first_inbound_id] if q.first_inbound_id else [])
            qls.append((_record(person, q, refs, f"first touch {source}{dup}"), source))

    # Inbound received this week but accepted after it: counts in the acceptance week.
    for person_id, q in sorted(data.qualifications.items()):
        first_at = data.first_inbound_at.get(person_id)
        if (q.status == "QL" and first_at and window.contains(first_at)
                and person_id not in by_person):
            not_counted.append(KpiRecord(
                person_id=person_id, name=q.name, company=q.company,
                refs=[r for r in (q.first_inbound_id, *q.decision_ids) if r],
                note="inbound this week, accepted after the week ends; counts in that week"))

    event_lines: dict[str, list[KpiRecord]] = {t: [] for t in
                                               ("meeting_booked", "meeting_held",
                                                "opportunity_created")}
    expansion_events: dict[str, list[KpiRecord]] = {t: [] for t in event_lines}
    for event in data.events:
        if not window.contains(event.occurred_at):
            continue
        person = data.index.person_for_key(event.contact_key)
        q = data.qualifications.get(person.person_id) if person else None
        when = f"{_local(event.occurred_at)} Israel time"
        if person is None:
            notes.append(f"{event.id} matches no known contact; counted as acquisition.")
            event_lines[event.type].append(_record(None, None, [event.id], when))
            continue
        commercial = data.commercial.get(person.person_id)
        if commercial == "existing_customer":
            expansion_events[event.type].append(_record(person, q, [event.id], when))
        elif commercial == "preexisting_open_deal":
            not_counted.append(_record(person, q, [event.id],
                                       f"{event.type} on a pre-existing open deal ({when})"))
        else:
            event_lines[event.type].append(_record(person, q, [event.id], when))

    source_lines = []
    for source in (*SOURCES, NOT_RECORDED):
        records = [r for r, s in qls if s == source]
        feed = "n/a" if source == NOT_RECORDED else data.feed_status.get(source, "not_received")
        count: int | None = len(records)
        if feed != "received" and source != NOT_RECORDED and not records:
            count = None
            notes.append(f"Feed '{source}' was not received: QLs from it are unknown, not zero.")
        source_lines.append(SourceLine(source=source, feed=feed, count=count, records=records))

    acquisition = [
        KpiLine(key="qls", label="QLs (accepted this week)", actual=len(qls),
                target=WEEKLY_TARGETS["qls"], records=[r for r, _ in qls]),
        KpiLine(key="meetings_booked", label="Meetings booked",
                actual=len(event_lines["meeting_booked"]),
                target=WEEKLY_TARGETS["meetings_booked"], records=event_lines["meeting_booked"]),
        KpiLine(key="meetings_held", label="Meetings held",
                actual=len(event_lines["meeting_held"]),
                target=WEEKLY_TARGETS["meetings_held"], records=event_lines["meeting_held"]),
        KpiLine(key="opportunities", label="Opportunities created",
                actual=len(event_lines["opportunity_created"]),
                target=WEEKLY_TARGETS["opportunities"],
                records=event_lines["opportunity_created"]),
    ]
    expansion = [
        KpiLine(key="expansion_accepted", label="Expansion enquiries accepted",
                actual=len(expansion_accepts), target=None, records=expansion_accepts),
        *[KpiLine(key=f"expansion_{t}", label=f"Expansion {t.replace('_', ' ')}",
                  actual=len(recs), target=None, records=recs)
          for t, recs in expansion_events.items()],
    ]
    return KpiPack(
        week_start=window.start.isoformat(),
        week_end=window.end.isoformat(),
        week_label=window.label(),
        timezone=str(REPORT_TZ),
        computed_at=computed_at.isoformat(),
        acquisition=acquisition,
        qls_by_source=source_lines,
        expansion=expansion,
        not_counted=not_counted,
        data_notes=notes,
    )
