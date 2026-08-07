from __future__ import annotations

from typing import Any


class RunHistoryBuilder:
    """Build a run summary without mixing per-run and cumulative counters."""

    def __init__(self, queue_service: Any) -> None:
        self.queue_service = queue_service

    def build(self, *, base: dict[str, Any], details: list[dict[str, Any]]) -> dict[str, Any]:
        snapshot = self.queue_service.build()
        queue = snapshot.summary()
        summary = dict(base)
        summary.update({
            "remaining_pending": snapshot.pending,
            "queue_ready": len(snapshot.ready),
            "queue_waiting": len(snapshot.waiting),
            "queue_recovery": len(snapshot.recovery),
            "queue_investigation": len(snapshot.investigation),
            "total_settled": int(queue.get("settled") or 0),
            "total_wins": int(queue.get("wins") or 0),
            "total_losses": int(queue.get("losses") or 0),
            "total_voids": int(queue.get("voids") or 0),
            "details": details[:100],
        })
        return summary
