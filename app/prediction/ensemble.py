from __future__ import annotations

import math
from typing import Any


def _softmax(values: list[float]) -> list[float]:
    exps = [math.exp(max(-20, min(20, v))) for v in values]
    total = sum(exps) or 1.0
    return [v / total for v in exps]


def elo_probabilities(home_rating: float, away_rating: float) -> dict[str, float]:
    expected = 1 / (1 + 10 ** ((away_rating - home_rating) / 400))
    draw = max(.16, min(.31, .29 - abs(expected-.5)*.24))
    return {"HOME_WIN": expected*(1-draw), "DRAW": draw, "AWAY_WIN": (1-expected)*(1-draw)}


def form_probabilities(home: dict[str, Any], away: dict[str, Any]) -> dict[str, float]:
    diff = (home["ppg"] - away["ppg"]) * .85 + (home["goal_difference"] - away["goal_difference"]) * .25 + .20
    h, d, a = _softmax([diff, .15-abs(diff)*.30, -diff])
    return {"HOME_WIN": h, "DRAW": d, "AWAY_WIN": a}


def api_probabilities(api_prediction: dict[str, Any]) -> dict[str, float] | None:
    percent = api_prediction.get("predictions", {}).get("percent", {}) if api_prediction else {}
    try:
        values = [float(str(percent.get(k, "")).replace("%", ""))/100 for k in ("home", "draw", "away")]
    except (TypeError, ValueError):
        return None
    if sum(values) <= .5:
        return None
    total = sum(values)
    return dict(zip(("HOME_WIN", "DRAW", "AWAY_WIN"), [x/total for x in values]))


def blend(models: dict[str, dict[str, float]], weights: dict[str, float]) -> tuple[dict[str, float], float]:
    keys = ("HOME_WIN", "DRAW", "AWAY_WIN")
    final = {k: 0.0 for k in keys}; used = 0.0
    for name, probs in models.items():
        weight = max(0.0, weights.get(name, 0.0))
        if not probs or weight <= 0:
            continue
        used += weight
        for key in keys:
            final[key] += probs.get(key, 0.0) * weight
    if not used:
        return {"HOME_WIN": .38, "DRAW": .28, "AWAY_WIN": .34}, 0.0
    final = {k: v/used for k, v in final.items()}
    # model agreement: inverse average absolute deviation from ensemble
    deviations = []
    for probs in models.values():
        if probs:
            deviations.extend(abs(probs.get(k, 0)-final[k]) for k in keys)
    agreement = max(0.0, 1.0 - (sum(deviations)/len(deviations) if deviations else .5)*2.5)
    return final, agreement
