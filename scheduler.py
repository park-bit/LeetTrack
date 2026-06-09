"""
scheduler.py
------------
APScheduler-based job scheduler for the bot.

Scheduled jobs:
  - Daily at 00:00 local time  → run_daily_job()
  - Weekly on Monday at 00:00  → start_new_week() (runs inside daily job)
  - Monthly on the 1st at 00:01 → reset_monthly_leaderboard()

The scheduler is started after the Discord bot is ready and runs
inside the asyncio event loop.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import config
from leetcode_fetcher import LeetCodeFetcher, Submission
from state_manager import StateManager
from profile_manager import ProfileManager
from roadmap_manager import RoadmapManager
from streak_manager import StreakManager
from leaderboard_manager import LeaderboardManager
from discord_manager import DiscordManager
import formatter

logger = logging.getLogger(__name__)


class DailyScheduler:
    """
    Wraps APScheduler and orchestrates all periodic jobs.

    Usage::

        scheduler = DailyScheduler(state, profile_mgr, roadmap_mgr,
                                    streak_mgr, lb_mgr, discord_mgr)
        scheduler.start()
        # ...later during shutdown:
        scheduler.stop()
    """

    def __init__(
        self,
        state: StateManager,
        profile_manager: ProfileManager,
        roadmap_manager: RoadmapManager,
        streak_manager: StreakManager,
        leaderboard_manager: LeaderboardManager,
        discord_manager: DiscordManager,
    ) -> None:
        self._state = state
        self._profile_manager = profile_manager
        self._roadmap_manager = roadmap_manager
        self._streak_manager = streak_manager
        self._lb_manager = leaderboard_manager
        self._discord_manager = discord_manager

        tz = pytz.timezone(config.TIMEZONE)
        self._scheduler = AsyncIOScheduler(timezone=tz)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Register jobs and start the scheduler."""
        tz_str = config.TIMEZONE

        # Daily job at configured hour:minute
        self._scheduler.add_job(
            self.run_daily_job,
            CronTrigger(
                hour=config.DAILY_RUN_HOUR,
                minute=config.DAILY_RUN_MINUTE,
                timezone=tz_str,
            ),
            id="daily_job",
            name="Daily LeetCode Report",
            max_instances=1,
            misfire_grace_time=300,  # 5 minutes
        )

        # Monthly reset on the 1st at 00:01
        self._scheduler.add_job(
            self._reset_monthly_if_first,
            CronTrigger(day=1, hour=0, minute=1, timezone=tz_str),
            id="monthly_reset",
            name="Monthly Leaderboard Reset",
            max_instances=1,
        )

        self._scheduler.start()
        logger.info(
            "Scheduler started. Daily job at %02d:%02d %s.",
            config.DAILY_RUN_HOUR,
            config.DAILY_RUN_MINUTE,
            config.TIMEZONE,
        )

    def stop(self) -> None:
        """Gracefully shut down the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped.")

    # ------------------------------------------------------------------
    # Daily job
    # ------------------------------------------------------------------

    async def run_daily_job(self, force_new_message: bool = False) -> None:
        """
        Main daily job executed at midnight.

        Steps:
          1. Reload profiles (pick up any additions without restart).
          2. Determine if today is Monday → start new week.
          3. Reset daily stats for all users.
          4. Fetch latest accepted submissions for every user.
          5. Calculate today's solves using TIMESTAMP-ONLY filtering.
             (Submissions are "today's" if their Unix timestamp falls
              within today's local-midnight → tomorrow's local-midnight window.
              known_accepted is NOT used to filter today_subs — only used
              to determine what is new for roadmap/history tracking.)
          6. Update streaks.
          7. Update leaderboard totals.
          8. Build roadmap progress per user.
          9. Publish or update Discord report.
          10. Persist all state.
        """
        now = datetime.now(tz=pytz.timezone(config.TIMEZONE))
        today = now.date()
        logger.info("=== Daily job started: %s ===", today.isoformat())

        # Reload profiles
        self._profile_manager.load()
        profiles = self._profile_manager.get_enabled_profiles()
        if not profiles:
            logger.warning("No enabled profiles found — skipping daily job.")
            return

        # Is today Monday?
        is_monday = today.weekday() == 0

        stored_week_start = self._state.get_week_start()

        # If it's Monday and a new week hasn't started yet, or week_start is missing
        if is_monday and (stored_week_start is None or stored_week_start != today):
            logger.info("Monday detected — starting new week.")
            self._lb_manager.reset_weekly_leaderboard(profiles)
            self._state.set_week_start(today)
        elif stored_week_start is None:
            # If the bot was offline on Monday, backfill the week_start to the most recent Monday
            recent_monday = today - timedelta(days=today.weekday())
            self._state.set_week_start(recent_monday)
            logger.info("Week start was missing. Backfilled to most recent Monday: %s", recent_monday)

        # Archive notification (new message will be sent below)

        # Reset daily stats
        self._state.reset_all_daily_stats()

        # Fetch submissions
        async with LeetCodeFetcher() as fetcher:
            user_data = await fetcher.fetch_all_users(profiles)

        # Process each user
        daily_problems: dict[str, list[dict[str, Any]]] = {}
        daily_stats: dict[str, dict[str, int]] = {}

        tz = pytz.timezone(config.TIMEZONE)
        today_dt = tz.localize(datetime(today.year, today.month, today.day, 0, 0, 0))
        today_start_ts = int(today_dt.timestamp())
        today_end_ts = today_start_ts + 86400
        # Unix timestamp at noon today — used by Discord's <t:TS:D> rendering
        today_noon_ts = today_start_ts + 43200

        for profile in profiles:
            name = profile["name"]
            submissions, lc_stats = user_data.get(name, ([], None))

            stats = self._state.get_user_stats(name)
            known_slugs: list[str] = stats.get("known_accepted", [])

            # TODAY'S solves: filter purely by timestamp.
            # We do NOT exclude known_slugs here — that would cause problems
            # to disappear if /run is triggered twice on the same day.
            today_subs: list[Submission] = [
                s for s in submissions
                if today_start_ts <= s.timestamp < today_end_ts
            ]

            # De-duplicate by slug (LeetCode may return multiple submission
            # records for the same accepted problem — keep the latest one).
            seen_today: set[str] = set()
            unique_today_subs: list[Submission] = []
            for s in sorted(today_subs, key=lambda x: x.timestamp, reverse=True):
                if s.slug not in seen_today:
                    seen_today.add(s.slug)
                    unique_today_subs.append(s)
            today_subs = unique_today_subs

            # Track ALL new slugs (across all time) for history.
            all_new_slugs: list[str] = [
                s.slug for s in submissions if s.slug not in known_slugs
            ]

            # Exact delta calculation using LeetCode's lifetime counts
            # This completely bypasses the 15-item limit on recent submissions!
            if lc_stats:
                old_total = stats.get("total_solved", 0)
                old_easy = stats.get("easy", 0)
                old_medium = stats.get("medium", 0)
                old_hard = stats.get("hard", 0)

                # Only calculate delta if we had a previous run, otherwise fallback to the len of today_subs
                if old_total > 0:
                    solved = max(0, lc_stats.total_solved - old_total)
                    easy = max(0, lc_stats.easy_solved - old_easy)
                    medium = max(0, lc_stats.medium_solved - old_medium)
                    hard = max(0, lc_stats.hard_solved - old_hard)
                else:
                    easy = sum(1 for s in today_subs if s.difficulty == "Easy")
                    medium = sum(1 for s in today_subs if s.difficulty == "Medium")
                    hard = sum(1 for s in today_subs if s.difficulty == "Hard")
                    solved = len(today_subs)

                # Update the baseline for tomorrow
                stats["total_solved"] = lc_stats.total_solved
                stats["easy"] = lc_stats.easy_solved
                stats["medium"] = lc_stats.medium_solved
                stats["hard"] = lc_stats.hard_solved

            # Fallback if the exact delta API lagged behind but we physically saw recent submissions
            if solved == 0 and len(today_subs) > 0:
                solved = len(today_subs)
                easy = max(easy, sum(1 for s in today_subs if s.difficulty == "Easy"))
                medium = max(medium, sum(1 for s in today_subs if s.difficulty == "Medium"))
                hard = max(hard, sum(1 for s in today_subs if s.difficulty == "Hard"))

            # Update daily stats in state
            stats["daily_solved"] = solved
            stats["daily_easy"] = easy
            stats["daily_medium"] = medium
            stats["daily_hard"] = hard

            # Extend known_accepted (for deduplication on future runs)
            stats["known_accepted"] = list(set(known_slugs + all_new_slugs))
            stats["last_updated"] = today.isoformat()
            self._state.set_user_stats(name, stats)

            # Persist history
            for sub in today_subs:
                self._state.add_history_entry(
                    name,
                    today.isoformat(),
                    {
                        "slug": sub.slug,
                        "title": sub.title,
                        "difficulty": sub.difficulty,
                        "url": sub.url,
                        "lang": sub.lang,
                        "timestamp": sub.timestamp,
                        "tags": sub.tags,
                    },
                )

            # Leaderboard update (monthly accumulation)
            self._lb_manager.record_daily_solves(name, solved, easy, medium, hard)

            # Collect for formatter
            daily_problems[name] = [
                {
                    "slug": s.slug,
                    "title": s.title,
                    "difficulty": s.difficulty,
                    "url": s.url,
                    "tags": s.tags,
                }
                for s in today_subs
            ]
            daily_stats[name] = {
                "solved": solved,
                "easy": easy,
                "medium": medium,
                "hard": hard,
            }

            logger.info(
                "Processed %s: %d problems today (E:%d M:%d H:%d).",
                name, solved, easy, medium, hard,
            )

        # Update streaks
        solve_counts = {name: daily_stats[name]["solved"] for name in daily_stats}
        self._streak_manager.update_all(solve_counts, today)

        week_start_date = self._state.get_week_start()

        # Gather history for all days from week_start to today
        daily_history = []
        if week_start_date:
            delta_days = (today - week_start_date).days
            if delta_days < 0:
                delta_days = 0
            
            # Add past days up to yesterday
            for i in range(delta_days):
                d = week_start_date + timedelta(days=i)
                probs = {}
                for p in profiles:
                    name = p["name"]
                    day_probs = self._state.get_day_problems(name, d.isoformat())
                    if day_probs:
                        probs[name] = day_probs
                daily_history.append((d, probs))

        # Add today's problems to the end of the history stack
        daily_history.append((today, daily_problems))

        # Build multiple embeds (one for each day)
        embeds = formatter.build_weekly_aggregate_embeds(
            profiles=profiles,
            daily_history=daily_history,
        )

        # Publish to Discord
        if force_new_message or (is_monday and (self._state.get_week_start() == today)):
            # First Monday of new week OR forced by /roll — send a fresh message
            await self._discord_manager.start_new_week(embeds)
        else:
            await self._discord_manager.publish_or_update(embeds)

        # Persist state
        self._state.set_last_run(now)
        # Save local markdown archive and upload to Discord archive channel
        await self._save_daily_report(
            today=today,
            profiles=profiles,
            daily_problems=daily_problems,
            daily_stats=daily_stats,
        )

        self._state.save()

        logger.info("=== Daily job completed: %s ===", today.isoformat())

    # ------------------------------------------------------------------
    # Monthly reset
    # ------------------------------------------------------------------

    async def _reset_monthly_if_first(self) -> None:
        """Reset monthly leaderboard on the 1st of each month."""
        now = datetime.now(tz=pytz.timezone(config.TIMEZONE))
        logger.info("Monthly reset triggered on %s.", now.date().isoformat())
        self._lb_manager.reset_monthly_leaderboard()
        self._state.save()
        logger.info("Monthly leaderboard reset completed.")

    # ------------------------------------------------------------------
    # Manual trigger (for testing / on-demand runs)
    # ------------------------------------------------------------------

    async def trigger_now(self, force_new_message: bool = False) -> None:
        """Manually trigger the daily job (useful for initial testing or /roll)."""
        logger.info("Manual daily job trigger requested. (force_new_message=%s)", force_new_message)
        await self.run_daily_job(force_new_message=force_new_message)

    # ------------------------------------------------------------------
    # Local report archiving
    # ------------------------------------------------------------------

    async def _save_daily_report(
        self,
        today: "date",
        profiles: list,
        daily_problems: dict,
        daily_stats: dict,
    ) -> None:
        """
        Save today's report as a Markdown file under reports/<date>.md.

        These files act as a permanent local archive — they survive Discord
        message deletion, bot removal, or channel wipes.  Each file is
        human-readable and can be committed to a git repo for off-site backup.
        """
        config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        filepath = config.REPORTS_DIR / f"{today.isoformat()}.md"

        lines: list[str] = [
            f"# Daily LeetCode Report — {today.strftime('%A, %d %B %Y')}",
            f"> Generated: {datetime.now(tz=pytz.timezone(config.TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S %Z')}",
            "",
        ]

        active_profiles  = [p for p in profiles if daily_stats.get(p["name"], {}).get("solved", 0) > 0]
        inactive_profiles = [p for p in profiles if daily_stats.get(p["name"], {}).get("solved", 0) == 0]

        for profile in active_profiles:
            name  = profile["name"]
            stats = daily_stats.get(name, {})
            problems = daily_problems.get(name, [])

            diff_parts = []
            if stats.get("easy"):   diff_parts.append(f"Easy: {stats['easy']}")
            if stats.get("medium"): diff_parts.append(f"Medium: {stats['medium']}")
            if stats.get("hard"):   diff_parts.append(f"Hard: {stats['hard']}")
            diff_str = " · ".join(diff_parts) if diff_parts else "Easy: 0"

            lines.append(f"## {name}")
            lines.append(f"**{stats['solved']} solved** ({diff_str})")
            lines.append("")

            for idx, prob in enumerate(problems, start=1):
                title = prob.get("title", prob.get("slug", ""))
                diff  = prob.get("difficulty", "")
                url   = prob.get("url", "")
                tags  = prob.get("tags", [])
                tag_str = " ".join(f"[{t}]" for t in tags)
                tag_part = f"  {tag_str}" if tag_str else ""
                lines.append(f"{idx}. {title} ({diff}){tag_part}")
                lines.append(f"   {url}")

            lines.append("")

        if inactive_profiles:
            lines.append("## No submissions today")
            for profile in inactive_profiles:
                lines.append(f"- {profile['name']}")
            lines.append("")

        lines.append("---")

        try:
            filepath.write_text("\n".join(lines), encoding="utf-8")
            logger.info("Daily report archived locally → %s", filepath)

            # Upload to Discord Archive Channel
            await self._discord_manager.archive_daily_report(
                today=today,
                report_path=filepath,
            )
        except OSError as exc:
            logger.error("Could not write daily report archive: %s", exc)
