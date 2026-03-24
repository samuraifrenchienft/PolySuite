# PolySuite Specialty & Wallet Finder Implementation Plan

## Executive Summary

This document provides a concrete implementation plan for:
1. **Specialty logic recalibration** – stricter requirements, no win-streak in specialty
2. **Separate Win-Streak (WS) badge** – distinct from SM/SP
3. **Points system to penalize farming** – downweight low-profit wallets
4. **Remove execution/copy code** – pure wallet finder

---

## 1. Implementation Plan with Concrete Changes

### 1.1 Fix Specialty Logic

**Current state:** `vetting.py` uses `vet_min_specialty_wins` (5), `vet_min_specialty_trades` (8), `vet_min_specialty_category_pct` (50), `vet_min_specialty_profit_pct` (15). Specialty is merged with "hot streak" via `specialty_or_hot_streak_note`. The `reliability_score` includes `streak_score` which conflates win streak with specialty.

**Required changes:**

| File | Change |
|------|--------|
| `src/config/__init__.py` | Update `vet_min_specialty_wins` default **5 → 4** (spec says "more than 3"), then add `vet_min_specialty_wins` **≥ 4** in config. |
| `src/config/__init__.py` | Add `vet_min_specialty_category_pct` (50), `vet_min_specialty_profit_pct` (15) – already present. |
| `src/wallet/vetting.py` | **Specialty logic:** Require `cw > min_spec_wins` (strictly > 3). Use `min_spec_wins = 4` (default). |
| `src/wallet/vetting.py` | **Specialty ROI:** Use **category-specific ROI** for the specialty category, not global `roi_pct`. If category PnL unavailable, fall back to global ROI. |
| `src/wallet/vetting.py` | **Remove win streak from specialty:** Ensure `specialty_or_hot_streak_note` does NOT conflate specialty with win streak. Keep specialty as category-only; hot streak stays separate. |
| `src/wallet/vetting.py` | **Specialty gate:** Require `min_spec_wins >= 4` (configurable), `min_spec_trades >= 10`, `min_spec_category_pct >= 50`, `min_spec_profit_pct >= 15` |

**Concrete spec:**
- `vet_min_specialty_wins`: **4** (more than 3)
- `vet_min_specialty_trades`: **10** (decent amount in category)
- `vet_min_specialty_category_pct`: **50** (category focus)
- `vet_min_specialty_profit_pct`: **15** (meaningful ROI)
- Wins in a row should **NOT** determine specialist – category focus + profit only

**Code change:** In `vetting.py` lines 381–396, replace `cw < min_spec_wins` with `cw <= min_spec_wins` (to require > 3 when min=4) or use `cw >= min_spec_wins` with `min_spec_wins = 4`. Currently `cw < min_spec_wins` with `min_spec_wins=5` means 4 wins is allowed. Spec says "more than 3" → `min_spec_wins = 4` and `cw >= min_spec_wins` is correct.

---

### 1.2 Add Separate Win-Streak (WS) Badge

**Current state:** `is_win_streak_badge` exists in `vetting.py` (line 324), `storage.py` (migration), `Wallet` model. `win_streak_badge_threshold` is 5. **Not displayed** in dashboard – only SM and SP are shown.

**Required changes:**

| File | Change |
|------|--------|
| `src/dashboard/templates/index.html` | Add `isWinStreakBadge: !!w.is_win_streak_badge` to wallet normalization (around line 1676). |
| `src/dashboard/templates/index.html` | Add WS badge in badge column: `${w.isWinStreakBadge ? '<span class="badge badge-win-streak">WS</span>' : ''}` |
| `src/dashboard/templates/index.html` | Add CSS class `.badge-win-streak` (e.g. amber/orange to distinguish from SM/SP). |
| `src/wallet/storage.py` | Ensure `update_wallet_vetting` persists `is_win_streak_badge` (add to `update_wallet` if not already). |
| `src/wallet/vetting.py` | Ensure vetting output includes `is_win_streak_badge` and flows to wallet storage. |
| `src/agent.py` / `main.py` | When vetting results are saved, persist `is_win_streak_badge`. |

**Storage:** `update_wallet_vetting` does not include `is_win_streak_badge`. Need to add it to `update_wallet` flow or extend `update_wallet_vetting` to accept `is_win_streak_badge`.

