from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any


class FixtureRecoveryEngine:
    """Relink stale fixture IDs using date, league and tolerant team matching."""

    def __init__(self, client: Any, store: Any) -> None:
        self.client = client
        self.store = store

    @staticmethod
    def _normalize(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
        text = re.sub(r"\b(fc|cf|sc|afc|fk|bk|women|woman|w|u\d{2}|ii|reserves?)\b", " ", text)
        return re.sub(r"[^a-z0-9]+", " ", text).strip()

    @classmethod
    def similarity(cls, left: Any, right: Any) -> float:
        a, b = cls._normalize(left), cls._normalize(right)
        if not a or not b:
            return 0.0
        return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()

    @staticmethod
    def fixture_id(fixture: dict[str, Any]) -> int | None:
        try:
            return int((fixture.get("fixture") or {}).get("id"))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def fixture_day(row: dict[str, Any]) -> date | None:
        try:
            return date.fromisoformat(str(row.get("fixture_date") or "")[:10])
        except ValueError:
            return None

    def score(self, row: dict[str, Any], candidate: dict[str, Any]) -> float:
        teams = candidate.get("teams") or {}
        home = self.similarity(row.get("home_team"), (teams.get("home") or {}).get("name"))
        away = self.similarity(row.get("away_team"), (teams.get("away") or {}).get("name"))
        if min(home, away) < 0.70:
            return 0.0
        league = candidate.get("league") or {}
        league_score = self.similarity(row.get("league"), league.get("name")) if row.get("league") else 0.5
        if row.get("league_id") and str(row.get("league_id")) == str(league.get("id")):
            league_score = 1.0
        return home * 0.43 + away * 0.43 + league_score * 0.14

    async def recover(self, row: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        day = self.fixture_day(row)
        if day is None:
            return None, "INVALID_FIXTURE_DATE"
        best: dict[str, Any] | None = None
        best_score = 0.0
        for offset in (0, -1, 1, -2, 2):
            payload = await self.client.fixtures_by_date((day + timedelta(days=offset)).isoformat())
            for candidate in payload.get("response") or []:
                if not self.fixture_id(candidate):
                    continue
                score = self.score(row, candidate)
                if score > best_score:
                    best, best_score = candidate, score
            if best_score >= 0.94:
                break
        if best is None or best_score < 0.82:
            return None, f"FIXTURE_NOT_FOUND similarity={best_score:.2f}"
        teams = best.get("teams") or {}
        return best, (
            f"FIXTURE_RELINKED similarity={best_score:.2f} "
            f"{(teams.get('home') or {}).get('name')} vs {(teams.get('away') or {}).get('name')}"
        )
