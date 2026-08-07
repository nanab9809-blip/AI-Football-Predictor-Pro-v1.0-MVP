from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer,
    JSON, String, Text, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class League(Base):
    __tablename__ = "leagues"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    api_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    country: Mapped[str | None] = mapped_column(String(120))
    logo: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("api_id", "season", name="uq_league_api_season"),)


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    api_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    country: Mapped[str | None] = mapped_column(String(120))
    logo: Mapped[str | None] = mapped_column(Text)
    venue_name: Mapped[str | None] = mapped_column(String(180))
    venue_city: Mapped[str | None] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Fixture(Base):
    __tablename__ = "fixtures"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    api_fixture_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    league_id: Mapped[int | None] = mapped_column(ForeignKey("leagues.id"))
    home_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    kickoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str | None] = mapped_column(String(24))
    referee: Mapped[str | None] = mapped_column(String(180))
    venue: Mapped[str | None] = mapped_column(String(180))
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (
        Index("idx_fixtures_kickoff_status", "kickoff_at", "status"),
        Index("idx_fixtures_league_kickoff", "league_id", "kickoff_at"),
    )


class StandingSnapshot(Base):
    __tablename__ = "standing_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), nullable=False)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    position: Mapped[int | None] = mapped_column(Integer)
    points: Mapped[int | None] = mapped_column(Integer)
    played: Mapped[int | None] = mapped_column(Integer)
    wins: Mapped[int | None] = mapped_column(Integer)
    draws: Mapped[int | None] = mapped_column(Integer)
    losses: Mapped[int | None] = mapped_column(Integer)
    goals_for: Mapped[int | None] = mapped_column(Integer)
    goals_against: Mapped[int | None] = mapped_column(Integer)
    form: Mapped[str | None] = mapped_column(String(30))
    __table_args__ = (Index("idx_standings_league_time", "league_id", "captured_at"),)


class TeamStatisticsSnapshot(Base):
    __tablename__ = "team_statistics_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int | None] = mapped_column(ForeignKey("leagues.id"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    __table_args__ = (Index("idx_team_stats_team_time", "team_id", "captured_at"),)


class PredictionVersion(Base):
    __tablename__ = "prediction_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_version: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    feature_version: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PredictionAuditRecord(Base):
    __tablename__ = "prediction_audits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    final_pick: Mapped[str | None] = mapped_column(String(180))
    probability: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    pqi: Mapped[float | None] = mapped_column(Float)
    data_quality: Mapped[float | None] = mapped_column(Float)
    model_agreement: Mapped[float | None] = mapped_column(Float)
    factors: Mapped[dict | None] = mapped_column(JSON)
    warnings: Mapped[list | None] = mapped_column(JSON)
    __table_args__ = (Index("idx_audit_prediction_time", "prediction_id", "created_at"),)


class MonteCarloResult(Base):
    __tablename__ = "monte_carlo_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    simulations: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int | None] = mapped_column(Integer)
    home_probability: Mapped[float] = mapped_column(Float, nullable=False)
    draw_probability: Mapped[float] = mapped_column(Float, nullable=False)
    away_probability: Mapped[float] = mapped_column(Float, nullable=False)
    over_25_probability: Mapped[float | None] = mapped_column(Float)
    btts_probability: Mapped[float | None] = mapped_column(Float)
    score_distribution: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (Index("idx_monte_prediction", "prediction_id"),)


class RecommendationHistory(Base):
    __tablename__ = "recommendation_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    prediction_id: Mapped[int | None] = mapped_column(BigInteger)
    recommendation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    selection: Mapped[str | None] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (Index("idx_recommendation_fixture_time", "fixture_id", "created_at"),)


