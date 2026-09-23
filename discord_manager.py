"""
discord_manager.py
------------------
Handles all interactions with the Discord API.

Responsibilities:
  - Sending new messages (embeds)
  - Editing existing messages
  - Recovering message IDs after restart
  - Handling Discord rate limits with exponential backoff
  - Logging all Discord actions

All Discord operations are retried up to DISCORD_MAX_RETRIES times
with exponential backoff to survive transient failures.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord

import config
from state_manager import StateManager

logger = logging.getLogger(__name__)


async def _discord_backoff(attempt: int) -> None:
    delay = min(
        config.DISCORD_RETRY_BASE_DELAY * (2 ** attempt),
        config.DISCORD_RETRY_MAX_DELAY,
    )
    logger.debug("Discord retry backoff %.1fs (attempt %d).", delay, attempt + 1)
    await asyncio.sleep(delay)


class DiscordManager:
    """
    Manages Discord message lifecycle for the report channel.

    Usage::

        dm = DiscordManager(bot_client, state_manager)
        await dm.publish_or_update(embeds)
    """

    def __init__(self, client: discord.Client, state: StateManager) -> None:
        self._client = client
        self._state = state
        self._channel: discord.TextChannel | None = None

    # ------------------------------------------------------------------
    # Channel resolution
    # ------------------------------------------------------------------

    async def get_channel(self, channel_id: int | None = None) -> discord.TextChannel:
        """
        Resolve a Discord text channel by ID, falling back to config.DISCORD_CHANNEL_ID.
        """
        target_id = channel_id or config.DISCORD_CHANNEL_ID
        if not target_id:
            raise RuntimeError("No channel ID provided and DISCORD_CHANNEL_ID is not configured.")

        channel = self._client.get_channel(target_id)
        if channel is None:
            try:
                channel = await self._client.fetch_channel(target_id)
            except discord.NotFound:
                raise RuntimeError(f"Discord channel {target_id} not found.")
            except discord.Forbidden:
                raise RuntimeError(f"Bot lacks permission to access channel {target_id}.")

        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError(f"Channel {target_id} is not a text channel.")

        return channel

    # ------------------------------------------------------------------
    # Message recovery
    # ------------------------------------------------------------------

    async def recover_message(
        self,
        channel_id: int | None = None,
        guild_id: int | str | None = None,
    ) -> discord.Message | None:
        """
        Attempt to fetch the stored report message from Discord for a guild or fallback.
        """
        if guild_id is not None:
            message_id = self._state.get_guild_message_id(guild_id)
        else:
            message_id = self._state.get_message_id()

        if message_id is None:
            logger.info("No stored message ID: will create new message.")
            return None

        try:
            channel = await self.get_channel(channel_id)
        except Exception as exc:
            logger.error("Could not resolve channel for message recovery: %s", exc)
            return None

        for attempt in range(config.DISCORD_MAX_RETRIES):
            try:
                message = await channel.fetch_message(message_id)
                logger.info("Recovered existing report message (ID: %d).", message_id)
                return message
            except discord.NotFound:
                logger.warning(
                    "Stored message ID %d not found: will create a new one.", message_id
                )
                if guild_id is not None:
                    self._state.set_guild_message_id(guild_id, None)
                else:
                    self._state.set_message_id(None)
                return None
            except discord.HTTPException as exc:
                if exc.status == 429:
                    logger.warning("Rate limited fetching message (attempt %d).", attempt + 1)
                    await _discord_backoff(attempt)
                else:
                    logger.error("HTTP error fetching message: %s", exc)
                    return None

        return None

    # ------------------------------------------------------------------
    # Text Dump Channel
    # ------------------------------------------------------------------

    async def send_weekly_text_summary(self, messages: list[str]) -> None:
        """Sends the weekly text summary blocks to the designated text channel."""
        if not hasattr(config, 'WEEKLY_TEXT_CHANNEL_ID'):
            logger.warning("WEEKLY_TEXT_CHANNEL_ID not set. Skipping text summary.")
            return
            
        try:
            channel = await self._client.fetch_channel(config.WEEKLY_TEXT_CHANNEL_ID)
            if not isinstance(channel, discord.TextChannel):
                logger.error("Weekly text channel is not a text channel.")
                return
                
            for msg in messages:
                if msg.strip():
                    await channel.send(msg)
            logger.info("Sent weekly text summary (%d chunks) to channel %d", len(messages), config.WEEKLY_TEXT_CHANNEL_ID)
        except Exception as e:
            logger.error("Failed to send weekly text summary: %s", e)

    # ------------------------------------------------------------------
    # Send new message
    # ------------------------------------------------------------------

    async def send_report(
        self,
        summary_embed: discord.Embed,
        detailed_embeds: list[discord.Embed],
        channel_id: int | None = None,
        guild_id: int | str | None = None,
    ) -> discord.Message | None:
        """
        Send a new message with the summary embed and interactive dropdown view.
        """
        from formatter import ReportView
        view = ReportView(self._client, summary_embed, detailed_embeds)
        try:
            channel = await self.get_channel(channel_id)
        except Exception as exc:
            logger.error("Could not resolve channel to send report: %s", exc)
            return None

        for attempt in range(config.DISCORD_MAX_RETRIES):
            try:
                message = await channel.send(embed=summary_embed, view=view)
                if guild_id is not None:
                    self._state.set_guild_message_id(guild_id, message.id)
                else:
                    self._state.set_message_id(message.id)
                logger.info("Sent new report message (ID: %d).", message.id)
                return message
            except discord.HTTPException as exc:
                if exc.status == 429:
                    retry_after = getattr(exc, "retry_after", None)
                    if retry_after:
                        logger.warning(
                            "Rate limited sending message. Retry after %.1fs.", retry_after
                        )
                        await asyncio.sleep(float(retry_after) + 0.5)
                    else:
                        await _discord_backoff(attempt)
                else:
                    logger.error(
                        "Failed to send message (attempt %d): %s", attempt + 1, exc
                    )
                    await _discord_backoff(attempt)
            except discord.Forbidden:
                logger.error(
                    "Bot lacks permission to send messages in #%s.", channel.name
                )
                return None

        logger.error("All %d send attempts failed.", config.DISCORD_MAX_RETRIES)
        return None

    # ------------------------------------------------------------------
    # Edit existing message
    # ------------------------------------------------------------------

    async def edit_report(
        self,
        message: discord.Message,
        summary_embed: discord.Embed,
        detailed_embeds: list[discord.Embed],
        guild_id: int | str | None = None,
    ) -> bool:
        """
        Edit an existing Discord message with the updated summary embed and view.
        """
        from formatter import ReportView
        view = ReportView(self._client, summary_embed, detailed_embeds)

        for attempt in range(config.DISCORD_MAX_RETRIES):
            try:
                await message.edit(embed=summary_embed, view=view)
                logger.info("Updated report message (ID: %d).", message.id)
                return True
            except discord.HTTPException as exc:
                if exc.status == 429:
                    retry_after = getattr(exc, "retry_after", None)
                    if retry_after:
                        await asyncio.sleep(float(retry_after) + 0.5)
                    else:
                        await _discord_backoff(attempt)
                elif exc.status == 404:
                    logger.warning("Message %d no longer exists.", message.id)
                    if guild_id is not None:
                        self._state.set_guild_message_id(guild_id, None)
                    else:
                        self._state.set_message_id(None)
                    return False
                else:
                    logger.error(
                        "Failed to edit message (attempt %d): %s", attempt + 1, exc
                    )
                    await _discord_backoff(attempt)
            except discord.Forbidden:
                logger.error("Bot lacks permission to edit messages.")
                return False

        logger.error("All %d edit attempts failed.", config.DISCORD_MAX_RETRIES)
        return False

    # ------------------------------------------------------------------
    # Publish or update (main entry point)
    # ------------------------------------------------------------------

    async def publish_or_update(
        self,
        summary_embed: discord.Embed,
        detailed_embeds: list[discord.Embed],
        channel_id: int | None = None,
        guild_id: int | str | None = None,
    ) -> None:
        """
        Publish a new report or update the existing one for a channel / guild.
        """
        existing = await self.recover_message(channel_id=channel_id, guild_id=guild_id)

        if existing is not None:
            success = await self.edit_report(
                existing, summary_embed, detailed_embeds, guild_id=guild_id
            )
            if not success:
                logger.warning("Edit failed: attempting to send a new message.")
                await self.send_report(
                    summary_embed, detailed_embeds, channel_id=channel_id, guild_id=guild_id
                )
        else:
            await self.send_report(
                summary_embed, detailed_embeds, channel_id=channel_id, guild_id=guild_id
            )

    # ------------------------------------------------------------------
    # New-week reset
    # ------------------------------------------------------------------

    async def start_new_week(
        self,
        summary_embed: discord.Embed,
        detailed_embeds: list[discord.Embed],
        channel_id: int | None = None,
        guild_id: int | str | None = None,
    ) -> None:
        """
        Send a brand-new message for the new week and clean up older summaries.
        """
        logger.info("Starting new week: creating fresh report message.")
        if guild_id is not None:
            self._state.set_guild_message_id(guild_id, None)
        else:
            self._state.set_message_id(None)

        await self.send_report(
            summary_embed, detailed_embeds, channel_id=channel_id, guild_id=guild_id
        )
        await self.cleanup_channel_duplicates(
            channel_id=channel_id, guild_id=guild_id, keep_current_message=True
        )

    async def cleanup_channel_duplicates(
        self,
        channel_id: int | None = None,
        guild_id: int | str | None = None,
        keep_current_message: bool = True,
    ) -> int:
        """
        Delete older duplicate 'Weekly LeetCode Summary' messages in the report channel,
        leaving only the current active report message.
        """
        try:
            channel = await self.get_channel(channel_id)
        except Exception as exc:
            logger.error("Could not resolve channel for cleanup: %s", exc)
            return 0

        if keep_current_message:
            if guild_id is not None:
                current_id = self._state.get_guild_message_id(guild_id)
            else:
                current_id = self._state.get_message_id()
        else:
            current_id = None

        deleted_count = 0

        try:
            async for msg in channel.history(limit=50):
                if msg.author.id != self._client.user.id:
                    continue
                if current_id and msg.id == current_id:
                    continue

                is_report = False
                if msg.embeds:
                    for embed in msg.embeds:
                        if embed.title and "Weekly LeetCode Summary" in embed.title:
                            is_report = True
                            break

                if is_report:
                    try:
                        await msg.delete()
                        deleted_count += 1
                        await asyncio.sleep(0.5)
                    except Exception as exc:
                        logger.warning("Failed to delete duplicate message %d: %s", msg.id, exc)

            logger.info("Cleaned up %d duplicate report message(s).", deleted_count)
        except Exception as exc:
            logger.error("Error during channel duplicate cleanup: %s", exc)

        return deleted_count

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    async def send_error_notification(
        self,
        title: str,
        description: str,
        channel_id: int | None = None,
    ) -> None:
        """
        Send a brief error notification embed to the report channel.
        Does not affect the stored message ID.
        """
        from formatter import build_error_embed

        embed = build_error_embed(title, description)
        try:
            channel = await self.get_channel(channel_id)
            await channel.send(embed=embed)
        except Exception as exc:
            logger.error("Could not send error notification: %s", exc)

    async def send_nudge_ping(
        self,
        mentions: list[str],
        channel_id: int | None = None,
    ) -> None:
        """
        Send a reminder ping to users who haven't solved a problem today.
        """
        if not mentions:
            return

        try:
            channel = await self.get_channel(channel_id)
        except Exception as exc:
            logger.error("Could not resolve channel for nudge ping: %s", exc)
            return

        mention_str = " ".join(mentions)

        embed = discord.Embed(
            title="⏰ 10 PM Nudge! Keep your streaks alive!",
            description="You haven't solved any LeetCode problems today! Midnight is approaching... time to lock in a quick Easy problem to keep your streak burning! 🔥",
            color=discord.Color.orange(),
        )

        try:
            await channel.send(content=mention_str, embed=embed, delete_after=60.0)
            logger.info("Sent 10 PM nudge ping to %d users.", len(mentions))
        except discord.HTTPException as exc:
            logger.error("Could not send nudge ping: %s", exc)

    async def send_potd(
        self,
        potd_data: dict[str, Any],
        channel_id: int | None = None,
    ) -> discord.Message | None:
        """
        Send the Problem of the Day to the specified channel.

        Returns the sent Message so callers can track and delete it later.
        """
        if not potd_data:
            return

        try:
            channel = await self.get_channel(channel_id)
        except Exception as exc:
            logger.error("Could not resolve channel for POTD: %s", exc)
            return

        diff_color = {
            "Easy": discord.Color.green(),
            "Medium": discord.Color.gold(),
            "Hard": discord.Color.red(),
        }.get(potd_data["difficulty"], discord.Color.blue())

        url = f"{config.LEETCODE_BASE_URL}{potd_data['link']}"

        embed = discord.Embed(
            title="🎯 LeetCode Problem of the Day",
            description=f"**[{potd_data['title']}]({url})**\n\n"
                        f"**Difficulty:** {potd_data['difficulty']}\n"
                        f"**Topics:** {', '.join(potd_data['tags']) if potd_data['tags'] else 'None'}",
            color=diff_color,
        )
        embed.set_footer(text=f"Date: {potd_data['date']}")

        try:
            sent = await channel.send(embed=embed)
            logger.info("Sent POTD to Discord channel #%s.", channel.name)
            return sent
        except discord.HTTPException as exc:
            logger.error("Could not send POTD: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Archive channel  (permanent file uploads)
    # ------------------------------------------------------------------

    async def archive_daily_report(
        self,
        today: "date",
        report_path: "Path",
    ) -> None:
        """
        Upload today's Markdown report as a file attachment to the archive channel.

        This creates a permanent record in Discord that survives:
        - Bot restarts / redeploys
        - Ephemeral cloud filesystems (Render, Railway, etc.)
        - The daily report message being deleted or the bot being removed

        The archive channel is separate from the report channel, so its
        history is never edited: just appended to each day.

        Does nothing if DISCORD_ARCHIVE_CHANNEL_ID is 0 (not configured).
        """
        from pathlib import Path
        from datetime import date as _date

        if config.DISCORD_ARCHIVE_CHANNEL_ID == 0:
            logger.debug("Archive channel not configured: skipping upload.")
            return

        if not report_path.exists():
            logger.warning("Archive skipped: report file does not exist at %s.", report_path)
            return

        archive_channel = self._client.get_channel(config.DISCORD_ARCHIVE_CHANNEL_ID)
        if archive_channel is None:
            try:
                archive_channel = await self._client.fetch_channel(config.DISCORD_ARCHIVE_CHANNEL_ID)
            except (discord.NotFound, discord.Forbidden) as exc:
                logger.error("Cannot access archive channel %d: %s", config.DISCORD_ARCHIVE_CHANNEL_ID, exc)
                return

        if not isinstance(archive_channel, discord.TextChannel):
            logger.error("Archive channel %d is not a text channel.", config.DISCORD_ARCHIVE_CHANNEL_ID)
            return

        embed = discord.Embed(
            title=f"📁 Archive: {today.strftime('%A, %d %B %Y')}",
            description=(
                "Daily report saved as a file below.\n"
                "This message is permanent and will never be edited."
            ),
            color=config.EMBED_COLOR_WEEKLY,
        )
        embed.set_footer(text=f"reports/{report_path.name}")

        # Upload the file
        filename = f"leetcode-{today.isoformat()}.md"
        try:
            with report_path.open("rb") as fp:
                file = discord.File(fp, filename=filename)
                await archive_channel.send(embed=embed, file=file)
            logger.info(
                "Daily report archived to #%s as '%s'.",
                archive_channel.name,
                filename,
            )
        except discord.Forbidden:
            logger.error("Bot lacks permission to send files in archive channel #%s.", archive_channel.name)
        except discord.HTTPException as exc:
            logger.error("Failed to upload archive file: %s", exc)
        except OSError as exc:
            logger.error("Could not read report file for upload: %s", exc)

