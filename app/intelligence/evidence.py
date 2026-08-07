from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


AVAILABLE = "AVAILABLE"
WAITING = "WAITING"
UNAVAILABLE = "UNAVAILABLE"
NOT_REQUIRED = "NOT_REQUIRED"
FAILED = "FAILED"


def _kickoff(fixture: dict[str, Any]) -> datetime | None:
    raw = str((fixture.get("fixture") or {}).get("date") or "")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _payload_ok(payload: dict[str, Any]) -> bool:
    return isinstance(payload, dict) and not bool(payload.get("errors"))


def _has_response(payload: dict[str, Any]) -> bool:
    response = payload.get("response") if isinstance(payload, dict) else None
    if isinstance(response, dict):
        return bool(response)
    return bool(response)


def build_evidence_collection(
    *,
    fixture: dict[str, Any],
    level: str,
    api_prediction: dict[str, Any],
    home_recent_payload: dict[str, Any],
    away_recent_payload: dict[str, Any],
    home_stats_payload: dict[str, Any],
    away_stats_payload: dict[str, Any],
    standings_payload: dict[str, Any],
    h2h_payload: dict[str, Any],
    odds_payload: dict[str, Any],
    injuries_payload: dict[str, Any],
    lineups_payload: dict[str, Any],
) -> dict[str, Any]:
    """Describe provider evidence honestly.

    AVAILABLE means the endpoint was queried successfully and returned usable data.
    WAITING means the information commonly appears closer to kickoff.
    UNAVAILABLE means the provider was queried successfully but has no applicable data.
    NOT_REQUIRED means absence is not a defect (for example no prior H2H).
    FAILED is reserved for an explicit provider error.
    """
    now = datetime.now(timezone.utc)
    kickoff = _kickoff(fixture)
    hours_to_kickoff = ((kickoff - now).total_seconds() / 3600) if kickoff else None
    final_attempted = level == "FINAL"
    candidate_attempted = level in {"CANDIDATE", "FINAL"}

    recent_home = home_recent_payload.get("response") or []
    recent_away = away_recent_payload.get("response") or []
    recent_count = min(len(recent_home), len(recent_away))

    def item(status: str, attempted: bool, count: int = 0, reason: str = "") -> dict[str, Any]:
        return {
            "status": status,
            "attempted": attempted,
            "count": int(count),
            "reason": reason,
            "checked_at": now.isoformat(),
        }

    result: dict[str, Any] = {
        "fixture": item(AVAILABLE, True, 1, "Identitas fixture tersedia."),
        "recent_form": item(
            AVAILABLE if recent_count >= 10 else WAITING if recent_count >= 5 else UNAVAILABLE,
            True,
            recent_count,
            "10 pertandingan tersedia." if recent_count >= 10 else f"Hanya {recent_count} pertandingan tersedia.",
        ),
        "model": item(AVAILABLE if api_prediction else UNAVAILABLE, True, 1 if api_prediction else 0,
                      "Output model tersedia." if api_prediction else "Prediksi provider tidak tersedia; model internal tetap digunakan."),
    }

    home_stats = home_stats_payload.get("response") or {}
    away_stats = away_stats_payload.get("response") or {}
    stats_ok = bool(home_stats) and bool(away_stats)
    result["statistics"] = item(
        AVAILABLE if stats_ok else UNAVAILABLE if candidate_attempted else WAITING,
        candidate_attempted,
        int(bool(home_stats)) + int(bool(away_stats)),
        "Statistik musim kedua tim tersedia." if stats_ok else "Provider tidak menyediakan statistik lengkap untuk kompetisi ini." if candidate_attempted else "Belum dikoleksi.",
    )

    standings = standings_payload.get("response") or []
    result["standings"] = item(
        AVAILABLE if standings else UNAVAILABLE if candidate_attempted else WAITING,
        candidate_attempted,
        len(standings),
        "Klasemen tersedia." if standings else "Kompetisi ini tidak menyediakan klasemen atau data belum tersedia." if candidate_attempted else "Belum dikoleksi.",
    )

    h2h = h2h_payload.get("response") or []
    result["h2h"] = item(
        AVAILABLE if len(h2h) >= 1 else NOT_REQUIRED if candidate_attempted else WAITING,
        candidate_attempted,
        len(h2h),
        "Riwayat pertemuan tersedia." if h2h else "Tidak ada pertemuan sebelumnya yang tersedia." if candidate_attempted else "Belum dikoleksi.",
    )

    odds = odds_payload.get("response") or []
    if odds:
        odds_status, odds_reason = AVAILABLE, "Odds bookmaker tersedia."
    elif final_attempted and hours_to_kickoff is not None and hours_to_kickoff > 0:
        odds_status, odds_reason = WAITING, "Market odds belum diterbitkan atau belum tersedia."
    elif final_attempted:
        odds_status, odds_reason = UNAVAILABLE, "Provider tidak menyediakan odds untuk fixture ini."
    else:
        odds_status, odds_reason = WAITING, "Belum dikoleksi."
    result["odds"] = item(odds_status, final_attempted, len(odds), odds_reason)

    injuries = injuries_payload.get("response") or []
    result["injuries"] = item(
        AVAILABLE if injuries else UNAVAILABLE if final_attempted else WAITING,
        final_attempted,
        len(injuries),
        "Laporan cedera tersedia." if injuries else "Tidak ada laporan cedera dari provider; dapat berarti tidak ada cedera atau liga tidak tercakup." if final_attempted else "Belum dikoleksi.",
    )

    lineups = lineups_payload.get("response") or []
    if lineups:
        lineups_status, lineups_reason = AVAILABLE, "Line-up resmi tersedia."
    elif final_attempted and hours_to_kickoff is not None and hours_to_kickoff > 1.5:
        lineups_status, lineups_reason = WAITING, "Menunggu line-up resmi mendekati kickoff."
    elif final_attempted:
        lineups_status, lineups_reason = UNAVAILABLE, "Line-up resmi belum/tidak disediakan provider."
    else:
        lineups_status, lineups_reason = WAITING, "Belum dikoleksi."
    result["lineups"] = item(lineups_status, final_attempted, len(lineups), lineups_reason)

    return {
        "mode": "EVIDENCE_COLLECTOR" if level == "FINAL" else level,
        "checked_at": now.isoformat(),
        "hours_to_kickoff": round(hours_to_kickoff, 2) if hours_to_kickoff is not None else None,
        "items": result,
        "summary": {
            status: sum(1 for value in result.values() if value["status"] == status)
            for status in (AVAILABLE, WAITING, UNAVAILABLE, NOT_REQUIRED, FAILED)
        },
    }
