from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from app.intelligence.decision_ladder import classify as classify_decision_ladder

CORE_HEADLINE_MARKETS = {
    "HOME_WIN", "DRAW", "AWAY_WIN",
    "HOME_OR_DRAW", "AWAY_OR_DRAW", "HOME_OR_AWAY",
    "OVER_1_5", "UNDER_1_5", "OVER_2_5", "UNDER_2_5", "OVER_3_5", "UNDER_3_5",
    "AH_HOME_M0_5", "AH_AWAY_M0_5", "HOME_DNB", "AWAY_DNB",
    "BTTS_YES", "BTTS_NO",
}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dig(data: dict[str, Any] | None, *path: str, default: Any = None) -> Any:
    cur: Any = data or {}
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _pct_edge(home: float, away: float, *, lower_is_better: bool = False) -> float:
    denom = max(abs(home), abs(away), 0.25)
    raw = (away - home) / denom if lower_is_better else (home - away) / denom
    return max(-1.0, min(1.0, raw))


def _season_metric(stats: dict[str, Any], kind: str) -> float | None:
    if not stats:
        return None
    if kind == "gf":
        return _num(_dig(stats, "goals", "for", "average", "total"), -1)
    if kind == "ga":
        return _num(_dig(stats, "goals", "against", "average", "total"), -1)
    if kind == "home_gf":
        return _num(_dig(stats, "goals", "for", "average", "home"), -1)
    if kind == "away_gf":
        return _num(_dig(stats, "goals", "for", "average", "away"), -1)
    if kind == "home_ga":
        return _num(_dig(stats, "goals", "against", "average", "home"), -1)
    if kind == "away_ga":
        return _num(_dig(stats, "goals", "against", "average", "away"), -1)
    if kind == "clean":
        home = _num(_dig(stats, "clean_sheet", "home"), 0)
        away = _num(_dig(stats, "clean_sheet", "away"), 0)
        total = _num(_dig(stats, "fixtures", "played", "total"), 0)
        return (home + away) / total if total else None
    if kind == "failed":
        home = _num(_dig(stats, "failed_to_score", "home"), 0)
        away = _num(_dig(stats, "failed_to_score", "away"), 0)
        total = _num(_dig(stats, "fixtures", "played", "total"), 0)
        return (home + away) / total if total else None
    return None


