from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.decision_policy import best_market_from_analysis, recommendation_from_analysis

from app.clients.api_football import ApiFootballClient
from app.database.store import Store
from app.services.analysis_service import AnalysisService
from app.services.fixture_service import FixtureService
from app.validation.settlement import FINAL_STATUSES, UPCOMING_STATUSES, VOID_STATUSES, fixture_score, settle_market


class ScannerConfigurationError(ValueError):
    """Raised before any API call when Scanner settings are unsafe."""


class ScannerService:
    """Resource-safe pre-match scanner.

    One browser request processes a small batch only. Repeating the scan resumes
    from fixtures that do not yet have a stored SCANNER snapshot, preventing the
    large fan-out that previously caused Render 502 responses.
    """

    BATCH_SIZE = 10
    MAX_BATCH = 10
    MAX_CONCURRENCY = 4
    FIXTURE_TIMEOUT_SECONDS = 60

    def __init__(self, client: ApiFootballClient, store: Store) -> None:
        self.client = client
        self.fixture_service = FixtureService(client)
        self.analysis = AnalysisService(client, store)
        self.store = store


    @staticmethod
    def _validate_league_configuration(cfg: dict[str, Any]) -> None:
        """Fail closed when SELECTED mode has no league IDs.

        This validation intentionally runs before grouped_fixtures(), therefore a
        mistaken empty selection cannot consume API quota or silently scan all leagues.
        """
        mode = str(cfg.get("scanner_league_filter_mode") or "SELECTED").upper().strip()
        if mode == "ALL":
            return
        raw_ids = cfg.get("scanner_allowed_league_ids") or []
        valid_ids: list[int] = []
        for value in raw_ids:
            try:
                valid_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        if not valid_ids:
            raise ScannerConfigurationError(
                "Tidak ada liga yang dipilih. Pilih minimal satu liga di Admin atau ubah mode ke Semua negara & semua liga."
            )



    @staticmethod
    def _latest_stored_by_fixture(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        """Return the newest stored prediction per fixture.

        predictions_for_date() is ordered by id DESC. Using a normal dict
        comprehension would overwrite the newest row with an older duplicate,
        causing Evidence Collector fixtures to remain eligible forever.
        """
        latest: dict[int, dict[str, Any]] = {}
        for row in rows:
            raw_id = row.get("fixture_id")
            if raw_id is None:
                continue
            try:
                fixture_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            latest.setdefault(fixture_id, row)
        return latest

    @staticmethod
    def _dedupe_fixtures(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[int] = set()
        result: list[dict[str, Any]] = []
        for item in items:
            try:
                fixture_id = int((item.get("fixture") or {}).get("id"))
            except (TypeError, ValueError):
                continue
            if fixture_id in seen:
                continue
            seen.add(fixture_id)
            result.append(item)
        return result

    @staticmethod
    def _refresh_state(row: dict[str, Any], *, now: datetime | None = None) -> tuple[bool, bool]:
        """Return (needs_refresh, due_now) for a stored evidence snapshot.

        WAITING evidence must not be selected again immediately. Without a
        cooldown, the same oldest fixtures occupy every batch and the queue
        appears stuck even though requests are consumed.
        """
        now = now or datetime.now(timezone.utc)
        try:
            payload = json.loads(row.get("payload") or "{}")
            analysis = payload.get("analysis") or payload
            collection = analysis.get("evidence_collection") or {}
            if collection.get("mode") != "EVIDENCE_COLLECTOR":
                return True, True

            items = collection.get("items") or {}
            waiting_keys = [k for k, v in items.items() if (v or {}).get("status") == "WAITING"]
            failed_keys = [k for k, v in items.items() if (v or {}).get("status") == "FAILED"]
            if not waiting_keys and not failed_keys:
                return False, False

            checked_raw = str(collection.get("checked_at") or "")
            try:
                checked_at = datetime.fromisoformat(checked_raw.replace("Z", "+00:00"))
                if checked_at.tzinfo is None:
                    checked_at = checked_at.replace(tzinfo=timezone.utc)
            except ValueError:
                checked_at = now - timedelta(days=1)

            # Provider failures can be retried after a short cooldown.
            if failed_keys:
                return True, now >= checked_at + timedelta(minutes=30)

            hours_to_kickoff = collection.get("hours_to_kickoff")
            try:
                hours_to_kickoff = float(hours_to_kickoff)
            except (TypeError, ValueError):
                hours_to_kickoff = None

            # Official line-ups normally appear close to kickoff. Do not keep
            # retrying them many hours in advance.
            only_late_data = set(waiting_keys).issubset({"lineups", "odds"})
            if only_late_data and hours_to_kickoff is not None:
                if "lineups" in waiting_keys and hours_to_kickoff > 3:
                    return True, False
                cooldown = timedelta(minutes=20 if hours_to_kickoff <= 3 else 60)
                return True, now >= checked_at + cooldown

            # Other incomplete evidence gets a longer rotation cooldown so the
            # next fixtures can progress through the batch queue.
            return True, now >= checked_at + timedelta(hours=2)
        except Exception:
            return True, True

    @classmethod
    def _needs_evidence_refresh(cls, row: dict[str, Any]) -> bool:
        return cls._refresh_state(row)[0]

    @classmethod
    def _evidence_refresh_due(cls, row: dict[str, Any]) -> bool:
        return cls._refresh_state(row)[1]

    @staticmethod
    def _kickoff_is_future(item: dict[str, Any]) -> bool:
        raw = str((item.get("fixture") or {}).get("date") or "")
        if not raw:
            return False
        try:
            kickoff = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if kickoff.tzinfo is None:
                kickoff = kickoff.replace(tzinfo=timezone.utc)
            return kickoff > datetime.now(timezone.utc)
        except ValueError:
            return False

    @classmethod
    def _is_upcoming(cls, item: dict[str, Any]) -> bool:
        status = str(((item.get("fixture") or {}).get("status") or {}).get("short") or "")
        return status in UPCOMING_STATUSES and cls._kickoff_is_future(item)

    @staticmethod
    def _league_is_allowed(item: dict[str, Any], cfg: dict[str, Any]) -> bool:
        """Return True when a fixture belongs to a configured scanner league.

        Filtering is disabled only when the admin explicitly turns it off. League
        IDs are used instead of display names so countries with similarly named
        competitions remain unambiguous.
        """
        mode = str(cfg.get("scanner_league_filter_mode") or "").upper().strip()
        if mode == "ALL":
            return True
        if mode == "SELECTED":
            filter_enabled = True
        else:
            # Backward compatibility with settings saved by v5.3 and earlier.
            filter_enabled = bool(cfg.get("scanner_league_filter_enabled", True))
        if not filter_enabled:
            return True
        raw_ids = cfg.get("scanner_allowed_league_ids") or []
        try:
            allowed_ids = {int(value) for value in raw_ids}
        except (TypeError, ValueError):
            allowed_ids = set()
        league_id = (item.get("league") or {}).get("id")
        try:
            return int(league_id) in allowed_ids
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _health_score(result: dict[str, Any]) -> float:
        """Core pre-match data score; odds and line-up are bonuses, not blockers."""
        internal = result["internal"]
        context = internal.get("context") or {}
        hf, af = internal["home_features"], internal["away_features"]
        sample = min(1.0, (float(hf.get("matches") or 0) + float(af.get("matches") or 0)) / 20)
        reliability = min(1.0, float(internal.get("reliability") or 0) / 100)
        h2h_samples = min(1.0, float((internal.get("h2h_features") or {}).get("matches") or 0) / 5)
        score = sample * 45 + reliability * 30 + h2h_samples * 10
        score += 7.5 if result.get("odds_available") else 0
        score += 7.5 if context.get("lineups_available") else 0
        return round(min(100.0, score), 1)

    @staticmethod
    def _short_reasons(result: dict[str, Any], best: dict[str, Any]) -> list[str]:
        internal = result["internal"]
        hf, af = internal["home_features"], internal["away_features"]
        reasons: list[str] = []
        if hf["ppg"] > af["ppg"] + 0.20:
            reasons.append("Home form lebih baik")
        elif af["ppg"] > hf["ppg"] + 0.20:
            reasons.append("Away form lebih baik")
        else:
            reasons.append("Form kedua tim relatif seimbang")
        reasons.append(f"Model agreement {internal['model_agreement']:.1f}%")
        if (best.get("ev") or 0) >= 0.03:
            reasons.append("Odds masih value")
        elif best.get("odds"):
            reasons.append("Odds tersedia, value terbatas")
        else:
            reasons.append("Model pick; odds belum tersedia")
        return reasons[:3]

    @staticmethod
    def _combined_score(*, probability: float, confidence: float, pqi: float,
                        agreement: float, health: float, ev_pct: float) -> float:
        probability_score = min(100.0, max(0.0, probability))
        ev_score = min(100.0, max(0.0, 50 + ev_pct * 2.0))
        score = (
            probability_score * 0.20 + confidence * 0.22 + max(pqi, health) * 0.22
            + agreement * 0.20 + health * 0.10 + ev_score * 0.06
        )
        return round(min(100.0, max(0.0, score)), 1)

    async def _auto_settle(self, date_value: str, fixtures: list[dict[str, Any]]) -> dict[str, Any]:
        pending = self.store.pending_predictions_for_date(date_value)[: self.BATCH_SIZE]
        by_fixture = {int(item["fixture"]["id"]): item for item in fixtures}
        settled_count = 0
        for prediction in pending:
            fixture = by_fixture.get(int(prediction["fixture_id"]))
            if not fixture:
                try:
                    payload = await self.client.fixture_by_id(int(prediction["fixture_id"]))
                    fixture = payload.get("response", [None])[0] if payload.get("response") else None
                except Exception:
                    fixture = None
            if not fixture:
                continue
            status = str((fixture.get("fixture", {}).get("status") or {}).get("short") or "")
            home_goals, away_goals = fixture_score(fixture)
            if status in VOID_STATUSES:
                result = "VOID"
            elif status in FINAL_STATUSES and home_goals is not None and away_goals is not None:
                result = settle_market(str(prediction.get("market_key") or ""), home_goals, away_goals)
            else:
                continue
            try:
                self.store.settle_prediction_by_fixture(
                    int(prediction["fixture_id"]), str(prediction.get("market_key") or ""), result,
                    fixture_status=status, home_score=home_goals, away_score=away_goals,
                )
                settled_count += 1
            except Exception:
                continue

        history = self.store.predictions_for_date(date_value, source="SCANNER")
        completed = [row for row in history if row.get("result") in {"WIN", "LOSS", "VOID"}]
        wins = sum(row.get("result") == "WIN" for row in completed)
        losses = sum(row.get("result") == "LOSS" for row in completed)
        voids = sum(row.get("result") == "VOID" for row in completed)
        return {
            "settled_count": settled_count,
            "backtest_rows": completed,
            "backtest_summary": {
                "total": len(completed), "wins": wins, "losses": losses, "voids": voids,
                "hit_rate": round(wins / (wins + losses) * 100, 1) if wins + losses else 0.0,
                "profit": round(sum(float(row.get("profit") or 0) for row in completed), 2),
            },
        }

    async def _analyze_one(
        self, fixture: dict[str, Any], semaphore: asyncio.Semaphore, *, level: str,
        retries: int, timeout_seconds: int, delay_seconds: float,
    ) -> dict[str, Any] | Exception:
        async with semaphore:
            last_error: Exception | None = None
            for attempt in range(retries + 1):
                try:
                    return await asyncio.wait_for(
                        self.analysis.progressive(fixture, level=level), timeout=timeout_seconds
                    )
                except Exception as exc:
                    last_error = exc
                    if self.client.quota_is_exhausted():
                        break
                    if attempt < retries and delay_seconds > 0:
                        await asyncio.sleep(delay_seconds)
            return last_error or RuntimeError("Scanner analysis failed")

    async def preview(self, date_value: str) -> dict[str, Any]:
        cfg = self.store.settings()
        self._validate_league_configuration(cfg)
        if self.client.quota_is_exhausted():
            quota = self.client.quota_status()
            return {
                "rows": [], "best_picks": [], "safe_picks": [], "balanced_picks": [], "value_picks": [],
                "backtest_rows": [], "backtest_summary": {"total":0,"wins":0,"losses":0,"voids":0,"hit_rate":0.0,"profit":0.0},
                "settled_count": 0, "excluded_started": 0, "excluded_league": 0, "upcoming_count": 0, "total_upcoming": 0,
                "already_scanned": 0, "remaining": 0, "failed_count": 0,
                "scanner_settings": self.store.settings(), "preview_only": True,
                "quota_paused": True, "quota_status": quota,
            }
        groups, _ = await self.fixture_service.grouped_fixtures(date_value)
        all_fixtures = [x for group in groups for x in group["fixtures"]]
        upcoming_status = [item for item in all_fixtures if self._is_upcoming(item)]
        upcoming_all = [item for item in upcoming_status if self._league_is_allowed(item, cfg)]
        excluded_league = len(upcoming_status) - len(upcoming_all)
        stored = self.store.predictions_for_date(date_value, source="SCANNER")
        scanned_ids = {int(row["fixture_id"]) for row in stored if row.get("fixture_id") is not None}
        stored_by_fixture = self._latest_stored_by_fixture(stored)
        unscanned = [item for item in upcoming_all if int(item["fixture"]["id"]) not in scanned_ids]
        evidence_refresh_all = [
            item for item in upcoming_all
            if int(item["fixture"]["id"]) in stored_by_fixture
            and self._needs_evidence_refresh(stored_by_fixture[int(item["fixture"]["id"])])
        ]
        evidence_refresh = [
            item for item in evidence_refresh_all
            if self._evidence_refresh_due(stored_by_fixture[int(item["fixture"]["id"])])
        ]
        deferred_refresh = max(0, len(evidence_refresh_all) - len(evidence_refresh))
        # New fixtures are always processed first; existing incomplete snapshots
        # are refreshed with remaining batch capacity.
        scan_candidates = self._dedupe_fixtures(unscanned + evidence_refresh)
        limit = self.BATCH_SIZE
        return {
            "rows": [], "best_picks": [], "safe_picks": [], "balanced_picks": [], "value_picks": [],
            "backtest_rows": [], "backtest_summary": {"total":0,"wins":0,"losses":0,"voids":0,"hit_rate":0.0,"profit":0.0},
            "settled_count": 0, "excluded_started": len(all_fixtures) - len(upcoming_status),
            "excluded_league": excluded_league,
            "upcoming_count": min(limit, len(scan_candidates)), "total_upcoming": len(upcoming_all),
            "already_scanned": len(scanned_ids), "remaining": len(scan_candidates), "failed_count": 0,
            "deferred_refresh": deferred_refresh,
            "scanner_settings": cfg, "preview_only": True, "quota_paused": False, "quota_status": self.client.quota_status(),
        }

    async def scan(self, date_value: str, limit: int | None = None) -> dict[str, Any]:
        cfg = self.store.settings()
        self._validate_league_configuration(cfg)
        if self.client.quota_is_exhausted():
            quota = self.client.quota_status()
            return {
                "rows": [], "best_picks": [], "safe_picks": [], "balanced_picks": [], "value_picks": [],
                "backtest_rows": [], "backtest_summary": {"total":0,"wins":0,"losses":0,"voids":0,"hit_rate":0.0,"profit":0.0},
                "settled_count": 0, "excluded_started": 0, "excluded_league": 0, "upcoming_count": 0, "total_upcoming": 0,
                "already_scanned": 0, "remaining": 0, "failed_count": 0,
                "scanner_settings": self.store.settings(), "preview_only": False,
                "quota_paused": True, "quota_status": quota,
            }
        groups, _ = await self.fixture_service.grouped_fixtures(date_value)
        all_fixtures = [x for group in groups for x in group["fixtures"]]
        settlement = await self._auto_settle(date_value, all_fixtures)

        upcoming_status = [item for item in all_fixtures if self._is_upcoming(item)]
        upcoming_all = [item for item in upcoming_status if self._league_is_allowed(item, cfg)]
        excluded_league = len(upcoming_status) - len(upcoming_all)
        stored = self.store.predictions_for_date(date_value, source="SCANNER")
        scanned_ids = {int(row["fixture_id"]) for row in stored if row.get("fixture_id") is not None}
        stored_by_fixture = self._latest_stored_by_fixture(stored)
        unscanned = [item for item in upcoming_all if int(item["fixture"]["id"]) not in scanned_ids]
        evidence_refresh_all = [
            item for item in upcoming_all
            if int(item["fixture"]["id"]) in stored_by_fixture
            and self._needs_evidence_refresh(stored_by_fixture[int(item["fixture"]["id"])])
        ]
        evidence_refresh = [
            item for item in evidence_refresh_all
            if self._evidence_refresh_due(stored_by_fixture[int(item["fixture"]["id"])])
        ]
        deferred_refresh = max(0, len(evidence_refresh_all) - len(evidence_refresh))
        # New fixtures are always processed first; existing incomplete snapshots
        # are refreshed with remaining batch capacity.
        scan_candidates = self._dedupe_fixtures(unscanned + evidence_refresh)

        requested = self.BATCH_SIZE
        concurrency = max(1, min(int(cfg.get("scanner_concurrency", 2)), self.MAX_CONCURRENCY))
        retries = max(0, min(int(cfg.get("scanner_retry", 2)), 5))
        delay_seconds = max(0.0, min(float(cfg.get("scanner_delay_seconds", 0.5)), 10.0))
        timeout_seconds = max(15, min(int(cfg.get("scanner_timeout_seconds", 50)), self.FIXTURE_TIMEOUT_SECONDS))
        batch = scan_candidates[:requested]
        semaphore = asyncio.Semaphore(concurrency)
        usage_before = self.client.usage_snapshot()

        # Evidence Collector mode: each fixture in the controlled batch receives
        # the same complete evidence attempt. Batch remains capped at 10 and
        # quota protection is checked before starting the enrichment.
        estimated_requests = len(batch) * 10
        evidence_budget_ok = self.client.can_spend(estimated_requests, reserve=20)
        collection_level = "FINAL" if evidence_budget_ok else "CANDIDATE"
        results = list(await asyncio.gather(
            *(self._analyze_one(
                item, semaphore, level=collection_level, retries=retries,
                timeout_seconds=timeout_seconds, delay_seconds=delay_seconds,
            ) for item in batch)
        ))
        core_completed = sum(not isinstance(result, Exception) for result in results)
        candidate_completed = core_completed if collection_level in {"CANDIDATE", "FINAL"} else 0
        final_completed = core_completed if collection_level == "FINAL" else 0

        rows: list[dict[str, Any]] = []
        failed_count = 0

        for fixture_item, result in zip(batch, results):
            if isinstance(result, Exception):
                failed_count += 1
                continue
            fx = result["fixture"]
            recommendation = recommendation_from_analysis(result)
            best_market = best_market_from_analysis(result)
            best = recommendation or best_market
            quality = result["internal"]["quality"]
            fixture_id = int(fx["fixture"]["id"])
            current_odds = best.get("odds")
            previous_odds = self.store.latest_market_odds(fixture_id, best["key"])
            odds_change_pct = None
            if previous_odds and current_odds:
                odds_change_pct = round((current_odds - previous_odds) / previous_odds * 100, 1)

            health = self._health_score(result)
            agreement = float(result["internal"]["model_agreement"])
            ev_pct = round((best.get("ev") or 0) * 100, 1)
            confidence = float(result["internal"]["confidence"])
            probability = float(best["probability_pct"])
            combined = self._combined_score(
                probability=probability, confidence=confidence,
                pqi=float(quality["score"]), agreement=agreement,
                health=health, ev_pct=ev_pct,
            )
            warnings: list[dict[str, str]] = []
            if not result["internal"]["context"].get("lineups_available"):
                warnings.append({"icon": "bi-people", "text": "Line-up belum tersedia; pick masih provisional", "level": "warning"})
            if not result.get("injuries"):
                warnings.append({"icon": "bi-bandaid", "text": "Data cedera belum lengkap", "level": "muted"})
            if not result.get("odds_available"):
                warnings.append({"icon": "bi-graph-down", "text": "Odds belum tersedia; EV tidak dinilai", "level": "muted"})
            elif odds_change_pct is not None and abs(odds_change_pct) >= 8:
                direction = "naik" if odds_change_pct > 0 else "turun"
                warnings.append({"icon": "bi-exclamation-triangle", "text": f"Odds {direction} {abs(odds_change_pct):.1f}%", "level": "danger"})

            core_quality = max(float(quality["score"]), health)
            decision = result.get("decision_intelligence") or {}
            decision_status = str(
                (recommendation or {}).get("decision_tier")
                or (recommendation or {}).get("decision_status")
                or decision.get("decision_tier")
                or "NO_BET"
            ).upper()
            published = bool(recommendation)

            row = {
                "fixture_id": fixture_id,
                "league": fx["league"]["name"],
                "home": fx["teams"]["home"]["name"],
                "away": fx["teams"]["away"]["name"],
                "pick": (recommendation or best_market).get("label") or "NO MARKET",
                "market_key": (recommendation or {}).get("key") or best_market.get("key"),
                "best_market": best_market,
                "recommendation": recommendation,
                "probability": probability,
                "probability_raw": (
                    best.get("probability")
                    if best.get("probability") is not None
                    else float(best.get("probability_pct") or 0) / 100.0
                ),
                "odds": current_odds,
                "ev": ev_pct,
                "ev_raw": best.get("ev"),
                "confidence": confidence,
                "pqi": float(quality["score"]),
                "decision": decision_status,
                "builder": result.get("best_builder"),
                "builder_diagnostics": result.get("builder_diagnostics") or {},
                "model_agreement": agreement,
                "health_score": health,
                "combined_score": combined,
                "reasons": self._short_reasons(result, best),
                "warnings": warnings,
                "odds_change_pct": odds_change_pct,
                "fixture_status": (fx["fixture"].get("status") or {}).get("short"),
                "published": published,
                "final_tier": decision_status,
            }
            rows.append(row)

            try:
                self.store.save_prediction({
                    "fixture_id": fixture_id, "league": row["league"], "home_team": row["home"],
                    "away_team": row["away"], "pick": row["pick"], "market_key": row["market_key"],
                    "pick_role": decision_status, "confidence": row["confidence"],
                    "settlement_eligible": published,
                    "probability": row["probability_raw"], "odds": row["odds"], "ev": row["ev_raw"],
                    "pqi": row["pqi"], "fixture_date": date_value,
                    "fixture_status": row["fixture_status"], "source": "SCANNER",
                    "combined_score": row["combined_score"], "model_agreement": row["model_agreement"],
                    "health_score": row["health_score"], "decision_status": decision_status,
                    "best_builder": result.get("best_builder"),
                    "builder_diagnostics": result.get("builder_diagnostics") or {},
                    "analysis": result,
                })
                self.store.save_odds_snapshot(fixture_id, result.get("markets") or [])
            except Exception as exc:
                row["warnings"].append({"icon": "bi-database-exclamation", "text": f"Gagal menyimpan snapshot: {exc.__class__.__name__}", "level": "danger"})

        # Include all already stored rows on Today Picks; scanner page shows only this safe batch.
        rows.sort(key=lambda r: ({"ELITE_PICK":5,"STRONG_PICK":4,"PICK":3,"MONITOR":2,"NO_BET":1}.get(r["decision"],0), r["combined_score"]), reverse=True)
        for index, row in enumerate(rows, start=1):
            row["rank"] = index

        already_scanned = len(scanned_ids)
        remaining = max(0, len(scan_candidates) - len(batch))
        usage_after = self.client.usage_snapshot()
        api_usage_delta = {
            "network_requests": max(0, int(usage_after.get("network_requests", 0)) - int(usage_before.get("network_requests", 0))),
            "cache_hits": max(0, int(usage_after.get("cache_hits", 0)) - int(usage_before.get("cache_hits", 0))),
            "cache_misses": max(0, int(usage_after.get("cache_misses", 0)) - int(usage_before.get("cache_misses", 0))),
        }
        lookups = api_usage_delta["cache_hits"] + api_usage_delta["cache_misses"]
        api_usage_delta["cache_hit_rate"] = round(api_usage_delta["cache_hits"] / lookups * 100, 1) if lookups else 0.0
        return {
            "rows": rows,
            "best_picks": [r for r in rows if r.get("published")][:3],
            "safe_picks": [],
            "balanced_picks": [],
            "value_picks": [],
            "excluded_started": len(all_fixtures) - len(upcoming_status),
            "excluded_league": excluded_league,
            "upcoming_count": len(batch),
            "total_upcoming": len(upcoming_all),
            "already_scanned": already_scanned,
            "remaining": remaining,
            "deferred_refresh": deferred_refresh,
            "failed_count": failed_count,
            "scanner_settings": cfg,
            "preview_only": False,
            "quota_paused": self.client.quota_is_exhausted(),
            "quota_status": self.client.quota_status(),
            "api_usage_before": usage_before,
            "api_usage": api_usage_delta,
            "api_usage_total": usage_after,
            "progressive_summary": {
                "core": core_completed,
                "candidate": candidate_completed,
                "final": final_completed,
                "candidate_limit": 3,
                "final_limit": len(batch),
                "collector_mode": collection_level,
                "evidence_budget_ok": evidence_budget_ok,
                "estimated_requests": estimated_requests,
            },
            **settlement,
        }
