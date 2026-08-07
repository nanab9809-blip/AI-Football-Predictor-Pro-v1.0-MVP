from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.validation.settlement import FINAL_STATUSES, VOID_STATUSES, fixture_score, normalize_market_key, settle_market


@dataclass(frozen=True)
class Resolution:
    final: bool
    status: str
    result: str | None
    home_score: int | None
    away_score: int | None
    reason: str


class ResultResolver:
    """One authoritative mapping of API fixture status and prediction result."""

    FINAL = set(FINAL_STATUSES) | {"AWD", "WO"}
    VOID = set(VOID_STATUSES) | {"CANCELLED", "ABANDONED"}

    @staticmethod
    def status(fixture: dict[str, Any] | None) -> str:
        if not fixture:
            return "NOT_FOUND"
        return str(((fixture.get("fixture") or {}).get("status") or {}).get("short") or "UNKNOWN").upper()

    def resolve(self, prediction: dict[str, Any], fixture: dict[str, Any] | None) -> Resolution:
        status = self.status(fixture)
        if status in self.VOID:
            return Resolution(True, status, "VOID", None, None, f"Fixture status {status} dipetakan ke VOID")
        if status not in self.FINAL:
            return Resolution(False, status, None, None, None, f"Fixture belum final ({status})")
        home, away = fixture_score(fixture or {})
        if status in {"AWD", "WO"} and (home is None or away is None):
            return Resolution(True, status, "VOID", home, away, "Awarded/walkover tanpa skor resmi")
        if home is None or away is None:
            return Resolution(False, status, None, home, away, "Status final tanpa skor resmi")
        raw_market = prediction.get("market_key") or prediction.get("pick") or ""
        market_key = normalize_market_key(str(raw_market))
        result = settle_market(market_key, home, away)
        if result is None:
            return Resolution(
                True, status, None, home, away,
                f"Market tidak didukung untuk settlement: {raw_market or 'EMPTY'}",
            )
        return Resolution(True, status, result, home, away, f"Market {market_key} berhasil dievaluasi")
