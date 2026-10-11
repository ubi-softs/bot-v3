"""
massdm.py — mass-DM cog (admin only, server only)

/dm all    message [exclude]   DM every human member of the server.
                               `exclude` = @mentions and/or raw user IDs to skip.
/dm users  targets message     DM specific people: @mention members, or paste raw
                               user IDs (non-members only work if the bot shares a
                               server with them or has talked to them before).

Every DM automatically ends with the Azami invite link.
Before anything is sent you get a preview with Send / Cancel buttons.
"""
import asyncio
import re
import traceback
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

# ───────────────────────── settings ─────────────────────────
INVITE_LINK = "https://discord.gg/azami"   # added to the bottom of EVERY mass DM
DM_LIMIT = 2000                            # Discord's max message length
SEND_DELAY = 1.5                           # seconds between DMs (be gentle, Discord flags fast DMing)
MAX_CONSECUTIVE_FAILS = 20                 # stop early if this many DMs in a row fail
# ────────────────────────────────────────────────────────────

ID_RE = re.compile(r"<@!?(\d+)>|\b(\d{15,20})\b")


# ───────────────────────── helpers ─────────────────────────
def parse_ids(text: str) -> set:
    """Pull user IDs out of a string containing @mentions and/or raw IDs."""
    ids = set()
    for token in ID_RE.findall(text or ""):
        ids.add(int(token[0] or token[1]))
    return ids


def with_footer(message: str):
    """Message + the Azami link at the bottom. Returns None if it's empty or too long.
    A typed '\\n' becomes a real line break (slash-command boxes can't hold newlines)."""
    message = message.replace("\\n", "\n").strip()
    if not message:
        return None
    full = f"{message}\n\n{INVITE_LINK}"
    return full if len(full) <= DM_LIMIT else None


def fit_lines(lines, limit=1000):
    """Join lines for an embed field (max 1024 chars), cutting with '…and N more'."""
    out, used = [], 0
    for idx, line in enumerate(lines):
        if used + len(line) + 1 > limit - 20:
            out.append(f"…and {len(lines) - idx} more")
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


def interaction_expired(interaction: discord.Interaction) -> bool:
    """Discord interaction tokens die after 15 minutes."""
    return discord.utils.utcnow() - interaction.created_at > timedelta(minutes=14)


def status_embed(title, color, done, total, sent, failed, excluded, failed_names):
    e = discord.Embed(title=title, color=color)
    e.add_field(name="Progress", value=f"{done} / {total}", inline=True)
    e.add_field(name="✅ Sent", value=str(sent), inline=True)
    e.add_field(name="❌ Failed", value=str(failed), inline=True)
    if excluded is not None:
        e.add_field(name="🚫 Excluded", value=str(excluded), inline=True)
    if failed_names:
        e.add_field(name="Recent Failures", value=fit_lines(failed_names[-5:]), inline=False)
    return e


class ConfirmView(discord.ui.View):
    """Send / Cancel buttons — only the person who ran the command can press them."""

    def __init__(self, author_id: int):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.confirmed = None  # True = send, False = cancel, None = timed out

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the person who ran the command can use these buttons.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Send", style=discord.ButtonStyle.danger, emoji="📨")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        await interaction.response.defer()
        self.stop()


