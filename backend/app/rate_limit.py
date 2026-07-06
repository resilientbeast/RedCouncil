"""
Credit-protection rate limiting for Qwen-consuming endpoints.

Two independent caps, both resetting at UTC midnight:
  - per-user daily cap: fair-use -- stops one enthusiastic visitor from
    hogging the demo
  - global daily cap: a hard ceiling on total spend regardless of how many
    distinct people hit the site -- this is the one that actually protects
    a limited credit balance from a room full of onlookers before judges
    get to it

`unlimited_user_ids` (a comma-separated Clerk user_id list in config) lets
the deployment owner bypass both caps for their own testing without eating
into the same budget everyone else shares.

In-memory counters -- correct and sufficient for a single-instance hackathon
deployment. If this ever runs as multiple replicas, the counters would need
to move to something shared (Redis, or the same Postgres instance store.py
already uses) -- same "in-memory is fine until it isn't" pattern as sse.py
and the original store.py before persistence was added.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class DailyDecisionLimiter:
    def __init__(self) -> None:
        self._day: str = _today()
        self._per_user: dict[str, int] = {}
        self._global: int = 0

    def _maybe_reset(self) -> None:
        today = _today()
        if today != self._day:
            self._day = today
            self._per_user = {}
            self._global = 0

    def check_and_increment(self, user_id: str) -> None:
        """Raises HTTPException(429) if either cap is exceeded; otherwise
        increments both counters and returns. Call this BEFORE starting a
        council run, not after -- the whole point is to stop the Qwen calls
        from happening at all once a cap is hit."""
        self._maybe_reset()

        if user_id in settings.unlimited_user_ids_set:
            return

        if self._global >= settings.max_total_decisions_per_day:
            raise HTTPException(
                429,
                "Daily demo capacity has been reached across all users. Please try again after "
                "midnight UTC, or contact the site owner.",
            )

        user_count = self._per_user.get(user_id, 0)
        if user_count >= settings.max_decisions_per_user_per_day:
            raise HTTPException(
                429,
                f"You've reached today's limit of {settings.max_decisions_per_user_per_day} "
                "council reviews. Please try again tomorrow.",
            )

        self._per_user[user_id] = user_count + 1
        self._global += 1

    def status(self, user_id: str) -> dict:
        """Read-only snapshot, useful for a small usage indicator in the UI
        (e.g. "2/5 reviews used today") -- does not mutate counters."""
        self._maybe_reset()
        unlimited = user_id in settings.unlimited_user_ids_set
        return {
            "unlimited": unlimited,
            "user_used": 0 if unlimited else self._per_user.get(user_id, 0),
            "user_limit": settings.max_decisions_per_user_per_day,
            "global_used": self._global,
            "global_limit": settings.max_total_decisions_per_day,
        }


decision_rate_limiter = DailyDecisionLimiter()
