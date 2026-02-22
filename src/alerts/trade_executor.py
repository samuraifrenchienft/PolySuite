"""Trade execution module for PolySuite - integrates with Bankr.bot."""

import threading
import queue
import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from src.config import Config
from src.market.bankr import BankrClient


@dataclass
class TradeSignal:
    """Represents a trade signal from alerts."""

    market_id: str
    market_question: str
    side: str  # "yes" or "no"
    amount: float
    odds: float
    source: str  # "convergence", "arb", "manual"
    confidence: float  # 0-100
    wallets: List[str]  # Wallet addresses that triggered this


class TradeExecutor:
    """Executes trades based on signals from alerts."""

    def __init__(self, config: Optional[Config] = None):
        if config is None:
            config = Config()
        self.config = config
        self.bankr = BankrClient(config.bankr_api_key)

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
                print(f"[TradeExecutor] Error: {e}")

    def _execute_trade(self, signal: TradeSignal):
        """Execute a trade via Bankr."""
        if self.dry_run:
            print(
                f"[TradeExecutor] DRY RUN: Would execute {signal.side} ${signal.amount} on {signal.market_question[:50]}"
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
            print("[TradeExecutor] Bankr not configured")
            return

        # Build prompt for Bankr
        prompt = self._build_trade_prompt(signal)
        job_id = self.bankr.send_prompt(prompt)

        if job_id:
            print(f"[TradeExecutor] Trade submitted: {job_id}")
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
            print(f"[TradeExecutor] Trade failed")

    def _build_trade_prompt(self, signal: TradeSignal) -> str:
        """Build natural language prompt for Bankr."""
        return f"Bet ${signal.amount} on {signal.side} for '{signal.market_question}' on Polymarket. Market ID: {signal.market_id}"

    def is_configured(self) -> bool:
        """Check if trade execution is configured."""
        return self.bankr.is_configured()

    def queue_trade(self, signal: TradeSignal):
        """Queue a trade for execution."""
        if signal.confidence < self.min_confidence:
            print(
                f"[TradeExecutor] Signal confidence {signal.confidence}% below threshold {self.min_confidence}%"
            )
            return

        if signal.amount > self.max_trade_amount:
            print(
                f"[TradeExecutor] Signal amount ${signal.amount} exceeds max ${self.max_trade_amount}"
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

    def from_arb_signal(self, arb: Dict, amount: float = 50.0) -> Optional[TradeSignal]:
        """Create trade signal from arbitrage alert."""
        try:
            profit_pct = float(arb.get("profit_pct", 0))
        except (ValueError, TypeError):
            profit_pct = 0

        if not arb or profit_pct < 1.0:
            return None

        market_id = arb.get("market_id") or arb.get("condition_id") or ""
        question = arb.get("question", "Unknown")

        # For arb, we bet on the underpriced side
        yes_price = arb.get("yes_price", 0.5)
        no_price = arb.get("no_price", 0.5)

        # Bet on the side that's underpriced relative to fair value
        if yes_price < no_price:
            side = "yes"
        else:
            side = "no"

        return TradeSignal(
            market_id=market_id,
            market_question=question,
            side=side,
            amount=min(amount, self.max_trade_amount),
            odds=yes_price if side == "yes" else no_price,
            source="arb",
            confidence=min(profit_pct * 10, 100),  # Convert profit % to confidence
            wallets=[],
        )

    def enable_live_trading(self):
        """Enable live trading (disable dry run)."""
        self.dry_run = False
        print("[TradeExecutor] Live trading ENABLED")

    def disable_live_trading(self):
        """Disable live trading (enable dry run)."""
        self.dry_run = True
        print("[TradeExecutor] Dry run mode enabled")

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
