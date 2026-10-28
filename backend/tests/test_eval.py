"""The labelled eval sets run as tests: the rules-only pipeline must never make an
unsafe status call on them (deferring to `needs review` is allowed)."""

import pytest

from stargo.config import DATA_DIR
from stargo.evaluation import run_eval


@pytest.mark.parametrize("name", ["labelled_messages.json", "holdout_messages.json"])
def test_rules_pipeline_makes_no_unsafe_status_calls(name):
    report = run_eval(path=DATA_DIR / "eval" / name)
    assert report.count("unsafe") == 0, report.render()
    assert report.count("rejected") == 0, report.render()


def test_eval_flags_unsafe_errors():
    # A broken extractor that calls everything a demo must show up as unsafe calls.
    class AlwaysDemo:
        name = "always-demo"

        def extract(self, message, crm):
            return {"language": "en", "intent": "demo",
                    "data_problem": {"category": "rate_quoting", "summary": "x"}}

    report = run_eval(AlwaysDemo, path=DATA_DIR / "eval" / "labelled_messages.json")
    assert report.count("unsafe") > 0
