# Prediction Suite - Implementation Plan (v2)
## Solana-Focused, Multi-Market, AI-Enhanced

---

## Core Principles

1. **Free First** - Use free APIs/services before paid
2. **Free Not Available → Paid** - Offer paid options when no free alternative exists
3. **Multi-Market** - Aggregate Polymarket, Kalshi, Jupiter
4. **AI-Enhanced** - OpenRouter free models for intelligence
5. **n8n Integration** - Free automation alongside bot

---

## Free Services Available

| Service | Use | Cost |
|---------|-----|------|
| OpenRouter | AI (DeepSeek R1, Llama, etc.) | FREE |
| Polymarket API | Market data | FREE |
| Kalshi API | Market data | FREE |
| DexScreener | Token data | FREE |
| Honeypot.is | Honeypot detection | FREE |
| n8n | Automation | FREE (self-hosted) |
| Discord/Telegram | Notifications | FREE |

---

## Priority Order

### Phase 1: Multi-Market Foundation (THIS WEEK)

- [ ] **Kalshi integration** - Add to aggregator (API requires no auth for market data)
- [ ] **Jupiter integration** - Research API for prediction markets
- [ ] **Fix alert priority** - New Events → Crypto → Expiring → Convergence

### Phase 2: AI Integration (FREE)

- [ ] **OpenRouter setup** - Sign up, get free API key
- [ ] **AI sentiment analysis** - Use DeepSeek R1 (free) to analyze market sentiment
- [ ] **AI anomaly detection** - Flag unusual trading patterns
- [ ] **AI market summaries** - Daily/weekly AI-generated market reports

### Phase 3: Automation (FREE)

- [ ] **n8n setup** - Self-hosted via Docker
- [ ] **Alert workflows** - Advanced routing in n8n
- [ ] **Scheduled reports** - Daily market summaries via n8n

### Phase 4: Features

- [ ] Wallet tracking (Polymarket)
- [ ] Whale alerts
- [ ] Convergence alerts
- [ ] Arbitrage detection
- [ ] Meme coin scanner (/ca)
- [ ] Insider detection (/scan)

---

## Technical Stack

### Core Bot
- Python
- Discord.py (Discord bot)
- aiogram (Telegram bot)
- requests (API calls)

### AI Layer (FREE)
- OpenRouter API
  - Model: `deepseek/deepseek-r1-0528:free` (reasoning)
  - Model: `meta-llama/llama-3.3-70b-instruct` (general)
- Fallback: `openrouter/free` (auto-selects)

### Automation Layer (FREE)
- n8n (self-hosted Docker)

### Market APIs
- Polymarket Gamma API (FREE)
- Polymarket CLOB API (FREE for data)
- Kalshi API (FREE for market data)
- Jupiter API (needs research)
- DexScreener (FREE)

---

## Implementation Details

### 1. OpenRouter Integration

```python
import requests

OPENROUTER_API_KEY = "your-free-key"
MODEL = "deepseek/deepseek-r1-0528:free"

def ask_ai(prompt: str) -> str:
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}]
        }
    )
    return response.json()["choices"][0]["message"]["content"]
```

**Use cases:**
- Summarize market sentiment
- Explain why a wallet is trading a certain way
- Generate market reports

### 2. n8n Integration

Run locally with Docker:
```bash
docker run -it --name n8n -p 5678:5678 n8nio/n8n
```

**Workflows to build:**
- Receive webhook from bot → format → send to Discord/Telegram
- Scheduled market scan → AI analysis → alert
- Whale alert → cross-post to multiple channels

### 3. Multi-Market Aggregator

```python
# src/market/aggregator.py

class MarketAggregator:
    def __init__(self):
        self.polymarket = PolymarketAPI()
        self.kalshi = KalshiAPI()
        self.jupiter = JupiterAPI()
    
    def get_all_markets(self, category: str = None):
        markets = []
        markets.extend(self.polymarket.get_markets(category))
        markets.extend(self.kalshi.get_markets(category))
        markets.extend(self.jupiter.get_markets(category))
        return markets
```

---

## Alert Priority System

1. **New Events** - Always alert immediately
2. **Crypto Markets** - High priority for Solana users
3. **Expiring Soon** - Time-sensitive
4. **Convergence** - Arbitrage opportunities
5. **Full Scans** - Background scanning

---

## File Structure

```
PolySuite/
├── main.py                 # Main entry
├── src/
│   ├── config/            # Configuration
│   ├── market/
│   │   ├── api.py         # Polymarket API
│   │   ├── aggregator.py  # Multi-market aggregator
│   │   ├── kalshi.py     # NEW: Kalshi
│   │   └── jupiter.py    # NEW: Jupiter
│   ├── alerts/            # Alert dispatchers
│   ├── ai/                # NEW: OpenRouter integration
│   │   └── openrouter.py
│   ├── automation/        # NEW: n8n webhooks
│   │   └── webhooks.py
│   ├── discord_bot.py     # Discord commands
│   └── telegram_bot.py    # Telegram commands
├── n8n/                   # n8n workflow exports
└── docker-compose.yml     # n8n + bot
```

---

## API Keys Needed

| Service | Status | Notes |
|---------|--------|-------|
| Polymarket | ✅ Using | Free |
| Kalshi | ✅ Using | Free (no auth for market data) |
| Jupiter | 🔬 Research | May need API key |
| DexScreener | ✅ Using | Free tier |
| Honeypot.is | ✅ Using | Free |
| OpenRouter | 🔲 Need key | FREE - sign up |
| n8n | 🔲 Need setup | FREE - Docker |

---

## Research: AI Agents on Solana

### Free Options
- **SAM Framework** - Open source, connects to OpenRouter
- **Solana Agent Kit** - 60+ actions, LangChain compatible
- **n8n + AI** - Visual automation

### Paid Alternatives (for later)
- **Nodebase** - $49/mo visual builder
- **QuickNode** - AI agents (pricing TBD)

---

## TODO: Immediate Actions

1. Sign up for OpenRouter (free) - openrouter.ai
2. Get free API key
3. Test DeepSeek R1 with market analysis prompt
4. Add Kalshi to aggregator
5. Research Jupiter prediction markets
6. Install n8n locally (optional)
7. Fix alert priority in main.py

---

## Questions Before Proceeding

1. Which features should be highest priority?
2. Should we include n8n from start or add later?
3. Any specific AI use cases besides sentiment analysis?

---

## Budget

**Goal: Free first, paid when no free option exists**

**FREE (Primary):**
- All core features: FREE
- n8n: FREE (self-hosted)
- AI: FREE (OpenRouter free tier)
- APIs: FREE (all market data APIs)

**PAID (When Needed):**
- Hosting: User's responsibility
- Premium APIs: Only when free unavailable
- n8n cloud: $20/mo (optional)
- OpenRouter paid: Pay as you go (only if free limits hit)
