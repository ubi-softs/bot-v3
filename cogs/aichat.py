"""
AI chat: mention the bot to start a conversation, reply to its message to
keep talking. Conversation history is tracked per-message-chain so multiple
people can have separate conversations with the bot at the same time.

Requires OPENAI_API_KEY to be set in your environment (Railway → Variables).
This is wired up for NVIDIA's OpenAI-compatible API (build.nvidia.com) since
that's where an `nvapi-...` key comes from. If you switch providers later
(OpenAI, Groq, etc.), only OPENAI_API_BASE / OPENAI_MODEL below need to change.

Conversation history is saved to disk (data/ai_conversations.json) so a
Railway restart/redeploy mid-conversation doesn't wipe people's chats.
"""
import discord
from discord.ext import commands
import aiohttp
import json
import os

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://integrate.api.nvidia.com/v1")
# 70B is noticeably better than 8B at actually using conversation history —
# override with a different model via the OPENAI_MODEL env var if you want.
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "meta/llama-3.1-70b-instruct")

SYSTEM_PROMPT = (
    "You are a friendly, helpful assistant for a Discord server that sells social "
    "media services. Keep replies concise and conversational, suitable for a Discord "
    "chat message (a few sentences, not an essay). Pay close attention to the "
    "conversation history provided and stay consistent with what's already been said."
)

MAX_HISTORY_MESSAGES = 12  # how many past turns to send back for context
MAX_REPLY_LENGTH = 1900    # stay under Discord's 2000 char limit
MAX_STORED_CONVERSATIONS = 500

CONVO_FILE = "data/ai_conversations.json"


def load_conversations() -> dict:
    if not os.path.exists(CONVO_FILE):
        return {}
    try:
        with open(CONVO_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_conversations(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(CONVO_FILE, "w") as f:
        json.dump(data, f)


class AIChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # str(message_id) -> list[{"role": "user"/"assistant", "content": str}]
        # keyed by the BOT's message ID so replies to it can find the thread
        self.conversations = load_conversations()

    async def _ask_ai(self, history: list[dict]) -> str:
        if not OPENAI_API_KEY:
            return "⚠️ AI chat isn't configured yet — an admin needs to set OPENAI_API_KEY."

        payload = {
            "model": OPENAI_MODEL,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + history,
            "max_tokens": 500,
        }
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

        async with aiohttp.ClientSession() as s:
            async with s.post(f"{OPENAI_API_BASE}/chat/completions", headers=headers, json=payload) as r:
                data = await r.json()
                if r.status != 200:
                    err = data.get("error", {}).get("message", str(data))
                    return f"⚠️ AI error: {err}"
                return data["choices"][0]["message"]["content"].strip()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        history = None

        # Case 1: someone @mentions the bot — start a new conversation
        if self.bot.user in message.mentions:
            user_text = message.content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()
            if not user_text:
                return  # just a bare ping with nothing to say, ignore
            history = [{"role": "user", "content": user_text}]

        # Case 2: someone replies to one of the bot's own messages — continue the conversation
        elif message.reference and str(message.reference.message_id) in self.conversations:
            history = list(self.conversations[str(message.reference.message_id)])
            history.append({"role": "user", "content": message.content})

        if history is None:
            return

        # Trim to the most recent turns so the request doesn't grow unbounded
        history = history[-MAX_HISTORY_MESSAGES:]

        async with message.channel.typing():
            reply_text = await self._ask_ai(history)

        if len(reply_text) > MAX_REPLY_LENGTH:
            reply_text = reply_text[:MAX_REPLY_LENGTH] + "…"

        bot_message = await message.reply(reply_text, mention_author=False)

        history.append({"role": "assistant", "content": reply_text})
        self.conversations[str(bot_message.id)] = history

        # Basic cleanup so this doesn't grow forever, then persist to disk
        if len(self.conversations) > MAX_STORED_CONVERSATIONS:
            oldest_key = next(iter(self.conversations))
            self.conversations.pop(oldest_key, None)
        save_conversations(self.conversations)


async def setup(bot):
    await bot.add_cog(AIChat(bot))