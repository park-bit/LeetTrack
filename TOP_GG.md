# Top.gg Listing Documentation for DSA chan

Documentation, listing copy, and reviewer notes for Top.gg and Discord App Directory submission.

---

## 1. Application Details

- **Bot Name**: DSA chan
- **Application ID / Client ID**: `1513954649466605699`
- **Prefix**: Slash Commands (`/`)
- **Repository URL**: `https://github.com/park-bit/LeetTrack`
- **Primary Repository (GitLab)**: `https://gitlab.com/park-bit/dsa-chan`
- **Invite URL**: `https://discord.com/oauth2/authorize?client_id=1513954649466605699&permissions=268823616&scope=bot+applications.commands`

---

## 2. Categories & Tags

- **Primary Category**: Education
- **Secondary Categories**: Productivity, Social, Gaming
- **Tags**: `leetcode`, `coding`, `dsa`, `programming`, `leaderboard`, `streaks`, `developer`, `education`

---

## 3. Short Description (Max 140 chars)

> Automated LeetCode tracker with server leaderboards, daily streaks, 1v1 duels, and Problem of the Day.

---

## 4. Long Description (Markdown for Top.gg Page)

```markdown
# DSA chan - Automated LeetCode Tracker & Leaderboard

DSA chan helps coding communities stay consistent with daily algorithmic practice. Track solves, maintain streaks, compete on server leaderboards, and duel your peers directly in Discord.

## Features

- **Automated Daily Reports**: Posts a weekly summary with interactive day-by-day submission breakdowns.
- **Server Leaderboards**: Tracks weekly and monthly rankings filtered exclusively to members in your server.
- **Problem of the Day**: Posts daily LeetCode challenges and cleans up yesterday's post automatically.
- **Streak Tracking**: Tracks current and all-time maximum streaks with streak freeze logic.
- **1v1 Coding Duels**: Challenge friends with `/duel` on a random problem and see who gets accepted first.
- **Visual Analytics**: Interactive dropdowns, activity heatmaps, and weekly performance charts.
- **Multi-Server Ready**: Each Discord server configures its own channels and sees only its own members.

---

## Commands

### User Commands
- `/register <name> <url>`: Link your LeetCode profile to your Discord account.
- `/profile`: View your linked profile, solve stats, and active streak.
- `/leaderboard`: View today's and this week's server rankings.
- `/weeksummary`: Display a graphical chart of community activity over the last 7 days.
- `/fetchdate <YYYY-MM-DD>`: Check submissions across the server for any past date.
- `/duel @user [difficulty]`: Challenge a server member to a 1v1 problem race.
- `/status`: Check bot uptime, scheduler status, and database health.
- `/help`: Show the complete command list and usage instructions.

### Admin Commands (Server Admins Only)
- `/setup <report_channel> [potd_channel]`: One-click setup wizard for new servers.
- `/report channel <channel>`: Change the automated report channel.
- `/report potd [channel] [enabled]`: Configure or toggle the Problem of the Day channel.
- `/roll`: Force an immediate report rollout in your server.

---

## Quick Setup

1. Invite the bot to your server.
2. Run `/setup report_channel:#your-channel`.
3. Have members run `/register name:YourName url:https://leetcode.com/u/your_username/`.
4. The bot automatically takes care of the rest at midnight UTC.
```

---

## 5. Note for Reviewer

```text
Hello reviewer,

DSA chan is an automated LeetCode tracker and community leaderboard bot.

All interactions use Discord Slash Commands (/).

Steps to test the bot:
1. Run `/setup report_channel:#<channel>` in any channel to initialize the server report channel.
2. Run `/register name:TestUser url:https://leetcode.com/u/park-bit/` to link a test LeetCode profile.
3. Run `/profile` to view the registered card, stats, and streak.
4. Run `/leaderboard` to check current server rankings.
5. Run `/status` to verify scheduler, database, and bot uptime.
6. Run `/roll` (Admin only) to immediately test-render the weekly report embed with interactive dropdowns.

Bot is hosted 24/7 on Render backed by persistent MongoDB Atlas storage.

Thank you!
```
