"""
config.py
---------
Central configuration for the LeetCode Discord Bot.
Loads environment variables from .env, resolves all file paths,
and exposes typed constants used across the entire project.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Base paths
# ---------------------------------------------------------------------------

BASE_DIR: Path = Path(__file__).parent.resolve()

load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

DISCORD_TOKEN: str = os.environ.get("DISCORD_TOKEN", "")
DISCORD_CHANNEL_ID: int = int(os.environ.get("DISCORD_CHANNEL_ID", "0"))
# Optional: separate channel for permanent daily report archives (file uploads).
# Set to 0 or leave blank to disable archiving.
DISCORD_ARCHIVE_CHANNEL_ID: int = int(os.environ.get("DISCORD_ARCHIVE_CHANNEL_ID", "0"))

if not DISCORD_TOKEN:
    raise EnvironmentError(
        "DISCORD_TOKEN is not set. "
        "Copy .env.example to .env and fill in your token."
    )
if not DISCORD_CHANNEL_ID:
    raise EnvironmentError(
        "DISCORD_CHANNEL_ID is not set. "
        "Copy .env.example to .env and fill in your channel ID."
    )

# ---------------------------------------------------------------------------
# Timezone
# ---------------------------------------------------------------------------

TIMEZONE: str = os.environ.get("TIMEZONE", "Asia/Kolkata")

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

# Hour and minute (local time) at which the daily job runs.
DAILY_RUN_HOUR: int = int(os.environ.get("DAILY_RUN_HOUR", "0"))
DAILY_RUN_MINUTE: int = int(os.environ.get("DAILY_RUN_MINUTE", "0"))

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

MONGODB_URI: str | None = os.environ.get("MONGODB_URI")

# ---------------------------------------------------------------------------
# Data files
# ---------------------------------------------------------------------------

PROFILES_FILE: Path = BASE_DIR / "profiles.json"
ROADMAP_FILE: Path = BASE_DIR / "roadmap.json"
STATE_FILE: Path = BASE_DIR / "state.json"

DATA_DIR: Path = BASE_DIR / "data"
USER_STATS_FILE: Path = DATA_DIR / "user_stats.json"
STREAKS_FILE: Path = DATA_DIR / "streaks.json"
HISTORY_FILE: Path = DATA_DIR / "history.json"

REPORTS_DIR: Path = BASE_DIR / "reports"  # local daily report archive (Markdown files)

LOGS_DIR: Path = BASE_DIR / "logs"
LOG_FILE: Path = LOGS_DIR / "bot.log"

# ---------------------------------------------------------------------------
# LeetCode API
# ---------------------------------------------------------------------------

LEETCODE_BASE_URL: str = "https://leetcode.com"
LEETCODE_GRAPHQL_URL: str = "https://leetcode.com/graphql"

# How many recent submissions to fetch per user.
RECENT_SUBMISSIONS_LIMIT: int = 50

# HTTP request settings
REQUEST_TIMEOUT: int = 30          # seconds
MAX_RETRIES: int = 5
RETRY_BASE_DELAY: float = 1.0      # seconds (doubles each retry)
RETRY_MAX_DELAY: float = 60.0      # seconds
RATE_LIMIT_DELAY: float = 1.0      # seconds between successive user fetches

# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

DISCORD_MAX_RETRIES: int = 5
DISCORD_RETRY_BASE_DELAY: float = 2.0  # seconds
DISCORD_RETRY_MAX_DELAY: float = 60.0  # seconds

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_MAX_BYTES: int = 5 * 1024 * 1024  # 5 MB per log file
LOG_BACKUP_COUNT: int = 5
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

EMBED_COLOR_DAILY: int = 0x5865F2    # Discord blurple
EMBED_COLOR_WEEKLY: int = 0xFEE75C   # Gold
EMBED_COLOR_LEADERBOARD: int = 0x57F287  # Green
EMBED_COLOR_ERROR: int = 0xED4245    # Red
EMBED_COLOR_WARNING: int = 0xFFA500  # Orange
