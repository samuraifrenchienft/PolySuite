"""Discord Chat Bot for Prediction Suite.

Uses Groq AI for conversation - replaces shady Telegram bots.
"""

import os
import requests
from discord import app_commands, Client, Intents, Message
from dotenv import load_dotenv

load_dotenv()

# System prompt for chat
CHAT_SYSTEM_PROMPT = """You are Prediction Suite AI Assistant, a helpful AI for prediction markets (Polymarket, Kalshi, Jupiter).

You help users understand:
- How prediction markets work
- Market sentiment and trends
- Wallet tracking and smart money
- Arbitrage opportunities

Rules:
- Be helpful and friendly
- Don't give financial advice
- Stay focused on prediction markets
- Use simple language
- Keep responses concise"""


class DiscordChatBot:
    """Discord bot with AI chat using Groq."""

    def __init__(self):
        self.token = os.getenv("Discord_bot_token")
        self.groq_key = os.getenv("Groq_api_key") or os.getenv("GROQ_API_KEY")
        self.groq_url = "https://api.groq.com/openai/v1"
        self.model = "llama-3.3-70b-versatile"
        
        # Fallback to OpenRouter
        self.openrouter_key = os.getenv("Openrouter_api_key") or os.getenv("OPENROUTER_API_KEY")
        
        self.client = Client(intents=Intents.default())
        self.tree = app_commands.CommandTree(self.client)

    def _call_ai(self, message: str) -> str:
        """Call AI to get response."""
        # Try Groq first
        if self.groq_key:
            try:
                resp = requests.post(
                    f"{self.groq_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.groq_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
                            {"role": "user", "content": message}
                        ],
                        "temperature": 0.7,
                        "max_tokens": 500,
                    },
                    timeout=30
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"[Chat] Groq error: {e}")

        # Fallback to OpenRouter
        if self.openrouter_key:
            try:
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.openrouter_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "qwen/qwen3-vl-30b-a3b-thinking",
                        "messages": [
                            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
                            {"role": "user", "content": message}
                        ],
                    },
                    timeout=30
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"[Chat] OpenRouter error: {e}")

        return "AI temporarily unavailable. Try again later."

    async def on_message(self, message: Message):
        """Handle incoming messages."""
        # Ignore bot messages
        if message.author.bot:
            return
        
        # Check if mentioned or DM
        if self.client.user in message.mentions or isinstance(message.channel, type(None)):
            return

        # Simple trigger - respond to any message in designated channels
        # Or use mention @PredictionSuite
        
        # For now, respond to DMs
        if isinstance(message.channel, ):
            async message.channel.typing()
            response = self._call_ai(message.content)
            await message.reply(response[:2000])  # Discord limit

    async def setup(self):
        """Setup bot commands."""
        @self.tree.command(name="chat", description="Chat with Prediction Suite AI")
        async def chat(interaction, message: str):
            await interaction.response.defer()
            response = self._call_ai(message)
            await interaction.followup.send(response[:2000])

        @self.tree.command(name="help", description="Get help with Prediction Suite")
        async def help_cmd(interaction):
            await interaction.response.send_message(
                "**Prediction Suite Commands:**\n"
                "/chat [message] - Chat with AI\n"
                "/help - Show this message\n"
                "/markets - View active markets\n"
                "/add [wallet] - Track a wallet\n"
                "/scan [wallet] - Scan wallet positions",
                ephemeral=True
            )

    def run(self):
        """Run the bot."""
        @self.client.event
        async def on_ready():
            print(f"Logged in as {self.client.user}")
            await self.setup()
            await self.tree.sync()
            print("Commands synced")

        @self.client.event
        async def on_message(message):
            await self.on_message(message)

        print("Starting Discord Chat Bot...")
        self.client.run(self.token)


if __name__ == "__main__":
    bot = DiscordChatBot()
    bot.run()
