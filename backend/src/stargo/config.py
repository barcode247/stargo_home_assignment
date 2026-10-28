"""Static configuration: paths, reporting time zone, targets and allowed values."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

REPORT_TZ = ZoneInfo("Asia/Jerusalem")

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("STARGO_DATA_DIR", REPO_ROOT / "data"))
DB_PATH = Path(os.environ.get("STARGO_DB_PATH", REPO_ROOT / "backend" / "stargo.db"))

WEEKLY_TARGETS = {
    "qls": 25,
    "meetings_booked": 15,
    "meetings_held": 12,
    "opportunities": 5,
}

SOURCES = (
    "event-email",
    "paid",
    "historical-reactivation",
    "new-connection",
    "warm-network",
    "organic/referral",
)

CHANNELS = ("email_reply", "form_fill", "linkedin_dm")

MAX_BODY_CHARS = 5000
