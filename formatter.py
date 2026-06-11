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
            is_resubmission = prob.get("is_resubmission", False)

            tag_str = "".join(f"[{t}]" for t in raw_tags) if raw_tags else ""
            tag_part = f" `{tag_str}`" if tag_str else ""
            resub_part = " *(resubmission)*" if is_resubmission else ""

            problem_lines.append(
                f"`{idx}.` {title} ({difficulty}){tag_part}{resub_part} [link]({url})"
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

# ---------------------------------------------------------------------------
# Weekly Aggregate Embed Builder
# ---------------------------------------------------------------------------

def build_weekly_aggregate_embeds(
    profiles: list[dict[str, Any]],
    daily_history: list[tuple[date, dict[str, list[dict[str, Any]]]]],
) -> list[discord.Embed]:
    """
    Builds a list of embeds, one for each day in the provided history.
    Discord allows up to 10 embeds per message, which fits a 7-day week perfectly.
    """
    embeds = []

    user_colors = {
        "park-bit": "🟠",
        "lilght01": "🔵",
        "Yuuta_1678": "🟢",
        "vedant_ghate": "🔴"
    }
    default_color = "🟤"
    
    for d, problems_by_user in daily_history:
        date_str = d.strftime("%A, %d %B %Y")
        embed = discord.Embed(
            title=f"📅 {date_str} (IST)",
            color=config.EMBED_COLOR_DAILY,
        )

        found_any = False
        inactive_names = []

        for p_idx, profile in enumerate(profiles):
            if not profile.get("enabled", True):
                continue

            name = profile["name"]
            discord_id: str = profile.get("discord_id", "")
            problems = problems_by_user.get(name, [])
            
            color_emoji = user_colors.get(name, default_color)

            if not problems:
                inactive_names.append(profile)
                continue

            found_any = True
            
            easy = sum(1 for p in problems if p.get("difficulty") == "Easy")
            medium = sum(1 for p in problems if p.get("difficulty") == "Medium")
            hard = sum(1 for p in problems if p.get("difficulty") == "Hard")

            diff_parts = []
            if easy: diff_parts.append(f"Easy: {easy}")
            if medium: diff_parts.append(f"Med: {medium}")
            if hard: diff_parts.append(f"Hard: {hard}")
            diff_str = " · ".join(diff_parts) if diff_parts else "—"

            # Put color in field name, but NOT the mention (Discord fields don't parse mentions in names)
            field_name = f"{color_emoji} **{name}** — {len(problems)} solved ({diff_str})"

            lines = []
            # Mentions only render in field values!
            if discord_id:
                lines.append(f"👤 <@{discord_id}>")
                
            for idx, prob in enumerate(problems, start=1):
                slug = prob.get("slug", "")
                title = prob.get("title", slug)
                diff = prob.get("difficulty", "Unknown")
                url = prob.get("url", f"https://leetcode.com/problems/{slug}/")
                tags = prob.get("tags", [])
                is_resubmission = prob.get("is_resubmission", False)
                tag_str = "".join(f"[{t}]" for t in tags)
                tag_part = f" `{tag_str}`" if tag_str else ""
                resub_part = " *(resubmission)*" if is_resubmission else ""
                lines.append(f"`{idx}.` {title} ({diff}){tag_part}{resub_part} [link]({url})")

            # Discord field value limit is 1024. Split into chunks to prevent truncation.
            chunks = []
            current_chunk = []
            current_len = 0
            
            for line in lines:
                line_len = len(line) + 1 # +1 for newline
                if current_len + line_len > 1000:
                    chunks.append("\n".join(current_chunk))
                    current_chunk = [line]
                    current_len = line_len
                else:
                    current_chunk.append(line)
                    current_len += line_len
                    
            if current_chunk:
                chunks.append("\n".join(current_chunk))

            for i, chunk_val in enumerate(chunks):
                if i == 0:
                    embed.add_field(name=field_name, value=chunk_val, inline=False)
                else:
                    embed.add_field(name=f"{color_emoji} **{name}** (continued)", value=chunk_val, inline=False)

        if not found_any:
            embed.description = "No submissions recorded for anyone on this date."
        else:
            if inactive_names:
                mentions = []
                for p_idx, p in enumerate(profiles):
                    if p in inactive_names:
                        c_emoji = user_colors.get(p["name"], default_color)
                        if p.get("discord_id"):
                            mentions.append(f"{c_emoji} <@{p['discord_id']}>")
                        else:
                            mentions.append(f"{c_emoji} `{p['name']}`")
                
                # Split into chunks if there are too many inactive users to fit in 1024 chars
                mentions_str = " ".join(mentions)
                if len(mentions_str) > 1024:
                    mentions_str = mentions_str[:1000] + "..."
                    
                embed.add_field(
                    name="No submissions",
                    value=mentions_str,
                    inline=False
                )

        embeds.append(embed)

    if embeds:
        embeds[-1].set_footer(text="Updates daily at midnight. Run /run to sync.")

    return embeds

# ---------------------------------------------------------------------------
# Weekly Summary & Interactive View
# ---------------------------------------------------------------------------

def build_weekly_summary_embed(
    profiles: list[dict[str, Any]],
    daily_history: list[tuple[date, dict[str, list[dict[str, Any]]]]],
) -> discord.Embed:
    """Builds a beautiful summary embed for the entire week."""
    if not daily_history:
        return discord.Embed(title="Weekly Report", description="No data for this week.", color=config.EMBED_COLOR_WEEKLY)
        
    start_date = daily_history[0][0]
    end_date = daily_history[-1][0]
    
    date_range = f"{start_date.strftime('%B %d')} - {end_date.strftime('%B %d, %Y')}"
    
    embed = discord.Embed(
        title="🏆 Weekly LeetCode Summary",
        description=f"**{date_range}**\nUse the dropdown below to view detailed daily submissions!",
        color=config.EMBED_COLOR_WEEKLY,
    )
    
    user_colors = {
        "park-bit": "🟠",
        "lilght01": "🔵",
        "Yuuta_1678": "🟢",
        "vedant_ghate": "🔴"
    }
    default_color = "🟤"
    
    # Calculate totals
    totals = {}
    for p in profiles:
        if p.get("enabled", True):
            totals[p["name"]] = {"solved": 0, "easy": 0, "medium": 0, "hard": 0, "discord_id": p.get("discord_id")}
            
    for d, problems_by_user in daily_history:
        for name, problems in problems_by_user.items():
            if name in totals:
                totals[name]["solved"] += len(problems)
                totals[name]["easy"] += sum(1 for p in problems if p.get("difficulty") == "Easy")
                totals[name]["medium"] += sum(1 for p in problems if p.get("difficulty") == "Medium")
                totals[name]["hard"] += sum(1 for p in problems if p.get("difficulty") == "Hard")

    # Sort by solved descending
    sorted_users = sorted(totals.items(), key=lambda x: x[1]["solved"], reverse=True)
    
    for name, stats in sorted_users:
        if stats["solved"] == 0:
            continue
            
        color_emoji = user_colors.get(name, default_color)
        mention = f"<@{stats['discord_id']}>" if stats["discord_id"] else name
        
        diff_parts = []
        if stats["easy"]: diff_parts.append(f"Easy: {stats['easy']}")
        if stats["medium"]: diff_parts.append(f"Med: {stats['medium']}")
        if stats["hard"]: diff_parts.append(f"Hard: {stats['hard']}")
        diff_str = " · ".join(diff_parts) if diff_parts else "—"
        
        embed.add_field(
            name=f"{color_emoji} {name}",
            value=f"👤 {mention}\n**{stats['solved']} solved** ({diff_str})",
            inline=True
        )
        
    embed.set_footer(text="Updates daily at midnight. Run /run to sync.")
    return embed


class ReportDropdown(discord.ui.Select):
    def __init__(self, bot, summary_embed: discord.Embed, detailed_embeds: list[discord.Embed]):
        self.bot = bot
        self.summary_embed = summary_embed
        self.detailed_embeds = detailed_embeds
        
        options = [
            discord.SelectOption(
                label="Weekly Summary",
                description="Overview of the week's totals",
                emoji="🏆",
                value="summary"
            )
        ]
        
        for i, embed in enumerate(detailed_embeds):
            # Extract date from embed title "📅 Monday, 08 June 2026 (IST)"
            title = embed.title.replace("📅 ", "").replace(" (IST)", "")
            options.append(
                discord.SelectOption(
                    label=title[:100],
                    description=f"Detailed submissions for {title.split(',')[0]}",
                    emoji="📅",
                    value=str(i)
                )
            )
            
        # Discord limits select options to 25.
        super().__init__(placeholder="Select a day to view details...", min_values=1, max_values=1, options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        # Defer response immediately since fetching LeetCode can take time
        await interaction.response.defer(ephemeral=True)

        if self.values[0] == "summary":
            await interaction.followup.send(embed=self.summary_embed, ephemeral=True)
            return

        import time
        now = time.time()
        
        # Enforce a 60-second cooldown on LeetCode API fetches
        if not hasattr(self.bot, "_last_dropdown_sync"):
            self.bot._last_dropdown_sync = 0
            
        if now - self.bot._last_dropdown_sync > 60:
            self.bot._last_dropdown_sync = now
            # Run background sync which fetches data and updates the main message natively
            try:
                new_summary, new_detailed = await self.bot.scheduler.run_daily_job(force_new_message=False)
                self.summary_embed = new_summary
                self.detailed_embeds = new_detailed
            except Exception as e:
                logger.error("Error during dropdown sync: %s", e)
        
        idx = int(self.values[0])
        await interaction.followup.send(embed=self.detailed_embeds[idx], ephemeral=True)

class ReportView(discord.ui.View):
    def __init__(self, bot, summary_embed: discord.Embed, detailed_embeds: list[discord.Embed]):
        super().__init__(timeout=None)
        self.add_item(ReportDropdown(bot, summary_embed, detailed_embeds))
