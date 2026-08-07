from __future__ import annotations

from typing import Any

from app.contracts.decision import AnalysisDecisionContract


class DecisionViewService:
    """Normalizes free-form analysis payloads into one typed decision contract."""

    @staticmethod
    def normalize(analysis: dict[str, Any]) -> tuple[dict[str, Any], AnalysisDecisionContract]:
        contract = AnalysisDecisionContract.from_analysis(analysis)
        normalized = dict(analysis)
        normalized["best_pick"] = contract.selected_pick.model_dump()
        normalized["selected_pick"] = contract.selected_pick.model_dump()
        normalized["best_builder"] = contract.best_builder.model_dump() if contract.best_builder else None
        normalized["decision_intelligence"] = contract.decision_intelligence.model_dump()
        normalized["decision_contract"] = contract.model_dump()
        return normalized, contract
