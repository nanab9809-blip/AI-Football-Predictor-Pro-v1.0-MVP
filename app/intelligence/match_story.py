from __future__ import annotations

from typing import Any


def build_match_story(
    *,
    comparison: dict[str, Any],
    selected_pick: dict[str, Any],
    home_features: dict[str, Any],
    away_features: dict[str, Any],
    h2h_features: dict[str, Any],
    home_xg: float,
    away_xg: float,
) -> dict[str, Any]:
    home = str(comparison.get("home_name") or "Tim kandang")
    away = str(comparison.get("away_name") or "Tim tandang")
    favored = comparison.get("favored_side")
    paragraphs: list[str] = []

    if favored == "HOME":
        paragraphs.append(
            f"{home} memiliki keunggulan bukti keseluruhan atas {away}, terutama dari perbandingan serangan, pertahanan, dan performa terkini."
        )
    elif favored == "AWAY":
        paragraphs.append(
            f"{away} memiliki keunggulan bukti keseluruhan atas {home}, terutama dari perbandingan serangan, pertahanan, dan performa terkini."
        )
    else:
        paragraphs.append(
            "Perbandingan kedua tim relatif seimbang sehingga market hasil pertandingan memerlukan kehati-hatian lebih tinggi."
        )

    paragraphs.append(
        f"Proyeksi expected goals adalah {home_xg:.2f} untuk {home} dan {away_xg:.2f} untuk {away}. "
        f"Form 10 laga: {home} {home_features.get('form_sequence') or '-'}; {away} {away_features.get('form_sequence') or '-'} ."
    )

    h2h_matches = int(h2h_features.get("matches") or 0)
    if h2h_matches >= 3:
        paragraphs.append(
            f"Tersedia {h2h_matches} H2H terbaru dengan rata-rata {float(h2h_features.get('avg_goals') or 0):.2f} gol per laga "
            f"dan pola {h2h_features.get('sequence') or '-'} dari perspektif tim kandang."
        )
    else:
        paragraphs.append("Sampel H2H terlalu kecil sehingga tidak dijadikan faktor dominan.")

    label = selected_pick.get("label") or "Tidak ada Selected Pick"
    status = str(selected_pick.get("decision_status") or "NO_PICK").replace("_", " ")
    verdict = (
        f"Keputusan akhir: {label} ({status}) dengan Decision Score "
        f"{selected_pick.get('decision_score', '-')}."
    )
    return {"paragraphs": paragraphs, "verdict": verdict}
