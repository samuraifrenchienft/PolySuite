# Wallet Tuning Guide — Match Settings to a Known-Good Wallet

Use this to test with a wallet you trust and tune config so similar wallets pass vet, avoid cleanup, and get the right labels.

---

## 1. Current Version

You have local changes (vet/classify fixes, cleanup, discovery). They’re the latest in your workspace. To keep them:

```powershell
cd c:\Users\AbuBa\Desktop\PolySuite
git add -A
git commit -m "Wallet fixes: vet/classify timeouts, cleanup, discovery"
```

---

## 2. Test Workflow

### Step A: Add your known-good wallet

- **Dashboard**: Settings → Bulk Import, or single Add
- **CLI**: `python main.py add 0xYourAddress "GoodTrader"`

### Step A2: Profile it (CLI — recommended)

Run vet and get metrics + config suggestions in one shot:

```powershell
python main.py profile 0xYourGoodWalletAddress
```

This prints `win_rate`, `total_pnl`, `roi_pct`, `specialty_category`, and suggested config values.

### Step B: Vet it (single) — Dashboard

- Click **Vet** on that row.
- In the toast / response, note:
  - `passed` (true/false)
  - `win_rate`, `total_pnl`, `roi_pct`
  - `specialty_category`
  - `issues` (if any)

### Step C: Classify it

- Click **Classify** (or run on just that wallet).
- Note:
  - `classification` (e.g. good, excellent, average)
  - `win_rate`, `total_trades`, `total_volume`
  - `specialty_category`

### Step D: Read raw output (optional)

Use the browser Network tab or run:

```powershell
# Vet
python -c "
from src.config import Config
from src.wallet.storage import WalletStorage
from src.wallet.vetting import WalletVetting
from src.market.api import APIClientFactory
from src.config.paths import DB_PATH

cfg = Config()
st = WalletStorage(db_path=DB_PATH)
af = APIClientFactory(cfg)
vetter = WalletVetting(af, config=cfg)
addr = '0xYOUR_GOOD_WALLET_HERE'
r = vetter.vet_wallet(addr, min_bet=10, platform='polymarket')
if r:
    for k, v in r.items():
        print(f'{k}: {v}')
else:
    print('No trades or vet failed')
"
```

---

## 3. Config Keys to Tune

Set these in `config.json` so wallets similar to your good one pass vet, avoid cleanup, and get the right specialty.

### Cleanup (who gets removed)

| Key | Default | Meaning | Tune to |
|-----|---------|---------|---------|
| `wallet_cleanup_min_win_rate` | 40 | Remove if win_rate < this | Set below your good wallet’s win_rate (e.g. 35) |
| `wallet_cleanup_grace_days` | 7 | Don’t remove wallets younger than this | Increase if you want more time before cleanup |

### Vetting (who passes single/bulk vet)

| Key | Default | Meaning | Tune to |
|-----|---------|---------|---------|
| `vet_min_trades_won` | 0 | Min total wins to pass baseline | 0 = off; or set below your good wallet’s wins |
| `vet_max_losses` | 0 | Max total losses (0 = off) | 0 unless you want a hard cap |
| `vet_min_pnl` | 0 | Min total PnL ($) | 0 or set below your good wallet’s total_pnl |
| `vet_min_roi_pct` | 0 | Min ROI (%) | 0 or set below your good wallet’s roi_pct |
| `vet_min_conviction` | 0 | Min conviction score | 0 or set below your good wallet |
| `vet_min_recent_wins` | 3 | Min wins in recent window | Set ≤ your good wallet’s recent wins |
| `vet_recent_wins_window` | 10 | Size of recent-wins window | Keep or adjust to match activity |
| `vet_min_specialty_wins` | 4 | Min wins in top category for specialty | Set ≤ your good wallet’s category wins |
| `vet_min_specialty_trades` | 10 | Min trades in top category | Set ≤ your good wallet’s category trades |
| `vet_specialty_window_days` | 14 | Rolling window for specialty | Match how “recent” you care about |

### Discovery (who gets auto-added)

| Key | Default | Meaning |
|-----|---------|---------|
| `wallet_discovery_max_wallets` | 150 | Max tracked wallets |
| `wallet_discovery_max_new` | 15 | New wallets per discovery run |
| `wallet_discovery_interval_sec` | 1800 | How often discovery runs |

### High-performer / smart money

| Key | Default | Meaning |
|-----|---------|---------|
| `win_rate_threshold` | 55 | Win rate above this = “high performer” |
| `min_trades_for_high_performer` | 10 | Min trades to qualify |
| `win_streak_badge_threshold` | 5 | Max win streak ≥ this = badge |

---

## 4. Example: Tuning for a Good Wallet

Suppose your good wallet has:

- `win_rate`: 62%
- `total_pnl`: 1,200
- `roi_pct`: 18
- `total_wins`: 25
- `specialty_category`: crypto
- `issues`: []

To favor similar wallets:

```json
{
  "wallet_cleanup_min_win_rate": 35,
  "vet_min_trades_won": 0,
  "vet_min_pnl": 0,
  "vet_min_roi_pct": 0,
  "vet_min_recent_wins": 2,
  "win_rate_threshold": 55
}
```

This keeps vet gates off (0) so baseline + specialty logic decides, and only removes wallets below 35% win rate during cleanup.

---

## 5. Restart After Changing Config

```powershell
# If dashboard is running
# Stop it (Ctrl+C), then:
python main.py dashboard
# or with collector:
python main.py run
```

Config is reloaded on each discovery/cleanup cycle; some changes may need a full restart.
