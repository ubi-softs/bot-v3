"""
Commands built specifically for a social-media-services shop:

  /services       — public command, lists everything you sell straight from SellAuth
  /orderstatus     — lets a customer check their own order without opening a ticket
  /refillrequest   — customer reports a drop (lost followers/likes/etc) and it opens
                     a dedicated ticket so staff can review it against your warranty window
"""
import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import datetime
import json
import os

REFILL_CONFIG_FILE = "data/refill_config.json"
REFILL_LOG_FILE = "data/refill_requests.json"


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs("data", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


class SocialMediaShop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @property
    def base(self):
        shop_id = getattr(self.bot, "SELLAUTH_SHOP_ID", "")
        return f"https://api.sellauth.com/v1/shops/{shop_id}"

    @property
    def headers(self):
        api_key = getattr(self.bot, "SELLAUTH_API_KEY", "")
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _configured(self):
        return bool(getattr(self.bot, "SELLAUTH_API_KEY", "")) and bool(getattr(self.bot, "SELLAUTH_SHOP_ID", ""))

    # ── /services ─────────────────────────────────────────────
    @app_commands.command(name="services", description="Browse every social media service we offer")
    async def services(self, interaction: discord.Interaction):
        if not self._configured():
            return await interaction.response.send_message("❌ The shop isn't connected yet — ask an admin to configure it.", ephemeral=True)

        await interaction.response.defer()
        async with aiohttp.ClientSession() as s:
            r = await s.get(f"{self.base}/products", headers=self.headers)
            data = await r.json()

        if r.status != 200:
            return await interaction.followup.send("❌ Couldn't load services right now, try again shortly.")

        products = data.get("data", data) if isinstance(data, dict) else data
        visible = [p for p in products if p.get("visible", True)]
        if not visible:
            return await interaction.followup.send("No services are listed right now.")

        e = discord.Embed(
            title="📱 Our Social Media Services",
            description="Here's everything currently available. Use `/vouch` after your order to leave feedback!",
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.utcnow(),
        )
        for p in visible[:25]:
            name = p.get("name", p.get("title", "Service"))
            price = p.get("price", "?")
            stock = p.get("stock")
            stock_text = "✅ In stock" if stock is None or stock == -1 else (f"📦 {stock} in stock" if stock > 0 else "❌ Out of stock")
            e.add_field(name=f"{name} — ${price}", value=stock_text, inline=True)
        e.set_footer(text="Open a ticket to order, or use /suggest to request a service we don't have yet")
        await interaction.followup.send(embed=e)

    # ── /orderstatus ──────────────────────────────────────────
    @app_commands.command(name="orderstatus", description="Check the status of your order")
    @app_commands.describe(order_id="Your order ID (from your confirmation email)", email="The email you used at checkout")
    async def orderstatus(self, interaction: discord.Interaction, order_id: str, email: str):
        if not self._configured():
            return await interaction.response.send_message("❌ The shop isn't connected yet — ask an admin to configure it.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            r = await s.get(f"{self.base}/orders/{order_id}", headers=self.headers)
            o = await r.json()

        if r.status != 200:
            return await interaction.followup.send("❌ Order not found — double check your order ID.", ephemeral=True)

        # Require the email to match so people can't snoop on each other's orders by guessing IDs
        order_email = str(o.get("email", "")).strip().lower()
        if order_email and order_email != email.strip().lower():
            return await interaction.followup.send("❌ That email doesn't match our records for this order ID.", ephemeral=True)

        e = discord.Embed(title=f"📦 Order #{order_id}", color=discord.Color.blurple(), timestamp=datetime.datetime.utcnow())
        e.add_field(name="Product", value=o.get("product_title", "?"), inline=True)
        e.add_field(name="Status", value=o.get("status", "?").title(), inline=True)
        e.add_field(name="Total", value=f"${o.get('total','?')}", inline=True)
        e.add_field(name="Ordered", value=str(o.get("created_at", "?"))[:10], inline=True)
        await interaction.followup.send(embed=e, ephemeral=True)

    # ── /refillrequest ────────────────────────────────────────
    @app_commands.command(name="refillrequest", description="Report a drop (lost followers/likes/views) and open a refill ticket")
    @app_commands.describe(
        order_id="Your order ID",
        platform="Which platform the service was on",
        link="The link/URL of the page or post that dropped",
        details="What happened — how much dropped, when you noticed, etc.",
    )
    async def refillrequest(self, interaction: discord.Interaction, order_id: str, platform: str, link: str, details: str):
        guild = interaction.guild
        member = interaction.user
        config = load_json(REFILL_CONFIG_FILE)
        gid = str(guild.id)

        cat_name = config.get(gid, {}).get("category", "Refill Requests")
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

        safe_name = "".join(c for c in member.name.lower() if c.isalnum() or c == "-").strip("-") or str(member.id)
        ch = await guild.create_text_channel(f"refill-{safe_name}", category=cat, overwrites=overwrites)

        e = discord.Embed(title="🔁 Refill Request", color=discord.Color.orange(), timestamp=datetime.datetime.utcnow())
        e.add_field(name="Order ID", value=order_id, inline=True)
        e.add_field(name="Platform", value=platform, inline=True)
        e.add_field(name="Link", value=link, inline=False)
        e.add_field(name="Details", value=details, inline=False)
        e.set_author(name=str(member), icon_url=member.display_avatar.url)
        e.set_footer(text="Staff: verify this is within the warranty window before actioning")

        await ch.send(content=f"{member.mention}" + (f" | {support_role.mention}" if support_role else ""), embed=e)

        log = load_json(REFILL_LOG_FILE)
        log.setdefault(gid, []).append({
            "user_id": str(member.id),
            "order_id": order_id,
            "platform": platform,
            "opened": str(datetime.datetime.utcnow()),
            "channel_id": str(ch.id),
        })
        save_json(REFILL_LOG_FILE, log)

        await interaction.response.send_message(f"✅ Refill request opened: {ch.mention}", ephemeral=True)

    @app_commands.command(name="setrefillrole", description="Set which role sees refill request tickets")
    @app_commands.describe(role="Support role for refill tickets")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setrefillrole(self, interaction: discord.Interaction, role: discord.Role):
        config = load_json(REFILL_CONFIG_FILE)
        config.setdefault(str(interaction.guild.id), {})["support_role"] = str(role.id)
        save_json(REFILL_CONFIG_FILE, config)
        await interaction.response.send_message(f"✅ Refill tickets will now be visible to {role.mention}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(SocialMediaShop(bot))