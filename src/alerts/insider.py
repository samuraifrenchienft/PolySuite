"""Insider/Weird Activity Detection for Polymarket.

Detects patterns that suggest informed trading:
- Fresh wallets making large trades
- Unusual sizing relative to market
- Niche market activity
"""

import requests
from typing import List, Dict, Optional
from datetime import datetime, timedelta


class InsiderDetector:
    """Detect potential insider trading activity."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

    def check_wallet_freshness(self, address: str) -> Dict:
        """Check if wallet is new (created recently)."""
        try:
            # Get closed positions to estimate wallet age
            resp = self.session.get(
                "https://data-api.polymarket.com/closed-positions",
                params={"user": address, "limit": 1},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 0:
                    # If only 1-5 total trades, likely new
                    return {
                        "is_fresh": len(data) < 10,
                        "total_trades": len(data),
                        "risk": "HIGH"
                        if len(data) < 5
                        else "MEDIUM"
                        if len(data) < 10
                        else "LOW",
                    }
        except Exception:
            pass
        return {"is_fresh": None, "total_trades": 0, "risk": "UNKNOWN"}

    def check_trade_size_vs_market(
        self, trade_size: float, market_volume: float
    ) -> Dict:
        """Check if trade size is unusually large for market."""
        if market_volume <= 0:
            return {"size_ratio": None, "risk": "UNKNOWN"}

        ratio = trade_size / market_volume

        # If trade is > 10% of market volume, suspicious
        if ratio > 0.1:
            risk = "HIGH"
        elif ratio > 0.05:
            risk = "MEDIUM"
        elif ratio > 0.01:
            risk = "LOW"
        else:
            risk = "NORMAL"

        return {
            "size_ratio": ratio,
            "risk": risk,
            "description": f"Trade is {ratio * 100:.1f}% of market volume",
        }

    def check_market_niche(self, market_volume: float, category: str = None) -> Dict:
        """Check if market is niche/low-volume."""
        if market_volume < 1000:
            risk = "HIGH"
            description = "Very low volume - niche market"
        elif market_volume < 10000:
            risk = "MEDIUM"
            description = "Low volume market"
        elif market_volume < 100000:
            risk = "LOW"
            description = "Moderate volume"
        else:
            risk = "NORMAL"
            description = "Liquid market"

        return {"volume": market_volume, "risk": risk, "description": description}

    def analyze_trade(self, wallet_address: str, trade: Dict, market: Dict) -> Dict:
        """Full analysis of a single trade for insider indicators."""
        trade_size = float(trade.get("size", 0) or 0)
        market_volume = float(market.get("volume", 0) or 0)

        # Check each signal
        freshness = self.check_wallet_freshness(wallet_address)
        size_check = self.check_trade_size_vs_market(trade_size, market_volume)
        niche_check = self.check_market_niche(market_volume)

        # Calculate overall risk score
        risk_scores = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "NORMAL": 0, "UNKNOWN": 0}

        total_score = (
            risk_scores.get(freshness.get("risk", "UNKNOWN"), 0)
            + risk_scores.get(size_check.get("risk", "UNKNOWN"), 0)
            + risk_scores.get(niche_check.get("risk", "UNKNOWN"), 0)
        )

        if total_score >= 7:
            overall_risk = "CRITICAL"
        elif total_score >= 5:
            overall_risk = "HIGH"
        elif total_score >= 3:
            overall_risk = "MEDIUM"
        else:
            overall_risk = "LOW"

        return {
            "wallet": wallet_address,
            "trade_size": trade_size,
            "market_volume": market_volume,
            "signals": {
                "fresh_wallet": freshness,
                "unusual_size": size_check,
                "niche_market": niche_check,
            },
            "risk_score": total_score,
            "overall_risk": overall_risk,
            "alerts": self._generate_alerts(freshness, size_check, niche_check),
        }

    def _generate_alerts(self, freshness: Dict, size: Dict, niche: Dict) -> List[str]:
        """Generate human-readable alerts."""
        alerts = []

        if freshness.get("risk") == "HIGH":
            alerts.append(
                f"⚠️ FRESH WALLET: Only {freshness.get('total_trades')} total trades"
            )

        if size.get("risk") == "HIGH":
            alerts.append(f"💰 LARGE TRADE: {size.get('description')}")
        elif size.get("risk") == "MEDIUM":
            alerts.append(f"💵 Notable trade size")

        if niche.get("risk") in ["HIGH", "MEDIUM"]:
            alerts.append(f"📍 NICHE MARKET: {niche.get('description')}")

        return alerts

    def scan_wallet_for_anomalies(self, address: str) -> Dict:
        """Scan a wallet for suspicious activity patterns."""
        try:
            # Get current positions
            resp = self.session.get(
                "https://data-api.polymarket.com/positions",
                params={"user": address},
                timeout=10,
            )
            positions = resp.json() if resp.status_code == 200 else []

            # Get closed positions for trade history
            resp2 = self.session.get(
                "https://data-api.polymarket.com/closed-positions",
                params={"user": address, "limit": 20},
                timeout=10,
            )
            closed = resp2.json() if resp2.status_code == 200 else []

            # Analyze
            freshness = self.check_wallet_freshness(address)

            return {
                "address": address,
                "is_suspicious": freshness.get("risk") in ["HIGH", "MEDIUM"],
                "freshness": freshness,
                "positions_count": len(positions),
                "closed_count": len(closed),
                "recommendation": "MONITOR"
                if freshness.get("risk") == "HIGH"
                else "OK",
            }
        except Exception as e:
            return {"error": str(e)}


def check_token_honeypot(token_address: str, chain: str = "polygon") -> Dict:
    """Check if a token might be a honeypot.

    Note: This is basic - real honeypot detection requires on-chain simulation.
    """
    return {
        "address": token_address,
        "chain": chain,
        "is_honeypot": None,
        "risk": "UNKNOWN",
        "note": "Advanced honeypot detection not implemented - requires on-chain simulation",
    }
