from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.intelligence.market_relationships import builder_correlation

# Sportsbook Builder AI: only broadly supported Bet Builder legs belong here.
# Asian Handicap remains a SINGLE MARKET and is intentionally excluded.
SPORTSBOOK_BUILDER_MARKETS = {
    "HOME_WIN", "DRAW", "AWAY_WIN",
    "HOME_OR_DRAW", "AWAY_OR_DRAW", "HOME_OR_AWAY",
    "OVER_1_5", "UNDER_1_5", "OVER_2_5", "UNDER_2_5", "OVER_3_5", "UNDER_3_5",
    "BTTS_YES", "BTTS_NO",
}

HANDICAP_MARKETS = {
    "AH_HOME_M0_5", "AH_AWAY_M0_5", "HOME_DNB", "AWAY_DNB",
    "AH_HOME_P0_5", "AH_AWAY_P0_5",
}

DISPLAY_PRIORITY = {
    "HOME_WIN": 10, "DRAW": 10, "AWAY_WIN": 10,
    "HOME_OR_DRAW": 20, "AWAY_OR_DRAW": 20, "HOME_OR_AWAY": 20,
    "BTTS_YES": 30, "BTTS_NO": 30,
    "OVER_1_5": 40, "UNDER_1_5": 40,
    "OVER_2_5": 40, "UNDER_2_5": 40,
    "OVER_3_5": 40, "UNDER_3_5": 40,
}

MARKET_LABELS = {
    "HOME_WIN": "Home Win", "DRAW": "Draw", "AWAY_WIN": "Away Win",
    "HOME_OR_DRAW": "Home or Draw", "AWAY_OR_DRAW": "Away or Draw", "HOME_OR_AWAY": "Home or Away",
    "OVER_1_5": "Over 1.5 Goals", "UNDER_1_5": "Under 1.5 Goals",
    "OVER_2_5": "Over 2.5 Goals", "UNDER_2_5": "Under 2.5 Goals",
    "OVER_3_5": "Over 3.5 Goals", "UNDER_3_5": "Under 3.5 Goals",
    "BTTS_YES": "BTTS Yes", "BTTS_NO": "BTTS No",
}


@dataclass(frozen=True)
class BuilderTemplate:
    code: str
    dna: str
    legs: tuple[str, str]
    min_probabilities: tuple[float, float]
    scenario: str
    base_correlation: float
    priority: int


# Template football stories. No handicap leg is permitted.
BUILDER_TEMPLATES: tuple[BuilderTemplate, ...] = (
    BuilderTemplate("DEF_HOME_U35", "Defensive Home", ("HOME_OR_DRAW", "UNDER_3_5"), (0.80, 0.75), "Tim kandang diproyeksikan tidak kalah dalam laga dengan total gol terkendali.", 92, 100),
    BuilderTemplate("HOME_FAV_U35", "Home Favourite", ("HOME_WIN", "UNDER_3_5"), (0.64, 0.72), "Tim kandang diproyeksikan menang tanpa laga menjadi sangat terbuka.", 89, 96),
    BuilderTemplate("DEF_AWAY_U35", "Defensive Away", ("AWAY_OR_DRAW", "UNDER_3_5"), (0.80, 0.75), "Tim tandang diproyeksikan tidak kalah dalam laga dengan total gol terkendali.", 92, 100),
    BuilderTemplate("AWAY_FAV_U35", "Away Favourite", ("AWAY_WIN", "UNDER_3_5"), (0.64, 0.72), "Tim tandang diproyeksikan menang tanpa laga menjadi sangat terbuka.", 89, 96),
    BuilderTemplate("HOME_OPEN_O25", "Home Attack", ("HOME_WIN", "OVER_2_5"), (0.60, 0.62), "Keunggulan tuan rumah didukung ekspektasi pertandingan dengan minimal tiga gol.", 84, 88),
    BuilderTemplate("AWAY_OPEN_O25", "Away Attack", ("AWAY_WIN", "OVER_2_5"), (0.60, 0.62), "Keunggulan tim tandang didukung ekspektasi pertandingan dengan minimal tiga gol.", 84, 88),
    BuilderTemplate("HOME_OPEN_O35", "High-Scoring Home", ("HOME_WIN", "OVER_3_5"), (0.60, 0.56), "Tim kandang unggul dalam proyeksi pertandingan dengan empat gol atau lebih.", 78, 74),
    BuilderTemplate("HOME_DC_O35", "Protected High-Scoring Home", ("HOME_OR_DRAW", "OVER_3_5"), (0.77, 0.56), "Perlindungan hasil kandang digabung dengan proyeksi skor tinggi.", 79, 76),
    BuilderTemplate("AWAY_OPEN_O35", "High-Scoring Away", ("AWAY_WIN", "OVER_3_5"), (0.60, 0.56), "Tim tandang unggul dalam proyeksi pertandingan dengan empat gol atau lebih.", 78, 74),
    BuilderTemplate("AWAY_DC_O35", "Protected High-Scoring Away", ("AWAY_OR_DRAW", "OVER_3_5"), (0.77, 0.56), "Perlindungan hasil tandang digabung dengan proyeksi skor tinggi.", 79, 76),
    BuilderTemplate("HOME_NIL", "Strong Home Favourite", ("HOME_WIN", "BTTS_NO"), (0.62, 0.60), "Tim kandang diproyeksikan menang dan peluang tim tandang mencetak gol relatif rendah.", 86, 86),
    BuilderTemplate("AWAY_NIL", "Strong Away Favourite", ("AWAY_WIN", "BTTS_NO"), (0.62, 0.60), "Tim tandang diproyeksikan menang dan peluang tim kandang mencetak gol relatif rendah.", 86, 86),
    BuilderTemplate("GOAL_FESTIVAL", "Goal Festival", ("BTTS_YES", "OVER_2_5"), (0.64, 0.64), "Kedua tim diproyeksikan mencetak gol dalam pertandingan terbuka.", 91, 94),
    BuilderTemplate("TACTICAL_U35", "Tactical Match", ("BTTS_NO", "UNDER_3_5"), (0.62, 0.74), "Setidaknya satu tim diproyeksikan gagal mencetak gol dan total laga tetap di bawah 3.5.", 90, 90),
    BuilderTemplate("LOW_SCORING", "Low-Scoring Match", ("BTTS_NO", "UNDER_2_5"), (0.64, 0.62), "Pertandingan diproyeksikan ketat dengan maksimal dua gol.", 91, 84),
)

