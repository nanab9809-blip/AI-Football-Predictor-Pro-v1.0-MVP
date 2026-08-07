from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings


class ApiFootballError(RuntimeError):
    """Kesalahan terkontrol saat mengambil data dari API-Football."""


@dataclass
class CacheItem:
    expires_at: float
    value: dict[str, Any]


class ApiFootballClient:
    """API-Football client with quota-aware retries and endpoint-specific cache."""

    RESET_TZ = ZoneInfo("Asia/Makassar")
    RESET_HOUR = 8
    ENDPOINT_TTL_SECONDS = {
        "fixtures": 300,
        "fixtures/headtohead": 24 * 3600,
        "teams/statistics": 6 * 3600,
        "standings": 6 * 3600,
        "predictions": 6 * 3600,
        "injuries": 2 * 3600,
        "fixtures/lineups": 15 * 60,
        "odds": 10 * 60,
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cache: dict[str, CacheItem] = {}
        self.last_headers: dict[str, str] = {}
        self.last_error: str | None = None
        self._quota_exhausted_until: datetime | None = None
        self.requests_this_process = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.endpoint_requests: dict[str, int] = {}
        self.endpoint_cache_hits: dict[str, int] = {}

    def _cache_key(self, endpoint: str, params: dict[str, Any]) -> str:
        encoded = "&".join(f"{key}={params[key]}" for key in sorted(params))
        return f"{endpoint}?{encoded}"

    def _ttl_for(self, endpoint: str, params: dict[str, Any]) -> int:
        # Recent fixture history changes slowly. A date fixture list changes faster.
        if endpoint == "fixtures" and ("last" in params or "team" in params):
            return 6 * 3600
        return int(self.ENDPOINT_TTL_SECONDS.get(endpoint, self.settings.cache_ttl_seconds))

    @classmethod
    def next_reset_at(cls, now: datetime | None = None) -> datetime:
        local_now = now.astimezone(cls.RESET_TZ) if now else datetime.now(cls.RESET_TZ)
        reset = local_now.replace(hour=cls.RESET_HOUR, minute=0, second=0, microsecond=0)
        if local_now >= reset:
            reset += timedelta(days=1)
        return reset

    @staticmethod
    def _is_daily_quota_error(message: str) -> bool:
        text = message.lower()
        return any(token in text for token in (
            "daily quota exceeded", "daily request limit", "requests quota reached",
            "request limit exceeded for the day", "quota exceeded for the day",
        ))

    @staticmethod
    def _is_quota_error(message: str) -> bool:
        """Backward-compatible helper used by older tests and modules."""
        return ApiFootballClient._is_daily_quota_error(message) or ApiFootballClient._is_rate_limit_error(message)

    @staticmethod
    def _is_rate_limit_error(message: str) -> bool:
        text = message.lower()
        return any(token in text for token in (
            "too many requests", "rate limit exceeded", "requests per minute",
        ))

    def mark_quota_exhausted(self, message: str) -> None:
        self.last_error = message
        self._quota_exhausted_until = self.next_reset_at()

    def clear_quota_lock(self) -> None:
        self._quota_exhausted_until = None
        self.last_error = None

    def quota_is_exhausted(self) -> bool:
        if not self._quota_exhausted_until:
            return False
        if datetime.now(self.RESET_TZ) >= self._quota_exhausted_until:
            self.clear_quota_lock()
            return False
        return True

    def _remaining_from_headers(self) -> int | None:
        candidates = (
            "x-ratelimit-requests-remaining",  # daily allowance on API-Sports
            "x-ratelimit-remaining",
        )
        for key in candidates:
            raw = self.last_headers.get(key)
            if raw is None:
                continue
            try:
                return int(raw)
            except ValueError:
                continue
        return None

    def can_spend(self, estimated_requests: int, *, reserve: int = 10) -> bool:
        remaining = self._remaining_from_headers()
        if remaining is None:
            return not self.quota_is_exhausted()
        return remaining - max(0, int(estimated_requests)) >= max(0, int(reserve))

    async def get(self, endpoint: str, params: dict[str, Any], *, cache: bool = True) -> dict[str, Any]:
        if not self.settings.api_configured:
            raise ApiFootballError("API_FOOTBALL_KEY belum diatur di Render Environment.")
        if self.quota_is_exhausted():
            reset = self._quota_exhausted_until.strftime("%d-%m-%Y %H:%M WITA") if self._quota_exhausted_until else "08:00 WITA"
            raise ApiFootballError(f"Daily quota exceeded. Request dihentikan sampai {reset}.")

        key = self._cache_key(endpoint, params)
        cached = self._cache.get(key)
        now = time.monotonic()
        if cache and cached and cached.expires_at > now:
            self.cache_hits += 1
            self.endpoint_cache_hits[endpoint] = self.endpoint_cache_hits.get(endpoint, 0) + 1
            return cached.value
        if cache:
            self.cache_misses += 1

        headers = {"x-apisports-key": self.settings.api_football_key}
        url = f"{self.settings.api_football_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(url, headers=headers, params=params)
                self.requests_this_process += 1
                self.endpoint_requests[endpoint] = self.endpoint_requests.get(endpoint, 0) + 1
                self.last_headers = {k.lower(): v for k, v in response.headers.items()}
                response_text = response.text or ""
                if response.status_code == 429:
                    if self._is_daily_quota_error(response_text):
                        self.mark_quota_exhausted(response_text)
                        raise ApiFootballError("Daily quota exceeded")
                    raise ApiFootballError("Rate limit per menit tercapai. Coba lagi sesaat.")
                response.raise_for_status()
                payload = response.json()
                if payload.get("errors"):
                    message = str(payload["errors"])
                    if self._is_daily_quota_error(message):
                        self.mark_quota_exhausted(message)
                    raise ApiFootballError(message)
                self.last_error = None
                if cache:
                    self._cache[key] = CacheItem(
                        expires_at=time.monotonic() + self._ttl_for(endpoint, params),
                        value=payload,
                    )
                return payload
            except (httpx.HTTPError, ValueError, ApiFootballError) as exc:
                last_error = exc
                text = str(exc)
                if isinstance(exc, ApiFootballError) and self.quota_is_exhausted():
                    break
                # Do not retry permanent/authentication errors; retry temporary failures only.
                if isinstance(exc, ApiFootballError) and not self._is_rate_limit_error(text):
                    break
                if attempt < 2:
                    await asyncio.sleep(0.8 * (attempt + 1))
        raise ApiFootballError(f"Gagal menghubungi API-Football: {last_error}")

    async def safe_get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self.get(endpoint, params)
        except ApiFootballError:
            return {"response": [], "paging": {}, "results": 0}

    async def fixtures_by_date(self, date_value: str) -> dict[str, Any]:
        return await self.get("fixtures", {"date": date_value, "timezone": self.settings.timezone})

    async def fixture_by_id(self, fixture_id: int, *, fresh: bool = False) -> dict[str, Any]:
        # Settlement must be able to bypass a cached pre-match NS/PST response.
        return await self.get(
            "fixtures",
            {"id": fixture_id, "timezone": self.settings.timezone},
            cache=not fresh,
        )

    async def prediction_by_fixture(self, fixture_id: int) -> dict[str, Any]:
        return await self.safe_get("predictions", {"fixture": fixture_id})

    async def team_statistics(self, league_id: int, season: int, team_id: int) -> dict[str, Any]:
        return await self.safe_get("teams/statistics", {"league": league_id, "season": season, "team": team_id})

    async def recent_fixtures(self, team_id: int, last: int = 10) -> dict[str, Any]:
        return await self.safe_get("fixtures", {"team": team_id, "last": last, "timezone": self.settings.timezone})

    async def head_to_head(self, home_id: int, away_id: int, last: int = 10) -> dict[str, Any]:
        return await self.safe_get("fixtures/headtohead", {"h2h": f"{home_id}-{away_id}", "last": last})

    async def standings(self, league_id: int, season: int) -> dict[str, Any]:
        return await self.safe_get("standings", {"league": league_id, "season": season})

    async def injuries(self, fixture_id: int) -> dict[str, Any]:
        return await self.safe_get("injuries", {"fixture": fixture_id})

    async def lineups(self, fixture_id: int) -> dict[str, Any]:
        return await self.safe_get("fixtures/lineups", {"fixture": fixture_id})

    async def odds(self, fixture_id: int) -> dict[str, Any]:
        return await self.safe_get("odds", {"fixture": fixture_id})

    def usage_snapshot(self) -> dict[str, Any]:
        total_lookups = self.cache_hits + self.cache_misses
        hit_rate = round(self.cache_hits / total_lookups * 100, 1) if total_lookups else 0.0
        return {
            "network_requests": self.requests_this_process,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": hit_rate,
            "endpoint_requests": dict(sorted(self.endpoint_requests.items())),
            "endpoint_cache_hits": dict(sorted(self.endpoint_cache_hits.items())),
        }

    def quota_status(self) -> dict[str, Any]:
        reset_at = self._quota_exhausted_until or self.next_reset_at()
        remaining = self._remaining_from_headers()
        status = "EXHAUSTED" if self.quota_is_exhausted() else ("LOW" if remaining is not None and remaining <= 20 else "ACTIVE")
        return {
            "limit": self.last_headers.get("x-ratelimit-requests-limit") or self.last_headers.get("x-ratelimit-limit"),
            "remaining": remaining,
            "status": status,
            "reset_at": reset_at.strftime("%d-%m-%Y %H:%M WITA"),
            "reset_hour": "08:00 WITA",
            "last_error": self.last_error,
            "requests_this_process": self.requests_this_process,
            "usage": self.usage_snapshot(),
        }
