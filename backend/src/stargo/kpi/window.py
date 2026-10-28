"""Reporting week: Sunday 00:00 to Thursday 23:59:59, Asia/Jerusalem."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from stargo.config import REPORT_TZ


@dataclass(frozen=True)
class ReportingWindow:
    start_date: date

    def __post_init__(self) -> None:
        if self.start_date.weekday() != 6:
            raise ValueError("a reporting week starts on a Sunday")

    @property
    def start(self) -> datetime:
        return datetime.combine(self.start_date, time(0), REPORT_TZ)

    @property
    def end(self) -> datetime:
        """Exclusive end: Friday 00:00 Israel time."""
        return datetime.combine(self.start_date + timedelta(days=5), time(0), REPORT_TZ)

    @property
    def last_day(self) -> date:
        return self.start_date + timedelta(days=4)

    def contains(self, ts: datetime) -> bool:
        if ts.tzinfo is None:
            raise ValueError("timestamps must carry an offset")
        return self.start <= ts < self.end

    def label(self) -> str:
        return (f"Sun {self.start_date.day} {self.start_date:%b} to "
                f"Thu {self.last_day.day} {self.last_day:%b %Y}")
