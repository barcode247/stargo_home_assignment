"""Application service: one path for seed data and pasted messages.

inbound -> validate -> store -> resolve identity -> Agent A (extract + validate)
        -> Agent B (deterministic gate) -> store qualifications
"""

import csv
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

from stargo.agents.reply_drafter import DraftRecord, ReplyDrafter, check_eligible
from stargo.agents.rules_extractor import LowConfidence, RulesExtractor, UnsupportedLanguage
from stargo.agents.schemas import ExtractionResult, InvalidExtraction, validate_extraction
from stargo.config import REPORT_TZ
from stargo.domain.accounts import account_for, build_accounts
from stargo.domain.identity import IdentityIndex, resolve_people
from stargo.domain.models import CrmRecord, InboundMessage, Rejection, SalesDecision
from stargo.domain.qualification import ExclusionCode, Qualification
from stargo.ingest.validation import (
    RecordRejected,
    validate_crm_row,
    validate_decision,
    validate_inbound,
    validate_pipeline_event,
)
from stargo.kpi.pack import KpiInputs, KpiPack, compute_kpi_pack
from stargo.kpi.window import ReportingWindow
from stargo.rules.qualify import LeadContext, commercial_exclusion, qualify
from stargo.storage.db import Store

log = logging.getLogger("stargo.pipeline")


class Extractor(Protocol):
    name: str

    def extract(self, message: InboundMessage, crm: CrmRecord | None) -> Any: ...


@dataclass
class SubmitResult:
    accepted: bool
    message_id: str | None
    person_id: str | None
    reasons: list[str]


@dataclass
class Snapshot:
    crm: list[CrmRecord]
    messages: dict[str, InboundMessage]
    index: IdentityIndex
    contexts: dict[str, LeadContext]
    commercial: dict[str, ExclusionCode | None]


