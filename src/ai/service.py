"""AI client for Prediction Suite using Groq (free, unlimited)."""

import os
import requests
from typing import Optional


SYSTEM_PROMPT = """You are Prediction Suite AI, an expert analyst for prediction markets (Polymarket, Kalshi, Jupiter).

Rules:
1. Be concise - Maximum 2-3 sentences
2. Use simple language
3. Stay focused on prediction markets
4. No financial advice
5. Use emojis: 🐂 bullish, 🐻 bearish, ➡️ neutral

Format:
Sentiment: [BULLISH/BEARISH/NEUTRAL]
Summary: [2-3 sentences max]"""


class GroqClient:
    """Free AI client using Groq API."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.base_url = "https://api.groq.com/openai/v1"
        self.model = "llama-3.3-70b-versatile"  # Free, fast

    def _call(self, prompt: str) -> Optional[str]:
        """Make API call to Groq."""
        if not self.api_key:
            return None

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 200,
                },
                timeout=30,
            )

            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            else:
                print(f"[Groq] Error: {response.status_code} - {response.text[:100]}")
                return None

        except Exception as e:
            print(f"[Groq] Exception: {e}")
            return None

    def analyze_market(
        self, question: str, current_price: float = None, volume: float = None
    ) -> str:
        """Analyze market sentiment."""
        prompt = f"Analyze this prediction market: '{question}'"
        if current_price:
            prompt += f" Current price: {current_price}"
        if volume:
            prompt += f" Volume: ${volume:,.0f}"
        prompt += "\nWhat is the sentiment?"

        return self._call(prompt) or "AI unavailable"

    def explain_wallet(self, trades: list) -> str:
        """Explain what a wallet is doing."""
        prompt = f"Analyze these trades: {trades}\nWhat is this wallet's strategy?"
        return self._call(prompt) or "AI unavailable"

    def summarize_markets(self, markets: list) -> str:
        """Summarize multiple markets."""
        prompt = f"Summarize these prediction markets in 2-3 sentences:\n{markets}"
        return self._call(prompt) or "AI unavailable"


class OpenRouterClient:
    """Backup AI client using OpenRouter (50 calls/day free)."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.base_url = "https://openrouter.ai/api/v1"
        self.model = "deepseek/deepseek-r1-0528:free"

    def _call(self, prompt: str) -> Optional[str]:
        if not self.api_key:
            return None

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=30,
            )

            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            return None
        except Exception as e:
            print(f"[OpenRouter] Error: {e}")
            return None

    def analyze_market(
        self, question: str, current_price: float = None, volume: float = None
    ) -> str:
        prompt = f"Analyze: '{question}'"
        if current_price:
            prompt += f" Price: {current_price}"
        return self._call(prompt) or "AI unavailable"

    def explain_wallet(self, trades: list) -> str:
        return self._call(f"Explain: {trades}") or "AI unavailable"

    def summarize_markets(self, markets: list) -> str:
        return self._call(f"Summarize: {markets}") or "AI unavailable"


class AIService:
    """Multi-source AI - tries Groq first, falls back to OpenRouter."""

    def __init__(self):
        self.groq = GroqClient()
        self.openrouter = OpenRouterClient()

    def analyze_market(
        self, question: str, current_price: float = None, volume: float = None
    ) -> str:
        # Try Groq first (unlimited)
        result = self.groq.analyze_market(question, current_price, volume)
        if result and result != "AI unavailable":
            return result

        # Fallback to OpenRouter
        result = self.openrouter.analyze_market(question, current_price, volume)
        if result and result != "AI unavailable":
            return result

        return "AI unavailable - all services down"

    def explain_wallet(self, trades: list) -> str:
        result = self.groq.explain_wallet(trades)
        if result and result != "AI unavailable":
            return result
        return self.openrouter.explain_wallet(trades) or "AI unavailable"

    def summarize_markets(self, markets: list) -> str:
        result = self.groq.summarize_markets(markets)
        if result and result != "AI unavailable":
            return result
        return self.openrouter.summarize_markets(markets) or "AI unavailable"


# Singleton
ai_service = AIService()
