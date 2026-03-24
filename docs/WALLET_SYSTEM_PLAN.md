# PolySuite Wallet Intelligence System - Research & Implementation Plan

## Executive Summary

This document outlines a comprehensive wallet tracking and scoring system for PolySuite. Based on research of existing smart money tracking systems and best practices from the prediction market and crypto trading communities, we propose a three-tier system (Watch → Vetted → Elite) with a weighted scoring algorithm, comprehensive data tracking, and an improved dashboard UI.

---

## Part 1: Research Findings

### 1.1 Existing Systems Analysis

| System | Key Approach | Strengths |
|--------|--------------|-----------|
| **GMGN.ai / Smart Money Follower** | Top wallets by profit, leaderboard ranking | Simple, proven |
| **Nansen Smart Money** | Top 5000 by realized profit + winrate | Volume-weighted win rates |
| **Smartclaw** | Cross-protocol tracking, volume-weighted winning rate | Consensus scoring, volume metrics |
| **Volfefe (Polymarket)** | Anomaly detection, ML-based smart money detection | Advanced pattern detection |
| **OpenClaw Bot** | Whale tracking, Smart Money Index (SMI) | Real-time signals, conviction scoring |

### 1.2 Key Scoring Principles (from research)

1. **Volume-Weighted Metrics**: A wallet with $100K at 55% win rate is more valuable than one with $100 at 60%
2. **Time-Decay**: Recent performance matters more than lifetime stats (7d > 14d > 30d > lifetime)
3. **Consensus**: Multiple independent signals = higher confidence
4. **Acceleration**: Is the wallet's activity increasing or decreasing?
5. **Category Specialization**: Wallets that specialize in specific categories have higher conviction

### 1.3 Pattern Recognition

Best systems track:
- **Temporal patterns**: Time of day, day of week trading preferences
- **Odds preferences**: Do they bet at <20%, 20-50%, 50-80%, >80%?
- **Hold duration**: Short-term vs position traders
- **Size consistency**: Fixed amounts vs variable sizing
- **Category concentration**: Politics, Sports, Crypto, Entertainment

---

## Part 2: Proposed System Architecture

### 2.1 Three-Tier System

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          ELITE TIER                                     │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ • Score >= 80 consistently (30+ days)                           │   │
│  │ • Win rate >= 60% on 7d/14d                                    │   │
│  │ • Current win streak >= 5                                      │   │
│  │ • Volume-weighted win rate >= 40%                              │   │
│  │ • Category specialization with >65% win rate                   │   │
│  │ → Auto-promoted from Vetted when criteria met                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────┤
│                         VETTED TIER (Active Copy)                       │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ • Passes all minimum thresholds                                │   │
│  │ • Score >= 50                                                  │   │
│  │ • Not flagged as bot/farmer/high-loss                         │   │
│  │ • Being actively copied                                        │   │
│  │ → Drops to Watch if:                                           │   │
│  │   - Score drops below 40                                       │   │
│  │   - 5+ consecutive losses                                     │   │
│  │   - 7-day activity threshold breached                          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────┤
│                          WATCH TIER                                     │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ • New wallets being evaluated                                   │   │
│  │ • Near-qualifying (meets some criteria, not all)              │   │
│  │ • Previously Vetted but dropped in score                      │   │
│  │ • Wallets flagged for review                                    │   │
│  │ → Auto-promotes to Vetted when score crosses >= 50            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Weighted Score Algorithm

| Metric | Weight | Description |
|--------|--------|-------------|
| **7-Day Win Rate** | 20% | Most recent performance |
| **14-Day Win Rate** | 15% | Recent performance |
| **30-Day Win Rate** | 10% | Medium-term performance |
| **Lifetime Win Rate** | 5% | Historical baseline |
| **Current Win Streak** | 15% | Momentum indicator |
| **Max Win Streak** | 5% | Peak performance |
| **7-Day PnL** | 15% | Recent profitability |
| **Volume-Weighted Win Rate** | 10% | Quality of wins |
| **Activity Consistency** | 5% | Regularity of trading |

### 2.3 Removal Triggers

| Condition | Action |
|-----------|--------|
| Score drops below 40 | Vetted → Watch |
| 5+ consecutive losses | Vetted → Watch (flag for review) |
| No trades in 14 days | Vetted → Watch (mark inactive) |
| Flagged as bot/farmer | Vetted → Watch immediately |
| Score drops below 25 | Watch → Remove entirely |
| 10+ consecutive losses | Watch → Remove |

### 2.4 Promotion Criteria

| From → To | Criteria |
|-----------|----------|
| Watch → Vetted | Score >= 50 for 7+ days AND win rate >= 50% AND not flagged |
| Vetted → Elite | Score >= 80 for 30+ days AND win rate >= 60% AND streak >= 5 |

---

## Part 3: Data Points to Track

### 3.1 Core Metrics (existing + enhanced)

