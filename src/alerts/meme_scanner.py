"""Meme Coin Scanner - Lute-style CA analysis.

Scans token contract addresses for safety analysis.
"""

import requests
from typing import Dict, Optional


class MemeCoinScanner:
    """Scan meme coin contracts for safety analysis."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )

    def scan_token(self, token_address: str) -> Dict:
        """Scan a token contract address for safety analysis."""
        try:
            # Try DexScreener first (most reliable)
            dexscreener_data = self._get_dexscreener(token_address)

            # Get basic token info
            token_info = self._get_token_info(token_address)

            # Build result
            result = {
                "address": token_address,
                "dexscreener": dexscreener_data,
                "token_info": token_info,
                "safety": self._assess_safety(dexscreener_data, token_info),
                "links": self._build_links(token_address),
            }

            return result

        except Exception as e:
            return {"error": str(e), "address": token_address}

    def _get_dexscreener(self, address: str) -> Dict:
        """Get token data from DexScreener."""
        try:
            # Try direct pair search by address
            resp = self.session.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{address}", timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("pairs") and len(data["pairs"]) > 0:
                    pair = data["pairs"][0]
                    return {
                        "found": True,
                        "pair": pair,
                        "price": pair.get("priceUsd"),
                        "liquidity": pair.get("liquidity", {}),
                        "volume24h": pair.get("volume", {}).get("h24"),
                        "priceChange24h": pair.get("priceChange", {}).get("h24"),
                        "fdv": pair.get("fdv"),  # Fully diluted valuation
                        "pair_address": pair.get("pairAddress"),
                        "dex": pair.get("dexId"),
                        "base_token": pair.get("baseToken", {}),
                        "quote_token": pair.get("quoteToken", {}),
                    }
            return {"found": False}
        except Exception as e:
            return {"found": False, "error": str(e)}

    def _get_token_info(self, address: str) -> Dict:
        """Get basic token info from different sources."""
        info = {"holders": None, "total_supply": None, "verified": False}

        # Try to get from DexScreener if not found above
        try:
            resp = self.session.get(
                f"https://api.dexscreener.com/token-insights/{address}/latest",
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                info["holders"] = data.get("holderCount")
                info["total_supply"] = data.get("totalSupply")
        except:
            pass

        return info

    def _assess_safety(self, dexscreener: Dict, token_info: Dict) -> Dict:
        """Assess token safety based on available data."""
        risk_factors = []
        safety_score = 100

        if not dexscreener.get("found"):
            return {
                "score": 0,
                "risk": "UNKNOWN",
                "factors": ["Token not found on DexScreener"],
            }

        # Check liquidity
        liquidity = dexscreener.get("liquidity", {})
        usd_liquidity = liquidity.get("usd", 0) if isinstance(liquidity, dict) else 0
        if usd_liquidity < 1000:
            risk_factors.append("⚠️ Very low liquidity (less than $1K)")
            safety_score -= 40
        elif usd_liquidity < 10000:
            risk_factors.append("⚡ Low liquidity (less than $10K)")
            safety_score -= 20

        # Check 24h volume
        volume = dexscreener.get("volume24h", 0)
        if volume and volume > 0:
            # High volume is good
            if volume < 1000:
                risk_factors.append("📉 Very low 24h volume")
                safety_score -= 15
        else:
            risk_factors.append("❓ No volume data")
            safety_score -= 10

        # Check price change (extreme changes are suspicious)
        price_change = dexscreener.get("priceChange24h", 0)
        if price_change:
            if abs(price_change) > 50:
                risk_factors.append(f"📊 Extreme price change: {price_change:+.1f}%")
                safety_score -= 20
            elif abs(price_change) > 25:
                risk_factors.append(f"⚡ Large price change: {price_change:+.1f}%")
                safety_score -= 10

        # Check FDV vs liquidity (if FDV is way higher than liquidity, could be red flag)
        fdv = dexscreener.get("fdv")
        if fdv and usd_liquidity:
            ratio = fdv / usd_liquidity if usd_liquidity > 0 else 0
            if ratio > 100:
                risk_factors.append(f"⚠️ FDV/Liquidity ratio very high ({ratio:.0f}x)")
                safety_score -= 15
            elif ratio > 50:
                risk_factors.append(f"⚡ High FDV/Liquidity ratio ({ratio:.0f}x)")
                safety_score -= 5

        # Determine overall risk
        if safety_score >= 80:
            risk = "LOW"
        elif safety_score >= 50:
            risk = "MEDIUM"
        elif safety_score >= 20:
            risk = "HIGH"
        else:
            risk = "CRITICAL"

        return {
            "score": max(0, safety_score),
            "risk": risk,
            "factors": risk_factors,
            "liquidity_usd": usd_liquidity,
        }

    def _build_links(self, address: str) -> Dict:
        """Build relevant links for the token."""
        return {
            "dexscreener": f"https://dexscreener.com/search?q={address}",
            "dextools": f"https://www.dextools.io/app/en/pair-explorer/{address}",
            "etherscan": f"https://etherscan.io/address/{address}"
            if len(address) == 42
            else None,
            "arbiscan": f"https://arbiscan.io/address/{address}"
            if len(address) == 42
            else None,
            "basescan": f"https://basescan.org/address/{address}"
            if len(address) == 42
            else None,
        }


def scan_contract_address(ca: str) -> Dict:
    """Quick function to scan a contract address."""
    scanner = MemeCoinScanner()
    return scanner.scan_token(ca)
