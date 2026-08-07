from __future__ import annotations

from typing import Any


def no_vig_probabilities(odds: dict[str, float]) -> dict[str, float]:
    raw = {k: 1/v for k, v in odds.items() if v and v > 1}
    total = sum(raw.values()) or 1.0
    return {k: v/total for k, v in raw.items()}


def bookmaker_margin(odds: dict[str, float]) -> float | None:
    vals = [1/v for v in odds.values() if v and v > 1]
    return round(sum(vals)-1, 4) if vals else None


def fractional_kelly(probability: float, odds: float | None, fraction: float = .25) -> float | None:
    if not odds or odds <= 1:
        return None
    b = odds - 1
    raw = (b*probability - (1-probability))/b
    return round(max(0.0, raw*fraction), 4)


def enrich_professional(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    one_x_two = {r["key"]: r["odds"] for r in rows if r["key"] in {"HOME_WIN","DRAW","AWAY_WIN"} and r.get("odds")}
    no_vig = no_vig_probabilities(one_x_two)
    margin = bookmaker_margin(one_x_two)
    for row in rows:
        row["market_implied_probability"] = round(1/row["odds"], 4) if row.get("odds") else None
        row["no_vig_probability"] = round(no_vig.get(row["key"], 0), 4) if row["key"] in no_vig else None
        benchmark = row["no_vig_probability"] if row["no_vig_probability"] is not None else row["market_implied_probability"]
        row["edge"] = round(row["probability"]-benchmark, 4) if benchmark is not None else None
        row["kelly_quarter"] = fractional_kelly(row["probability"], row.get("odds"), .25)
        row["bookmaker_margin"] = margin
        row["value_status"] = "VALUE" if row.get("ev") is not None and row["ev"] >= .03 and (row.get("edge") or 0) >= .02 else "NEUTRAL"
    return rows
