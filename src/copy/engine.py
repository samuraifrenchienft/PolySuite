"""Copy trading engine: RTDS trades -> qualify -> execute via Polymarket CLOB."""

import logging
import time
from collections import deque
from typing import Callable, Dict, Optional

from src.copy.storage import get_copy_target_addresses, list_copy_targets
from src.market.rtds_client import RTDSClient
from src.market.polymarket_clob import PolymarketCLOBTrading
from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions
from py_clob_client.order_builder.constants import BUY, SELL

logger = logging.getLogger(__name__)


class CopyEngine:
    """Subscribes to RTDS activity:trades, filters by copy targets, qualifies, and executes orders."""

    def __init__(
        self,
        config: dict,
        credential_store=None,
    ):
        self.config = config or {}
        self._credential_store = credential_store
        self._rtds: Optional[RTDSClient] = None
        self._clob: Optional[PolymarketCLOBTrading] = None
        self._trade_timestamps: deque = deque(maxlen=500)
        self._freeze_until: float = 0.0

    def _get_user_creds(self, user_id: str) -> Optional[dict]:
        """Fetch Polymarket creds for user. Returns None if not found or store unavailable."""
        if not user_id or not self._credential_store:
            return None
        try:
            return self._credential_store.get_credentials(user_id, "polymarket")
        except RuntimeError:
            return None
        except Exception as e:
            logger.warning("[CopyEngine] get_creds error: %s", e)
            return None

    def _check_throttle(self) -> bool:
        """Return True if we can execute (under throttle limit)."""
        max_per_min = int(self.config.get("copy_max_trades_per_minute", 0) or 0)
        if max_per_min <= 0:
            return True
        now = time.time()
        cutoff = now - 60
        while self._trade_timestamps and self._trade_timestamps[0] < cutoff:
            self._trade_timestamps.popleft()
        return len(self._trade_timestamps) < max_per_min

    def _check_freeze(self) -> bool:
        """Return True if we are NOT in freeze (can execute)."""
        if time.time() < self._freeze_until:
            return False
        freeze_after = int(self.config.get("copy_freeze_after_trades", 0) or 0)
        if freeze_after <= 0:
            return True
        window_min = int(self.config.get("copy_reduction_window_minutes", 60) or 60)
        cutoff = time.time() - (window_min * 60)
        count = sum(1 for ts in self._trade_timestamps if ts >= cutoff)
        if count >= freeze_after:
            duration_min = int(
                self.config.get("copy_freeze_duration_minutes", 60) or 60
            )
            self._freeze_until = time.time() + (duration_min * 60)
            logger.info(
                "[CopyEngine] Freeze triggered: %d trades in %d min, pausing %d min",
                count,
                window_min,
                duration_min,
            )
            return False
        return True

    def _get_effective_multiplier(self) -> float:
        """Return multiplier (possibly reduced after many trades)."""
        base = float(self.config.get("copy_size_multiplier", 1.0))
        reduce_after = int(
            self.config.get("copy_reduce_multiplier_after_trades", 0) or 0
        )
        if reduce_after <= 0:
            return base
        window_min = int(self.config.get("copy_reduction_window_minutes", 60) or 60)
        cutoff = time.time() - (window_min * 60)
        count = sum(1 for ts in self._trade_timestamps if ts >= cutoff)
        if count >= reduce_after:
            reduced = float(self.config.get("copy_reduced_multiplier", 0.5))
            return reduced
        return base

    def _qualify(self, trade: dict) -> bool:
        """Check config filters: odds, size, liquidity, throttle, freeze."""
        if self.config.get("copy_pause"):
            return False
        if not self._check_freeze():
            return False
        if not self._check_throttle():
            return False
        price = float(trade.get("price", 0) or 0)
        size = float(trade.get("size", 0) or 0)
        min_odds = float(self.config.get("copy_min_odds", 0.05))
        max_odds = float(self.config.get("copy_max_odds", 0.95))
        max_usd = float(self.config.get("copy_max_order_usd", 100))
        if price < min_odds or price > max_odds:
            return False
        order_usd = size * price
        if order_usd <= 0 or order_usd > max_usd:
            return False
        return True

    def _execute_order(self, trade: dict, user_id: str) -> Optional[str]:
        """Execute an order via Polymarket CLOB with maker-only strategy."""
        if self.config.get("copy_dry_run", True):
            logger.info(
                "[CopyEngine] Dry run: would copy trade %s for user %s",
                trade.get("asset_id"),
                user_id,
            )
            return None
        try:
            creds = self._get_user_creds(user_id)
            if not creds:
                logger.warning("[CopyEngine] No credentials for user %s", user_id)
                return None

            clob = PolymarketCLOBTrading(
                api_key=creds["api_key"],
                api_secret=creds["api_secret"],
                api_passphrase=creds["api_passphrase"],
            )
            token_id = (
                trade.get("asset_id")
                or trade.get("raw", {}).get("asset_id")
                or trade.get("raw", {}).get("assetId")
            )
            if not token_id:
                logger.warning("[CopyEngine] No asset_id in trade")
                return None
            price = float(trade.get("price", 0) or 0)
            size = float(trade.get("size", 0) or 0)
            mult = self._get_effective_multiplier()
            size = size * mult
            if size <= 0:
                return None
            side = (trade.get("side") or "BUY").upper()

            # Use POST_ONLY (maker-only) order to earn fee rebates
            # According to March 2026 changelog: maker rebate -0.07%, taker fee 0.12%
            opts = PartialCreateOrderOptions(
                tick_size="0.01", neg_risk=False, post_only=True
            )
            args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=BUY if side == "BUY" else SELL,
            )

            resp = clob._client.create_and_post_order(args, options=opts)
            if isinstance(resp, dict):
                order_id = resp.get("orderID") or resp.get("order_id")
            else:
                order_id = str(resp) if resp is not None else None

            if order_id:
                self._trade_timestamps.append(time.time())
                logger.info("[CopyEngine] Maker-only order placed: %s", order_id)
                return order_id
            else:
                logger.warning("[CopyEngine] Order placement failed: %s", resp)
                return None
        except Exception as e:
            logger.exception("[CopyEngine] execute error: %s", e)
            return None
        if self.config.get("copy_dry_run", True):
            logger.info(
                "[CopyEngine] Dry run: would copy trade %s for user %s",
                trade.get("asset_id"),
                user_id,
            )
            return None
        try:
            clob = PolymarketCLOBTrading(
                api_key=creds["api_key"],
                api_secret=creds["api_secret"],
                api_passphrase=creds["api_passphrase"],
            )
            token_id = (
                trade.get("asset_id")
                or trade.get("raw", {}).get("asset_id")
                or trade.get("raw", {}).get("assetId")
            )
            if not token_id:
                logger.warning("[CopyEngine] No asset_id in trade")
                return None
            price = float(trade.get("price", 0) or 0)
            size = float(trade.get("size", 0) or 0)
            mult = self._get_effective_multiplier()
            size = size * mult
            if size <= 0:
                return None
            side = (trade.get("side") or "BUY").upper()
            order_id = clob.create_and_post_order(
                token_id=token_id, price=price, size=size, side=side
            )
            if order_id:
                self._trade_timestamps.append(time.time())
                logger.info("[CopyEngine] Order placed: %s", order_id)
            return order_id
        except Exception as e:
            logger.exception("[CopyEngine] execute error: %s", e)
            return None

    def _on_trade(self, trade: dict) -> None:
        """Handle RTDS trade: filter by targets, qualify, execute."""
        proxy = (trade.get("proxyWallet") or "").strip().lower()
        if not proxy:
            return
        targets = get_copy_target_addresses()
        if proxy not in targets:
            return
        if not self._qualify(trade):
            return
        user_id = (self.config.get("copy_default_user_id") or "").strip()
        if not user_id:
            logger.debug("[CopyEngine] No copy_default_user_id, dry-run only")
            if self.config.get("copy_dry_run", True):
                logger.info(
                    "[CopyEngine] Would copy trade from %s (no user_id set)", proxy[:12]
                )
            return
        self._execute_order(trade, user_id)

    def start(self) -> None:
        """Start RTDS client and subscribe to trades."""
        targets = get_copy_target_addresses()
        if not targets:
            logger.info("[CopyEngine] No copy targets, not starting RTDS")
            return
        if not self.config.get("copy_enabled"):
            logger.info("[CopyEngine] copy_enabled=false, not starting")
            return
        self._rtds = RTDSClient()
        self._rtds.subscribe_trades(self._on_trade)
        self._rtds.start()
        logger.info("[CopyEngine] Started, %d targets", len(targets))

    def stop(self) -> None:
        """Stop RTDS client."""
        if self._rtds:
            self._rtds.stop()
            self._rtds = None
        self._clob = None
        logger.info("[CopyEngine] Stopped")
