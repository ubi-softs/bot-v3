import discord
from discord import app_commands
from discord.ext import commands


class PersonalInvite(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="invitecreate", description="Generate a personal invite link you can share")
    @app_commands.describe(max_uses="Max number of times it can be used (0 = unlimited)", expires_hours="Hours until it expires (0 = never)")
    async def invitecreate(self, interaction: discord.Interaction, max_uses: app_commands.Range[int, 0, 100] = 0, expires_hours: app_commands.Range[int, 0, 720] = 0):
        channel = interaction.channel
        try:
            invite = await channel.create_invite(
                max_uses=max_uses,
                max_age=expires_hours * 3600,
                unique=True,
                reason=f"Personal invite for {interaction.user}",
            )
        except discord.Forbidden:
            return await interaction.response.send_message("❌ I don't have permission to create invites here.", ephemeral=True)

        e = discord.Embed(title="🔗 Your Personal Invite", description=invite.url, color=discord.Color.blurple())
        details = []
        details.append(f"Uses: {'Unlimited' if max_uses == 0 else max_uses}")
        details.append(f"Expires: {'Never' if expires_hours == 0 else f'{expires_hours}h'}")
        e.set_footer(text=" • ".join(details))
        await interaction.response.send_message(embed=e, ephemeral=True)


async def setup(bot):
    await bot.add_cog(PersonalInvite(bot))