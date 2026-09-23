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
        "guilds": {},                # {guild_id: {channel_id, potd_channel_id, potd_enabled, current_message_id}}
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
        """Return the fallback Discord report message ID, or None."""
        val = self._state.get("current_message_id")
        return int(val) if val is not None else None

    def set_message_id(self, message_id: int | None) -> None:
        self._state["current_message_id"] = message_id

    # ------------------------------------------------------------------
    # Guild / Server Management
    # ------------------------------------------------------------------

    def get_guild_config(self, guild_id: int | str) -> dict[str, Any]:
        """Return the configuration dict for a guild."""
        guilds = self._state.setdefault("guilds", {})
        gid = str(guild_id)
        return guilds.setdefault(
            gid,
            {
                "channel_id": None,
                "potd_channel_id": None,
                "potd_enabled": True,
                "current_message_id": None,
                "potd_message_id": None,
            },
        )

    def set_guild_channel(self, guild_id: int | str, channel_id: int) -> None:
        """Set the main report channel for a guild."""
        cfg = self.get_guild_config(guild_id)
        cfg["channel_id"] = int(channel_id)
        self.save()

    def set_guild_potd(
        self,
        guild_id: int | str,
        channel_id: int | None,
        enabled: bool = True,
    ) -> None:
        """Set the POTD channel and enable/disable flag for a guild."""
        cfg = self.get_guild_config(guild_id)
        cfg["potd_channel_id"] = int(channel_id) if channel_id is not None else None
        cfg["potd_enabled"] = bool(enabled)
        self.save()

    def get_guild_message_id(self, guild_id: int | str) -> int | None:
        """Get the current report message ID for a guild."""
        cfg = self.get_guild_config(guild_id)
        val = cfg.get("current_message_id")
        return int(val) if val is not None else None

    def set_guild_message_id(self, guild_id: int | str, message_id: int | None) -> None:
        """Set the current report message ID for a guild."""
        cfg = self.get_guild_config(guild_id)
        cfg["current_message_id"] = int(message_id) if message_id is not None else None
        self.save()

    def get_guild_potd_message_id(self, guild_id: int | str) -> int | None:
        """Get the last posted POTD message ID for a guild."""
        cfg = self.get_guild_config(guild_id)
        val = cfg.get("potd_message_id")
        return int(val) if val is not None else None

    def set_guild_potd_message_id(self, guild_id: int | str, message_id: int | None) -> None:
        """Set the last posted POTD message ID for a guild."""
        cfg = self.get_guild_config(guild_id)
        cfg["potd_message_id"] = int(message_id) if message_id is not None else None
        self.save()

    def get_all_guild_configs(self) -> dict[str, dict[str, Any]]:
        """Return all stored guild configurations."""
        return self._state.setdefault("guilds", {})

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
    # Utility & Admin
    # ------------------------------------------------------------------

    def all_usernames(self) -> list[str]:
        """Return all usernames that have at least some stats stored."""
        return list(self._user_stats.keys())

    def rename_user(self, old_name: str, new_name: str) -> bool:
        """
        Migrate user stats, streaks, history, and monthly leaderboard keys
        when a user's display name is updated.
        """
        if old_name == new_name:
            return False

        changed = False
        if old_name in self._user_stats:
            self._user_stats[new_name] = self._user_stats.pop(old_name)
            changed = True

        if old_name in self._streaks:
            self._streaks[new_name] = self._streaks.pop(old_name)
            changed = True

        if old_name in self._history:
            self._history[new_name] = self._history.pop(old_name)
            changed = True

        monthly = self._state.get("monthly_leaderboard", {})
        if old_name in monthly:
            monthly[new_name] = monthly.pop(old_name)
            changed = True

        if changed:
            self.save()
            logger.info("Migrated state for renamed user: '%s' -> '%s'", old_name, new_name)
        return changed

    def set_user_streak(
        self,
        username: str,
        current: int,
        longest: int | None = None,
        last_active_date: str | None = None,
    ) -> None:
        """Set a user's current/longest streak directly."""
        streak = self.get_streak(username)
        streak["current"] = current
        if longest is not None:
            streak["longest"] = longest
        elif current > streak.get("longest", 0):
            streak["longest"] = current
        if last_active_date is not None:
            streak["last_active_date"] = last_active_date
        self.set_streak(username, streak)
        self.save()
