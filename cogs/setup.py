import discord
from discord import app_commands
from discord.ext import commands
import json, os

TICKET_CONFIG_FILE = "data/ticket_config.json"
WELCOME_CONFIG_FILE = "data/welcome_config.json"
AUTOMOD_CONFIG_FILE = "data/automod_config.json"


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs("data", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


class ChannelPicker(discord.ui.ChannelSelect):
    def __init__(self, placeholder, config_file, config_key, success_text):
        super().__init__(placeholder=placeholder, channel_types=[discord.ChannelType.text], min_values=1, max_values=1)
        self.config_file = config_file
        self.config_key = config_key
        self.success_text = success_text

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        config = load_json(self.config_file)
        config.setdefault(str(interaction.guild.id), {})[self.config_key] = str(channel.id)
        save_json(self.config_file, config)
        await interaction.response.edit_message(content=f"✅ {self.success_text.format(channel=channel.mention)}", view=None)


class RolePicker(discord.ui.RoleSelect):
    def __init__(self, placeholder, config_file, config_key, success_text):
        super().__init__(placeholder=placeholder, min_values=1, max_values=1)
        self.config_file = config_file
        self.config_key = config_key
        self.success_text = success_text

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        config = load_json(self.config_file)
        config.setdefault(str(interaction.guild.id), {})[self.config_key] = str(role.id)
        save_json(self.config_file, config)
        await interaction.response.edit_message(content=f"✅ {self.success_text.format(role=role.mention)}", view=None)


class PickerView(discord.ui.View):
    def __init__(self, picker):
        super().__init__(timeout=120)
        self.add_item(picker)


class SetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Ticket Channel", emoji="🎫", style=discord.ButtonStyle.primary, row=0)
    async def ticket_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        picker = ChannelPicker("Choose the ticket panel channel", TICKET_CONFIG_FILE, "_setup_ticket_channel", "Noted! Now run `/setuptickets channel:{channel}` to actually post the panel there.")
        await interaction.response.send_message("Pick a channel for your ticket panel:", view=PickerView(picker), ephemeral=True)

    @discord.ui.button(label="Support Role", emoji="🛠️", style=discord.ButtonStyle.primary, row=0)
    async def support_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        picker = RolePicker("Choose your support/staff role", TICKET_CONFIG_FILE, "support_role", "Support role set to {role} — they'll see every ticket.")
        await interaction.response.send_message("Pick your support role:", view=PickerView(picker), ephemeral=True)

    @discord.ui.button(label="Ticket Log Channel", emoji="📜", style=discord.ButtonStyle.primary, row=0)
    async def ticket_log(self, interaction: discord.Interaction, button: discord.ui.Button):
        picker = ChannelPicker("Choose the ticket transcript log channel", TICKET_CONFIG_FILE, "log_channel", "Ticket transcripts will now be logged to {channel}.")
        await interaction.response.send_message("Pick a channel for ticket transcripts:", view=PickerView(picker), ephemeral=True)

    @discord.ui.button(label="Welcome Channel", emoji="👋", style=discord.ButtonStyle.success, row=1)
    async def welcome_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        picker = ChannelPicker("Choose the welcome message channel", WELCOME_CONFIG_FILE, "welcome_channel", "Welcome messages will now post in {channel}.")
        await interaction.response.send_message("Pick your welcome channel:", view=PickerView(picker), ephemeral=True)

    @discord.ui.button(label="Leave Channel", emoji="🚪", style=discord.ButtonStyle.success, row=1)
    async def leave_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        picker = ChannelPicker("Choose the leave message channel", WELCOME_CONFIG_FILE, "leave_channel", "Leave messages will now post in {channel}.")
        await interaction.response.send_message("Pick your leave channel:", view=PickerView(picker), ephemeral=True)

    @discord.ui.button(label="Toggle AutoMod", emoji="🛡️", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_automod(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = load_json(AUTOMOD_CONFIG_FILE)
        gid = str(interaction.guild.id)
        config.setdefault(gid, {})
        config[gid]["enabled"] = not config[gid].get("enabled", False)
        save_json(AUTOMOD_CONFIG_FILE, config)
        state = "enabled ✅" if config[gid]["enabled"] else "disabled ❌"
        await interaction.response.send_message(
            f"🛡️ AutoMod is now **{state}**.\nFine-tune it further with `/automod addword`, `/automod toggleinvites`, etc.",
            ephemeral=True,
        )


class Setup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Interactive setup wizard for the bot's main features")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_cmd(self, interaction: discord.Interaction):
        e = discord.Embed(
            title="⚙️ Bot Setup Wizard",
            description=(
                "Tap a button below to configure that part of the bot. Each one lets you "
                "pick a channel or role right from a dropdown — no need to remember command syntax.\n\n"
                "🎫 **Ticket Channel** — where the ticket panel lives\n"
                "🛠️ **Support Role** — who can see every ticket\n"
                "📜 **Ticket Log Channel** — where closed-ticket transcripts get saved\n"
                "👋 **Welcome Channel** — where join messages post\n"
                "🚪 **Leave Channel** — where leave messages post\n"
                "🛡️ **Toggle AutoMod** — turn spam/link/word filtering on or off"
            ),
            color=discord.Color.blurple(),
        )
        e.set_footer(text="This only covers the basics — every feature has its own dedicated commands for deeper config too.")
        await interaction.response.send_message(embed=e, view=SetupView(), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Setup(bot))