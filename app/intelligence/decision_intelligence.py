from __future__ import annotations
from typing import Any


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 1)


def build(*, data_quality: dict[str, Any], evidence_score: float, model_agreement: float,
          confidence: float, odds_available: bool, lineup_available: bool) -> dict[str, Any]:
    dq = _clamp(data_quality.get('score') or 0)
    breakdown = data_quality.get('breakdown') or {}
    freshness = _clamp(breakdown.get('freshness') or 0)
    consistency = _clamp(breakdown.get('consistency') or 0)
    evidence = _clamp(evidence_score)

    reliability_score = _clamp(dq*.40 + evidence*.30 + consistency*.15 + freshness*.15)
    grade = 'A+' if reliability_score >= 95 else 'A' if reliability_score >= 90 else 'B' if reliability_score >= 80 else 'C' if reliability_score >= 70 else 'D'
    label = {'A+':'PREMIUM','A':'STRONG','B':'STANDARD','C':'CAUTION','D':'NO BET'}[grade]

    if dq < 70 or grade == 'D' or evidence < 60:
        eligibility = 'NO_BET'
    elif grade == 'C' or model_agreement < 70 or confidence < 68:
        eligibility = 'REVIEW'
    else:
        eligibility = 'ELIGIBLE'

    permissions = {
        'selected_pick_allowed': eligibility in {'ELIGIBLE','REVIEW'},
        'builder_allowed': eligibility == 'ELIGIBLE' and grade in {'A+','A','B'},
        'ev_allowed': eligibility == 'ELIGIBLE' and odds_available,
    }
    reasons: list[str] = []
    reasons.append(f"Data Quality {dq:.1f}/100 (Grade {data_quality.get('grade','-')}).")
    reasons.append(f"Evidence Strength {evidence:.1f}/100.")
    reasons.append(f"Reliability {grade} · {label} ({reliability_score:.1f}/100).")
    if not odds_available:
        reasons.append('Odds belum tersedia; EV tidak diizinkan.')
    if not lineup_available:
        reasons.append('Line-up resmi belum tersedia.')
    if eligibility == 'NO_BET':
        reasons.append('Quality Gate operasional gagal; rekomendasi publik dihentikan.')
    elif eligibility == 'REVIEW':
        reasons.append('Pertandingan hanya layak untuk Selected Pick dengan kehati-hatian; Builder diblokir.')
    else:
        reasons.append('Data Gate lolos; market selection dan evaluasi Builder dapat dilanjutkan.')

    return {
        'data_quality': dq,
        'data_quality_grade': data_quality.get('grade'),
        'data_quality_breakdown': breakdown,
        'evidence_strength': evidence,
        'reliability_score': reliability_score,
        'reliability_grade': grade,
        'reliability_label': label,
        'decision_eligibility': eligibility,
        **permissions,
        'reasons': reasons,
    }
