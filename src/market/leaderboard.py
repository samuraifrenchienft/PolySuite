"""Leaderboard importer for PolySuite."""

import logging
from typing import List, Dict, Optional

import requests

from src.market.api import APIClientFactory

logger = logging.getLogger(__name__)


class LeaderboardImporter:
    """Import top traders from various sources."""

    def __init__(self, api_factory: APIClientFactory = None):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        self.api_factory = api_factory
        self._polymarket_api = None
        self._predictfolio_client = None
        self._jupiter_client = None

    @property
    def polymarket_api(self):
        if self._polymarket_api is None and self.api_factory:
            self._polymarket_api = self.api_factory.get_polymarket_api()
        return self._polymarket_api

    @property
    def predictfolio_client(self):
        if self._predictfolio_client is None and self.api_factory:
            self._predictfolio_client = self.api_factory.get_predictfolio_client()
        return self._predictfolio_client

    @property
    def jupiter_client(self):
        if self._jupiter_client is None and self.api_factory:
            self._jupiter_client = self.api_factory.get_jupiter_prediction_client()
        return self._jupiter_client

    def fetch_leaderboard(self, limit: int = 50) -> List[Dict]:
        """Fetch the latest leaderboard from public sources.

        Sources:
        - Polymarket Data API (Ethereum proxy wallets, 0x...).
        - Jupiter *prediction markets* API (prediction-market-api.jup.ag) — NOT Jupiter token swap/DEX.
        Merged and deduped by address; Solana pubkeys from Jupiter are skipped by auto-discovery
        (collector only adds 0x addresses today).
        """
        all_wallets = {}

        try:
            resp = requests.get(
                "https://data-api.polymarket.com/v1/leaderboard",
                params={"category": "OVERALL", "limit": limit},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    for w in data:
                        addr = w.get("proxyWallet") or w.get("address")
                        if addr:
                            w["address"] = addr
                            w["source"] = "polymarket"
                            if w.get("userName") and not w.get("username"):
                                w["username"] = w["userName"]
                            all_wallets[addr] = w
                    logger.info("Leaderboard: fetched %d from Polymarket", len(all_wallets))
        except Exception as e:
            logger.warning("Leaderboard Polymarket fetch failed: %s", e)

        try:
            resp = requests.get(
                "https://prediction-market-api.jup.ag/api/v1/leaderboards",
                params={"limit": limit},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                for w in data.get("data", []):
                    addr = w.get("ownerPubkey")
                    if addr:
                        all_wallets[addr] = {
                            "address": addr,
                            "source": "jupiter",
                            "realizedPnlUsd": w.get("realizedPnlUsd"),
                            "totalVolumeUsd": w.get("totalVolumeUsd"),
                            "predictionsCount": w.get("predictionsCount"),
                            "correctPredictions": w.get("correctPredictions"),
                            "wrongPredictions": w.get("wrongPredictions"),
                            "winRatePct": w.get("winRatePct"),
                            "pnl": w.get("realizedPnlUsd"),
                            "volume": w.get("totalVolumeUsd"),
                        }
                logger.info(
                    "Leaderboard: fetched %d from Jupiter prediction API",
                    len(data.get("data", [])),
                )
        except Exception as e:
            logger.warning("Leaderboard Jupiter fetch failed: %s", e)

        return list(all_wallets.values())[:limit]

    def fetch_polymarket_leaderboard_only(self, limit: int = 100) -> List[Dict]:
        """Top traders from Polymarket Data API only (0x proxy wallets).

        Use for **auto wallet discovery** — the merged leaderboard includes Jupiter
        Solana pubkeys, which discovery skips, so the merged list could contain
        no addable addresses.

        API caps ``limit`` at 50 per request; we paginate with ``offset``.
        """
        out: List[Dict] = []
        offset = 0
        try:
            while len(out) < limit:
                page_size = min(50, limit - len(out))
                resp = self.session.get(
                    "https://data-api.polymarket.com/v1/leaderboard",
                    params={
                        "category": "OVERALL",
                        "limit": page_size,
                        "offset": offset,
                    },
                    timeout=20,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "Polymarket leaderboard-only: HTTP %s (offset=%s)",
                        resp.status_code,
                        offset,
                    )
                    break
                data = resp.json()
                if not isinstance(data, list) or not data:
                    break
                for w in data:
                    addr = w.get("proxyWallet") or w.get("address")
                    if not addr or not str(addr).startswith("0x"):
                        continue
                    vol = w.get("vol") or w.get("volume") or 0
                    try:
                        vol = float(vol)
                    except (TypeError, ValueError):
                        vol = 0
                    out.append(
                        {
                            "address": str(addr).lower(),
                            "username": (
                                w.get("userName")
                                or w.get("username")
                                or w.get("name")
                                or w.get("pseudonym")
                                or "Trader"
                            ),
                            "source": "polymarket",
                            "volume": vol,
                            "pnl": w.get("pnl") or w.get("realizedPnl") or 0,
                        }
                    )
                offset += len(data)
                if len(data) < page_size:
                    break
            logger.info(
                "Leaderboard (Polymarket-only): %d Ethereum proxy wallets",
                len(out),
            )
        except Exception as e:
            logger.warning("Polymarket leaderboard-only fetch failed: %s", e)
        return out

    def fetch_gamma_leaderboard_wallets(self, limit: int = 80) -> List[Dict]:
        """Supplemental 0x wallets from Polymarket Gamma ``/leaderboards`` (third-party UI source).

        Merged with :meth:`fetch_polymarket_leaderboard_only` in wallet discovery so we add
        more unique proxies when the Data API list overlaps or is thin.
        """
        out: List[Dict] = []
        try:
            cap = min(int(limit or 80), 100)
            resp = self.session.get(
                "https://gamma-api.polymarket.com/leaderboards",
                params={"limit": cap},
                timeout=20,
            )
            if resp.status_code != 200:
                logger.debug("Gamma leaderboards HTTP %s", resp.status_code)
                return []
            data = resp.json()
            rows = data if isinstance(data, list) else (data.get("data") or data.get("leaderboard") or [])
            if not isinstance(rows, list):
                return []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                addr = (
                    row.get("proxyWallet")
                    or row.get("address")
                    or row.get("userAddress")
                    or row.get("wallet")
                    or row.get("user")
                )
                if not addr:
                    continue
                addr = str(addr).strip()
                if not addr.startswith("0x"):
                    continue
                nick = (
                    row.get("name")
                    or row.get("username")
                    or row.get("pseudonym")
                    or row.get("displayName")
                    or "Trader"
                )
                out.append(
                    {
                        "address": addr.lower(),
                        "username": str(nick)[:64],
                        "source": "gamma",
                    }
                )
                if len(out) >= cap:
                    break
            logger.info("Gamma leaderboard supplement: %d proxy wallets (0x)", len(out))
        except Exception as e:
            logger.warning("Gamma leaderboard supplement failed: %s", e)
        return out

    def get_top_traders(self, limit: int = 20) -> List[Dict]:
        """Get top traders sorted by PnL/volume."""
        traders = self.fetch_leaderboard(limit=limit * 2)

        sorted_traders = []
        for t in traders:
            pnl = t.get("pnl") or t.get("volume") or 0
            try:
                pnl = float(str(pnl).replace("$", "").replace(",", ""))
            except Exception:
                pnl = 0
            t["sort_value"] = pnl
            sorted_traders.append(t)

        sorted_traders.sort(key=lambda x: x.get("sort_value", 0), reverse=True)
        return sorted_traders[:limit]

    def import_all_polymarket(self, limit: int = 20) -> List[Dict]:
        """Top traders from Polymarket Data API only (0x proxy wallets).

        Returns list of {address, username}. Jupiter/Solana entries from the merged
        leaderboard are excluded so imports match auto-discovery behavior.
        """
        raw = self.fetch_polymarket_leaderboard_only(limit=limit)
        out = []
        for i, t in enumerate(raw, 1):
            out.append(
                {
                    "address": t["address"],
                    "username": t.get("username") or f"Trader{i}",
                }
            )
        return out

    def get_wallet_stats(self, address: str) -> Optional[Dict]:
        """Get wallet stats."""
        if self.polymarket_api and hasattr(self.polymarket_api, "get_wallet_stats"):
            try:
                result = self.polymarket_api.get_wallet_stats(address)
                if result:
                    return result
            except Exception:
                pass

        try:
            url = "https://gamma-api.polymarket.com/public-profile"
            resp = self.session.get(url, params={"address": address}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    return {
                        "address": address,
                        "total_trades": data.get("totalTrades", 0),
                        "wins": data.get("wins", 0),
                        "win_rate": data.get("winRate", 0.0),
                        "volume": data.get("volume", 0),
                        "positions": data.get("positionsCount", 0),
                    }
        except Exception as e:
            logger.debug("Leaderboard get_wallet_stats: %s", e)

        return None


if __name__ == "__main__":
    importer = LeaderboardImporter()
    traders = importer.fetch_leaderboard(limit=10)

    logger.info("Found %s top traders:", len(traders))
    for i, t in enumerate(traders[:10], 1):
        source = t.get("source", "unknown")
        logger.info("%s. %s... [%s]", i, t.get("address", "N/A")[:20], source)
