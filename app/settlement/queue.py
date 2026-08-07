from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class QueueSnapshot:
    ready: list[dict[str, Any]]
    waiting: list[dict[str, Any]]
    recovery: list[dict[str, Any]]
    investigation: list[dict[str, Any]]
    settled: dict[str, int]
    observations: int = 0

    @property
    def pending(self) -> int:
        return len(self.ready) + len(self.waiting) + len(self.recovery) + len(self.investigation)

    def summary(self) -> dict[str, int]:
        now_utc = datetime.now(timezone.utc)
        recovery_due = sum(1 for row in self.recovery if SettlementQueueService._retry_due(row, now_utc))
        recovery_backoff = len(self.recovery) - recovery_due
        ready_due = sum(1 for row in self.ready if SettlementQueueService._retry_due(row, now_utc))
        investigation_due = sum(1 for row in self.investigation if SettlementQueueService._investigation_due(row, now_utc))
        values = {
            "pending": self.pending,
            "ready": len(self.ready),
            "ready_due": ready_due,
            "waiting": len(self.waiting),
            "recovery": len(self.recovery),
            "recovery_due": recovery_due,
            "recovery_backoff": recovery_backoff,
            "needs_investigation": len(self.investigation),
            "investigation_due": investigation_due,
            "overdue_pending": len(self.ready) + len(self.recovery) + investigation_due,
            "due_now": ready_due + recovery_due + investigation_due,
        }
        values.update(self.settled)
        values["observations"] = int(self.observations or 0)
        return values


class SettlementQueueService:
    """Single source of truth for settlement queues and dashboard totals.

    Queue classification is computed once from the same database rows used by the
    engine, Prediction History and Automation Center. Diagnostic metadata never
    hides a PENDING prediction; only NEEDS_INVESTIGATION isolates it.
    """

    RECOVERY_STATES = {"RETRY", "RECOVERED", "RECOVERY"}
    STALE_API_STATUSES = {"NS", "TBD", "PST", "NOT_FOUND", "UNKNOWN", "API_ERROR", "ENGINE_ERROR"}

    def __init__(self, store: Any, *, timezone_name: str = "Asia/Makassar") -> None:
        self.store = store
        self.zone = ZoneInfo(timezone_name)

    @staticmethod
    def _fixture_day(row: dict[str, Any]) -> date | None:
        raw = str(row.get("fixture_date") or "")[:10]
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None



    def _fixture_kickoff(self, row: dict[str, Any]) -> datetime | None:
        raw = str(row.get("fixture_date") or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=self.zone)
            return parsed.astimezone(self.zone)
        except ValueError:
            day = self._fixture_day(row)
            return datetime.combine(day, datetime.min.time(), tzinfo=self.zone) if day else None

    @staticmethod
    def _investigation_due(row: dict[str, Any], now_utc: datetime) -> bool:
        raw = row.get("settlement_checked_at")
        if not raw:
            return True
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return (now_utc - parsed).total_seconds() >= 24 * 3600
        except (TypeError, ValueError):
            return True

    @staticmethod
    def _retry_due(row: dict[str, Any], now_utc: datetime) -> bool:
        raw = row.get("next_retry_at")
        if not raw:
            return True
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed <= now_utc
        except (TypeError, ValueError):
            return True

    def build(self) -> QueueSnapshot:
        loader = getattr(self.store, "settlement_queue_rows", None)
        rows = loader() if callable(loader) else self.store.pending_scanner_predictions()
        now_local = datetime.now(self.zone)
        today = now_local.date()
        ready: list[dict[str, Any]] = []
        waiting: list[dict[str, Any]] = []
        recovery: list[dict[str, Any]] = []
        investigation: list[dict[str, Any]] = []

        for row in rows:
            state = str(row.get("settlement_state") or "PENDING").upper()
            status = str(row.get("last_api_status") or row.get("fixture_status") or "UNKNOWN").upper()
            fixture_day = self._fixture_day(row)
            kickoff = self._fixture_kickoff(row)
            row["queue_fixture_day"] = fixture_day.isoformat() if fixture_day else None
            row["queue_kickoff"] = kickoff.isoformat() if kickoff else None

            if state == "NEEDS_INVESTIGATION":
                row["queue_bucket"] = "INVESTIGATION"
                investigation.append(row)
                continue
            if kickoff is not None and kickoff > now_local:
                row["queue_bucket"] = "WAITING"
                waiting.append(row)
                continue
            if kickoff is None and fixture_day is not None and fixture_day > today:
                row["queue_bucket"] = "WAITING"
                waiting.append(row)
                continue
            if state in self.RECOVERY_STATES or (fixture_day is not None and fixture_day < today and status in self.STALE_API_STATUSES):
                row["queue_bucket"] = "RECOVERY"
                recovery.append(row)
                continue
            row["queue_bucket"] = "READY"
            ready.append(row)

        def sort_key(row: dict[str, Any]) -> tuple[str, str, int]:
            return (
                str(row.get("fixture_date") or "9999-12-31"),
                str(row.get("settlement_checked_at") or ""),
                int(row.get("id") or 0),
            )

        ready.sort(key=sort_key)
        recovery.sort(key=sort_key)
        waiting.sort(key=sort_key)
        investigation.sort(key=sort_key)
        totals_loader = getattr(self.store, "settlement_result_totals", None)
        if callable(totals_loader):
            settled = totals_loader()
        else:
            raw = getattr(self.store, "settlement_totals", lambda: {})()
            settled = {key: int(raw.get(key) or 0) for key in ("wins", "losses", "voids", "settled")}
        summary_loader = getattr(self.store, "prediction_history_summary", None)
        observations = int(summary_loader().get("observations") or 0) if callable(summary_loader) else 0
        return QueueSnapshot(ready, waiting, recovery, investigation, settled, observations)

    def fixture_batch(self, *, mode: str = "PRIORITY", limit: int = 10) -> list[dict[str, Any]]:
        snapshot = self.build()
        mode = str(mode or "PRIORITY").upper()
        investigation_due = [row for row in snapshot.investigation if self._investigation_due(row, datetime.now(timezone.utc))]
        if mode == "OVERDUE":
            candidates = snapshot.recovery + snapshot.ready + investigation_due
        elif mode == "RECOVERY":
            candidates = snapshot.recovery + investigation_due
        else:
            candidates = snapshot.recovery + snapshot.ready + investigation_due

        # Respect retry backoff during execution so repeated manual clicks do not
        # hammer the same ten stale fixtures and prematurely move them to
        # NEEDS_INVESTIGATION. Dashboard counts still include every pending row.
        now_utc = datetime.now(timezone.utc)
        candidates = [row for row in candidates if self._retry_due(row, now_utc)]

        selected: list[dict[str, Any]] = []
        seen: set[int] = set()
        for row in candidates:
            try:
                fixture_id = int(row.get("fixture_id"))
            except (TypeError, ValueError):
                continue
            if fixture_id in seen:
                continue
            seen.add(fixture_id)
            selected.append(row)
            if len(selected) >= max(1, int(limit)):
                break
        return selected

    def rows_for_fixture(self, fixture_id: int) -> list[dict[str, Any]]:
        loader = getattr(self.store, "pending_predictions_by_fixture", None)
        if callable(loader):
            return loader(int(fixture_id))
        return [row for row in self.store.pending_scanner_predictions() if int(row.get("fixture_id") or 0) == int(fixture_id)]