TEMPLATE_BY_PAIR = {frozenset(t.legs): t for t in BUILDER_TEMPLATES}


def _market_map(market_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(m.get("key") or ""): m for m in market_rows if str(m.get("key") or "")}


def _label(item: dict[str, Any]) -> str:
    return MARKET_LABELS.get(str(item.get("key") or ""), str(item.get("label") or item.get("key") or "-"))


def _offered_odds(items: Iterable[dict[str, Any]]) -> tuple[float, bool]:
    odds = 1.0
    complete = True
    for item in items:
        value = item.get("odds")
        if value:
            odds *= float(value)
        else:
            complete = False
            fair = float(item.get("fair_odds") or 0)
            if fair <= 1:
                p = float(item.get("probability") or 0)
                fair = 1 / p if p > 0 else 1.0
            odds *= fair
    return odds, complete


def _joint_probability(items: tuple[dict[str, Any], dict[str, Any]], correlation: float) -> float:
    """Joint probability adjusted by V14 market dependency correlation."""
    p1, p2 = (float(x.get("probability") or 0) for x in items)
    independent = p1 * p2
    corr = max(-0.95, min(0.95, float(correlation)))
    if corr >= 0:
        lift = min(p1, p2) - independent
        joint = independent + lift * corr * 0.38
    else:
        joint = independent * (1.0 + corr * 0.30)
    return max(0.0, min(0.95, joint))


def _quality_tier(score: float) -> tuple[str, str, int]:
    if score >= 90:
        return "ELITE_BUILDER", "Elite Builder", 5
    if score >= 82:
        return "STRONG_BUILDER", "Strong Builder", 4
    if score >= 74:
        return "STANDARD_BUILDER", "Standard Builder", 3
    if score >= 66:
        return "EXPERIMENTAL_BUILDER", "Experimental Builder", 2
    return "HIGH_RISK_BUILDER", "High Risk Builder", 1


def _risk(score: float, probability: float) -> str:
    if score >= 88 and probability >= 0.62:
        return "LOW"
    if score >= 78 and probability >= 0.52:
        return "LOW-MEDIUM"
    if score >= 68:
        return "MEDIUM"
    return "HIGH"


