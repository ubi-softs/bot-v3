import discord
from discord import app_commands
from discord.ext import commands

ONLINE_STATUSES = {discord.Status.online, discord.Status.idle, discord.Status.dnd}


class OnlineRole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="onlinerole", description="Give (or remove) a role for everyone currently online")
    @app_commands.describe(
        role="The role to give out",
        remove="If true, removes the role instead of adding it",
        include_idle_dnd="Count Idle and Do Not Disturb as 'online' too (default: yes)",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def onlinerole(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        remove: bool = False,
        include_idle_dnd: bool = True,
    ):
        guild = interaction.guild

        # Safety checks
        if role.is_default():
            return await interaction.response.send_message("❌ You can't use @everyone for this.", ephemeral=True)
        if role >= guild.me.top_role:
            return await interaction.response.send_message(
                "❌ I can't manage that role — it's higher than or equal to my own top role. Move my role above it in Server Settings → Roles.",
                ephemeral=True,
            )
        if role >= interaction.user.top_role and interaction.user.id != guild.owner_id:
            return await interaction.response.send_message("❌ You can't assign a role equal to or higher than your own top role.", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)

        statuses = ONLINE_STATUSES if include_idle_dnd else {discord.Status.online}

        targets = []
        for member in guild.members:
            if member.bot:
                continue
            if member.status not in statuses:
                continue
            has_role = role in member.roles
            if remove and has_role:
                targets.append(member)
            elif not remove and not has_role:
                targets.append(member)

        if not targets:
            verb = "have" if remove else "already have"
            return await interaction.followup.send(f"✅ No changes needed — no online members {'need the role removed' if remove else 'are missing the role'}.", ephemeral=True)

        success, failed = 0, 0
        for member in targets:
            try:
                if remove:
                    await member.remove_roles(role, reason=f"/onlinerole by {interaction.user}")
                else:
                    await member.add_roles(role, reason=f"/onlinerole by {interaction.user}")
                success += 1
            except discord.HTTPException:
                failed += 1

        action = "Removed from" if remove else "Given to"
        summary = f"✅ **{action}** {success} online member(s): {role.mention}"
        if failed:
            summary += f"\n⚠️ Failed on {failed} member(s) (likely permission/hierarchy issues)."

        await interaction.followup.send(summary, ephemeral=True)

    @onlinerole.error
    async def onlinerole_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ You need Manage Roles permission to use this.", ephemeral=True)
            return
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ Error: {error}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ Error: {error}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(OnlineRole(bot))