from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import text

from app.services.decision_snapshot_service import canonical_tier
from app.validation.settlement import normalize_market_key, settle_market

PERIODS = {"7D": 7, "30D": 30, "90D": 90, "ALL": None}
DECISION_ORDER = ["ELITE_PICK", "STRONG_PICK", "PICK", "MONITOR", "NO_BET"]


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return default


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _pct(value: float) -> float:
    return round(value * 100.0, 2)


def _grade(score: float) -> str:
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def _rating_from_roi(roi: float, sample: int) -> str:
    if sample < 10:
        return "MONITOR"
    if roi >= 15:
        return "★★★★★"
    if roi >= 8:
        return "★★★★"
    if roi >= 2:
        return "★★★"
    if roi >= -3:
        return "★★"
    return "★"


def _settle_builder(selections: list[dict[str, Any]], home: int, away: int) -> str | None:
    results: list[str] = []
    for leg in selections:
        key = normalize_market_key(str(leg.get("key") or leg.get("market_key") or leg.get("label") or ""))
        if not key:
            return None
        result = settle_market(key, home, away)
        if result not in {"WIN", "LOSS", "VOID"}:
            return None
        results.append(result)
    if not results:
        return None
    if "LOSS" in results:
        return "LOSS"
    if all(r == "WIN" for r in results):
        return "WIN"
    return "VOID"


def _financials(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    decided = [r for r in rows if str(r.get("result") or "").upper() in {"WIN", "LOSS"}]
    settled = [r for r in rows if str(r.get("result") or "").upper() in {"WIN", "LOSS", "VOID"}]
    wins = sum(str(r.get("result") or "").upper() == "WIN" for r in settled)
    losses = sum(str(r.get("result") or "").upper() == "LOSS" for r in settled)
    voids = sum(str(r.get("result") or "").upper() == "VOID" for r in settled)
    stake = sum(_f(r.get("stake"), 1.0) for r in settled if r.get("profit") is not None)
    profit = sum(_f(r.get("profit")) for r in settled if r.get("profit") is not None)
    odds_values = [_f(r.get("odds")) for r in settled if _f(r.get("odds")) > 1]
    ev_values = [_f(r.get("ev")) for r in settled if r.get("ev") is not None]
    clv_values = [_f(r.get("clv")) for r in settled if r.get("clv") is not None]
    roi = (profit / stake * 100.0) if stake else 0.0
    # With unit stakes ROI and yield coincide; keep both fields because the UI/API
    # treats Yield as profit per settled recommendation.
    yield_pct = roi
    return {
        "sample": len(settled), "wins": wins, "losses": losses, "voids": voids,
        "accuracy": (wins / len(decided) * 100.0) if decided else 0.0,
        "profit": profit, "stake": stake, "roi": roi, "yield": yield_pct,
        "avg_odds": sum(odds_values) / len(odds_values) if odds_values else 0.0,
        "avg_ev": sum(ev_values) / len(ev_values) * 100.0 if ev_values else 0.0,
        "avg_clv": sum(clv_values) / len(clv_values) * 100.0 if clv_values else 0.0,
    }


def _risk_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda r: str(r.get("settled_at") or r.get("created_at") or ""))
    equity = peak = 0.0
    max_drawdown = 0.0
    win_streak = lose_streak = longest_win = longest_lose = 0
    gross_profit = gross_loss = 0.0
    for row in ordered:
        result = str(row.get("result") or "").upper()
        profit = _f(row.get("profit"))
        equity += profit
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
        if profit > 0:
            gross_profit += profit
        elif profit < 0:
            gross_loss += abs(profit)
        if result == "WIN":
            win_streak += 1; lose_streak = 0; longest_win = max(longest_win, win_streak)
        elif result == "LOSS":
            lose_streak += 1; win_streak = 0; longest_lose = max(longest_lose, lose_streak)
    profit_factor = (gross_profit / gross_loss) if gross_loss else (gross_profit if gross_profit else 0.0)
    recovery_factor = (equity / abs(max_drawdown)) if max_drawdown < 0 else (equity if equity > 0 else 0.0)
    return {
        "longest_win_streak": longest_win, "longest_lose_streak": longest_lose,
        "max_drawdown": round(max_drawdown, 2), "profit_factor": round(profit_factor, 2),
        "recovery_factor": round(recovery_factor, 2),
    }