# ───────────────────────── cog ─────────────────────────
class MassDM(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.running = set()  # guild IDs that currently have a mass DM in progress

    dm_group = app_commands.Group(
        name="dm",
        description="Mass-DM members or specific users",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )

    # ── error handler (works even after the command was deferred) ──
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "❌ You need the **Administrator** permission to use this."
        else:
            msg = "❌ Something went wrong. Check the bot's logs."
            traceback.print_exception(type(error), error, error.__traceback__)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass

    # ── send one DM, returns (ok, reason) ──
    async def _dm_one(self, user, text: str):
        for attempt in (1, 2):
            try:
                await user.send(text)
                return True, ""
            except discord.HTTPException as ex:
                if ex.code == 40003 and attempt == 1:  # "opening DMs too fast" — back off once, retry
                    await asyncio.sleep(30)
                    continue
                if ex.code == 50007:
                    reason = "50007 DMs closed/blocked"
                elif ex.code == 40003:
                    reason = "40003 sending too fast"
                else:
                    reason = f"{ex.status}/{ex.code} {str(ex.text)[:30]}"
                print(f"[massdm] failed to DM {user} ({user.id}): {ex.status} code={ex.code} {ex.text}")
                return False, reason
            except Exception as ex:
                print(f"[massdm] unexpected error DMing {user} ({user.id}): {ex!r}")
                return False, type(ex).__name__
        return False, "unknown"

    # ── the sending loop with live status ──
    async def _send_batch(self, interaction: discord.Interaction, targets: list, text: str, excluded):
        total = len(targets)
        sent = failed = consecutive = 0
        failed_names = []
        stopped_early = False
        step = 1 if total <= 50 else 5  # how often the status message is refreshed

        async def push(embed):
            if interaction_expired(interaction):
                return
            try:
                await interaction.edit_original_response(content=None, embed=embed, view=None)
            except discord.HTTPException:
                pass

        await push(status_embed("📨 Mass DM in Progress", discord.Color.blurple(), 0, total, 0, 0, excluded, []))

        done = 0
        for i, user in enumerate(targets, start=1):
            ok, reason = await self._dm_one(user, text)
            done = i
            if ok:
                sent += 1
                consecutive = 0
            else:
                failed += 1
                consecutive += 1
                failed_names.append(f"{user} — {reason}")

            if i % step == 0 and i != total:
                await push(status_embed("📨 Mass DM in Progress", discord.Color.blurple(), i, total, sent, failed, excluded, failed_names))

            if consecutive >= MAX_CONSECUTIVE_FAILS and i < total:
                stopped_early = True
                break

            await asyncio.sleep(SEND_DELAY)

        final = discord.Embed(
            title="⛔ Mass DM Stopped Early" if stopped_early else "✅ Mass DM Complete",
            color=discord.Color.red() if stopped_early else discord.Color.green(),
        )
        if stopped_early:
            final.description = (
                f"{MAX_CONSECUTIVE_FAILS} DMs in a row failed, so I stopped to avoid getting the bot flagged. "
                "Check the errors below (50007 = closed DMs / blocked bot)."
            )
        final.add_field(name="Total Targeted", value=str(total), inline=True)
        final.add_field(name="Sent Successfully", value=str(sent), inline=True)
        final.add_field(name="Failed", value=str(failed), inline=True)
        if stopped_early:
            final.add_field(name="Not Attempted", value=str(total - done), inline=True)
        if excluded is not None:
            final.add_field(name="🚫 Excluded", value=str(excluded), inline=True)
        if failed_names:
            final.add_field(name="Failures", value=fit_lines(failed_names[:15]), inline=False)

        # Update the status message; if the 15-minute interaction window is over, DM the summary instead.
        if not interaction_expired(interaction):
            try:
                await interaction.edit_original_response(content=None, embed=final, view=None)
                return
            except discord.HTTPException:
                pass
        try:
            await interaction.user.send(embed=final)
        except discord.HTTPException:
            pass

    # ── preview + confirm + send (shared by both commands) ──
    async def _confirm_and_send(self, interaction: discord.Interaction, targets: list, text: str, excluded=None, notes=None):
        guild_id = interaction.guild_id
        if guild_id in self.running:
            return await interaction.followup.send("⚠️ A mass DM is already running in this server. Wait for it to finish.", ephemeral=True)

        minutes = max(1, round(len(targets) * SEND_DELAY / 60))
        preview = discord.Embed(title="📨 Confirm Mass DM", description=text, color=discord.Color.orange())
        preview.add_field(name="Recipients", value=str(len(targets)), inline=True)
        if excluded is not None:
            preview.add_field(name="🚫 Excluded", value=str(excluded), inline=True)
        preview.add_field(name="Est. time", value=f"~{minutes} min", inline=True)
        if notes:
            preview.add_field(name="Notes", value=fit_lines(notes), inline=False)
        preview.set_footer(text="The message above is exactly what gets sent. Buttons expire in 60 seconds.")

        view = ConfirmView(interaction.user.id)
        await interaction.followup.send(embed=preview, view=view, ephemeral=True)
        await view.wait()

        if view.confirmed is not True:
            text_out = "❌ Cancelled. Nothing was sent." if view.confirmed is False else "⌛ Timed out. Nothing was sent."
            return await interaction.edit_original_response(content=text_out, embed=None, view=None)

        if guild_id in self.running:  # someone else started one while we waited
            return await interaction.edit_original_response(content="⚠️ A mass DM is already running in this server.", embed=None, view=None)

        self.running.add(guild_id)
        try:
            await self._send_batch(interaction, targets, text, excluded)
        finally:
            self.running.discard(guild_id)

    # ───────────────────────── /dm all ─────────────────────────
    @dm_group.command(name="all", description="DM every member currently in this server (optionally skipping some)")
    @app_commands.describe(
        message="The message to send (the Azami link is added automatically)",
        exclude="Members to skip: mention them (@user) and/or paste raw user IDs, separated by spaces",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def dm_all(self, interaction: discord.Interaction, message: str, exclude: str = ""):
        await interaction.response.defer(ephemeral=True)

        text = with_footer(message)
        if text is None:
            return await interaction.followup.send(
                f"❌ Message is empty or too long. With the Azami link added it must fit in {DM_LIMIT} characters. Nothing was sent.",
                ephemeral=True,
            )

        excluded_ids = parse_ids(exclude)
        if exclude.strip() and not excluded_ids:
            return await interaction.followup.send("❌ I couldn't find any valid mentions or user IDs in `exclude`. Nothing was sent.", ephemeral=True)

        guild = interaction.guild
        if not guild.chunked:  # make sure the full member list is loaded
            try:
                await guild.chunk()
            except Exception:
                pass

        members = [m for m in guild.members if not m.bot]
        targets = [m for m in members if m.id not in excluded_ids]
        excluded_count = (len(members) - len(targets)) if excluded_ids else None

        notes = []
        if excluded_ids and len(excluded_ids) > (excluded_count or 0):
            notes.append(f"{len(excluded_ids) - excluded_count} excluded ID(s) aren't members of this server.")

        if not targets:
            return await interaction.followup.send("No members left to DM after exclusions.", ephemeral=True)

        await self._confirm_and_send(interaction, targets, text, excluded=excluded_count, notes=notes)

    # ───────────────────────── /dm users ─────────────────────────
    @dm_group.command(name="users", description="DM specific members/users — tag members, or paste raw IDs for non-members")
    @app_commands.describe(
        targets="Mention members (@user) and/or paste raw user IDs, separated by spaces",
        message="The message to send (the Azami link is added automatically)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def dm_users(self, interaction: discord.Interaction, targets: str, message: str):
        await interaction.response.defer(ephemeral=True)

        text = with_footer(message)
        if text is None:
            return await interaction.followup.send(
                f"❌ Message is empty or too long. With the Azami link added it must fit in {DM_LIMIT} characters. Nothing was sent.",
                ephemeral=True,
            )

        ids = parse_ids(targets)
        if not ids:
            return await interaction.followup.send("❌ No valid mentions or user IDs found.", ephemeral=True)

        resolved, unresolved, bots = [], [], []
        for uid in sorted(ids):
            user = interaction.guild.get_member(uid)
            if user is None:
                try:
                    user = await self.bot.fetch_user(uid)
                except (discord.NotFound, discord.HTTPException):
                    unresolved.append(str(uid))
                    continue
            if user.bot:
                bots.append(str(user))
                continue
            resolved.append(user)

        notes = []
        if unresolved:
            notes.append("Couldn't find these IDs: " + ", ".join(unresolved))
        if bots:
            notes.append("Skipped bots: " + ", ".join(bots))

        if not resolved:
            return await interaction.followup.send("❌ No valid targets to DM." + ("\n" + "\n".join(notes) if notes else ""), ephemeral=True)

        await self._confirm_and_send(interaction, resolved, text, notes=notes)


async def setup(bot):
    await bot.add_cog(MassDM(bot))
