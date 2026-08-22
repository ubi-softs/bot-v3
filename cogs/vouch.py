import discord
from discord import app_commands
from discord.ext import commands

VOUCH_CHANNEL_ID = 1539877661898313728


class VouchModal(discord.ui.Modal, title="Leave Feedback"):
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
        # Validate the star rating
        try:
            rating = int(str(self.stars.value).strip())
        except ValueError:
            return await interaction.response.send_message("❌ Rating must be a whole number from 1 to 5.", ephemeral=True)

        if rating < 1 or rating > 5:
            return await interaction.response.send_message("❌ Rating must be between 1 and 5.", ephemeral=True)

        stars_display = "🌟" * rating

        channel = self.bot.get_channel(VOUCH_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(VOUCH_CHANNEL_ID)
            except Exception:
                return await interaction.response.send_message(
                    "❌ Couldn't find the vouch channel. Ask an admin to check the channel ID/permissions.", ephemeral=True
                )

        message = (
            "**FEEDBACK RECEIVED**\n\n"
            "How satisfied?\n"
            f"{stars_display}\n\n"
            "What was purchased?\n"
            f"\u201c{self.purchased.value}\u201d\n\n"
            "Description by buyer\n"
            f"{self.description.value}"
        )

        try:
            await channel.send(message)
        except discord.Forbidden:
            return await interaction.response.send_message("❌ I don't have permission to post in the vouch channel.", ephemeral=True)

        await interaction.response.send_message("✅ Thanks for your feedback! It's been posted.", ephemeral=True)


class Vouch(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="vouch", description="Leave feedback / a vouch for your purchase")
    async def vouch(self, interaction: discord.Interaction):
        await interaction.response.send_modal(VouchModal(self.bot))


async def setup(bot):
    await bot.add_cog(Vouch(bot))