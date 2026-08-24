import discord
from discord import app_commands
from discord.ext import commands
import json, os, datetime

NOTES_FILE = "data/customer_notes.json"


def load_notes():
    if not os.path.exists(NOTES_FILE):
        return {}
    with open(NOTES_FILE) as f:
        return json.load(f)


def save_notes(d):
    os.makedirs("data", exist_ok=True)
    with open(NOTES_FILE, "w") as f:
        json.dump(d, f, indent=2)


class Notes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    note_group = app_commands.Group(name="note", description="Manage private staff notes on a member")

    @note_group.command(name="add", description="Add a private staff note about a member")
    @app_commands.describe(member="The member this note is about", text="The note")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def add(self, interaction: discord.Interaction, member: discord.Member, text: str):
        notes = load_notes()
        gid, uid = str(interaction.guild.id), str(member.id)
        notes.setdefault(gid, {}).setdefault(uid, [])
        notes[gid][uid].append({
            "text": text,
            "by": str(interaction.user),
            "time": str(datetime.datetime.utcnow()),
        })
        save_notes(notes)
        await interaction.response.send_message(f"✅ Note added for {member.mention}.", ephemeral=True)

    @note_group.command(name="view", description="View all staff notes for a member")
    @app_commands.describe(member="The member to check")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def view(self, interaction: discord.Interaction, member: discord.Member):
        notes = load_notes().get(str(interaction.guild.id), {}).get(str(member.id), [])
        if not notes:
            return await interaction.response.send_message(f"No notes on file for {member.mention}.", ephemeral=True)

        lines = [f"**{i+1}.** {n['text']}\n> *by {n['by']} — {n['time'][:10]}*" for i, n in enumerate(notes)]
        e = discord.Embed(title=f"📝 Staff Notes — {member}", description="\n\n".join(lines), color=discord.Color.orange())
        e.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @note_group.command(name="remove", description="Remove a single note by its number (see /note view)")
    @app_commands.describe(member="The member", index="Note number to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction, member: discord.Member, index: int):
        notes = load_notes()
        gid, uid = str(interaction.guild.id), str(member.id)
        user_notes = notes.get(gid, {}).get(uid, [])
        if index < 1 or index > len(user_notes):
            return await interaction.response.send_message("❌ Invalid note number.", ephemeral=True)
        removed = user_notes.pop(index - 1)
        save_notes(notes)
        await interaction.response.send_message(f"✅ Removed note: *{removed['text']}*", ephemeral=True)

    @note_group.command(name="clear", description="Clear ALL notes for a member")
    @app_commands.describe(member="The member")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def clear(self, interaction: discord.Interaction, member: discord.Member):
        notes = load_notes()
        notes.get(str(interaction.guild.id), {}).pop(str(member.id), None)
        save_notes(notes)
        await interaction.response.send_message(f"✅ Cleared all notes for {member.mention}.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Notes(bot))