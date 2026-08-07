from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.clients.api_football import ApiFootballClient


class FixtureService:
    def __init__(self, client: ApiFootballClient) -> None:
        self.client = client

    async def grouped_fixtures(self, date_value: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        payload = await self.client.fixtures_by_date(date_value)
        grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"league": {}, "fixtures": []})

        for item in payload.get("response", []):
            league = item.get("league", {})
            league_id = str(league.get("id", "unknown"))
            grouped[league_id]["league"] = league
            grouped[league_id]["fixtures"].append(item)

        groups = sorted(
            grouped.values(),
            key=lambda row: (row["league"].get("country", ""), row["league"].get("name", "")),
        )
        return groups, payload.get("paging", {})
