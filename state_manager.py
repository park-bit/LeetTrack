"""
state_manager.py
----------------
Manages all persistent state for the bot.

Stores and retrieves:
  - current Discord message ID
  - week start date
  - last run timestamp
  - daily / weekly / monthly stats
  - streaks
  - leaderboard snapshots
  - history

All data is kept in state.json (top-level key/value store) and
supplementary JSON files under data/.  Gracefully handles corrupted
or missing files by recreating defaults.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)


from database import DatabaseManager

# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------

class StateManager:
    """
    Singleton-style manager for all persisted bot state.

    Usage::

        sm = StateManager()
        sm.load()
        sm.set_message_id(123456)
        sm.save()
    """

    # Default structure for state.json
    _STATE_DEFAULTS: dict[str, Any] = {
        "current_message_id": None,
        "week_start": None,          # ISO date string, e.g. "2024-06-03"
        "last_run": None,            # ISO datetime string
        "monthly_leaderboard": {},   # {username: total_monthly_count}
    }

    # Default structure for user_stats.json
    _USER_STATS_DEFAULTS: dict[str, Any] = {}

    # Default structure for streaks.json
    _STREAKS_DEFAULTS: dict[str, Any] = {}

    # Default structure for history.json
    _HISTORY_DEFAULTS: dict[str, Any] = {}

    def __init__(self) -> None:
        self._state: dict[str, Any] = {}
        self._user_stats: dict[str, Any] = {}   # {username: {...stats...}}
        self._streaks: dict[str, Any] = {}       # {username: {...streak...}}
        self._history: dict[str, Any] = {}       # {username: {date: [problems]}}

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load all state files from DB or disk."""
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        config.LOGS_DIR.mkdir(parents=True, exist_ok=True)

        db = DatabaseManager()

        self._state = {
            **self._STATE_DEFAULTS,
            **db.read_data("state.json", config.STATE_FILE, {}),
        }
        self._user_stats = db.read_data("user_stats.json", config.USER_STATS_FILE, self._USER_STATS_DEFAULTS)
        self._streaks = db.read_data("streaks.json", config.STREAKS_FILE, self._STREAKS_DEFAULTS)
        self._history = db.read_data("history.json", config.HISTORY_FILE, self._HISTORY_DEFAULTS)

        logger.info("State loaded successfully.")

    def save(self) -> None:
        """Flush all in-memory state to DB or disk."""
        db = DatabaseManager()
        db.write_data("state.json", config.STATE_FILE, self._state)
        db.write_data("user_stats.json", config.USER_STATS_FILE, self._user_stats)
        db.write_data("streaks.json", config.STREAKS_FILE, self._streaks)
        db.write_data("history.json", config.HISTORY_FILE, self._history)
        logger.debug("State saved.")

    # ------------------------------------------------------------------
    # State (state.json top-level keys)
    # ------------------------------------------------------------------

    def get_message_id(self) -> int | None:
        """Return the current Discord report message ID, or None."""
        val = self._state.get("current_message_id")
        return int(val) if val is not None else None

    def set_message_id(self, message_id: int | None) -> None:
        self._state["current_message_id"] = message_id

    def get_week_start(self) -> date | None:
        """Return the Monday that started the current week, or None."""
        val = self._state.get("week_start")
        if val is None:
            return None
        try:
            return date.fromisoformat(val)
        except (ValueError, TypeError):
            return None

    def set_week_start(self, d: date) -> None:
        self._state["week_start"] = d.isoformat()

    def get_last_run(self) -> datetime | None:
        val = self._state.get("last_run")
        if val is None:
            return None
        try:
            return datetime.fromisoformat(val)
        except (ValueError, TypeError):
            return None

    def set_last_run(self, dt: datetime) -> None:
        self._state["last_run"] = dt.isoformat()

    # ------------------------------------------------------------------
    # Monthly leaderboard
    # ------------------------------------------------------------------

    def get_monthly_leaderboard(self) -> dict[str, int]:
        return dict(self._state.get("monthly_leaderboard", {}))

    def update_monthly_leaderboard(self, username: str, delta: int) -> None:
        lb = self._state.setdefault("monthly_leaderboard", {})
        lb[username] = lb.get(username, 0) + delta

    def reset_monthly_leaderboard(self) -> None:
        self._state["monthly_leaderboard"] = {}

    # ------------------------------------------------------------------
    # User stats  (user_stats.json)
    # ------------------------------------------------------------------

    def get_user_stats(self, username: str) -> dict[str, Any]:
        """
        Return stats dict for *username*.  Structure::

            {
                "total_solved": int,
                "easy": int,
                "medium": int,
                "hard": int,
                "weekly_solved": int,
                "weekly_easy": int,
                "weekly_medium": int,
                "weekly_hard": int,
                "daily_solved": int,   # only valid on the day it was updated
                "daily_easy": int,
                "daily_medium": int,
                "daily_hard": int,
                "roadmap_solved": int,
                "last_updated": str,   # ISO date
                "known_accepted": [],  # list of question slugs accepted so far
            }
        """
        return self._user_stats.setdefault(
            username,
            {
                "total_solved": 0,
                "easy": 0,
                "medium": 0,
                "hard": 0,
                "weekly_solved": 0,
                "weekly_easy": 0,
                "weekly_medium": 0,
                "weekly_hard": 0,
                "daily_solved": 0,
                "daily_easy": 0,
                "daily_medium": 0,
                "daily_hard": 0,
                "roadmap_solved": 0,
                "last_updated": None,
                "known_accepted": [],
            },
        )

    def set_user_stats(self, username: str, stats: dict[str, Any]) -> None:
        self._user_stats[username] = stats

    def reset_weekly_stats(self, username: str) -> None:
        stats = self.get_user_stats(username)
        stats["weekly_solved"] = 0
        stats["weekly_easy"] = 0
        stats["weekly_medium"] = 0
        stats["weekly_hard"] = 0

    def reset_daily_stats(self, username: str) -> None:
        stats = self.get_user_stats(username)
        stats["daily_solved"] = 0
        stats["daily_easy"] = 0
        stats["daily_medium"] = 0
        stats["daily_hard"] = 0

    def reset_all_weekly_stats(self) -> None:
        for username in self._user_stats:
            self.reset_weekly_stats(username)

    def reset_all_daily_stats(self) -> None:
        for username in self._user_stats:
            self.reset_daily_stats(username)

    # ------------------------------------------------------------------
    # Streaks  (streaks.json)
    # ------------------------------------------------------------------

    def get_streak(self, username: str) -> dict[str, Any]:
        """
        Return streak dict for *username*.  Structure::

            {
                "current": int,
                "longest": int,
                "last_active_date": str,   # ISO date, last day solved
            }
        """
        return self._streaks.setdefault(
            username,
            {
                "current": 0,
                "longest": 0,
                "last_active_date": None,
            },
        )

    def set_streak(self, username: str, streak: dict[str, Any]) -> None:
        self._streaks[username] = streak

    # ------------------------------------------------------------------
    # History  (history.json)
    # ------------------------------------------------------------------

    def get_history(self, username: str) -> dict[str, list[dict[str, Any]]]:
        """
        Return history dict for *username*.  Structure::

            {
                "2024-06-08": [
                    {"slug": "two-sum", "title": "Two Sum", "difficulty": "Easy",
                     "url": "https://leetcode.com/problems/two-sum/"},
                    ...
                ],
                ...
            }
        """
        return self._history.setdefault(username, {})

    def add_history_entry(
        self,
        username: str,
        date_str: str,
        problem: dict[str, Any],
    ) -> None:
        history = self.get_history(username)
        history.setdefault(date_str, [])
        # Avoid duplicates by slug
        existing_slugs = {p["slug"] for p in history[date_str]}
        if problem["slug"] not in existing_slugs:
            history[date_str].append(problem)

    def get_day_problems(
        self, username: str, date_str: str
    ) -> list[dict[str, Any]]:
        return self.get_history(username).get(date_str, [])

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def all_usernames(self) -> list[str]:
        """Return all usernames that have at least some stats stored."""
        return list(self._user_stats.keys())
