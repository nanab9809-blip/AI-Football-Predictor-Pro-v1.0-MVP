from __future__ import annotations

from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def classify(
    *,
    data_quality: float,
    evidence: float,
    reliability_grade: str,
    model_agreement: float,
    confidence: float,
    suitability: float,
    probability: float,
    ev: float | None,
) -> dict[str, Any]:
    """Classify one market using a graded operational decision ladder.

    Data completeness permits evaluation, but the market direction still needs
    sufficient probability, evidence and agreement. EV improves a tier but is
    never mandatory when bookmaker odds are unavailable.
    """
    dq = max(0.0, min(100.0, _num(data_quality)))
    evidence = max(0.0, min(100.0, _num(evidence)))
    agreement = max(0.0, min(100.0, _num(model_agreement)))
    confidence = max(0.0, min(100.0, _num(confidence)))
    suitability = max(0.0, min(100.0, _num(suitability)))
    probability = max(0.0, min(100.0, _num(probability)))
    grade = str(reliability_grade or "D").upper()

    ladder_score = round(
        evidence * 0.24
        + suitability * 0.24
        + agreement * 0.15
        + confidence * 0.15
        + dq * 0.12
        + probability * 0.10,
        1,
    )

    hard_blocks: list[str] = []
    if dq < 70:
        hard_blocks.append("Data Quality di bawah 70")
    if grade == "D":
        hard_blocks.append("Reliability Grade D")
    if evidence < 55:
        hard_blocks.append("Evidence arah market terlalu lemah")
    if probability < 45:
        hard_blocks.append("Probabilitas market di bawah 45%")

    ev_value = _num(ev) if ev is not None else None
    value_verified = ev_value is not None and ev_value > 0
    value_status = (
        "UNAVAILABLE" if ev_value is None else
        "POSITIVE" if ev_value > 0 else
        "NEUTRAL" if ev_value == 0 else
        "NEGATIVE"
    )
    positive_value_bonus = 2.0 if value_verified else 0.0
    effective_score = round(min(100.0, ladder_score + positive_value_bonus), 1)

    # Recommendation and model ranking are intentionally different concepts.
    # A market may be the model's best market, but it is not a public betting
    # recommendation when live bookmaker odds prove the expected value negative.
    severe_negative_value = ev_value is not None and ev_value <= -0.05
    mild_negative_value = ev_value is not None and -0.05 < ev_value <= 0
    if severe_negative_value:
        hard_blocks.append(f"EV negatif {ev_value*100:.1f}%")

    if hard_blocks:
        tier = "NO_BET"
    elif (
        effective_score >= 86
        and dq >= 85
        and evidence >= 78
        and agreement >= 78
        and confidence >= 76
        and suitability >= 80
        and probability >= 58
    ):
        tier = "ELITE_PICK"
    elif (
        effective_score >= 78
        and dq >= 78
        and evidence >= 68
        and agreement >= 68
        and confidence >= 68
        and suitability >= 70
        and probability >= 53
    ):
        tier = "STRONG_PICK"
    elif (
        effective_score >= 69
        and dq >= 70
        and evidence >= 60
        and agreement >= 60
        and confidence >= 62
        and suitability >= 62
        and probability >= 50
    ):
        tier = "PICK"
    elif effective_score >= 58 and probability >= 47 and evidence >= 55:
        tier = "MONITOR"
    else:
        tier = "NO_BET"

    # Mildly negative or break-even EV can remain analytically interesting, but
    # must never be published as PICK/STRONG/ELITE. This preserves Best Market
    # visibility while keeping the Recommendation layer commercially honest.
    if mild_negative_value and tier in {"ELITE_PICK", "STRONG_PICK", "PICK"}:
        tier = "MONITOR"

    labels = {
        "ELITE_PICK": "ELITE PICK",
        "STRONG_PICK": "STRONG PICK",
        "PICK": "PICK",
        "MONITOR": "MONITOR",
        "NO_BET": "NO BET",
    }
    risk = {
        "ELITE_PICK": "LOW",
        "STRONG_PICK": "LOW-MEDIUM",
        "PICK": "MEDIUM",
        "MONITOR": "HIGH",
        "NO_BET": "AVOID",
    }[tier]
    published = tier in {"ELITE_PICK", "STRONG_PICK", "PICK"}
    eligibility = "ELIGIBLE" if published else "REVIEW" if tier == "MONITOR" else "NO_BET"

    reasons: list[str] = [
        f"Decision Ladder Score {effective_score:.1f}/100.",
        f"Kombinasi: Data Quality {dq:.1f}, Evidence {evidence:.1f}, Suitability {suitability:.1f}, "
        f"Agreement {agreement:.1f}, Confidence {confidence:.1f}, Probability {probability:.1f}%.",
    ]
    if value_verified:
        reasons.append("EV positif terverifikasi dan memberi bonus kecil pada tier keputusan.")
    elif ev_value is None:
        reasons.append("Odds/EV belum tersedia; market tetap dinilai sebagai Model Pick.")
    elif ev_value <= -0.05:
        reasons.append(f"EV {ev_value*100:.1f}% bersifat negatif dan memblokir rekomendasi publik.")
    elif ev_value <= 0:
        reasons.append(f"EV {ev_value*100:.1f}% belum positif; market dibatasi maksimal MONITOR.")
    if hard_blocks:
        reasons.append("Hard block: " + ", ".join(hard_blocks) + ".")
    elif tier == "MONITOR":
        reasons.append("Market belum cukup kuat untuk rekomendasi publik, tetapi layak dipantau.")
    elif published:
        reasons.append(f"Market lolos sebagai {labels[tier]}.")
    else:
        reasons.append("Kekuatan arah market belum mencapai ambang rekomendasi.")

    return {
        "decision_tier": tier,
        "decision_label": labels[tier],
        "decision_eligibility": eligibility,
        "decision_score": effective_score,
        "risk_level": risk,
        "published": published,
        "value_verified": value_verified,
        "value_status": value_status,
        "recommendation_basis": "VALUE_VERIFIED" if value_verified else "MODEL_ONLY" if ev_value is None else "NO_VALUE",
        "ladder_reasons": reasons,
        "hard_blocks": hard_blocks,
    }
