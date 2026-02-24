# Research: Alerts, AI Engine, Fetching & Report UI

## 1. AI Engine Assessment

### Current Usage
- **`src/ai/engine.py` (AIFilter)**: Used for categorize, score, arbitrage, sentiment, whale analysis, new market analysis, entry zones
- **`src/ai/service.py` (GroqClient/OpenRouterClient)**: Used by Discord chat only; NOT used in alert pipeline
- **main.py** uses `ai_filter` for:
  - Daily summary (1x/day)
  - AI report every 30 min (optimal entry points)
  - Whale trade analysis (every whale batch)
  - New market sentiment + analysis
  - Entry zone analysis for top 5 markets

### Gaps & Improvements
1. **AI not used for alert prioritization** – All new events are alerted; AI could filter low-value alerts
2. **Duplicate AI clients** – engine.py and service.py both call Groq/OpenRouter; consolidate
3. **AI not used for convergence/arb** – Could add AI reasoning to convergence alerts
4. **Whale analysis runs on every batch** – Expensive; could skip if batch is small or add cooldown
5. **No AI for sports/crypto category scoring** – Could rank which markets to alert first

---

## 2. Whale Reports – Too Frequent

### Current Behavior
- Whale check runs **every 60 seconds** (`last_smart_money_import > 60`)
- Compares current positions vs last positions for tracked wallets
- Any new position ≥ $50k triggers whale alert
- No cooldown between whale alerts

### Fixes
1. Add `whale_alert_cooldown` (e.g. 30 min) – don’t send whale batch if last one was < 30 min ago
2. Increase whale check interval to 5 min (300s) instead of 1 min
3. Raise `whale_min_size` to $75k–$100k to reduce noise
4. Batch by time window – only send if ≥2 whale trades or total size > $100k

---

## 3. Crypto & Sports Fetching – "No Games" / Poor Coverage

### Current Flow
- `get_active_markets(limit=200)` → `get_markets(limit, active=True)` – **no `order` param**
- Polymarket Gamma API default order may not surface sports/crypto
- `filter_by_category` uses keyword matching on `question` via `get_category()`
- Crypto 5M/15M: Uses `get_crypto_short_term_markets()` with tag_id 744 – separate path
- Sports: `check_sports_markets` fetches 200 markets, filters by sports keywords – if API returns markets ordered by creation, sports may be buried

### Fixes
1. **Add `order=volume_24hr` or `order=volume`** to `get_markets` / `get_active_markets` so top markets by volume are returned
2. **Use Polymarket tag_id for sports** – Fetch tag IDs from `/tags` or `/sports`, filter events by `tag_id`
3. **Increase limit** for category-specific fetches (sports, politics) to 300–500
4. **Dedicated sports fetch** – `get_markets(tag_id=<sports_tag>, order=volume, limit=100)` if API supports it
5. **Fallback**: If tag_id fails, keep keyword filter but ensure we fetch enough markets (500+)

---

## 4. Report Widgets / Cards – Too Basic

### Current State
- **Dashboard** (`src/dashboard/`): Plain list + bar chart, no styling
- **Formatter** (`src/alerts/formatter.py`): Plain text with emojis
- **Discord embeds**: Basic structure (title, description, fields), single color (0xFF6B6B)

### Improvements
1. **Discord embeds**: Gradient-like colors per alert type (crypto=blue, sports=green, whale=orange), thumbnails, footer with timestamp
2. **Formatter**: Add visual separators (━━━), section headers, better spacing
3. **Dashboard**: Card layout with shadows, category badges, volume bars, modern CSS
4. **Telegram**: Use HTML formatting, bold/italic for key metrics

---

## 5. Polymarket API Notes
- Events: `tag_id`, `order` (volume_24hr, volume, liquidity, start_date, end_date)
- Markets: Same params
- Sports: Dedicated `/sports` endpoint for tag IDs
- Crypto: Tag 744 used for crypto short-term
