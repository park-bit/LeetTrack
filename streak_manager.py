"""
streak_manager.py
-----------------
Maintains current and longest streaks for every monitored user.

Logic:
  - A "day" is defined by the local date (in the configured timezone).
  - If a user solved at least one problem today, their streak increments.
  - If they missed yesterday (and it wasn't already counted), the streak resets to 0.
  - The longest streak is updated whenever current exceeds it.
  - All streak data is persisted via StateManager.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from state_manager import StateManager

logger = logging.getLogger(__name__)


class StreakManager:
    """
    Updates and queries streaks for all users.

    Usage::

        sm = StateManager(); sm.load()
        import pytz
        from datetime import datetime
        import config
        tz = pytz.timezone(config.TIMEZONE)
        streak_mgr.update("Parth", solved_today=True, today=datetime.now(tz).date())
        current, longest = streak_mgr.get("Parth")
    """

    def __init__(self, state: StateManager) -> None:
        self._state = state

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(
        self,
        username: str,
        solved_today: bool,
        today: date,
    ) -> None:
        """
        Update streak for *username* based on whether they solved problems today.

        This should be called once per day per user after the daily fetch.
        """
        streak_data: dict[str, Any] = self._state.get_streak(username)
        current: int = streak_data["current"]
        longest: int = streak_data["longest"]
        last_active_raw: str | None = streak_data["last_active_date"]

        last_active: date | None = None
        if last_active_raw:
            try:
                last_active = date.fromisoformat(last_active_raw)
            except ValueError:
                last_active = None

        if solved_today:
            if last_active is None:
                # First ever solve
                current = 1
            elif last_active == today:
                # Already counted today (shouldn't normally happen, but safe)
                pass
            elif last_active == today - timedelta(days=1):
                # Consecutive day
                current += 1
            else:
                # Missed one or more days — streak reset
                current = 1

            if current > longest:
                longest = current
            last_active = today

        else:
            # No solve today
            if last_active is not None and last_active < today - timedelta(days=1):
                # Missed yesterday — break the streak
                current = 0
            # If last_active == yesterday or today, streak stays intact
            # (user hasn't had a chance to solve today yet, but since this
            #  runs at midnight we know today is over — streak broken)
            elif last_active is not None and last_active < today:
                current = 0

        streak_data["current"] = current
        streak_data["longest"] = longest
        streak_data["last_active_date"] = (
            last_active.isoformat() if last_active else None
        )
        self._state.set_streak(username, streak_data)

        logger.info(
            "Streak updated for %s: current=%d, longest=%d, last_active=%s",
            username,
            current,
            longest,
            last_active,
        )

    def update_all(
        self,
        solve_counts: dict[str, int],
        today: date,
    ) -> None:
        """
        Update streaks for all users.

        Args:
            solve_counts: Mapping of ``{display_name: problems_solved_today}``.
            today: The local date representing today.
        """
        for username, count in solve_counts.items():
            self.update(username, solved_today=count > 0, today=today)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get(self, username: str) -> tuple[int, int]:
        """Return ``(current_streak, longest_streak)`` for *username*."""
        data = self._state.get_streak(username)
        return data["current"], data["longest"]

    def get_current(self, username: str) -> int:
        """Return the current streak for *username*."""
        return self._state.get_streak(username)["current"]

    def get_longest(self, username: str) -> int:
        """Return the longest streak for *username*."""
        return self._state.get_streak(username)["longest"]

    def get_all_streaks(self) -> dict[str, dict[str, int]]:
        """
        Return a summary of all tracked streaks.

        Returns::

            {
                "Parth": {"current": 17, "longest": 31},
                ...
            }
        """
        result: dict[str, dict[str, int]] = {}
        for username in self._state.all_usernames():
            current, longest = self.get(username)
            result[username] = {"current": current, "longest": longest}
        return result
