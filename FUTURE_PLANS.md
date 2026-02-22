# PolySuite Future Plans

## Current Design (Simplified)

### How It Works
1. Users add wallets they want to track via `/add <address>` command
2. Bot monitors those specific wallets for new trades
3. Alerts when:
   - **Whale Trade** - tracked wallet opens new position
   - **Convergence** - multiple tracked wallets in same market
4. No leaderboard import - keeps it simple

### Alerts We Have
- 🐋 Whale Trade Alerts (NEW!)
- 🎯 Convergence Alerts
- 🆕 New Markets
- 📈 Volume Spikes
- ⏰ Expiring Soon
- Arbitrage Opportunities
- Crypto Prices (CoinGecko)


---

## Phase 2: Advanced Features

### Priority 1: Token Scanner (Discord)
- Auto-detect token/contract addresses in Discord chat
- Fetch and display: price, volume, liquidity, market details

### Priority 2: Copy Trading
- Auto-mirror trades from followed wallets
- Configurable position sizing
- Risk controls

### Priority 3: Revenue Share (Builder Program)
- Apply for Polymarket Builder Program
- Earn 35% of fees from volume routed through bot


---

## Research Notes

### Competitors/Vamp Sources
- **Lute**: Social trading, Discord bot, 35% revenue share, token scanning
- **Stand.trade**: Whale alerts, copy trading, free
- **Polycule**: Telegram copy trading, 1% fee
- **Polywhaler**: Whale tracking, $10K+ trades with AI
- **PolyWatch**: Free whale alerts

### APIs Available
- Polymarket CLOB: Trading execution
- Polymarket WebSocket: Real-time data
- Polymarket Builder Program: Revenue (35%)
- CoinGecko: Crypto prices (integrated)


---

## Completed Features
- ✅ Polymarket market monitoring
- ✅ Wallet tracking (user-added)
- ✅ Whale trade alerts (when tracked wallets trade)
- ✅ Convergence alerts
- ✅ New market alerts
- ✅ Category filtering (sports, tech, business, economics, science, weather, pop_culture, crypto)
- ✅ Discord + Telegram alerts
- ✅ Bankr AI integration (/bankr command)
- ✅ Token Scanner (auto-detect addresses in Discord)
- ✅ Health checks & backups
