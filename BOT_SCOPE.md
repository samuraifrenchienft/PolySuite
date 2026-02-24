# Prediction Suite - Bot Scope

## What Is Prediction Suite?

AI-powered prediction market monitoring bot that tracks Polymarket, Kalshi, and Jupiter markets, detects opportunities, and alerts users via Discord/Telegram.

---

## Core Features

### 1. Multi-Market Aggregation
- **Polymarket** - 500+ markets ✅ Working
- **Kalshi** - 50+ markets ✅ Working  
- **Jupiter** - 300+ markets ✅ Working
- **Auto-discovery** - Checks which APIs are working ✅ Done

### 2. Market Filtering
- **Category Filter** - crypto, sports, politics, economy, entertainment, other
- **Keyword-based** - With word boundaries (no false matches)
- **AI Enhancement** - Smart categorization (needs API key)

### 3. Alert System
- **Discord** - Webhook alerts ✅ Tested
- **Telegram** - Bot messages ✅ Tested
- **Rate limiting** - 2 second delay between alerts ✅ Done
- **Batching** - Whale alerts batched into one message ✅ Done
- **Priority** - New Events → Crypto → Expiring → Convergence

### 4. Wallet Tracking
- Users add wallets via `/add` command
- Max 10 wallets per user
- Real-time trade alerts
- Position tracking

### 5. Opportunity Detection
- **New Markets** - Alerts for fresh markets
- **Arbitrage** - Cross-market price differences
- **Convergence** - Multiple smart wallets in same market
- **Expiring** - Markets about to close

### 6. AI Integration (Internal Functions)
| AI Function | Purpose |
|-------------|---------|
| Smart Categorization | Better than keywords |
| Opportunity Scoring | Rank markets 0-100 |
| Arbitrage Detection | Find cross-market ops |
| Sentiment Analysis | Bullish/bearish/neutral |
| Anomaly Detection | Flag unusual activity |

### 7. Automation Layer
- **Scheduled backups** - Every 6 hours ✅ In main.py
- **Health checks** - Hourly heartbeat
- **n8n ready** - Webhook system in place

---

## What's NOT in Scope (Yet)

- ❌ Copy trading (Phase D - future)
- ❌ Dashboard (needs users first)
- ❌ User accounts/auth
- ❌ Mobile app
- ❌ Paid features

---

## API Keys Needed

| Service | Status | Purpose |
|---------|--------|---------|
| Polymarket | ✅ In .env | Market data |
| Kalshi | ✅ Working | Market data |
| Jupiter | ✅ Working | Market data |
| Discord | ✅ In .env | Alerts |
| Telegram | ✅ In .env | Alerts |
| Bankr | ✅ In .env | Trade execution (future) |
| Groq | 🔲 Need | AI (free, unlimited) |
| OpenRouter | 🔲 Need | AI backup (50/day free) |

---

## Technical Stack

- **Language**: Python
- **Bot**: Discord.py, aiogram
- **Database**: SQLite
- **AI**: Groq (primary), OpenRouter (backup)
- **Automation**: n8n compatible (webhooks)

---

## Files Structure

```
src/
├── market/
│   ├── aggregator.py    # Multi-market fetching
│   └── api.py          # Polymarket API
├── alerts/
│   ├── combined.py      # Alert dispatcher
│   ├── events.py        # Event detection
│   └── convergence.py   # Convergence detection
├── ai/
│   ├── engine.py        # AI functions
│   └── service.py       # AI client
└── utils/
    └── backup.py        # Database backups
```

---

## Human Tasks

1. Get **Groq** API key (groq.com - free)
2. Get **OpenRouter** API key (openrouter.ai - free)

---

## Current Status

| Feature | Status |
|---------|--------|
| Polymarket | ✅ Working |
| Kalshi | ✅ Working |
| Jupiter | ✅ Working |
| Category Filter | ✅ Working |
| Discord Alerts | ✅ Tested |
| Telegram Alerts | ✅ Tested |
| Backup System | ✅ In main.py |
| AI Engine | ✅ Code ready, needs key |
| n8n Integration | 📋 Planned |
