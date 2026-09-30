"""
/dm all      — DMs every human member currently in the server
/dm users    — DMs a specific list of people: tag members normally (@user),
               or paste raw user IDs for people not in this server (works
               only if the bot shares some server with them or has otherwise
               interacted with them — Discord blocks bots from DMing total
               strangers with zero mutual server, no way around that).

Both show a live-updating status message as it goes.
"""
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import re


class MassDM(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    dm_group = app_commands.Group(name="dm", description="Mass-DM members or specific users")

    async def _send_batch(self, interaction: discord.Interaction, targets: list, message: str):
        """targets: list of discord.abc.User/Member objects (already resolved, deduped)."""
        total = len(targets)
        sent, failed = 0, 0
        failed_names = []

        e = discord.Embed(title="📨 Mass DM in Progress", color=discord.Color.blurple())
        e.add_field(name="Progress", value=f"0 / {total}", inline=True)
        e.add_field(name="✅ Sent", value="0", inline=True)
        e.add_field(name="❌ Failed", value="0", inline=True)
        await interaction.followup.send(embed=e, ephemeral=True)

        for i, user in enumerate(targets, start=1):
            try:
                await user.send(message)
                sent += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1
                failed_names.append(str(user))

            # Update the status roughly once per second (matches the send delay below)
            e = discord.Embed(title="📨 Mass DM in Progress", color=discord.Color.blurple())
            e.add_field(name="Progress", value=f"{i} / {total}", inline=True)
            e.add_field(name="✅ Sent", value=str(sent), inline=True)
            e.add_field(name="❌ Failed", value=str(failed), inline=True)
            if failed_names:
                e.add_field(name="Recent Failures", value="\n".join(failed_names[-5:]), inline=False)
            try:
                await interaction.edit_original_response(embed=e)
            except discord.HTTPException:
                pass

            await asyncio.sleep(1)  # pace sends to avoid rate limits / spam flags

        final = discord.Embed(title="✅ Mass DM Complete", color=discord.Color.green())
        final.add_field(name="Total Targeted", value=str(total), inline=True)
        final.add_field(name="Sent Successfully", value=str(sent), inline=True)
        final.add_field(name="Failed", value=str(failed), inline=True)
        if failed_names:
            final.add_field(name="Failed (DMs closed / no mutual server / etc)", value="\n".join(failed_names[:15]) + ("..." if len(failed_names) > 15 else ""), inline=False)
        await interaction.edit_original_response(embed=final)

    @dm_group.command(name="all", description="DM every member currently in this server")
    @app_commands.describe(message="The message to send")
    @app_commands.checks.has_permissions(administrator=True)
    async def dm_all(self, interaction: discord.Interaction, message: str):
        await interaction.response.defer(ephemeral=True)
        targets = [m for m in interaction.guild.members if not m.bot]
        if not targets:
            return await interaction.followup.send("No members to DM.", ephemeral=True)
        await self._send_batch(interaction, targets, message)

    @dm_group.command(name="users", description="DM specific members/users — tag members, or paste raw IDs for non-members")
    @app_commands.describe(
        targets="Mention members (@user) and/or paste raw user IDs, separated by spaces",
        message="The message to send",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def dm_users(self, interaction: discord.Interaction, targets: str, message: str):
        await interaction.response.defer(ephemeral=True)

        ids = set()
        for token in re.findall(r"<@!?(\d+)>|\b(\d{15,20})\b", targets):
            uid = token[0] or token[1]
            ids.add(int(uid))

        if not ids:
            return await interaction.followup.send("❌ No valid mentions or user IDs found.", ephemeral=True)

        resolved = []
        unresolved = []
        for uid in ids:
            member = interaction.guild.get_member(uid)
            if member:
                resolved.append(member)
                continue
            try:
                user = await self.bot.fetch_user(uid)
                resolved.append(user)
            except discord.NotFound:
                unresolved.append(str(uid))

        if unresolved:
            await interaction.followup.send(
                f"⚠️ Couldn't find these user IDs (invalid or Discord doesn't recognize them): {', '.join(unresolved)}. Continuing with the rest...",
                ephemeral=True,
            )

        if not resolved:
            return await interaction.followup.send("❌ No valid targets to DM.", ephemeral=True)

        await self._send_batch(interaction, resolved, message)


async def setup(bot):
    await bot.add_cog(MassDM(bot))
