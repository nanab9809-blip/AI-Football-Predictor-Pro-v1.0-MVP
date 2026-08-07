from __future__ import annotations

from collections import Counter
from typing import Any

from app.intelligence.market_relationships import relationship_score
from app.intelligence.probability_calibration import calibrate_probability


# V14 Decision Intelligence Core. Probability is no longer allowed to dominate
# the ranking. Calibration and market dependencies are first-class components.
MARKET_INTELLIGENCE_WEIGHTS = {
    "probability": 0.20,
    "expected_value": 0.20,
    "historical_roi": 0.12,
    "market_reliability": 0.12,
    "calibration": 0.10,
    "relationship": 0.06,
    "evidence": 0.10,
    "data_quality": 0.06,
    "diversity": 0.04,
}

MIN_HISTORY_SAMPLE = 10
FULL_HISTORY_SAMPLE = 50


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _sample_weight(sample: int) -> float:
    if sample < MIN_HISTORY_SAMPLE:
        return 0.0
    return min(1.0, sample / FULL_HISTORY_SAMPLE)


def _probability_component(probability: float) -> float:
    return _clamp(probability * 100.0)


def _ev_component(ev: float | None) -> tuple[float, str]:
    if ev is None:
        return 50.0, "EV belum tersedia; komponen value dibuat netral."
    score = _clamp(50.0 + _num(ev) * 200.0)
    return score, f"EV {_num(ev)*100:+.1f}% memberi skor value {score:.1f}/100."


def _history_components(history: dict[str, Any] | None) -> tuple[float, float, dict[str, Any]]:
    history = history or {}
    sample = int(_num(history.get("sample")))
    shrink = _sample_weight(sample)
    roi = _num(history.get("roi"))
    accuracy = _num(history.get("accuracy"))
    clv = _num(history.get("avg_clv"))

    if not shrink:
        return 50.0, 50.0, {
            "sample": sample, "roi": roi, "accuracy": accuracy, "avg_clv": clv,
            "history_status": "PROVISIONAL",
        }

    raw_roi = _clamp(50.0 + roi * 2.0)
    roi_score = 50.0 + (raw_roi - 50.0) * shrink
    accuracy_score = _clamp(accuracy)
    clv_score = _clamp(50.0 + clv * 4.0)
    raw_reliability = accuracy_score * 0.70 + clv_score * 0.30
    reliability_score = 50.0 + (raw_reliability - 50.0) * shrink
    return round(roi_score, 2), round(reliability_score, 2), {
        "sample": sample, "roi": roi, "accuracy": accuracy, "avg_clv": clv,
        "history_status": "MATURE" if shrink >= 1.0 else "PARTIAL",
    }


def _diversity_component(market_key: str, daily_counts: dict[str, int] | None) -> tuple[float, dict[str, Any]]:
    counts = Counter({str(k): int(v or 0) for k, v in (daily_counts or {}).items()})
    total = sum(counts.values())
    count = counts.get(str(market_key), 0)
    share = (count / total) if total else 0.0
    if total < 8 or share <= 0.25:
        score = 70.0
    elif share <= 0.40:
        score = 70.0 - ((share - 0.25) / 0.15) * 20.0
    else:
        score = max(20.0, 50.0 - ((share - 0.40) / 0.35) * 30.0)
    return round(_clamp(score), 2), {
        "daily_count": count, "daily_total": total, "daily_share_pct": round(share * 100.0, 1),
    }


def _calibration_component(cal: dict[str, Any]) -> float:
    sample = int(cal.get("calibration_sample") or 0)
    delta = abs(_num(cal.get("calibration_delta")))
    status = str(cal.get("calibration_status") or "PROVISIONAL")
    base = 50.0 if status == "PROVISIONAL" else 72.0 if status == "PARTIAL" else 82.0
    # Large correction signals model instability and reduces the component.
    return round(_clamp(base - min(28.0, delta * 180.0) + min(8.0, sample / 25.0)), 2)


