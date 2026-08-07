from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class TeamFeatures:
    matches: int
    ppg: float
    goals_for: float
    goals_against: float
    goal_difference: float
    win_rate: float
    draw_rate: float
    loss_rate: float
    clean_sheet_rate: float
    failed_to_score_rate: float
    btts_rate: float
    over_25_rate: float
    momentum: float
    attack_rating: float
    defense_rating: float
    form_sequence: str
    current_streak_type: str
    current_streak_length: int
    unbeaten_streak: int
    scoring_streak: int
    clean_sheet_streak: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _streak(sequence: list[str]) -> tuple[str, int]:
    if not sequence:
        return "-", 0
    first = sequence[0]
    length = 0
    for result in sequence:
        if result != first:
            break
        length += 1
    return first, length


def team_features(fixtures: list[dict[str, Any]], team_id: int, *, home_only: bool = False, away_only: bool = False) -> TeamFeatures:
    # API responses are normally newest first. Only the latest ten completed matches
    # are allowed to influence form and streak calculations.
    points: list[int] = []
    gf: list[float] = []
    ga: list[float] = []
    sequence: list[str] = []
    wins = draws = losses = clean = failed = btts = over25 = 0
    weighted_points = weighted_total = 0.0

    for index, item in enumerate(fixtures):
        if len(points) >= 10:
            break
        home = item.get("teams", {}).get("home", {})
        away = item.get("teams", {}).get("away", {})
        goals = item.get("goals", {})
        if goals.get("home") is None or goals.get("away") is None:
            continue
        is_home = home.get("id") == team_id
        if home_only and not is_home:
            continue
        if away_only and is_home:
            continue
        scored = _safe_float(goals.get("home") if is_home else goals.get("away"))
        conceded = _safe_float(goals.get("away") if is_home else goals.get("home"))
        result_points = 3 if scored > conceded else 1 if scored == conceded else 0
        result_code = "W" if result_points == 3 else "D" if result_points == 1 else "L"
        sequence.append(result_code)
        points.append(result_points)
        gf.append(scored)
        ga.append(conceded)
        wins += result_points == 3
        draws += result_points == 1
        losses += result_points == 0
        clean += conceded == 0
        failed += scored == 0
        btts += scored > 0 and conceded > 0
        over25 += scored + conceded > 2.5
        weight = max(0.35, 1.0 - index * 0.07)
        weighted_points += result_points * weight
        weighted_total += 3 * weight

    n = len(points)
    if not n:
        return TeamFeatures(
            0, 1.35, 1.25, 1.25, 0.0, .33, .30, .37, .25, .22,
            .48, .48, .50, 50.0, 50.0, "", "-", 0, 0, 0, 0,
        )

    current_type, current_length = _streak(sequence)
    unbeaten = 0
    scoring = 0
    clean_streak = 0
    for p in points:
        if p == 0:
            break
        unbeaten += 1
    for value in gf:
        if value <= 0:
            break
        scoring += 1
    for value in ga:
        if value != 0:
            break
        clean_streak += 1

    avg_gf = sum(gf) / n
    avg_ga = sum(ga) / n
    attack = max(0.0, min(100.0, 50 + (avg_gf - 1.25) * 22 + (sum(points)/(3*n)-.45)*18))
    defense = max(0.0, min(100.0, 50 + (1.25 - avg_ga) * 22 + (clean/n-.25)*20))
    return TeamFeatures(
        n, sum(points)/n, avg_gf, avg_ga, avg_gf-avg_ga,
        wins/n, draws/n, losses/n, clean/n, failed/n, btts/n, over25/n,
        weighted_points/weighted_total if weighted_total else .5,
        attack, defense, "".join(sequence), current_type, current_length,
        unbeaten, scoring, clean_streak,
    )


def h2h_features(fixtures: list[dict[str, Any]], home_id: int, away_id: int) -> dict[str, Any]:
    # Recent H2H receives more weight and the sample is capped at ten.
    weighted_home_points = weighted_total = weighted_goals = weighted_btts = weighted_over25 = 0.0
    count = 0
    sequence: list[str] = []
    over_sequence: list[bool] = []
    btts_sequence: list[bool] = []

    for index, item in enumerate(fixtures):
        if count >= 10:
            break
        goals = item.get("goals", {})
        if goals.get("home") is None or goals.get("away") is None:
            continue
        teams = item.get("teams", {})
        fixture_home_id = teams.get("home", {}).get("id")
        gh = _safe_float(goals.get("home"))
        ga = _safe_float(goals.get("away"))
        if fixture_home_id == home_id:
            hs, aas = gh, ga
        else:
            hs, aas = ga, gh
        points = 3 if hs > aas else 1 if hs == aas else 0
        sequence.append("H" if points == 3 else "D" if points == 1 else "A")
        is_btts = hs > 0 and aas > 0
        is_over = hs + aas > 2.5
        btts_sequence.append(is_btts)
        over_sequence.append(is_over)
        weight = max(0.40, 1.0 - index * 0.08)
        weighted_home_points += points * weight
        weighted_goals += (hs + aas) * weight
        weighted_btts += float(is_btts) * weight
        weighted_over25 += float(is_over) * weight
        weighted_total += weight
        count += 1

    streak_type, streak_length = _streak(sequence)
    over_streak = 0
    for value in over_sequence:
        if not value:
            break
        over_streak += 1
    btts_streak = 0
    for value in btts_sequence:
        if not value:
            break
        btts_streak += 1

    return {
        "matches": count,
        "home_ppg": weighted_home_points / weighted_total if weighted_total else 1.35,
        "avg_goals": weighted_goals / weighted_total if weighted_total else 2.5,
        "btts_rate": weighted_btts / weighted_total if weighted_total else .50,
        "over_25_rate": weighted_over25 / weighted_total if weighted_total else .50,
        "sequence": "".join(sequence),
        "current_streak_type": streak_type,
        "current_streak_length": streak_length,
        "over_25_streak": over_streak,
        "btts_streak": btts_streak,
    }


def context_features(injuries: list[dict[str, Any]], lineups: list[dict[str, Any]], home_id: int, away_id: int) -> dict[str, Any]:
    home_inj = sum(1 for x in injuries if x.get("team", {}).get("id") == home_id)
    away_inj = sum(1 for x in injuries if x.get("team", {}).get("id") == away_id)
    lineup_ids = {x.get("team", {}).get("id") for x in lineups}
    return {
        "home_injuries": home_inj,
        "away_injuries": away_inj,
        "home_lineup_available": home_id in lineup_ids,
        "away_lineup_available": away_id in lineup_ids,
        "lineups_available": home_id in lineup_ids and away_id in lineup_ids,
    }