@dataclass
class EvidenceComponent:
    key: str
    label: str
    score: float
    weight: float
    available: bool
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_team_comparison(
    *,
    home_name: str,
    away_name: str,
    home_features: dict[str, Any],
    away_features: dict[str, Any],
    home_statistics: dict[str, Any] | None,
    away_statistics: dict[str, Any] | None,
    h2h_features: dict[str, Any],
    context: dict[str, Any],
    home_xg: float,
    away_xg: float,
    model_agreement: float,
    data_quality: float,
    league_reliability: float,
) -> dict[str, Any]:
    components: list[EvidenceComponent] = []

    attack_edge = (
        _pct_edge(_num(home_features.get("goals_for")), _num(away_features.get("goals_for"))) * 0.45
        + _pct_edge(_num(home_features.get("attack_rating")), _num(away_features.get("attack_rating"))) * 0.35
        + _pct_edge(home_xg, away_xg) * 0.20
    )
    components.append(EvidenceComponent(
        "attack", "Attack", round(50 + attack_edge * 50, 1), 0.16, True,
        f"Gol/laga {home_name} {_num(home_features.get('goals_for')):.2f} vs {away_name} {_num(away_features.get('goals_for')):.2f}; xG {home_xg:.2f} vs {away_xg:.2f}.",
    ))

    defense_edge = (
        _pct_edge(_num(home_features.get("goals_against")), _num(away_features.get("goals_against")), lower_is_better=True) * 0.65
        + _pct_edge(_num(home_features.get("defense_rating")), _num(away_features.get("defense_rating"))) * 0.35
    )
    components.append(EvidenceComponent(
        "defense", "Defense", round(50 + defense_edge * 50, 1), 0.14, True,
        f"Kebobolan/laga {home_name} {_num(home_features.get('goals_against')):.2f} vs {away_name} {_num(away_features.get('goals_against')):.2f}.",
    ))

    form_edge = (
        _pct_edge(_num(home_features.get("ppg")), _num(away_features.get("ppg"))) * 0.60
        + _pct_edge(_num(home_features.get("momentum")), _num(away_features.get("momentum"))) * 0.40
    )
    form_available = _num(home_features.get("matches")) >= 5 and _num(away_features.get("matches")) >= 5
    components.append(EvidenceComponent(
        "form", "Last 10 & momentum", round(50 + form_edge * 50, 1), 0.16, form_available,
        f"PPG 10 laga {home_name} {_num(home_features.get('ppg')):.2f} vs {away_name} {_num(away_features.get('ppg')):.2f}.",
    ))

    home_split = _season_metric(home_statistics or {}, "home_gf")
    away_split = _season_metric(away_statistics or {}, "away_gf")
    home_ga = _season_metric(home_statistics or {}, "home_ga")
    away_ga = _season_metric(away_statistics or {}, "away_ga")
    split_available = home_split is not None and away_split is not None and home_split >= 0 and away_split >= 0
    if split_available:
        split_edge = _pct_edge(float(home_split), float(away_split)) * 0.60
        if home_ga is not None and away_ga is not None and home_ga >= 0 and away_ga >= 0:
            split_edge += _pct_edge(float(home_ga), float(away_ga), lower_is_better=True) * 0.40
        split_score = round(50 + split_edge * 50, 1)
        split_summary = f"Split kandang/tandang gol: {home_name} {home_split:.2f}, {away_name} {away_split:.2f}."
    else:
        split_score = 50.0
        split_summary = "Statistik split kandang/tandang belum lengkap."
    components.append(EvidenceComponent("home_away", "Home/Away split", split_score, 0.12, split_available, split_summary))

    h2h_matches = int(_num(h2h_features.get("matches")))
    h2h_edge = max(-1.0, min(1.0, (_num(h2h_features.get("home_ppg"), 1.35) - 1.35) / 1.65))
    h2h_available = h2h_matches >= 3
    components.append(EvidenceComponent(
        "h2h", "H2H", round(50 + h2h_edge * 50, 1), 0.08, h2h_available,
        f"{h2h_matches} H2H; PPG perspektif tim kandang {_num(h2h_features.get('home_ppg'), 1.35):.2f}; rata-rata gol {_num(h2h_features.get('avg_goals'), 2.5):.2f}.",
    ))

    home_streak = int(_num(home_features.get("current_streak_length")))
    away_streak = int(_num(away_features.get("current_streak_length")))
    home_type = str(home_features.get("current_streak_type") or "-")
    away_type = str(away_features.get("current_streak_type") or "-")
    streak_edge = 0.0
    if home_type == "W":
        streak_edge += min(1.0, home_streak / 5) * 0.55
    elif home_type == "L":
        streak_edge -= min(1.0, home_streak / 5) * 0.55
    if away_type == "W":
        streak_edge -= min(1.0, away_streak / 5) * 0.45
    elif away_type == "L":
        streak_edge += min(1.0, away_streak / 5) * 0.45
    streak_edge += max(-0.35, min(0.35, (int(_num(home_features.get("unbeaten_streak"))) - int(_num(away_features.get("unbeaten_streak")))) / 12))
    components.append(EvidenceComponent(
        "streak", "Current streak", round(50 + max(-1.0, min(1.0, streak_edge)) * 50, 1), 0.08, form_available,
        f"Streak {home_name}: {home_type}{home_streak}, unbeaten {int(_num(home_features.get('unbeaten_streak')))}; "
        f"{away_name}: {away_type}{away_streak}, unbeaten {int(_num(away_features.get('unbeaten_streak')))}.",
    ))

    injury_delta = int(_num(context.get("away_injuries"))) - int(_num(context.get("home_injuries")))
    squad_score = max(20.0, min(80.0, 50 + injury_delta * 5))
    squad_available = bool(context.get("home_injuries") or context.get("away_injuries") or context.get("lineups_available"))
    components.append(EvidenceComponent(
        "squad", "Squad availability", round(squad_score, 1), 0.07, squad_available,
        f"Cedera terdata {home_name} {int(_num(context.get('home_injuries')))} vs {away_name} {int(_num(context.get('away_injuries')))}; line-up {'lengkap' if context.get('lineups_available') else 'belum lengkap'}.",
    ))

    season_available = bool(home_statistics) and bool(away_statistics)
    season_gf_home = _season_metric(home_statistics or {}, "gf")
    season_gf_away = _season_metric(away_statistics or {}, "gf")
    season_ga_home = _season_metric(home_statistics or {}, "ga")
    season_ga_away = _season_metric(away_statistics or {}, "ga")
    if season_available and season_gf_home is not None and season_gf_away is not None and season_gf_home >= 0 and season_gf_away >= 0:
        season_edge = _pct_edge(season_gf_home, season_gf_away) * 0.55
        if season_ga_home is not None and season_ga_away is not None and season_ga_home >= 0 and season_ga_away >= 0:
            season_edge += _pct_edge(season_ga_home, season_ga_away, lower_is_better=True) * 0.45
        season_score = round(50 + season_edge * 50, 1)
        season_summary = f"Musim: gol/laga {season_gf_home:.2f} vs {season_gf_away:.2f}; kebobolan {season_ga_home:.2f} vs {season_ga_away:.2f}."
    else:
        season_score = 50.0
        season_summary = "Statistik musim belum lengkap."
    components.append(EvidenceComponent("season", "Season statistics", season_score, 0.10, season_available, season_summary))

    agreement_score = max(0.0, min(100.0, model_agreement))
    components.append(EvidenceComponent("agreement", "Model agreement", agreement_score, 0.06, True, f"Kesepakatan model {agreement_score:.1f}%."))
    components.append(EvidenceComponent("league", "League reliability", max(0.0, min(100.0, league_reliability)), 0.03, True, f"Reliabilitas historis liga {league_reliability:.1f}%."))

    available_weight = sum(c.weight for c in components if c.available)
    weighted = sum(c.score * c.weight for c in components if c.available)
    evidence_score = round(weighted / available_weight if available_weight else 0.0, 1)
    completeness = round(100 * available_weight / sum(c.weight for c in components), 1)
    directional_score = round(evidence_score - 50, 1)
    favored_side = "HOME" if directional_score >= 5 else "AWAY" if directional_score <= -5 else "BALANCED"

    strengths = sorted((c for c in components if c.available), key=lambda c: abs(c.score - 50), reverse=True)[:4]
    metric_rows = [
        {"label": "Matches used", "home": int(_num(home_features.get("matches"))), "away": int(_num(away_features.get("matches"))), "format": "integer"},
        {"label": "Form sequence", "home": home_features.get("form_sequence") or "-", "away": away_features.get("form_sequence") or "-", "format": "text"},
        {"label": "Points per game", "home": round(_num(home_features.get("ppg")), 2), "away": round(_num(away_features.get("ppg")), 2), "format": "number"},
        {"label": "Goals per game", "home": round(_num(home_features.get("goals_for")), 2), "away": round(_num(away_features.get("goals_for")), 2), "format": "number"},
        {"label": "Goals conceded", "home": round(_num(home_features.get("goals_against")), 2), "away": round(_num(away_features.get("goals_against")), 2), "format": "number", "lower_better": True},
        {"label": "Win rate", "home": round(_num(home_features.get("win_rate"))*100, 1), "away": round(_num(away_features.get("win_rate"))*100, 1), "format": "percent"},
        {"label": "Clean sheet", "home": round(_num(home_features.get("clean_sheet_rate"))*100, 1), "away": round(_num(away_features.get("clean_sheet_rate"))*100, 1), "format": "percent"},
        {"label": "Failed to score", "home": round(_num(home_features.get("failed_to_score_rate"))*100, 1), "away": round(_num(away_features.get("failed_to_score_rate"))*100, 1), "format": "percent", "lower_better": True},
        {"label": "BTTS rate", "home": round(_num(home_features.get("btts_rate"))*100, 1), "away": round(_num(away_features.get("btts_rate"))*100, 1), "format": "percent"},
        {"label": "Over 2.5 rate", "home": round(_num(home_features.get("over_25_rate"))*100, 1), "away": round(_num(away_features.get("over_25_rate"))*100, 1), "format": "percent"},
        {"label": "Current streak", "home": f"{home_features.get('current_streak_type') or '-'}{int(_num(home_features.get('current_streak_length')))}", "away": f"{away_features.get('current_streak_type') or '-'}{int(_num(away_features.get('current_streak_length')))}", "format": "text"},
        {"label": "Unbeaten streak", "home": int(_num(home_features.get("unbeaten_streak"))), "away": int(_num(away_features.get("unbeaten_streak"))), "format": "integer"},
        {"label": "Scoring streak", "home": int(_num(home_features.get("scoring_streak"))), "away": int(_num(away_features.get("scoring_streak"))), "format": "integer"},
        {"label": "Expected goals", "home": round(home_xg, 2), "away": round(away_xg, 2), "format": "number"},
    ]
    return {
        "home_name": home_name,
        "away_name": away_name,
        "components": [c.to_dict() for c in components],
        "evidence_score": evidence_score,
        "data_completeness": completeness,
        "favored_side": favored_side,
        "directional_score": directional_score,
        "strengths": [c.summary for c in strengths],
        "metric_rows": metric_rows,
        "h2h_summary": {
            "matches": h2h_matches,
            "sequence": h2h_features.get("sequence") or "-",
            "current_streak": f"{h2h_features.get('current_streak_type') or '-'}{int(_num(h2h_features.get('current_streak_length')))}",
            "avg_goals": round(_num(h2h_features.get("avg_goals"), 2.5), 2),
            "btts_rate": round(_num(h2h_features.get("btts_rate"), .5)*100, 1),
            "over_25_rate": round(_num(h2h_features.get("over_25_rate"), .5)*100, 1),
            "over_25_streak": int(_num(h2h_features.get("over_25_streak"))),
            "btts_streak": int(_num(h2h_features.get("btts_streak"))),
        },
        "data_quality": round(data_quality, 1),
    }