class BetBuilderRecord(Base):
    __tablename__ = "bet_builder_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    builder_type: Mapped[str] = mapped_column(String(32), nullable=False)
    legs: Mapped[list] = mapped_column(JSON, nullable=False)
    combined_odds: Mapped[float | None] = mapped_column(Float)
    estimated_probability: Mapped[float | None] = mapped_column(Float)
    expected_value: Mapped[float | None] = mapped_column(Float)
    correlation_penalty: Mapped[float | None] = mapped_column(Float)
    balance_score: Mapped[float | None] = mapped_column(Float)
    result: Mapped[str] = mapped_column(String(24), default="PENDING")
    profit: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("idx_builder_fixture_type", "fixture_id", "builder_type"),)


class LeagueMarketReliability(Base):
    __tablename__ = "league_market_reliability"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int | None] = mapped_column(BigInteger)
    league_name: Mapped[str | None] = mapped_column(String(180))
    market_key: Mapped[str] = mapped_column(String(100), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    accuracy: Mapped[float | None] = mapped_column(Float)
    roi: Mapped[float | None] = mapped_column(Float)
    brier_score: Mapped[float | None] = mapped_column(Float)
    log_loss: Mapped[float | None] = mapped_column(Float)
    reliability_score: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("league_id", "market_key", name="uq_reliability_league_market"),
        Index("idx_reliability_score", "reliability_score"),
    )


class AdaptiveWeight(Base):
    __tablename__ = "adaptive_weights"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int | None] = mapped_column(BigInteger)
    market_key: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(80), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    validation_score: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("league_id", "market_key", "model_name", name="uq_adaptive_weight"),)


class DataQualitySnapshot(Base):
    __tablename__ = "data_quality_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    grade: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    components: Mapped[dict] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list | None] = mapped_column(JSON)
    __table_args__ = (Index("idx_data_quality_fixture_time", "fixture_id", "captured_at"),)


class PredictionDriftRecord(Base):
    __tablename__ = "prediction_drift_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    market_key: Mapped[str | None] = mapped_column(String(100))
    previous_probability: Mapped[float | None] = mapped_column(Float)
    current_probability: Mapped[float | None] = mapped_column(Float)
    probability_delta: Mapped[float | None] = mapped_column(Float)
    previous_confidence: Mapped[float | None] = mapped_column(Float)
    current_confidence: Mapped[float | None] = mapped_column(Float)
    drift_level: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (Index("idx_drift_fixture_time", "fixture_id", "created_at"),)


class ApiUsageRecord(Base):
    __tablename__ = "api_usage_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(180), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    response_ms: Mapped[float | None] = mapped_column(Float)
    remaining_quota: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (Index("idx_api_usage_endpoint_time", "endpoint", "created_at"),)


class SystemEvent(Base):
    __tablename__ = "system_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    module: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (Index("idx_system_events_level_time", "level", "created_at"),)


class CacheEntry(Base):
    __tablename__ = "api_cache_entries"
    cache_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(180), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (Index("idx_cache_endpoint_expiry", "endpoint", "expires_at"),)


class UserAccount(Base):
    __tablename__ = "user_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(180))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(24), default="MEMBER", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)
    membership_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    membership_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (
        Index("idx_user_status_expiry", "status", "membership_expires_at"),
    )


class MembershipHistory(Base):
    __tablename__ = "membership_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_accounts.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    old_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("user_accounts.id"))
    note: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (Index("idx_membership_history_user_time", "user_id", "changed_at"),)


class LicenseRecord(Base):
    __tablename__ = "license_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_accounts.id"), unique=True, nullable=False)
    license_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (Index("idx_license_status", "status"),)


class LicenseHistory(Base):
    __tablename__ = "license_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_accounts.id"), nullable=False)
    license_id: Mapped[int | None] = mapped_column(ForeignKey("license_records.id"))
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    old_key: Mapped[str | None] = mapped_column(String(64))
    new_key: Mapped[str | None] = mapped_column(String(64))
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("user_accounts.id"))
    note: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (Index("idx_license_history_user_time", "user_id", "changed_at"),)
