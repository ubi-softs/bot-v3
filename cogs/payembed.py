"""
/payembed — posts a product embed with a Buy button. Clicking it DMs the
buyer the correct Rewarble G2A gift card link for that price + instructions.
Once they buy the gift card and reply in DMs with the code, the bot logs it
and forwards it to your configured payment log (a channel, or your DMs if
none is set).
"""
import discord
from discord import app_commands
from discord.ext import commands
import json, os, datetime

CONFIG_FILE = "data/pay_config.json"
LOG_FILE = "data/payments.json"

# Default Rewarble G2A denomination links — editable/extendable via /paysetup addlink
DEFAULT_DENOMINATIONS = {
    "5": "https://www.g2a.com/rewarble-visa-gift-card-5-usd-by-rewarble-key-global-i10000502992002",
    "10": "https://www.g2a.com/rewarble-visa-gift-card-10-usd-by-rewarble-key-global-i10000502992001",
    "15": "https://www.g2a.com/rewarble-visa-gift-card-15-usd-by-rewarble-key-global-i10000502992012",
    "20": "https://www.g2a.com/rewarble-visa-gift-card-20-usd-by-rewarble-key-global-i10000502992006",
    "25": "https://www.g2a.com/rewarble-visa-gift-card-25-usd-by-rewarble-key-global-i10000502992003",
    "35": "https://www.g2a.com/rewarble-visa-gift-card-35-usd-by-rewarble-key-global-i10000502992020",
    "40": "https://www.g2a.com/rewarble-visa-gift-card-40-usd-by-rewarble-key-global-i10000502992013",
    "50": "https://www.g2a.com/rewarble-visa-gift-card-50-usd-by-rewarble-key-global-i10000502992004",
    "60": "https://www.g2a.com/rewarble-visa-gift-card-60-usd-by-rewarble-key-global-i10000502992014",
    "100": "https://www.g2a.com/rewarble-visa-gift-card-100-usd-by-rewarble-key-global-i10000502992005",
}


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs("data", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_denominations(gid: str) -> dict:
    config = load_json(CONFIG_FILE)
    return config.get(gid, {}).get("denominations", DEFAULT_DENOMINATIONS)


def find_matching_link(gid: str, price: float):
    """Find the smallest available denomination that's >= the price, so the
    buyer always has enough (or exactly enough) on the card."""
    denoms = get_denominations(gid)
    numeric = sorted(((float(k), v) for k, v in denoms.items()), key=lambda x: x[0])

    for amount, url in numeric:
        if amount >= price:
            return amount, url

    # Price is higher than every available card — return the largest anyway
    return numeric[-1] if numeric else (None, None)


class BuyView(discord.ui.View):
    def __init__(self, bot, item_name: str, price: float, guild_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.item_name = item_name
        self.price = price
        self.guild_id = guild_id

    @discord.ui.button(label="Buy Now", emoji="💰", style=discord.ButtonStyle.success, custom_id="payembed_buy")
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid = str(self.guild_id)
        amount, link = find_matching_link(gid, self.price)

        if not link:
            return await interaction.response.send_message(
                "❌ Payment isn't set up yet — ask an admin to run `/paysetup addlink`.", ephemeral=True
            )

        note = ""
        if amount > self.price:
            note = f"\n⚠️ There's no exact ${self.price:g} card, so buy the ${amount:g} one — you'll have credit left over, staff will sort that out with you."
        elif amount < self.price:
            note = f"\n⚠️ This is above our largest card (${amount:g}). You may need to buy more than one, or contact staff for help."

        e = discord.Embed(
            title=f"💰 Purchase: {self.item_name}",
            description=(
                f"**Price:** ${self.price:g}\n\n"
                f"**How to pay:**\n"
                f"1️⃣ Buy a **${amount:g}** Rewarble G2A gift card here:\n{link}{note}\n\n"
                f"2️⃣ Once you have the code, reply to **this DM** with the code and nothing else.\n"
                f"3️⃣ We'll confirm and process your order once we receive it."
            ),
            color=discord.Color.gold(),
        )

        try:
            await interaction.user.send(embed=e)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "❌ I couldn't DM you — please enable DMs from server members and try again.", ephemeral=True
            )

        config = load_json(CONFIG_FILE)
        config.setdefault(gid, {}).setdefault("awaiting", {})[str(interaction.user.id)] = {
            "item": self.item_name,
            "price": self.price,
            "guild_id": self.guild_id,
            "time": str(datetime.datetime.utcnow()),
        }
        save_json(CONFIG_FILE, config)

        await interaction.response.send_message("✅ Check your DMs for payment instructions!", ephemeral=True)


class PayEmbed(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is not None or message.author.bot:
            return

        config = load_json(CONFIG_FILE)
        uid = str(message.author.id)

        matched_gid = None
        for gid, gconf in config.items():
            if uid in gconf.get("awaiting", {}):
                matched_gid = gid
                break

        if not matched_gid:
            return

        pending = config[matched_gid]["awaiting"].pop(uid)
        save_json(CONFIG_FILE, config)

        code = message.content.strip()

        log = load_json(LOG_FILE)
        log.setdefault(matched_gid, []).append({
            "user_id": uid,
            "username": str(message.author),
            "item": pending["item"],
            "price": pending["price"],
            "code": code,
            "time": str(datetime.datetime.utcnow()),
        })
        save_json(LOG_FILE, log)

        await message.channel.send("✅ Got it! Your code has been submitted to our team — we'll confirm shortly.")

        guild = self.bot.get_guild(int(matched_gid))
        if not guild:
            return

        e = discord.Embed(title="💰 New Payment Submission", color=discord.Color.gold(), timestamp=datetime.datetime.utcnow())
        e.add_field(name="Buyer", value=f"{message.author} (`{message.author.id}`)", inline=False)
        e.add_field(name="Item", value=pending["item"], inline=True)
        e.add_field(name="Price", value=f"${pending['price']:g}", inline=True)
        e.add_field(name="Code Submitted", value=f"||{code}||", inline=False)
        e.set_footer(text="Verify the code before delivering the order")

        gconf = config.get(matched_gid, {})
        log_channel_id = gconf.get("log_channel")
        if log_channel_id:
            channel = guild.get_channel(int(log_channel_id))
            if channel:
                try:
                    await channel.send(embed=e)
                    return
                except discord.Forbidden:
                    pass

        owner = guild.owner
        if owner:
            try:
                await owner.send(embed=e)
            except discord.Forbidden:
                pass

    # ── /payembed ─────────────────────────────────────────────
    @app_commands.command(name="payembed", description="Post a product embed with a Buy Now button")
    @app_commands.describe(
        item="Item/service name",
        price="Price in USD (e.g. 10 or 17.50)",
        description="Extra description/details (optional)",
        image_url="Image URL for the embed (optional)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def payembed(self, interaction: discord.Interaction, item: str, price: float, description: str = "", image_url: str = ""):
        e = discord.Embed(title=item, description=description or "Click the button below to purchase!", color=discord.Color.gold())
        e.add_field(name="Price", value=f"${price:g}", inline=True)
        if image_url:
            e.set_image(url=image_url)
        e.set_footer(text="Click Buy Now to get payment instructions in your DMs")

        view = BuyView(self.bot, item_name=item, price=price, guild_id=interaction.guild.id)
        await interaction.channel.send(embed=e, view=view)
        await interaction.response.send_message("✅ Product embed posted.", ephemeral=True)

    # ── /paysetup ─────────────────────────────────────────────
    paysetup_group = app_commands.Group(name="paysetup", description="Configure the payment system")

    @paysetup_group.command(name="addlink", description="Add or update a G2A gift card denomination link")
    @app_commands.describe(amount="Dollar amount of the card (e.g. 30)", url="The G2A link for that denomination")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def paysetup_addlink(self, interaction: discord.Interaction, amount: float, url: str):
        config = load_json(CONFIG_FILE)
        gid = str(interaction.guild.id)
        config.setdefault(gid, {}).setdefault("denominations", dict(DEFAULT_DENOMINATIONS))
        config[gid]["denominations"][str(amount)] = url
        save_json(CONFIG_FILE, config)
        await interaction.response.send_message(f"✅ Added the ${amount:g} card link.", ephemeral=True)

    @paysetup_group.command(name="removelink", description="Remove a G2A gift card denomination")
    @app_commands.describe(amount="Dollar amount of the card to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def paysetup_removelink(self, interaction: discord.Interaction, amount: float):
        config = load_json(CONFIG_FILE)
        gid = str(interaction.guild.id)
        denoms = config.get(gid, {}).get("denominations", {})
        removed = denoms.pop(str(amount), None)
        save_json(CONFIG_FILE, config)
        if removed:
            await interaction.response.send_message(f"✅ Removed the ${amount:g} card link.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ No card link found for that amount.", ephemeral=True)

    @paysetup_group.command(name="listlinks", description="View all configured G2A gift card denomination links")
    async def paysetup_listlinks(self, interaction: discord.Interaction):
        denoms = get_denominations(str(interaction.guild.id))
        sorted_items = sorted(denoms.items(), key=lambda x: float(x[0]))
        lines = [f"**${amt}** — {url}" for amt, url in sorted_items]
        e = discord.Embed(title="🎁 G2A Gift Card Links", description="\n".join(lines), color=discord.Color.gold())
        await interaction.response.send_message(embed=e, ephemeral=True)

    @paysetup_group.command(name="logchannel", description="Set the channel where submitted payment codes get sent")
    @app_commands.describe(channel="Channel for payment submissions (leave blank to fall back to DMing you)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def paysetup_logchannel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        config = load_json(CONFIG_FILE)
        gid = str(interaction.guild.id)
        config.setdefault(gid, {})
        if channel:
            config[gid]["log_channel"] = str(channel.id)
            await interaction.response.send_message(f"✅ Payment submissions will be sent to {channel.mention}", ephemeral=True)
        else:
            config[gid].pop("log_channel", None)
            await interaction.response.send_message("✅ Payment submissions will be DMed to you (the server owner).", ephemeral=True)
        save_json(CONFIG_FILE, config)

    @paysetup_group.command(name="log", description="View recent payment submissions")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def paysetup_log(self, interaction: discord.Interaction):
        log = load_json(LOG_FILE).get(str(interaction.guild.id), [])
        if not log:
            return await interaction.response.send_message("No payment submissions logged yet.", ephemeral=True)
        recent = log[-10:]
        lines = [f"**{p['item']}** — ${p['price']:g} — {p['username']} — {p['time'][:16]}" for p in reversed(recent)]
        e = discord.Embed(title="💰 Recent Payment Submissions", description="\n".join(lines), color=discord.Color.gold())
        e.set_footer(text="Codes are hidden here — check the payment log channel/DMs for the actual code")
        await interaction.response.send_message(embed=e, ephemeral=True)


async def setup(bot):
    await bot.add_cog(PayEmbed(bot))