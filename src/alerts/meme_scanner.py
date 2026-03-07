"""Meme Coin Scanner - Lute-style CA analysis.

Scans token contract addresses for safety analysis.
"""

import logging
import requests
import time
from typing import Dict, Optional


class MemeCoinScanner:
    """Scan meme coin contracts for safety analysis."""

    def __init__(self, cache_ttl: int = 120):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        self.cache = {}
        self.cache_ttl = cache_ttl  # Cache for 2 minutes

    def _get_cached(self, key: str) -> Optional[Dict]:
        """Get from cache if not expired."""
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.cache_ttl:
                return value
            del self.cache[key]
        return None

    def _set_cache(self, key: str, value: Dict):
        """Set cache with timestamp."""
        self.cache[key] = (value, time.time())

    def scan_token(self, token_address: str) -> Dict:
        """Scan a token contract address for safety analysis."""
        try:
            # Normalize address for APIs
            addr = (
                token_address
                if token_address.startswith("0x")
                else f"0x{token_address}"
            )

            # Check cache first
            cache_key = f"scan:{addr.lower()}"
            cached = self._get_cached(cache_key)
            if cached:
                cached["cached"] = True
                return cached

            # Try DexScreener first (most reliable)
            dexscreener_data = self._get_dexscreener(addr)

            # Get basic token info
            token_info = self._get_token_info(addr)

            # Honeypot check via Honeypot.is (free, no API key)
            honeypot_data = self._get_honeypot_check(addr)

            # Build result
            result = {
                "address": token_address,
                "dexscreener": dexscreener_data,
                "token_info": token_info,
                "honeypot": honeypot_data,
                "safety": self._assess_safety(
                    dexscreener_data, token_info, honeypot_data
                ),
                "links": self._build_links(token_address),
            }

            # Cache the result
            self._set_cache(cache_key, result)

            result["cached"] = False
            return result

        except Exception as e:
            logging.getLogger(__name__).exception("MemeScanner scan_token error")
            return {"error": "Scan failed", "address": token_address}

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
            logging.getLogger(__name__).exception("MemeScanner DexScreener error")
            return {"found": False, "error": "Data fetch failed"}

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
        except Exception as e:
            print(f"[MemeScanner] token-insights error: {e}")

        return info

    def _get_honeypot_check(self, address: str, chain_id: int = 137) -> Dict:
        """Check if token is honeypot via Honeypot.is API (free, no key)."""
        try:
            resp = self.session.get(
                "https://api.honeypot.is/v2/IsHoneypot",
                params={"address": address, "chainID": chain_id},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                summary = data.get("summary", {})
                hp = data.get("honeypotResult", {})
                sim = data.get("simulationResult", {})
                token = data.get("token", {})
                return {
                    "is_honeypot": hp.get("isHoneypot", False),
                    "reason": hp.get("honeypotReason"),
                    "risk": summary.get("risk", "unknown"),
                    "risk_level": summary.get("riskLevel"),
                    "total_holders": token.get("totalHolders"),
                    "buy_tax": sim.get("buyTax"),
                    "sell_tax": sim.get("sellTax"),
                    "simulation_success": data.get("simulationSuccess", False),
                }
        except Exception as e:
            logging.getLogger(__name__).exception("MemeScanner honeypot check error")
            return {"error": "Honeypot check failed", "is_honeypot": None}
        return {"is_honeypot": None}

    def _assess_safety(
        self, dexscreener: Dict, token_info: Dict, honeypot: Dict = None
    ) -> Dict:
        """Assess token safety based on available data."""
        risk_factors = []
        safety_score = 100

        if not dexscreener.get("found"):
            return {
                "score": 0,
                "risk": "UNKNOWN",
                "factors": ["Token not found on DexScreener"],
            }

        # Honeypot check (highest priority)
        if honeypot:
            if honeypot.get("is_honeypot") is True:
                risk_factors.append("🚨 HONEYPOT - Cannot sell")
                safety_score -= 60
            elif honeypot.get("risk") in ("very_high", "honeypot"):
                risk_factors.append("⚠️ Very high honeypot risk")
                safety_score -= 40
            elif honeypot.get("risk") == "high":
                risk_factors.append("⚡ High honeypot risk")
                safety_score -= 25
            elif honeypot.get("risk") == "medium":
                risk_factors.append("📊 Medium honeypot risk")
                safety_score -= 10
            buy_tax = honeypot.get("buy_tax")
            sell_tax = honeypot.get("sell_tax")
            if buy_tax is not None and buy_tax > 5:
                risk_factors.append(f"📈 Buy tax: {buy_tax:.0f}%")
                safety_score -= 5
            if sell_tax is not None and sell_tax > 5:
                risk_factors.append(f"📉 Sell tax: {sell_tax:.0f}%")
                safety_score -= 10

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

        out = {
            "score": max(0, safety_score),
            "risk": risk,
            "factors": risk_factors,
            "liquidity_usd": usd_liquidity,
        }
        if honeypot:
            out["honeypot"] = honeypot.get("is_honeypot")
            out["honeypot_risk"] = honeypot.get("risk")
            out["buy_tax"] = honeypot.get("buy_tax")
            out["sell_tax"] = honeypot.get("sell_tax")
            out["total_holders"] = honeypot.get("total_holders")
        return out

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
