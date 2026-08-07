from __future__ import annotations

import asyncio
from typing import Any, Literal

from app.analytics.odds import enrich, extract
from app.analytics.pro_odds import enrich_professional
from app.bet_builder.engine import generate, select_best_builder, select_builder_portfolio
from app.clients.api_football import ApiFootballClient, ApiFootballError
from app.database.store import Store
from app.prediction.quality import confidence, quality_index
from app.services.professional_engine import analyze_professional
from app.intelligence.monte_carlo import simulate
from app.intelligence.data_quality import assess as assess_data_quality
from app.intelligence.confidence import dynamic as dynamic_confidence
from app.intelligence.audit import build as build_audit
from app.intelligence.decision_engine import build_team_comparison, market_suitability, select_decision
from app.intelligence.market_intelligence import rank_markets as rank_market_intelligence
from app.intelligence.match_story import build_match_story
from app.intelligence.decision_intelligence import build as build_decision_intelligence
from app.intelligence.quality_controller import finalize_decision
from app.contracts.decision import AnalysisDecisionContract
from app.intelligence.evidence import build_evidence_collection

EnrichmentLevel = Literal["CORE", "CANDIDATE", "FINAL"]


class AnalysisService:
    """Builds one authoritative decision with progressive API enrichment.

    CORE is intentionally cheap and is used for every fixture in a scanner batch.
    CANDIDATE is used only for the strongest few fixtures. FINAL adds odds,
    injuries, and line-ups only for the best one or two candidates.
    """

    def __init__(self, client: ApiFootballClient, store: Store) -> None:
        self.client = client
        self.store = store

    async def full(self, fixture_id: int) -> dict[str, Any]:
        fixture_payload = await self.client.fixture_by_id(fixture_id)
        if not fixture_payload.get("response"):
            raise ApiFootballError("Pertandingan tidak ditemukan.")
        return await self.progressive(fixture_payload["response"][0], level="FINAL")

    async def progressive(self, fixture: dict[str, Any], *, level: EnrichmentLevel = "CORE") -> dict[str, Any]:
        level = str(level or "CORE").upper()  # type: ignore[assignment]
        if level not in {"CORE", "CANDIDATE", "FINAL"}:
            level = "CORE"

        fixture_id = int(fixture["fixture"]["id"])
        home_id = int(fixture["teams"]["home"]["id"])
        away_id = int(fixture["teams"]["away"]["id"])
        league_id = int(fixture["league"]["id"])
        season = int(fixture["league"]["season"])
        league_name = str(fixture["league"]["name"])

        # Stage 1: every fixture. Three network requests at most; fixture data is
        # already supplied by the date endpoint and is not fetched again.
        api_pred_p, home_recent_p, away_recent_p = await asyncio.gather(
            self.client.prediction_by_fixture(fixture_id),
            self.client.recent_fixtures(home_id, 10),
            self.client.recent_fixtures(away_id, 10),
        )

        h2h_p: dict[str, Any] = {"response": []}
        standings_p: dict[str, Any] = {"response": []}
        home_stats_p: dict[str, Any] = {"response": {}}
        away_stats_p: dict[str, Any] = {"response": {}}
        injuries_p: dict[str, Any] = {"response": []}
        lineups_p: dict[str, Any] = {"response": []}
        odds_p: dict[str, Any] = {"response": []}

        # Stage 2: only shortlisted candidates. Cached core data is reused.
        if level in {"CANDIDATE", "FINAL"} and not self.client.quota_is_exhausted():
            h2h_p, standings_p, home_stats_p, away_stats_p = await asyncio.gather(
                self.client.head_to_head(home_id, away_id, 10),
                self.client.standings(league_id, season),
                self.client.team_statistics(league_id, season, home_id),
                self.client.team_statistics(league_id, season, away_id),
            )

        # Stage 3: only the final one or two candidates.
        if level == "FINAL" and not self.client.quota_is_exhausted():
            injuries_p, lineups_p, odds_p = await asyncio.gather(
                self.client.injuries(fixture_id),
                self.client.lineups(fixture_id),
                self.client.odds(fixture_id),
            )

        api_prediction = api_pred_p.get("response", [{}])[0] if api_pred_p.get("response") else {}
        h2h = h2h_p.get("response", [])
        injuries = injuries_p.get("response", [])
        lineups = lineups_p.get("response", [])
        internal = analyze_professional(
            home_id=home_id,
            away_id=away_id,
            home_recent=home_recent_p.get("response", []),
            away_recent=away_recent_p.get("response", []),
            h2h=h2h,
            injuries=injuries,
            lineups=lineups,
            api_prediction=api_prediction,
            history=self.store.recent_predictions(1000),
            league=league_name,
        )

        odds_map = extract(odds_p)
        market_rows = enrich_professional(enrich(internal["markets"], odds_map))
        best_edge = max((m.get("edge") or -1 for m in market_rows), default=None)
        historical_accuracy = self.store.historical_accuracy(league_name)
        quality = quality_index(
            data_completeness=min(1.0, (internal["home_features"]["matches"] + internal["away_features"]["matches"]) / 20),
            model_agreement=internal["model_agreement"] / 100,
            sample_strength=internal["reliability"] / 100,
            odds_available=bool(odds_map),
            lineups_available=internal["context"]["lineups_available"],
            historical_accuracy=historical_accuracy,
            volatility=.20,
        )
        internal["quality"] = quality
        internal["confidence"] = confidence(
            top_probability=max(internal["markets"][k] for k in ("HOME_WIN", "DRAW", "AWAY_WIN")),
            model_agreement=internal["model_agreement"] / 100,
            quality_score=quality["score"],
            edge=best_edge,
        )
        monte_carlo = simulate(internal["home_xg"], internal["away_xg"], 10000 if level == "CORE" else 20000, fixture_id)
        evidence_collection = build_evidence_collection(
            fixture=fixture, level=level, api_prediction=api_prediction,
            home_recent_payload=home_recent_p, away_recent_payload=away_recent_p,
            home_stats_payload=home_stats_p, away_stats_payload=away_stats_p,
            standings_payload=standings_p, h2h_payload=h2h_p, odds_payload=odds_p,
            injuries_payload=injuries_p, lineups_payload=lineups_p,
        )
        preliminary = {
            "fixture": fixture,
            "internal": internal,
            "home_statistics": home_stats_p.get("response", {}),
            "away_statistics": away_stats_p.get("response", {}),
            "standings": standings_p.get("response", []),
            "h2h": h2h,
            "injuries": injuries,
            "lineups": lineups,
            "odds_available": bool(odds_map),
            "enrichment_level": level,
            "evidence_collection": evidence_collection,
            "data_timestamps": {
                key: value.get("checked_at")
                for key, value in (evidence_collection.get("items") or {}).items()
                if value.get("attempted")
            },
        }
        data_quality = assess_data_quality(preliminary)
        dyn_conf = dynamic_confidence(
            internal["confidence"],
            data_quality=data_quality["score"],
            agreement=internal["model_agreement"],
            odds_available=bool(odds_map),
            lineups_available=internal["context"]["lineups_available"],
            drift_points=0,
        )
        internal["dynamic_confidence"] = dyn_conf
        internal["confidence"] = dyn_conf["final"]

        comparison = build_team_comparison(
            home_name=fixture["teams"]["home"]["name"],
            away_name=fixture["teams"]["away"]["name"],
            home_features=internal["home_features"],
            away_features=internal["away_features"],
            home_statistics=home_stats_p.get("response", {}),
            away_statistics=away_stats_p.get("response", {}),
            h2h_features=internal["h2h_features"],
            context=internal["context"],
            home_xg=internal["home_xg"],
            away_xg=internal["away_xg"],
            model_agreement=float(internal["model_agreement"]),
            data_quality=float(data_quality["score"]),
            league_reliability=float(historical_accuracy * 100),
        )
        suitability_markets = market_suitability(
            market_rows,
            comparison=comparison,
            h2h_features=internal["h2h_features"],
            home_features=internal["home_features"],
            away_features=internal["away_features"],
            home_xg=internal["home_xg"],
            away_xg=internal["away_xg"],
        )
        business_date = str((fixture.get("fixture") or {}).get("date") or "")[:10]
        market_performance = self.store.market_performance_snapshot()
        daily_market_counts = self.store.decision_market_counts_for_date(business_date) if business_date else {}
        calibration_by_market = self.store.market_calibration_snapshot({
            str(m.get("key") or ""): float(m.get("probability") or 0) for m in suitability_markets
            if m.get("key") and m.get("probability") is not None
        })
        ranked_markets = rank_market_intelligence(
            suitability_markets,
            data_quality=float(data_quality["score"]),
            evidence_strength=float(comparison["evidence_score"]),
            performance_by_market=market_performance,
            calibration_by_market=calibration_by_market,
            daily_counts=daily_market_counts,
        )
        decision_intelligence = build_decision_intelligence(
            data_quality=data_quality,
            evidence_score=float(comparison["evidence_score"]),
            model_agreement=float(internal["model_agreement"]),
            confidence=float(internal["confidence"]),
            odds_available=bool(odds_map),
            lineup_available=bool(internal["context"].get("lineups_available")),
        )
        # Best Market is an analytical ranking and always remains visible.
        # Recommendation is the public decision after all quality/reliability gates.
        best_market = select_decision(
            ranked_markets,
            comparison=comparison,
            data_quality=float(data_quality["score"]),
            model_agreement=float(internal["model_agreement"]),
            confidence=float(internal["confidence"]),
            odds_available=bool(odds_map),
            reliability_grade=str(decision_intelligence.get("reliability_grade") or "D"),
        )
        recommendation_allowed = bool(
            decision_intelligence.get("selected_pick_allowed") and best_market.get("published")
        )
        if recommendation_allowed:
            selected_pick = dict(best_market)
        else:
            blocked_reasons = list(best_market.get("decision_reasons") or [])
            blocked_reasons.extend(decision_intelligence.get("reasons") or [])
            selected_pick = {
                "status": "NO_PICK", "decision_status": "NO_BET",
                "decision_tier": "NO_BET", "decision_label": "NO BET",
                "risk_level": "AVOID", "published": False,
                "label": "NO BET", "key": "NO_BET", "probability_pct": 0,
                "decision_score": float(best_market.get("decision_score") or 0),
                "evidence_score": comparison["evidence_score"],
                "market_suitability": float(best_market.get("market_suitability") or 0),
                "value_verified": False,
                "decision_reasons": list(dict.fromkeys(blocked_reasons)),
                "best_market_key": best_market.get("key"),
                "best_market_label": best_market.get("label"),
            }

        # The data gate only permits evaluation. Public builder/EV access is
        # finalized by the selected market tier from the Decision Ladder.
        decision_intelligence["selected_pick_allowed"] = bool(selected_pick.get("published"))
        decision_intelligence["builder_allowed"] = bool(
            decision_intelligence.get("builder_allowed") and selected_pick.get("published")
        )
        decision_intelligence["ev_allowed"] = bool(
            decision_intelligence.get("ev_allowed") and selected_pick.get("published")
        )

        match_story = build_match_story(
            comparison=comparison,
            selected_pick=best_market,
            home_features=internal["home_features"],
            away_features=internal["away_features"],
            h2h_features=internal["h2h_features"],
            home_xg=internal["home_xg"],
            away_xg=internal["away_xg"],
        )
        # Compatibility: best_pick remains the public recommendation used by scanner/storage.
        best_pick = selected_pick
        recommendation = selected_pick if selected_pick.get("published") else None
        model_pick = recommendation if recommendation and not recommendation.get("value_verified") else None
        value_pick = recommendation if recommendation and recommendation.get("value_verified") else None
        # Builder consumes the same calibrated/ranked market rows as Best Market.
        # This prevents Recommendation and Builder from using different probabilities.
        builders = generate(
            ranked_markets,
            data_quality=float(data_quality["score"]),
            model_agreement=float(internal["model_agreement"]),
            selected_pick_key=str((recommendation or {}).get("key") or ""),
            evidence_score=float(comparison["evidence_score"]),
        )
        builder_portfolio = select_builder_portfolio(
            builders,
            data_quality=float(data_quality["score"]),
            model_agreement=float(internal["model_agreement"]),
            selected_pick_key=str((recommendation or {}).get("key") or ""),
            evidence_score=float(comparison["evidence_score"]),
        )
        best_builder = builder_portfolio[0] if builder_portfolio else None
        if not decision_intelligence["builder_allowed"]:
            best_builder = None
            builder_portfolio = []
        elif best_builder is not None:
            best_builder["decision_eligibility"] = decision_intelligence["decision_eligibility"]
            best_builder["reliability_grade"] = decision_intelligence["reliability_grade"]

        builder_diagnostics = dict(builders.get("_diagnostics") or {})
        decision_intelligence = finalize_decision(
            decision_intelligence=decision_intelligence,
            selected_pick=selected_pick,
            best_builder=best_builder,
            builder_diagnostics=builder_diagnostics,
        )
        if not decision_intelligence["builder_available"]:
            best_builder = None
        reasons = self._reasons(fixture, internal, best_market, market_rows)
        reasons.extend(selected_pick.get("decision_reasons") or [])
        preliminary.update({"best_pick": best_pick, "team_comparison": comparison})
        audit = build_audit(preliminary, data_quality, dyn_conf, monte_carlo)

        self.store.save_decision_intelligence_trace(
            fixture_id=fixture_id, business_date=business_date, ranked_markets=ranked_markets,
            final_market=best_market, final_tier=str(selected_pick.get("decision_tier") or "NO_BET"),
            engine_version="14.0",
        )

        response = {
            "fixture": fixture,
            "api_prediction": api_prediction,
            "internal": internal,
            "markets": market_rows,
            "ranked_markets": ranked_markets,
            "market_intelligence": {
                "weights": {"probability":20,"expected_value":20,"historical_roi":12,"market_reliability":12,"calibration":10,"relationship":6,"evidence":10,"data_quality":6,"diversity":4},
                "calibration_markets": len(calibration_by_market),
                "performance_markets": len(market_performance),
                "daily_distribution": daily_market_counts,
            },
            "builders": builders,
            "builder_diagnostics": builder_diagnostics,
            "best_builder": best_builder,
            "builder_portfolio": builder_portfolio,
            "best_market": best_market,
            "recommendation": recommendation,
            "best_pick": best_pick,
            "selected_pick": selected_pick,
            "model_pick": model_pick,
            "value_pick": value_pick,
            "safe_pick": None,
            "team_comparison": comparison,
            "match_story": match_story,
            "h2h": h2h,
            "standings": standings_p.get("response", []),
            "injuries": injuries,
            "lineups": lineups,
            "home_statistics": home_stats_p.get("response", {}),
            "away_statistics": away_stats_p.get("response", {}),
            "odds_available": bool(odds_map),
            "reasons": reasons,
            "quota": self.client.quota_status(),
            "monte_carlo": monte_carlo,
            "data_quality": data_quality,
            "decision_intelligence": decision_intelligence,
            "prediction_audit": audit,
            "enrichment_level": level,
            "evidence_collection": evidence_collection,
        }
        response["decision_contract"] = AnalysisDecisionContract.from_analysis(response).model_dump()
        return response

    @staticmethod
    def decision_rank(result: dict[str, Any]) -> float:
        selected = result.get("selected_pick") or result.get("best_pick") or {}
        comparison = result.get("team_comparison") or {}
        internal = result.get("internal") or {}
        return round(
            float(selected.get("decision_score") or selected.get("suitability_score") or selected.get("probability_pct") or 0) * 0.55
            + float(comparison.get("evidence_score") or 0) * 0.25
            + float(internal.get("model_agreement") or 0) * 0.20,
            3,
        )

    @staticmethod
    def _reasons(fixture: dict[str, Any], internal: dict[str, Any], pick: dict[str, Any], markets: list[dict[str, Any]]) -> list[str]:
        hf, af = internal["home_features"], internal["away_features"]
        q = internal["quality"]
        probability = float(pick.get("probability_pct") or 0)
        label = str(pick.get("label") or "Model Pick")
        reasons = [
            f"Ensemble memberi probabilitas {probability:.1f}% untuk {label}.",
            f"Prediction Quality Index {q['score']}/100 (Grade {q['grade']}) dengan keputusan {q['decision'].replace('_', ' ')}.",
            f"Kesepakatan antar-model {internal['model_agreement']}%; bobot aktif: "
            + ", ".join(f"{k} {v * 100:.0f}%" for k, v in internal["weights"].items()),
        ]
        if hf["ppg"] > af["ppg"] + .25:
            reasons.append(f"Form kandang lebih kuat: {hf['ppg']:.2f} poin/laga vs {af['ppg']:.2f}.")
        elif af["ppg"] > hf["ppg"] + .25:
            reasons.append(f"Form tandang lebih kuat: {af['ppg']:.2f} poin/laga vs {hf['ppg']:.2f}.")
        reasons.append(
            f"Attack/defense rating: kandang {hf['attack_rating']:.0f}/{hf['defense_rating']:.0f}, "
            f"tandang {af['attack_rating']:.0f}/{af['defense_rating']:.0f}."
        )
        reasons.append(
            f"Expected goals: {fixture['teams']['home']['name']} {internal['home_xg']} – "
            f"{internal['away_xg']} {fixture['teams']['away']['name']}."
        )
        return reasons
