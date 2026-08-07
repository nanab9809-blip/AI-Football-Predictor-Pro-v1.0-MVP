from __future__ import annotations

from typing import Any

DEFAULT_WEIGHTS = {"poisson": .38, "elo": .20, "form": .22, "api": .20}


def adaptive_weights(history: list[dict[str, Any]], league: str | None = None) -> dict[str, float]:
    """Return conservative adaptive weights.

    The database currently stores final-pick outcomes, not per-model outcomes. Until at least
    200 settled samples with model diagnostics exist, stable default weights are intentionally used.
    """
    settled = [x for x in history if x.get("result") in {"WIN", "LOSS"} and (not league or x.get("league") == league)]
    if len(settled) < 200:
        return dict(DEFAULT_WEIGHTS)
    hit_rate = sum(x.get("result") == "WIN" for x in settled) / len(settled)
    shift = max(-.04, min(.04, (hit_rate-.55)*.2))
    weights = dict(DEFAULT_WEIGHTS)
    weights["poisson"] -= shift/2; weights["form"] += shift; weights["api"] -= shift/2
    total = sum(weights.values())
    return {k: round(v/total, 4) for k, v in weights.items()}
