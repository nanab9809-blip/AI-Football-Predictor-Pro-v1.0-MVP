from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
WITA = ZoneInfo("Asia/Makassar")


def now_utc() -> datetime:
    """Current timezone-aware UTC timestamp for persistence and audit logs."""
    return datetime.now(UTC)


def now_wita() -> datetime:
    """Current timezone-aware operational time in Asia/Makassar (WITA)."""
    return datetime.now(WITA)


def today_wita() -> date:
    """Current operational calendar date in Asia/Makassar."""
    return now_wita().date()


def today_wita_iso() -> str:
    return today_wita().isoformat()


def to_wita(value: datetime) -> datetime:
    """Convert an aware timestamp to WITA; naive values are treated as UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(WITA)
