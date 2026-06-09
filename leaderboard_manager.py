"""
leaderboard_manager.py
----------------------
Computes and maintains daily, weekly, and monthly leaderboards.

Ranking criteria (descending priority):
  1. Total accepted problems in the period
  2. More Hard problems
  3. More Medium problems
  4. Username (alphabetical)
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from state_manager import StateManager

logger = logging.getLogger(__name__)


def _rank_key(entry: dict[str, Any]) -> tuple[int, int, int, str]:
    """Comparator key for leaderboard sorting (higher is better for ints)."""
    return (
        -entry.get("solved", 0),
        -entry.get("hard", 0),
        -entry.get("medium", 0),
        entry.get("username", "").lower(),
    )


class LeaderboardManager:
    """
    Builds leaderboard rankings from current state.

    Usage::

        sm = StateManager(); sm.load()
        lb = LeaderboardManager(sm)
        daily = lb.build_daily_leaderboard(profiles)
        weekly = lb.build_weekly_leaderboard(profiles)
    """

    def __init__(self, state: StateManager) -> None:
        self._state = state

    # ------------------------------------------------------------------
    # Daily leaderboard
    # ------------------------------------------------------------------

    def build_daily_leaderboard(
        self, profiles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Build today's leaderboard from daily_solved stats.

        Returns a sorted list::

            [
                {
                    "rank": 1,
                    "username": "Parth",
                    "solved": 5,
                    "easy": 2,
                    "medium": 3,
                    "hard": 0,
                },
                ...
            ]
        """
        entries: list[dict[str, Any]] = []

        for profile in profiles:
            if not profile.get("enabled", True):
                continue
            name = profile["name"]
            stats = self._state.get_user_stats(name)
            entries.append(
                {
                    "username": name,
                    "solved": stats.get("daily_solved", 0),
                    "easy": stats.get("daily_easy", 0),
                    "medium": stats.get("daily_medium", 0),
                    "hard": stats.get("daily_hard", 0),
                }
            )

        entries.sort(key=_rank_key)

        for idx, entry in enumerate(entries, start=1):
            entry["rank"] = idx

        logger.debug("Daily leaderboard built: %d entries.", len(entries))
        return entries

    # ------------------------------------------------------------------
    # Weekly leaderboard
    # ------------------------------------------------------------------

    def build_weekly_leaderboard(
        self, profiles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Build the current week's leaderboard from weekly_solved stats.

        Returns the same structure as the daily leaderboard.
        """
        entries: list[dict[str, Any]] = []

        for profile in profiles:
            if not profile.get("enabled", True):
                continue
            name = profile["name"]
            stats = self._state.get_user_stats(name)
            entries.append(
                {
                    "username": name,
                    "solved": stats.get("weekly_solved", 0),
                    "easy": stats.get("weekly_easy", 0),
                    "medium": stats.get("weekly_medium", 0),
                    "hard": stats.get("weekly_hard", 0),
                }
            )

        entries.sort(key=_rank_key)

        for idx, entry in enumerate(entries, start=1):
            entry["rank"] = idx

        logger.debug("Weekly leaderboard built: %d entries.", len(entries))
        return entries

    # ------------------------------------------------------------------
    # Monthly leaderboard
    # ------------------------------------------------------------------

    def build_monthly_leaderboard(
        self, profiles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Build the current month's leaderboard from the running monthly totals
        stored in state.

        Returns the same structure as the daily leaderboard, but without
        easy/medium/hard breakdown (monthly only tracks total count).
        """
        monthly_data: dict[str, int] = self._state.get_monthly_leaderboard()
        entries: list[dict[str, Any]] = []

        for profile in profiles:
            if not profile.get("enabled", True):
                continue
            name = profile["name"]
            entries.append(
                {
                    "username": name,
                    "solved": monthly_data.get(name, 0),
                    "easy": 0,
                    "medium": 0,
                    "hard": 0,
                }
            )

        entries.sort(key=_rank_key)

        for idx, entry in enumerate(entries, start=1):
            entry["rank"] = idx

        logger.debug("Monthly leaderboard built: %d entries.", len(entries))
        return entries

    # ------------------------------------------------------------------
    # Update helpers (called by the daily job)
    # ------------------------------------------------------------------

    def record_daily_solves(
        self,
        username: str,
        solved: int,
        easy: int,
        medium: int,
        hard: int,
    ) -> None:
        """
        Update weekly and monthly running totals for *username*.

        Daily totals are stored in user_stats and reset each day by the
        scheduler.  Weekly/monthly totals accumulate until explicitly reset.
        """
        stats = self._state.get_user_stats(username)

        # Weekly accumulation
        stats["weekly_solved"] = stats.get("weekly_solved", 0) + solved
        stats["weekly_easy"] = stats.get("weekly_easy", 0) + easy
        stats["weekly_medium"] = stats.get("weekly_medium", 0) + medium
        stats["weekly_hard"] = stats.get("weekly_hard", 0) + hard

        self._state.set_user_stats(username, stats)

        # Monthly accumulation (kept separately in state root)
        self._state.update_monthly_leaderboard(username, solved)

        logger.debug(
            "Recorded %d daily solves for %s (E:%d M:%d H:%d).",
            solved, username, easy, medium, hard,
        )

    def reset_weekly_leaderboard(self, profiles: list[dict[str, Any]]) -> None:
        """Reset all users' weekly counters (called every Monday)."""
        for profile in profiles:
            if profile.get("enabled", True):
                self._state.reset_weekly_stats(profile["name"])
        logger.info("Weekly leaderboard reset for %d users.", len(profiles))

    def reset_monthly_leaderboard(self) -> None:
        """Reset monthly totals (called on the 1st of each month)."""
        self._state.reset_monthly_leaderboard()
        logger.info("Monthly leaderboard reset.")

    # ------------------------------------------------------------------
    # Leaderboard text helpers
    # ------------------------------------------------------------------

    def format_leaderboard_lines(
        self, entries: list[dict[str, Any]], show_zeros: bool = True
    ) -> list[str]:
        """
        Return a list of formatted leaderboard line strings.

        Example::

            ["1. Parth - 5", "2. Aman - 2", "3. Riya - 0"]
        """
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines: list[str] = []
        for entry in entries:
            rank = entry["rank"]
            name = entry["username"]
            solved = entry["solved"]
            if not show_zeros and solved == 0:
                lines.append(f"{rank}. {name} - 0")
            else:
                medal = medals.get(rank, "")
                lines.append(f"{medal} {rank}. {name} - {solved}" if medal else f"{rank}. {name} - {solved}")
        return lines

    def get_inactive_users(
        self, entries: list[dict[str, Any]]
    ) -> list[str]:
        """Return usernames from *entries* who solved 0 problems today."""
        return [e["username"] for e in entries if e.get("solved", 0) == 0]
