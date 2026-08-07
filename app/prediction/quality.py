from __future__ import annotations

from typing import Any


def quality_index(*, data_completeness: float, model_agreement: float, sample_strength: float,
                  odds_available: bool, lineups_available: bool, historical_accuracy: float = .55,
                  volatility: float = .25) -> dict[str, Any]:
    score = (
        data_completeness * 25 + model_agreement * 22 + sample_strength * 18 +
        historical_accuracy * 18 + (1.0 if odds_available else .35) * 9 +
        (1.0 if lineups_available else .25) * 8 - volatility * 10
    )
    score = round(max(0.0, min(100.0, score)), 1)
    if score >= 80:
        grade, decision = "A", "STRONG_RECOMMENDATION"
    elif score >= 68:
        grade, decision = "B", "RECOMMENDATION"
    elif score >= 55:
        grade, decision = "C", "CAUTION"
    else:
        grade, decision = "D", "NO_RECOMMENDATION"
    return {"score": score, "grade": grade, "decision": decision}


def confidence(*, top_probability: float, model_agreement: float, quality_score: float, edge: float | None) -> float:
    value = 35 + top_probability*30 + model_agreement*18 + quality_score*.17
    if edge is not None:
        value += max(-8, min(8, edge*80))
    return round(max(35.0, min(94.0, value)), 1)
