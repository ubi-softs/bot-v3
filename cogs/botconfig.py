import discord
from discord import app_commands
from discord.ext import commands
import json, os
import aiohttp

CONFIG_FILE = "data/bot_config.json"


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(d):
    os.makedirs("data", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(d, f, indent=2)


class BotConfig(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    config_group = app_commands.Group(name="config", description="Configure bot-wide settings")

    @config_group.command(name="admin-role", description="Set the role treated as your admin role for reference (informational)")
    @app_commands.describe(role="Your admin role")
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_role(self, interaction: discord.Interaction, role: discord.Role):
        config = load_config()
        config.setdefault(str(interaction.guild.id), {})["admin_role"] = str(role.id)
        save_config(config)
        await interaction.response.send_message(
            f"✅ Noted {role.mention} as your admin role.\n"
            f"💡 This is a reference only — actual command permissions still follow real Discord permissions "
            f"(e.g. Administrator, Manage Guild) on each command, not this setting.",
            ephemeral=True,
        )

    @config_group.command(name="view", description="View this server's current bot configuration")
    async def view(self, interaction: discord.Interaction):
        config = load_config().get(str(interaction.guild.id), {})
        admin_role_id = config.get("admin_role")
        admin_role = interaction.guild.get_role(int(admin_role_id)) if admin_role_id else None

        e = discord.Embed(title="⚙️ Bot Configuration", color=discord.Color.blurple())
        e.add_field(name="Admin Role", value=admin_role.mention if admin_role else "Not set", inline=True)
        e.add_field(name="Command Prefix", value=self.bot.command_prefix, inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @config_group.command(name="bot-name", description="Change the bot's display username (owner only)")
    @app_commands.describe(name="New username for the bot")
    async def bot_name(self, interaction: discord.Interaction, name: str):
        if interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("❌ Owner only.", ephemeral=True)
        try:
            await self.bot.user.edit(username=name)
            await interaction.response.send_message(f"✅ Bot username changed to **{name}**.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.response.send_message(f"❌ Failed: {e} (Discord limits how often this can be changed)", ephemeral=True)

    @config_group.command(name="bot-avatar", description="Change the bot's avatar (owner only)")
    @app_commands.describe(url="Direct image URL for the new avatar")
    async def bot_avatar(self, interaction: discord.Interaction, url: str):
        if interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("❌ Owner only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as r:
                if r.status != 200:
                    return await interaction.followup.send("❌ Couldn't fetch that image.", ephemeral=True)
                img_bytes = await r.read()

        try:
            await self.bot.user.edit(avatar=img_bytes)
            await interaction.followup.send("✅ Bot avatar updated.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Failed: {e}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(BotConfig(bot))