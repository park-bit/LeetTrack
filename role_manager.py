import logging
import discord
from typing import List, Dict, Any

import config

logger = logging.getLogger(__name__)

class RoleManager:
    """Manages the automatic assignment of Discord roles for top performers and streaks."""

    def __init__(self, bot: discord.Client, profile_manager) -> None:
        self.bot = bot
        self.profile_manager = profile_manager

    async def get_guild(self) -> discord.Guild | None:
        channel = self.bot.get_channel(config.DISCORD_CHANNEL_ID)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(config.DISCORD_CHANNEL_ID)
            except Exception as e:
                logger.error("Failed to fetch guild channel: %s", e)
                return None
        
        if hasattr(channel, "guild"):
            return channel.guild
        return None

    async def get_or_create_role(self, guild: discord.Guild, name: str, color: discord.Color) -> discord.Role | None:
        """Find a role by name, or create it if it doesn't exist."""
        role = discord.utils.get(guild.roles, name=name)
        if role:
            return role
        
        try:
            role = await guild.create_role(name=name, color=color, hoist=True, reason="Auto-created by LeetCode Bot")
            logger.info("Auto-created role: %s", name)
            return role
        except discord.Forbidden:
            logger.error("Bot lacks 'Manage Roles' permission to create %s.", name)
            return None
        except Exception as e:
            logger.error("Error creating role %s: %s", name, e)
            return None

    async def update_weekly_roles(self, leaderboard: List[Dict[str, Any]]) -> None:
        """Assign Rank 1, 2, and 3 roles to the top 3 weekly users."""
        guild = await self.get_guild()
        if not guild:
            return

        role_configs = {
            1: ("🥇 LeetCode Rank 1", discord.Color.gold()),
            2: ("🥈 LeetCode Rank 2", discord.Color.light_gray()),
            3: ("🥉 LeetCode Rank 3", discord.Color.dark_orange()),
        }

        # Ensure roles exist and fetch them
        roles = {}
        for rank, (name, color) in role_configs.items():
            role = await self.get_or_create_role(guild, name, color)
            if role:
                roles[rank] = role

        if not roles:
            return

        # Strip these roles from everyone in the database first
        all_rank_roles = list(roles.values())
        profiles = self.profile_manager.get_enabled_profiles()
        
        for profile in profiles:
            if not profile.get("discord_id"): continue
            try:
                member = await guild.fetch_member(int(profile["discord_id"]))
                roles_to_remove = [r for r in all_rank_roles if r in member.roles]
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove, reason="Weekly Leaderboard Reset")
            except discord.NotFound:
                pass # member left server
            except discord.Forbidden:
                logger.error("Lacking permission to remove roles from %s", profile["name"])
            except Exception as e:
                logger.error("Error removing roles from %s: %s", profile["name"], e)

        # Assign new roles
        profiles = self.profile_manager.get_enabled_profiles()
        for entry in leaderboard:
            rank = entry["rank"]
            if rank not in roles:
                continue
                
            matched_profile = next((p for p in profiles if p["name"] == entry["username"]), None)
            if not matched_profile or not matched_profile.get("discord_id"):
                continue
                
            member = None
            try:
                member = await guild.fetch_member(int(matched_profile["discord_id"]))
            except discord.NotFound:
                pass
                
            if member:
                try:
                    await member.add_roles(roles[rank], reason="Weekly Leaderboard Winner")
                    logger.info("Assigned %s to %s", roles[rank].name, member.display_name)
                except Exception as e:
                    logger.error("Failed to assign %s to %s: %s", roles[rank].name, member.display_name, e)

    async def update_streak_roles(self, active_streaks: Dict[str, int]) -> None:
        """Assign 🔥 On Fire role to anyone with streak >= 7."""
        guild = await self.get_guild()
        if not guild:
            return

        role = await self.get_or_create_role(guild, "🔥 On Fire", discord.Color.red())
        if not role:
            return

        profiles = self.profile_manager.get_enabled_profiles()
        
        # Build set of discord_ids that deserve the role
        deserving_ids = set()
        for username, streak in active_streaks.items():
            if streak >= 7:
                matched_profile = next((p for p in profiles if p["name"] == username), None)
                if matched_profile and matched_profile.get("discord_id"):
                    deserving_ids.add(int(matched_profile["discord_id"]))

        # Update members based on our profiles database
        for profile in profiles:
            if not profile.get("discord_id"): continue
            
            try:
                member = await guild.fetch_member(int(profile["discord_id"]))
                has_role = role in member.roles
                deserves_role = member.id in deserving_ids
    
                if deserves_role and not has_role:
                    try:
                        await member.add_roles(role, reason="LeetCode 7-day streak")
                        logger.info("Assigned On Fire role to %s", member.display_name)
                    except discord.Forbidden:
                        pass
                elif not deserves_role and has_role:
                    try:
                        await member.remove_roles(role, reason="Lost LeetCode streak")
                        logger.info("Removed On Fire role from %s", member.display_name)
                    except discord.Forbidden:
                        pass
            except discord.NotFound:
                pass
            except Exception as e:
                logger.error("Error updating streak roles for %s: %s", profile["name"], e)
