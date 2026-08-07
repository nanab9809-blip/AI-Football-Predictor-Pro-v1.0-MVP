from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Relationship:
    kind: str
    strength: float
    note: str


# Directional implications. If A occurs, B must also occur.
IMPLICATIONS: dict[str, tuple[str, ...]] = {
    "HOME_WIN": ("HOME_OR_DRAW", "HOME_OR_AWAY", "AH_HOME_M0_5"),
    "AWAY_WIN": ("AWAY_OR_DRAW", "HOME_OR_AWAY", "AH_AWAY_M0_5"),
    "OVER_3_5": ("OVER_2_5", "OVER_1_5"),
    "OVER_2_5": ("OVER_1_5",),
    "UNDER_1_5": ("UNDER_2_5", "UNDER_3_5"),
    "UNDER_2_5": ("UNDER_3_5",),
}

# True logical conflicts, not merely weak correlations.
EXCLUSIONS: set[frozenset[str]] = {
    frozenset(("HOME_WIN", "DRAW")),
    frozenset(("HOME_WIN", "AWAY_WIN")),
    frozenset(("DRAW", "AWAY_WIN")),
    frozenset(("HOME_OR_DRAW", "AWAY_WIN")),
    frozenset(("AWAY_OR_DRAW", "HOME_WIN")),
    frozenset(("BTTS_YES", "BTTS_NO")),
    frozenset(("OVER_1_5", "UNDER_1_5")),
    frozenset(("OVER_2_5", "UNDER_2_5")),
    frozenset(("OVER_3_5", "UNDER_3_5")),
}

# Football-context correlations used for ranking and builder joint probability.
# Positive values mean the events tend to reinforce the same scenario;
# negative values mean scenario tension. These are priors, not learned truth.
CORRELATIONS: dict[frozenset[str], float] = {
    frozenset(("HOME_WIN", "HOME_OR_DRAW")): 0.94,
    frozenset(("AWAY_WIN", "AWAY_OR_DRAW")): 0.94,
    frozenset(("OVER_2_5", "OVER_3_5")): 0.88,
    frozenset(("UNDER_2_5", "UNDER_3_5")): 0.88,
    frozenset(("BTTS_YES", "OVER_2_5")): 0.76,
    frozenset(("BTTS_NO", "UNDER_3_5")): 0.70,
    frozenset(("DRAW", "UNDER_3_5")): 0.63,
    frozenset(("HOME_WIN", "BTTS_NO")): 0.55,
    frozenset(("AWAY_WIN", "BTTS_NO")): 0.55,
    frozenset(("HOME_WIN", "UNDER_3_5")): 0.38,
    frozenset(("AWAY_WIN", "UNDER_3_5")): 0.38,
    frozenset(("HOME_OR_DRAW", "UNDER_3_5")): 0.46,
    frozenset(("AWAY_OR_DRAW", "UNDER_3_5")): 0.46,
    frozenset(("HOME_WIN", "OVER_2_5")): 0.42,
    frozenset(("AWAY_WIN", "OVER_2_5")): 0.42,
    frozenset(("BTTS_NO", "OVER_2_5")): -0.35,
    frozenset(("BTTS_YES", "UNDER_2_5")): -0.48,
    frozenset(("BTTS_YES", "UNDER_3_5")): -0.15,
}


def relation(a: str, b: str) -> Relationship:
    a, b = str(a or ""), str(b or "")
    if not a or not b:
        return Relationship("NONE", 0.0, "Market tidak tersedia.")
    if a == b:
        return Relationship("IDENTICAL", 1.0, "Market identik.")
    pair = frozenset((a, b))
    if pair in EXCLUSIONS:
        return Relationship("EXCLUSIVE", -1.0, "Kedua market tidak dapat menang bersamaan.")
    if b in IMPLICATIONS.get(a, ()):
        return Relationship("IMPLIES", 1.0, f"{a} mengimplikasikan {b}.")
    if a in IMPLICATIONS.get(b, ()):
        return Relationship("IMPLIED_BY", 1.0, f"{b} mengimplikasikan {a}.")
    corr = CORRELATIONS.get(pair)
    if corr is not None:
        return Relationship("CORRELATED", corr, f"Prior korelasi skenario {corr:+.2f}.")
    return Relationship("NEUTRAL", 0.0, "Tidak ada dependency kuat yang didefinisikan.")


def builder_correlation(a: str, b: str, default: float = 0.35) -> dict[str, Any]:
    rel = relation(a, b)
    if rel.kind in {"EXCLUSIVE", "IDENTICAL"}:
        return {"allowed": False, "correlation": 1.0, "kind": rel.kind, "reason": rel.note}
    if rel.kind in {"IMPLIES", "IMPLIED_BY"}:
        # Redundant legs are mathematically valid but poor Bet Builder choices.
        return {"allowed": False, "correlation": 0.98, "kind": "REDUNDANT", "reason": rel.note}
    corr = rel.strength if rel.kind == "CORRELATED" else default
    return {
        "allowed": True,
        "correlation": max(-0.95, min(0.95, float(corr))),
        "kind": rel.kind,
        "reason": rel.note,
    }


def relationship_score(market: dict[str, Any], all_markets: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure whether a market is coherent with related model probabilities.

    This does not reward redundancy. It penalizes logical inconsistencies, e.g.
    Home Win being assigned a higher probability than Home-or-Draw, or Over 3.5
    being higher than Over 2.5. It also records the strongest competitor conflict.
    """
    key = str(market.get("key") or "")
    p = _num(market.get("calibrated_probability", market.get("probability")))
    by_key = {str(x.get("key") or ""): x for x in all_markets}
    penalty = 0.0
    notes: list[str] = []

    for implied in IMPLICATIONS.get(key, ()):
        other = by_key.get(implied)
        if not other:
            continue
        op = _num(other.get("calibrated_probability", other.get("probability")))
        if p > op + 0.015:
            gap = p - op
            penalty += min(24.0, gap * 160.0)
            notes.append(f"Inconsistency: {key} {p*100:.1f}% > implied {implied} {op*100:.1f}%.")

    # If another market implies this one, this market should not be lower than it.
    for source, implieds in IMPLICATIONS.items():
        if key not in implieds:
            continue
        other = by_key.get(source)
        if not other:
            continue
        op = _num(other.get("calibrated_probability", other.get("probability")))
        if op > p + 0.015:
            gap = op - p
            penalty += min(24.0, gap * 160.0)
            notes.append(f"Inconsistency: source {source} {op*100:.1f}% > {key} {p*100:.1f}%.")

    # Competition awareness: a mutually exclusive market with materially higher
    # probability weakens this candidate's relationship score.
    strongest_conflict: tuple[str, float] | None = None
    for other_key, other in by_key.items():
        if other_key == key or frozenset((key, other_key)) not in EXCLUSIONS:
            continue
        op = _num(other.get("calibrated_probability", other.get("probability")))
        if op > p and (strongest_conflict is None or op > strongest_conflict[1]):
            strongest_conflict = (other_key, op)
    if strongest_conflict:
        gap = strongest_conflict[1] - p
        penalty += min(18.0, gap * 65.0)
        notes.append(f"Exclusive competitor {strongest_conflict[0]} lebih kuat ({strongest_conflict[1]*100:.1f}%).")

    score = max(0.0, min(100.0, 100.0 - penalty))
    if not notes:
        notes.append("Dependency market konsisten dengan probabilitas model.")
    return {"score": round(score, 2), "penalty": round(penalty, 2), "notes": notes}