| Field | Description | Source |
|-------|-------------|--------|
| `total_trades` | Total resolved trades | API |
| `total_wins` | Number of winning trades | Calculated |
| `total_losses` | Number of losing trades | Calculated |
| `win_rate` | Win rate percentage | Calculated |
| `volume_weighted_win_rate` | Wins weighted by USD value | Calculated |
| `total_pnl` | Total profit/loss | API |
| `avg_bet_size` | Average USD per trade | Calculated |
| `trades_per_day` | Activity rate | Calculated |

### 3.2 New Data Points

| Field | Description | Calculation |
|-------|-------------|-------------|
| `specialty_category` | Primary category | Max volume + win rate |
| `specialty_category_2` | Secondary category | 2nd best performing |
| `specialty_win_rate` | Win rate in specialty | Filtered trades |
| `avg_hold_duration_hours` | Average hold time | Timestamp diff |
| `preferred_odds_range` | Odds preference | Bucket trades by price |
| `size_consistency` | Bet size variance | Std dev / mean |
| `trading_hours` | Primary trading hours | Histogram of timestamps |
| `trading_days` | Preferred days | Day of week histogram |
| `recent_7d_trades` | Trades in last 7 days | Filter by time |
| `recent_7d_win_rate` | 7-day win rate | Filtered + calculated |
| `recent_7d_pnl` | 7-day PnL | Filtered + calculated |
| `recent_14d_trades` | Trades in last 14 days | Filter by time |
| `recent_14d_win_rate` | 14-day win rate | Filtered + calculated |
| `consecutive_losses` | Current loss streak | Sequence analysis |
| `max_consecutive_losses` | Worst losing streak | Sequence analysis |
| `last_trade_date` | Most recent trade | Max timestamp |
| `days_inactive` | Days since last trade | Now - last_trade |

### 3.3 Pattern Analysis

```
PATTERNS TO EXTRACT:
├── Time Patterns
│   ├── Peak trading hours (00-06, 06-12, 12-18, 18-24 UTC)
│   ├── Peak trading days (weekday vs weekend)
│   └── Recent activity acceleration
│
├── Odds Patterns
│   ├── Low odds (<20%) - long shots
│   ├── Medium odds (20-50%) - moderate confidence
│   ├── High odds (50-80%) - favorites
│   └── Near certain (>80%) - safeties
│
├── Category Patterns
│   ├── Politics
│   ├── Sports
│   ├── Crypto
│   ├── Business/Economics
│   ├── Entertainment
│   └── Science/Tech
│
└── Size Patterns
    ├── Conservative (consistent small)
    ├── Aggressive (variable large)
    ├── Scaling (grows with confidence)
    └── Fixed (same size always)
```

---

## Part 4: UI Improvements

### 4.1 Clickable Specialty Counter

**Current**: Simple count of specialty markets

**Proposed**:
- Click to open modal with:
  - Category breakdown (pie chart)
  - Win rate per category
  - Total volume per category
  - Recent trades in each category
  - Best performing category highlight

### 4.2 Clear Copy Targets

Each wallet display should show:
```
┌────────────────────────────────────────────────────┐
│ 0x1234...abcd  "PoliWhale"           [ELITE]     │
│ ┌────────────────────────────────────────────────┐│
│ │ Win Rate: 68%  │  Streak: 7  │  Score: 85    ││
│ │ 7d: +$2,340    │  Vol: $145K  │  Risk: LOW   ││
│ │ Categories: [Politics ★] [Crypto ★★]          ││
│ └────────────────────────────────────────────────┘│
│ Why: 7-win streak, 72% in politics, consistent  │
│ Last active: 2 hours ago                         │
└────────────────────────────────────────────────────┘
```

### 4.3 Filter Improvements

| Filter | Options |
|--------|---------|
| Tier | All / Elite / Vetted / Watch |
| Category | Any / Politics / Sports / Crypto / etc. |
| Min Score | Slider 0-100 |
| Min Win Rate | Slider 0-100% |
| Max Loss Rate | Slider 0-100% |
| Activity | Active (7d) / Active (14d) / Any |
| Patterns | Morning / Afternoon / Evening / Night |
| Risk Level | Conservative / Moderate / Aggressive |

### 4.4 Pattern Dashboard

New tab showing aggregate patterns across all tracked wallets:
- **Time Heatmap**: When are the best opportunities?
- **Category Performance**: Which categories have highest win rates?
- **Odds Distribution**: What odds range wins most?
- **Volume Trends**: Is smart money flow increasing?

---

## Part 5: Implementation Scope

### Phase 1: Data Infrastructure (Priority: HIGH)

1. **Database Schema Updates**
   - Add new columns to wallets table
   - Create scoring_history table
   - Create tier_log table (promotion/demotion tracking)

2. **Wallet Model Updates**
   - Add all new data point fields
   - Add tier field (watch/vetted/elite)
   - Add score history tracking

