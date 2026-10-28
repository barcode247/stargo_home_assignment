"""Command line entry points.

    python -m stargo.cli leads                 # seed on first run, print the lead queue
    python -m stargo.cli kpi --week 2026-10-04 --out ../KPI_PACK.md
    python -m stargo.cli reset                 # delete the local database
"""

import argparse
import logging
from datetime import date
from pathlib import Path

from stargo.config import DATA_DIR, DB_PATH, REPORT_TZ
from stargo.kpi.render import render_markdown
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
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)


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
    kpi.set_defaults(fn=cmd_kpi)
    sub.add_parser("reset").set_defaults(fn=cmd_reset)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