def _validate_template(template: BuilderTemplate, market_by_key: dict[str, dict[str, Any]]) -> tuple[bool, str]:
    if any(key in HANDICAP_MARKETS for key in template.legs):
        return False, "HANDICAP_NOT_ALLOWED_IN_BUILDER"
    if any(key not in SPORTSBOOK_BUILDER_MARKETS for key in template.legs):
        return False, "SPORTSBOOK_MARKET_NOT_SUPPORTED"
    if any(key not in market_by_key for key in template.legs):
        return False, "MARKET_NOT_AVAILABLE"
    dependency = builder_correlation(template.legs[0], template.legs[1])
    if not dependency.get("allowed"):
        return False, f"DEPENDENCY_REJECT:{dependency.get('kind')}:{dependency.get('reason')}"
    for idx, key in enumerate(template.legs):
        p = float(market_by_key[key].get("probability") or 0)
        if p < template.min_probabilities[idx]:
            return False, f"ACTIVATION_THRESHOLD:{key}:{p:.3f}<{template.min_probabilities[idx]:.3f}"
    return True, "PASS"


def _builder_row(
    template: BuilderTemplate,
    items: tuple[dict[str, Any], dict[str, Any]],
    *,
    data_quality: float,
    model_agreement: float,
    evidence_score: float,
    selected_pick_key: str,
) -> dict[str, Any]:
    dependency = builder_correlation(template.legs[0], template.legs[1])
    corr_value = float(dependency.get("correlation") or 0.0)
    probability = _joint_probability(items, corr_value)
    combined_odds, complete_odds = _offered_odds(items)
    ev = probability * combined_odds - 1 if complete_odds else None
    fair_odds = round(1 / probability, 2) if probability > 0 else None
    direct = selected_pick_key in template.legs if selected_pick_key else False

    # Correlation quality rewards useful scenario linkage without redundancy.
    correlation = max(0.0, min(100.0, 100.0 - abs(corr_value - 0.45) * 70.0))
    if corr_value < 0:
        correlation = max(0.0, correlation - abs(corr_value) * 45.0)
    value_score = 55.0 if ev is None else max(0.0, min(100.0, 55.0 + ev * 220.0))
    reliability_component = max(0.0, min(100.0, (data_quality * 0.55 + model_agreement * 0.45)))
    quality = (
        correlation * 0.25
        + value_score * 0.20
        + reliability_component * 0.20
        + evidence_score * 0.20
        + data_quality * 0.15
    )
    if direct:
        quality += 3.0
    quality = round(max(0.0, min(100.0, quality)), 1)
    status, display_status, stars = _quality_tier(quality)
    risk = _risk(quality, probability)

    ordered = tuple(sorted(items, key=lambda x: DISPLAY_PRIORITY.get(str(x.get("key")), 999)))
    labels = [_label(x) for x in ordered]
    leg_reasons = [
        f"{_label(x)} memiliki probabilitas model {float(x.get('probability') or 0)*100:.1f}%"
        + (f" dan odds {float(x.get('odds')):.2f}." if x.get("odds") else ".")
        for x in ordered
    ]
    return {
        "template_code": template.code,
        "template_name": template.dna,
        "builder_dna": template.dna,
        "selections": list(ordered),
        "combined_label": " + ".join(labels),
        "probability": round(probability, 4),
        "probability_pct": round(probability * 100, 1),
        "combined_odds": round(combined_odds, 2),
        "fair_odds": fair_odds,
        "complete_odds": complete_odds,
        "ev": None if ev is None else round(ev, 4),
        "builder_quality": quality,
        "correlation_score": round(correlation, 1),
        "correlation_coefficient": round(corr_value, 3),
        "correlation_kind": dependency.get("kind"),
        "correlation_reason": dependency.get("reason"),
        "correlation": "PASS",
        "risk": risk,
        "status": status,
        "display_status": display_status,
        "stars": stars,
        "scenario": template.scenario,
        "supports_selected_pick": direct,
        "alignment": "DIRECT" if direct else "CONTEXTUAL",
        "selected_pick_key": selected_pick_key,
        "leg_reasons": leg_reasons,
        "compatibility_reason": f"Kedua leg termasuk market Bet Builder umum dan lolos V14 dependency check ({dependency.get('kind')}, corr {corr_value:+.2f}).",
        "narrative": f"Builder DNA {template.dna}. {template.scenario} Probabilitas gabungan {probability*100:.1f}% dengan kualitas {quality}/100.",
    }


