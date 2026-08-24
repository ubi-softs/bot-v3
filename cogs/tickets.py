import discord
from discord import app_commands
from discord.ext import commands, tasks
import json, os, datetime, asyncio, io

TICKETS_FILE = "data/tickets.json"
CONFIG_FILE = "data/ticket_config.json"


def load_tickets():
    if not os.path.exists(TICKETS_FILE):
        return {}
    with open(TICKETS_FILE) as f:
        return json.load(f)


def save_tickets(d):
    os.makedirs("data", exist_ok=True)
    with open(TICKETS_FILE, "w") as f:
        json.dump(d, f, indent=2)


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(d):
    os.makedirs("data", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(d, f, indent=2)


async def build_transcript(channel: discord.TextChannel) -> discord.File:
    """Fetch the ticket's message history and turn it into a downloadable .txt transcript."""
    lines = []
    async for msg in channel.history(limit=1000, oldest_first=True):
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
        content = msg.content or "[embed/attachment]"
        lines.append(f"[{ts}] {msg.author}: {content}")
    text = "\n".join(lines) if lines else "(no messages)"
    buffer = io.BytesIO(text.encode("utf-8"))
    return discord.File(buffer, filename=f"transcript-{channel.name}.txt")


async def log_ticket_close(bot: commands.Bot, guild: discord.Guild, channel: discord.TextChannel, opener_id: str, ticket_type: str, closed_by: str):
    """Post a transcript + summary to the configured ticket log channel, if one is set."""
    config = load_config()
    log_channel_id = config.get(str(guild.id), {}).get("log_channel")
    if not log_channel_id:
        return
    log_channel = guild.get_channel(int(log_channel_id))
    if not log_channel:
        return

    try:
        file = await build_transcript(channel)
    except discord.HTTPException:
        return

    opener = guild.get_member(int(opener_id)) if opener_id else None
    e = discord.Embed(title="🎫 Ticket Closed", color=discord.Color.dark_grey(), timestamp=datetime.datetime.utcnow())
    e.add_field(name="Opened By", value=opener.mention if opener else f"User ID: {opener_id}", inline=True)
    e.add_field(name="Type", value=ticket_type, inline=True)
    e.add_field(name="Closed By", value=closed_by, inline=True)
    e.set_footer(text=f"Channel: #{channel.name}")

    try:
        await log_channel.send(embed=e, file=file)
    except discord.Forbidden:
        pass


# ── Ticket Panel View (the 5 buttons users click to open a ticket) ────────────
class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _open_ticket(self, interaction: discord.Interaction, category_name: str, emoji: str):
        guild = interaction.guild
        member = interaction.user
        config = load_config()
        gid = str(guild.id)
        tickets = load_tickets()

        safe_name = "".join(c for c in member.name.lower() if c.isalnum() or c == "-").strip("-") or str(member.id)
        existing = discord.utils.get(guild.text_channels, name=f"ticket-{safe_name}")
        if existing:
            return await interaction.response.send_message(
                f"❌ You already have an open ticket: {existing.mention}", ephemeral=True
            )

        cat_name = config.get(gid, {}).get("ticket_category", "Tickets")
        cat = discord.utils.get(guild.categories, name=cat_name)
        if not cat:
            cat = await guild.create_category(cat_name)

        support_role_id = config.get(gid, {}).get("support_role")
        support_role = guild.get_role(int(support_role_id)) if support_role_id else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        ch = await guild.create_text_channel(
            f"ticket-{safe_name}",
            category=cat,
            overwrites=overwrites,
            topic=f"Ticket by {member} | Type: {category_name}",
        )

        tickets.setdefault(gid, {})[str(ch.id)] = {
            "user_id": str(member.id),
            "type": category_name,
            "opened": str(datetime.datetime.utcnow()),
            "closed": False,
            "warned": False,
        }
        save_tickets(tickets)

        e = discord.Embed(
            title=f"{emoji} {category_name} Ticket",
            description=(
                f"Welcome {member.mention}!\n\n"
                f"**Ticket type:** {category_name}\n"
                f"A staff member will be with you shortly.\n\n"
                f"Click 🔒 **Close** to close this ticket when done."
            ),
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.utcnow(),
        )
        e.set_footer(text=f"Ticket ID: {ch.id}")
        await ch.send(
            content=f"{member.mention}" + (f" | {support_role.mention}" if support_role else ""),
            embed=e,
            view=TicketControlView(),
        )
        await interaction.response.send_message(f"✅ Ticket created: {ch.mention}", ephemeral=True)

    @discord.ui.button(label="Speak to Owner", emoji="👑", style=discord.ButtonStyle.danger, custom_id="ticket_owner")
    async def owner(self, interaction, button):
        await self._open_ticket(interaction, "Speak to Owner", "👑")

    @discord.ui.button(label="Support", emoji="🛠️", style=discord.ButtonStyle.primary, custom_id="ticket_support")
    async def support(self, interaction, button):
        await self._open_ticket(interaction, "Support", "🛠️")

    @discord.ui.button(label="Purchase", emoji="💰", style=discord.ButtonStyle.success, custom_id="ticket_purchase")
    async def purchase(self, interaction, button):
        await self._open_ticket(interaction, "Purchase", "💰")

    @discord.ui.button(label="Website Purchased", emoji="🌐", style=discord.ButtonStyle.secondary, custom_id="ticket_website")
    async def website(self, interaction, button):
        await self._open_ticket(interaction, "Website Purchased", "🌐")

    @discord.ui.button(label="Problem with Purchase", emoji="⚠️", style=discord.ButtonStyle.danger, custom_id="ticket_problem")
    async def problem(self, interaction, button):
        await self._open_ticket(interaction, "Problem with Purchase", "⚠️")


# ── Ticket Control View (inside an open ticket) ───────────────────────────────
class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = discord.Embed(title="🔒 Close Ticket", description="Are you sure you want to close this ticket?", color=discord.Color.red())
        await interaction.response.send_message(embed=e, view=TicketCloseConfirmView(), ephemeral=False)

    @discord.ui.button(label="Claim Ticket", emoji="🙋", style=discord.ButtonStyle.primary, custom_id="ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        topic = interaction.channel.topic or ""
        await interaction.channel.edit(topic=f"{topic} | Claimed by {interaction.user}")
        await interaction.response.send_message(f"✅ {interaction.user.mention} claimed this ticket.")
        button.disabled = True
        await interaction.message.edit(view=self)

    @discord.ui.button(label="Add User", emoji="➕", style=discord.ButtonStyle.secondary, custom_id="ticket_add")
    async def add_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Mention the user to add:", ephemeral=True)

        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel

        try:
            msg = await interaction.client.wait_for("message", check=check, timeout=30)
            if msg.mentions:
                user = msg.mentions[0]
                await interaction.channel.set_permissions(user, view_channel=True, send_messages=True)
                await interaction.channel.send(f"✅ Added {user.mention} to this ticket.")
                await msg.delete()
        except asyncio.TimeoutError:
            pass


class TicketCloseConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Yes, Close", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        tickets = load_tickets()
        gid = str(interaction.guild.id)
        cid = str(interaction.channel.id)
        entry = tickets.get(gid, {}).get(cid, {})

        # Log the transcript BEFORE the channel is deleted
        await log_ticket_close(
            interaction.client, interaction.guild, interaction.channel,
            entry.get("user_id", ""), entry.get("type", "Unknown"), str(interaction.user),
        )

        if gid in tickets and cid in tickets[gid]:
            tickets[gid][cid]["closed"] = True
            save_tickets(tickets)

        await interaction.response.send_message("🔒 Closing ticket in 5 seconds...")
        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Cancelled.", ephemeral=True)
        self.stop()


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(TicketPanelView())
        bot.add_view(TicketControlView())
        self.autoclose_loop.start()

    def cog_unload(self):
        self.autoclose_loop.cancel()

    # ── /setuptickets — asks which channel, then posts the 5-option panel ─────
    @app_commands.command(name="setuptickets", description="Set up the ticket panel in a channel")
    @app_commands.describe(channel="Channel to post the ticket panel in")
    @app_commands.checks.has_permissions(administrator=True)
    async def setuptickets(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        e = discord.Embed(
            title="🎫 Support Tickets",
            description=(
                "Need help? Open a ticket below and our team will assist you.\n\n"
                "👑 **Speak to Owner** — Direct message to the owner\n"
                "🛠️ **Support** — General help & questions\n"
                "💰 **Purchase** — Want to buy something?\n"
                "🌐 **Website Purchased** — Bought from our website\n"
                "⚠️ **Problem with Purchase** — Issue with an order\n\n"
                "*Select a category below to open your ticket.*"
            ),
            color=discord.Color.blurple(),
        )
        e.set_footer(text="One ticket per user • Staff will respond shortly")
        await channel.send(embed=e, view=TicketPanelView())
        await interaction.followup.send(f"✅ Ticket panel sent to {channel.mention}!", ephemeral=True)

    @app_commands.command(name="ticketsupport", description="Set the support role for tickets")
    @app_commands.describe(role="Role that can see all tickets")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticketsupport(self, interaction: discord.Interaction, role: discord.Role):
        config = load_config()
        config.setdefault(str(interaction.guild.id), {})["support_role"] = str(role.id)
        save_config(config)
        await interaction.response.send_message(f"✅ Support role set to {role.mention}", ephemeral=True)

    @app_commands.command(name="ticketcategory", description="Set the category name for ticket channels")
    @app_commands.describe(name="Category name")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticketcategory(self, interaction: discord.Interaction, name: str):
        config = load_config()
        config.setdefault(str(interaction.guild.id), {})["ticket_category"] = name
        save_config(config)
        await interaction.response.send_message(f"✅ Ticket category set to **{name}**", ephemeral=True)

    # ── /setticketlog — where transcripts get posted on close ─────────────────
    @app_commands.command(name="setticketlog", description="Set the channel where ticket transcripts are logged when closed")
    @app_commands.describe(channel="Channel to log closed ticket transcripts to")
    @app_commands.checks.has_permissions(administrator=True)
    async def setticketlog(self, interaction: discord.Interaction, channel: discord.TextChannel):
        config = load_config()
        config.setdefault(str(interaction.guild.id), {})["log_channel"] = str(channel.id)
        save_config(config)
        await interaction.response.send_message(f"✅ Ticket transcripts will be logged to {channel.mention}", ephemeral=True)

    @app_commands.command(name="claim", description="Claim the current ticket")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def claim(self, interaction: discord.Interaction):
        topic = interaction.channel.topic or ""
        await interaction.channel.edit(topic=f"{topic} | Claimed by {interaction.user}")
        await interaction.response.send_message(f"✅ {interaction.user.mention} has claimed this ticket.")

    @app_commands.command(name="ticketlist", description="List all open tickets")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticketlist(self, interaction: discord.Interaction):
        tickets = load_tickets()
        gid = str(interaction.guild.id)
        open_tickets = {cid: t for cid, t in tickets.get(gid, {}).items() if not t.get("closed")}
        if not open_tickets:
            return await interaction.response.send_message("✅ No open tickets.", ephemeral=True)
        lines = []
        for cid, t in open_tickets.items():
            ch = interaction.guild.get_channel(int(cid))
            ch_str = ch.mention if ch else f"#{cid}"
            uid = t.get("user_id", "?")
            user = interaction.guild.get_member(int(uid))
            lines.append(f"{ch_str} — **{t.get('type','?')}** | {user.mention if user else uid}")
        e = discord.Embed(title=f"🎫 Open Tickets ({len(open_tickets)})", description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="ticketpurge", description="Delete ALL ticket channels (Owner only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticketpurge(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        deleted = 0
        for ch in interaction.guild.text_channels:
            if ch.name.startswith("ticket-"):
                try:
                    await ch.delete(reason="Ticket purge")
                    deleted += 1
                except Exception:
                    pass
        tickets = load_tickets()
        tickets.pop(str(interaction.guild.id), None)
        save_tickets(tickets)
        await interaction.followup.send(f"🗑️ Purged **{deleted}** ticket channels.", ephemeral=True)

    # ── Auto-close configuration ───────────────────────────────────────────────
    autoclose_group = app_commands.Group(name="ticketautoclose", description="Configure automatic closing of inactive tickets")

    @autoclose_group.command(name="enable", description="Enable auto-closing of inactive tickets")
    @app_commands.checks.has_permissions(administrator=True)
    async def ac_enable(self, interaction: discord.Interaction):
        config = load_config()
        config.setdefault(str(interaction.guild.id), {})["autoclose_enabled"] = True
        save_config(config)
        await interaction.response.send_message("✅ Ticket auto-close enabled.", ephemeral=True)

    @autoclose_group.command(name="disable", description="Disable auto-closing of inactive tickets")
    @app_commands.checks.has_permissions(administrator=True)
    async def ac_disable(self, interaction: discord.Interaction):
        config = load_config()
        config.setdefault(str(interaction.guild.id), {})["autoclose_enabled"] = False
        save_config(config)
        await interaction.response.send_message("✅ Ticket auto-close disabled.", ephemeral=True)

    @autoclose_group.command(name="setwarn", description="Set how many hours of inactivity before a warning is sent")
    @app_commands.describe(hours="Hours of inactivity before warning")
    @app_commands.checks.has_permissions(administrator=True)
    async def ac_setwarn(self, interaction: discord.Interaction, hours: app_commands.Range[int, 1, 720]):
        config = load_config()
        config.setdefault(str(interaction.guild.id), {})["autoclose_warn_hours"] = hours
        save_config(config)
        await interaction.response.send_message(f"✅ Tickets will get a warning after **{hours}h** of inactivity.", ephemeral=True)

    @autoclose_group.command(name="setclose", description="Set how many hours of inactivity before a ticket auto-closes")
    @app_commands.describe(hours="Hours of inactivity before auto-close")
    @app_commands.checks.has_permissions(administrator=True)
    async def ac_setclose(self, interaction: discord.Interaction, hours: app_commands.Range[int, 1, 720]):
        config = load_config()
        config.setdefault(str(interaction.guild.id), {})["autoclose_close_hours"] = hours
        save_config(config)
        await interaction.response.send_message(f"✅ Tickets will auto-close after **{hours}h** of inactivity.", ephemeral=True)

    @autoclose_group.command(name="settings", description="View current auto-close settings")
    async def ac_settings(self, interaction: discord.Interaction):
        conf = load_config().get(str(interaction.guild.id), {})
        e = discord.Embed(title="⏳ Ticket Auto-Close Settings", color=discord.Color.blurple())
        e.add_field(name="Enabled", value=str(conf.get("autoclose_enabled", False)), inline=True)
        e.add_field(name="Warn After", value=f"{conf.get('autoclose_warn_hours', 24)}h", inline=True)
        e.add_field(name="Close After", value=f"{conf.get('autoclose_close_hours', 48)}h", inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── Background task: checks every 30 minutes for inactive tickets ─────────
    @tasks.loop(minutes=30)
    async def autoclose_loop(self):
        all_tickets = load_tickets()
        all_config = load_config()

        for gid, guild_tickets in list(all_tickets.items()):
            gconf = all_config.get(gid, {})
            if not gconf.get("autoclose_enabled"):
                continue

            guild = self.bot.get_guild(int(gid))
            if not guild:
                continue

            warn_hours = gconf.get("autoclose_warn_hours", 24)
            close_hours = gconf.get("autoclose_close_hours", 48)
            now = datetime.datetime.utcnow()

            for cid, entry in list(guild_tickets.items()):
                if entry.get("closed"):
                    continue
                channel = guild.get_channel(int(cid))
                if not channel:
                    continue

                # Find the last message time in the channel
                last_time = None
                try:
                    async for msg in channel.history(limit=1):
                        last_time = msg.created_at.replace(tzinfo=None)
                except discord.HTTPException:
                    continue
                if last_time is None:
                    try:
                        last_time = datetime.datetime.fromisoformat(entry.get("opened"))
                    except (ValueError, TypeError):
                        continue

                inactive_hours = (now - last_time).total_seconds() / 3600

                if inactive_hours >= close_hours:
                    await log_ticket_close(self.bot, guild, channel, entry.get("user_id", ""), entry.get("type", "Unknown"), "Auto-close (inactivity)")
                    entry["closed"] = True
                    save_tickets(all_tickets)
                    try:
                        await channel.delete(reason="Auto-closed due to inactivity")
                    except discord.HTTPException:
                        pass
                elif inactive_hours >= warn_hours and not entry.get("warned"):
                    try:
                        opener = guild.get_member(int(entry.get("user_id", 0)))
                        mention = opener.mention if opener else ""
                        remaining = round(close_hours - inactive_hours, 1)
                        await channel.send(
                            f"⏳ {mention} This ticket has been inactive for a while and will "
                            f"auto-close in about **{remaining}h** if there's no more activity."
                        )
                    except discord.HTTPException:
                        pass
                    entry["warned"] = True
                    save_tickets(all_tickets)

    @autoclose_loop.before_loop
    async def before_autoclose_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Tickets(bot))