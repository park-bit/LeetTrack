"""
roadmap_manager.py
------------------
Manages the curated problem roadmap loaded from roadmap.json.

roadmap.json format::

    {
        "Build Array from Permutation": 1,
        "Concatenation of Array": 2,
        ...
    }

Keys are problem titles (as shown on LeetCode), values are sequential
roadmap numbers.  Matching is done case-insensitively against both
problem title and slug.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)


def _title_to_slug(title: str) -> str:
    """Convert a display title to a LeetCode-style slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())
    return slug.strip("-")


class RoadmapManager:
    """
    Loads roadmap.json and provides matching/progress utilities.

    Usage::

        rm = RoadmapManager()
        rm.load()
        number = rm.get_problem_number("Two Sum")   # returns 1 (or None)
        progress = rm.compute_progress(["Two Sum", "Add Two Numbers"])
    """

    def __init__(self) -> None:
        # {normalised_title: roadmap_number}
        self._by_title: dict[str, int] = {}
        # {slug: roadmap_number}
        self._by_slug: dict[str, int] = {}
        # {roadmap_number: original_title}
        self._number_to_title: dict[int, str] = {}
        self._total: int = 0

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Read roadmap.json and build lookup structures."""
        path: Path = config.ROADMAP_FILE

        if not path.exists():
            logger.warning(
                "roadmap.json not found at %s — roadmap tracking disabled.", path
            )
            self._total = 0
            return

        try:
            with path.open("r", encoding="utf-8") as fh:
                raw: Any = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to read roadmap.json: %s", exc)
            return

        if not isinstance(raw, dict):
            logger.error(
                "roadmap.json must be a JSON object. Found: %s", type(raw).__name__
            )
            return

        self._by_title.clear()
        self._by_slug.clear()
        self._number_to_title.clear()

        for title, number in raw.items():
            if not isinstance(title, str) or not isinstance(number, int):
                logger.warning(
                    "Skipping invalid roadmap entry: %r -> %r", title, number
                )
                continue
            key = title.strip().lower()
            slug = _title_to_slug(title)
            self._by_title[key] = number
            self._by_slug[slug] = number
            self._number_to_title[number] = title.strip()

        self._total = len(self._by_title)
        logger.info("Loaded %d roadmap problems.", self._total)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_problem_number(self, title: str) -> int | None:
        """Return roadmap number for a problem *title*, or None if not in roadmap."""
        return self._by_title.get(title.strip().lower())

    def get_problem_number_by_slug(self, slug: str) -> int | None:
        """Return roadmap number for a problem *slug*, or None if not in roadmap."""
        return self._by_slug.get(slug.lower().strip())

    def get_roadmap_title(self, number: int) -> str | None:
        """Return the original problem title for a roadmap *number*."""
        return self._number_to_title.get(number)

    @property
    def total(self) -> int:
        """Total number of problems in the roadmap."""
        return self._total

    # ------------------------------------------------------------------
    # Progress computation
    # ------------------------------------------------------------------

    def compute_progress(
        self,
        solved_slugs: list[str],
        solved_titles: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Compute roadmap progress given lists of solved slugs (and optionally titles).

        Returns::

            {
                "completed": int,
                "total": int,
                "percentage": float,
                "solved_roadmap_items": [
                    {"number": int, "title": str},
                    ...
                ],
            }
        """
        solved_roadmap: list[dict[str, Any]] = []
        seen: set[int] = set()

        # Match by slug
        for slug in solved_slugs:
            number = self.get_problem_number_by_slug(slug)
            if number is not None and number not in seen:
                seen.add(number)
                solved_roadmap.append(
                    {"number": number, "title": self._number_to_title[number]}
                )

        # Match by title (fallback / additional)
        if solved_titles:
            for title in solved_titles:
                number = self.get_problem_number(title)
                if number is not None and number not in seen:
                    seen.add(number)
                    solved_roadmap.append(
                        {"number": number, "title": self._number_to_title[number]}
                    )

        solved_roadmap.sort(key=lambda x: x["number"])
        completed = len(solved_roadmap)
        percentage = (completed / self._total * 100) if self._total else 0.0

        return {
            "completed": completed,
            "total": self._total,
            "percentage": round(percentage, 1),
            "solved_roadmap_items": solved_roadmap,
        }

    def filter_today_roadmap(
        self,
        today_slugs: list[str],
        today_titles: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return roadmap items solved today.

        Returns a sorted list of ``{"number": int, "title": str}`` dicts.
        """
        seen: set[int] = set()
        items: list[dict[str, Any]] = []

        for slug in today_slugs:
            number = self.get_problem_number_by_slug(slug)
            if number is not None and number not in seen:
                seen.add(number)
                items.append(
                    {"number": number, "title": self._number_to_title[number]}
                )

        if today_titles:
            for title in today_titles:
                number = self.get_problem_number(title)
                if number is not None and number not in seen:
                    seen.add(number)
                    items.append(
                        {"number": number, "title": self._number_to_title[number]}
                    )

        items.sort(key=lambda x: x["number"])
        return items
