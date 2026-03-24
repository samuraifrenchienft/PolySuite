# PolySuite codebase checklist

Tracked work: **done in tree** vs **still open** (from plan docs and sweeps).

## Done (this pass)

- [x] Wallet JSON helpers: specific `except` types (`json.JSONDecodeError`, `TypeError`).
- [x] `max_tracked_wallets()` — single cap for CLI + Discord + collector (`wallet_discovery_max_wallets`).
- [x] Leaderboard importer: removed dead imports, `logging` instead of `print`.
- [x] Pump Archive: **TTL cache** (45s) for mint→creator and creator stats; **parallel** enrichment + batch stats (`ThreadPoolExecutor`).
- [x] Pump Archive: optional **disk cache** `data/pumparchive_cache.json` — hydrate at start of `enrich_pump_categories_for_dashboard`, persist after enrich (TTL **105s** on disk, aligned with ~90–120s intent).
- [x] Polymarket API client + Event alerter + dashboard routes: **`logging`** instead of `print` in hot paths.
- [x] `main.py`: **`LOG_LEVEL`** + `basicConfig` for stderr logs.
- [x] Dashboard: startup messages for **auth misconfiguration**; JS debug logs gated by `window.__DASHBOARD_DEBUG`.
- [x] Dashboard: **single wallet load path** — always **`/api/dashboard/data`** first; embedded `#dashboard-wallets` / `loadWalletsFromPage()` only if the API request fails.
- [x] Migrate remaining **`print()`** in `src/` (telegram, combined, vetting, agent, trendscanner, convergence, aggregator, trade_executor, auth_api, discord_bot, jupiter_*, market/storage, wallet/storage, tasks, hashdive, alerts `__init__`, discovery, bankr, polymarket_clob/whale, polyscope, predictfolio, meme_scanner, ai/engine, etc.) to **`logging`**. (Docstrings / CLI hints in `credential_store.py` still mention `print` in shell one-liners — intentional.)
- [x] Discord bot: receives **`config` + `api_factory`** so limits match `config.json`.
- [x] `.gitignore`: **`nul`** (Windows), `*temp*dashboard*.html` scratch pattern; `data/` and `*.db` already covered.
- [x] Tests: `tests/test_config_max_tracked_wallets.py`, `tests/test_dashboard_pump_batch.py` (Flask client + mocked Pump Archive).

## Still open (backlog)

### High value

- [ ] Pump enrichment: **background refresh** if Pump Archive rate-limits under heavy parallel load (disk cache reduces cold-start/API churn; optional worker TBD).

### From plan docs (see `docs/*_PLAN.md`)

- [ ] `RUN_MODE_IMPLEMENTATION_PLAN.md` — run-mode behavior polish.
- [ ] `PUMPFUN_NEW_COIN_ALERT_PLAN.md` — ingestion when HTTP APIs fail (WS / indexer).
- [ ] `REFACTOR_PLAN.md` — structural refactors as listed there.
- [ ] `PUMP_SWAP_CATEGORIES_PLAN.md` / `PUMP_SWAP_METRICS_PLAN.md` — metrics depth.
- [ ] `SPECIALTY_IMPLEMENTATION_PLAN.md` — classifier / vetting thresholds.
- [ ] `WALLET_SYSTEM_PLAN.md` — long-term wallet DB fields and flows.

### Hygiene

- [ ] Tests: expand integration coverage for dashboard routes and collector (beyond batch + auth smoke).

---

*Update this file when you close items; keep detailed design in the linked `*_PLAN.md` files.*
