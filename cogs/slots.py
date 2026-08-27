import discord
from discord import app_commands
from discord.ext import commands
import json, os

CONFIG_FILE = "data/slots.json"


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(d):
    os.makedirs("data", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(d, f, indent=2)


class Slots(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="createslot", description="Create a personal slot channel for a member")
    @app_commands.describe(member="Member to create the slot for", category="Category to put the slot channel in (optional)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def createslot(self, interaction: discord.Interaction, member: discord.Member, category: discord.CategoryChannel = None):
        guild = interaction.guild
        gid = str(guild.id)
        config = load_config()

        existing_id = config.get(gid, {}).get(str(member.id))
        if existing_id:
            existing = guild.get_channel(int(existing_id))
            if existing:
                return await interaction.response.send_message(f"❌ {member.mention} already has a slot: {existing.mention}", ephemeral=True)

        safe_name = "".join(c for c in member.name.lower() if c.isalnum() or c == "-").strip("-") or str(member.id)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        ch = await guild.create_text_channel(f"slot-{safe_name}", category=category, overwrites=overwrites, topic=f"Slot channel for {member}")

        config.setdefault(gid, {})[str(member.id)] = str(ch.id)
        save_config(config)

        await ch.send(f"🎟️ Welcome to your slot, {member.mention}! This is your dedicated channel to post here.")
        await interaction.response.send_message(f"✅ Created slot channel {ch.mention} for {member.mention}", ephemeral=True)

    @app_commands.command(name="revokeslot", description="Revoke a member's slot channel (removes their access)")
    @app_commands.describe(member="Member whose slot to revoke")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def revokeslot(self, interaction: discord.Interaction, member: discord.Member):
        config = load_config()
        gid = str(interaction.guild.id)
        ch_id = config.get(gid, {}).get(str(member.id))
        if not ch_id:
            return await interaction.response.send_message(f"❌ {member.mention} doesn't have a slot channel.", ephemeral=True)

        channel = interaction.guild.get_channel(int(ch_id))
        if channel:
            await channel.set_permissions(member, view_channel=False, send_messages=False)
        await interaction.response.send_message(f"✅ Revoked {member.mention}'s access to their slot.", ephemeral=True)

    @app_commands.command(name="unrevokeslot", description="Restore a member's revoked slot access")
    @app_commands.describe(member="Member whose slot to restore")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unrevokeslot(self, interaction: discord.Interaction, member: discord.Member):
        config = load_config()
        gid = str(interaction.guild.id)
        ch_id = config.get(gid, {}).get(str(member.id))
        if not ch_id:
            return await interaction.response.send_message(f"❌ {member.mention} doesn't have a slot channel.", ephemeral=True)

        channel = interaction.guild.get_channel(int(ch_id))
        if channel:
            await channel.set_permissions(member, view_channel=True, send_messages=True, embed_links=True, attach_files=True)
        await interaction.response.send_message(f"✅ Restored {member.mention}'s access to their slot.", ephemeral=True)

    @app_commands.command(name="deleteslot", description="Permanently delete a member's slot channel")
    @app_commands.describe(member="Member whose slot to delete")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def deleteslot(self, interaction: discord.Interaction, member: discord.Member):
        config = load_config()
        gid = str(interaction.guild.id)
        ch_id = config.get(gid, {}).pop(str(member.id), None)
        save_config(config)
        if not ch_id:
            return await interaction.response.send_message(f"❌ {member.mention} doesn't have a slot channel.", ephemeral=True)

        channel = interaction.guild.get_channel(int(ch_id))
        if channel:
            await channel.delete(reason=f"Slot deleted by {interaction.user}")
        await interaction.response.send_message(f"✅ Deleted {member.mention}'s slot channel.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Slots(bot))