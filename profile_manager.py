"""
profile_manager.py
------------------
Loads and validates user profiles from profiles.json.

Each profile must have:
  - name        (non-empty string)
  - leetcode_url (valid LeetCode profile URL)
  - enabled     (bool, default True)

Invalid profiles are skipped with a warning.  The bot continues
processing the remaining valid profiles.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import config
from database import DatabaseManager

logger = logging.getLogger(__name__)

_LEETCODE_URL_RE = re.compile(
    r"^https://leetcode\.com/(u/)?[A-Za-z0-9_\-\.]+/?$"
)


def _is_valid_url(url: str) -> bool:
    return bool(_LEETCODE_URL_RE.match(url.strip()))


class ProfileManager:
    """
    Loads, validates, and exposes user profiles.

    Usage::

        pm = ProfileManager()
        pm.load()
        profiles = pm.get_enabled_profiles()
    """

    def __init__(self) -> None:
        self._profiles: list[dict[str, Any]] = []

    def load(self) -> None:
        """Read profiles.json from DB or disk and validate each entry."""
        db = DatabaseManager()
        raw = db.read_data("profiles.json", config.PROFILES_FILE, None)

        if raw is None:
            logger.warning(
                "profiles.json not found in DB or disk. Creating example file locally."
            )
            self._create_example()
            self._profiles = []
            return

        if not isinstance(raw, list):
            logger.error(
                "profiles.json must be a JSON array. Found: %s", type(raw).__name__
            )
            self._profiles = []
            return

        validated: list[dict[str, Any]] = []
        for idx, profile in enumerate(raw):
            result = self._validate_profile(profile, idx)
            if result is not None:
                validated.append(result)

        self._profiles = validated
        logger.info(
            "Loaded %d valid profile(s).", len(validated)
        )

    def _validate_profile(
        self, profile: Any, idx: int
    ) -> dict[str, Any] | None:
        """Return a cleaned profile dict or None if invalid."""
        if not isinstance(profile, dict):
            logger.warning("Profile at index %d is not a dict — skipping.", idx)
            return None

        name = profile.get("name", "").strip()
        if not name:
            logger.warning(
                "Profile at index %d has no 'name' — skipping.", idx
            )
            return None

        url = profile.get("leetcode_url", "").strip()
        if not url:
            logger.warning(
                "Profile '%s' has no 'leetcode_url' — skipping.", name
            )
            return None

        if not _is_valid_url(url):
            logger.warning(
                "Profile '%s' has invalid leetcode_url '%s' — skipping.", name, url
            )
            return None

        enabled = bool(profile.get("enabled", True))
        discord_id = profile.get("discord_id", "").strip()

        return {
            "name": name,
            "leetcode_url": url.rstrip("/") + "/",
            "enabled": enabled,
            "discord_id": discord_id,
        }

    def get_all_profiles(self) -> list[dict[str, Any]]:
        """Return all loaded profiles (including disabled)."""
        return list(self._profiles)

    def get_enabled_profiles(self) -> list[dict[str, Any]]:
        """Return only profiles where enabled=True."""
        return [p for p in self._profiles if p.get("enabled", True)]

    def get_profile_by_name(self, name: str) -> dict[str, Any] | None:
        """Return the first profile whose name matches (case-insensitive)."""
        name_lower = name.lower()
        for p in self._profiles:
            if p["name"].lower() == name_lower:
                return p
        return None

    def get_profile_by_discord_id(self, discord_id: str) -> dict[str, Any] | None:
        """Return the profile matching the given Discord ID, if any."""
        for p in self._profiles:
            if p.get("discord_id") == discord_id:
                return p
        return None

    # ------------------------------------------------------------------
    # Mutation Methods
    # ------------------------------------------------------------------

    def add_profile(self, name: str, leetcode_url: str, discord_id: str) -> bool:
        """
        Add a new profile or update an existing one for the given Discord ID.
        Returns True if successful, False if the URL is invalid.
        """
        if not _is_valid_url(leetcode_url):
            return False

        # Ensure trailing slash
        leetcode_url = leetcode_url.rstrip("/") + "/"

        # Check if they already exist by discord_id
        existing = self.get_profile_by_discord_id(discord_id)
        if existing:
            existing["name"] = name
            existing["leetcode_url"] = leetcode_url
            existing["enabled"] = True
        else:
            self._profiles.append({
                "name": name,
                "leetcode_url": leetcode_url,
                "enabled": True,
                "discord_id": discord_id,
            })

        self.save()
        return True

    def remove_profile(self, discord_id: str) -> bool:
        """
        Remove the profile associated with the given Discord ID.
        Returns True if removed, False if not found.
        """
        initial_count = len(self._profiles)
        self._profiles = [p for p in self._profiles if p.get("discord_id") != discord_id]
        
        if len(self._profiles) < initial_count:
            self.save()
            return True
        return False

    def save(self) -> None:
        """Write the current profiles back to DB or disk."""
        db = DatabaseManager()
        db.write_data("profiles.json", config.PROFILES_FILE, self._profiles)
        logger.info("Saved %d profiles via DatabaseManager", len(self._profiles))

    # ------------------------------------------------------------------
    # Example Generation
    # ------------------------------------------------------------------

    def _create_example(self) -> None:
        """Write an example profiles.json so the user knows the format."""
        example = [
            {
                "name": "Parth",
                "leetcode_url": "https://leetcode.com/u/parth123/",
                "enabled": True,
            },
            {
                "name": "Aman",
                "leetcode_url": "https://leetcode.com/u/aman_dev/",
                "enabled": True,
            },
            {
                "name": "Riya",
                "leetcode_url": "https://leetcode.com/u/riya007/",
                "enabled": True,
            },
        ]
        try:
            with config.PROFILES_FILE.open("w", encoding="utf-8") as fh:
                json.dump(example, fh, indent=2)
            logger.info("Created example profiles.json at %s", config.PROFILES_FILE)
        except OSError as exc:
            logger.error("Could not write example profiles.json: %s", exc)