class PerformanceIntelligence:
    """Settlement-backed performance warehouse.

    Prediction and builder results are materialized only from settled outcomes.
    Read pages consume the warehouse and never recalculate model statistics.
    """

    def __init__(self, store: Any) -> None:
        self.store = store

    def rebuild(self) -> None:
        self._rebuild_builder_settlements()
        prediction_rows = self.store._rows("""SELECT id AS source_id, fixture_id, settled_at, created_at,
            league, market_key, pick_role, result, profit, COALESCE(odds,1.0) AS odds,
            ev, clv, 1.0 AS stake FROM predictions
            WHERE result IN ('WIN','LOSS','VOID') AND COALESCE(settlement_eligible,1)=1""")
        builder_rows = self.store._rows("SELECT * FROM performance_builder_settlements WHERE result IN ('WIN','LOSS','VOID')")
        self._rebuild_rollups(prediction_rows, builder_rows)
        self._rebuild_score_and_insights(prediction_rows, builder_rows)

    def _rebuild_builder_settlements(self) -> None:
        fixtures = self.store._rows("""SELECT fixture_id, MAX(settled_at) AS settled_at,
            MAX(home_score) AS home_score, MAX(away_score) AS away_score
            FROM predictions WHERE result IN ('WIN','LOSS','VOID') AND home_score IS NOT NULL AND away_score IS NOT NULL
            GROUP BY fixture_id""")
        with self.store.engine.begin() as conn:
            for fixture in fixtures:
                decision_rows = self.store._rows("SELECT * FROM decision_records WHERE fixture_id=:f LIMIT 1", {"f": fixture["fixture_id"]})
                if not decision_rows:
                    continue
                decision = decision_rows[0]
                try:
                    analysis = json.loads(decision.get("analysis_json") or "{}")
                except (TypeError, ValueError):
                    analysis = {}
                portfolio = analysis.get("builder_portfolio") if isinstance(analysis, dict) else []
                if not isinstance(portfolio, list):
                    portfolio = []
                if not portfolio:
                    try:
                        top = json.loads(decision.get("builder_json") or "{}")
                    except (TypeError, ValueError):
                        top = {}
                    portfolio = [top] if isinstance(top, dict) and top.get("selections") else []
                for index, builder in enumerate(portfolio[:3], start=1):
                    if not isinstance(builder, dict) or not builder.get("selections"):
                        continue
                    result = _settle_builder(builder.get("selections") or [], int(fixture["home_score"]), int(fixture["away_score"]))
                    if not result:
                        continue
                    complete_odds = bool(builder.get("complete_odds"))
                    odds = _f(builder.get("combined_odds")) if complete_odds else 0.0
                    stake = 1.0 if complete_odds and odds > 1 else 0.0
                    profit = ((odds - 1.0) if result == "WIN" else (-1.0 if result == "LOSS" else 0.0)) if stake else None
                    template_code = str(builder.get("template_code") or f"PORTFOLIO_{index}")
                    conn.execute(text("""INSERT INTO performance_builder_settlements
                        (fixture_id,template_code,portfolio_rank,builder_dna,builder_label,result,odds,ev,builder_quality,risk_level,profit,stake,settled_at)
                        VALUES (:fixture_id,:template_code,:rank,:dna,:label,:result,:odds,:ev,:quality,:risk,:profit,:stake,:settled_at)
                        ON CONFLICT(fixture_id,template_code) DO UPDATE SET portfolio_rank=excluded.portfolio_rank,
                        builder_dna=excluded.builder_dna,builder_label=excluded.builder_label,result=excluded.result,
                        odds=excluded.odds,ev=excluded.ev,builder_quality=excluded.builder_quality,risk_level=excluded.risk_level,
                        profit=excluded.profit,stake=excluded.stake,settled_at=excluded.settled_at"""), {
                        "fixture_id": fixture["fixture_id"], "template_code": template_code, "rank": index,
                        "dna": builder.get("builder_dna") or builder.get("template_name") or "Unknown",
                        "label": builder.get("combined_label") or builder.get("label") or template_code,
                        "result": result, "odds": odds or None, "ev": builder.get("ev"),
                        "quality": builder.get("builder_quality"), "risk": builder.get("risk"),
                        "profit": profit, "stake": stake, "settled_at": fixture.get("settled_at"),
                    })

    @staticmethod
    def _filter_period(rows: list[dict[str, Any]], days: int | None) -> list[dict[str, Any]]:
        if days is None:
            return rows
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return [r for r in rows if (_dt(r.get("settled_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]

    def _insert_rollup(self, conn: Any, dimension_type: str, dimension_value: str, period_key: str, stats: dict[str, Any], extra: dict[str, Any] | None = None) -> None:
        conn.execute(text("""INSERT INTO performance_rollups
            (dimension_type,dimension_value,period_key,sample,wins,losses,voids,accuracy,profit,stake,roi,yield_pct,avg_odds,avg_ev,avg_clv,extra_json,updated_at)
            VALUES (:dt,:dv,:pk,:sample,:wins,:losses,:voids,:accuracy,:profit,:stake,:roi,:yield_pct,:avg_odds,:avg_ev,:avg_clv,:extra,:updated)
            ON CONFLICT(dimension_type,dimension_value,period_key) DO UPDATE SET
            sample=excluded.sample,wins=excluded.wins,losses=excluded.losses,voids=excluded.voids,accuracy=excluded.accuracy,
            profit=excluded.profit,stake=excluded.stake,roi=excluded.roi,yield_pct=excluded.yield_pct,avg_odds=excluded.avg_odds,
            avg_ev=excluded.avg_ev,avg_clv=excluded.avg_clv,extra_json=excluded.extra_json,updated_at=excluded.updated_at"""), {
            "dt": dimension_type, "dv": dimension_value, "pk": period_key,
            **{k: round(_f(stats.get(k)), 4) if k not in {"sample","wins","losses","voids"} else int(stats.get(k) or 0)
               for k in ("sample","wins","losses","voids","accuracy","profit","stake","roi","yield","avg_odds","avg_ev","avg_clv")},
            "yield_pct": round(_f(stats.get("yield")), 4),
            "extra": json.dumps(extra or {}, ensure_ascii=False, default=str), "updated": datetime.now(timezone.utc).isoformat(),
        })

    def _rebuild_rollups(self, predictions: list[dict[str, Any]], builders: list[dict[str, Any]]) -> None:
        with self.store.engine.begin() as conn:
            conn.execute(text("DELETE FROM performance_rollups"))
            for period_key, days in PERIODS.items():
                rows = self._filter_period(predictions, days)
                overall = _financials(rows)
                self._insert_rollup(conn, "OVERALL", "ALL", period_key, overall, _risk_metrics(rows))

                groups: dict[str, dict[str, list[dict[str, Any]]]] = {
                    "DECISION": defaultdict(list), "MARKET": defaultdict(list), "LEAGUE": defaultdict(list),
                }
                for row in rows:
                    groups["DECISION"][canonical_tier(row.get("pick_role"))].append(row)
                    groups["MARKET"][str(row.get("market_key") or "UNKNOWN")].append(row)
                    groups["LEAGUE"][str(row.get("league") or "Unknown")].append(row)
                # Include canonical decision rows even if sample is zero so the UI is stable.
                for tier in DECISION_ORDER:
                    group_rows = groups["DECISION"].get(tier, [])
                    self._insert_rollup(conn, "DECISION", tier, period_key, _financials(group_rows), {"settlement_eligible": tier in {"ELITE_PICK","STRONG_PICK","PICK"}})
                for dim in ("MARKET", "LEAGUE"):
                    for value, group_rows in groups[dim].items():
                        self._insert_rollup(conn, dim, value, period_key, _financials(group_rows), {"rating": _rating_from_roi(_financials(group_rows)["roi"], len(group_rows))})

                b_rows = self._filter_period(builders, days)
                b_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
                for row in b_rows:
                    b_groups[str(row.get("builder_dna") or "Unknown")].append(row)
                for dna, group_rows in b_groups.items():
                    stats = _financials(group_rows)
                    qualities = [_f(x.get("builder_quality")) for x in group_rows if x.get("builder_quality") is not None]
                    self._insert_rollup(conn, "BUILDER", dna, period_key, stats, {
                        "avg_quality": round(sum(qualities)/len(qualities), 1) if qualities else 0,
                        "rating": _rating_from_roi(stats["roi"], stats["sample"]),
                    })

    def _rebuild_score_and_insights(self, predictions: list[dict[str, Any]], builders: list[dict[str, Any]]) -> None:
        overall = _financials(predictions)
        risk = _risk_metrics(predictions)
        builder = _financials(builders)
        settled_sample = overall["sample"]
        # Score components are intentionally conservative for small samples.
        sample_factor = min(1.0, settled_sample / 100.0) if settled_sample else 0.0
        accuracy_score = min(100.0, max(0.0, overall["accuracy"] * 1.25))
        roi_score = min(100.0, max(0.0, 50.0 + overall["roi"] * 2.0))
        yield_score = min(100.0, max(0.0, 50.0 + overall["yield"] * 2.0))
        clv_score = min(100.0, max(0.0, 50.0 + overall["avg_clv"] * 4.0)) if overall["avg_clv"] else 50.0
        decision_rows = {r["dimension_value"]: r for r in self.store._rows("SELECT * FROM performance_rollups WHERE dimension_type='DECISION' AND period_key='ALL'")}
        ordered_acc = [_f((decision_rows.get(k) or {}).get("accuracy")) for k in ("ELITE_PICK","STRONG_PICK","PICK") if int((decision_rows.get(k) or {}).get("sample") or 0) >= 5]
        decision_consistency = 100.0 if len(ordered_acc) < 2 else max(0.0, 100.0 - sum(max(0.0, ordered_acc[i+1]-ordered_acc[i]) for i in range(len(ordered_acc)-1))*3.0)
        builder_score = 50.0 if builder["sample"] < 5 else min(100.0, max(0.0, builder["accuracy"] * 0.7 + (50 + builder["roi"]*2)*0.3))
        recent = _financials(self._filter_period(predictions, 30))
        consistency = max(0.0, 100.0 - abs(recent["accuracy"] - overall["accuracy"])*2.0) if settled_sample >= 10 else 50.0
        raw_score = (accuracy_score*.25 + roi_score*.25 + yield_score*.15 + clv_score*.10 + decision_consistency*.10 + builder_score*.10 + consistency*.05)
        # Small samples remain explicitly provisional instead of receiving an inflated grade.
        score = raw_score * (0.65 + 0.35*sample_factor) if settled_sample else 0.0
        grade = _grade(score)
        with self.store.engine.begin() as conn:
            conn.execute(text("DELETE FROM performance_ai_score"))
            conn.execute(text("""INSERT INTO performance_ai_score
                (id,score,grade,sample,accuracy_component,roi_component,yield_component,clv_component,decision_component,builder_component,consistency_component,updated_at)
                VALUES (1,:score,:grade,:sample,:a,:r,:y,:c,:d,:b,:co,:u)"""), {
                "score": round(score,1), "grade": grade, "sample": settled_sample,
                "a": round(accuracy_score,1), "r": round(roi_score,1), "y": round(yield_score,1),
                "c": round(clv_score,1), "d": round(decision_consistency,1), "b": round(builder_score,1),
                "co": round(consistency,1), "u": datetime.now(timezone.utc).isoformat(),
            })
            conn.execute(text("DELETE FROM performance_insights"))
            insights: list[tuple[str,str,str]] = []
            if settled_sample < 30:
                insights.append(("MONITOR", "Sampel belum stabil", f"Baru {settled_sample} rekomendasi settled. Hindari mengubah bobot model sebelum sampel bertambah."))
            elif overall["roi"] > 5:
                insights.append(("POSITIVE", "Strategi saat ini profitable", f"ROI settlement {overall['roi']:.1f}% dengan profit {overall['profit']:+.2f} unit."))
            elif overall["roi"] < 0:
                insights.append(("REVIEW", "Profitabilitas perlu ditinjau", f"ROI settlement {overall['roi']:.1f}%. Prioritaskan market dan tier yang memiliki ROI positif."))
            market_rows = self.store._rows("SELECT * FROM performance_rollups WHERE dimension_type='MARKET' AND period_key='ALL' AND sample>=10 ORDER BY roi DESC")
            if market_rows:
                best = market_rows[0]; worst = market_rows[-1]
                if _f(best.get("roi")) > 3:
                    insights.append(("OPPORTUNITY", f"{str(best.get('dimension_value')).replace('_',' ')} unggul", f"ROI {_f(best.get('roi')):+.1f}% dari {best.get('sample')} settlement. Pertahankan prioritas sambil memonitor CLV."))
                if _f(worst.get("roi")) < -5:
                    insights.append(("CAUTION", f"{str(worst.get('dimension_value')).replace('_',' ')} lemah", f"ROI {_f(worst.get('roi')):+.1f}% dari {worst.get('sample')} settlement. Jangan menaikkan prioritas sebelum kalibrasi."))
            builder_rows = self.store._rows("SELECT * FROM performance_rollups WHERE dimension_type='BUILDER' AND period_key='ALL' AND sample>=8 ORDER BY roi DESC")
            if builder_rows:
                bestb = builder_rows[0]
                if _f(bestb.get("roi")) > 3:
                    insights.append(("BUILDER", f"Builder DNA {bestb.get('dimension_value')} efektif", f"ROI {_f(bestb.get('roi')):+.1f}% pada {bestb.get('sample')} builder settled."))
            for idx, (kind, title, message) in enumerate(insights[:6], start=1):
                conn.execute(text("INSERT INTO performance_insights(id,kind,title,message,created_at) VALUES (:id,:k,:t,:m,:c)"), {
                    "id": idx, "k": kind, "t": title, "m": message, "c": datetime.now(timezone.utc).isoformat(),
                })

    def dashboard(self) -> dict[str, Any]:
        def rows(dim: str, period: str = "ALL") -> list[dict[str, Any]]:
            out = self.store._rows("SELECT * FROM performance_rollups WHERE dimension_type=:d AND period_key=:p ORDER BY sample DESC, roi DESC", {"d": dim, "p": period})
            for row in out:
                try: row["extra"] = json.loads(row.get("extra_json") or "{}")
                except (TypeError, ValueError): row["extra"] = {}
            return out
        overall_rows = self.store._rows("SELECT * FROM performance_rollups WHERE dimension_type='OVERALL' AND dimension_value='ALL' AND period_key='ALL' LIMIT 1")
        overall = overall_rows[0] if overall_rows else {"sample":0,"wins":0,"losses":0,"voids":0,"accuracy":0,"profit":0,"roi":0,"yield_pct":0,"avg_odds":0,"avg_ev":0,"avg_clv":0,"extra_json":"{}"}
        try: overall["extra"] = json.loads(overall.get("extra_json") or "{}")
        except (TypeError, ValueError): overall["extra"] = {}
        score_rows = self.store._rows("SELECT * FROM performance_ai_score WHERE id=1")
        score = score_rows[0] if score_rows else {"score":0,"grade":"D","sample":0}
        timeline = []
        for key in ("7D","30D","90D","ALL"):
            rr = self.store._rows("SELECT * FROM performance_rollups WHERE dimension_type='OVERALL' AND dimension_value='ALL' AND period_key=:p LIMIT 1", {"p":key})
            if rr: timeline.append(rr[0])
        return {
            "overall": overall, "score": score, "decision": rows("DECISION"), "builder": rows("BUILDER"),
            "market": rows("MARKET"), "league": rows("LEAGUE"), "timeline": timeline,
            "insights": self.store._rows("SELECT * FROM performance_insights ORDER BY id"),
        }
