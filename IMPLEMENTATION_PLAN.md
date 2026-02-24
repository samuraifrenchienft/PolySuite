# PolySuite - Implementation Plan

> **Single source of truth.** Update this file when plans change. Do not create new plan files.

---

## Current State (What Works)

### Implemented
- **Multi-market aggregator** – Polymarket, Kalshi, Jupiter
- **Alert priority** – New Events → Crypto 5M/15M → Sports/Politics → Expiring → Convergence
- **Crypto short-term** – `get_crypto_short_term_markets`, `check_crypto_short_term_markets`, `format_crypto_short_term`
- **Filter keywords** – Crypto, politics, economy, sports, tech (CATEGORY_KEYWORDS, CRYPTO_SHORT_TERM_KEYWORDS)
- **AI engine** – Groq/OpenRouter: sentiment, whale analysis, `analyze_entry_zones`, 30-min report with ENTRY_ZONE
- **Trade executor** – Bankr.bot, dry-run by default
- **Discord/Telegram** – Alerts, health, arb channels
- **Alert improvements** – Whale AI bug fix, convergence side/price/size, format_expiring, AI wired into new/arb

---

## Remaining Work (Prioritized)

### Phase 1: Fix & Verify
- [x] Crypto 5M/15M: Events API + tag 744, fallback to top crypto (5M/15M not in Gamma API)
- [x] Config: `priority_categories`, `crypto_short_term_interval`, `channel_overrides`
- [ ] Test whale, convergence, expiring alerts
- [ ] Test `/ca`, `/scan`, `/add` commands
- [ ] Rate limit handling + retry logic

### Phase 2: Scanner Upgrades
- [ ] Meme scanner (`/ca`) – Honeypot API, top holders
- [ ] Wallet scanner (`/scan`) – Recent trades, categories

### Phase 3: Bankr Discord
- [ ] `defer()` + `edit_original_response()` for long Bankr polls
- [ ] Poll 2s, max 60 attempts; surface 403/429 errors

### Phase 4: Future (FUTURE_PLANS.md)
- Copy trading (py-clob-client, WebSocket)
- Points/referrals, Builder Program

---

## Merged Plans Reference

| Source | Content |
|--------|---------|
| filter_keywords_ai_report_crypto | Crypto fetch, keywords, AI entry zones |
| filter_keywords_and_alert_improvements | Whale bug, convergence, expiring, AI wiring |
| future_plans_implementation | Bankr fix, Honeypot, copy-trading research |

---

## Config (config.json)

| Key | Default | Description |
|-----|---------|-------------|
| `priority_categories` | `["crypto", "politics"]` | Categories to prioritize when fetching |
| `crypto_short_term_interval` | `90` | Seconds between crypto 5M/15M checks |
| `channel_overrides` | `{}` | Per-category channels, e.g. `{"crypto": {"discord_webhook_url": "...", "telegram_chat_id": "..."}}` |

---

## API Keys

| Service | Status |
|---------|--------|
| Polymarket | ✅ |
| Kalshi | ✅ |
| OpenRouter/Groq | ✅ |
| Discord/Telegram | ✅ |
| Bankr | ✅ |

---

## Resources

- Polymarket: docs.polymarket.com
- CLOB Client: github.com/Polymarket/py-clob-client