class Pipeline:
    def __init__(self, store: Store, extractor: Extractor | None = None,
                 clock: Callable[[], datetime] | None = None,
                 drafter: ReplyDrafter | None = None) -> None:
        self.store = store
        self.extractor = extractor or RulesExtractor()
        self.drafter = drafter or ReplyDrafter()
        self.clock = clock or (lambda: datetime.now(UTC))

    # ---------- ingest ----------

    def seed_if_empty(self, data_dir: Path) -> bool:
        if self.store.get_meta("seeded_at"):
            return False
        crm = []
        with open(data_dir / "crm_export.csv", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    crm.append(validate_crm_row(row))
                except RecordRejected as exc:
                    self._reject(row.get("record_id") or "crm-row", "crm", exc.reasons)
        self.store.put_crm(crm)

        events = json.loads((data_dir / "gtm_events.json").read_text(encoding="utf-8"))
        self.store.put_feed_status(events.get("feed_status", {}))
        for raw in events.get("inbound", []):
            self.submit_inbound(raw, message_id=raw.get("id"), requalify=False)
        for raw in events.get("sales_decisions", []):
            try:
                self.store.put_decision(validate_decision(raw, origin="seed", now=self.clock()))
            except RecordRejected as exc:
                self._reject(str(raw.get("id")), "decision", exc.reasons)
        pipeline_events = []
        for raw in events.get("pipeline_events", []):
            try:
                pipeline_events.append(validate_pipeline_event(raw))
            except RecordRejected as exc:
                self._reject(str(raw.get("id")), "pipeline_event", exc.reasons)
        self.store.put_pipeline_events(pipeline_events)
        self.store.set_meta("seeded_at", self.clock().isoformat())
        self.requalify()
        return True

    def submit_inbound(self, raw: dict[str, Any], *, message_id: str | None = None,
                       requalify: bool = True) -> SubmitResult:
        message_id = message_id or f"UI-{uuid.uuid4().hex[:8]}"
        try:
            message = validate_inbound(raw, message_id=message_id, now=self.clock())
        except RecordRejected as exc:
            self._reject(message_id, "inbound", exc.reasons)
            return SubmitResult(False, None, None, exc.reasons)
        self.store.put_message(message)
        snapshot = self._snapshot()
        person = snapshot.index.person_for_message(message.id)
        self.store.put_extraction(self._analyse(message, person.crm))
        log.info("inbound %s stored for person %s", message.id, person.person_id)
        if requalify:
            self.requalify()
        return SubmitResult(True, message.id, person.person_id, [])

    def record_decision(self, person_id: str, decision: str, *, decided_by: str | None,
                        decided_at: datetime | str | None = None,
                        note: str | None = None) -> SalesDecision:
        snapshot = self._snapshot()
        person = snapshot.index.people.get(person_id)
        if person is None:
            raise RecordRejected([f"unknown person {person_id}"])
        record = validate_decision(
            {"id": f"UD-{uuid.uuid4().hex[:8]}", "contact_key": person.primary_key,
             "decision": decision, "decided_by": decided_by, "decided_at": decided_at,
             "note": note},
            origin="ui", now=self.clock())
        if record.decided_at > self.clock():
            raise RecordRejected(["decided_at cannot be in the future"])
        self.store.put_decision(record)
        log.info("decision %s recorded for person %s", record.id, person_id)
        self.requalify()
        return record

    def reanalyse(self, person_id: str) -> Qualification:
        """Retry Agent A on this person's failed messages, then requalify."""
        snapshot = self._snapshot()
        ctx = snapshot.contexts.get(person_id)
        if ctx is None:
            raise RecordRejected([f"unknown lead {person_id}"])
        for message in ctx.messages:
            result = ctx.results.get(message.id)
            if result is None or result.status == "failed":
                self.store.put_extraction(self._analyse(message, ctx.person.crm))
        self.requalify()
        return self.qualification(person_id)

    # ---------- drafts (never sent) ----------

    def draft_reply(self, person_id: str) -> DraftRecord:
        snapshot = self._snapshot()
        ctx = snapshot.contexts.get(person_id)
        if ctx is None:
            raise RecordRejected([f"unknown lead {person_id}"])
        q = self.qualification(person_id)
        extractions = [ctx.results[m.id].extraction for m in ctx.messages
                       if m.id in ctx.results and ctx.results[m.id].extraction]
        first_name = ctx.person.crm.first_name if ctx.person.crm else None
        draft = self.drafter.draft(q, extractions, first_name, self.clock())
        self.store.put_json("drafts", person_id, draft.model_dump_json())
        log.info("draft created for person %s by %s", person_id, draft.generator)
        return draft

    def draft(self, person_id: str) -> DraftRecord | None:
        raw = self.store.get_json("drafts", person_id)
        return DraftRecord.model_validate_json(raw) if raw else None

    def approve_draft(self, person_id: str, approved_by: str) -> DraftRecord:
        draft = self.draft(person_id)
        if draft is None:
            raise RecordRejected(["no draft to approve"])
        if not approved_by.strip():
            raise RecordRejected(["approver name is required"])
        # Status may have changed since drafting, e.g. an unsubscribe arrived.
        check_eligible(self.qualification(person_id))
        approved = draft.model_copy(update={"status": "approved",
                                            "approved_by": approved_by.strip(),
                                            "approved_at": self.clock().isoformat()})
        self.store.put_json("drafts", person_id, approved.model_dump_json())
        return approved

    def qualification(self, person_id: str) -> Qualification:
        for q in self.store.qualifications():
            if q.person_id == person_id:
                return q
        raise RecordRejected([f"unknown lead {person_id}"])

    def lead_queue(self) -> list[dict[str, Any]]:
        """One row per lead, newest inbound first."""
        snapshot = self._snapshot()
        rows = []
        for q in self.store.qualifications():
            ctx = snapshot.contexts.get(q.person_id)
            latest = ctx.messages[-1] if ctx and ctx.messages else None
            rows.append({
                "person_id": q.person_id, "name": q.name, "company": q.company,
                "channel": latest.channel if latest else None,
                "received_at": latest.received_at.astimezone(REPORT_TZ).isoformat()
                if latest else None,
                "score": q.score.total if q.score else None,
                "band": q.score.band if q.score else None,
                "status": q.status, "owner": q.owner,
                "flagged": bool(q.review_flags),
            })
        rows.sort(key=lambda r: r["received_at"] or "", reverse=True)
        return rows

    def lead_detail(self, person_id: str) -> dict[str, Any]:
        snapshot = self._snapshot()
        ctx = snapshot.contexts.get(person_id)
        if ctx is None:
            raise RecordRejected([f"unknown lead {person_id}"])
        return {
            "qualification": self.qualification(person_id),
            "messages": ctx.messages,
            "extractions": [ctx.results.get(m.id) for m in ctx.messages],
            "decisions": sorted(ctx.decisions, key=lambda d: (d.decided_at, d.id)),
            "crm": ctx.person.crm,
            "draft": self.draft(person_id),
        }

    # ---------- analysis ----------

    def _analyse(self, message: InboundMessage, crm: CrmRecord | None) -> ExtractionResult:
        name = getattr(self.extractor, "name", "unknown")
        try:
            raw = self.extractor.extract(message, crm)
            extraction = validate_extraction(raw, message.body)
        except UnsupportedLanguage as exc:
            error = f"rules extractor cannot read language '{exc}'"
        except LowConfidence as exc:
            error = f"rules extractor is not confident reading '{exc}' text"
        except InvalidExtraction as exc:
            error = f"invalid extractor output: {exc}"
        except TimeoutError:
            error = "extractor timed out"
        except Exception as exc:  # noqa: BLE001 - any model failure must degrade to review
            error = f"extractor error: {type(exc).__name__}"
        else:
            return ExtractionResult(message_id=message.id, extractor=name, status="ok",
                                    extraction=extraction)
        log.warning("analysis failed for %s: %s", message.id, error)
        return ExtractionResult(message_id=message.id, extractor=name, status="failed",
                                error=error)

    def _snapshot(self) -> Snapshot:
        crm = self.store.crm()
        messages = self.store.messages()
        index = resolve_people(crm, messages)
        accounts = build_accounts(crm)
        results = self.store.extractions()
        by_id = {m.id: m for m in messages}

        decisions_by_person: dict[str, list[SalesDecision]] = {}
        for decision in self.store.decisions():
            person = index.person_for_key(decision.contact_key)
            if person:
                decisions_by_person.setdefault(person.person_id, []).append(decision)

        contexts, commercial = {}, {}
        for person in index.people.values():
            msgs = [by_id[i] for i in person.message_ids]
            decisions = decisions_by_person.get(person.person_id, [])
            account = account_for(accounts, person.crm, person.email)
            accepted = sorted(d.decided_at for d in decisions if d.decision == "accepted")
            commercial[person.person_id] = commercial_exclusion(
                person, account, msgs[0].received_at if msgs else None,
                accepted[0] if accepted else None)
            if msgs or decisions:  # researched-only contacts are not leads
                contexts[person.person_id] = LeadContext(
                    person=person, messages=msgs,
                    results={i: results[i] for i in person.message_ids if i in results},
                    account=account, decisions=decisions)
        return Snapshot(crm, by_id, index, contexts, commercial)

    def requalify(self) -> list[Qualification]:
        snapshot = self._snapshot()
        now = self.clock()
        quals = [qualify(ctx, now=now) for ctx in snapshot.contexts.values()]
        self.store.replace_qualifications(quals)
        return quals

    # ---------- reporting ----------

    def kpi_pack(self, week_start: date) -> KpiPack:
        window = ReportingWindow(week_start)
        snapshot = self._snapshot()
        # Replay the week: judge each person on what was on record when the week ended, so a
        # later decline or unsubscribe does not rewrite a past week's numbers.
        quals = {}
        for pid, ctx in snapshot.contexts.items():
            as_of = LeadContext(
                person=ctx.person,
                messages=[m for m in ctx.messages if m.received_at < window.end],
                results=ctx.results, account=ctx.account,
                decisions=[d for d in ctx.decisions if d.decided_at < window.end])
            if as_of.messages or as_of.decisions:
                quals[pid] = qualify(as_of, now=window.end)
        first_inbound = {
            pid: snapshot.messages[ctx.person.message_ids[0]].received_at
            for pid, ctx in snapshot.contexts.items() if ctx.person.message_ids
        }
        pack = compute_kpi_pack(
            window,
            KpiInputs(index=snapshot.index, qualifications=quals,
                      commercial=snapshot.commercial, decisions=self.store.decisions(),
                      events=self.store.pipeline_events(),
                      feed_status=self.store.feed_status(), first_inbound_at=first_inbound),
            computed_at=self.clock())
        self.store.put_kpi_pack(week_start.isoformat(), self.clock(), pack.model_dump_json())
        return pack

    def _reject(self, ref: str, kind: str, reasons: list[str]) -> None:
        self.store.put_rejection(Rejection(ref=ref, kind=kind, reasons=reasons,
                                           rejected_at=self.clock()))
        log.info("rejected %s %s: %s", kind, ref, "; ".join(reasons))
