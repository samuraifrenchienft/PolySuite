# Prediction Suite (formerly PolySuite)

A prediction market monitoring bot for Polymarket with wallet tracking, arbitrage detection, and AI integration.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your API keys
# Edit config.json with your settings

# Run
python main.py discord    # Start Discord bot
python main.py monitor    # Run market monitor
```

## Discord Commands

| Command | Description |
|---------|-------------|
| `/add <address>` | Add wallet to track (max 10) |
| `/remove <address>` | Remove wallet |
| `/status` | See tracked wallets |
| `/scan <address>` | Check wallet for suspicious activity |
| `/ca <address>` | Scan meme coin contract address |
| `/bankr <question>` | Ask Bankr AI |
| `/ask <question>` | Ask general AI |
| `/deploy` | Deploy token via Bankr |

## Features

- **Wallet Tracking** - Track wallets, get alerts on trades
- **Smart Money Detection** - Identify high-performing wallets
- **Arbitrage Detection** - Find cross-market opportunities
- **Meme Coin Scanner** - Scan contract addresses (DexScreener, safety score)
- **Insider Detection** - Detect suspicious wallet activity (fresh wallets, large trades)
- **Convergence Alerts** - When multiple tracked wallets are in the same market
- **Discord + Telegram Alerts** - Real-time notifications

## Configuration

Edit `config.json`:
```json
{
  "win_rate_threshold": 60.0,
  "alert_cooldown": 300
}
```

Edit `.env`:
```
DISCORD_BOT_TOKEN=your_token
DISCORD_APPLICATION_ID=your_app_id
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_id
BANKR_API_KEY=your_key
```

**Bankr:** Enable Agent API at [bankr.bot/api](https://bankr.bot/api). Free tier: 100 messages/day.

## Requirements

- Python 3.10+
- Internet connection (Polymarket API)
