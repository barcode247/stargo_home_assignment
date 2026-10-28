from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from stargo.config import DATA_DIR
from stargo.pipeline import Pipeline
from stargo.storage.db import Store

IL = ZoneInfo("Asia/Jerusalem")
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=IL)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def make_pipeline(db_path):
    stores = []

    def _make(extractor=None, seed=True) -> Pipeline:
        store = Store(db_path)
        stores.append(store)
        pipeline = Pipeline(store, extractor=extractor, clock=lambda: NOW)
        if seed:
            pipeline.seed_if_empty(DATA_DIR)
        return pipeline

    yield _make
    for store in stores:
        store.close()


@pytest.fixture
def seeded(make_pipeline) -> Pipeline:
    return make_pipeline()


@pytest.fixture
def quals(seeded):
    return {q.person_id: q for q in seeded.store.qualifications()}


IN_WEEK_LEAD = {
    "from_name": "Lotte Bakker", "from_email": "lotte@deltaforwarding.nl",
    "channel": "form_fill", "source": "paid", "received_at": "2026-10-06T10:00:00+03:00",
    "body": "We're a 120-person freight forwarder in Rotterdam. I am the head of pricing. "
            "We build every spot quote by hand from email rate requests. Could we see a demo?",
}


def add_in_week_candidate(pipeline) -> str:
    """A QL candidate whose inbound falls inside the 4-8 Oct week; returns its person id."""
    result = pipeline.submit_inbound(dict(IN_WEEK_LEAD))
    assert pipeline.qualification(result.person_id).status == "QL candidate"
    return result.person_id


def inbound(**overrides):
    raw = {
        "from_name": "Test Person",
        "from_email": "test.person@examplefreight.com",
        "linkedin_url": None,
        "channel": "email_reply",
        "source": "paid",
        "received_at": "2026-10-06T10:00:00+03:00",
        "subject": None,
        "body": "Hello.",
    }
    raw.update(overrides)
    return raw