def market_suitability(
    market_rows: list[dict[str, Any]],
    *,
    comparison: dict[str, Any],
    h2h_features: dict[str, Any],
    home_features: dict[str, Any],
    away_features: dict[str, Any],
    home_xg: float,
    away_xg: float,
) -> list[dict[str, Any]]:
    total_xg = home_xg + away_xg
    favored = comparison.get("favored_side")
    evidence = _num(comparison.get("evidence_score"), 50)
    h2h_goals = _num(h2h_features.get("avg_goals"), 2.5)
    h2h_btts = _num(h2h_features.get("btts_rate"), 0.5)
    combined_btts = (_num(home_features.get("btts_rate"), .5) + _num(away_features.get("btts_rate"), .5)) / 2
    combined_over = (_num(home_features.get("over_25_rate"), .5) + _num(away_features.get("over_25_rate"), .5)) / 2
    home_streak_type = str(home_features.get("current_streak_type") or "-")
    away_streak_type = str(away_features.get("current_streak_type") or "-")
    home_streak_len = int(_num(home_features.get("current_streak_length")))
    away_streak_len = int(_num(away_features.get("current_streak_length")))

    rows: list[dict[str, Any]] = []
    for row in market_rows:
        key = str(row.get("key") or "")
        if key not in CORE_HEADLINE_MARKETS:
            continue
        probability = _num(row.get("probability"))
        score = probability * 58 + evidence * 0.22
        reasons: list[str] = [f"Probabilitas model {probability*100:.1f}%."]

        if key in {"HOME_WIN", "HOME_OR_DRAW", "AH_HOME_M0_5", "HOME_DNB"}:
            score += 14 if favored == "HOME" else -12 if favored == "AWAY" else 0
            if home_streak_type == "W":
                score += min(6, home_streak_len * 1.5)
                reasons.append(f"Tim kandang sedang dalam streak W{home_streak_len}.")
            if away_streak_type == "L":
                score += min(5, away_streak_len * 1.25)
                reasons.append(f"Tim tandang sedang dalam streak L{away_streak_len}.")
            reasons.append("Team Comparison mendukung tim kandang." if favored == "HOME" else "Team Comparison tidak memberi dominasi kuat untuk tim kandang.")
        elif key in {"AWAY_WIN", "AWAY_OR_DRAW", "AH_AWAY_M0_5", "AWAY_DNB"}:
            score += 14 if favored == "AWAY" else -12 if favored == "HOME" else 0
            if away_streak_type == "W":
                score += min(6, away_streak_len * 1.5)
                reasons.append(f"Tim tandang sedang dalam streak W{away_streak_len}.")
            if home_streak_type == "L":
                score += min(5, home_streak_len * 1.25)
                reasons.append(f"Tim kandang sedang dalam streak L{home_streak_len}.")
            reasons.append("Team Comparison mendukung tim tandang." if favored == "AWAY" else "Team Comparison tidak memberi dominasi kuat untuk tim tandang.")
        elif key.startswith("OVER_"):
            threshold = 1.5 if "1_5" in key else 3.5 if "3_5" in key else 2.5
            goal_signal = (total_xg - threshold) * 8 + (h2h_goals - threshold) * 4 + (combined_over - .5) * 15
            score += max(-16, min(18, goal_signal))
            reasons.append(f"Sinyal gol: total xG {total_xg:.2f}, H2H {h2h_goals:.2f} gol/laga.")
        elif key.startswith("UNDER_"):
            threshold = 1.5 if "1_5" in key else 2.5 if "2_5" in key else 3.5
            goal_signal = (threshold - total_xg) * 8 + (threshold - h2h_goals) * 3 + (.5 - combined_over) * 12
            score += max(-16, min(18, goal_signal))
            reasons.append(f"Sinyal under: total xG {total_xg:.2f}, H2H {h2h_goals:.2f} gol/laga.")
        elif key == "BTTS_YES":
            score += max(-14, min(16, (combined_btts - .5) * 28 + (h2h_btts - .5) * 18))
            reasons.append(f"BTTS form {combined_btts*100:.0f}% dan H2H {h2h_btts*100:.0f}%.")
        elif key == "BTTS_NO":
            score += max(-14, min(16, (.5 - combined_btts) * 28 + (.5 - h2h_btts) * 18))
            reasons.append(f"BTTS rendah: form {combined_btts*100:.0f}% dan H2H {h2h_btts*100:.0f}%.")

        if row.get("ev") is not None:
            score += max(-12, min(14, _num(row.get("ev")) * 80))
            reasons.append(f"EV {_num(row.get('ev'))*100:+.1f}%.")
        score = round(max(0.0, min(100.0, score)), 1)
        enriched = dict(row)
        enriched["suitability_score"] = score
        enriched["suitability_reasons"] = reasons
        rows.append(enriched)
    rows.sort(key=lambda x: (x["suitability_score"], _num(x.get("probability"))), reverse=True)
    return rows


