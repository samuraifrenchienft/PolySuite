# Wallet scoring, vetting, and specialty — end-to-end

This document describes **every stage** that affects tracked Polymarket wallets (`0x…` proxy addresses) in PolySuite, from ingestion to dashboard labels. Use it to debug “classify spins forever”, “vet all fails”, or “no specialty”.

---

## 0) Config on disk (`config.json`)

- **`config_schema_version`** (current **3**): if your file is older, the next load **rewrites** vetted defaults for every `vet_*` key plus wallet discovery/cleanup keys listed in `src/config/__init__.py` (`_VETTING_AND_WALLET_PIPELINE_KEYS`) and bumps the version so strict vet settings from older installs are not stuck forever.
- To **opt out** of a future auto-refresh for those keys only, set `config_schema_version` manually to match `CONFIG_SCHEMA_VERSION` in code before upgrading (advanced).

## 1) Ingestion (how a wallet gets on the list)

| Step | What happens | Config keys |
|------|----------------|-------------|
| Manual / import | `POST` bulk import or CLI adds `Wallet` rows in SQLite | `wallet_discovery_max_wallets` cap (via `max_tracked_wallets`) |
| Auto-discovery | `run_wallet_discovery_step` in `src/collector/runner.py` | `wallet_discovery_enabled`, `wallet_discovery_interval_sec`, `wallet_discovery_max_new`, `wallet_discovery_max_wallets` |
| Leaderboard sources | **Data API**: `GET https://data-api.polymarket.com/v1/leaderboard` (paginated, `0x` only). Optional **Gamma**: `GET https://gamma-api.polymarket.com/leaderboards` when `wallet_discovery_gamma_supplement` is true | Same + `wallet_discovery_gamma_supplement` |

**Likely issues**

- Saved `config.json` overriding defaults (e.g. discovery off, tiny `max_new`, low cap).
- Interval gate: discovery only runs after `wallet_discovery_interval_sec` **and** only advances after a **non-empty** leaderboard fetch (`last_ts_ref` logic).

---

## 2) Background stats refresh (dashboard numbers vs vet/classify)

| Component | File | Logic |
|-----------|------|--------|
| **WalletCalculator** | `src/wallet/calculator.py` | `get_wallet_trades` → **`resolution_stats.compute_polymarket_resolution_rollup`** (same win rules as vetting, capped markets). Stores **resolved wins** + **win_rate = wins / resolved_decisions** via explicit `win_rate` in `update_wallet_stats`. |
| **Collector** | `src/collector/runner.py` `_collect_wallet_stats` | Periodically writes `total_trades`, `wins`, `win_rate`, `trade_volume` from calculator into storage. |

**Likely issues**

- Dashboard **win rate / wins** can **disagree** with Classify/Vet because calculator does **not** use market outcomes.
- Users interpret “my wallet has 60% on Polymarket” but PolySuite header used a **different definition** until they run vet/classify.

---

## 3) Classify (“Analyze” / `POST /api/wallets/analyze`)

| Step | File | Detail |
|------|------|--------|
| Load trades | `app.py` | `get_wallet_trades(addr, limit=trade_limit)` — default **400**, clamped 50–500. |
| Batch size | `app.py` | **Up to 25 addresses per HTTP request** (`addresses[:25]`). |
| Per wallet | `src/wallet/classifier.py` | Parse trades → **`_resolve_trade_outcomes`**: fetches market metadata via `get_market` for up to **`MAX_MARKETS_TO_RESOLVE` (140)** markets per wallet (top-by-trade-count + random tail). |
| Category + wins | `classifier.py` | Categories come from **fetched** market `category`. Wins/losses only when market is **resolved** and outcome matches trade logic (aligned with vetting). |
| Specialty | `classifier.py` `_calculate_category_breakdown` | Builds `category_stats` (trades, wins, volume per category). Assigns `specialty_category` using win concentration, PnL gates, or **volume-led** fallbacks. **If there are zero resolved wins in the sample**, specialty can still be set from **volume/trades** (≥5 trades in top category) after recent code changes. |
| Persist | `app.py` | Updates wallet: `classification`, flags, `tier`, `is_specialty`, `specialty_category`, etc., via `storage.update_wallet`. |

**Dashboard UI**

- `runClassification()` in `index.html` sends **chunks of 6** addresses per request (to reduce timeouts). Progress text updates **once per chunk** — a single slow chunk (many `get_market` calls) feels like a “hang”.
- There is **no** server-side progress stream; only “batch N done”.

**Likely issues (classify “cycles forever”)**

1. **Heavy API fan-out**: 6 wallets × up to ~140 markets each = hundreds of HTTP calls per chunk; slow Polymarket/Gamma responses.
2. **Silent stall**: Browser waits on one `fetch` with no intermediate events.
3. **Address cap mismatch**: Frontend may loop over 100+ wallets in many chunks; user must keep tab open until **all** chunks finish.

