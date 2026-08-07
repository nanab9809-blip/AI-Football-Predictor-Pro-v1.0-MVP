from __future__ import annotations

from typing import Any

from app.learning.weights import adaptive_weights
from app.prediction.ensemble import api_probabilities, blend, elo_probabilities, form_probabilities
from app.prediction.features import context_features, h2h_features, team_features
from app.prediction.poisson import build_markets, likely_scores
from app.prediction.quality import confidence, quality_index


def _normalize_1x2(markets: dict[str, float]) -> dict[str, float]:
    total = sum(markets.get(k, 0) for k in ("HOME_WIN","DRAW","AWAY_WIN")) or 1
    return {k: markets.get(k,0)/total for k in ("HOME_WIN","DRAW","AWAY_WIN")}


def analyze_professional(*, home_id: int, away_id: int, home_recent: list[dict[str, Any]], away_recent: list[dict[str, Any]],
                         h2h: list[dict[str, Any]], injuries: list[dict[str, Any]], lineups: list[dict[str, Any]],
                         api_prediction: dict[str, Any], history: list[dict[str, Any]], league: str) -> dict[str, Any]:
    hf = team_features(home_recent, home_id).to_dict(); af = team_features(away_recent, away_id).to_dict()
    hh = h2h_features(h2h, home_id, away_id); context = context_features(injuries, lineups, home_id, away_id)
    home_xg = max(.2, .52*hf["goals_for"] + .32*af["goals_against"] + .20 + (hf["attack_rating"]-af["defense_rating"])/180)
    away_xg = max(.15, .52*af["goals_for"] + .32*hf["goals_against"] - .02 + (af["attack_rating"]-hf["defense_rating"])/180)
    home_xg -= context["home_injuries"]*.025; away_xg -= context["away_injuries"]*.025
    home_xg = max(.15, min(4.5, home_xg)); away_xg = max(.15, min(4.5, away_xg))
    poisson_markets = build_markets(home_xg, away_xg)
    home_elo = 1500 + (hf["ppg"]-1.4)*115 + (hf["goal_difference"])*35 + 55
    away_elo = 1500 + (af["ppg"]-1.4)*115 + (af["goal_difference"])*35
    models = {
        "poisson": _normalize_1x2(poisson_markets),
        "elo": elo_probabilities(home_elo, away_elo),
        "form": form_probabilities(hf, af),
        "api": api_probabilities(api_prediction),
    }
    weights = adaptive_weights(history, league)
    final_1x2, agreement = blend(models, weights)
    markets = dict(poisson_markets); markets.update(final_1x2)
    sample_strength = min(1.0, (hf["matches"]+af["matches"])/20)
    completeness_items = [hf["matches"] >= 5, af["matches"] >= 5, hh["matches"] >= 3, bool(api_prediction), bool(injuries), bool(lineups)]
    completeness = sum(completeness_items)/len(completeness_items)
    quality = quality_index(data_completeness=completeness, model_agreement=agreement, sample_strength=sample_strength,
                            odds_available=False, lineups_available=context["lineups_available"], historical_accuracy=.55,
                            volatility=abs(final_1x2["HOME_WIN"]-final_1x2["AWAY_WIN"])*.15)
    top = max(final_1x2.values())
    return {
        "home_features": hf, "away_features": af, "h2h_features": hh, "context": context,
        "home_xg": round(home_xg,2), "away_xg": round(away_xg,2), "home_elo": round(home_elo), "away_elo": round(away_elo),
        "markets": {k: round(v,4) for k,v in markets.items()}, "likely_scores": likely_scores(home_xg, away_xg),
        "models": models, "weights": weights, "model_agreement": round(agreement*100,1), "quality": quality,
        "confidence": confidence(top_probability=top, model_agreement=agreement, quality_score=quality["score"], edge=None),
        "reliability": round(sample_strength*100,1),
    }