**Filter:** Add optional filter "Win Streak" in dashboard filters (like Smart Money, Specialty).

**Data flow note:** Vetting (`vet_wallet`) returns `is_win_streak_badge` but vetting results are not routinely persisted. The dashboard's **Analyze** flow uses the **classifier** (not vetting). The classifier has `max_win_streak` but does not set `is_win_streak_badge`. Therefore:
- In `api_wallets/analyze`, add: `existing.is_win_streak_badge = score.max_win_streak >= config.win_streak_badge_threshold`
- This ensures WS badge is set when wallets are analyzed via the dashboard.

---

### 1.3 Points System to Penalize Farming

**Current state:** `classifier.py` has `FARMER_MIN_TRADES = 500`, `FARMER_MAX_AVG_PNL = 0.01`, `is_farmer` flag. Config has `farming_min_profit_pct` (5), `farming_zero_weight_below_pct` (2). These are **not** used in scoring.

**Required changes:**

| File | Change |
|------|--------|
| `src/config/__init__.py` | Add `farming_avg_profit_pct_min` (e.g. 5), `farming_penalty_pct` (e.g. 20), `farming_score_cap` (e.g. 60). |
| `src/wallet/classifier.py` | In `_calculate_score` add penalty: if `avg_pnl_per_trade` / `avg_trade_size` * 100 < `farming_min_profit_pct`, apply `farming_penalty_pct` penalty. |
| `src/wallet/classifier.py` | Add high-volume + low-profit check: if `total_volume > 50k` and `roi_pct < 5`, apply `farming_penalty_pct`. |
| `src/wallet/classifier.py` | Cap score for wallets with many tiny wins: if `avg_pnl_per_trade < $2` and `total_wins > 20`, cap score at `farming_score_cap`. |
| `src/wallet/classifier.py` | Integrate `farming_min_profit_pct`, `farming_zero_weight_below_pct` from config into scoring. |

**Proposed formula:**
- `avg_profit_per_win_pct` = (total_pnl / total_volume) * 100 if total_volume > 0 else 0
- Penalty: if `avg_profit_per_win_pct < farming_min_profit_pct` (5), subtract `farming_penalty_pct` (20)
- Penalty: if `total_volume > 50000` and `roi_pct < 5`, subtract 15
- Penalty: if `avg_pnl_per_trade < 2` and `total_wins > 20`, cap score at 60

---

### 1.4 Remove Execution/Copy Code

**Identified copy/execution code to remove or disable:**

| File | Action |
|------|--------|
| `src/copy/engine.py` | **Remove or disable** – CopyEngine subscribes to RTDS trades and executes orders. |
| `src/copy/storage.py` | **Remove or disable** – Copy target storage. |
| `src/copy/__init__.py` | **Remove or disable** – Exports copy engine. |
| `src/alerts/trade_executor.py` | **Remove or disable** – TradeExecutor executes via Bankr. |
| `src/market/bankr.py` | **Remove or disable** – Bankr.bot execution client. |
| `src/market/rtds_client.py` | **Remove or disable** – RTDS WebSocket client used by CopyEngine. |
| `src/market/polymarket_clob.py` | **Remove or disable** – CLOB trading client. |
| `src/dashboard/app.py` | **Remove** copy API routes: `/api/copy/add`, `/api/copy/remove`, `/api/copy/list`, `/api/copy/toggle`. Remove copy UI imports. |
| `src/dashboard/templates/index.html` | **Remove** copy toggle column, copy targets count, copy-related JS. |
| `main.py` | **Remove** CopyEngine startup (around line 320). |

**Recommended approach:** Disable rather than delete initially:
- Add `copy_enabled: false` and `copy_removed: true` in config.
- In `main.py`, skip CopyEngine startup when `copy_removed` or `copy_enabled=false`.
- Add feature flag or stub for copy UI to hide it.

**Full removal:** Remove `src/copy/` directory, remove TradeExecutor imports, remove Bankr execution paths, remove copy dashboard routes and UI.

---

## 2. Updated Config Defaults

Apply these changes to `src/config/__init__.py` in `DEFAULT_CONFIG`:

