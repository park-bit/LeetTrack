"""
roadmap_manager.py
------------------
Manages the curated problem roadmaps loaded from roadmaps/*.json.

roadmap JSON format::

    {
        "contains-duplicate": 1,
        "valid-anagram": 2,
        ...
    }

Keys are problem slugs, values are sequential roadmap numbers.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)


class RoadmapManager:
    """
    Loads roadmaps from roadmaps/ directory.
    """

    def __init__(self) -> None:
        # {sheet_name: {slug: roadmap_number}}
        self._roadmaps: dict[str, dict[str, int]] = {}

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Read all JSON files from the roadmaps directory."""
        dir_path: Path = config.ROADMAPS_DIR
        self._roadmaps.clear()

        if not dir_path.exists() or not dir_path.is_dir():
            logger.warning(
                "Roadmaps directory not found at %s.", dir_path
            )
            return

        for path in dir_path.glob("*.json"):
            sheet_name = path.stem
            try:
                with path.open("r", encoding="utf-8") as fh:
                    raw: Any = json.load(fh)
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Failed to read roadmap %s: %s", path.name, exc)
                continue

            if not isinstance(raw, dict):
                logger.error(
                    "Roadmap %s must be a JSON object.", path.name
                )
                continue

            slug_dict = {}
            for title_or_slug, number in raw.items():
                if not isinstance(title_or_slug, str) or not isinstance(number, int):
                    continue
                slug_dict[title_or_slug.strip().lower()] = number
            
            self._roadmaps[sheet_name] = slug_dict
            logger.info("Loaded roadmap %s with %d problems.", sheet_name, len(slug_dict))

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_roadmap(self, sheet_name: str) -> dict[str, int] | None:
        """Return the dictionary for a specific roadmap."""
        return self._roadmaps.get(sheet_name)

    def get_all_roadmaps(self) -> list[str]:
        """Return a list of available roadmap sheet names."""
        return list(self._roadmaps.keys())

    @property
    def total(self) -> int:
        """Total number of roadmaps loaded."""
        return len(self._roadmaps)

