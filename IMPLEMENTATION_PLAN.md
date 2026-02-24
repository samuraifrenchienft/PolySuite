# Prediction Suite - Research & Implementation Plan

## Research Summary (Feb 2026)

### 1. Honeypot Detection APIs

| Service | Free Tier | API | Chains |
|---------|-----------|-----|--------|
| DexScreener | Yes | Yes | All (we use this) |
| TokenSniffer | Limited | Yes (paid) | 11 chains |
| HoneypotScan | Yes | No | ETH, Polygon, Arb |

**Current:** We use DexScreener for basic token data
**Plan:** Add TokenSniffer for honeypot detection (needs API key)

### 2. Copy Trading

**Implementation:**
```python
from py_clob_client.client import ClobClient

# Setup
client = ClobClient(
    "https://clob.polymarket.com",
    key=private_key,
    chain_id=137,  # Polygon
)
client.set_api_creds(client.create_or_derive_api_creds())

# Copy trade
client.create_order(OrderArgs(
    token_id=token_id,
    price=0.6,
    size=10,  # Amount
    side="BUY"
))
```

**Requirements:**
- Polymarket account with USDC
- Private key
- Builder code (for revenue)

### 3. API Rate Limits

| API | Endpoint | Limit |
|-----|----------|-------|
| Data API | General | 1,000 req/10s |
| Data API | /positions | 150 req/10s |
| Data API | /trades | 200 req/10s |
| Gamma API | General | 4,000 req/10s |
| CLOB API | General | 9,000 req/10s |

**Optimization:**
- Cache market data (60s TTL)
- Batch position queries
- Use WebSocket for real-time (future)

### 4. Builder Program

- Apply: builders.polymarket.com
- Get builder code
- Add to all trades for revenue

### 5. User Points & Fee System (Lute-style)

**Lute's Model:**

| Feature | Details |
|---------|---------|
| **Referral Fees** | 25-35% of trading fees from referrals |
| **Call/Share** | 35% fee share for making trading calls |
| **Send** | 25% fee share for sharing tokens |
| **Levels** | Bronze → Silver → Sapphire → Ruby → Diamond → Emerald → Master |
| **Cashback** | Up to 35% cashback based on rank |

**Referral Tiers:**
- Level 1 (Direct): 30% of user's fees
- Level 2 (Secondary): 3% of user's fees  
- Level 3 (Extended): 2% of user's fees

**XP/Points System:**
- Earn XP for: trades, referrals, sharing tokens
- XP unlocks ranks with better cashback
- Example: Lute has Bronze→Diamond ranks

**Implementation Options:**

1. **Simple (Free)**
   - Track user points in database
   - No real money, just gamification
   - Leaderboards for engagement

2. **With Fees (Revenue)**
   - Builder code → earn from volume
   - Referral tracking → earn % from users
   - Requires: Builder code + fee structure

3. **Hybrid**
   - Free points system for engagement
   - Optional paid tier for referral earnings
   - Apply for Builder Program for revenue

---

## Implementation Plan

### Phase 1: Fix & Verify (This Week)

#### Issues to Fix
- [ ] Test whale alerts working
- [ ] Test convergence alerts
- [ ] Test `/ca`, `/scan`, `/add` commands

#### Optimization
- [ ] Add Redis/memory cache for API responses
- [ ] Implement rate limit handling
- [ ] Add retry logic

### Phase 2: Scanner Upgrades

#### Meme Coin Scanner (`/ca`)
- [ ] Add TokenSniffer integration
- [ ] Show: honeypot risk, score (0-100)
- [ ] Show: top holders with %
- [ ] Liquidity lock status

#### Wallet Scanner (`/scan`)
- [ ] Already working (Polymarket data)
- [ ] Add: recent trade history
- [ ] Add: market categories

### Phase 3: Trading (Future)

#### Copy Trading
- [ ] Install py-clob-client
- [ ] Add trade execution
- [ ] Position sizing config
- [ ] Risk controls (max position)

#### Builder Program
- [ ] Apply for builder code
- [ ] Integrate into trading

### Phase 4: Points & Referrals

#### Research Findings

**How Other Bots Do It:**

| Bot | Type | Points | Referral |
|-----|------|--------|----------|
| Lute | Trading | XP for actions | 25-35% fees |
| WL.BOT | Trading | N/A | Up to 90% of 0.1% fee |
| Tipsy | Casino | $0.01 per transaction | Lifetime |
| Gunbot | Trading | N/A | $25-100 per license |
| Points.bot | General | Message/voice XP | Custom |