def score_market(
    market: dict[str, Any],
    *,
    data_quality: float,
    evidence_strength: float,
    history: dict[str, Any] | None = None,
    calibration: dict[str, Any] | None = None,
    daily_counts: dict[str, int] | None = None,
    all_markets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    key = str(market.get("key") or "")
    raw_probability = _num(market.get("probability"))
    cal = calibrate_probability(raw_probability, calibration)
    probability = _num(cal.get("calibrated_probability"), raw_probability)
    ev = market.get("ev")

    p_score = _probability_component(probability)
    ev_score, ev_reason = _ev_component(_num(ev) if ev is not None else None)
    roi_score, reliability_score, history_meta = _history_components(history)
    diversity_score, diversity_meta = _diversity_component(key, daily_counts)
    evidence_score = _clamp(_num(evidence_strength))
    dq_score = _clamp(_num(data_quality))
    cal_score = _calibration_component(cal)

    temp_market = dict(market)
    temp_market.update(cal)
    relationship_meta = relationship_score(temp_market, all_markets or [temp_market])
    relationship_component = _clamp(_num(relationship_meta.get("score"), 100.0))

    components = {
        "probability": round(p_score, 2),
        "expected_value": round(ev_score, 2),
        "historical_roi": round(roi_score, 2),
        "market_reliability": round(reliability_score, 2),
        "calibration": round(cal_score, 2),
        "relationship": round(relationship_component, 2),
        "evidence": round(evidence_score, 2),
        "data_quality": round(dq_score, 2),
        "diversity": round(diversity_score, 2),
    }
    final_score = sum(components[name] * weight for name, weight in MARKET_INTELLIGENCE_WEIGHTS.items())

    reasons = [
        f"Raw probability {raw_probability*100:.1f}% → calibrated {probability*100:.1f}% ({cal['calibration_status']}).",
        ev_reason,
    ]
    if history_meta["sample"] >= MIN_HISTORY_SAMPLE:
        reasons.append(
            f"Histori {history_meta['sample']} settlement: ROI {history_meta['roi']:+.1f}%, "
            f"accuracy {history_meta['accuracy']:.1f}%, CLV {history_meta['avg_clv']:+.1f}%."
        )
    else:
        reasons.append(f"Histori baru {history_meta['sample']} settlement; pengaruh historis masih dibatasi.")
    reasons.extend(relationship_meta.get("notes") or [])
    if diversity_meta["daily_total"] >= 8:
        reasons.append(
            f"Konsentrasi market hari ini {diversity_meta['daily_share_pct']:.1f}% "
            f"({diversity_meta['daily_count']}/{diversity_meta['daily_total']}); diversity hanya bobot 4%."
        )

    enriched = dict(market)
    enriched.update(cal)
    enriched.update({
        "probability": round(probability, 5),
        "probability_pct": round(probability * 100.0, 1),
        "raw_probability": round(raw_probability, 5),
        "raw_probability_pct": round(raw_probability * 100.0, 1),
        "market_intelligence_score": round(_clamp(final_score), 1),
        "market_rank_score": round(_clamp(final_score), 1),
        "market_intelligence_components": components,
        "market_intelligence_reasons": reasons,
        "market_history": history_meta,
        "market_diversity": diversity_meta,
        "market_relationship": relationship_meta,
    })
    if probability > 0:
        enriched["fair_odds"] = round(1.0 / probability, 2)
        if enriched.get("odds"):
            offered = _num(enriched.get("odds"))
            enriched["ev"] = round(probability * offered - 1.0, 5)
            enriched["edge"] = round(probability - (1.0 / offered), 5) if offered > 1 else None
    return enriched


def rank_markets(
    markets: list[dict[str, Any]],
    *,
    data_quality: float,
    evidence_strength: float,
    performance_by_market: dict[str, dict[str, Any]] | None = None,
    calibration_by_market: dict[str, dict[str, Any]] | None = None,
    daily_counts: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    performance_by_market = performance_by_market or {}
    calibration_by_market = calibration_by_market or {}

    # First pass calibrates all markets, so relationship checks compare calibrated
    # probabilities rather than raw outputs.
    calibrated: list[dict[str, Any]] = []
    for market in markets:
        key = str(market.get("key") or "")
        cal = calibrate_probability(_num(market.get("probability")), calibration_by_market.get(key))
        row = dict(market)
        row.update(cal)
        row["probability"] = _num(cal.get("calibrated_probability"), _num(market.get("probability")))
        calibrated.append(row)

    ranked = [
        score_market(
            market,
            data_quality=data_quality,
            evidence_strength=evidence_strength,
            history=performance_by_market.get(str(market.get("key") or "")),
            calibration=calibration_by_market.get(str(market.get("key") or "")),
            daily_counts=daily_counts,
            all_markets=calibrated,
        )
        for market in markets
    ]
    ranked.sort(
        key=lambda row: (
            _num(row.get("market_intelligence_score")),
            _num(row.get("suitability_score")),
            _num(row.get("probability")),
        ), reverse=True,
    )
    for idx, row in enumerate(ranked, start=1):
        row["market_rank"] = idx
        row["competition_winner"] = idx == 1
        if idx == 1:
            row.setdefault("market_intelligence_reasons", []).append("Market Competition winner: Decision Intelligence Score tertinggi.")
        else:
            gap = _num(ranked[0].get("market_intelligence_score")) - _num(row.get("market_intelligence_score"))
            row.setdefault("market_intelligence_reasons", []).append(f"Kalah dalam Market Competition sebesar {gap:.1f} poin dari market #1.")
    return ranked
