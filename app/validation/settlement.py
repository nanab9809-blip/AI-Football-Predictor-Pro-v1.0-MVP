from __future__ import annotations

from typing import Any

FINAL_STATUSES = {"FT", "AET", "PEN", "AWD", "WO"}
VOID_STATUSES = {"CANC", "ABD", "SUSP", "INT"}
UPCOMING_STATUSES = {"NS", "TBD"}


def normalize_market_key(market_key: str | None) -> str:
    """Normalize stored labels/legacy aliases into the canonical settlement key."""
    raw = str(market_key or "").strip().upper()
    normalized = "_".join(raw.replace("/", " ").replace("-", " ").replace(".", " ").split())
    aliases = {
        "1": "HOME_WIN", "HOME": "HOME_WIN", "HOME_WIN": "HOME_WIN",
        "X": "DRAW", "DRAW": "DRAW",
        "2": "AWAY_WIN", "AWAY": "AWAY_WIN", "AWAY_WIN": "AWAY_WIN",
        "1X": "HOME_OR_DRAW", "HOME_OR_DRAW": "HOME_OR_DRAW", "HOME_DRAW": "HOME_OR_DRAW",
        "X2": "AWAY_OR_DRAW", "AWAY_OR_DRAW": "AWAY_OR_DRAW", "AWAY_DRAW": "AWAY_OR_DRAW",
        "OVER_15": "OVER_1_5", "OVER_1_5": "OVER_1_5",
        "UNDER_15": "UNDER_1_5", "UNDER_1_5": "UNDER_1_5",
        "OVER_25": "OVER_2_5", "OVER_2_5": "OVER_2_5",
        "UNDER_25": "UNDER_2_5", "UNDER_2_5": "UNDER_2_5",
        "OVER_35": "OVER_3_5", "OVER_3_5": "OVER_3_5",
        "UNDER_35": "UNDER_3_5", "UNDER_3_5": "UNDER_3_5",
        "BTTS_YES": "BTTS_YES", "BTTS": "BTTS_YES", "BOTH_TEAMS_TO_SCORE_YES": "BTTS_YES",
        "BTTS_NO": "BTTS_NO", "BOTH_TEAMS_TO_SCORE_NO": "BTTS_NO",
        "HOME_OVER_05": "HOME_OVER_0_5", "HOME_OVER_0_5": "HOME_OVER_0_5",
        "AWAY_OVER_05": "AWAY_OVER_0_5", "AWAY_OVER_0_5": "AWAY_OVER_0_5",
        "HOME_UNDER_25": "HOME_UNDER_2_5", "HOME_UNDER_2_5": "HOME_UNDER_2_5",
        "AWAY_UNDER_25": "AWAY_UNDER_2_5", "AWAY_UNDER_2_5": "AWAY_UNDER_2_5",

        "HOME_WINNER": "HOME_WIN", "HOME_TEAM_TO_WIN": "HOME_WIN",
        "AWAY_WINNER": "AWAY_WIN", "AWAY_TEAM_TO_WIN": "AWAY_WIN",
        "HOME_WIN_OR_DRAW": "HOME_OR_DRAW", "DOUBLE_CHANCE_HOME_OR_DRAW": "HOME_OR_DRAW",
        "AWAY_WIN_OR_DRAW": "AWAY_OR_DRAW", "DOUBLE_CHANCE_AWAY_OR_DRAW": "AWAY_OR_DRAW",
        "OVER_1_5_GOALS": "OVER_1_5", "TOTAL_OVER_1_5": "OVER_1_5",
        "UNDER_1_5_GOALS": "UNDER_1_5", "TOTAL_UNDER_1_5": "UNDER_1_5",
        "OVER_2_5_GOALS": "OVER_2_5", "TOTAL_OVER_2_5": "OVER_2_5",
        "UNDER_2_5_GOALS": "UNDER_2_5", "TOTAL_UNDER_2_5": "UNDER_2_5",
        "OVER_3_5_GOALS": "OVER_3_5", "TOTAL_OVER_3_5": "OVER_3_5",
        "UNDER_3_5_GOALS": "UNDER_3_5", "TOTAL_UNDER_3_5": "UNDER_3_5",
        "BOTH_TEAMS_TO_SCORE": "BTTS_YES", "BOTH_TEAMS_TO_SCORE_YES": "BTTS_YES",
        "BOTH_TEAMS_TO_SCORE_NO": "BTTS_NO",
        "HOME_OVER_0_5_GOALS": "HOME_OVER_0_5", "HOME_TEAM_OVER_0_5": "HOME_OVER_0_5",
        "AWAY_OVER_0_5_GOALS": "AWAY_OVER_0_5", "AWAY_TEAM_OVER_0_5": "AWAY_OVER_0_5",
        "HOME_UNDER_2_5_GOALS": "HOME_UNDER_2_5", "HOME_TEAM_UNDER_2_5": "HOME_UNDER_2_5",
        "AWAY_UNDER_2_5_GOALS": "AWAY_UNDER_2_5", "AWAY_TEAM_UNDER_2_5": "AWAY_UNDER_2_5",
        "ASIAN_HANDICAP_HOME_0_5": "AH_HOME_M0_5", "AH_HOME_M0_5": "AH_HOME_M0_5",
        "ASIAN_HANDICAP_AWAY_0_5": "AH_AWAY_M0_5", "AH_AWAY_M0_5": "AH_AWAY_M0_5",
        "HOME_DRAW_NO_BET": "HOME_DNB", "HOME_DNB": "HOME_DNB",
        "AWAY_DRAW_NO_BET": "AWAY_DNB", "AWAY_DNB": "AWAY_DNB",
    }
    return aliases.get(normalized, normalized)


