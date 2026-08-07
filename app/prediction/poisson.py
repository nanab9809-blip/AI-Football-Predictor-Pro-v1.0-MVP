from __future__ import annotations

import math
from typing import Any


def poisson(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def build_markets(home_xg: float, away_xg: float, max_goals: int = 8) -> dict[str, float]:
    matrix = [[poisson(h, home_xg) * poisson(a, away_xg) for a in range(max_goals + 1)] for h in range(max_goals + 1)]
    home = sum(matrix[h][a] for h in range(max_goals + 1) for a in range(max_goals + 1) if h > a)
    draw = sum(matrix[h][h] for h in range(max_goals + 1))
    away = sum(matrix[h][a] for h in range(max_goals + 1) for a in range(max_goals + 1) if h < a)
    total_mass = home + draw + away
    home, draw, away = home / total_mass, draw / total_mass, away / total_mass
    total = home_xg + away_xg
    under_15 = sum(poisson(k, total) for k in range(0, 2))
    under_25 = sum(poisson(k, total) for k in range(0, 3))
    under_35 = sum(poisson(k, total) for k in range(0, 4))
    btts_no = math.exp(-home_xg) + math.exp(-away_xg) - math.exp(-(home_xg + away_xg))
    return {
        "HOME_WIN": home, "DRAW": draw, "AWAY_WIN": away,
        "HOME_OR_DRAW": home + draw, "AWAY_OR_DRAW": away + draw, "HOME_OR_AWAY": home + away,
        # Asian Handicap remains a single-market family; never a Builder leg.
        "AH_HOME_M0_5": home, "AH_AWAY_M0_5": away,
        "AH_HOME_P0_5": home + draw, "AH_AWAY_P0_5": away + draw,
        "HOME_DNB": home / (home + away) if (home + away) else 0.5,
        "AWAY_DNB": away / (home + away) if (home + away) else 0.5,
        "OVER_1_5": 1-under_15, "UNDER_1_5": under_15,
        "OVER_2_5": 1-under_25, "UNDER_2_5": under_25,
        "OVER_3_5": 1-under_35, "UNDER_3_5": under_35,
        "BTTS_YES": 1-btts_no, "BTTS_NO": btts_no,
        "HOME_OVER_0_5": 1-math.exp(-home_xg), "AWAY_OVER_0_5": 1-math.exp(-away_xg),
        "HOME_UNDER_2_5": sum(poisson(k, home_xg) for k in range(3)),
        "AWAY_UNDER_2_5": sum(poisson(k, away_xg) for k in range(3)),
    }


def likely_scores(home_xg: float, away_xg: float, limit: int = 3) -> list[dict[str, Any]]:
    values = []
    for h in range(6):
        for a in range(6):
            values.append({"score": f"{h}-{a}", "probability": poisson(h, home_xg) * poisson(a, away_xg)})
    return sorted(values, key=lambda x: x["probability"], reverse=True)[:limit]
