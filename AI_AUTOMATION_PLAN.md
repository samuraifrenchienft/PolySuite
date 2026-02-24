# AI + Automation Integration Plan

## AI Functions (Internal Bot Operations)

| Function | What It Does | Trigger |
|----------|--------------|---------|
| **Smart Categorization** | AI categorizes markets better than keywords | Every market fetch |
| **Opportunity Scoring** | AI scores markets by potential (0-100) | Every scan cycle |
| **Arbitrage Detection** | AI finds cross-market opportunities | Every arbitrage check |
| **Sentiment Analysis** | AI analyzes market sentiment | On new markets |
| **Anomaly Detection** | AI flags unusual wallet activity | On whale trades |

## n8n Automation Integration

| n8n Trigger | Bot Action | Automation |
|-------------|------------|------------|
| Webhook from bot | Format alert → Discord/Telegram | Advanced routing |
| Scheduled | Run AI analysis → Post summary | Daily reports |
| Whale alert | Cross-post to multiple channels | Multi-platform |
| New market | AI analysis → Quality check | Auto-filtering |

## Workflow

```
Bot scans markets → AI scores/categorizes → Filter top opportunities 
→ Send to n8n → n8n formats → Discord/Telegram/Email
```

## Current Implementation

- `src/ai/engine.py` - AI functions for:
  - `ai_filter.categorize()` - Smart categorization
  - `ai_filter.score_opportunity()` - Opportunity scoring  
  - `ai_filter.find_arbitrage()` - Cross-market arb
  - `ai_sentiment.analyze()` - Sentiment analysis

## What Needs Keys

- `GROQ_API_KEY` - Primary AI (unlimited)
- `OPENROUTER_API_KEY` - Backup AI
