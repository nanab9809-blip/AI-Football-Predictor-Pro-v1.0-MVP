from __future__ import annotations

from typing import Any

PUBLIC_TIERS = {"ELITE_PICK", "STRONG_PICK", "PICK"}
NON_PUBLIC_TIERS = {"MONITOR", "NO_BET", "NO_PICK", "WATCH", "SELECTED_VALUE", "SELECTED_MODEL", "SAFE", "VALUE", "QUALIFIED", "MODEL_PICK", "VALUE_PICK"}
LEGACY_PUBLIC_ROLES: set[str] = set()


def normalize_tier(value: Any) -> str:
    raw = str(value or "").strip().upper().replace(" ", "_")
    aliases = {
        "ELITE": "ELITE_PICK",
        "STRONG": "STRONG_PICK",
        "NO_PICK": "NO_BET",
        "NOBET": "NO_BET",
    }
    return aliases.get(raw, raw or "NO_BET")


def recommendation_from_analysis(analysis: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = analysis or {}
    candidate = payload.get("recommendation")
    if isinstance(candidate, dict) and candidate.get("published"):
        return candidate
    pick = payload.get("best_pick") or payload.get("selected_pick") or {}
    if isinstance(pick, dict) and pick.get("published"):
        return pick
    return None


def best_market_from_analysis(analysis: dict[str, Any] | None) -> dict[str, Any]:
    payload = analysis or {}
    market = payload.get("best_market") or payload.get("best_pick") or payload.get("selected_pick") or {}
    return market if isinstance(market, dict) else {}


def is_public_recommendation(*, decision_tier: Any = None, published: Any = None,
                             pick_role: Any = None, pick: Any = None,
                             market_key: Any = None) -> bool:
    if published is not None:
        return bool(published)
    tier = normalize_tier(decision_tier or pick_role)
    if tier in PUBLIC_TIERS or tier in LEGACY_PUBLIC_ROLES:
        return True
    if tier in NON_PUBLIC_TIERS:
        return False
    if str(market_key or "").strip().upper() == "NO_BET":
        return False
    if str(pick or "").strip().upper().replace("_", " ") in {"NO BET", "NO PICK"}:
        return False
    return bool(str(market_key or "").strip())


def settlement_eligible_from_row(row: dict[str, Any]) -> bool:
    explicit = row.get("settlement_eligible")
    if explicit is not None:
        if isinstance(explicit, str):
            return explicit.strip().lower() not in {"0", "false", "no", "off", ""}
        return bool(explicit)
    return is_public_recommendation(
        decision_tier=row.get("decision_status") or row.get("pick_role"),
        published=row.get("published"),
        pick_role=row.get("pick_role"),
        pick=row.get("pick"),
        market_key=row.get("market_key"),
    )
