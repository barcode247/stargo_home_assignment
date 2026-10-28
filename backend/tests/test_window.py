from datetime import date, datetime

import pytest

from stargo.ingest.validation import parse_timestamp
from stargo.kpi.window import ReportingWindow

WEEK = ReportingWindow(date(2026, 10, 4))


def ts(value: str) -> datetime:
    return parse_timestamp(value, field="t")


@pytest.mark.parametrize("value, inside", [
    ("2026-10-03T21:00:00Z", True),         # Sun 00:00 Israel
    ("2026-10-03T20:59:59Z", False),        # Sat 23:59:59 Israel
    ("2026-10-04T00:00:00+03:00", True),
    ("2026-10-08T20:30:00Z", True),         # Thu 23:30 Israel (IN-017)
    ("2026-10-08T23:59:59+03:00", True),
    ("2026-10-08T21:30:00Z", False),        # Fri 00:30 Israel (IN-018)
    ("2026-10-09T00:00:00+03:00", False),
    ("2026-10-07T05:00:00Z", True),         # Wed 08:00 Israel (PE-007)
    ("2026-10-08T23:00:00-04:00", False),   # New York evening = Fri morning Israel
])
def test_window_converts_to_israel_time(value, inside):
    assert WEEK.contains(ts(value)) is inside


def test_week_must_start_on_sunday():
    with pytest.raises(ValueError):
        ReportingWindow(date(2026, 10, 5))


def test_naive_timestamps_are_refused_by_window():
    with pytest.raises(ValueError):
        WEEK.contains(datetime(2026, 10, 5, 12, 0))


def test_window_across_dst_change():
    # Israel leaves DST at 02:00 on Sun 25 Oct 2026: the week starts at +03 and ends at +02.
    week = ReportingWindow(date(2026, 10, 25))
    assert week.start.utcoffset().total_seconds() == 3 * 3600
    assert week.end.utcoffset().total_seconds() == 2 * 3600
    assert week.contains(ts("2026-10-24T21:00:00Z"))
    assert not week.contains(ts("2026-10-24T20:59:00Z"))
    assert week.contains(ts("2026-10-29T21:59:00Z"))      # Thu 23:59 Israel, now +02
    assert not week.contains(ts("2026-10-29T22:00:00Z"))  # Fri 00:00 Israel
