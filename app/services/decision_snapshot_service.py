from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

CANONICAL_TIERS = ("ELITE_PICK", "STRONG_PICK", "PICK", "MONITOR", "NO_BET")
PUBLIC_TIERS = {"ELITE_PICK", "STRONG_PICK", "PICK"}
LEGACY_STATUSES = {
    "SELECTED_VALUE", "SELECTED_MODEL", "SAFE", "VALUE", "QUALIFIED",
    "WATCH", "MODEL_PICK", "VALUE_PICK", "WATCH_ONLY", "NO_PICK",
}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _probability(value: Any, pct: Any = None) -> tuple[float | None, float | None]:
    p = _float(value)
    pp = _float(pct)
    if p is None and pp is not None:
        p = pp / 100.0
    if pp is None and p is not None:
        pp = p * 100.0 if p <= 1 else p
        if p > 1:
            p = p / 100.0
    return p, pp


def canonical_tier(value: Any) -> str:
    tier = str(value or "NO_BET").upper().strip().replace(" ", "_")
    if tier in CANONICAL_TIERS:
        return tier
    # Legacy labels are not recommendations. They are deliberately downgraded
    # until the fixture is recomputed by the single Decision Engine.
    if tier in LEGACY_STATUSES:
        return "NO_BET"
    return "NO_BET"


class DecisionSnapshotService:
    """Build the only persisted decision contract consumed by all read pages."""

    version = "13.0-s1"

    def from_analysis(self, analysis: dict[str, Any], *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        metadata = metadata or {}
        decision = _dict(analysis.get("decision_intelligence"))
        recommendation = _dict(analysis.get("recommendation"))
        selected = _dict(analysis.get("selected_pick") or analysis.get("best_pick"))
        best_market = _dict(analysis.get("best_market"))
        builder = _dict(analysis.get("best_builder"))
        builder_portfolio = analysis.get("builder_portfolio") if isinstance(analysis.get("builder_portfolio"), list) else []

        tier = canonical_tier(
            recommendation.get("decision_tier")
            or selected.get("decision_tier")
            or decision.get("decision_tier")
            or recommendation.get("decision_status")
            or selected.get("decision_status")
        )
        published = tier in PUBLIC_TIERS and bool(recommendation or selected.get("published"))
        if not published and tier in PUBLIC_TIERS:
            # A canonical public tier is authoritative even if an older payload
            # omitted the published flag.
            published = True

        public_pick = recommendation if published else {}
        if not public_pick and published:
            public_pick = selected
        analytical_market = best_market or selected or public_pick

        rec_probability, rec_probability_pct = _probability(
            public_pick.get("probability"), public_pick.get("probability_pct")
        )
        best_probability, best_probability_pct = _probability(
            analytical_market.get("probability"), analytical_market.get("probability_pct")
        )

        fixture = _dict(analysis.get("fixture"))
        fixture_info = _dict(fixture.get("fixture"))
        teams = _dict(fixture.get("teams"))
        home = _dict(teams.get("home"))
        away = _dict(teams.get("away"))
        league = _dict(fixture.get("league"))
        internal = _dict(analysis.get("internal"))
        dq = _dict(analysis.get("data_quality"))

        builder_available = bool(builder and builder.get("selections")) and published
        if not builder_available:
            builder = {}

        return {
            "fixture_id": int(metadata.get("fixture_id") or fixture_info.get("id") or 0),
            "business_date": str(metadata.get("business_date") or metadata.get("fixture_date") or fixture_info.get("date") or "")[:10],
            "fixture_date": metadata.get("fixture_date") or fixture_info.get("date"),
            "fixture_status": metadata.get("fixture_status") or _dict(fixture_info.get("status")).get("short"),
            "league": metadata.get("league") or league.get("name"),
            "home_team": metadata.get("home_team") or home.get("name"),
            "away_team": metadata.get("away_team") or away.get("name"),
            "final_tier": tier,
            "final_label": str(decision.get("decision_label") or selected.get("decision_label") or tier).replace("_", " "),
            "published": published,
            "best_market_key": analytical_market.get("key"),
            "best_market_label": analytical_market.get("label") or "NO MARKET",
            "best_market_probability": best_probability,
            "best_market_probability_pct": best_probability_pct,
            "recommendation_key": public_pick.get("key") if published else None,
            "recommendation_label": public_pick.get("label") if published else None,
            "recommendation_probability": rec_probability if published else None,
            "recommendation_probability_pct": rec_probability_pct if published else None,
            "confidence": _float(internal.get("confidence") or public_pick.get("confidence") or metadata.get("confidence")),
            "model_agreement": _float(internal.get("model_agreement") or metadata.get("model_agreement")),
            "data_quality": _float(decision.get("data_quality") or dq.get("score") or metadata.get("pqi")) or 0.0,
            "reliability_grade": str(decision.get("reliability_grade") or "D"),
            "reliability_score": _float(decision.get("reliability_score")) or 0.0,
            "evidence_strength": _float(decision.get("evidence_strength")) or 0.0,
            "risk_level": str(decision.get("risk_level") or public_pick.get("risk_level") or "AVOID"),
            "value_status": str(public_pick.get("value_status") or analytical_market.get("value_status") or "UNAVAILABLE"),
            "recommendation_basis": str(public_pick.get("recommendation_basis") or analytical_market.get("recommendation_basis") or "MODEL_ONLY"),
            "decision_reason": str((public_pick.get("decision_reasons") or decision.get("reasons") or [""])[-1]),
            "odds": _float(public_pick.get("odds") if published else analytical_market.get("odds")),
            "ev": _float(public_pick.get("ev") if published else None),
            "builder_available": builder_available,
            "builder_status": str(decision.get("builder_status") or ("AVAILABLE" if builder_available else "NO_QUALIFIED_BUILDER")),
            "builder": builder,
            "builder_portfolio": builder_portfolio if published else [],
            "decision": decision,
            "analysis": analysis,
            "source_prediction_id": metadata.get("source_prediction_id"),
            "source": metadata.get("source") or "UNKNOWN",
            "engine_version": self.version,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def from_prediction_row(self, row: dict[str, Any]) -> dict[str, Any] | None:
        try:
            payload = json.loads(row.get("payload") or "{}")
        except (TypeError, ValueError):
            payload = {}
        analysis = _dict(payload.get("analysis") or payload)
        if not analysis:
            return None
        return self.from_analysis(
            analysis,
            metadata={
                "fixture_id": row.get("fixture_id"), "fixture_date": row.get("fixture_date"),
                "fixture_status": row.get("fixture_status"), "league": row.get("league"),
                "home_team": row.get("home_team"), "away_team": row.get("away_team"),
                "confidence": row.get("confidence"), "pqi": row.get("pqi"),
                "source_prediction_id": row.get("id"), "source": row.get("source"),
            },
        )
