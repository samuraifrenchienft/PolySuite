"""Trade execution module for PolySuite - integrates with Bankr.bot."""

import logging
import threading
import queue
import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from src.config import Config
from src.market.bankr import BankrClient

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    """Represents a trade signal from alerts."""

    market_id: str
    market_question: str
    side: str  # "yes" or "no"
    amount: float
    odds: float
    source: str  # "convergence", "manual"
    confidence: float  # 0-100
    wallets: List[str]  # Wallet addresses that triggered this


class TradeExecutor:
    """Executes trades based on signals from alerts."""

    def __init__(
        self,
        config: Optional[Config] = None,
        api_factory: Optional[Any] = None,
        max_slippage: float = 1.0,
    ):
        if config is None:
            config = Config()
        self.config = config
        self.bankr = BankrClient(config.bankr_api_key)
        self.api_factory = api_factory
        self.max_slippage = max_slippage  # Maximum allowed slippage %

        # Trade queue for async execution
        self._trade_queue: queue.Queue = queue.Queue(maxsize=50)
        self._worker_started = False
        self._start_worker()

        # Settings
        self.min_confidence = 70.0  # Minimum confidence to execute
        self.max_trade_amount = 100.0  # Max $ per trade
        self.dry_run = True  # Start in dry-run mode

        # Track executed trades
        self.executed_trades: List[Dict] = []

    def _start_worker(self):
        if self._worker_started:
            return
        thread = threading.Thread(
            target=self._worker, daemon=True, name="trade-executor"
        )
        thread.start()
        self._worker_started = True

    def _worker(self):
        """Process trade queue."""
        while True:
            try:
                signal = self._trade_queue.get(timeout=1)
                self._execute_trade(signal)
            except queue.Empty:
                continue
            except Exception as e:
                logger.exception("TradeExecutor worker error: %s", e)

    def _execute_trade(self, signal: TradeSignal):
        """Execute a trade via Bankr."""
        if self.dry_run:
            logger.info(
                "TradeExecutor DRY RUN: Would execute %s $%s on %s",
                signal.side,
                signal.amount,
                signal.market_question[:50],
            )
            self.executed_trades.append(
                {
                    "dry_run": True,
                    "market_id": signal.market_id,
                    "side": signal.side,
                    "amount": signal.amount,
                    "timestamp": time.time(),
                }
            )
            return

        if not self.bankr.is_configured():
            logger.warning("TradeExecutor: Bankr not configured")
            return

        # Validate slippage if we have API access
        if self.api_factory and signal.market_id:
            if not self._validate_slippage(signal):
                logger.warning(
                    "TradeExecutor: Slippage validation failed for %s", signal.market_id
                )
                return

        # Build prompt for Bankr
        prompt = self._build_trade_prompt(signal)
        job_id, _ = self.bankr.send_prompt(prompt)

        if job_id:
            logger.info("TradeExecutor: Trade submitted: %s", job_id)
            self.executed_trades.append(
                {
                    "job_id": job_id,
                    "market_id": signal.market_id,
                    "side": signal.side,
                    "amount": signal.amount,
                    "timestamp": time.time(),
                }
            )
        else:
            logger.error("TradeExecutor: Trade failed (no job_id)")

    def _build_trade_prompt(self, signal: TradeSignal) -> str:
        """Build natural language prompt for Bankr."""
        return f"Bet ${signal.amount} on {signal.side} for '{signal.market_question}' on Polymarket. Market ID: {signal.market_id}"

    def _validate_slippage(self, signal: TradeSignal) -> bool:
        """Validate that trade slippage is within acceptable limits."""
        if not self.api_factory:
            # If no API factory, we can't validate slippage - allow trade
            return True

        try:
            # Get API client for price data
            api = self.api_factory.get_polymarket_api()

            # Get current market price
            market_data = api.get_market(signal.market_id)
            if not market_data:
                logger.warning(
                    "TradeExecutor: Could not fetch market data for %s",
                    signal.market_id,
                )
                return False

            # Determine which token to check based on side
            # This is a simplification - in practice, we'd need to map yes/no to specific tokens
            outcome_prices = market_data.get("outcomePrices", "[]")
            try:
                import json

                prices = (
                    json.loads(outcome_prices)
                    if isinstance(outcome_prices, str)
                    else outcome_prices
                )
                if len(prices) >= 2:
                    # Assume index 0 is NO, index 1 is YES (common convention)
                    token_index = 1 if signal.side.lower() == "yes" else 0
                    if token_index < len(prices):
                        current_price = float(prices[token_index])

                        # Calculate slippage based on signal odds vs current price
                        # Signal odds represent the implied probability from the alert
                        price_diff = abs(current_price - signal.odds)
                        slippage_pct = (
                            (price_diff / current_price) * 100
                            if current_price > 0
                            else 0
                        )

                        if slippage_pct > self.max_slippage:
                            logger.warning(
                                "TradeExecutor: Slippage %.2f%% exceeds max %s%%",
                                slippage_pct,
                                self.max_slippage,
                            )
                            return False
                        else:
                            logger.debug(
                                "TradeExecutor: Slippage validation passed: %.2f%%",
                                slippage_pct,
                            )
                            return True
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                logger.warning("TradeExecutor: Error parsing outcome prices: %s", e)
                # If we can't parse prices, be conservative and allow the trade
                return True

        except Exception as e:
            logger.warning("TradeExecutor: Error validating slippage: %s", e)
            # If validation fails, be conservative and allow the trade
            return True

        # If we couldn't validate, allow the trade
        return True

    def is_configured(self) -> bool:
        """Check if trade execution is configured."""
        return self.bankr.is_configured()

    def queue_trade(self, signal: TradeSignal):
        """Queue a trade for execution."""
        if signal.confidence < self.min_confidence:
            logger.info(
                "TradeExecutor: Signal confidence %s%% below threshold %s%%",
                signal.confidence,
                self.min_confidence,
            )
            return

        if signal.amount > self.max_trade_amount:
            logger.info(
                "TradeExecutor: Signal amount $%s exceeds max $%s",
                signal.amount,
                self.max_trade_amount,
            )
            signal.amount = self.max_trade_amount

        self._trade_queue.put(signal)

    def from_convergence_signal(
        self, market: Dict, wallets: List[Dict], amount: float = 10.0
    ) -> Optional[TradeSignal]:
        """Create trade signal from convergence alert."""
        if not market:
            return None

        market_id = market.get("id") or market.get("conditionId") or ""
        question = market.get("question", "Unknown")

        # Determine side based on wallets - use majority vote
        yes_votes = sum(1 for w in wallets if w.get("side", "").lower() == "yes")
        no_votes = sum(1 for w in wallets if w.get("side", "").lower() == "no")

        if yes_votes > no_votes:
            side = "yes"
            confidence = (yes_votes / len(wallets)) * 100 if wallets else 0
        elif no_votes > yes_votes:
            side = "no"
            confidence = (no_votes / len(wallets)) * 100 if wallets else 0
        else:
            return None  # No consensus

        wallet_addresses = [w.get("address", "") for w in wallets if w.get("address")]

        return TradeSignal(
            market_id=market_id,
            market_question=question,
            side=side,
            amount=amount,
            odds=market.get("probability", 0.5),
            source="convergence",
            confidence=confidence,
            wallets=wallet_addresses,
        )

    def enable_live_trading(self):
        """Enable live trading (disable dry run)."""
        self.dry_run = False
        logger.warning("TradeExecutor: Live trading ENABLED")

    def disable_live_trading(self):
        """Disable live trading (enable dry run)."""
        self.dry_run = True
        logger.info("TradeExecutor: Dry run mode enabled")

    def get_status(self) -> Dict[str, Any]:
        """Get executor status."""
        return {
            "configured": self.is_configured(),
            "dry_run": self.dry_run,
            "min_confidence": self.min_confidence,
            "max_trade_amount": self.max_trade_amount,
            "trades_executed": len(self.executed_trades),
            "queue_size": self._trade_queue.qsize(),
        }
