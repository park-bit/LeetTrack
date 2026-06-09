"""
leetcode_fetcher.py
-------------------
Async LeetCode data fetcher.

Strategy (in priority order):
  1. LeetCode GraphQL API (preferred — official, structured)
  2. REST fallback endpoints where GraphQL is insufficient
  3. Minimal scraping fallback for public profile pages

Features:
  - Async HTTP via aiohttp
  - Session reuse across requests
  - Per-user rate limiting delay
  - Exponential backoff retries
  - Timeout handling
  - Structured response models (dataclasses)
  - Graceful per-user failure isolation
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Submission:
    """Represents a single accepted LeetCode submission."""

    slug: str           # problem slug, e.g. "two-sum"
    title: str          # human-readable title, e.g. "Two Sum"
    difficulty: str     # "Easy" | "Medium" | "Hard"
    timestamp: int      # Unix timestamp of submission
    url: str            # canonical problem URL
    lang: str = ""      # programming language used
    tags: list[str] = field(default_factory=list)  # e.g. ["Array", "Hash Table"]


@dataclass
class UserStats:
    """Aggregated statistics for a LeetCode user."""

    username: str
    total_solved: int = 0
    easy_solved: int = 0
    medium_solved: int = 0
    hard_solved: int = 0
    acceptance_rate: float = 0.0
    ranking: int = 0
    streak: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# GraphQL queries
# ---------------------------------------------------------------------------

_RECENT_AC_QUERY = """
query recentAcSubmissions($username: String!, $limit: Int!) {
  recentAcSubmissionList(username: $username, limit: $limit) {
    id
    title
    titleSlug
    timestamp
    lang
  }
}
"""

_USER_PROFILE_QUERY = """
query userPublicProfile($username: String!) {
  matchedUser(username: $username) {
    username
    submitStats: submitStatsGlobal {
      acSubmissionNum {
        difficulty
        count
        submissions
      }
    }
    userCalendar {
      streak
    }
  }
}
"""

_PROBLEM_DETAIL_QUERY = """
query problemDetail($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionId
    title
    titleSlug
    difficulty
    topicTags {
      name
    }
  }
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_username(leetcode_url: str) -> str:
    """
    Extract LeetCode username from a profile URL.

    Supports:
      - https://leetcode.com/u/username/
      - https://leetcode.com/username/
      - username (plain)
    """
    url = leetcode_url.strip().rstrip("/")
    # Pattern: /u/username or /username at end
    match = re.search(r"/u/([^/]+)$", url) or re.search(r"/([^/]+)$", url)
    if match:
        return match.group(1)
    # Assume raw username was passed
    return url


def _problem_url(slug: str) -> str:
    return f"{config.LEETCODE_BASE_URL}/problems/{slug}/"


async def _sleep_backoff(attempt: int) -> None:
    """Sleep for exponential backoff duration."""
    delay = min(
        config.RETRY_BASE_DELAY * (2 ** attempt),
        config.RETRY_MAX_DELAY,
    )
    logger.debug("Backoff sleep %.1fs (attempt %d).", delay, attempt + 1)
    await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# LeetCodeFetcher
# ---------------------------------------------------------------------------


