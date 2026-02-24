# Prediction Suite - Technical Implementation Plan

## Current State (What Already Works)

### ✅ Already Implemented
1. **Multi-market aggregator** (`src/market/aggregator.py`)
   - Polymarket API ✓
   - Kalshi API ✓
   - Jupiter API (needs key)

2. **Alert priority** (already correct in main.py)
   - PRIORITY 1: New Events + Arbitrage check
   - PRIORITY 2: Crypto prices
   - PRIORITY 3: Expiring events
   - PRIORITY 4: Convergence

3. **Trade executor** (`src/alerts/trade_executor.py`)
   - Uses Bankr.bot for execution
   - Dry-run mode by default
   - Confidence threshold: 70%

4. **Discord/Telegram** - Configured in .env

---

## What Needs to be Done

### 1. ADD OPENROUTER AI INTEGRATION

**New file: `src/ai/openrouter_client.py`**

```python
import requests
from typing import Optional

class OpenRouterClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://openrouter.ai/api/v1"
        self.model = "deepseek/deepseek-r1-0528:free"  # FREE model
    
    def analyze_sentiment(self, market_question: str) -> str:
        """Analyze market sentiment using DeepSeek R1."""
        prompt = f"Analyze this prediction market: '{market_question}'. Give a brief sentiment (bullish/bearish/neutral) and why."
        return self._call(prompt)
    
    def explain_wallet(self, wallet_trades: list) -> str:
        """Explain what a wallet is doing."""
        prompt = f"Analyze these trades: {wallet_trades}. What is this wallet's strategy?"
        return self._call(prompt)
    
    def _call(self, prompt: str) -> str:
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}]
            }
        )
        return response.json()["choices"][0]["message"]["content"]
```

**Where to integrate:**
- `src/alerts/events.py` - Add sentiment to new market alerts
- `src/alerts/insider.py` - Add wallet explanation to /scan

**Config needed:**
- `OPENROUTER_API_KEY` in .env

---

### 2. TEST ALERTS

**Manual test:**
```bash
cd Desktop/PolySuite
python -c "
from src.alerts.combined import AlertDispatcher
d = AlertDispatcher()
d.send_health('TEST ALERT - Ignore')
"
```

**Or run bot with test mode:**
- Already sends test alert on first run (main.py:270)

**What to verify:**
- Discord webhook fires
- Telegram bot fires
- No errors in logs

---

### 3. ADD KALSHI TO MAIN.PY

**Current:** Aggregator already has Kalshi

**What to do:** Make sure it's called in main loop

In `main.py`, find where markets are fetched and add:
```python
from src.market.aggregator import aggregator

# Add to get_all_markets call
all_markets = aggregator.get_all_markets(jupiter_key=config.jupiter_api_key)
```

---

### 4. SCHEDULED BACKUP

**New file: `src/utils/backup.py`**

```python
import sqlite3
import os
from datetime import datetime

def backup_database(db_path: str, backup_dir: str = "backups"):
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{backup_dir}/predictionsuite_{timestamp}.db"
    
    conn = sqlite3.connect(db_path)
    backup = sqlite3.connect(backup_path)
    conn.backup(backup)
    
    # Keep only last 7 backups
    backups = sorted(os.listdir(backup_dir))
    for old in backups[:-7]:
        os.remove(f"{backup_dir}/{old}")
    
    return backup_path
```

**Add to main.py loop:**
```python
# Every 6 hours
if current_time - last_backup > 6 * 3600:
    backup_database("data/predictionsuite.db")
    last_backup = current_time
```

---

### 5. PHASE D - TRADE EXECUTION

**What's already there:** `src/alerts/trade_executor.py`

**What's needed to enable:**
1. Set `dry_run = False` in TradeExecutor
2. Ensure Bankr API key works
3. Set confidence threshold (default 70%)
4. Set max trade amount (default $100)

**To enable live trading:**
```python
executor = TradeExecutor(config)
executor.enable_live_trading()  # REMOVES DRY RUN
```

---

## Implementation Order

### Step 1: Test Alerts (Today)
- [ ] Run test command
- [ ] Verify Discord fires
- [ ] Verify Telegram fires
- [ ] Fix any errors

### Step 2: OpenRouter AI (Tomorrow)
- [ ] Sign up at openrouter.ai
- [ ] Get free API key
- [ ] Add to .env
- [ ] Create openrouter_client.py
- [ ] Integrate into alerts

### Step 3: Multi-market (After AI)
- [ ] Verify Kalshi in aggregator works
- [ ] Add Jupiter API key if available
- [ ] Test all 3 sources

### Step 4: Backup (Later)
- [ ] Create backup.py
- [ ] Add to main loop

### Step 5: Phase D (Future)
- [ ] Test dry-run mode
- [ ] Enable live trading when ready

---

## Files to Modify

| File | Change |
|------|--------|
| `.env` | Add OPENROUTER_API_KEY |
| `src/ai/openrouter_client.py` | NEW - AI client |
| `src/alerts/events.py` | Add sentiment analysis |
| `src/alerts/insider.py` | Add wallet explanation |
| `src/utils/backup.py` | NEW - Backup utility |
| `main.py` | Add backup to loop |

---

## API Keys Status

| Service | Status | Key Needed |
|---------|--------|------------|
| Polymarket | ✅ Has | - |
| Kalshi | ✅ Has | - |
| Jupiter | ⚠️ Has URL, need key | Optional |
| OpenRouter | ❌ Missing | YES - FREE |
| Discord | ✅ Has | - |
| Telegram | ✅ Has | - |
| Bankr | ✅ Has | - |

---

## Questions Before Coding

1. Should I start with testing alerts first?
2. Do you want to sign up for OpenRouter now?
3. Any other priorities?
