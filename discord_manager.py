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

    async def get_channel(self) -> discord.TextChannel:
        """
        Resolve and cache the configured Discord channel.

        Raises RuntimeError if the channel cannot be found.
        """
        if self._channel is not None:
            return self._channel

        channel = self._client.get_channel(config.DISCORD_CHANNEL_ID)
        if channel is None:
            # Try fetching directly (handles channels not yet in cache)
            try:
                channel = await self._client.fetch_channel(config.DISCORD_CHANNEL_ID)
            except discord.NotFound:
                raise RuntimeError(
                    f"Discord channel {config.DISCORD_CHANNEL_ID} not found. "
                    "Check DISCORD_CHANNEL_ID in your .env file."
                )
            except discord.Forbidden:
                raise RuntimeError(
                    f"Bot lacks permission to access channel {config.DISCORD_CHANNEL_ID}."
                )

        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError(
                f"Channel {config.DISCORD_CHANNEL_ID} is not a text channel."
            )

        self._channel = channel
        logger.info("Resolved report channel: #%s (ID: %d)", channel.name, channel.id)
        return channel

    # ------------------------------------------------------------------
    # Message recovery
    # ------------------------------------------------------------------

    async def recover_message(self) -> discord.Message | None:
        """
        Attempt to fetch the stored report message from Discord.

        Returns None if the message no longer exists or the ID is unset.
        """
        message_id = self._state.get_message_id()
        if message_id is None:
            logger.info("No stored message ID — will create new message.")
            return None

        channel = await self.get_channel()
        for attempt in range(config.DISCORD_MAX_RETRIES):
            try:
                message = await channel.fetch_message(message_id)
                logger.info("Recovered existing report message (ID: %d).", message_id)
                return message
            except discord.NotFound:
                logger.warning(
                    "Stored message ID %d not found — will create a new one.", message_id
                )
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
    # Send new message
    # ------------------------------------------------------------------

    async def send_embeds(self, embeds: list[discord.Embed]) -> discord.Message | None:
        """
        Send a new message with the given embeds to the report channel.

        Discord allows up to 10 embeds per message.  We send the first 10
        (which is more than enough for our report structure).
        """
        channel = await self.get_channel()
        embeds_to_send = embeds[:10]

        for attempt in range(config.DISCORD_MAX_RETRIES):
            try:
                message = await channel.send(embeds=embeds_to_send)
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

    async def edit_embeds(
        self, message: discord.Message, embeds: list[discord.Embed]
    ) -> bool:
        """
        Edit an existing Discord message with updated embeds.

        Returns True on success, False on failure.
        """
        embeds_to_send = embeds[:10]

        for attempt in range(config.DISCORD_MAX_RETRIES):
            try:
                await message.edit(embeds=embeds_to_send)
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

    async def publish_or_update(self, embeds: list[discord.Embed]) -> None:
        """
        Publish a new report or update the existing one.

        Workflow:
          1. Try to recover the stored message.
          2. If found → edit it.
          3. If not found → send a new message and store the ID.
        """
        existing = await self.recover_message()

        if existing is not None:
            success = await self.edit_embeds(existing, embeds)
            if not success:
                logger.warning("Edit failed — attempting to send a new message.")
                await self.send_embeds(embeds)
        else:
            await self.send_embeds(embeds)

    # ------------------------------------------------------------------
    # New-week reset
    # ------------------------------------------------------------------

    async def start_new_week(self, embeds: list[discord.Embed]) -> None:
        """
        Send a brand-new message for the new week, discarding the old message ID.

        The old message remains in Discord for archival purposes but will
        not be edited again.
        """
        logger.info("Starting new week — creating fresh report message.")
        self._state.set_message_id(None)
        await self.send_embeds(embeds)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    async def send_error_notification(self, title: str, description: str) -> None:
        """
        Send a brief error notification embed to the report channel.
        Does not affect the stored message ID.
        """
        from formatter import build_error_embed

        embed = build_error_embed(title, description)
        channel = await self.get_channel()
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            logger.error("Could not send error notification: %s", exc)

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

        This creates a **permanent record** in Discord that survives:
        - Bot restarts / redeploys
        - Ephemeral cloud filesystems (Render, Railway, etc.)
        - The daily report message being deleted or the bot being removed

        The archive channel is separate from the report channel, so its
        history is never edited — just appended to each day.

        Does nothing if DISCORD_ARCHIVE_CHANNEL_ID is 0 (not configured).
        """
        from pathlib import Path
        from datetime import date as _date  # avoid shadowing outer scope

        if config.DISCORD_ARCHIVE_CHANNEL_ID == 0:
            logger.debug("Archive channel not configured — skipping upload.")
            return

        if not report_path.exists():
            logger.warning("Archive skipped: report file does not exist at %s.", report_path)
            return

        # Resolve archive channel
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

        # Build a small header embed
        embed = discord.Embed(
            title=f"📁 Archive — {today.strftime('%A, %d %B %Y')}",
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

