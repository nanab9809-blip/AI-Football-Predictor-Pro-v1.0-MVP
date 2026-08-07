from __future__ import annotations

from typing import Any

MARKET_MAP = {
    ("Match Winner", "Home"): "HOME_WIN", ("Match Winner", "Draw"): "DRAW", ("Match Winner", "Away"): "AWAY_WIN",
    ("Goals Over/Under", "Over 1.5"): "OVER_1_5", ("Goals Over/Under", "Under 1.5"): "UNDER_1_5",
    ("Goals Over/Under", "Over 2.5"): "OVER_2_5", ("Goals Over/Under", "Under 2.5"): "UNDER_2_5",
    ("Goals Over/Under", "Over 3.5"): "OVER_3_5", ("Goals Over/Under", "Under 3.5"): "UNDER_3_5", ("Both Teams Score", "Yes"): "BTTS_YES",
    ("Both Teams Score", "No"): "BTTS_NO", ("Double Chance", "Home/Draw"): "HOME_OR_DRAW",
    ("Double Chance", "Draw/Away"): "AWAY_OR_DRAW", ("Double Chance", "Home/Away"): "HOME_OR_AWAY",
    ("Asian Handicap", "Home -0.5"): "AH_HOME_M0_5", ("Asian Handicap", "Away -0.5"): "AH_AWAY_M0_5",
    ("Asian Handicap", "Home 0"): "HOME_DNB", ("Asian Handicap", "Away 0"): "AWAY_DNB",
}


def extract(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for fixture in payload.get("response", []):
        for bookmaker in fixture.get("bookmakers", []):
            for bet in bookmaker.get("bets", []):
                bet_name = bet.get("name")
                for value in bet.get("values", []):
                    key = MARKET_MAP.get((bet_name, value.get("value")))
                    if key and key not in result:
                        try:
                            odds = float(value.get("odd"))
                        except (TypeError, ValueError):
                            continue
                        result[key] = {"odds": odds, "bookmaker": bookmaker.get("name", "-")}
    return result


def enrich(markets: dict[str, float], odds: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for key, probability in markets.items():
        fair = 1/probability if probability > 0 else 0
        offered = odds.get(key, {}).get("odds")
        ev = probability * offered - 1 if offered else None
        rows.append({
            "key": key, "label": {
                "HOME_WIN":"Home Win","DRAW":"Draw","AWAY_WIN":"Away Win",
                "HOME_OR_DRAW":"Home or Draw","AWAY_OR_DRAW":"Away or Draw","HOME_OR_AWAY":"Home or Away",
                "OVER_1_5":"Over 1.5 Goals","UNDER_1_5":"Under 1.5 Goals",
                "OVER_2_5":"Over 2.5 Goals","UNDER_2_5":"Under 2.5 Goals",
                "OVER_3_5":"Over 3.5 Goals","UNDER_3_5":"Under 3.5 Goals",
                "BTTS_YES":"BTTS Yes","BTTS_NO":"BTTS No",
                "AH_HOME_M0_5":"Asian Handicap Home -0.5","AH_AWAY_M0_5":"Asian Handicap Away -0.5",
                "AH_HOME_P0_5":"Asian Handicap Home +0.5","AH_AWAY_P0_5":"Asian Handicap Away +0.5",
                "HOME_DNB":"Home Draw No Bet","AWAY_DNB":"Away Draw No Bet",
            }.get(key, key.replace("_", " ").title()), "probability": probability,
            "probability_pct": round(probability*100, 1), "fair_odds": round(fair, 2),
            "odds": offered, "bookmaker": odds.get(key, {}).get("bookmaker"),
            "ev": round(ev, 3) if ev is not None else None,
        })
    return sorted(rows, key=lambda x: ((x["ev"] if x["ev"] is not None else -99), x["probability"]), reverse=True)
