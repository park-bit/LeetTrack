"""
formatter.py
------------
Builds Discord Embed objects for the daily report.

Minimal format:
  - Date header (Discord timestamp)
  - Per-user: name, solved count, difficulty breakdown (plain text)
  - Per-user: each problem as "Title (Difficulty) [link]"
  - Inactive users listed at the bottom
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import discord

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Daily report embed  (single embed, no leaderboard, no roadmap, no circles)
# ---------------------------------------------------------------------------


def build_daily_embed(
    today: date,
    today_ts: int,
    profiles: list[dict[str, Any]],
    daily_problems: dict[str, list[dict[str, Any]]],
    daily_stats: dict[str, dict[str, int]],
) -> list[discord.Embed]:
    """
    Build the minimal daily report embed.

    Format per active user::

        **park-bit** <@761809603670441994> — 3 solved (Easy: 1 · Medium: 2 · Hard: 0)
        1. Two Sum (Easy) [Array][Hash Table] [link]
        2. Rotate Array (Medium) [Array][Two Pointers] [link]

    Tags are rendered as bracketed labels sourced from LeetCode's topicTags.
    Discord user mentions are resolved from the discord_id field in profiles.json.
    Inactive users are listed at the bottom.
    Returns a single-element list for API compatibility.
    """
    date_str = today.strftime("%A, %d %B %Y")
    embed = discord.Embed(
        title="📅 Daily LeetCode Report",
        description=f"**{date_str} (IST)**",
        color=config.EMBED_COLOR_DAILY,
    )
    embed.set_footer(text="Updates daily at midnight")

    inactive_names: list[str] = []

    for profile in profiles:
        if not profile.get("enabled", True):
            continue

        name = profile["name"]
        discord_id: str = profile.get("discord_id", "")
        stats = daily_stats.get(name, {"solved": 0, "easy": 0, "medium": 0, "hard": 0})
        problems_today = daily_problems.get(name, [])

        # If the exact delta API lagged behind but we physically saw recent submissions today, fall back
        if stats["solved"] == 0 and len(problems_today) > 0:
            stats = stats.copy()
            stats["solved"] = len(problems_today)

        if stats["solved"] == 0:
            inactive_names.append(name)
            continue

        # Header line: name + optional mention + count + difficulty breakdown
        easy, medium, hard = stats["easy"], stats["medium"], stats["hard"]
        diff_parts: list[str] = []
        if easy:
            diff_parts.append(f"Easy: {easy}")
        if medium:
            diff_parts.append(f"Medium: {medium}")
        if hard:
            diff_parts.append(f"Hard: {hard}")
        diff_str = " · ".join(diff_parts) if diff_parts else "Easy: 0"

        mention = f" <@{discord_id}>" if discord_id else ""
        field_header = f"**{name}**{mention} — {stats['solved']} solved ({diff_str})"

        # Problem lines: "1. Title (Difficulty) [Tag1][Tag2] [link]"
        problem_lines: list[str] = []
        for idx, prob in enumerate(problems_today, start=1):
            slug = prob.get("slug", "")
            title = prob.get("title", slug)
            difficulty = prob.get("difficulty", "Unknown")
            url = prob.get("url", f"https://leetcode.com/problems/{slug}/")
            raw_tags: list[str] = prob.get("tags", [])

            tag_str = "".join(f"[{t}]" for t in raw_tags) if raw_tags else ""
            tag_part = f" `{tag_str}`" if tag_str else ""

            problem_lines.append(
                f"`{idx}.` {title} ({difficulty}){tag_part} [link]({url})"
            )

        field_value = field_header
        if problem_lines:
            field_value += "\n" + "\n".join(problem_lines)

        # Discord field value cap: 1024 chars
        if len(field_value) > 1020:
            field_value = field_value[:1017] + "..."

        embed.add_field(name="\u200b", value=field_value, inline=False)

    # Inactive users
    if inactive_names:
        inactive_mentions: list[str] = []
        for profile in profiles:
            if profile["name"] in inactive_names:
                did = profile.get("discord_id", "")
                inactive_mentions.append(f"<@{did}>" if did else f"`{profile['name']}`")
        embed.add_field(
            name="No submissions today",
            value="  ".join(inactive_mentions),
            inline=False,
        )

    return [embed]


# ---------------------------------------------------------------------------
# Error embed
# ---------------------------------------------------------------------------


def build_error_embed(title: str, description: str) -> discord.Embed:
    """Build a simple error-notification embed."""
    return discord.Embed(
        title=f"❌ {title}",
        description=description,
        color=config.EMBED_COLOR_ERROR,
    )