```python
# Specialty (recalibrated): category focus + profit, NOT win streak
"vet_min_specialty_wins": 4,        # More than 3 wins (spec: > 3)
"vet_min_specialty_trades": 10,    # Decent amount in category (was 8)
"vet_min_specialty_category_pct": 50,
"vet_min_specialty_profit_pct": 15,
"vet_specialty_window_days": 14,
"vet_max_specialty_losses": 2,
"win_streak_badge_threshold": 5,
"farming_min_profit_pct": 5,
"farming_zero_weight_below_pct": 2,
"farming_penalty_pct": 20,
"farming_score_cap": 60,
"farming_avg_profit_pct_min": 5,
```

Add Config property accessors for new keys:
- `farming_penalty_pct`
- `farming_score_cap`
- `farming_avg_profit_pct_min`

---

## 3. Gap Analysis vs Current Implementation

| Requirement | Current | Gap |
|-------------|---------|-----|
| **Specialty: more than 3 wins** | `vet_min_specialty_wins=5` | Change to 4 (spec: > 3). |
| **Specialty: decent category focus** | `vet_min_specialty_trades=8` | Increase to 10. |
| **Specialty: meaningful ROI** | `vet_min_specialty_profit_pct=15` | Uses global ROI; consider category-specific ROI. |
| **Specialty: NOT win streak** | `reliability_score` includes streak; `specialty_or_hot_streak` merges | Decouple specialty from streak; hot streak stays separate. |
| **Win streak badge (WS)** | `is_win_streak_badge` exists, threshold 5 | Not displayed in dashboard; add WS badge. |
| **Farming penalty** | `farming_min_profit_pct`, `farming_zero_weight_below_pct` in config | Not used in classifier scoring. |
| **Farming: avg profit per win** | Classifier has `is_farmer` flag | No score penalty for low avg profit. |
| **Copy/execution removal** | CopyEngine, TradeExecutor, Bankr, RTDS active | Need to disable/remove. |

---

## 4. List of Copy/Execution Code to Remove or Disable

### 4.1 Copy Trading

| Path | Description |
|------|-------------|
| `src/copy/engine.py` | CopyEngine: RTDS trades → qualify → execute via CLOB |
| `src/copy/storage.py` | Copy target storage (JSON file) |
| `src/copy/__init__.py` | Copy module exports |

### 4.2 Trade Execution

| Path | Description |
|------|-------------|
| `src/alerts/trade_executor.py` | TradeExecutor: signals → Bankr API |
| `src/market/bankr.py` | Bankr.bot client for execute_polymarket_bet |
| `src/market/polymarket_clob.py` | Polymarket CLOB trading client |

### 4.3 Supporting Infrastructure

| Path | Description |
|------|-------------|
| `src/market/rtds_client.py` | RTDS WebSocket client (activity:trades) – used by CopyEngine |

### 4.4 Dashboard & Main Entry

| Path | Description |
|------|-------------|
| `src/dashboard/app.py` | Routes: `/api/copy/add`, `/api/copy/remove`, `/api/copy/list`, `/api/copy/toggle` |
| `src/dashboard/templates/index.html` | Copy toggle column, copy targets UI |
| `main.py` | CopyEngine startup (around line 320) |

### 4.5 References to Remove

- `src/alerts/formatter.py` – "copy-trade guidance" text (lines 289–303)
- `src/config/__init__.py` – `copy_enabled`, `copy_multiplier`, etc.
- `settings` in dashboard – `copy_enabled`, `copy_multiplier`

---

## 5. Optional: Pumpfun Coin Alert (Research Only)

- **Scope:** New pumpfun coins with specific specs – research only.
- **Not implemented** in this plan.

---

## 6. Implementation Order

1. **Phase 1 – Specialty:** Update config defaults, fix vetting logic, decouple specialty from win streak.
2. **Phase 2 – WS Badge:** Add WS badge display in dashboard, ensure is_win_streak_badge flows through storage.
3. **Phase 3 – Farming Penalty:** Add farming penalty to classifier scoring, wire config.
4. **Phase 4 – Copy/Execution:** Disable CopyEngine, remove copy API routes, hide copy UI.

---

## 7. Schema Changes

- `is_win_streak_badge` – already in schema (storage migration).
- No new columns required for farming penalty (score is computed).
- `update_wallet_vetting` – add `is_win_streak_badge` parameter if not already persisted via `update_wallet`.
