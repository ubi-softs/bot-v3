import discord
from discord import app_commands
from discord.ext import commands
import json, os, datetime

CONFIG_FILE = "data/server_tools.json"


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(d):
    os.makedirs("data", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(d, f, indent=2)


class LegitVoteView(discord.ui.View):
    def __init__(self, message_id: int = None):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="Vote Legit", emoji="✅", style=discord.ButtonStyle.success, custom_id="legit_vote")
    async def vote(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = load_config()
        gid = str(interaction.guild.id)
        mid = str(interaction.message.id)
        votes = config.setdefault(gid, {}).setdefault("legit_votes", {}).setdefault(mid, [])
        uid = str(interaction.user.id)
        if uid in votes:
            return await interaction.response.send_message("❌ You've already voted.", ephemeral=True)
        votes.append(uid)
        save_config(config)

        e = interaction.message.embeds[0]
        e.description = f"✅ **{len(votes)}** members have voted this server is legit!\n\nTap the button below to add your vote."
        await interaction.response.edit_message(embed=e)


class ServerTools(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_deleted = {}  # channel_id -> {"author": str, "content": str, "time": datetime}
        bot.add_view(LegitVoteView())

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot:
            return
        self.last_deleted[message.channel.id] = {
            "author": str(message.author),
            "avatar": message.author.display_avatar.url,
            "content": message.content or "*[no text content — embed/attachment]*",
            "time": datetime.datetime.utcnow(),
        }

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Ping-spam protection: if someone mass-mentions a protected member, time out the sender
        config = load_config()
        gid = str(message.guild.id)
        protected = config.get(gid, {}).get("ping_protected", [])
        if protected and len(message.mentions) >= 3:
            if any(str(m.id) in protected for m in message.mentions):
                if not message.author.guild_permissions.moderate_members:
                    try:
                        from datetime import timedelta
                        await message.author.timeout(discord.utils.utcnow() + timedelta(minutes=10), reason="Ping-spamming a protected member")
                        await message.channel.send(f"⏱️ {message.author.mention} was timed out for mass-mentioning a protected member.")
                    except discord.HTTPException:
                        pass

        # Sticky message re-post
        sticky = config.get(gid, {}).get("sticky", {}).get(str(message.channel.id))
        if sticky:
            try:
                old = await message.channel.fetch_message(int(sticky["message_id"]))
                await old.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
            e = discord.Embed.from_dict(sticky["embed"])
            new_msg = await message.channel.send(embed=e)
            config[gid]["sticky"][str(message.channel.id)]["message_id"] = str(new_msg.id)
            save_config(config)

    # ── /nuke ─────────────────────────────────────────────────
    @app_commands.command(name="nuke", description="Instantly clear a channel by cloning it and deleting the original")
    @app_commands.describe(channel="Channel to nuke (defaults to current)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def nuke(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        ch = channel or interaction.channel
        await interaction.response.send_message(f"💣 Nuking {ch.mention} in 3 seconds...", ephemeral=True)
        position = ch.position
        new_channel = await ch.clone(reason=f"Nuked by {interaction.user}")
        await new_channel.edit(position=position)
        await ch.delete(reason=f"Nuked by {interaction.user}")
        await new_channel.send("💥 **Channel nuked!**")

    # ── /rules ────────────────────────────────────────────────
    @app_commands.command(name="rules", description="Post a rules embed in this channel")
    @app_commands.describe(title="Rules embed title", rules="Your rules, use \\n between each one")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rules(self, interaction: discord.Interaction, title: str = "📜 Server Rules", rules: str = "1. Be respectful\n2. No spam\n3. Follow Discord ToS"):
        e = discord.Embed(title=title, description=rules.replace("\\n", "\n"), color=discord.Color.blurple())
        await interaction.channel.send(embed=e)
        await interaction.response.send_message("✅ Rules posted.", ephemeral=True)

    # ── /stick ────────────────────────────────────────────────
    stick_group = app_commands.Group(name="stick", description="Keep an embed pinned to the bottom of a channel")

    @stick_group.command(name="set", description="Make a message sticky (stays at the bottom of the channel)")
    @app_commands.describe(title="Sticky message title", content="Sticky message content")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def stick_set(self, interaction: discord.Interaction, title: str, content: str):
        e = discord.Embed(title=title, description=content.replace("\\n", "\n"), color=discord.Color.gold())
        msg = await interaction.channel.send(embed=e)

        config = load_config()
        gid = str(interaction.guild.id)
        config.setdefault(gid, {}).setdefault("sticky", {})[str(interaction.channel.id)] = {
            "message_id": str(msg.id),
            "embed": e.to_dict(),
        }
        save_config(config)
        await interaction.response.send_message("✅ Sticky message set for this channel.", ephemeral=True)

    @stick_group.command(name="remove", description="Remove the sticky message from this channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def stick_remove(self, interaction: discord.Interaction):
        config = load_config()
        gid = str(interaction.guild.id)
        removed = config.get(gid, {}).get("sticky", {}).pop(str(interaction.channel.id), None)
        save_config(config)
        if removed:
            await interaction.response.send_message("✅ Sticky message removed.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ No sticky message set in this channel.", ephemeral=True)

    # ── /legit ────────────────────────────────────────────────
    @app_commands.command(name="legit", description="Post a vote embed where members can vote the server is legit")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def legit(self, interaction: discord.Interaction):
        e = discord.Embed(
            title="✅ Is this server legit?",
            description="✅ **0** members have voted this server is legit!\n\nTap the button below to add your vote.",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=e, view=LegitVoteView())

    # ── /pingspamprotect ──────────────────────────────────────
    @app_commands.command(name="pingspamprotect", description="Toggle ping-spam protection for a member (auto-timeout if they mass-mention)")
    @app_commands.describe(member="Member to protect against ping-spamming")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def pingspamprotect(self, interaction: discord.Interaction, member: discord.Member):
        config = load_config()
        gid = str(interaction.guild.id)
        protected = config.setdefault(gid, {}).setdefault("ping_protected", [])
        uid = str(member.id)
        if uid in protected:
            protected.remove(uid)
            msg = f"✅ Ping-spam protection **disabled** for {member.mention}."
        else:
            protected.append(uid)
            msg = f"✅ Ping-spam protection **enabled** for {member.mention} — anyone who mass-mentions them will be timed out."
        save_config(config)
        await interaction.response.send_message(msg, ephemeral=True)

    # ── /status ───────────────────────────────────────────────
    status_group = app_commands.Group(name="status", description="Set or view a custom status note for a member")

    @status_group.command(name="set", description="Set a custom status note for a member")
    @app_commands.describe(member="Member", text="Status text")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def status_set(self, interaction: discord.Interaction, member: discord.Member, text: str):
        config = load_config()
        gid = str(interaction.guild.id)
        config.setdefault(gid, {}).setdefault("statuses", {})[str(member.id)] = text
        save_config(config)
        await interaction.response.send_message(f"✅ Set status for {member.mention}: *{text}*", ephemeral=True)

    @status_group.command(name="view", description="View a member's custom status note")
    @app_commands.describe(member="Member to check")
    async def status_view(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        status = load_config().get(str(interaction.guild.id), {}).get("statuses", {}).get(str(member.id))
        if not status:
            return await interaction.response.send_message(f"{member.mention} has no custom status set.", ephemeral=True)
        await interaction.response.send_message(f"**{member.display_name}'s status:** {status}")

    # ── /snipe ────────────────────────────────────────────────
    @app_commands.command(name="snipe", description="Show the last deleted message in this channel")
    async def snipe(self, interaction: discord.Interaction):
        data = self.last_deleted.get(interaction.channel.id)
        if not data:
            return await interaction.response.send_message("Nothing to snipe — no recently deleted messages here.", ephemeral=True)
        e = discord.Embed(description=data["content"], color=discord.Color.orange(), timestamp=data["time"])
        e.set_author(name=data["author"], icon_url=data["avatar"])
        e.set_footer(text="Deleted message")
        await interaction.response.send_message(embed=e)


async def setup(bot):
    await bot.add_cog(ServerTools(bot))