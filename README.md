# LeetCode Discord Bot (DSA chan)

A fully automated LeetCode tracking and community competition bot for Discord servers.  
Zero manual intervention after setup - just add your profiles and let it run.  
Supports 24/7 cloud hosting on Render and persistent MongoDB Atlas storage.

> **Repository Note**: The primary repository is hosted on [GitLab (park-bit/dsa-chan)](https://gitlab.com/park-bit/dsa-chan). This GitHub repository is an official mirror maintained by the same author. Both repositories are synchronized with the identical codebase.

---

### 🔗 Invite the Bot

[**Click here to invite DSA chan to your server**](https://discord.com/oauth2/authorize?client_id=1513954649466605699&permissions=268823616&scope=bot+applications.commands)

After inviting, run `/setup report_channel:#your-channel` to get started.

---

## Features

| Feature | Description |
|---|---|
| 📊 **Daily Reports** | Automatic daily report with each user's solves, difficulty breakdown, and clickable problem links |
| 🔥 **Streak Tracking** | Current and longest streaks, automatically updated based on daily activity |
| 🏆 **Server Leaderboards** | Weekly and monthly rankings filtered exclusively to members of each server |
| ⚔️ **1v1 Duels** | Challenge server members to live coding races with `/duel` |
| 🎯 **Problem of the Day** | Automated daily LeetCode challenge posting with automatic cleanup of yesterday's post |
| 📈 **Weekly Summaries** | Weekly totals per user embedded with interactive dropdowns and activity charts |
| ⚠️ **Inactive Detection** | Highlights users who did not solve anything today |
| 💾 **Cloud Persistence** | Persistent MongoDB Atlas integration with seamless local JSON fallback |
| 🤖 **Slash Commands** | Modern Discord slash command suite with server admin protections |
| 🔁 **Self-healing** | Retries on LeetCode rate limits and Discord API errors with backoff |

---

<details>
  <summary>📸 View Project Screenshots</summary>

  ![Commands-3](image-4.png)
  ![WeekSummary](image.png)
  ![Profile View](image-1.png)
  ![Commands 2](image-3.png)
  ![Commands-1](image-5.png)

</details>

---

## 🚀 Installation & Local Hosting

### Prerequisites

- Python **3.11+** ([download](https://python.org/downloads/))
- A Discord bot token ([guide below](#creating-a-discord-bot))
- Internet access

### Quick Start

```bash
# 1. Clone the project (GitHub mirror or GitLab primary)
git clone https://github.com/park-bit/LeetTrack.git
cd LeetTrack

# 2. Run the one-click setup
setup.bat

# 3. Configure credentials
code .env

# 4. Configure initial user profiles (optional, users can /register in Discord)
code profiles.json

# 5. Start the bot
start.bat
```

> **Note:** Everything (venv, logs, data, cache) stays inside the project folder.  
> No global installs. No admin privileges required.

---

## ⚙️ Configuration

### `.env` Variables

Copy `.env.example` to `.env` and fill in:

```dotenv
# Required
DISCORD_TOKEN=your_discord_bot_token
DISCORD_CHANNEL_ID=your_default_channel_id

# Optional Cloud Database (MongoDB Atlas)
MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/?appName=Cluster0

# Optional Timezone & Scheduling (UTC matches LeetCode calendar reset at 00:00 UTC)
TIMEZONE=UTC
DAILY_RUN_HOUR=0
DAILY_RUN_MINUTE=0
LOG_LEVEL=INFO
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `DISCORD_TOKEN` | Yes | None | Bot token from Discord Developer Portal |
| `DISCORD_CHANNEL_ID` | Yes | None | Default channel where reports are posted |
| `MONGODB_URI` | No | None | MongoDB Atlas connection string for cloud storage |
| `TIMEZONE` | No | `UTC` | Timezone for day rollover (`UTC` matches LeetCode) |
| `DAILY_RUN_HOUR` | No | `0` | Hour (0-23) to run the daily rollover job |
| `DAILY_RUN_MINUTE` | No | `0` | Minute (0-59) to run the daily rollover job |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

---

## 🏗️ Creating Your Own Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** and enter an application name.
3. Navigate to **Bot** and click **Add Bot**.
4. Under **Token**, click **Reset Token** and copy it into `.env` as `DISCORD_TOKEN`.
5. Under **Privileged Gateway Intents**, keep all intents disabled (the bot uses standard REST and slash commands).
6. Under **OAuth2 -> URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Permissions: `View Channels`, `Send Messages`, `Manage Messages`, `Embed Links`, `Attach Files`, `Read Message History`, `Use External Emojis`, `Add Reactions`, `Manage Roles`
7. Copy the generated URL and authorize the bot to your server.

---

## 📊 Slash Commands

### General User Commands

| Command | Description | Permission |
|---|---|---|
| `/help` | Show full list of commands and usage syntax | Everyone |
| `/status` | View bot uptime, scheduler status, and database health | Everyone |
| `/leaderboard` | View active weekly and daily server rankings | Everyone |
| `/weeksummary` | View interactive charts of community activity | Everyone |
| `/profile` | Check your linked LeetCode profile, solve stats, and active streak | Everyone |
| `/register <name> <url>` | Link your Discord account to a LeetCode profile | Everyone |
| `/unregister` | Unlink your profile from the tracker | Everyone |
| `/fetchdate <YYYY-MM-DD>` | View submissions for any specific date | Everyone |
| `/duel @user [difficulty]` | Challenge another server member to a 1v1 problem race | Everyone |

### Server Admin Commands

| Command | Description | Permission |
|---|---|---|
| `/setup <report_channel> [potd_channel]` | Initialize and configure the bot for your server | Server Admins |
| `/report channel <channel>` | Update the daily report channel for your server | Server Admins |
| `/report potd [channel] [enabled]` | Configure or toggle the Problem of the Day channel | Server Admins |
| `/roll` | Force an immediate report refresh in your server | Server Admins |
| `/run` | Force the daily rollover job globally | Bot Owner / Admins |
| `/lastweek` | Post the raw text dump of the past week's problems | Bot Owner / Admins |
| `/admin add/update/remove` | Global profile management | Bot Owner / Admins |
| `/admin setstreak` | Set current or longest streak for a user | Bot Owner / Admins |

---

## 👥 Multi-Server Support

The bot is designed to serve multiple Discord servers concurrently:
- Each server configures its own dedicated report and POTD channels via `/setup`.
- Leaderboards and reports automatically filter to members of the respective server.
- Profiles and submission history are stored globally, meaning mutual users have identical stats across all servers without duplicate tracking.

---

## ❓ FAQ

**Q: Does this use the official LeetCode API?**  
A: Yes. It uses the public GraphQL endpoint at `leetcode.com/graphql`, the same API backing the LeetCode website.

**Q: When does the daily report rollover happen?**  
A: By default, the rollover runs at 00:00 UTC (05:30 AM IST), aligning exactly with LeetCode's daily problem reset.

**Q: What if our server misses an update during downtime?**  
A: The bot automatically scans and backfills any submissions solved during the current week on next sync. Server admins can also run `/roll` to refresh immediately.

---

## 📄 License

MIT - free to use, modify, and self-host.