---

## 4) Vet single (`POST /api/wallet/vet`)

| Step | File | Detail |
|------|------|--------|
| Trades | `src/wallet/vetting.py` | `get_wallet_trades(address, limit=500)`. If empty → **`None`** (“no trades / failed”). |
| Markets | `vetting.py` | One `get_market` per unique `conditionId` (cached in-request). |
| Outcomes | `vetting.py` | Same style as classifier: resolved markets, winning outcome, BUY/SELL + inferred YES/NO. |
| Bot / settlement | `vetting.py` | `bot_score`, unresolved loss checks, min avg bet, etc. |
| Specialty (vet path) | `vetting.py` | Rolling window `vet_specialty_window_days`: per-category wins/losses; sets `specialty_category` / `is_specialty` with several fallbacks (`top_category` by volume, etc.). |
| Pass / fail | `vetting.py` | **`baseline`**: human, settled, avg bet ≥ `min_bet`, **≥ 5 resolved markets**, trades/day ≤ `vet_max_trades_per_day`, wins ≥ `vet_min_trades_won`, losses ≤ `vet_max_losses` (if enabled), optional streak/reliability/fee gates. **`normal_pass`**: baseline + optional PnL / ROI / conviction mins. **`specialty_or_recent_pass`**: baseline + (specialty **or** hot recent wins) + **`total_pnl >= 0`**. `passed = normal_pass OR specialty_or_recent_pass`. |
| Persist | `app.py` | `update_wallet_vetting` sets `tier` to `vetted` or `watch`, copies specialty fields. |

**Likely issues**

- **`vet_min_trades_won`** or **`vet_max_losses`** in user config make **baseline** impossible → everything fails with issues listed in API (not always shown in UI).
- **`estimated_fees_paid`** is often **0** in code today; if `vet_min_estimated_fees > 0`, **every** Polymarket vet fails the fee gate.
- Single vet “removes one / didn’t pass”: tier goes to **`watch`** when `passed` is false — that’s expected, not deletion.

---

## 5) Vet all (`POST /api/wallets/bulk-vet`)

| Detail | Value |
|--------|--------|
| Max addresses per request | **25** (`addresses[:25]`) |
| UI | Chunks of **6** in `index.html` |

**Likely issues**

- Same **baseline** strictness as single vet → most wallets fail if thresholds are high.
- Each address still does full trade + market resolution work → slow; errors truncated in `errors[:10]`.

---

## 6) Specialty on the dashboard

| Source | When it’s set |
|--------|----------------|
| **Classifier** | After successful **Analyze**; stored in DB (`specialty_category`, `is_specialty`, …). |
| **Vetting** | After **Vet**; can overwrite / align specialty fields via `update_wallet_vetting`. |
| **API JSON** | `_wallet_to_json_safe` forces `is_specialty = true` if `specialty_category` string is non-empty (fixes stale flag). |

**Stats card “Specialty count”**

- `_calculate_stats` counts wallets where `is_specialty` **or** non-empty `specialty_category`.

**Historical reasons specialty was empty**

1. Classifier required **resolved wins** in category stats before labeling; wallets with mostly **open** markets → **0 wins** → no specialty (mitigated by volume/trades fallback when ≥5 trades in top category).
2. **`get_market` failures** → no `category` on trades → empty `category_stats`.
3. Analyze response JSON **does not** include specialty fields (only DB after refresh); user must reload dashboard data to see badges.

---

## 7) Quick “where it hurts” checklist

| Symptom | Check |
|---------|--------|
| Classify never ends | Network tab: stuck on `/api/wallets/analyze`; reduce wallets per run or `trade_limit`; Polymarket rate limits. |
| Vet always fails | Log/print `issues` from vet result; set `vet_min_trades_won`, `vet_max_losses`, `vet_min_estimated_fees`, `vet_min_pnl`, `vet_min_roi_pct`, `vet_min_conviction` to **0** to isolate. |
| No specialty after classify | Ensure markets return `category`; ensure enough trades in one category (≥5 for volume fallback); run Analyze again after code update. |
| Header win% ≠ vet win% | Expected: calculator **heuristic** vs vet **resolved** logic — run vet/classify and consider aligning calculator later. |

---

## 8) File map

| Concern | Primary files |
|---------|----------------|
| Discovery | `src/collector/runner.py`, `src/market/leaderboard.py` |
| Background win/volume | `src/wallet/calculator.py`, `src/collector/runner.py` |
| Classify | `src/wallet/classifier.py`, `src/dashboard/app.py` (`/api/wallets/analyze`) |
| Vet | `src/wallet/vetting.py`, `src/dashboard/app.py` (`/api/wallet/vet`, `/api/wallets/bulk-vet`) |
| Config | `src/config/__init__.py`, `Config` properties for `vet_*` |
| UI | `src/dashboard/templates/index.html` (`runClassification`, `runBulkVet`) |
