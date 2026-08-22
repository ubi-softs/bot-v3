import discord
from discord import app_commands
from discord.ext import commands
import datetime

VOUCH_CHANNEL_ID = 1539877661898313728
PINK = discord.Color.from_rgb(255, 105, 180)  # hot pink sidebar


class VouchModal(discord.ui.Modal, title="Leave a Vouch"):
    stars = discord.ui.TextInput(
        label="How satisfied? (1-5)",
        placeholder="Enter a number from 1 to 5",
        min_length=1,
        max_length=1,
        required=True,
    )
    purchased = discord.ui.TextInput(
        label="What was purchased?",
        placeholder="e.g. Social Media Services",
        max_length=100,
        required=True,
    )
    description = discord.ui.TextInput(
        label="Description",
        placeholder="What went well about it?",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        try:
            rating = int(str(self.stars.value).strip())
        except ValueError:
            return await interaction.response.send_message("❌ Rating must be a whole number from 1 to 5.", ephemeral=True)

        if rating < 1 or rating > 5:
            return await interaction.response.send_message("❌ Rating must be between 1 and 5.", ephemeral=True)

        channel = self.bot.get_channel(VOUCH_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(VOUCH_CHANNEL_ID)
            except Exception:
                return await interaction.response.send_message(
                    "❌ Couldn't find the vouch channel. Ask an admin to check the channel ID/permissions.", ephemeral=True
                )

        stars_display = "🌟" * rating + "☆" * (5 - rating)

        e = discord.Embed(color=PINK, timestamp=datetime.datetime.utcnow())
        e.title = "✅ Feedback Received"
        e.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        e.add_field(name="How satisfied?", value=stars_display, inline=False)
        e.add_field(name="What was purchased?", value=f"\u201c{self.purchased.value}\u201d", inline=False)
        e.add_field(name="Description by buyer", value=self.description.value, inline=False)
        e.set_footer(text=f"Vouched by {interaction.user.display_name} • ID: {interaction.user.id}")
        e.set_thumbnail(url=interaction.user.display_avatar.url)

        try:
            await channel.send(content=f"🌟 New vouch from {interaction.user.mention}!", embed=e)
        except discord.Forbidden:
            return await interaction.response.send_message("❌ I don't have permission to post in the vouch channel.", ephemeral=True)

        await interaction.response.send_message("✅ Thanks for your feedback! It's been posted.", ephemeral=True)


class Vouch(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="vouch", description="Leave a vouch / feedback for your purchase")
    async def vouch(self, interaction: discord.Interaction):
        await interaction.response.send_modal(VouchModal(self.bot))


async def setup(bot):
    await bot.add_cog(Vouch(bot))