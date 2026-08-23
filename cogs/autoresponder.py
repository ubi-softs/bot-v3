import discord
from discord import app_commands
from discord.ext import commands
import json, os

CONFIG_FILE = "data/autoresponder.json"


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(d):
    os.makedirs("data", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(d, f, indent=2)


def _gconf(gid: int) -> dict:
    return load_config().get(str(gid), {})


class AutoResponder(commands.Cog):
    """
    Two kinds of triggers:

      • public  — anyone can say the keyword, the bot replies in the channel
                  for everyone to see.

      • staff   — only members with Manage Messages (i.e. staff) trigger it,
                  and the reply is kept private to staff: it's sent either
                  to a dedicated staff-only channel (if one's been set with
                  /autoresponder staffchannel) or, if none is set, DMed
                  straight to the staff member who typed it.
    """

    def __init__(self, bot):
        self.bot = bot

    def _is_staff(self, member: discord.Member) -> bool:
        conf = _gconf(member.guild.id)
        staff_role_id = conf.get("staff_role")
        if staff_role_id:
            role = member.guild.get_role(int(staff_role_id))
            return role is not None and role in member.roles
        # Fallback if no staff role has been configured yet
        return member.guild_permissions.manage_messages

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        conf = _gconf(message.guild.id)
        if not conf.get("enabled", True):
            return

        triggers = conf.get("triggers", {})
        content_lower = message.content.lower()

        for keyword, data in triggers.items():
            if keyword.lower() not in content_lower:
                continue

            visibility = data.get("visibility", "public")
            response = data.get("response", "")

            if visibility == "staff":
                if not self._is_staff(message.author):
                    continue  # non-staff saying a staff-only keyword does nothing

                staff_channel_id = conf.get("staff_channel")
                target = None
                if staff_channel_id:
                    target = message.guild.get_channel(int(staff_channel_id))

                embed = discord.Embed(
                    title="🔒 Staff Auto-Response",
                    description=response,
                    color=discord.Color.blurple(),
                )
                embed.set_footer(text=f"Triggered by {message.author} in #{message.channel.name}")

                if target:
                    try:
                        await target.send(embed=embed)
                    except discord.Forbidden:
                        pass
                else:
                    try:
                        await message.author.send(embed=embed)
                    except discord.Forbidden:
                        pass
            else:
                try:
                    await message.channel.send(response)
                except discord.Forbidden:
                    pass

            break  # only fire the first matching trigger per message

    autoresponder_group = app_commands.Group(name="autoresponder", description="Manage keyword auto-responses")

    @autoresponder_group.command(name="add", description="Add a new auto-response trigger")
    @app_commands.describe(
        keyword="The word or phrase that triggers the response",
        response="What the bot should reply with",
        visibility="Who can trigger it and see the reply",
    )
    @app_commands.choices(
        visibility=[
            app_commands.Choice(name="Public — anyone can trigger, reply shown to everyone", value="public"),
            app_commands.Choice(name="Staff only — only staff can trigger, reply only visible to staff", value="staff"),
        ]
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def add(self, interaction: discord.Interaction, keyword: str, response: str, visibility: app_commands.Choice[str]):
        config = load_config()
        gid = str(interaction.guild.id)
        config.setdefault(gid, {}).setdefault("triggers", {})[keyword.lower()] = {
            "response": response,
            "visibility": visibility.value,
        }
        config[gid].setdefault("enabled", True)
        save_config(config)

        note = ""
        if visibility.value == "staff" and not config[gid].get("staff_channel"):
            note = "\n💡 No staff channel is set, so staff replies will be DMed to whoever triggers it. Use `/autoresponder staffchannel` to send them to a channel instead."

        await interaction.response.send_message(
            f"✅ Added trigger `{keyword}` ({visibility.name}).{note}", ephemeral=True
        )

    @autoresponder_group.command(name="remove", description="Remove an auto-response trigger")
    @app_commands.describe(keyword="The keyword to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction, keyword: str):
        config = load_config()
        gid = str(interaction.guild.id)
        removed = config.get(gid, {}).get("triggers", {}).pop(keyword.lower(), None)
        save_config(config)
        if removed:
            await interaction.response.send_message(f"✅ Removed trigger `{keyword}`.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ No trigger found with that keyword.", ephemeral=True)

    @autoresponder_group.command(name="list", description="View all configured auto-response triggers")
    async def list_triggers(self, interaction: discord.Interaction):
        triggers = _gconf(interaction.guild.id).get("triggers", {})
        if not triggers:
            return await interaction.response.send_message("No auto-responder triggers configured yet.", ephemeral=True)
        lines = []
        for kw, data in triggers.items():
            tag = "🌐 Public" if data.get("visibility") == "public" else "🔒 Staff only"
            lines.append(f"**`{kw}`** — {tag}\n> {data.get('response','')[:100]}")
        e = discord.Embed(title="💬 Auto-Responder Triggers", description="\n\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=e, ephemeral=True)

    @autoresponder_group.command(name="staffchannel", description="Set the channel where staff-only auto-responses get sent")
    @app_commands.describe(channel="Channel for staff-only replies (leave blank to go back to DMs)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def staffchannel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        config = load_config()
        gid = str(interaction.guild.id)
        config.setdefault(gid, {})
        if channel:
            config[gid]["staff_channel"] = str(channel.id)
            save_config(config)
            await interaction.response.send_message(f"✅ Staff-only auto-responses will now be sent to {channel.mention}.", ephemeral=True)
        else:
            config[gid].pop("staff_channel", None)
            save_config(config)
            await interaction.response.send_message("✅ Staff-only auto-responses will now be DMed to whoever triggers them.", ephemeral=True)

    @autoresponder_group.command(name="role", description="Set which role counts as 'staff' for staff-only triggers")
    @app_commands.describe(role="The staff role (members with this role can trigger and see staff-only replies)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autoresponderrole(self, interaction: discord.Interaction, role: discord.Role):
        config = load_config()
        gid = str(interaction.guild.id)
        config.setdefault(gid, {})["staff_role"] = str(role.id)
        save_config(config)
        await interaction.response.send_message(
            f"✅ {role.mention} is now the staff role — only members with this role can trigger staff-only auto-responses.",
            ephemeral=True,
        )

    @autoresponder_group.command(name="toggle", description="Enable or disable the auto-responder entirely")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def toggle(self, interaction: discord.Interaction):
        config = load_config()
        gid = str(interaction.guild.id)
        config.setdefault(gid, {})
        config[gid]["enabled"] = not config[gid].get("enabled", True)
        save_config(config)
        await interaction.response.send_message(f"✅ Auto-responder is now **{'enabled' if config[gid]['enabled'] else 'disabled'}**.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(AutoResponder(bot))