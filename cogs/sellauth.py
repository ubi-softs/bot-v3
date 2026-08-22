"""
SellAuth API cog
Docs: https://docs.sellauth.com/api-documentation
All requests go to: https://api.sellauth.com/v1/shops/{SHOP_ID}/...

Reads SELLAUTH_API_KEY / SELLAUTH_SHOP_ID from the bot object, which main.py
sets from the SELLAUTH_API_KEY / SELLAUTH_SHOP_ID environment variables.
"""
import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import datetime


def sa_embed(title, description="", color=discord.Color.green()):
    e = discord.Embed(title=title, description=description, color=color, timestamp=datetime.datetime.utcnow())
    e.set_footer(text="SellAuth Integration")
    return e


class SellAuth(commands.Cog):
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

    # ── /sa_products ──────────────────────────────────────────
    @app_commands.command(name="sa_products", description="List all products in your SellAuth shop")
    @app_commands.checks.has_permissions(administrator=True)
    async def sa_products(self, interaction: discord.Interaction):
        if not self._configured():
            return await interaction.response.send_message("❌ SellAuth isn't configured. Set SELLAUTH_API_KEY / SELLAUTH_SHOP_ID.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            r = await s.get(f"{self.base}/products", headers=self.headers)
            data = await r.json()
        if r.status != 200:
            return await interaction.followup.send(f"❌ API Error: {data}", ephemeral=True)
        products = data.get("data", data) if isinstance(data, dict) else data
        if not products:
            return await interaction.followup.send("No products found.", ephemeral=True)
        lines = [f"**{p.get('name', p.get('title','?'))}** — ID: `{p.get('id','?')}` | ${p.get('price','?')}" for p in products[:20]]
        e = sa_embed(f"🛒 Products ({len(products)})", "\n".join(lines))
        await interaction.followup.send(embed=e, ephemeral=True)

    # ── /sa_product ───────────────────────────────────────────
    @app_commands.command(name="sa_product", description="View details of a specific product")
    @app_commands.describe(product_id="Product ID from /sa_products")
    @app_commands.checks.has_permissions(administrator=True)
    async def sa_product(self, interaction: discord.Interaction, product_id: str):
        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            r = await s.get(f"{self.base}/products/{product_id}", headers=self.headers)
            p = await r.json()
        if r.status != 200:
            return await interaction.followup.send(f"❌ API Error: {p}", ephemeral=True)
        e = sa_embed(f"🛒 {p.get('name', p.get('title','Product'))}")
        e.add_field(name="ID", value=str(p.get("id", "?")), inline=True)
        e.add_field(name="Price", value=f"${p.get('price','?')}", inline=True)
        e.add_field(name="Stock", value=str(p.get("stock", "∞")), inline=True)
        e.add_field(name="Visible", value="✅" if p.get("visible") else "❌", inline=True)
        e.add_field(name="Description", value=str(p.get("description", "—"))[:500], inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

    # ── /sa_addproduct ────────────────────────────────────────
    @app_commands.command(name="sa_addproduct", description="Create a new product in your SellAuth shop")
    @app_commands.describe(title="Product name", price="Price (e.g. 9.99)", description="Product description", stock="Stock quantity (-1 for unlimited)")
    @app_commands.checks.has_permissions(administrator=True)
    async def sa_addproduct(self, interaction: discord.Interaction, title: str, price: float, description: str = "", stock: int = -1):
        await interaction.response.defer(ephemeral=True)
        payload = {"name": title, "price": price, "description": description}
        if stock != -1:
            payload["stock"] = stock
        async with aiohttp.ClientSession() as s:
            r = await s.post(f"{self.base}/products", headers=self.headers, json=payload)
            data = await r.json()
        if r.status not in (200, 201):
            return await interaction.followup.send(f"❌ Failed: {data}", ephemeral=True)
        pid = data.get("id", "?")
        await interaction.followup.send(embed=sa_embed("✅ Product Created", f"**{title}** created!\nID: `{pid}` | Price: **${price}**"), ephemeral=True)

    # ── /sa_editproduct ───────────────────────────────────────
    @app_commands.command(name="sa_editproduct", description="Edit an existing product")
    @app_commands.describe(product_id="Product ID to edit", title="New title (leave blank to keep)", price="New price (leave 0 to keep)", description="New description")
    @app_commands.checks.has_permissions(administrator=True)
  async def sa_editproduct(self, interaction: discord.Interaction, product_id: str, title: str = "", price: float = 0.0, description: str = ""):
        await interaction.response.defer(ephemeral=True)
        payload = {}
        if title:
            payload["name"] = title
        if price:
            payload["price"] = price
        if description:
            payload["description"] = description
        if not payload:
            return await interaction.followup.send("❌ Provide at least one field to edit.", ephemeral=True)
        async with aiohttp.ClientSession() as s:
            r = await s.put(f"{self.base}/products/{product_id}", headers=self.headers, json=payload)
            data = await r.json()
        if r.status != 200:
            return await interaction.followup.send(f"❌ Failed: {data}", ephemeral=True)
        await interaction.followup.send(embed=sa_embed("✅ Product Updated", f"Product `{product_id}` has been updated."), ephemeral=True)

    # ── /sa_deleteproduct ─────────────────────────────────────
    @app_commands.command(name="sa_deleteproduct", description="Delete a product from your shop")
    @app_commands.describe(product_id="Product ID to delete")
    @app_commands.checks.has_permissions(administrator=True)
    async def sa_deleteproduct(self, interaction: discord.Interaction, product_id: str):
        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            r = await s.delete(f"{self.base}/products/{product_id}", headers=self.headers)
        if r.status in (200, 204):
            await interaction.followup.send(embed=sa_embed("🗑️ Product Deleted", f"Product `{product_id}` deleted."), ephemeral=True)
        else:
            data = await r.json()
            await interaction.followup.send(f"❌ Failed: {data}", ephemeral=True)

    # ── /sa_orders ────────────────────────────────────────────
    @app_commands.command(name="sa_orders", description="List recent orders from your shop")
    @app_commands.checks.has_permissions(administrator=True)
    async def sa_orders(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            r = await s.get(f"{self.base}/orders", headers=self.headers)
            data = await r.json()
        if r.status != 200:
            return await interaction.followup.send(f"❌ API Error: {data}", ephemeral=True)
        orders = data.get("data", data) if isinstance(data, dict) else data
        if not orders:
            return await interaction.followup.send("No orders found.", ephemeral=True)
        lines = [f"**#{o.get('id','?')}** — {o.get('product_title','?')} | ${o.get('total','?')} | {o.get('status','?')}" for o in orders[:15]]
        e = sa_embed(f"📦 Recent Orders ({len(orders)})", "\n".join(lines))
        await interaction.followup.send(embed=e, ephemeral=True)

    # ── /sa_order ─────────────────────────────────────────────
    @app_commands.command(name="sa_order", description="View a specific order")
    @app_commands.describe(order_id="Order ID")
    @app_commands.checks.has_permissions(administrator=True)
    async def sa_order(self, interaction: discord.Interaction, order_id: str):
        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            r = await s.get(f"{self.base}/orders/{order_id}", headers=self.headers)
            o = await r.json()
        if r.status != 200:
            return await interaction.followup.send("❌ Not found.", ephemeral=True)
        e = sa_embed(f"📦 Order #{order_id}")
        e.add_field(name="Product", value=o.get("product_title", "?"), inline=True)
        e.add_field(name="Total", value=f"${o.get('total','?')}", inline=True)
        e.add_field(name="Status", value=o.get("status", "?"), inline=True)
        e.add_field(name="Email", value=o.get("email", "?"), inline=True)
        e.add_field(name="Date", value=str(o.get("created_at", "?"))[:10], inline=True)
        await interaction.followup.send(embed=e, ephemeral=True)

    # ── /sa_invoices ──────────────────────────────────────────
    @app_commands.command(name="sa_invoices", description="List recent invoices for your shop")
    @app_commands.checks.has_permissions(administrator=True)
    async def sa_invoices(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            r = await s.get(f"{self.base}/invoices", headers=self.headers)
            data = await r.json()
        if r.status != 200:
            return await interaction.followup.send(f"❌ API Error: {data}", ephemeral=True)
        invoices = data.get("data", data) if isinstance(data, dict) else data
        if not invoices:
            return await interaction.followup.send("No invoices found.", ephemeral=True)
        lines = [f"**#{i.get('id','?')}** — ${i.get('total', i.get('amount','?'))} | {i.get('status','?')}" for i in invoices[:15]]
        await interaction.followup.send(embed=sa_embed(f"🧾 Invoices ({len(invoices)})", "\n".join(lines)), ephemeral=True)

    # ── /sa_coupons ───────────────────────────────────────────
    @app_commands.command(name="sa_coupons", description="List all coupons")
    @app_commands.checks.has_permissions(administrator=True)
    async def sa_coupons(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            r = await s.get(f"{self.base}/coupons", headers=self.headers)
            data = await r.json()
        if r.status != 200:
            return await interaction.followup.send(f"❌ {data}", ephemeral=True)
        coupons = data.get("data", data) if isinstance(data, dict) else data
        if not coupons:
            return await interaction.followup.send("No coupons found.", ephemeral=True)
        lines = [f"`{c.get('code','?')}` — {c.get('discount','?')}% off | Uses: {c.get('uses',0)}" for c in coupons[:20]]
        await interaction.followup.send(embed=sa_embed(f"🏷️ Coupons ({len(coupons)})", "\n".join(lines)), ephemeral=True)

    # ── /sa_addcoupon ─────────────────────────────────────────
    @app_commands.command(name="sa_addcoupon", description="Create a discount coupon")
    @app_commands.describe(code="Coupon code", discount="Discount percentage (1-100)", max_uses="Max uses (0 = unlimited)")
    @app_commands.checks.has_permissions(administrator=True)
    async def sa_addcoupon(self, interaction: discord.Interaction, code: str, discount: app_commands.Range[int, 1, 100], max_uses: int = 0):
        await interaction.response.defer(ephemeral=True)
        payload = {"code": code, "discount": discount}
        if max_uses:
            payload["max_uses"] = max_uses
        async with aiohttp.ClientSession() as s:
            r = await s.post(f"{self.base}/coupons", headers=self.headers, json=payload)
            data = await r.json()
        if r.status not in (200, 201):
            return await interaction.followup.send(f"❌ {data}", ephemeral=True)
        await interaction.followup.send(embed=sa_embed("✅ Coupon Created", f"Code: `{code}` | {discount}% off"), ephemeral=True)

    # ── /sa_deletecoupon ──────────────────────────────────────
    @app_commands.command(name="sa_deletecoupon", description="Delete a coupon")
    @app_commands.describe(coupon_id="Coupon ID")
    @app_commands.checks.has_permissions(administrator=True)
    async def sa_deletecoupon(self, interaction: discord.Interaction, coupon_id: str):
        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            r = await s.delete(f"{self.base}/coupons/{coupon_id}", headers=self.headers)
        if r.status in (200, 204):
            await interaction.followup.send(embed=sa_embed("🗑️ Coupon Deleted", f"Coupon `{coupon_id}` deleted."), ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to delete coupon.", ephemeral=True)

    # ── /sa_blacklist ─────────────────────────────────────────
    @app_commands.command(name="sa_blacklist", description="List blacklist entries on your shop")
    @app_commands.checks.has_permissions(administrator=True)
    async def sa_blacklist(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            r = await s.get(f"{self.base}/blacklist", headers=self.headers)
            data = await r.json()
        if r.status != 200:
            return await interaction.followup.send(f"❌ {data}", ephemeral=True)
        entries = data.get("data", data) if isinstance(data, dict) else data
        if not entries:
            return await interaction.followup.send("No blacklist entries.", ephemeral=True)
        lines = [f"**#{b.get('id','?')}** — {b.get('type','?')}: `{b.get('value','?')}`" for b in entries[:20]]
        await interaction.followup.send(embed=sa_embed(f"🚫 Blacklist ({len(entries)})", "\n".join(lines)), ephemeral=True)

    # ── /sa_blacklistadd ──────────────────────────────────────
    @app_commands.command(name="sa_blacklistadd", description="Add an entry (email/ip/etc) to the SellAuth blacklist")
    @app_commands.describe(type="Blacklist type, e.g. email, ip, discord_id", value="The value to blacklist")
    @app_commands.checks.has_permissions(administrator=True)
    async def sa_blacklistadd(self, interaction: discord.Interaction, type: str, value: str):
        await interaction.response.defer(ephemeral=True)
        payload = {"type": type, "match_type": "exact", "value": value}
        async with aiohttp.ClientSession() as s:
            r = await s.post(f"{self.base}/blacklist", headers=self.headers, json=payload)
            data = await r.json()
        if r.status not in (200, 201):
            return await interaction.followup.send(f"❌ {data}", ephemeral=True)
        await interaction.followup.send(embed=sa_embed("✅ Blacklist Entry Added", f"`{type}`: `{value}`"), ephemeral=True)

    # ── /sa_blacklistremove ───────────────────────────────────
    @app_commands.command(name="sa_blacklistremove", description="Remove a blacklist entry by its ID")
    @app_commands.describe(blacklist_id="Blacklist entry ID from /sa_blacklist")
    @app_commands.checks.has_permissions(administrator=True)
    async def sa_blacklistremove(self, interaction: discord.Interaction, blacklist_id: str):
        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            r = await s.delete(f"{self.base}/blacklist/{blacklist_id}", headers=self.headers)
        if r.status in (200, 204):
            await interaction.followup.send(embed=sa_embed("🗑️ Blacklist Entry Removed", f"Entry `{blacklist_id}` removed."), ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to remove entry.", ephemeral=True)

    # ── /sa_shopinfo ──────────────────────────────────────────
    @app_commands.command(name="sa_shopinfo", description="View your SellAuth shop details")
    @app_commands.checks.has_permissions(administrator=True)
    async def sa_shopinfo(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            r = await s.get(f"{self.base}", headers=self.headers)
            data = await r.json()
        if r.status != 200:
            return await interaction.followup.send(f"❌ {data}", ephemeral=True)
        e = sa_embed("🏪 Shop Info")
        for k, v in data.items():
            if isinstance(v, (str, int, float, bool)) and len(str(v)) < 100:
                e.add_field(name=k.replace("_", " ").title(), value=str(v), inline=True)
        await interaction.followup.send(embed=e, ephemeral=True)

    # ── /sa_revenue ───────────────────────────────────────────
    @app_commands.command(name="sa_revenue", description="Check shop revenue/stats")
    @app_commands.checks.has_permissions(administrator=True)
    async def sa_revenue(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            r = await s.get(f"{self.base}/analytics", headers=self.headers)
            data = await r.json()
        if r.status != 200:
            return await interaction.followup.send(f"❌ {data}", ephemeral=True)
        e = sa_embed("📈 Shop Revenue & Stats")
        for k, v in data.items():
            if isinstance(v, (str, int, float)):
                e.add_field(name=k.replace("_", " ").title(), value=str(v), inline=True)
        await interaction.followup.send(embed=e, ephemeral=True)

    # ── /sa_topproducts ───────────────────────────────────────
    @app_commands.command(name="sa_topproducts", description="View your top 5 products by revenue")
    @app_commands.checks.has_permissions(administrator=True)
    async def sa_topproducts(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            r = await s.get(f"{self.base}/analytics/top-products", headers=self.headers)
            data = await r.json()
        if r.status != 200:
            return await interaction.followup.send(f"❌ {data}", ephemeral=True)
        items = data if isinstance(data, list) else data.get("data", [])
        if not items:
            return await interaction.followup.send("No product revenue data yet.", ephemeral=True)
        lines = [f"**{p.get('product_name','?')}** — ${p.get('total_revenue_usd',0)} ({p.get('total_orders',0)} orders)" for p in items]
        await interaction.followup.send(embed=sa_embed("🏆 Top Products", "\n".join(lines)), ephemeral=True)

    async def cog_app_command_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            return
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ SellAuth error: {error}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(SellAuth(bot))
