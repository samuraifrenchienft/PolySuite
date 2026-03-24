# Signals Overview — What Exists

## Current State

### 1. CLI `signals` command (`main.py`)
```python
def handle_signals_command(...):
    generator = SignalGenerator()   # ← SignalGenerator is NOT DEFINED (bug)
    wallets = storage.list_wallets()
    signals = generator.generate_signals(wallets)
```
**Status:** Broken — `SignalGenerator` is never imported or defined. Would raise `NameError`.

### 2. Alert / Signal Types in Codebase

| Type | Location | What It Does |
|------|----------|--------------|
| **Convergence** | `ConvergenceDetector`, `combined.py` | 2+ high-performers in same market; sends to Discord/Telegram |
| **Insider** | `InsiderSignalDetector`, `insider_signal.py` | Fresh wallet + large trade + winning outcome |
| **Contrarian** | `contrarian.py` | Minority side vs majority volume |
| **TradeSignal** | `trade_executor.py` | Executable trade (market_id, side, amount, odds) |
| **Whale** | `polymarket_whale.py`, formatter | Large trades |
| **Smart Money** | `SmartMoneyDetector`, monitor loop | Identifies and flags smart money wallets |

### 3. Monitor Loop (runs on high performers, not vetted)
- Uses `high_performers` = wallets with `trade_volume >= threshold` and `is_high_performer(win_rate_threshold)`
- **Not** filtered by tier (vetted/elite)
- Convergence uses `get_high_performers()` from storage (win_rate >= 55%, min 10 trades)

### 4. What You Want (from your message)
- Notice when **wallet upload is complete**
- **Window/popup** with all important data when there's a signal
- Strategy runs on **all vetted wallets** (not just high performers)
- Jupiter prediction markets — keep developing

---

## Gaps

1. **SignalGenerator** — Does not exist; `signals` CLI is broken.
2. **Vetted vs high performers** — Monitor uses high performers; you want vetted.
3. **Wallet upload complete** — No UI notice when bulk import / refresh finishes.
4. **Signal popup** — No dashboard window for when a signal fires.
5. **Jupiter** — Prediction markets integration in progress.
