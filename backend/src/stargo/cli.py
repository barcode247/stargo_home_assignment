"""Command line entry points.

    python -m stargo.cli leads                 # seed on first run, print the lead queue
    python -m stargo.cli kpi --week 2026-10-04 --note ../docs/cro_note.md --out ../KPI_PACK.md
    python -m stargo.cli eval                  # score against the labelled message sets
    python -m stargo.cli reset                 # delete the local database
"""

import argparse
import logging
import tempfile
from datetime import date
from pathlib import Path

from stargo.agents.llm_extractor import LlmExtractor
from stargo.config import DATA_DIR, DB_PATH, REPO_ROOT, REPORT_TZ
from stargo.evaluation import EVAL_PATH, build_template, run_eval
from stargo.kpi.render import render_markdown
from stargo.llm.client import ChatClient, load_dotenv, load_settings
from stargo.pipeline import Pipeline
from stargo.storage.db import Store


def _pipeline() -> Pipeline:
    pipeline = Pipeline(Store(DB_PATH))
    pipeline.seed_if_empty(DATA_DIR)
    return pipeline


def cmd_leads(_: argparse.Namespace) -> None:
    pipeline = _pipeline()
    quals = sorted(pipeline.store.qualifications(),
                   key=lambda q: -(q.score.total if q.score else -1))
    print(f"{'person':<12} {'name':<18} {'status':<13} {'score':>5} {'owner':<13} rationale")
    for q in quals:
        score = f"{q.score.total}{q.score.band[0]}" if q.score else "-"
        print(f"{q.person_id:<12} {(q.name or '')[:18]:<18} {q.status:<13} {score:>5} "
              f"{q.owner or '-':<13} {q.rationale[:90]}")
    for r in pipeline.store.rejections():
        print(f"rejected {r.kind} {r.ref}: {'; '.join(r.reasons)}")


def cmd_kpi(args: argparse.Namespace) -> None:
    pack = _pipeline().kpi_pack(date.fromisoformat(args.week))
    text = render_markdown(pack)
    if args.note:
        note = Path(args.note).read_text(encoding="utf-8").strip()
        text = f"{text.rstrip()}\n\n## Note to the CRO\n\n{note}\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)


def cmd_eval(args: argparse.Namespace) -> None:
    logging.disable(logging.INFO)
    factory = None
    if args.llm:
        load_dotenv(REPO_ROOT / ".env")
        settings = load_settings()
        if settings is None:
            raise SystemExit("--llm needs LLM_PROVIDER and LLM_API_KEY in .env")
        client = ChatClient(settings)  # one client, so its rate limit spans every call

        def factory() -> LlmExtractor:
            return LlmExtractor(client)

        print(f"Seeding once with {settings.label}; this makes one call per message.")

    def progress(label: str) -> None:
        print(f"  running {label}", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        template = build_template(Path(tmp), factory)
        for name in args.sets:
            report = run_eval(factory, path=EVAL_PATH.parent / name, template=template,
                              progress=progress if args.llm else None)
            print(report.render(), "\n")


def cmd_reset(_: argparse.Namespace) -> None:
    DB_PATH.unlink(missing_ok=True)
    print(f"deleted {DB_PATH}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="stargo")
    sub = parser.add_subparsers(required=True)
    sub.add_parser("leads").set_defaults(fn=cmd_leads)
    kpi = sub.add_parser("kpi")
    kpi.add_argument("--week", default="2026-10-04", help="Sunday the week starts, "
                     f"{REPORT_TZ}")
    kpi.add_argument("--out")
    kpi.add_argument("--note", help="markdown file appended as the note to the CRO")
    kpi.set_defaults(fn=cmd_kpi)
    ev = sub.add_parser("eval", help="score the pipeline on the labelled message sets")
    ev.add_argument("sets", nargs="*",
                    default=["labelled_messages.json", "holdout_messages.json"])
    ev.add_argument("--llm", action="store_true", help="use the model configured in .env")
    ev.set_defaults(fn=cmd_eval)
    sub.add_parser("reset").set_defaults(fn=cmd_reset)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
