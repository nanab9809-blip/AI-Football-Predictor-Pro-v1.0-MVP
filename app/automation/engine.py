from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.clients.api_football import ApiFootballClient, ApiFootballError
from app.database.store import Store
from app.settlement import FixtureRecoveryEngine, ResultResolver, RunHistoryBuilder, SettlementQueueService

logger = logging.getLogger("uvicorn.error")


class AutomationEngine:
    """V9 unified settlement pipeline.

    Every execution, dashboard and history view uses SettlementQueueService. Retry
    metadata can explain a failure but never silently hides PENDING predictions.
    """

    BATCH_SIZE = 10
    MAX_RETRIES = 5
    STALE_STATUSES = {"NS", "TBD", "PST", "NOT_FOUND", "UNKNOWN"}
    RETRY_DELAYS = (timedelta(minutes=30), timedelta(hours=2), timedelta(hours=6), timedelta(hours=12))

    def __init__(self, client: ApiFootballClient, store: Store, *, interval_minutes: int = 30) -> None:
        self.client = client
        self.store = store
        self.interval_seconds = max(5, int(interval_minutes)) * 60
        self.queue = SettlementQueueService(store)
        self.recovery = FixtureRecoveryEngine(client, store)
        self.resolver = ResultResolver()
        self.history = RunHistoryBuilder(self.queue)
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._run_lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="automatic-settlement")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        await asyncio.sleep(10)
        while not self._stop_event.is_set():
            try:
                await self.run_once(trigger="SCHEDULED")
            except Exception:  # pragma: no cover
                logger.exception("Scheduled settlement failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    def _next_retry_at(self, retry_count: int) -> str:
        index = min(max(retry_count - 1, 0), len(self.RETRY_DELAYS) - 1)
        return (datetime.now(timezone.utc) + self.RETRY_DELAYS[index]).isoformat()

    def _record_failure(self, fixture_id: int, *, status: str, reason: str, recovery: bool = False) -> tuple[int, bool]:
        retry = self.store.record_fixture_settlement_attempt(
            fixture_id,
            fixture_status=status,
            reason=reason,
            state="RECOVERY" if recovery else "RETRY",
            increment_retry=True,
            increment_recovery=recovery,
            next_retry_at=None,
        )
        if retry >= self.MAX_RETRIES:
            self.store.mark_fixture_needs_investigation(
                fixture_id,
                status=status,
                reason=f"{reason}. Batas {self.MAX_RETRIES} percobaan tercapai.",
            )
            return retry, True
        self.store.record_fixture_settlement_attempt(
            fixture_id,
            fixture_status=status,
            reason=reason,
            state="RECOVERY" if recovery else "RETRY",
            increment_retry=False,
            increment_recovery=False,
            next_retry_at=self._next_retry_at(retry),
        )
        return retry, False

    async def _fixture_payload(self, fixture_id: int) -> dict[str, Any] | None:
        payload = await self.client.fixture_by_id(int(fixture_id), fresh=True)
        response = payload.get("response") or []
        return response[0] if response else None

    async def run_once(self, *, trigger: str = "MANUAL", overdue_only: bool = False) -> dict[str, Any]:
        if self._run_lock.locked():
            return {"status": "SKIPPED", "message": "Settlement lain masih berjalan."}

        async with self._run_lock:
            started_at = datetime.now(timezone.utc).isoformat()
            run_id = self.store.start_automation_run("AUTO_SETTLEMENT", trigger, started_at)
            mode = "OVERDUE" if overdue_only else "PRIORITY"
            counts = {
                "checked_fixtures": 0, "settled": 0, "wins": 0, "losses": 0,
                "voids": 0, "not_final": 0, "not_found": 0, "recovered": 0,
                "needs_investigation": 0, "errors": 0, "queue_mode": mode,
            }
            details: list[dict[str, Any]] = []

            try:
                quota_exhausted = getattr(self.client, "quota_is_exhausted", lambda: False)
                if quota_exhausted():
                    summary = self.history.build(base={**counts, "status": "QUOTA_EXHAUSTED", "run_id": run_id, "trigger": trigger}, details=[])
                    self.store.finish_automation_run(run_id, "QUOTA_EXHAUSTED", summary)
                    return summary

                candidates = self.queue.fixture_batch(mode=mode, limit=self.BATCH_SIZE)
                counts["checked_fixtures"] = len(candidates)
                logger.info(
                    "SETTLEMENT_BATCH mode=%s candidates=%s fixture_ids=%s",
                    mode, len(candidates), [row.get("fixture_id") for row in candidates],
                )

                for representative in candidates:
                    original_id = int(representative["fixture_id"])
                    active_id = original_id
                    try:
                        fixture = await self._fixture_payload(original_id)
                        resolution_status = self.resolver.status(fixture)
                        logger.info(
                            "SETTLEMENT_FIXTURE fixture_id=%s bucket=%s api_status=%s date=%s home=%s away=%s",
                            original_id, representative.get("queue_bucket"), resolution_status,
                            representative.get("fixture_date"), representative.get("home_team"),
                            representative.get("away_team"),
                        )

                        # A stale or missing historical fixture is relinked by date/team/league.
                        if representative.get("queue_bucket") == "RECOVERY" and resolution_status in self.STALE_STATUSES:
                            recovered_fixture, reason = await self.recovery.recover(representative)
                            if recovered_fixture:
                                recovered_id = self.recovery.fixture_id(recovered_fixture)
                                logger.info(
                                    "SETTLEMENT_RECOVERY fixture_id=%s recovered_id=%s reason=%s",
                                    original_id, recovered_id, reason,
                                )
                                if recovered_id and recovered_id != original_id:
                                    self.store.recover_fixture_id(original_id, recovered_id, reason=reason)
                                    active_id = recovered_id
                                    counts["recovered"] += 1
                                    details.append({"fixture_id": original_id, "new_fixture_id": recovered_id, "status": "RECOVERED", "reason": reason})
                                fixture = recovered_fixture
                            else:
                                logger.info(
                                    "SETTLEMENT_RECOVERY_FAILED fixture_id=%s status=%s reason=%s",
                                    original_id, resolution_status, reason,
                                )
                                retry, investigated = self._record_failure(original_id, status=resolution_status, reason=reason, recovery=True)
                                counts["not_found"] += int(resolution_status == "NOT_FOUND")
                                counts["not_final"] += int(resolution_status != "NOT_FOUND")
                                counts["needs_investigation"] += int(investigated)
                                details.append({"fixture_id": original_id, "status": "NEEDS_INVESTIGATION" if investigated else resolution_status, "reason": reason, "retry": retry})
                                continue

                        prediction_rows = self.queue.rows_for_fixture(active_id)
                        if not prediction_rows:
                            # This can happen immediately after a relink if another run settled it.
                            continue

                        first_resolution = self.resolver.resolve(prediction_rows[0], fixture)
                        if not first_resolution.final:
                            logger.info(
                                "SETTLEMENT_NOT_FINAL fixture_id=%s status=%s reason=%s",
                                active_id, first_resolution.status, first_resolution.reason,
                            )
                            retry, investigated = self._record_failure(
                                active_id,
                                status=first_resolution.status,
                                reason=first_resolution.reason,
                                recovery=representative.get("queue_bucket") == "RECOVERY",
                            )
                            counts["not_final"] += 1
                            counts["needs_investigation"] += int(investigated)
                            details.append({"fixture_id": active_id, "status": "NEEDS_INVESTIGATION" if investigated else first_resolution.status, "reason": first_resolution.reason, "retry": retry})
                            continue

                        fixture_settled = 0
                        unsupported_reasons: list[str] = []
                        for prediction in prediction_rows:
                            resolution = self.resolver.resolve(prediction, fixture)
                            if not resolution.final:
                                continue
                            if not resolution.result:
                                unsupported_reasons.append(resolution.reason)
                                logger.warning(
                                    "SETTLEMENT_UNSUPPORTED fixture_id=%s prediction_id=%s market_key=%s pick=%s reason=%s",
                                    active_id, prediction.get("id"), prediction.get("market_key"), prediction.get("pick"), resolution.reason,
                                )
                                continue
                            updated = self.store.settle_prediction_id(
                                int(prediction["id"]), resolution.result,
                                fixture_status=resolution.status,
                                home_score=resolution.home_score,
                                away_score=resolution.away_score,
                            )
                            if not updated:
                                continue
                            fixture_settled += 1
                            counts["settled"] += 1
                            counts["wins"] += int(resolution.result == "WIN")
                            counts["losses"] += int(resolution.result == "LOSS")
                            counts["voids"] += int(resolution.result == "VOID")
                            logger.info(
                                "SETTLEMENT_RESOLVED fixture_id=%s prediction_id=%s result=%s status=%s score=%s-%s",
                                active_id, prediction["id"], resolution.result, resolution.status,
                                resolution.home_score, resolution.away_score,
                            )
                            details.append({
                                "prediction_id": prediction["id"], "fixture_id": active_id,
                                "market": prediction.get("market_key"), "result": resolution.result,
                                "status": resolution.status,
                                "score": f"{resolution.home_score}-{resolution.away_score}" if resolution.home_score is not None else "-",
                                "reason": resolution.reason,
                            })

                        if fixture_settled == 0:
                            reason = (
                                "; ".join(dict.fromkeys(unsupported_reasons))
                                if unsupported_reasons
                                else "Final tersedia tetapi tidak ada prediction PENDING yang dapat diperbarui"
                            )
                            retry, investigated = self._record_failure(active_id, status=first_resolution.status, reason=reason)
                            counts["needs_investigation"] += int(investigated)
                            details.append({
                                "fixture_id": active_id, "status": "UNSUPPORTED_MARKET" if unsupported_reasons else "NO_UPDATE",
                                "reason": reason, "retry": retry,
                            })

                    except ApiFootballError as exc:
                        counts["errors"] += 1
                        retry, investigated = self._record_failure(active_id, status="API_ERROR", reason=str(exc))
                        counts["needs_investigation"] += int(investigated)
                        details.append({"fixture_id": active_id, "status": "API_ERROR", "reason": str(exc), "retry": retry})
                        if quota_exhausted():
                            break
                    except Exception as exc:  # isolate one fixture
                        counts["errors"] += 1
                        logger.exception("Settlement fixture %s gagal", active_id)
                        retry, investigated = self._record_failure(active_id, status="ENGINE_ERROR", reason=f"{type(exc).__name__}: {exc}")
                        counts["needs_investigation"] += int(investigated)
                        details.append({"fixture_id": active_id, "status": "ENGINE_ERROR", "reason": str(exc), "retry": retry})

                status = "QUOTA_EXHAUSTED" if quota_exhausted() else ("SUCCESS" if counts["errors"] == 0 else "PARTIAL")
                if counts["settled"]:
                    self.store.refresh_performance_intelligence()
                summary = self.history.build(base={**counts, "status": status, "run_id": run_id, "trigger": trigger}, details=details)
                self.store.finish_automation_run(run_id, status, summary)
                return summary
            except Exception as exc:
                self.store.finish_automation_run(run_id, "FAILED", {"error": str(exc), **counts})
                raise
