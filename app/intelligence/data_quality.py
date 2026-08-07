from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _parse_age_hours(value: Any) -> float | None:
    if not value:
        return None
    try:
        text = str(value).replace('Z', '+00:00')
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600)
    except (TypeError, ValueError):
        return None


def assess(analysis: dict[str, Any]) -> dict[str, Any]:
    internal = analysis.get('internal') or {}
    context = internal.get('context') or {}
    hf, af = internal.get('home_features') or {}, internal.get('away_features') or {}

    evidence_items = ((analysis.get("evidence_collection") or {}).get("items") or {})
    def component(key: str, label: str, weight: int, fallback_available: bool, fallback_partial: bool = False) -> dict[str, Any]:
        evidence = evidence_items.get(key) or {}
        status = str(evidence.get("status") or ("AVAILABLE" if fallback_available else "WAITING" if fallback_partial else "UNAVAILABLE"))
        return {
            "key": key, "label": label, "weight": weight, "status": status,
            "available": status == "AVAILABLE",
            "waiting": status == "WAITING",
            "unavailable": status in {"UNAVAILABLE", "NOT_REQUIRED"},
            "failed": status == "FAILED",
            "reason": evidence.get("reason") or "",
            "count": evidence.get("count"),
        }

    components = [
        component('fixture','Fixture identity',8,bool(analysis.get('fixture'))),
        component('recent_form','Last 10 matches',20,hf.get('matches',0)>=10 and af.get('matches',0)>=10,hf.get('matches',0)>=5 and af.get('matches',0)>=5),
        component('statistics','Team statistics',15,bool(analysis.get('home_statistics')) and bool(analysis.get('away_statistics'))),
        component('standings','Standings',8,bool(analysis.get('standings'))),
        component('h2h','Head-to-head',8,len(analysis.get('h2h') or [])>=1),
        component('odds','Bookmaker odds',15,bool(analysis.get('odds_available'))),
        component('injuries','Injuries',8,bool(analysis.get('injuries'))),
        component('lineups','Official line-ups',10,bool(context.get('lineups_available'))),
        component('model','Model output',8,bool(internal.get('markets')) and internal.get('model_agreement') is not None),
    ]
    total_weight = sum(c['weight'] for c in components)
    earned = 0.0
    status_scores = {'AVAILABLE': 100, 'WAITING': 55, 'UNAVAILABLE': 35, 'NOT_REQUIRED': 70, 'FAILED': 0}
    for c in components:
        c['score'] = status_scores.get(c.get('status'), 0)
        earned += c['weight'] * c['score'] / 100
    completeness = _clamp(earned / total_weight * 100)

    # Freshness uses cache/source timestamps when present and otherwise applies a
    # conservative neutral score rather than inventing freshness.
    timestamps = analysis.get('data_timestamps') or {}
    ages = {k: _parse_age_hours(v) for k, v in timestamps.items()}
    freshness_scores: list[float] = []
    limits = {'odds': 1, 'lineups': .5, 'injuries': 6, 'statistics': 12, 'standings': 12, 'recent_form': 12, 'h2h': 48}
    for key, limit in limits.items():
        age = ages.get(key)
        if age is None:
            continue
        freshness_scores.append(100 if age <= limit else max(20, 100 - ((age-limit)/max(limit,1))*35))
    freshness = _clamp(sum(freshness_scores)/len(freshness_scores) if freshness_scores else 75)

    consistency_checks: list[bool] = []
    home_matches, away_matches = float(hf.get('matches') or 0), float(af.get('matches') or 0)
    consistency_checks.append(home_matches <= 10 and away_matches <= 10)
    for features in (hf, af):
        gf, ga = float(features.get('goals_for') or 0), float(features.get('goals_against') or 0)
        ppg = float(features.get('ppg') or 0)
        consistency_checks.extend([0 <= gf <= 8, 0 <= ga <= 8, 0 <= ppg <= 3])
    markets = internal.get('markets') or {}
    one_x_two = sum(float(markets.get(k) or 0) for k in ('HOME_WIN','DRAW','AWAY_WIN'))
    if one_x_two:
        consistency_checks.append(abs(one_x_two - 1.0) <= .08)
    consistency = _clamp(100 * sum(consistency_checks) / len(consistency_checks) if consistency_checks else 70)

    # Coverage rewards the breadth of independent evidence families.
    evidence_families = [
        home_matches >= 5 and away_matches >= 5,
        bool(analysis.get('home_statistics')) and bool(analysis.get('away_statistics')),
        bool(analysis.get('standings')),
        len(analysis.get('h2h') or []) >= 3,
        bool(analysis.get('odds_available')),
        bool(analysis.get('injuries')),
        bool(context.get('lineups_available')),
    ]
    coverage = _clamp(100 * sum(evidence_families) / len(evidence_families))
    integrity = _clamp((consistency * .65) + (100 if analysis.get('fixture') else 0) * .35)

    score = _clamp(completeness*.35 + freshness*.20 + consistency*.20 + coverage*.15 + integrity*.10)
    grade = 'A+' if score >= 95 else 'A' if score >= 90 else 'B' if score >= 80 else 'C' if score >= 70 else 'D'
    decision = 'READY' if score >= 80 else 'LIMITED' if score >= 70 else 'INSUFFICIENT'
    warnings = [f"{c['label']}: {c.get('reason') or c.get('status')}" for c in components if c.get('status') in {'WAITING','FAILED'}]
    unavailable = [f"{c['label']}: {c.get('reason') or c.get('status')}" for c in components if c.get('status') in {'UNAVAILABLE','NOT_REQUIRED'}]
    strengths = [f"{c['label']} tersedia" for c in components if c.get('available')]
    return {
        'score': score,
        'grade': grade,
        'decision': decision,
        'components': components,
        'breakdown': {
            'completeness': completeness,
            'freshness': freshness,
            'consistency': consistency,
            'coverage': coverage,
            'integrity': integrity,
        },
        'warnings': warnings,
        'unavailable': unavailable,
        'strengths': strengths,
        'status_summary': {status: sum(1 for c in components if c.get('status') == status) for status in ('AVAILABLE','WAITING','UNAVAILABLE','NOT_REQUIRED','FAILED')},
        'diagnostics': [*strengths[:5], *warnings[:3], *unavailable[:2]],
    }
