"""Score the pipeline against hand-labelled messages it has never seen.

Each case runs as a new inbound message on a freshly seeded database, so cases
cannot affect each other. Status outcomes are graded three ways:

- correct: matches the label
- safe deferral: predicted `needs review` where the label is something else
  (a human looks; nothing wrong is recorded)
- unsafe: any other mismatch, e.g. a QL candidate that should be excluded,
  or a real lead disqualified. These are the errors that cost pipeline or trust.
"""

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from stargo.config import DATA_DIR, REPORT_TZ
from stargo.pipeline import Extractor, Pipeline
from stargo.storage.db import Store

EVAL_PATH = DATA_DIR / "eval" / "labelled_messages.json"
EVAL_NOW = datetime(2026, 10, 12, 12, 0, tzinfo=REPORT_TZ)
FIELDS = ("intent", "problem", "status", "owner")


@dataclass
class CaseResult:
    case_id: str
    note: str
    expected: dict
    actual: dict
    outcome: str  # correct | safe_deferral | unsafe | rejected


@dataclass
class EvalReport:
    extractor: str
    results: list[CaseResult] = field(default_factory=list)

    def accuracy(self, name: str) -> float:
        hits = sum(r.expected[name] == r.actual.get(name) for r in self.results)
        return hits / len(self.results) if self.results else 0.0

    def count(self, outcome: str) -> int:
        return sum(r.outcome == outcome for r in self.results)

    def render(self) -> str:
        n = len(self.results)
        lines = [f"Eval: {n} labelled messages, extractor {self.extractor}", ""]
        for name in FIELDS:
            lines.append(f"  {name:<8} accuracy {self.accuracy(name):6.1%}")
        lines += ["", f"  status correct        {self.count('correct')}/{n}",
                  f"  safe deferrals        {self.count('safe_deferral')}/{n}",
                  f"  unsafe status errors  {self.count('unsafe')}/{n}",
                  f"  rejected as invalid   {self.count('rejected')}/{n}", ""]
        for r in self.results:
            if r.outcome == "correct" and all(r.expected[f] == r.actual.get(f) for f in FIELDS):
                continue
            diffs = ", ".join(f"{f}: expected {r.expected[f]!r} got {r.actual.get(f)!r}"
                              for f in FIELDS if r.expected[f] != r.actual.get(f))
            lines.append(f"  {r.case_id} [{r.outcome}] {r.note}: {diffs}")
        return "\n".join(lines)


def _grade(expected: str, actual: str | None) -> str:
    if actual == expected:
        return "correct"
    if actual == "needs review":
        return "safe_deferral"
    return "unsafe"


def _pipeline(db: Path, extractor_factory) -> Pipeline:
    extractor: Extractor | None = extractor_factory() if extractor_factory else None
    return Pipeline(Store(db), extractor=extractor, clock=lambda: EVAL_NOW)


def build_template(directory: Path, extractor_factory=None) -> Path:
    """Seed once; every case starts from a copy, so a model sees each seed message once."""
    template = directory / "template.db"
    pipeline = _pipeline(template, extractor_factory)
    pipeline.seed_if_empty(DATA_DIR)
    pipeline.store.close()
    return template


def run_eval(extractor_factory=None, path: Path = EVAL_PATH, template: Path | None = None,
             progress=None) -> EvalReport:
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    report: EvalReport | None = None
    with tempfile.TemporaryDirectory() as tmp:
        template = template or build_template(Path(tmp), extractor_factory)
        for i, case in enumerate(cases):
            db = Path(tmp) / f"case{i}.db"
            shutil.copyfile(template, db)
            pipeline = _pipeline(db, extractor_factory)
            store = pipeline.store
            if report is None:
                report = EvalReport(extractor=pipeline.extractor.name)
            if progress:
                progress(f"{case['id']} ({i + 1}/{len(cases)})")
            result = pipeline.submit_inbound(case["input"])
            if not result.accepted:
                actual = {"rejected": result.reasons}
                outcome = "rejected"
            else:
                q = pipeline.qualification(result.person_id)
                extraction = pipeline.store.extractions()[result.message_id].extraction
                actual = {
                    "intent": extraction.intent if extraction else None,
                    "problem": (extraction.data_problem.category
                                if extraction and extraction.data_problem else None),
                    "status": q.status,
                    "owner": q.owner,
                }
                outcome = _grade(case["expected"]["status"], q.status)
            report.results.append(CaseResult(case["id"], case.get("note", ""),
                                             case["expected"], actual, outcome))
            store.close()
    return report
