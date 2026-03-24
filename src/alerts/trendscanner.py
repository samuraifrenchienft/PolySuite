"""AI-powered trend scanner for meme coins and trends.

Monitors DexScreener trending tokens.
"""

import logging
import requests
from typing import List, Dict

logger = logging.getLogger(__name__)


class TrendScanner:
    """AI scanner for trending tokens."""

    def __init__(self, ai_filter=None):
        self.ai = ai_filter
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            }
        )

    def get_dexscreener_trending(self, limit: int = 15) -> List[Dict]:
        """Get trending Solana tokens from DexScreener (community takeovers + token boosts)."""
        tokens = []
        seen = set()

        # Community takeovers - trending tokens
        try:
            resp = self.session.get(
                "https://api.dexscreener.com/community-takeovers/latest/v1",
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in (data if isinstance(data, list) else [])[:limit]:
                    addr = item.get("tokenAddress")
                    if addr and addr not in seen:
                        seen.add(addr)
                        tokens.append({
                            "name": item.get("description", "")[:50] or "Unknown",
                            "symbol": "?",
                            "mint": addr,
                            "address": addr,
                            "source": "dexscreener_takeover",
                            "chainId": item.get("chainId", ""),
                        })
        except Exception as e:
            logger.debug("TrendScanner DexScreener takeovers error: %s", e)

        # Token boosts - promoted/trending
        try:
            resp = self.session.get(
                "https://api.dexscreener.com/token-boosts/latest/v1",
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in (data if isinstance(data, list) else [])[:limit]:
                    addr = item.get("tokenAddress")
                    if addr and addr not in seen:
                        seen.add(addr)
                        tokens.append({
                            "name": item.get("description", "")[:50] or "Unknown",
                            "symbol": "?",
                            "mint": addr,
                            "address": addr,
                            "source": "dexscreener_boost",
                            "chainId": item.get("chainId", ""),
                        })
        except Exception as e:
            logger.debug("TrendScanner DexScreener boosts error: %s", e)

        return tokens[:limit]

    def analyze_token(self, token: Dict) -> Dict:
        """Use AI to analyze if a token is worth alerting."""
        if not self.ai:
            return {"alert": False, "reason": "No AI"}

        try:
            name = token.get("name", "")
            symbol = token.get("symbol", "?")
            desc = token.get("description", "")[:100]

            prompt = f"""Analyze this token:
Name: {name}
Symbol: {symbol}
Desc: {desc}

Is this a potential scam, rug, or worth watching? Reply:
ALERT: [YES/NO]
REASON: [1 sentence]"""

            result = self.ai._call(prompt)
            if result and "ALERT: YES" in result.upper():
                return {"alert": True, "reason": result, "token": token}

            return {"alert": False, "reason": result[:100] if result else "No signal"}

        except Exception as e:
            logging.getLogger(__name__).exception("TrendScanner analyze_token error")
            return {"alert": False, "reason": "Analysis failed"}

    def scan_dexscreener_trending(self, limit: int = 10) -> List[Dict]:
        """Scan DexScreener trending tokens for alerts."""
        alerts = []
        tokens = self.get_dexscreener_trending(limit=limit)
        if tokens:
            logger.info(
                "TrendScanner: Found %s DexScreener trending tokens", len(tokens)
            )
        for token in tokens[:5]:
            if token.get("chainId") == "solana":
                analysis = self.analyze_token(token)
                if analysis.get("alert"):
                    alerts.append({
                        "type": "trending",
                        "source": "dexscreener",
                        "token": token,
                        "analysis": analysis,
                    })
        return alerts

    def scan_all(self) -> List[Dict]:
        """Scan all sources."""
        return self.scan_dexscreener_trending()


# Singleton - wire AI filter for token analysis
try:
    from src.ai.engine import ai_filter
    trendscanner = TrendScanner(ai_filter=ai_filter)
except ImportError:
    trendscanner = TrendScanner()
