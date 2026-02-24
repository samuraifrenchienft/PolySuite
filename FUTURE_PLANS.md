# Prediction Suite - Future Plans

## Current Features

- Wallet tracking (user adds wallets via `/add`)
- Whale alerts when tracked wallets trade
- Convergence alerts
- Meme coin scanner (`/ca`) - Lute-style
- Insider detection (`/scan`)
- Discord + Telegram alerts
- Groq AI chat (replaced Bankr)

---

## Future: Bankr Integration

### Why Bankr Later
Bankr offers real trading execution on Polymarket. Currently we use Groq for AI chat which is free/unlimited.

### Planned Integration
- Add optional `/trade` command for users with Bankr accounts
- Separate from AI chat - users can use both
- No conflict with current Groq setup
- Streamlined: users connect their Bankr key only when they want to trade
- Keep Groq as default for all AI queries

### Implementation
- Add `/connect` command to link Bankr API key
- Add `/trade` command for execution (optional, opt-in)
- Keep `/ask` and `/ai` using Groq

---

## Research Findings

### 1. Honeypot Detection

**Free APIs/Services:**
- **HoneypotScan** (honeypotscan.pages.dev) - Free, no API key, Ethereum/Polygon/Arbitrum
- **TokenSniffer** (tokensniffer.com) - Free, 14 chains, API available
- **Honeypot.is** - Simulates buy/sell to detect honeypots

**Implementation:**
- Use DexScreener API (already integrated)
- Add TokenSniffer or HoneypotScan API
- Simple check: can you sell? (simulate small trade)

### 2. Copy Trading

**How it works:**
1. Monitor tracked wallets for new trades (already done)
2. Automatically execute same trade on your account
3. Use Polymarket CLOB API for execution

**Tools:**
- **Stand.trade** - Free, Discord alerts
- **Polycule** - Telegram, 1% fee
- **py-clob-client** - Official Polymarket Python SDK

**Implementation:**
- Requires: Polymarket API credentials + wallet
- Position sizing: fixed amount or % of bankroll
- Risk controls: max position size, stop-loss

### 3. Lute (docs.lute.gg)

- Real-time alerts, automatic token info, revenue sharing (35% fees)
- "See what friends are buying" - social positions on events
- Market calls, momentum scanning, one-click execution
- Polymarket integration for prediction markets

### 4. Olympus (olympusx.app)

- Non-custodial copy trading, Privy wallet
- Size multiplier, max order, min odds, liquidity filters
- Discord alerts per trade; trader profile pages (PnL, win rate, volume)
- Fees: 0.01%-0.75%

### 5. Copy Trade Bots

- [crypmancer/polymarket-copy-bot](https://github.com/crypmancer/polymarket-copy-bot): WebSocket `activity:trades`, filter by TARGET_WALLET, CLOB execution
- [py-clob-client](https://github.com/Polymarket/py-clob-client): Python CLOB client
- Polymarket WebSocket: `wss://ws-live-data.polymarket.com` (RTDS), `activity` topic

### 6. Leverage Prediction Markets

- Polymarket/Kalshi: binary 0.01-0.99; Parlays/Combos for bundled outcomes
- No native leverage; position sizing simulates

### 7. SOL Decoder (docs.soldecoder.app)

- NFT mints, hype eval, multi-source alpha (Discord, Twitter, Magic Eden)
- Keyword search, scheduled alerts

### 8. Builder Program (Revenue Share)

**How it works:**
- Apply at builders.polymarket.com
- Get unique builder code
- Attach code to all API trades
- Earn % of volume (top builders: $31M+/week!)

**Stats:**
- Betmoar: $31M/week
- Top 10: $20M+/week combined
- Rewards: Weekly USDC distribution

**Apply requirements:**
- Working MVP
- Website URL
- Description

---

## Priority Roadmap

### Phase 1: Improve Existing (Immediate)

1. **Verify alerts working**
   - Test whale trade alerts
   - Test convergence alerts
   - Test Discord commands

2. **Fix bugs** — see [.cursor/MAIN_ISSUES.md](.cursor/MAIN_ISSUES.md) for full list

3. **Optimize API calls** (upgrades)
   - Add TTLCache/LRU for unbounded caches (events.py _previous_prices, _last_alerts)
   - Deduplicate market fetches in calculator, vetting

### Phase 2: Scanner Improvements

1. **Honeypot check in `/ca`** — done (Honeypot.is API)

2. **Add top holders to scanner**
   - Show top 5 holders with % ownership
   - Flag if team holds >20%

### Phase 3: Revenue Features

1. **Apply for Builder Program**
   - Build MVP with trading capability
   - Submit at builders.polymarket.com

2. **Copy Trading**
   - Add trade execution via CLOB API
   - Position sizing controls

---

## Competitors Analysis

| Tool | Type | Fee | Features |
|------|------|-----|----------|
| Stand.trade | Web | Free | Whale alerts, copy trading |
| Polycule | Telegram | 1% | Auto-copy, filters |
| PolyWatch | Discord | Free | $1K+ whale alerts |
| Polywhaler | Web | $? | AI predictions |
| Lute | Discord | ? | Token scanning, social |

---

## API References

- **Polymarket Data API**: data-api.polymarket.com
- **Polymarket CLOB**: Trading execution
- **DexScreener**: api.dexscreener.com
- **TokenSniffer**: tokensniffer.com (API)
- **HoneypotScan**: honeypotscan.pages.dev

---

## Bankr on Discord (Research + Test 2025-02)

**What works:** Agent API has no Discord-specific limits. Same capabilities as CLI. Tested: `send_prompt` + poll `get_job_status` completes in ~30s for "what is the price of ETH?".

**Discord constraints:**
- Slash commands: 3s initial response → use `defer(ephemeral=True)` (extends to 15 min). Already implemented.
- Slash string options: **100 char max** for `/bankr` and `/ask`. Use `!bankr` or @mention for longer prompts.
- Message limit: 2000 chars. We truncate with `[:2000]`.

**Implemented:**
- 401 handling in send_prompt
- `cancelled` status in poll loop
- Clearer slash descriptions (mention 100 char limit, suggest !bankr for longer)

**Possible upgrades:**
- `threadId` for multi-turn context per user (Bankr supports it)
- `richData` parsing (charts, token_info) for embeds
- Deploy: consider `defer` + `edit_original_response` for consistency (currently uses `send_message` + `followup`)

---

## Debug Scan Upgrades (from MAIN_ISSUES)

Ideas to improve robustness and performance (not critical fixes):

- **Logging:** Add structured logging to `except Exception` blocks instead of silent pass
- **Cache limits:** TTLCache or LRU with maxsize for events.py, alerts __init__.py
- **Address validation:** Full ETH checksum validation for /add, /ca, /scan
- **Bankr multi-user:** Encrypted storage for user-connected Bankr API keys (Telegram)
- **Config safety:** Redact secrets in config __repr__ to avoid accidental log leaks

---

## Completed

- ✅ Wallet tracking
- ✅ Meme coin scanner (`/ca`)
- ✅ Honeypot check in `/ca` (Honeypot.is API)
- ✅ Insider detection (`/scan`)
- ✅ Discord commands
- ✅ Bankr AI
