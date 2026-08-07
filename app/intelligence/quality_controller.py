from __future__ import annotations

from typing import Any


def finalize_decision(
    *,
    decision_intelligence: dict[str, Any],
    selected_pick: dict[str, Any] | None,
    best_builder: dict[str, Any] | None,
    builder_diagnostics: dict[str, Any] | None,
) -> dict[str, Any]:
    """Create the final, auditable decision state shown by every UI.

    `builder_allowed` means the quality gate permits evaluation. It never means
    a builder was actually found. Availability is derived only after the
    builder engine has completed its validation pipeline.
    """
    final = dict(decision_intelligence or {})
    diagnostics = dict(builder_diagnostics or {})
    pick = selected_pick or {}

    pick_status = str(pick.get("decision_tier") or pick.get("decision_status") or pick.get("status") or "").upper()
    published = pick.get("published")
    if published is None:
        published = pick_status not in {"", "NO_BET", "NO_PICK", "MONITOR"}
    pick_available = bool(
        final.get("selected_pick_allowed")
        and str(pick.get("key") or "") not in {"", "NO_BET"}
        and bool(published)
        and pick_status not in {"NO_BET", "NO_PICK", "MONITOR"}
    )

    pick_tier = str(pick.get("decision_tier") or pick.get("decision_status") or "NO_BET").upper()
    final_eligibility = (
        "ELIGIBLE" if pick_tier in {"ELITE_PICK", "STRONG_PICK", "PICK"}
        else "REVIEW" if pick_tier == "MONITOR"
        else "NO_BET"
    )
    builder_evaluation_allowed = bool(final.get("builder_allowed"))
    builder_evaluated = bool(
        builder_evaluation_allowed
        and (
            diagnostics.get("pairs_generated") is not None
            or diagnostics.get("eligible_markets") is not None
        )
    )
    builder_available = bool(best_builder and best_builder.get("selections"))

    if not builder_evaluation_allowed:
        builder_status = "NOT_ELIGIBLE"
        builder_reason = "Quality Gate tidak mengizinkan evaluasi Best Builder."
    elif builder_available:
        builder_status = "AVAILABLE"
        builder_reason = "Satu kombinasi Best Builder lolos seluruh validasi akhir."
    elif not builder_evaluated:
        builder_status = "NOT_EVALUATED"
        builder_reason = "Builder Engine belum menyelesaikan evaluasi kandidat."
    else:
        qualified = int(diagnostics.get("qualified_pairs") or 0)
        mismatch = int(diagnostics.get("rejected_selected_pick_mismatch") or 0)
        rejected_gate = int(diagnostics.get("rejected_quality_gate") or 0)
        if qualified > 0 and mismatch >= qualified:
            builder_status = "NO_QUALIFIED_BUILDER"
            builder_reason = (
                f"{qualified} pasangan lolos validasi awal, tetapi seluruhnya tidak selaras "
                "dengan Selected Pick."
            )
        elif rejected_gate > 0:
            builder_status = "NO_QUALIFIED_BUILDER"
            builder_reason = "Tidak ada kandidat yang lolos Quality Gate akhir Best Builder."
        else:
            builder_status = "NO_QUALIFIED_BUILDER"
            builder_reason = "Tidak ada kombinasi 2-leg yang lolos seluruh validasi."

    # A published builder is impossible when the selected pick itself is absent.
    if not pick_available and builder_available:
        builder_available = False
        builder_status = "BLOCKED_BY_FINAL_CONTROLLER"
        builder_reason = "Best Builder diblokir karena tidak ada Selected Pick publik yang valid."

    final.update({
        "decision_eligibility": final_eligibility,
        "decision_tier": pick_tier,
        "decision_label": str(pick.get("decision_label") or pick_tier.replace("_", " ")),
        "decision_score": pick.get("decision_score"),
        "risk_level": str(pick.get("risk_level") or "AVOID"),
        "selected_pick_available": pick_available,
        "builder_evaluation_allowed": builder_evaluation_allowed,
        "builder_evaluated": builder_evaluated,
        "builder_available": builder_available,
        "builder_status": builder_status,
        "builder_reason": builder_reason,
    })

    final_reasons = list(final.get("reasons") or [])
    for reason in pick.get("decision_reasons") or []:
        if reason not in final_reasons:
            final_reasons.append(reason)
    if builder_reason and builder_reason not in final_reasons:
        final_reasons.append(builder_reason)
    final["reasons"] = final_reasons
    return final
