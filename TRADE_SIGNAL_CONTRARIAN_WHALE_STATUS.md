# TradeSignal, Contrarian & Whale — Status Report

## 1. TradeSignal — What It Means

**TradeSignal** (`src/alerts/trade_executor.py`) is a **dataclass that represents an executable trade recommendation** from alerts. It is the bridge between "something interesting happened" and "place a bet."

| Field | Meaning |
|-------|---------|
| `market_id` | Polymarket condition/market ID |
| `market_question` | Human-readable question |
| `side` | "yes" or "no" |
| `amount` | USD to bet |
| `odds` | Implied probability at signal time |
| `source` | "convergence", "manual", etc. |
| `confidence` | 0–100 |
| `wallets` | Addresses that triggered the signal |

**Flow:** Alerts (e.g. convergence) → `TradeExecutor.from_convergence_signal()` → `TradeSignal` → `queue_trade()` → Bankr API (or dry-run). It is the **actionable output** of the alert system.

---

## 2. Contrarian — Status

### What It Does
"Golden odds" 20–40%: when the crowd piles on one side, the minority side has high payout. Score = `imbalance × payout`.

### Code Quality: **Good structure, potential bug**

| Aspect | Status |
|--------|--------|
| Logic | Clear: min volume $10k, imbalance ≥60%, minority price 0.20–0.40 |
| Scoring | `score = imbalance * payout` — reasonable |
| API usage | Uses `get_active_markets(80, order="volume")` and `get_market_trades(200)` |
| Error handling | Try/except, returns empty on failure |
| Tests | `test_formatter_alerts`, `test_alerts` |

### Potential Bug: **Minority price indexing**
- When majority = YES, minority = NO → code uses `prices[1]` (YES). Should use `prices[0]` (NO).
- When majority = NO, minority = YES → code uses `prices[0]` (NO). Should use `prices[1]` (YES).

Polymarket `outcomePrices` is typically `[NO, YES]`. The current indexing appears reversed.

### Wired Into Monitor? **No**
- `ContrarianDetector` exists and has `scan()`.
- `format_contrarian()` exists.
- **Not called** from `main.py` monitor loop.
- Config has `contrarian_alerts` (default False).

### Trader Edge
- **Concept:** Crowd vs minority is a known prediction-market edge.
- **Usefulness:** High if the logic is correct and the minority price is right.
- **Action:** Fix price indexing, wire into monitor (or dashboard), enable when ready.

---

## 3. Whale — Status

### What Exists

| Component | Location | Purpose |
|-----------|----------|---------|
| **PolymarketWhaleClient** | `polymarket_whale.py` | Fetches large trades ($5k+ default) from Polymarket Data API (no key) |
| **InsiderSignalDetector** | `insider_signal.py` | Uses whale trades as one input for insider-style signals |
| **format_whale_batch** | `formatter.py` | Formats "CURATED WALLET ACTIVITY" alerts |
| **send_whale_batch** | `combined.py` | Sends batched whale alerts to Discord/Telegram |

### Code Quality: **Solid**

| Aspect | Status |
|--------|--------|
| PolymarketWhaleClient | Simple, uses public API, normalizes to HashDive-like format |
| Rate limiting | min_usd 0–1M, limit 1–100 |
| Error handling | Returns [] on failure |
| Format | Groups by wallet, shows top trades |

### Wired Into Monitor? **No**
- `send_whale_batch()` exists but is **never called** from `main.py` or the monitor loop.
- Whale data is only used inside **InsiderSignalDetector** (fresh wallet + large trade + win).
- There is no standalone "whale alert" in the monitor.

### Trader Edge
- **Concept:** Large trades can signal informed flow.
- **Usefulness:** Moderate — size alone is noisy; combined with wallet quality (e.g. insider logic) it’s stronger.
- **Action:** Either wire whale batch into the monitor, or rely on InsiderSignal (which already uses whale data).

---

## Summary

| Component | Coded Well? | Wired? | Trader Edge |
|-----------|-------------|--------|-------------|
| **TradeSignal** | Yes | Yes (convergence → Bankr) | High — turns alerts into trades |
| **Contrarian** | Mostly (check price indexing) | No | High if logic is correct |
| **Whale** | Yes | No (only via Insider) | Moderate alone; stronger with Insider |

### Recommendations
1. **Contrarian:** Fix minority price indexing, then wire into monitor or dashboard.
2. **Whale:** Decide: (a) add standalone whale alerts to monitor, or (b) keep as Insider input only.
3. **TradeSignal:** Already usable; ensure convergence and other alerts can produce TradeSignals when appropriate.