**Key Features from Research:**

1. **Daily Rewards** - Login once/day for points
2. **Streaks** - Consecutive days = bonus multiplier
3. **Challenges** - Complete tasks for bonus points
4. **Leaderboards** - Weekly/monthly/all-time
5. **Roles** - Unlock Discord roles at milestones

**Referral Tiers (Industry Standard):**
- Level 1: 25-35% (direct)
- Level 2: 3-5%
- Level 3: 2-3%

#### Design

**Recommendation: Start Free for Engagement**

- Not for revenue initially
- Focus on user engagement
- Add revenue later via Builder Program

#### Points System

**Earning Points:**
| Action | Points |
|--------|--------|
| Daily login | +5 |
| Add wallet | +10 |
| Use /ca scanner | +2 |
| Use /scan | +2 |
| Get whale alert | +1 |
| Invite friend | +50 |

**Streaks:**
- Day 1: 5 pts
- Day 2: 7 pts (+2)
- Day 3: 9 pts (+2)
- Day 4: 11 pts (+2)
- Day 5+: 13 pts max (+2)

**Ranks:**
| Rank | Points | Discord Role |
|------|--------|--------------|
| Bronze | 0 | None |
| Silver | 100 | 🔶 |
| Sapphire | 500 | 💎 |
| Ruby | 1,000 | 🔴 |
| Diamond | 5,000 | 💠 |
| Emerald | 10,000 | ✳️ |
| Master | 25,000 | 👑 |

#### Commands

| Command | Description |
|---------|-------------|
| `/points` | Show balance & rank |
| `/leaderboard` | Top 10 users |
| `/invite` | Get referral code |
| `/claim` | Daily login bonus |

#### Referral System

- Unique 8-char code per user
- Track: who referred whom
- Tiers:
  - Level 1: Referrer gets 25% of points from referred
  - Level 2: 5%
  - Level 3: 3%

#### Database Schema

```sql
-- Users
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    discord_id TEXT UNIQUE,
    username TEXT,
    points INTEGER DEFAULT 0,
    rank TEXT DEFAULT 'Bronze',
    streak_days INTEGER DEFAULT 0,
    last_claim DATE,
    referral_code TEXT UNIQUE,
    referred_by TEXT,
    discord_role TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Points history
CREATE TABLE points_log (
    id INTEGER PRIMARY KEY,
    discord_id TEXT,
    points INTEGER,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Daily claims
CREATE TABLE daily_claims (
    id INTEGER PRIMARY KEY,
    discord_id TEXT,
    claimed_at DATE,
    streak_count INTEGER DEFAULT 0
);

-- Referrals
CREATE TABLE referrals (
    id INTEGER PRIMARY KEY,
    referrer_id TEXT,
    referred_id TEXT,
    points_earned REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Implementation Order

1. Database setup
2. Points tracking middleware (auto-add on actions)
3. `/points` command
4. `/leaderboard` command (weekly/monthly/all-time tabs)
5. `/claim` command (daily login with streak)
6. `/invite` command
7. Role rewards at milestones

---

## Questions Before Coding

---

## API Keys Needed

| Service | Status | Key |
|---------|--------|-----|
| DexScreener | ✅ Using free API | N/A |
| TokenSniffer | ❌ Not integrated | Need Pro plan |
| Polymarket CLOB | ❌ Not integrated | Need account |
| Builder Program | ❌ Not applied | Need application |

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/alerts/meme_scanner.py` | Add TokenSniffer |
| `src/market/trading.py` | NEW: Trade execution |
| `src/config/__init__.py` | Add trading config |
| `main.py` | Add trading commands |

---

## Quick Wins

1. **Cache**: Add 60s cache for market data → reduce API calls
2. **Retry**: Add exponential backoff for rate limits
3. **TokenSniffer**: Free tier may be enough for basic checks

---

## Database Schema (Points System)

```sql
-- Users table
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    discord_id TEXT UNIQUE,
    points INTEGER DEFAULT 0,
    rank TEXT DEFAULT 'Bronze',
    referral_code TEXT UNIQUE,
    referred_by TEXT,
    total_earned REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Points history
CREATE TABLE points_log (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    points INTEGER,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Referrals
CREATE TABLE referrals (
    id INTEGER PRIMARY KEY,
    referrer_id INTEGER,
    referred_id INTEGER,
    earned REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Resources

- Docs: docs.polymarket.com
- CLOB Client: github.com/Polymarket/py-clob-client
- Rate Limits: docs.polymarket.com/api-reference/rate-limits
- Builder: builders.polymarket.com
