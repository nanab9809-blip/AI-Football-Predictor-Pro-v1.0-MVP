from __future__ import annotations

import math
from typing import Any

MIN_SAMPLE = 12
FULL_SAMPLE = 80
PRIOR_STRENGTH = 20.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calibrate_probability(raw_probability: float, calibration: dict[str, Any] | None) -> dict[str, Any]:
    """Empirical bucket calibration with Bayesian shrinkage.

    No extra ML dependency is required. With insufficient history the raw model
    remains dominant. As settled sample grows, the empirical hit-rate receives
    more weight. This is deliberately conservative to avoid overfitting.
    """
    raw = max(0.001, min(0.999, _num(raw_probability)))
    calibration = calibration or {}
    sample = int(_num(calibration.get("sample")))
    wins = int(_num(calibration.get("wins")))
    empirical = (wins / sample) if sample > 0 else raw

    if sample < MIN_SAMPLE:
        calibrated = raw
        weight = 0.0
        status = "PROVISIONAL"
    else:
        data_weight = min(1.0, sample / FULL_SAMPLE)
        bayes_empirical = (wins + raw * PRIOR_STRENGTH) / (sample + PRIOR_STRENGTH)
        calibrated = raw * (1.0 - data_weight) + bayes_empirical * data_weight
        weight = data_weight
        status = "MATURE" if data_weight >= 1.0 else "PARTIAL"

    # Uncertainty around the calibrated estimate. A conservative floor prevents
    # fake precision even when samples are large.
    effective_n = max(sample, 8)
    se = math.sqrt(max(calibrated * (1.0 - calibrated), 0.0001) / effective_n)
    margin = max(0.025, min(0.12, 1.64 * se))  # ~90% interval
    low = max(0.0, calibrated - margin)
    high = min(1.0, calibrated + margin)

    return {
        "raw_probability": round(raw, 5),
        "calibrated_probability": round(calibrated, 5),
        "calibration_delta": round(calibrated - raw, 5),
        "calibration_sample": sample,
        "calibration_wins": wins,
        "empirical_accuracy": round(empirical, 5),
        "calibration_weight": round(weight, 3),
        "calibration_status": status,
        "confidence_interval_low": round(low, 5),
        "confidence_interval_high": round(high, 5),
        "confidence_interval_margin": round(margin, 5),
    }