def generate(
    market_rows: list[dict[str, Any]], *, data_quality: float = 70.0,
    model_agreement: float = 70.0, evidence_score: float = 70.0,
    selected_pick_key: str = "",
) -> dict[str, Any]:
    market_by_key = _market_map(market_rows)
    diagnostics: dict[str, Any] = {
        "market_rows": len(market_rows),
        "sportsbook_markets": len([k for k in market_by_key if k in SPORTSBOOK_BUILDER_MARKETS]),
        "templates_total": len(BUILDER_TEMPLATES),
        "templates_evaluated": 0,
        "rejected_market_unavailable": 0,
        "rejected_activation_threshold": 0,
        "rejected_sportsbook_compatibility": 0,
        "rejected_quality_gate": 0,
        "rejected_negative_ev": 0,
        "qualified_pairs": 0,
        "portfolio_size": 0,
        "available_keys": sorted(k for k in market_by_key if k in SPORTSBOOK_BUILDER_MARKETS),
        "handicap_keys_excluded": sorted(k for k in market_by_key if k in HANDICAP_MARKETS),
        "rejections": [],
    }
    candidates: list[dict[str, Any]] = []

    for template in BUILDER_TEMPLATES:
        diagnostics["templates_evaluated"] += 1
        valid, reason = _validate_template(template, market_by_key)
        if not valid:
            if reason == "MARKET_NOT_AVAILABLE":
                diagnostics["rejected_market_unavailable"] += 1
            elif reason.startswith("ACTIVATION_THRESHOLD"):
                diagnostics["rejected_activation_threshold"] += 1
            else:
                diagnostics["rejected_sportsbook_compatibility"] += 1
            if len(diagnostics["rejections"]) < 12:
                diagnostics["rejections"].append({"template": template.code, "reason": reason})
            continue

        items = (market_by_key[template.legs[0]], market_by_key[template.legs[1]])
        row = _builder_row(
            template, items, data_quality=data_quality, model_agreement=model_agreement,
            evidence_score=evidence_score, selected_pick_key=selected_pick_key,
        )
        if data_quality < 65 or model_agreement < 62 or evidence_score < 58 or row["builder_quality"] < 66:
            diagnostics["rejected_quality_gate"] += 1
            continue
        if row["ev"] is not None and float(row["ev"]) < -0.08:
            diagnostics["rejected_negative_ev"] += 1
            continue
        candidates.append(row)

    # Direct Selected Pick alignment first, then builder quality and probability.
    candidates.sort(
        key=lambda r: (
            bool(r.get("supports_selected_pick")),
            float(r.get("builder_quality") or 0),
            float(r.get("ev") or -999) if r.get("ev") is not None else -0.01,
            float(r.get("probability") or 0),
            next((t.priority for t in BUILDER_TEMPLATES if t.code == r.get("template_code")), 0),
        ), reverse=True,
    )

    # Portfolio max 3 and avoid duplicate football DNA / exact pair.
    portfolio: list[dict[str, Any]] = []
    seen_pairs: set[frozenset[str]] = set()
    seen_dna: set[str] = set()
    for row in candidates:
        pair = frozenset(str(x.get("key")) for x in row.get("selections", []))
        dna = str(row.get("builder_dna") or "")
        if pair in seen_pairs or dna in seen_dna:
            continue
        portfolio.append(dict(row))
        seen_pairs.add(pair)
        seen_dna.add(dna)
        if len(portfolio) == 3:
            break

    labels = ("ELITE", "SAFE", "VALUE")
    for idx, row in enumerate(portfolio):
        row["portfolio_rank"] = idx + 1
        row["portfolio_role"] = labels[idx]
        row["portfolio_label"] = f"{labels[idx]} BUILDER"

    diagnostics["qualified_pairs"] = len(candidates)
    diagnostics["portfolio_size"] = len(portfolio)
    output: dict[str, Any] = {
        "_portfolio": portfolio,
        "_diagnostics": diagnostics,
        "safe": portfolio[0] if portfolio else None,
        "balanced": portfolio[1] if len(portfolio) > 1 else None,
        "aggressive": portfolio[2] if len(portfolio) > 2 else None,
    }
    return output


def select_builder_portfolio(
    builders: dict[str, Any], *, data_quality: float, model_agreement: float,
    selected_pick_key: str = "", evidence_score: float = 50.0,
) -> list[dict[str, Any]]:
    # generate() already applies the full gate. Keep signature compatible with
    # the old selector and protect public publishing with the final quality gate.
    if data_quality < 65 or model_agreement < 62 or evidence_score < 58:
        return []
    return [dict(x) for x in builders.get("_portfolio", []) if isinstance(x, dict)]


def select_best_builder(
    builders: dict[str, Any], *, data_quality: float, model_agreement: float,
    selected_pick_key: str = "", evidence_score: float = 50.0,
) -> dict[str, Any] | None:
    portfolio = select_builder_portfolio(
        builders, data_quality=data_quality, model_agreement=model_agreement,
        selected_pick_key=selected_pick_key, evidence_score=evidence_score,
    )
    return portfolio[0] if portfolio else None
