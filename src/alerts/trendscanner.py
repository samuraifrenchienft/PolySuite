"""AI-powered trend scanner for meme coins and trends.

Monitors:
- pump.fun new launches
- DexScreener trending (when available)
"""

import os
import requests
from typing import List, Dict
from datetime import datetime


class TrendScanner:
    """AI scanner for trending tokens and new launches."""

    def __init__(self, ai_filter=None):
        self.ai = ai_filter
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Origin": "https://pump.fun",
            }
        )

    def get_pumpfun_new(self, limit: int = 10) -> List[Dict]:
        """Get new tokens from pump.fun."""
        try:
            resp = self.session.get(
                "https://frontend-api-v3.pump.fun/coins",
                params={"limit": limit},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            print(f"[TrendScanner] pump.fun error: {e}")
        return []

    def get_pumpfun_graduated(self, limit: int = 10) -> List[Dict]:
        """Get graduated tokens from pump.fun."""
        try:
            resp = self.session.get(
                "https://frontend-api-v3.pump.fun/coins/graduated",
                params={"limit": limit},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return []

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
            return {"alert": False, "reason": str(e)[:50]}

    def scan_new_tokens(self, limit: int = 20) -> List[Dict]:
        """Scan new pump.fun tokens for alerts."""
        alerts = []

        tokens = self.get_pumpfun_new(limit)
        print(f"[TrendScanner] Found {len(tokens)} new tokens")

        for token in tokens[:10]:  # Check top 10
            analysis = self.analyze_token(token)
            if analysis.get("alert"):
                alerts.append(
                    {
                        "type": "new_token",
                        "source": "pump.fun",
                        "token": token,
                        "analysis": analysis,
                    }
                )

        return alerts

    def scan_graduated(self, limit: int = 10) -> List[Dict]:
        """Scan graduated tokens (higher quality)."""
        alerts = []

        tokens = self.get_pumpfun_graduated(limit)
        print(f"[TrendScanner] Found {len(tokens)} graduated tokens")

        for token in tokens[:5]:
            analysis = self.analyze_token(token)
            if analysis.get("alert"):
                alerts.append(
                    {
                        "type": "graduated",
                        "source": "pump.fun",
                        "token": token,
                        "analysis": analysis,
                    }
                )

        return alerts

    def scan_all(self) -> List[Dict]:
        """Scan all sources."""
        alerts = []
        alerts.extend(self.scan_new_tokens())
        alerts.extend(self.scan_graduated())
        return alerts


# Singleton
trendscanner = TrendScanner()
