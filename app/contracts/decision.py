from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ContractModel(BaseModel):
    """Stable inter-module contract with backward-compatible extra fields."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class SelectedPickContract(ContractModel):
    label: str = "NO BET"
    key: str = "NO_BET"
    probability: float | None = None
    probability_pct: float | None = None
    confidence: float | None = None
    odds: float | None = None
    fair_odds: float | None = None
    ev: float | None = None
    edge: float | None = None
    kelly_quarter: float | None = None
    decision_status: str = "NO_BET"
    decision_tier: str = "NO_BET"
    decision_label: str = "NO BET"
    risk_level: str = "AVOID"
    published: bool = False
    decision_score: float | None = None
    evidence_score: float | None = None
    market_suitability: float | None = None
    value_verified: bool = False
    value_status: str = "UNAVAILABLE"
    recommendation_basis: str = "MODEL_ONLY"
    decision_reasons: list[str] = Field(default_factory=list)

    @field_validator("probability", mode="before")
    @classmethod
    def normalize_probability(cls, value: Any) -> float | None:
        if value in (None, ""):
            return None
        number = float(value)
        return number / 100.0 if number > 1 else number

    def model_post_init(self, __context: Any) -> None:
        if self.probability is None and self.probability_pct is not None:
            self.probability = float(self.probability_pct) / 100.0
        if self.probability_pct is None and self.probability is not None:
            self.probability_pct = round(float(self.probability) * 100.0, 1)


class BestBuilderContract(ContractModel):
    label: str | None = None
    selections: list[Any] = Field(default_factory=list)
    probability: float | None = None
    probability_pct: float | None = None
    builder_quality: float | None = None
    status: str | None = None
    alignment: str | None = None
    ev: float | None = None
    risk: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if self.probability is None and self.probability_pct is not None:
            self.probability = float(self.probability_pct) / 100.0
        if self.probability_pct is None and self.probability is not None:
            self.probability_pct = round(float(self.probability) * 100.0, 1)


class DecisionIntelligenceContract(ContractModel):
    data_quality: float = 0.0
    data_quality_grade: str | None = None
    data_quality_breakdown: dict[str, Any] = Field(default_factory=dict)
    evidence_strength: float = 0.0
    reliability_score: float = 0.0
    reliability_grade: str = "D"
    reliability_label: str = "NO BET"
    decision_eligibility: str = "NO_BET"
    decision_tier: str = "NO_BET"
    decision_label: str = "NO BET"
    decision_score: float | None = None
    risk_level: str = "AVOID"
    selected_pick_allowed: bool = False
    builder_allowed: bool = False
    builder_evaluation_allowed: bool = False
    builder_evaluated: bool = False
    builder_available: bool = False
    builder_status: str = "NOT_ELIGIBLE"
    builder_reason: str = ""
    selected_pick_available: bool = False
    ev_allowed: bool = False
    reasons: list[str] = Field(default_factory=list)


class AnalysisDecisionContract(ContractModel):
    selected_pick: SelectedPickContract = Field(default_factory=SelectedPickContract)
    best_builder: BestBuilderContract | None = None
    decision_intelligence: DecisionIntelligenceContract = Field(default_factory=DecisionIntelligenceContract)

    @classmethod
    def from_analysis(cls, analysis: dict[str, Any]) -> "AnalysisDecisionContract":
        pick = analysis.get("best_pick") or analysis.get("selected_pick") or {}
        builder = analysis.get("best_builder")
        decision = analysis.get("decision_intelligence") or {}
        return cls(
            selected_pick=SelectedPickContract.model_validate(pick),
            best_builder=BestBuilderContract.model_validate(builder) if isinstance(builder, dict) else None,
            decision_intelligence=DecisionIntelligenceContract.model_validate(decision),
        )
