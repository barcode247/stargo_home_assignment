"""HTTP API. Thin: validation and rules live in the pipeline; this maps them to HTTP.

Run: uv run uvicorn stargo.api:build_default_app --factory --port 8000
"""

import logging
import threading
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from stargo.agents.llm_extractor import LlmExtractor
from stargo.agents.reply_drafter import DraftNotAllowed, ReplyDrafter
from stargo.config import DATA_DIR, DB_PATH, REPO_ROOT
from stargo.ingest.validation import RecordRejected
from stargo.kpi.render import render_markdown
from stargo.llm.client import ChatClient, LlmSettings, load_dotenv, load_settings
from stargo.pipeline import Pipeline
from stargo.storage.db import Store
from stargo.visibility.analysis import VisibilitySnapshot, load_snapshot
from stargo.visibility.brief import BriefGenerator, ContentBrief

log = logging.getLogger("stargo.api")
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InboundIn(Strict):
    # Everything optional here so the pipeline's validator reports readable reasons.
    from_name: str | None = None
    from_email: str | None = None
    linkedin_url: str | None = None
    channel: str | None = None
    subject: str | None = None
    body: str | None = Field(default=None, max_length=20_000)
    received_at: str | None = None
    source: str | None = None


class DecisionIn(Strict):
    decision: str
    decided_by: str | None = None
    decided_at: str | None = None
    note: str | None = Field(default=None, max_length=1000)


class ApproveIn(Strict):
    approved_by: str


def create_app(pipeline: Pipeline, *, data_dir: Path = DATA_DIR,
               llm: LlmSettings | None = None, brief_generator: BriefGenerator | None = None,
               serve_frontend: bool = True) -> FastAPI:
    app = FastAPI(title="Stargo GTM pipeline", version="0.1.0")
    lock = threading.Lock()  # one SQLite connection, low traffic: serialise requests
    snapshot: VisibilitySnapshot = load_snapshot(data_dir / "ai_answers.json")
    briefs = brief_generator or BriefGenerator(data_dir / "brand_context.md")

    @app.exception_handler(RecordRejected)
    async def rejected(_: Request, exc: RecordRejected) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": exc.reasons})

    @app.exception_handler(RequestValidationError)
    async def bad_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Field name and message only: never echo the submitted values back.
        reasons = [f"{'.'.join(str(p) for p in e['loc'][1:]) or 'request'}: {e['msg']}"
                   for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": reasons})

    @app.exception_handler(DraftNotAllowed)
    async def not_allowed(_: Request, exc: DraftNotAllowed) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": [str(exc)]})

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "mode": f"llm ({llm.label})" if llm else "rules-only (no LLM key)",
                "extractor": getattr(pipeline.extractor, "name", "unknown")}

    @app.get("/api/leads")
    def leads() -> list[dict[str, Any]]:
        with lock:
            return pipeline.lead_queue()

    @app.get("/api/leads/{person_id}")
    def lead(person_id: str) -> dict[str, Any]:
        with lock:
            return pipeline.lead_detail(person_id)

    @app.post("/api/inbound")
    def submit(payload: InboundIn) -> dict[str, Any]:
        with lock:
            result = pipeline.submit_inbound(payload.model_dump())
        if not result.accepted:
            raise RecordRejected(result.reasons)
        return {"message_id": result.message_id, "person_id": result.person_id}

    @app.post("/api/leads/{person_id}/decisions")
    def decide(person_id: str, payload: DecisionIn) -> dict[str, Any]:
        with lock:
            decision = pipeline.record_decision(person_id, payload.decision,
                                                decided_by=payload.decided_by,
                                                decided_at=payload.decided_at,
                                                note=payload.note)
            return {"decision": decision, "qualification": pipeline.qualification(person_id)}

    @app.post("/api/leads/{person_id}/reanalyse")
    def reanalyse(person_id: str) -> dict[str, Any]:
        with lock:
            return {"qualification": pipeline.reanalyse(person_id)}

    @app.post("/api/reanalyse-failed")
    def reanalyse_failed() -> dict[str, int]:
        with lock:
            return pipeline.reanalyse_failed()

    @app.post("/api/leads/{person_id}/draft")
    def draft(person_id: str) -> dict[str, Any]:
        with lock:
            return {"draft": pipeline.draft_reply(person_id)}

    @app.post("/api/leads/{person_id}/draft/approve")
    def approve(person_id: str, payload: ApproveIn) -> dict[str, Any]:
        with lock:
            return {"draft": pipeline.approve_draft(person_id, payload.approved_by),
                    "sent": False}

    @app.get("/api/kpi")
    def kpi(week: date = date(2026, 10, 4)) -> dict[str, Any]:
        try:
            with lock:
                pack = pipeline.kpi_pack(week)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=[str(exc)]) from None
        return {"pack": pack, "markdown": render_markdown(pack)}

    @app.get("/api/rejections")
    def rejections() -> list[dict[str, Any]]:
        with lock:
            return [r.model_dump() for r in pipeline.store.rejections()]

    @app.get("/api/visibility")
    def visibility() -> dict[str, Any]:
        with lock:
            stored = [pipeline.store.get_json("briefs", g.prompt_id) for g in snapshot.gaps]
        return {"snapshot": snapshot,
                "briefs": [ContentBrief.model_validate_json(b) for b in stored if b]}

    @app.post("/api/visibility/briefs/{prompt_id}")
    def make_brief(prompt_id: str) -> dict[str, Any]:
        gap = next((g for g in snapshot.gaps if g.prompt_id == prompt_id), None)
        if gap is None:
            raise HTTPException(status_code=404, detail=[f"unknown prompt {prompt_id}"])
        brief = briefs.generate(gap, snapshot.known_competitors, pipeline.clock())
        with lock:
            pipeline.store.put_json("briefs", prompt_id, brief.model_dump_json())
        return {"brief": brief}

    if serve_frontend and FRONTEND_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


def build_default_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    load_dotenv(REPO_ROOT / ".env")
    settings = load_settings()
    client = ChatClient(settings) if settings else None
    pipeline = Pipeline(
        Store(DB_PATH),
        extractor=LlmExtractor(client) if client else None,
        drafter=ReplyDrafter(client),
    )
    log.info("mode: %s", settings.label if settings else "rules-only")
    pipeline.seed_if_empty(DATA_DIR)
    return create_app(pipeline, llm=settings,
                      brief_generator=BriefGenerator(DATA_DIR / "brand_context.md", client))