### Phase 2: Scoring Engine (Priority: HIGH)

1. **Enhanced Classifier**
   - Implement weighted scoring algorithm
   - Add tier transition logic
   - Add pattern extraction

2. **Automated Management**
   - Run tier checks on schedule
   - Handle promotions/demotions
   - Log all changes

### Phase 3: Dashboard UI (Priority: MEDIUM)

1. **Tier Display**
   - Visual distinction (color-coded badges)
   - Filter by tier

2. **Enhanced Modals**
   - Clickable specialty with category breakdown
   - Pattern summary in wallet detail
   - Clear "why recommended" text

3. **New Pattern Tab**
   - Aggregate visualizations
   - Time heatmap
   - Category performance chart

---

## Part 6: API Endpoints

### New/Updated Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/wallets/tiers` | GET | Get wallets by tier |
| `/api/wallets/<addr>/patterns` | GET | Get pattern analysis for wallet |
| `/api/wallets/<addr>/promote` | POST | Manual promote to next tier |
| `/api/wallets/<addr>/demote` | POST | Manual demote to lower tier |
| `/api/wallets/<addr>/refresh` | POST | Force re-analysis |
| `/api/patterns/aggregate` | GET | Get aggregate patterns |
| `/api/scoring/run` | POST | Run scoring (manual trigger) |

---

## Part 7: Acceptance Criteria

### Must Have (MVP)

- [ ] Three-tier system (Watch/Vetted/Elite) with clear visual distinction
- [ ] Weighted scoring algorithm implemented
- [ ] Auto-promotion/demotion based on thresholds
- [ ] Category specialization tracking
- [ ] 7d/14d/30d stats available
- [ ] Clickable specialty showing category breakdown
- [ ] Clear "why recommended" for each wallet

### Should Have

- [ ] Pattern tracking (time, odds, size)
- [ ] Manual override for tier changes
- [ ] Scoring history visible
- [ ] Aggregate pattern dashboard

### Nice to Have

- [ ] ML-based anomaly detection
- [ ] Cross-wallet consensus signals
- [ ] Real-time alerts for tier changes

---

## Appendix: Database Schema Changes

### New Columns for Wallets Table

```sql
-- Tier management
tier TEXT DEFAULT 'watch' CHECK(tier IN ('watch', 'vetting', 'vetted', 'elite'))
tier_changed_at TEXT
tier_change_reason TEXT

-- Scoring
composite_score REAL DEFAULT 0
score_7d REAL DEFAULT 0
score_14d REAL DEFAULT 0
score_30d REAL DEFAULT 0
last_scored_at TEXT

-- Streaks
consecutive_losses INTEGER DEFAULT 0
max_consecutive_losses INTEGER DEFAULT 0
last_trade_at TEXT
days_inactive INTEGER DEFAULT 0

-- Category specialization
specialty_category TEXT
specialty_category_2 TEXT
specialty_win_rate REAL DEFAULT 0
specialty_volume REAL DEFAULT 0

-- Betting patterns
avg_hold_duration_hours REAL DEFAULT 0
preferred_odds_range TEXT  -- 'low', 'medium', 'high', 'very_high'
size_consistency REAL DEFAULT 0  -- 0=variable, 1=consistent

-- Volume-weighted metrics
volume_weighted_win_rate REAL DEFAULT 0
recent_7d_volume REAL DEFAULT 0
recent_14d_volume REAL DEFAULT 0
recent_7d_trades INTEGER DEFAULT 0
recent_14d_trades INTEGER DEFAULT 0
recent_7d_win_rate REAL DEFAULT 0
recent_14d_win_rate REAL DEFAULT 0
recent_7d_pnl REAL DEFAULT 0
recent_14d_pnl REAL DEFAULT 0

-- Pattern tracking (stored as JSON)
trading_hours TEXT  -- JSON: {"0-6": 10, "6-12": 25, ...}
trading_days TEXT   -- JSON: {"mon": 15, "tue": 20, ...}
odds_distribution TEXT  -- JSON: {"low": 20, "medium": 40, ...}
```

### New Tables

```sql
-- Scoring history
CREATE TABLE scoring_history (
    id INTEGER PRIMARY KEY,
    wallet_address TEXT,
    scored_at TEXT,
    composite_score REAL,
    win_rate REAL,
    streak INTEGER,
    tier TEXT,
    FOREIGN KEY (wallet_address) REFERENCES wallets(address)
);

-- Tier change log
CREATE TABLE tier_log (
    id INTEGER PRIMARY KEY,
    wallet_address TEXT,
    changed_at TEXT,
    old_tier TEXT,
    new_tier TEXT,
    reason TEXT,
    score_at_change REAL,
    FOREIGN KEY (wallet_address) REFERENCES wallets(address)
);
```

---

*Document Version: 1.0*
*Created: 2026-03-16*