class LeetCodeFetcher:
    """
    Async HTTP client for fetching LeetCode data.

    Intended to be used as an async context manager::

        async with LeetCodeFetcher() as fetcher:
            subs = await fetcher.get_accepted_submissions("username")
    """

    _HEADERS: dict[str, str] = {
        "Content-Type": "application/json",
        "Referer": "https://leetcode.com",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        # Cache full problem info to reduce GraphQL calls
        # {slug: {"difficulty": str, "tags": list[str]}}
        self._problem_cache: dict[str, dict[str, Any]] = {}

    async def __aenter__(self) -> "LeetCodeFetcher":
        timeout = aiohttp.ClientTimeout(total=config.REQUEST_TIMEOUT)
        connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
        self._session = aiohttp.ClientSession(
            headers=self._HEADERS,
            timeout=timeout,
            connector=connector,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Internal request helpers
    # ------------------------------------------------------------------

    async def _graphql(
        self,
        query: str,
        variables: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Execute a GraphQL query against the LeetCode API."""
        if self._session is None:
            raise RuntimeError("Use LeetCodeFetcher as an async context manager.")

        payload = {"query": query, "variables": variables}
        last_exc: Exception | None = None

        for attempt in range(config.MAX_RETRIES):
            try:
                async with self._session.post(
                    config.LEETCODE_GRAPHQL_URL,
                    json=payload,
                ) as resp:
                    if resp.status == 429:
                        logger.warning("Rate limited by LeetCode (attempt %d).", attempt + 1)
                        await _sleep_backoff(attempt)
                        continue
                    if resp.status != 200:
                        logger.warning(
                            "GraphQL returned HTTP %d (attempt %d).",
                            resp.status,
                            attempt + 1,
                        )
                        await _sleep_backoff(attempt)
                        continue
                    data = await resp.json(content_type=None)
                    if "errors" in data:
                        logger.warning("GraphQL errors: %s", data["errors"])
                        return None
                    return data.get("data")
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                logger.warning(
                    "Request error (attempt %d): %s", attempt + 1, exc
                )
                await _sleep_backoff(attempt)

        logger.error("All %d GraphQL attempts failed. Last: %s", config.MAX_RETRIES, last_exc)
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_recent_submissions(
        self,
        leetcode_url: str,
        limit: int = config.RECENT_SUBMISSIONS_LIMIT,
    ) -> list[Submission]:
        """
        Fetch the *limit* most recent **accepted** submissions for a user.

        Returns an empty list on failure (does not propagate exceptions).
        """
        username = _extract_username(leetcode_url)
        logger.debug("Fetching recent submissions for %s (limit=%d).", username, limit)

        data = await self._graphql(
            _RECENT_AC_QUERY,
            {"username": username, "limit": limit},
        )
        if not data:
            logger.warning("No GraphQL data returned for %s.", username)
            return []

        raw_list = data.get("recentAcSubmissionList") or []
        submissions: list[Submission] = []

        for raw in raw_list:
            slug = raw.get("titleSlug", "")
            title = raw.get("title", slug)
            difficulty, tags = await self._get_problem_info(slug)
            timestamp = int(raw.get("timestamp", 0))
            lang = raw.get("lang", "")
            submissions.append(
                Submission(
                    slug=slug,
                    title=title,
                    difficulty=difficulty,
                    timestamp=timestamp,
                    url=_problem_url(slug),
                    lang=lang,
                    tags=tags,
                )
            )

        logger.info(
            "Fetched %d accepted submissions for %s.", len(submissions), username
        )
        return submissions

    async def get_accepted_submissions(
        self,
        leetcode_url: str,
    ) -> list[Submission]:
        """Alias for get_recent_submissions with default limit."""
        return await self.get_recent_submissions(leetcode_url)

    async def get_today_submissions(
        self,
        leetcode_url: str,
        today_start_ts: int,
        today_end_ts: int,
    ) -> list[Submission]:
        """
        Return accepted submissions whose timestamp falls within
        [*today_start_ts*, *today_end_ts*].
        """
        all_subs = await self.get_recent_submissions(leetcode_url)
        return [
            s for s in all_subs
            if today_start_ts <= s.timestamp < today_end_ts
        ]

    async def get_user_stats(self, leetcode_url: str) -> UserStats | None:
        """
        Return aggregated stats for a user from the public profile.
        Returns None on failure.
        """
        username = _extract_username(leetcode_url)
        logger.debug("Fetching user stats for %s.", username)

        data = await self._graphql(_USER_PROFILE_QUERY, {"username": username})
        if not data:
            return None

        matched = data.get("matchedUser")
        if not matched:
            logger.warning("LeetCode user not found: %s", username)
            return None

        stats = UserStats(username=username, raw=data)

        # Parse accepted counts per difficulty
        ac_list: list[dict[str, Any]] = (
            matched.get("submitStats", {}).get("acSubmissionNum", [])
        )
        for item in ac_list:
            difficulty = item.get("difficulty", "").lower()
            count = item.get("count", 0)
            if difficulty == "all":
                stats.total_solved = count
            elif difficulty == "easy":
                stats.easy_solved = count
            elif difficulty == "medium":
                stats.medium_solved = count
            elif difficulty == "hard":
                stats.hard_solved = count

        # Streak
        calendar = matched.get("userCalendar") or {}
        stats.streak = calendar.get("streak", 0)

        return stats

    async def get_problem_details(self, slug: str) -> dict[str, Any] | None:
        """Return raw question details for a given slug."""
        data = await self._graphql(_PROBLEM_DETAIL_QUERY, {"titleSlug": slug})
        if not data:
            return None
        return data.get("question")

    # ------------------------------------------------------------------
    # Problem info cache (difficulty + topic tags)
    # ------------------------------------------------------------------

    async def _get_problem_info(self, slug: str) -> tuple[str, list[str]]:
        """
        Return ``(difficulty, tags)`` for *slug*, using cache to save API calls.

        *tags* is a list of topic tag names, e.g. ``["Array", "Hash Table"]``.
        """
        if slug in self._problem_cache:
            cached = self._problem_cache[slug]
            return cached["difficulty"], cached["tags"]

        details = await self.get_problem_details(slug)
        if details:
            difficulty = details.get("difficulty", "Unknown")
            tags = [t["name"] for t in details.get("topicTags", [])]
        else:
            difficulty = "Unknown"
            tags = []

        self._problem_cache[slug] = {"difficulty": difficulty, "tags": tags}
        # Small delay to avoid hammering the API
        await asyncio.sleep(0.3)
        return difficulty, tags

    # ------------------------------------------------------------------
    # Batch multi-user fetch
    # ------------------------------------------------------------------

    async def fetch_all_users(
        self,
        profiles: list[dict[str, Any]],
    ) -> dict[str, tuple[list[Submission], UserStats | None]]:
        """
        Fetch recent accepted submissions and exact user stats for all enabled profiles in parallel.
        Returns a mapping of ``{display_name: (list[Submission], UserStats | None)}``.
        """
        results: dict[str, tuple[list[Submission], UserStats | None]] = {}
        sem = asyncio.Semaphore(5)

        async def _fetch(profile: dict[str, Any]) -> None:
            if not profile.get("enabled", True):
                return
            name = profile["name"]
            url = profile["leetcode_url"]
            async with sem:
                try:
                    # Request up to 100 (though LeetCode internally caps at 15-20)
                    subs = await self.get_recent_submissions(url, limit=100)
                    stats = await self.get_user_stats(url)
                    results[name] = (subs, stats)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Failed to fetch data for %s: %s", name, exc)
                    results[name] = ([], None)

        await asyncio.gather(*[_fetch(p) for p in profiles])
        return results
