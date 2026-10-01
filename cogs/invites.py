import discord
from discord import app_commands
from discord.ext import commands
import json, os, datetime

INVITES_FILE = "data/invites.json"
CONFIG_FILE = "data/invite_config.json"
REWARDS_FILE = "data/invite_rewards.json"


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs("data", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def effective_invites(stats: dict) -> int:
    """Net invites still counted — total ever invited minus how many have since left."""
    return max(0, stats.get("total", 0) - stats.get("left", 0))


class Invites(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.invite_cache = {}

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            try:
                invites = await guild.invites()
                self.invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        self.invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        try:
            new_invites = await guild.invites()
        except Exception:
            return
        old_cache = self.invite_cache.get(guild.id, {})
        inviter_id = None
        used_code = None

        for inv in new_invites:
            if old_cache.get(inv.code, 0) < inv.uses:
                inviter_id = str(inv.inviter.id) if inv.inviter else None
                used_code = inv.code
                break

        self.invite_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}

        if inviter_id:
            data = load_json(INVITES_FILE)
            gid = str(guild.id)
            data.setdefault(gid, {}).setdefault(inviter_id, {"total": 0, "left": 0, "codes": [], "invited_users": []})
            data[gid][inviter_id]["total"] += 1
            if used_code not in data[gid][inviter_id]["codes"]:
                data[gid][inviter_id]["codes"].append(used_code)
            # Remember exactly who this inviter brought in, so we can attribute a later leave correctly
            data[gid][inviter_id].setdefault("invited_users", []).append(str(member.id))
            save_json(INVITES_FILE, data)

        config = load_json(CONFIG_FILE)
        gid = str(guild.id)
        welch_id = config.get(gid, {}).get("welcome_channel")
        if welch_id:
            ch = guild.get_channel(int(welch_id))
            if ch:
                inviter_text = f"Invited by <@{inviter_id}>" if inviter_id else "Used a vanity/unknown invite"
                e = discord.Embed(
                    title="👋 New Member!",
                    description=f"Welcome {member.mention} to **{guild.name}**!\n{inviter_text}",
                    color=discord.Color.green(),
                    timestamp=datetime.datetime.utcnow(),
                )
                e.set_thumbnail(url=member.display_avatar.url)
                e.set_footer(text=f"Member #{guild.member_count}")
                await ch.send(embed=e)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        guild = member.guild
        gid = str(guild.id)
        data = load_json(INVITES_FILE)
        guild_data = data.get(gid, {})

        data.setdefault(gid, {}).setdefault("__leaves__", 0)
        data[gid]["__leaves__"] = data[gid].get("__leaves__", 0) + 1

        # Find who invited this leaving member
        inviter_id = None
        for uid, stats in guild_data.items():
            if uid == "__leaves__" or not isinstance(stats, dict):
                continue
            if str(member.id) in stats.get("invited_users", []):
                inviter_id = uid
                break

        if not inviter_id:
            save_json(INVITES_FILE, data)
            return

        data[gid][inviter_id]["left"] = data[gid][inviter_id].get("left", 0) + 1
        data[gid][inviter_id]["invited_users"] = [u for u in data[gid][inviter_id].get("invited_users", []) if u != str(member.id)]
        save_json(INVITES_FILE, data)

        config = load_json(CONFIG_FILE)
        if not config.get(gid, {}).get("revoke_enabled"):
            return  # revoke feature is off, just update the numbers silently

        new_count = effective_invites(data[gid][inviter_id])
        rewards = load_json(REWARDS_FILE).get(gid, {})
        inviter_member = guild.get_member(int(inviter_id))
        if not inviter_member:
            return

        lost_roles = []
        for threshold_str, role_id in rewards.items():
            threshold = int(threshold_str)
            if new_count < threshold:
                role = guild.get_role(int(role_id))
                if role and role in inviter_member.roles:
                    try:
                        await inviter_member.remove_roles(role, reason="No longer qualifies — an invited member left")
                        lost_roles.append((role, threshold))
                    except discord.HTTPException:
                        pass

        if lost_roles:
            role_list = "\n".join(f"• {r.mention} (required {t} invites)" for r, t in lost_roles)
            try:
                await inviter_member.send(
                    f"⚠️ **{member}** left **{guild.name}**, and one of their invites was yours.\n\n"
                    f"You now have **{new_count}** effective invite(s), so you no longer qualify for:\n{role_list}\n\n"
                    f"Invite more people to earn these back!"
                )
            except discord.Forbidden:
                pass

    @app_commands.command(name="invites", description="Check your invite stats")
    @app_commands.describe(member="Member to check (default: yourself)")
    async def invites(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        uid, gid = str(member.id), str(interaction.guild.id)
        stats = load_json(INVITES_FILE).get(gid, {}).get(uid, {"total": 0, "left": 0})
        e = discord.Embed(
            title=f"📨 Invites for {member.display_name}",
            description=(
                f"**Total Invited:** {stats.get('total',0)}\n"
                f"**Left Since:** {stats.get('left',0)}\n"
                f"**Effective Invites:** {effective_invites(stats)}"
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="inviteleaderboard", description="View the invite leaderboard")
    async def inviteleaderboard(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        data = load_json(INVITES_FILE)
        users = {uid: d for uid, d in data.get(gid, {}).items() if uid != "__leaves__" and isinstance(d, dict)}
        sorted_users = sorted(users.items(), key=lambda x: effective_invites(x[1]), reverse=True)
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (uid, d) in enumerate(sorted_users[:10]):
            m = interaction.guild.get_member(int(uid))
            name = m.display_name if m else f"User {uid}"
            medal = medals[i] if i < 3 else f"**#{i+1}**"
            lines.append(f"{medal} {name} — **{effective_invites(d)}** effective invites")
        e = discord.Embed(title="📨 Invite Leaderboard", description="\n".join(lines) or "No data.", color=discord.Color.gold())
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="invitepanel", description="Post the invite tracking panel")
    @app_commands.describe(channel="Channel to post in")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def invitepanel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        gid = str(interaction.guild.id)
        data = load_json(INVITES_FILE)
        users = {uid: d for uid, d in data.get(gid, {}).items() if uid != "__leaves__" and isinstance(d, dict)}
        sorted_users = sorted(users.items(), key=lambda x: effective_invites(x[1]), reverse=True)
        lines = [f"**#{i+1}** <@{uid}> — {effective_invites(d)} invites" for i, (uid, d) in enumerate(sorted_users[:15])]
        e = discord.Embed(
            title="📊 Invite Tracking Panel",
            description="\n".join(lines) or "No invites tracked yet.",
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.utcnow(),
        )
        e.set_footer(text="Updates on new joins")
        await channel.send(embed=e)
        await interaction.response.send_message(f"✅ Invite panel posted in {channel.mention}", ephemeral=True)

    @app_commands.command(name="setinvitepanel", description="Customize the invite panel title")
    @app_commands.describe(title="Panel title")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setinvitepanel(self, interaction: discord.Interaction, title: str):
        config = load_json(CONFIG_FILE)
        config.setdefault(str(interaction.guild.id), {})["panel_title"] = title
        save_json(CONFIG_FILE, config)
        await interaction.response.send_message(f"✅ Invite panel title set to **{title}**", ephemeral=True)

    # ── Reward thresholds ───────────────────────────────────────
    inviterewards_group = app_commands.Group(name="inviterewards", description="Manage invite-milestone role rewards")

    @inviterewards_group.command(name="set", description="Give a role automatically once a member hits X effective invites")
    @app_commands.describe(invites="Number of invites required", role="Role to award")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rewards_set(self, interaction: discord.Interaction, invites: app_commands.Range[int, 1, 100000], role: discord.Role):
        rewards = load_json(REWARDS_FILE)
        rewards.setdefault(str(interaction.guild.id), {})[str(invites)] = str(role.id)
        save_json(REWARDS_FILE, rewards)
        await interaction.response.send_message(f"✅ {role.mention} is now awarded at **{invites}** effective invites.", ephemeral=True)

    @inviterewards_group.command(name="remove", description="Remove an invite milestone reward")
    @app_commands.describe(invites="The invite threshold to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rewards_remove(self, interaction: discord.Interaction, invites: int):
        rewards = load_json(REWARDS_FILE)
        gid = str(interaction.guild.id)
        removed = rewards.get(gid, {}).pop(str(invites), None)
        save_json(REWARDS_FILE, rewards)
        if removed:
            await interaction.response.send_message(f"✅ Removed the reward for **{invites}** invites.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ No reward was set for that number.", ephemeral=True)

    @inviterewards_group.command(name="list", description="View all configured invite milestone rewards")
    async def rewards_list(self, interaction: discord.Interaction):
        rewards = load_json(REWARDS_FILE).get(str(interaction.guild.id), {})
        if not rewards:
            return await interaction.response.send_message("No invite rewards configured yet.", ephemeral=True)
        sorted_items = sorted(rewards.items(), key=lambda x: int(x[0]))
        lines = []
        for threshold, role_id in sorted_items:
            role = interaction.guild.get_role(int(role_id))
            lines.append(f"**{threshold}** invites → {role.mention if role else '`deleted role`'}")
        e = discord.Embed(title="🎁 Invite Milestone Rewards", description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=e)

    # ── Revoke on leave toggle ────────────────────────────────────
    @app_commands.command(name="inviterevoke", description="Toggle: if an invited member leaves, revoke reward roles the inviter no longer qualifies for")
    @app_commands.describe(enabled="Turn invite revoke on or off")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def inviterevoke(self, interaction: discord.Interaction, enabled: bool):
        config = load_json(CONFIG_FILE)
        config.setdefault(str(interaction.guild.id), {})["revoke_enabled"] = enabled
        save_json(CONFIG_FILE, config)
        state = "enabled" if enabled else "disabled"
        description = (
            "If a member leaves, the person who invited them loses the reward role(s) they no longer "
            "qualify for and gets a DM explaining why."
            if enabled else
            "Reward roles will no longer be automatically revoked when invited members leave."
        )
        await interaction.response.send_message(f"✅ Invite revoke **{state}**. {description}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Invites(bot))
