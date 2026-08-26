import discord
from discord import app_commands
from discord.ext import commands
import json, os, datetime

CONFIG_FILE = "data/welcome_config.json"


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(d):
    os.makedirs("data", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(d, f, indent=2)


class WelcomeButtonsView(discord.ui.View):
    """Plain link buttons — no callback needed, Discord opens the URL client-side."""

    def __init__(self, rules_url: str = None, buy_url: str = None):
        super().__init__(timeout=None)
        if rules_url:
            self.add_item(discord.ui.Button(label="Rules", emoji="📜", style=discord.ButtonStyle.link, url=rules_url))
        if buy_url:
            self.add_item(discord.ui.Button(label="Buy Now", emoji="🛍️", style=discord.ButtonStyle.link, url=buy_url))


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        config = load_config()
        gid = str(member.guild.id)
        g_config = config.get(gid, {})

        ch_id = g_config.get("welcome_channel")
        if ch_id:
            ch = member.guild.get_channel(int(ch_id))
            if ch:
                msg = g_config.get("welcome_message", "Welcome {user} to **{server}**!")
                msg = msg.replace("{user}", member.mention).replace("{server}", member.guild.name).replace("{count}", str(member.guild.member_count))
                color = int(g_config.get("welcome_color", "0x57F287").replace("0x", ""), 16)

                e = discord.Embed(description=msg, color=color, timestamp=datetime.datetime.utcnow())
                e.set_author(name=member.display_name, icon_url=member.display_avatar.url)
                e.set_footer(text=f"ID: {member.id}")

                image_url = g_config.get("welcome_image")
                if image_url:
                    e.set_image(url=image_url)

                # Build link buttons: Rules → your rules/TOS channel, Buy Now → your shop link
                rules_url = None
                rules_channel_id = g_config.get("rules_channel")
                if rules_channel_id:
                    rules_url = f"https://discord.com/channels/{member.guild.id}/{rules_channel_id}"
                buy_url = g_config.get("buy_link")

                view = WelcomeButtonsView(rules_url=rules_url, buy_url=buy_url) if (rules_url or buy_url) else None

                await ch.send(embed=e, view=view)

        auto_role_id = g_config.get("auto_role")
        if auto_role_id:
            role = member.guild.get_role(int(auto_role_id))
            if role:
                try:
                    await member.add_roles(role, reason="Auto-role on join")
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        config = load_config()
        gid = str(member.guild.id)
        g_config = config.get(gid, {})

        ch_id = g_config.get("leave_channel")
        if ch_id:
            ch = member.guild.get_channel(int(ch_id))
            if ch:
                msg = g_config.get("leave_message", "**{user}** has left the server. We now have {count} members.")
                msg = msg.replace("{user}", str(member)).replace("{server}", member.guild.name).replace("{count}", str(member.guild.member_count))
                color = int(g_config.get("leave_color", "0xED4245").replace("0x", ""), 16)
                e = discord.Embed(description=msg, color=color, timestamp=datetime.datetime.utcnow())
                e.set_author(name=str(member), icon_url=member.display_avatar.url)
                await ch.send(embed=e)

    @app_commands.command(name="setwelchannel", description="Set the welcome message channel")
    @app_commands.describe(channel="Channel for welcome messages")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setwelchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        config = load_config()
        config.setdefault(str(interaction.guild.id), {})["welcome_channel"] = str(channel.id)
        save_config(config)
        await interaction.response.send_message(f"✅ Welcome channel set to {channel.mention}", ephemeral=True)

    @app_commands.command(name="setwelcome", description="Customize the welcome embed message")
    @app_commands.describe(message="Use {user}, {server}, {count} as placeholders")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setwelcome(self, interaction: discord.Interaction, message: str):
        config = load_config()
        config.setdefault(str(interaction.guild.id), {})["welcome_message"] = message
        save_config(config)
        await interaction.response.send_message("✅ Welcome message updated.", ephemeral=True)

    @app_commands.command(name="setwelcomeimage", description="Set the banner image shown on the welcome embed")
    @app_commands.describe(image_url="Direct image URL (leave blank to remove the banner)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setwelcomeimage(self, interaction: discord.Interaction, image_url: str = None):
        config = load_config()
        gid = str(interaction.guild.id)
        config.setdefault(gid, {})
        if image_url:
            config[gid]["welcome_image"] = image_url
            await interaction.response.send_message("✅ Welcome banner image set.", ephemeral=True)
        else:
            config[gid].pop("welcome_image", None)
            await interaction.response.send_message("✅ Welcome banner image removed.", ephemeral=True)
        save_config(config)

    @app_commands.command(name="setwelcomerules", description="Set which channel the Rules button on the welcome message links to")
    @app_commands.describe(channel="Your rules/TOS channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setwelcomerules(self, interaction: discord.Interaction, channel: discord.TextChannel):
        config = load_config()
        config.setdefault(str(interaction.guild.id), {})["rules_channel"] = str(channel.id)
        save_config(config)
        await interaction.response.send_message(f"✅ The Rules button will now link to {channel.mention}", ephemeral=True)

    @app_commands.command(name="setwelcomebuylink", description="Set the URL the Buy Now button on the welcome message opens")
    @app_commands.describe(url="Your shop link (leave blank to remove the button)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setwelcomebuylink(self, interaction: discord.Interaction, url: str = None):
        config = load_config()
        gid = str(interaction.guild.id)
        config.setdefault(gid, {})
        if url:
            config[gid]["buy_link"] = url
            await interaction.response.send_message(f"✅ The Buy Now button will now open {url}", ephemeral=True)
        else:
            config[gid].pop("buy_link", None)
            await interaction.response.send_message("✅ Buy Now button removed.", ephemeral=True)
        save_config(config)

    @app_commands.command(name="testwelcome", description="Preview the welcome message as it would appear for you")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def testwelcome(self, interaction: discord.Interaction):
        await self.on_member_join(interaction.user)
        await interaction.response.send_message("✅ Sent a preview to your welcome channel.", ephemeral=True)

    @app_commands.command(name="setleavechannel", description="Set the leave message channel")
    @app_commands.describe(channel="Channel for leave messages")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setleavechannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        config = load_config()
        config.setdefault(str(interaction.guild.id), {})["leave_channel"] = str(channel.id)
        save_config(config)
        await interaction.response.send_message(f"✅ Leave channel set to {channel.mention}", ephemeral=True)

    @app_commands.command(name="setleave", description="Customize the leave embed message")
    @app_commands.describe(message="Use {user}, {server}, {count} as placeholders")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setleave(self, interaction: discord.Interaction, message: str):
        config = load_config()
        config.setdefault(str(interaction.guild.id), {})["leave_message"] = message
        save_config(config)
        await interaction.response.send_message("✅ Leave message updated.", ephemeral=True)

    @app_commands.command(name="autorole", description="Set a role to be given to new members automatically")
    @app_commands.describe(role="Role to assign on join (leave blank to disable)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autorole(self, interaction: discord.Interaction, role: discord.Role = None):
        config = load_config()
        gid = str(interaction.guild.id)
        if role:
            config.setdefault(gid, {})["auto_role"] = str(role.id)
            msg = f"✅ Auto-role set to {role.mention}"
        else:
            config.get(gid, {}).pop("auto_role", None)
            msg = "✅ Auto-role disabled."
        save_config(config)
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Welcome(bot))