def select_decision(
    ranked_markets: list[dict[str, Any]],
    *,
    comparison: dict[str, Any],
    data_quality: float,
    model_agreement: float,
    confidence: float,
    odds_available: bool,
    reliability_grade: str = "D",
) -> dict[str, Any]:
    if not ranked_markets:
        return {
            "status": "NO_PICK", "decision_status": "NO_BET",
            "decision_tier": "NO_BET", "decision_label": "NO BET",
            "published": False, "reasons": ["Tidak ada market inti yang dapat dinilai."],
        }

    # Evaluate every headline market through the same ladder, then select the
    # strongest public recommendation. This prevents one unsuitable top-ranked
    # market from forcing the entire match into NO BET.
    evaluated: list[dict[str, Any]] = []
    for market in ranked_markets:
        candidate = dict(market)
        evidence = _num(comparison.get("evidence_score"))
        suitability = _num(candidate.get("suitability_score"))
        probability = _num(candidate.get("probability")) * 100
        ev = candidate.get("ev")
        ladder = classify_decision_ladder(
            data_quality=data_quality, evidence=evidence,
            reliability_grade=reliability_grade,
            model_agreement=model_agreement, confidence=confidence,
            suitability=suitability, probability=probability, ev=ev,
        )
        reasons = list(candidate.get("suitability_reasons") or [])
        reasons.extend(candidate.get("market_intelligence_reasons") or [])
        reasons.extend(ladder["ladder_reasons"])
        candidate.update({
            "status": ladder["decision_tier"],
            "decision_status": ladder["decision_tier"],
            "decision_tier": ladder["decision_tier"],
            "decision_label": ladder["decision_label"],
            "decision_eligibility": ladder["decision_eligibility"],
            "published": ladder["published"],
            "decision_score": ladder["decision_score"],
            "risk_level": ladder["risk_level"],
            "evidence_score": evidence,
            "market_suitability": suitability,
            "value_verified": ladder["value_verified"],
            "decision_reasons": reasons,
            "hard_blocks": ladder["hard_blocks"],
        })
        evaluated.append(candidate)

    tier_rank = {"ELITE_PICK": 5, "STRONG_PICK": 4, "PICK": 3, "MONITOR": 2, "NO_BET": 1}
    evaluated.sort(
        key=lambda row: (
            tier_rank.get(str(row.get("decision_tier")), 0),
            _num(row.get("market_intelligence_score"), _num(row.get("suitability_score"))),
            _num(row.get("decision_score")),
            _num(row.get("suitability_score")),
            _num(row.get("probability")),
        ),
        reverse=True,
    )
    return evaluated[0]

