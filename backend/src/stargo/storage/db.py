"""SQLite persistence. Records are stored as validated JSON so a restart reloads
exactly what the pipeline decided."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from stargo.agents.schemas import ExtractionResult
from stargo.domain.models import (
    CrmRecord,
    InboundMessage,
    PipelineEvent,
    Rejection,
    SalesDecision,
)
from stargo.domain.qualification import Qualification

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS crm_records (record_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, received_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS extractions (message_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY, contact_key TEXT NOT NULL, decided_at TEXT NOT NULL,
    data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pipeline_events (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feed_status (source TEXT PRIMARY KEY, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rejections (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS qualifications (person_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS drafts (person_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS briefs (prompt_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kpi_packs (
    week_start TEXT PRIMARY KEY, computed_at TEXT NOT NULL, data TEXT NOT NULL);
"""


def _utc(ts: datetime) -> str:
    """UTC text so SQL ORDER BY sorts mixed-offset timestamps correctly."""
    return ts.astimezone(UTC).isoformat()


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        # The API serialises access with a lock, so one connection can be shared by threads.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.conn:
            yield self.conn

    # meta
    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    # writes
    def put_crm(self, records: list[CrmRecord]) -> None:
        with self.conn:
            self.conn.executemany("INSERT OR REPLACE INTO crm_records VALUES (?, ?)",
                                  [(r.record_id, r.model_dump_json()) for r in records])

    def put_message(self, message: InboundMessage) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO messages VALUES (?, ?, ?)",
                              (message.id, _utc(message.received_at),
                               message.model_dump_json()))

    def put_extraction(self, result: ExtractionResult) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO extractions VALUES (?, ?)",
                              (result.message_id, result.model_dump_json()))

    def put_decision(self, decision: SalesDecision) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO decisions VALUES (?, ?, ?, ?)",
                              (decision.id, decision.contact_key,
                               _utc(decision.decided_at), decision.model_dump_json()))

    def put_pipeline_events(self, events: list[PipelineEvent]) -> None:
        with self.conn:
            self.conn.executemany("INSERT OR REPLACE INTO pipeline_events VALUES (?, ?)",
                                  [(e.id, e.model_dump_json()) for e in events])

    def put_feed_status(self, status: dict[str, str]) -> None:
        with self.conn:
            self.conn.executemany("INSERT OR REPLACE INTO feed_status VALUES (?, ?)",
                                  list(status.items()))

    def put_rejection(self, rejection: Rejection) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO rejections (ref, data) VALUES (?, ?)",
                              (rejection.ref, rejection.model_dump_json()))

    def replace_qualifications(self, quals: list[Qualification]) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM qualifications")
            self.conn.executemany("INSERT INTO qualifications VALUES (?, ?)",
                                  [(q.person_id, q.model_dump_json()) for q in quals])

    def put_kpi_pack(self, week_start: str, computed_at: datetime, data: str) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO kpi_packs VALUES (?, ?, ?)",
                              (week_start, computed_at.isoformat(), data))

    # reads
    def _rows(self, sql: str) -> list[str]:
        return [row[0] for row in self.conn.execute(sql)]

    def crm(self) -> list[CrmRecord]:
        return [CrmRecord.model_validate_json(d)
                for d in self._rows("SELECT data FROM crm_records ORDER BY record_id")]

    def messages(self) -> list[InboundMessage]:
        return [InboundMessage.model_validate_json(d)
                for d in self._rows("SELECT data FROM messages ORDER BY received_at, id")]

    def message_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    def extractions(self) -> dict[str, ExtractionResult]:
        results = (ExtractionResult.model_validate_json(d)
                   for d in self._rows("SELECT data FROM extractions"))
        return {r.message_id: r for r in results}

    def decisions(self) -> list[SalesDecision]:
        return [SalesDecision.model_validate_json(d)
                for d in self._rows("SELECT data FROM decisions ORDER BY decided_at, id")]

    def pipeline_events(self) -> list[PipelineEvent]:
        return [PipelineEvent.model_validate_json(d)
                for d in self._rows("SELECT data FROM pipeline_events ORDER BY id")]

    def feed_status(self) -> dict[str, str]:
        return dict(self.conn.execute("SELECT source, status FROM feed_status"))

    def rejections(self) -> list[Rejection]:
        return [Rejection.model_validate_json(d)
                for d in self._rows("SELECT data FROM rejections ORDER BY seq")]

    def qualifications(self) -> list[Qualification]:
        return [Qualification.model_validate_json(d)
                for d in self._rows("SELECT data FROM qualifications ORDER BY person_id")]

    def put_json(self, table: str, key: str, data: str) -> None:
        assert table in ("drafts", "briefs")
        with self.conn:
            self.conn.execute(f"INSERT OR REPLACE INTO {table} VALUES (?, ?)", (key, data))

    def get_json(self, table: str, key: str) -> str | None:
        assert table in ("drafts", "briefs")
        key_col = "person_id" if table == "drafts" else "prompt_id"
        row = self.conn.execute(f"SELECT data FROM {table} WHERE {key_col} = ?",
                                (key,)).fetchone()
        return row[0] if row else None

    def kpi_pack(self, week_start: str) -> dict | None:
        row = self.conn.execute("SELECT data FROM kpi_packs WHERE week_start = ?",
                                (week_start,)).fetchone()
        return json.loads(row[0]) if row else None