def settle_market(market_key: str, home_goals: int, away_goals: int) -> str | None:
    """Return WIN/LOSS for a supported market; None means unsupported, never fake VOID."""
    total = home_goals + away_goals
    key = normalize_market_key(market_key)

    if key == "HOME_DNB":
        if home_goals == away_goals:
            return "VOID"
        return "WIN" if home_goals > away_goals else "LOSS"
    if key == "AWAY_DNB":
        if home_goals == away_goals:
            return "VOID"
        return "WIN" if away_goals > home_goals else "LOSS"

    outcomes: dict[str, bool] = {
        "HOME_WIN": home_goals > away_goals,
        "DRAW": home_goals == away_goals,
        "AWAY_WIN": away_goals > home_goals,
        "HOME_OR_DRAW": home_goals >= away_goals,
        "AWAY_OR_DRAW": away_goals >= home_goals,
        "HOME_OR_AWAY": home_goals != away_goals,
        "AH_HOME_M0_5": home_goals > away_goals,
        "AH_AWAY_M0_5": away_goals > home_goals,
        "OVER_1_5": total > 1.5,
        "UNDER_1_5": total < 1.5,
        "OVER_2_5": total > 2.5,
        "UNDER_2_5": total < 2.5,
        "OVER_3_5": total > 3.5,
        "UNDER_3_5": total < 3.5,
        "BTTS_YES": home_goals > 0 and away_goals > 0,
        "BTTS_NO": home_goals == 0 or away_goals == 0,
        "HOME_OVER_0_5": home_goals > 0,
        "AWAY_OVER_0_5": away_goals > 0,
        "HOME_UNDER_2_5": home_goals < 2.5,
        "AWAY_UNDER_2_5": away_goals < 2.5,
    }
    if key not in outcomes:
        return None
    return "WIN" if outcomes[key] else "LOSS"


def fixture_score(fixture: dict[str, Any]) -> tuple[int | None, int | None]:
    goals = fixture.get("goals") or {}
    home = goals.get("home")
    away = goals.get("away")
    try:
        return int(home), int(away)
    except (TypeError, ValueError):
        return None, None
