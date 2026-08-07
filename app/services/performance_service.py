from __future__ import annotations

from typing import Any


def metrics(predictions: list[dict[str, Any]], trades: list[dict[str, Any]], bankroll: float = 100.0) -> dict[str, Any]:
    settled = [p for p in predictions if p.get("result") in {"WIN", "LOSS"}]
    wins = sum(1 for p in settled if p["result"] == "WIN")
    total_profit = sum(float(p.get("profit") or 0) for p in predictions)
    trade_profit = sum(float(t.get("profit") or 0) for t in trades)
    settled_trades = [t for t in trades if t.get("result") in {"WIN", "LOSS"}]
    trade_wins = sum(1 for t in settled_trades if t["result"] == "WIN")
    total_staked = sum(float(t.get("stake") or 0) for t in settled_trades)
    return {
        "predictions": len(predictions), "settled_predictions": len(settled),
        "accuracy": round(100*wins/len(settled), 1) if settled else 0,
        "paper_trades": len(trades), "paper_hit_rate": round(100*trade_wins/len(settled_trades), 1) if settled_trades else 0,
        "profit": round(trade_profit, 2), "bankroll": round(bankroll+trade_profit, 2),
        "roi": round(100*trade_profit/total_staked, 1) if total_staked else 0,
        "prediction_profit": round(total_profit, 2),
    }
