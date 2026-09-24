"""
bot.py
------
Entry point for the LeetCode Discord Bot.

Initialises all managers, starts the APScheduler, and connects to
Discord.  Handles graceful shutdown on SIGINT / SIGTERM.

Bot slash commands:
  /status       - Show bot status, last run time, and upcoming schedule.
  /run          - Manually trigger the daily report (owner-only).
  /leaderboard  - Show current weekly leaderboard on demand.
  /weeksummary  - Weekly summary with pie + bar chart.
  /history      - Fetch the LeetCode summary for a specific date.
  /register     - Link your LeetCode profile to your Discord account.
  /unregister   - Remove your profile from the tracker.
  /profile      - View your linked LeetCode profile.
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import signal
import sys
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
import pytz

import config
from state_manager import StateManager
from profile_manager import ProfileManager
from roadmap_manager import RoadmapManager
from streak_manager import StreakManager
from leaderboard_manager import LeaderboardManager
from discord_manager import DiscordManager
from scheduler import DailyScheduler
from duel_manager import DuelManager
from role_manager import RoleManager

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def _setup_logging() -> None:
    """Configure root logger with rotating file + console handlers."""
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        config.LOG_FILE,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)

    root.addHandler(file_handler)
    root.addHandler(console_handler)


# ---------------------------------------------------------------------------
# Bot definition
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


class LeetCodeBot(discord.Client):
    """Main Discord client with slash command tree."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = False  # not needed: we only check message.mentions
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

        # Managers (initialised in setup())
        self.state: StateManager | None = None
        self.profile_manager: ProfileManager | None = None
        self.roadmap_manager: RoadmapManager | None = None
        self.streak_manager: StreakManager | None = None
        self.leaderboard_manager: LeaderboardManager | None = None
        self.discord_manager: DiscordManager | None = None
        self.scheduler: DailyScheduler | None = None
        self.duel_manager: DuelManager | None = None
        self.role_manager: RoleManager | None = None

    async def setup_hook(self) -> None:
        """Called by discord.py before connecting: initialise everything."""
        # Managers
        self.state = StateManager()
        self.state.load()

        self.profile_manager = ProfileManager()
        self.profile_manager.set_state_manager(self.state)
        self.profile_manager.load()

        self.roadmap_manager = RoadmapManager()
        self.roadmap_manager.load()

        self.streak_manager = StreakManager(self.state)
        self.leaderboard_manager = LeaderboardManager(self.state)
        self.discord_manager = DiscordManager(self, self.state)
        self.duel_manager = DuelManager(self)
        self.role_manager = RoleManager(self, self.profile_manager)

        self.scheduler = DailyScheduler(
            state=self.state,
            profile_manager=self.profile_manager,
            roadmap_manager=self.roadmap_manager,
            streak_manager=self.streak_manager,
            leaderboard_manager=self.leaderboard_manager,
            discord_manager=self.discord_manager,
            role_manager=self.role_manager,
        )

        # Register slash commands
        _register_commands(self)

        # Sync slash commands globally
        await self.tree.sync()
        logger.info("Slash commands synced.")

    async def on_ready(self) -> None:
        """Called when the bot has successfully connected to Discord."""
        assert self.scheduler is not None
        assert self.user is not None

        logger.info(
            "Bot connected as %s (ID: %d).", self.user.name, self.user.id
        )

        # Start scheduler
        self.scheduler.start()
        logger.info("Bot is ready and scheduler is running.")

    async def close(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down bot...")
        if self.scheduler:
            self.scheduler.stop()
        if self.state:
            self.state.save()
        await super().close()
        logger.info("Bot shutdown complete.")

    async def on_message(self, message: discord.Message) -> None:
        """
        Respond when a registered user @mentions the bot.

        - Looks up the message author's Discord ID in profiles.json.
        - If found: replies with today's solves, streak, and weekly total.
        - If not found: replies with a friendly "not found" message.
        """
        if message.author.bot:
            return
        if self.user is None or self.user not in message.mentions:
            return
        if self.state is None or self.profile_manager is None or self.streak_manager is None:
            return

        author_id = str(message.author.id)
        profiles  = self.profile_manager.get_enabled_profiles()

        # Find profile by discord_id
        matched = next(
            (p for p in profiles if p.get("discord_id") == author_id),
            None,
        )

        if matched is None:
            await message.reply(
                "❌ **User not found in database.**\n"
                "Your Discord account isn\'t linked to a LeetCode profile.\n"
                "Ask the admin to add you to `profiles.json` with your Discord ID.",
                mention_author=True,
            )
            logger.info("Mention from unknown user %s (%s).", message.author, author_id)
            return

        name = matched["name"]
        stats = self.state.get_user_stats(name)
        current_streak, longest_streak = self.streak_manager.get(name)

        import pytz
        from datetime import datetime, timedelta
        tz = pytz.timezone(config.TIMEZONE)
        today = datetime.now(tz).date()
        today_str = today.isoformat()
        today_problems = self.state.get_day_problems(name, today_str)

        week_start = self.state.get_week_start()
        if week_start:
            delta_days = (today - week_start).days
            if delta_days < 0: delta_days = 0
            dates_in_week = [week_start + timedelta(days=i) for i in range(delta_days + 1)]
        else:
            dates_in_week = [today]
            
        weekly_solved = sum(len(self.state.get_day_problems(name, d.isoformat())) for d in dates_in_week)
        daily_solved = len(today_problems)

        embed = discord.Embed(
            title=f"📊 {name}\'s Stats",
            color=config.EMBED_COLOR_DAILY,
        )
        embed.add_field(
            name="Today",
            value=f"**{daily_solved}** solved",
            inline=True,
        )
        embed.add_field(
            name="This Week",
            value=f"**{weekly_solved}** solved",
            inline=True,
        )
        streak_label = "days" if current_streak != 1 else "day"
        embed.add_field(
            name="🔥 Streak",
            value=f"**{current_streak}** {streak_label}  (longest: {longest_streak})",
            inline=True,
        )

        if today_problems:
            lines = []
            for idx, prob in enumerate(today_problems, start=1):
                title = prob.get("title", prob.get("slug", ""))
                diff  = prob.get("difficulty", "")
                url   = prob.get("url", "")
                tags  = prob.get("tags", [])
                tag_str  = "".join(f"[{t}]" for t in tags)
                tag_part = f" `{tag_str}`" if tag_str else ""
                lines.append(f"`{idx}.` {title} ({diff}){tag_part} [link]({url})")
            embed.add_field(
                name="Today\'s Problems",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(
                name="Today\'s Problems",
                value="_No submissions recorded yet today._",
                inline=False,
            )

        await message.reply(embed=embed, mention_author=True)
        logger.info("Mention stats served for %s (%s).", name, author_id)


# ---------------------------------------------------------------------------
# Slash command registration
# ---------------------------------------------------------------------------


def _register_commands(bot: LeetCodeBot) -> None:
    """Register all slash commands on the bot's command tree."""

    @bot.tree.command(
        name="help",
        description="Show all available bot commands and their syntax.",
    )
    async def help_command(interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🛠️ Bot Commands & Syntax",
            description="Here are all the commands you can use to interact with me:",
            color=config.EMBED_COLOR_DAILY,
        )
        embed.add_field(name="`/help`", value="Show this help menu.", inline=False)
        embed.add_field(name="`/status`", value="Show bot status and scheduling info.", inline=False)
        embed.add_field(name="`/run`", value="Manually trigger the daily report. (Takes ~1 min)", inline=False)
        embed.add_field(name="`/leaderboard`", value="Show current weekly and monthly leaderboards.", inline=False)
        embed.add_field(name="`/weeksummary`", value="Generate a chart showing activity over the last 7 days.", inline=False)
        embed.add_field(name="`/fetchdate <YYYY-MM-DD>`", value="Fetch the problems solved by everyone on a specific date.\n*Example:* `/fetchdate target_date:2026-06-09`", inline=False)
        embed.add_field(name="`/register <name> <url>`", value="Register your LeetCode profile.\n*Example:* `/register name:Park url:https://leetcode.com/u/park-bit/`", inline=False)
        embed.add_field(name="`/unregister`", value="Remove your LeetCode profile from the bot.", inline=False)
        embed.add_field(name="`/profile`", value="Check which LeetCode profile is linked to your Discord account.", inline=False)
        embed.add_field(name="`/admin`", value="Manage database profiles, names, Discord IDs, and streaks (Admin only).", inline=False)
        embed.add_field(name="`/setup`", value="Configure report channel and check permissions for this server (Admin only).", inline=False)
        embed.add_field(name="`/report`", value="Configure report channel or POTD toggle for this server (Admin only).", inline=False)
        embed.add_field(name="`@DSA-chan`", value="Ping me anywhere to instantly see your stats for today.", inline=False)
        
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(
        name="status",
        description="Show bot status, last run time, and next scheduled run.",
    )
    async def status_command(interaction: discord.Interaction) -> None:
        assert bot.state is not None
        assert bot.scheduler is not None

        tz = pytz.timezone(config.TIMEZONE)
        now = datetime.now(tz=tz)
        last_run = bot.state.get_last_run()
        week_start = bot.state.get_week_start()
        msg_id = bot.state.get_message_id()

        embed = discord.Embed(
            title="🤖 LeetCode Bot Status",
            color=config.EMBED_COLOR_DAILY,
        )
        embed.add_field(
            name="Status",
            value="✅ Running",
            inline=True,
        )
        embed.add_field(
            name="Timezone",
            value=config.TIMEZONE,
            inline=True,
        )
        embed.add_field(
            name="Current Time",
            value=now.strftime("%Y-%m-%d %H:%M:%S"),
            inline=True,
        )
        embed.add_field(
            name="Last Run",
            value=last_run.strftime("%Y-%m-%d %H:%M") if last_run else "Never",
            inline=True,
        )
        embed.add_field(
            name="Week Start",
            value=week_start.isoformat() if week_start else "Not set",
            inline=True,
        )
        embed.add_field(
            name="Report Message ID",
            value=str(msg_id) if msg_id else "Not set",
            inline=True,
        )

        profiles = bot.profile_manager.get_enabled_profiles() if bot.profile_manager else []
        embed.add_field(
            name="Monitored Users",
            value=", ".join(p["name"] for p in profiles) or "None",
            inline=False,
        )

        embed.add_field(
            name="Roadmaps Loaded",
            value=str(bot.roadmap_manager.total) if bot.roadmap_manager else "0",
            inline=True,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info("Status command used by %s.", interaction.user)

    @bot.tree.command(
        name="run",
        description="Manually trigger the daily report.",
    )
    async def run_command(interaction: discord.Interaction) -> None:
        assert bot.scheduler is not None

        await interaction.response.send_message(
            "⏳ Running daily job now... this may take a minute."
        )
        logger.info("Manual /run triggered by %s.", interaction.user)

        try:
            await bot.scheduler.trigger_now()
            await interaction.edit_original_response(content="✅ Daily report generated!")
            import asyncio
            loop = asyncio.get_running_loop()
            async def _cleanup():
                await asyncio.sleep(30)
                try:
                    await interaction.delete_original_response()
                except Exception:
                    pass
            loop.create_task(_cleanup())
        except Exception as exc:  # noqa: BLE001
            logger.error("Manual run failed: %s", exc, exc_info=True)
            await interaction.followup.send(
                f"❌ Error during manual run: {exc}", ephemeral=True
            )
    @bot.tree.command(
        name="lastweek",
        description="Manually post the raw text summary of the past week's problems.",
    )
    async def lastweek_command(interaction: discord.Interaction) -> None:
        await interaction.response.send_message("⏳ Gathering past week data...", ephemeral=True)
        try:
            import formatter
            from datetime import timedelta, datetime
            import pytz
            import config
            
            profiles = bot.profile_manager.get_enabled_profiles()
            tz = pytz.timezone(config.TIMEZONE)
            today = datetime.now(tz=tz).date()
            stored_week_start = bot.state.get_week_start()
            
            if not stored_week_start:
                await interaction.edit_original_response(content="❌ Could not determine week start date.")
                return
                
            delta_days = (today - stored_week_start).days
            if delta_days <= 0:
                # If run right after the week resets, stored_week_start is today.
                # Shift back 7 days to fetch the actual last week.
                stored_week_start = today - timedelta(days=7)
                delta_days = 7
                
            last_week_history = []
            for i in range(delta_days):
                d = stored_week_start + timedelta(days=i)
                d_iso = d.isoformat()
                day_dict = {}
                for p in profiles:
                    name = p["name"]
                    probs = bot.state.get_day_problems(name, d_iso)
                    if probs:
                        day_dict[name] = probs
                last_week_history.append((d, day_dict))
                
            text_chunks = formatter.build_weekly_raw_text_summary(profiles, last_week_history)
            
            await bot.discord_manager.send_weekly_text_summary(text_chunks)
            await interaction.edit_original_response(content=f"✅ Dumped {len(text_chunks)} messages to <#{config.WEEKLY_TEXT_CHANNEL_ID}>.")
                
        except Exception as exc:
            logger.error("Error in /lastweek: %s", exc, exc_info=True)
            await interaction.edit_original_response(content=f"❌ Error: {exc}")

    @bot.tree.command(
        name="roll",
        description="Force the bot to post a brand new message for the current week.",
    )
    async def roll_command(interaction: discord.Interaction) -> None:
        assert bot.scheduler is not None
        await interaction.response.defer()
        
        try:
            await bot.scheduler.trigger_now(force_new_message=True)
            msg = await interaction.followup.send("✅ Successfully rolled out a new message for the week!")
            
            import asyncio
            loop = asyncio.get_running_loop()
            async def _cleanup_roll():
                await asyncio.sleep(30)
                try:
                    await msg.delete()
                except Exception:
                    pass
            loop.create_task(_cleanup_roll())
            
        except Exception as exc:
            logger.exception("Error during /roll")
            await interaction.followup.send(
                f"❌ Error during manual roll: {exc}", ephemeral=True
            )


    @bot.tree.command(
        name="leaderboard",
        description="Show the current weekly leaderboard.",
    )
    async def leaderboard_command(interaction: discord.Interaction) -> None:
        assert bot.state is not None
        assert bot.leaderboard_manager is not None
        assert bot.profile_manager is not None

        profiles = bot.profile_manager.get_enabled_profiles()
        if interaction.guild:
            guild_profiles = []
            for p in profiles:
                did = p.get("discord_id")
                if did:
                    if interaction.guild.get_member(int(did)) is not None:
                        guild_profiles.append(p)
                else:
                    guild_profiles.append(p)
            if guild_profiles:
                profiles = guild_profiles

        weekly_lb = bot.leaderboard_manager.build_weekly_leaderboard(profiles)
        daily_lb = bot.leaderboard_manager.build_daily_leaderboard(profiles)

        embed = discord.Embed(
            title="🏆 Current Leaderboards",
            color=config.EMBED_COLOR_LEADERBOARD,
        )

        daily_lines = []
        for entry in daily_lb:
            if entry["solved"] > 0:
                medals = {1: "🥇", 2: "🥈", 3: "🥉"}
                medal = medals.get(entry["rank"], "")
                daily_lines.append(
                    f"{medal} **{entry['username']}**: {entry['solved']}"
                )
        embed.add_field(
            name="📅 Today",
            value="\n".join(daily_lines) or "No solves recorded today",
            inline=False,
        )

        weekly_lines = []
        for entry in weekly_lb:
            if entry["solved"] > 0:
                medals = {1: "🥇", 2: "🥈", 3: "🥉"}
                medal = medals.get(entry["rank"], "")
                weekly_lines.append(
                    f"{medal} **{entry['username']}**: {entry['solved']}"
                )
        embed.add_field(
            name="📆 This Week",
            value="\n".join(weekly_lines) or "No solves recorded this week yet",
            inline=False,
        )

        week_start = bot.state.get_week_start()
        if week_start:
            embed.set_footer(text=f"Week started {week_start.strftime('%d %b %Y')}")

        await interaction.response.send_message(embed=embed)
        logger.info("Leaderboard command used by %s.", interaction.user)

    @bot.tree.command(
        name="nudge",
        description="Manually trigger the 10 PM Evening Nudge to test it.",
    )
    async def nudge_command(interaction: discord.Interaction) -> None:
        assert bot.scheduler is not None
        
        await interaction.response.defer()
        
        try:
            await bot.scheduler.run_evening_nudge()
            msg = await interaction.followup.send("✅ Evening nudge check executed! Anyone who hasn't solved a problem today was pinged.")
            import asyncio
            asyncio.create_task(msg.delete(delay=60.0))
        except Exception as e:
            logger.error("Error during manual nudge: %s", e)
            await interaction.followup.send(f"❌ Error during manual nudge: `{e}`")

    @bot.tree.command(
        name="potd",
        description="Manually fetch and post today's LeetCode Problem of the Day.",
    )
    async def potd_command(interaction: discord.Interaction) -> None:
        assert bot.scheduler is not None
        
        await interaction.response.defer()
        
        try:
            await bot.scheduler.run_potd()
            msg = await interaction.followup.send("✅ Problem of the Day posted!")
            import asyncio
            asyncio.create_task(msg.delete(delay=60.0))
        except Exception as e:
            logger.error("Error during manual POTD: %s", e)
            await interaction.followup.send(f"❌ Error during manual POTD: `{e}`")

    @bot.tree.command(
        name="roadmap",
        description="Check roadmap progress for yourself or another user.",
    )
    @app_commands.describe(
        sheet="The problem sheet to check progress against",
        target_user="Optional: User to check progress for"
    )
    @app_commands.choices(sheet=[
        app_commands.Choice(name="NeetCode 150", value="neetcode150"),
        app_commands.Choice(name="Striver A2Z", value="striver_a2z")
    ])
    async def roadmap_command(
        interaction: discord.Interaction,
        sheet: app_commands.Choice[str],
        target_user: discord.Member | None = None,
    ) -> None:
        assert bot.state is not None
        assert bot.profile_manager is not None
        assert bot.roadmap_manager is not None
        
        await interaction.response.defer()
        
        if target_user:
            member_id = target_user.id
            profile = bot.profile_manager.get_profile_by_discord_id(str(member_id))
            if not profile:
                await interaction.followup.send(f"❌ <@{member_id}> is not registered in profiles.json.")
                return
            name = profile["name"]
        else:
            member_id = interaction.user.id
            profile = bot.profile_manager.get_profile_by_discord_id(str(member_id))
            if not profile:
                await interaction.followup.send("❌ You are not registered in profiles.json. Provide a user via `/roadmap @user`.")
                return
            name = profile["name"]
            
        stats = bot.state.get_user_stats(name)
        known_accepted = stats.get("known_accepted", [])
        
        roadmap_dict = bot.roadmap_manager.get_roadmap(sheet.value)
        if not roadmap_dict:
            await interaction.followup.send(f"❌ Could not load roadmap '{sheet.value}'.")
            return
            
        solved_roadmap = set(known_accepted) & set(roadmap_dict.keys())
        total_roadmap = len(roadmap_dict)
        solved_count = len(solved_roadmap)
        percentage = (solved_count / total_roadmap) * 100 if total_roadmap > 0 else 0
        
        # Build progress bar [████████░░]
        bar_length = 20
        filled_length = int(bar_length * solved_count // total_roadmap) if total_roadmap > 0 else 0
        bar = "█" * filled_length + "░" * (bar_length - filled_length)
        
        embed = discord.Embed(
            title=f"🗺️ {sheet.name} Progress: {name}",
            description=f"**[{bar}] {percentage:.1f}%**\n\n**{solved_count} / {total_roadmap}** problems solved.",
            color=discord.Color.purple()
        )
        
        await interaction.followup.send(embed=embed)

    @bot.tree.command(
        name="weeksummary",
        description="Show this week's LeetCode summary with a difficulty breakdown chart.",
    )
    async def weeksummary_command(interaction: discord.Interaction) -> None:
        assert bot.state is not None
        assert bot.profile_manager is not None
        assert bot.streak_manager is not None

        await interaction.response.defer()  # chart generation may take a moment

        profiles = bot.profile_manager.get_enabled_profiles()
        week_start = bot.state.get_week_start()

        # Collect weekly stats per user
        weekly_data: dict[str, dict] = {}
        
        from datetime import datetime, timedelta
        import pytz
        import config
        today = datetime.now(tz=pytz.timezone(config.TIMEZONE)).date()
        
        if week_start:
            delta_days = (today - week_start).days
            if delta_days < 0: delta_days = 0
            dates_in_week = [week_start + timedelta(days=i) for i in range(delta_days + 1)]
        else:
            dates_in_week = [today]

        for profile in profiles:
            name = profile["name"]
            discord_id = profile.get("discord_id", "")
            current_streak, longest_streak = bot.streak_manager.get(name)
            
            solved = 0
            easy = 0
            medium = 0
            hard = 0
            
            for d in dates_in_week:
                probs = bot.state.get_day_problems(name, d.isoformat())
                solved += len(probs)
                easy += sum(1 for p in probs if p.get("difficulty") == "Easy")
                medium += sum(1 for p in probs if p.get("difficulty") == "Medium")
                hard += sum(1 for p in probs if p.get("difficulty") == "Hard")

            weekly_data[name] = {
                "easy":          easy,
                "medium":        medium,
                "hard":          hard,
                "total":         solved,
                "discord_id":    discord_id,
                "streak":        current_streak,
                "longest":       longest_streak,
            }

        # Sort by total solved descending
        sorted_users = sorted(
            weekly_data.items(), key=lambda x: -x[1]["total"]
        )

        # Week label
        week_label = week_start.strftime("%d %b") if week_start else "Current Week"

        # Generate chart in a thread so we don't block the event loop
        import asyncio
        import functools
        from chart_generator import generate_week_chart

        loop = asyncio.get_event_loop()
        buf = await loop.run_in_executor(
            None,
            functools.partial(
                generate_week_chart,
                dict(sorted_users),
                week_label,
            ),
        )

        # Build embed
        embed = discord.Embed(
            title=f"📊 Weekly Summary: {week_label}",
            color=config.EMBED_COLOR_WEEKLY,
        )

        # Per-user stats fields
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for rank, (name, data) in enumerate(sorted_users, start=1):
            medal = medals.get(rank, "")
            did = data["discord_id"]
            mention = f" <@{did}>" if did else ""
            total   = data["total"]
            easy    = data["easy"]
            medium  = data["medium"]
            hard    = data["hard"]
            streak  = data["streak"]
            longest = data["longest"]

            diff_parts = []
            if easy:   diff_parts.append(f"Easy: {easy}")
            if medium: diff_parts.append(f"Medium: {medium}")
            if hard:   diff_parts.append(f"Hard: {hard}")
            diff_str = " · ".join(diff_parts) if diff_parts else "0"

            value = (
                f"{mention}\n" if mention else ""
            )
            value += (
                f"{medal} **{total} solved**: {diff_str}\n"
                f"🔥 Streak: {streak} day{'s' if streak != 1 else ''}  "
                f"(longest: {longest})"
            )
            embed.add_field(
                name=name,
                value=value,
                inline=True,
            )

        if week_start:
            embed.set_footer(text=f"Week started {week_start.strftime('%d %b %Y')} • resets every Monday")

        # Attach chart image
        chart_file = discord.File(buf, filename="weeksummary.png")
        embed.set_image(url="attachment://weeksummary.png")

        await interaction.followup.send(embed=embed, file=chart_file)
        logger.info("Week summary command used by %s.", interaction.user)

    @bot.tree.command(
        name="profile",
        description="View a beautiful profile card for yourself or another user.",
    )
    @app_commands.describe(
        user="Optional: Tag someone to view their profile instead of yours."
    )
    async def profile_command(interaction: discord.Interaction, user: discord.Member = None) -> None:
        assert bot.profile_manager is not None
        assert bot.streak_manager is not None
        
        await interaction.response.defer()

        target_id = str(user.id) if user else str(interaction.user.id)
        profiles = bot.profile_manager.get_enabled_profiles()
        
        matched = next(
            (p for p in profiles if p.get("discord_id") == target_id),
            None,
        )
        
        if not matched:
            msg = "❌ The selected user isn't linked to a LeetCode profile." if user else "❌ You aren't linked to a LeetCode profile. Use `/register` first."
            await interaction.followup.send(msg)
            return
            
        name = matched["name"]
        url = matched["leetcode_url"]
        
        from leetcode_fetcher import LeetCodeFetcher
        async with LeetCodeFetcher() as fetcher:
            stats = await fetcher.get_user_stats(url)
        
        if not stats:
            await interaction.followup.send(f"❌ Failed to fetch LeetCode profile for **{name}**. Check if the username is correct.")
            return

        current_streak, longest_streak = bot.streak_manager.get(name)
        
        user_colors = {
            "park-bit": "🟠",
            "lilght01": "🔵",
            "Yuuta_1678": "🟢",
            "vedant_ghate": "🔴"
        }
        emoji = user_colors.get(name, "👤")
        
        embed = discord.Embed(
            title=f"{emoji} {name}'s LeetCode Profile",
            url=f"https://leetcode.com/u/{name}/",
            color=config.EMBED_COLOR_DAILY,
        )
        
        # We can use the discord member's avatar if they are in the server
        target_member = user or interaction.user
        embed.set_thumbnail(url=target_member.display_avatar.url)
        
        embed.add_field(
            name="🏆 Ranking",
            value=f"**{stats.ranking:,}**" if stats.ranking else "Unranked",
            inline=True
        )
        embed.add_field(
            name="🔥 Server Streak",
            value=f"**{current_streak}** days\n(Longest: {longest_streak})",
            inline=True
        )
        embed.add_field(name="\u200b", value="\u200b", inline=False) # blank line
        
        embed.add_field(
            name="Total Solved",
            value=f"**{stats.total_solved}** problems",
            inline=False
        )
        
        # Add roadmap progress
        if bot.roadmap_manager and bot.state:
            user_stats = bot.state.get_user_stats(name)
            known_accepted = user_stats.get("known_accepted", [])
            for sheet_name in bot.roadmap_manager.get_all_roadmaps():
                roadmap_dict = bot.roadmap_manager.get_roadmap(sheet_name)
                if not roadmap_dict: continue
                
                solved_roadmap = set(known_accepted) & set(roadmap_dict.keys())
                total_roadmap = len(roadmap_dict)
                solved_count = len(solved_roadmap)
                percentage = (solved_count / total_roadmap) * 100 if total_roadmap > 0 else 0
                
                bar_length = 15
                filled_length = int(bar_length * solved_count // total_roadmap) if total_roadmap > 0 else 0
                bar = "█" * filled_length + "░" * (bar_length - filled_length)
                
                embed.add_field(
                    name=f"🗺️ {sheet_name} Progress",
                    value=f"`[{bar}]` **{percentage:.1f}%** ({solved_count}/{total_roadmap})",
                    inline=False
                )

        import asyncio
        import functools
        from chart_generator import generate_profile_donut_chart

        loop = asyncio.get_event_loop()
        buf = await loop.run_in_executor(
            None,
            functools.partial(
                generate_profile_donut_chart,
                stats.easy_solved,
                stats.medium_solved,
                stats.hard_solved,
                name
            ),
        )

        chart_file = discord.File(buf, filename="profile_donut.png")
        embed.set_image(url="attachment://profile_donut.png")
        
        await interaction.followup.send(embed=embed, file=chart_file)
        logger.info("Profile command used for %s.", name)


    @bot.tree.command(
        name="register",
        description="Link your LeetCode profile to your Discord account.",
    )
    @app_commands.describe(
        name="Your preferred display name",
        url="Your LeetCode profile URL (e.g., https://leetcode.com/u/username/)"
    )
    async def register_command(interaction: discord.Interaction, name: str, url: str) -> None:
        assert bot.profile_manager is not None

        author_id = str(interaction.user.id)
        success = bot.profile_manager.add_profile(name, url, author_id)
        
        if success:
            embed = discord.Embed(
                title="✅ Profile Registered",
                description=f"Welcome, **{name}**!\nYour profile has been linked: {url}",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info("User %s registered as '%s'.", interaction.user, name)
        else:
            embed = discord.Embed(
                title="❌ Invalid URL",
                description="Please provide a valid LeetCode profile URL.\nExample: `https://leetcode.com/u/your_username/`",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(
        name="unregister",
        description="Remove your LeetCode profile from the tracker.",
    )
    async def unregister_command(interaction: discord.Interaction) -> None:
        assert bot.profile_manager is not None

        author_id = str(interaction.user.id)
        removed = bot.profile_manager.remove_profile(author_id)
        
        if removed:
            await interaction.response.send_message(
                "✅ Your profile has been removed from the tracker.", ephemeral=True
            )
            logger.info("User %s unregistered.", interaction.user)
        else:
            await interaction.response.send_message(
                "❌ You are not currently registered.", ephemeral=True
            )



    @bot.tree.command(
        name="history",
        description="Fetch the LeetCode summary for a specific date.",
    )
    @app_commands.describe(
        date="Date in YYYY-MM-DD format (e.g., 2026-06-09)",
        username="Optional: Specific user to fetch problems for"
    )
    async def history_command(interaction: discord.Interaction, date: str, username: str | None = None) -> None:
        assert bot.state is not None
        assert bot.profile_manager is not None
        
        # Validate date format roughly
        from datetime import date as dt_date
        try:
            parsed_date = dt_date.fromisoformat(date)
            date_str = parsed_date.isoformat()
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid date format. Please use **YYYY-MM-DD** (e.g., `2026-06-09`).",
                ephemeral=True
            )
            return

        profiles = bot.profile_manager.get_enabled_profiles()
        
        embed = discord.Embed(
            title=f"📅 History — {parsed_date.strftime('%A, %d %B %Y')}",
            color=config.EMBED_COLOR_DAILY,
        )

        found_any = False

        if username:
            # Filter for specific user
            matched = next((p for p in profiles if p["name"].lower() == username.lower()), None)
            if not matched:
                await interaction.response.send_message(f"❌ User **{username}** not found.", ephemeral=True)
                return
            
            problems = bot.state.get_day_problems(matched["name"], date_str)
            if not problems:
                embed.description = f"**{matched['name']}** did not solve any problems on this date."
            else:
                found_any = True
                lines = []
                for idx, prob in enumerate(problems, start=1):
                    title = prob.get("title", prob.get("slug", ""))
                    diff  = prob.get("difficulty", "")
                    url   = prob.get("url", "")
                    tags  = prob.get("tags", [])
                    tag_str  = "".join(f"[{t}]" for t in tags)
                    tag_part = f" `{tag_str}`" if tag_str else ""
                    lines.append(f"`{idx}.` {title} ({diff}){tag_part} [link]({url})")
                
                embed.add_field(
                    name=f"{matched['name']} ({len(problems)} solved)",
                    value="\n".join(lines),
                    inline=False,
                )
        else:
            # Summary for all users
            for profile in profiles:
                name = profile["name"]
                problems = bot.state.get_day_problems(name, date_str)
                if problems:
                    found_any = True
                    lines = []
                    for idx, prob in enumerate(problems, start=1):
                        title = prob.get("title", prob.get("slug", ""))
                        diff  = prob.get("difficulty", "")
                        url   = prob.get("url", "")
                        tags  = prob.get("tags", [])
                        tag_str  = "".join(f"[{t}]" for t in tags)
                        tag_part = f" `{tag_str}`" if tag_str else ""
                        lines.append(f"`{idx}.` {title} ({diff}){tag_part} [link]({url})")
                    
                    embed.add_field(
                        name=f"{name} ({len(problems)} solved)",
                        value="\n".join(lines),
                        inline=False,
                    )
            
            if not found_any:
                embed.description = "No submissions recorded for anyone on this date."

        await interaction.response.send_message(embed=embed)
        logger.info("History command used by %s for date %s.", interaction.user, date_str)


    @bot.tree.command(
        name="duel",
        description="Challenge another registered user to a LeetCode duel!",
    )
    @app_commands.describe(opponent="The user you want to duel")
    async def duel_command(interaction: discord.Interaction, opponent: discord.Member) -> None:
        assert bot.profile_manager is not None
        assert bot.roadmap_manager is not None
        assert bot.duel_manager is not None

        await interaction.response.defer()

        if opponent.id == interaction.user.id:
            await interaction.followup.send("❌ You can't duel yourself!")
            return

        profiles = bot.profile_manager.get_enabled_profiles()
        
        challenger = next((p for p in profiles if p.get("discord_id") == str(interaction.user.id)), None)
        challenged = next((p for p in profiles if p.get("discord_id") == str(opponent.id)), None)

        if not challenger:
            await interaction.followup.send("❌ You aren't linked to a LeetCode profile. Use `/register` first.")
            return
        if not challenged:
            await interaction.followup.send(f"❌ {opponent.mention} isn't linked to a LeetCode profile.")
            return

        # Check if either user is already in a duel
        if bot.duel_manager.get_active_duel(str(interaction.user.id)):
            await interaction.followup.send("❌ You are already in an active duel!")
            return
        if bot.duel_manager.get_active_duel(str(opponent.id)):
            await interaction.followup.send(f"❌ {opponent.mention} is already in an active duel!")
            return

        # Collect recently solved problems for both users
        def get_solved_slugs(username: str) -> set[str]:
            slugs = set()
            history = bot.state.get_history(username)
            for day_probs in history.values():
                for p in day_probs:
                    slugs.add(p["slug"])
            return slugs

        c1_slugs = get_solved_slugs(challenger["name"])
        c2_slugs = get_solved_slugs(challenged["name"])
        combined_solved = c1_slugs.union(c2_slugs)

        # Pick a random problem from the roadmap that neither has solved
        import random
        pool = []
        for slug, number in bot.roadmap_manager._by_slug.items():
            if slug not in combined_solved:
                title = bot.roadmap_manager._number_to_title[number]
                pool.append((slug, title))

        if not pool:
            await interaction.followup.send("❌ Wow! Between the two of you, you've solved every problem in the roadmap! No fair duel possible.")
            return

        slug, title = random.choice(pool)
        import config
        url = f"{config.LEETCODE_BASE_URL}/problems/{slug}/"

        bot.duel_manager.start_duel(str(interaction.user.id), str(opponent.id), slug, title, url)

        embed = discord.Embed(
            title="⚔️ LEETCODE DUEL! ⚔️",
            description=f"{interaction.user.mention} has challenged {opponent.mention}!\n\n"
                        f"**Problem:** [{title}]({url})\n\n"
                        f"First to solve it and type `/claim_win` is the victor!",
            color=0xFF0000
        )
        await interaction.followup.send(content=f"{interaction.user.mention} 🆚 {opponent.mention}", embed=embed)
        logger.info("Duel started between %s and %s.", interaction.user, opponent)


    @bot.tree.command(
        name="claim_win",
        description="Claim victory if you've solved the problem for your active duel!",
    )
    async def claim_win_command(interaction: discord.Interaction) -> None:
        assert bot.duel_manager is not None
        assert bot.profile_manager is not None

        await interaction.response.defer()
        
        user_id = str(interaction.user.id)
        duel = bot.duel_manager.get_active_duel(user_id)
        if not duel:
            await interaction.followup.send("❌ You are not in an active duel.")
            return

        profiles = bot.profile_manager.get_enabled_profiles()
        profile = next((p for p in profiles if p.get("discord_id") == user_id), None)
        if not profile:
            await interaction.followup.send("❌ You aren't linked to a LeetCode profile.")
            return
            
        username = profile["name"]
        url = profile["leetcode_url"]
        slug = duel["problem_slug"]
        start_time = duel["start_time"]
        
        from leetcode_fetcher import LeetCodeFetcher
        async with LeetCodeFetcher() as fetcher:
            subs = await fetcher.get_accepted_submissions(url)
            
        # Check if they solved the problem AFTER the duel started
        won = False
        import datetime
        for sub in subs:
            if sub.slug == slug:
                # sub.timestamp is unix seconds. start_time is datetime.utcnow()
                sub_dt = datetime.datetime.utcfromtimestamp(sub.timestamp)
                if sub_dt >= start_time:
                    won = True
                    break

        if won:
            opponent_id = duel["user1"] if duel["user2"] == user_id else duel["user2"]
            bot.duel_manager.close_duel(user_id)
            
            embed = discord.Embed(
                title="🏆 DUEL FINISHED! 🏆",
                description=f"{interaction.user.mention} successfully solved **{duel['problem_title']}** and defeated <@{opponent_id}>!\n\nGG WP!",
                color=0xFFD700
            )
            await interaction.followup.send(embed=embed)
            logger.info("Duel won by %s.", interaction.user)
        else:
            await interaction.followup.send(f"❌ I checked your recent submissions, but I don't see an accepted solution for **{duel['problem_title']}** since the duel started. Keep trying!")

    # ------------------------------------------------------------------
    # Admin Command Group
    # ------------------------------------------------------------------

    def _is_admin(interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) in config.ADMIN_USER_IDS:
            return True
        if interaction.guild and interaction.user.guild_permissions.administrator:
            return True
        return False

    async def _admin_profile_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        if not bot.profile_manager:
            return []
        profiles = bot.profile_manager.get_all_profiles()
        current_lower = current.lower()
        choices = []
        for p in profiles:
            dc = p.get("discord_id") or "no DC ID"
            label = f"{p['name']} ({dc})"
            if current_lower in p["name"].lower() or current in str(p.get("discord_id", "")):
                choices.append(app_commands.Choice(name=label[:100], value=p["name"]))
        return choices[:25]

    admin_group = app_commands.Group(
        name="admin",
        description="Admin controls for database, profiles, and streaks",
        default_permissions=discord.Permissions(administrator=True),
    )

    @admin_group.command(
        name="list",
        description="List all tracked profiles and their database linkage.",
    )
    async def admin_list(interaction: discord.Interaction) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin permissions required.", ephemeral=True)
            return

        assert bot.profile_manager is not None
        profiles = bot.profile_manager.get_all_profiles()
        from database import DatabaseManager
        backend = DatabaseManager().get_storage_type()

        embed = discord.Embed(
            title="🛡️ Database Profiles",
            description=f"**Storage Backend:** `{backend}`\n**Total Profiles:** `{len(profiles)}`",
            color=config.EMBED_COLOR_DAILY,
        )

        if not profiles:
            embed.description += "\n\n*No profiles registered in database.*"
        else:
            for p in profiles:
                name = p["name"]
                url = p.get("leetcode_url", "N/A")
                dc_id = p.get("discord_id", "")
                dc_display = f"<@{dc_id}> (`{dc_id}`)" if dc_id else "*Not linked*"
                status = "🟢 Enabled" if p.get("enabled", True) else "🔴 Disabled"
                
                streak_str = "0"
                if bot.streak_manager:
                    cur, long = bot.streak_manager.get(name)
                    streak_str = f"cur: {cur}, longest: {long}"

                field_value = (
                    f"🔗 **LeetCode:** [{p.get('leetcode_username', name)}]({url})\n"
                    f"💬 **Discord:** {dc_display}\n"
                    f"⚙️ **Status:** {status} | 🔥 **Streak:** {streak_str}"
                )
                embed.add_field(name=f"👤 {name}", value=field_value, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info("Admin list command run by %s.", interaction.user)

    @admin_group.command(
        name="update",
        description="Modify an existing profile (name, URL, Discord ID, enabled status).",
    )
    @app_commands.describe(
        target="User to update (type or select from list)",
        new_name="New display name (renames in state & streaks too)",
        new_url="New LeetCode URL (e.g. https://leetcode.com/u/username/)",
        discord_user="Discord account to link",
        discord_id="Raw Discord user ID string (alternative to tagging)",
        enabled="Enable or disable monitoring for this user",
    )
    @app_commands.autocomplete(target=_admin_profile_autocomplete)
    async def admin_update(
        interaction: discord.Interaction,
        target: str,
        new_name: str | None = None,
        new_url: str | None = None,
        discord_user: discord.Member | None = None,
        discord_id: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin permissions required.", ephemeral=True)
            return

        assert bot.profile_manager is not None

        # Resolve discord ID
        resolved_dc_id = None
        if discord_user is not None:
            resolved_dc_id = str(discord_user.id)
        elif discord_id is not None:
            resolved_dc_id = discord_id.strip()

        # Find existing profile
        old_profile = bot.profile_manager.find_profile(target)
        if not old_profile:
            await interaction.response.send_message(
                f"❌ Profile `{target}` not found in database.", ephemeral=True
            )
            return

        old_name = old_profile["name"]

        # If name is being changed, rename in state manager too
        if new_name and new_name.strip() and new_name.strip() != old_name:
            if bot.state:
                bot.state.rename_user(old_name, new_name.strip())

        success, msg, updated = bot.profile_manager.update_profile(
            target,
            new_name=new_name,
            new_url=new_url,
            new_discord_id=resolved_dc_id,
            enabled=enabled,
        )

        if not success or not updated:
            await interaction.response.send_message(f"❌ {msg}", ephemeral=True)
            return

        embed = discord.Embed(
            title="✅ Profile Updated",
            description=f"Successfully modified database record for **{updated['name']}**.",
            color=discord.Color.green(),
        )
        embed.add_field(name="Name", value=f"`{old_name}` ➔ `{updated['name']}`", inline=True)
        embed.add_field(
            name="LeetCode",
            value=f"[{updated.get('leetcode_username', updated['name'])}]({updated['leetcode_url']})",
            inline=True,
        )
        did = updated.get("discord_id")
        embed.add_field(
            name="Discord Link",
            value=f"<@{did}> (`{did}`)" if did else "*Not linked*",
            inline=False,
        )
        embed.add_field(
            name="Tracking",
            value="🟢 Enabled" if updated.get("enabled", True) else "🔴 Disabled",
            inline=True,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info("Admin updated profile %s to %s by %s.", old_name, updated["name"], interaction.user)

    @admin_group.command(
        name="add",
        description="Add a new user to the database.",
    )
    @app_commands.describe(
        name="Display name for the user",
        url="LeetCode profile URL (e.g. https://leetcode.com/u/username/)",
        discord_user="Discord account to link",
        discord_id="Raw Discord user ID string (alternative to tagging)",
        enabled="Whether to enable monitoring immediately",
    )
    async def admin_add(
        interaction: discord.Interaction,
        name: str,
        url: str,
        discord_user: discord.Member | None = None,
        discord_id: str | None = None,
        enabled: bool = True,
    ) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin permissions required.", ephemeral=True)
            return

        assert bot.profile_manager is not None

        resolved_dc_id = ""
        if discord_user is not None:
            resolved_dc_id = str(discord_user.id)
        elif discord_id is not None:
            resolved_dc_id = discord_id.strip()

        success, msg, profile = bot.profile_manager.add_or_update_profile(
            name=name,
            leetcode_url=url,
            discord_id=resolved_dc_id,
            enabled=enabled,
        )

        if not success or not profile:
            await interaction.response.send_message(f"❌ {msg}", ephemeral=True)
            return

        embed = discord.Embed(
            title="✅ Profile Saved",
            description=f"Profile for **{profile['name']}** added/updated in database.",
            color=discord.Color.green(),
        )
        embed.add_field(name="Name", value=f"`{profile['name']}`", inline=True)
        embed.add_field(name="LeetCode URL", value=profile["leetcode_url"], inline=False)
        did = profile.get("discord_id")
        embed.add_field(
            name="Linked Discord",
            value=f"<@{did}> (`{did}`)" if did else "*Not linked*",
            inline=True,
        )
        embed.add_field(
            name="Tracking",
            value="🟢 Enabled" if profile.get("enabled", True) else "🔴 Disabled",
            inline=True,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info("Admin added profile %s by %s.", profile["name"], interaction.user)

    @admin_group.command(
        name="remove",
        description="Remove a profile from the database.",
    )
    @app_commands.describe(
        target="User to remove (type or select from list)",
    )
    @app_commands.autocomplete(target=_admin_profile_autocomplete)
    async def admin_remove(interaction: discord.Interaction, target: str) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin permissions required.", ephemeral=True)
            return

        assert bot.profile_manager is not None

        success, msg = bot.profile_manager.remove_profile_by_identifier(target)
        if success:
            await interaction.response.send_message(f"✅ {msg}", ephemeral=True)
            logger.info("Admin removed profile %s by %s.", target, interaction.user)
        else:
            await interaction.response.send_message(f"❌ {msg}", ephemeral=True)

    @admin_group.command(
        name="link",
        description="Quickly link or re-link a Discord user to a LeetCode profile.",
    )
    @app_commands.describe(
        target="User to link (type or select from list)",
        discord_user="Discord account to link",
    )
    @app_commands.autocomplete(target=_admin_profile_autocomplete)
    async def admin_link(
        interaction: discord.Interaction,
        target: str,
        discord_user: discord.Member,
    ) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin permissions required.", ephemeral=True)
            return

        assert bot.profile_manager is not None

        dc_id = str(discord_user.id)
        success, msg, profile = bot.profile_manager.update_profile(
            target, new_discord_id=dc_id
        )

        if success and profile:
            embed = discord.Embed(
                title="🔗 Discord Account Linked",
                description=f"Linked **{profile['name']}** to {discord_user.mention} (`{dc_id}`).",
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info("Admin linked %s to Discord %s by %s.", profile["name"], dc_id, interaction.user)
        else:
            await interaction.response.send_message(f"❌ {msg}", ephemeral=True)

    @admin_group.command(
        name="setstreak",
        description="Manually adjust a user's current or longest streak.",
    )
    @app_commands.describe(
        target="User to adjust streak for",
        current="Current streak value (days)",
        longest="Longest streak value (optional)",
    )
    @app_commands.autocomplete(target=_admin_profile_autocomplete)
    async def admin_setstreak(
        interaction: discord.Interaction,
        target: str,
        current: int,
        longest: int | None = None,
    ) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin permissions required.", ephemeral=True)
            return

        assert bot.state is not None
        profile = bot.profile_manager.find_profile(target) if bot.profile_manager else None
        user_name = profile["name"] if profile else target

        bot.state.set_user_streak(user_name, current=current, longest=longest)
        embed = discord.Embed(
            title="🔥 Streak Updated",
            description=f"Streak for **{user_name}** set to **{current}** (longest: **{longest if longest is not None else current}**).",
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info("Admin set streak for %s: cur=%d by %s.", user_name, current, interaction.user)

    @admin_group.command(
        name="reload",
        description="Reload all profiles and state from database/disk.",
    )
    async def admin_reload(interaction: discord.Interaction) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin permissions required.", ephemeral=True)
            return

        if bot.profile_manager:
            bot.profile_manager.load()
        if bot.state:
            bot.state.load()

        await interaction.response.send_message("🔄 Database state and profiles reloaded.", ephemeral=True)
        logger.info("Admin reloaded database state by %s.", interaction.user)

    @admin_group.command(
        name="cleanup",
        description="Clean up duplicate/older weekly summary messages from the channel.",
    )
    async def admin_cleanup(interaction: discord.Interaction) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin permissions required.", ephemeral=True)
            return

        assert bot.discord_manager is not None
        await interaction.response.defer(ephemeral=True)

        deleted = await bot.discord_manager.cleanup_channel_duplicates(keep_current_message=True)
        await interaction.followup.send(
            f"🧹 Cleaned up **{deleted}** duplicate report message(s). Only the active summary remains.",
            ephemeral=True,
        )
        logger.info("Admin cleaned up %d duplicate messages by %s.", deleted, interaction.user)

    # Register admin group on the command tree
    bot.tree.add_command(admin_group)

    @bot.tree.command(
        name="setup",
        description="Set up the bot report and POTD channels for this server (Admin only).",
    )
    @app_commands.default_permissions(administrator=True)
    async def setup_command(
        interaction: discord.Interaction,
        report_channel: discord.TextChannel,
        potd_channel: discord.TextChannel | None = None,
    ) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin permissions required.", ephemeral=True)
            return

        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ This command must be run inside a server.", ephemeral=True)
            return

        assert bot.state is not None
        bot_member = guild.me or guild.get_member(bot.user.id)
        if bot_member:
            perms = report_channel.permissions_for(bot_member)
            required_perms = {
                "View Channel": perms.view_channel,
                "Send Messages": perms.send_messages,
                "Embed Links": perms.embed_links,
                "Attach Files": perms.attach_files,
                "Read Message History": perms.read_message_history,
            }
            missing = [name for name, ok in required_perms.items() if not ok]
            if missing:
                await interaction.response.send_message(
                    f"❌ Bot is missing permissions in {report_channel.mention}:\n"
                    + "\n".join(f"- {m}" for m in missing)
                    + "\nPlease grant them and try again.",
                    ephemeral=True,
                )
                return

        bot.state.set_guild_channel(guild.id, report_channel.id)
        if potd_channel:
            bot.state.set_guild_potd(guild.id, potd_channel.id, enabled=True)

        embed = discord.Embed(
            title="✅ Server Setup Complete",
            description=(
                f"Configuration saved for **{guild.name}**:\n"
                f"• **Report Channel:** {report_channel.mention}\n"
                f"• **POTD Channel:** {potd_channel.mention if potd_channel else report_channel.mention}\n\n"
                "The weekly summary will now update automatically in this channel.\n"
                "Use `/run` to trigger the report immediately."
            ),
            color=config.EMBED_COLOR_DAILY,
        )
        await interaction.response.send_message(embed=embed)
        logger.info("Setup completed for guild %s (%d) by %s.", guild.name, guild.id, interaction.user)

    report_group = app_commands.Group(
        name="report",
        description="Configure report and POTD channels for this server",
        default_permissions=discord.Permissions(administrator=True),
    )

    @report_group.command(
        name="channel",
        description="Set the weekly report channel for this server.",
    )
    async def report_channel_command(
        interaction: discord.Interaction,
        target_channel: discord.TextChannel,
    ) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin permissions required.", ephemeral=True)
            return

        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ This command must be run inside a server.", ephemeral=True)
            return

        assert bot.state is not None
        bot_member = guild.me or guild.get_member(bot.user.id)
        if bot_member:
            perms = target_channel.permissions_for(bot_member)
            if not perms.send_messages or not perms.embed_links:
                await interaction.response.send_message(
                    f"⚠️ Warning: Bot lacks Send Messages or Embed Links permissions in {target_channel.mention}.",
                    ephemeral=True,
                )
                return

        bot.state.set_guild_channel(guild.id, target_channel.id)
        await interaction.response.send_message(
            f"✅ Report channel set to {target_channel.mention} for **{guild.name}**."
        )
        logger.info("Report channel updated to %d for guild %d by %s.", target_channel.id, guild.id, interaction.user)

    @report_group.command(
        name="potd",
        description="Configure Problem of the Day channel and toggle for this server.",
    )
    async def report_potd_command(
        interaction: discord.Interaction,
        target_channel: discord.TextChannel | None = None,
        enabled: bool = True,
    ) -> None:
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Admin permissions required.", ephemeral=True)
            return

        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ This command must be run inside a server.", ephemeral=True)
            return

        assert bot.state is not None
        chan_id = target_channel.id if target_channel else None
        bot.state.set_guild_potd(guild.id, chan_id, enabled=enabled)

        status_text = "enabled" if enabled else "disabled"
        chan_text = target_channel.mention if target_channel else "default report channel"
        await interaction.response.send_message(
            f"✅ POTD {status_text} in {chan_text} for **{guild.name}**."
        )
        logger.info("POTD set to %s (channel: %s) for guild %d by %s.", status_text, chan_id, guild.id, interaction.user)

    bot.tree.add_command(report_group)


# ---------------------------------------------------------------------------
# Render Keep-Alive Server
# ---------------------------------------------------------------------------

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()

def keep_alive():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logger.info("Starting Render health check server on port %d...", port)
    threading.Thread(target=server.serve_forever, daemon=True).start()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Set up logging, start health check server, create the bot, and run it."""
    _setup_logging()
    logger.info("Starting LeetCode Discord Bot...")

    # Start dummy HTTP server for Render health checks
    keep_alive()

    bot = LeetCodeBot()

    try:
        bot.run(config.DISCORD_TOKEN, log_handler=None)
    except discord.LoginFailure:
        logger.critical(
            "Invalid Discord token. Check DISCORD_TOKEN in your .env file."
        )
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received — exiting.")


if __name__ == "__main__":
    main()
