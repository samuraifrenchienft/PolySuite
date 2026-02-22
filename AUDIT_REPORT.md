# PolySuite Codebase Audit Report

**Date:** 2025-02-22  
**Scope:** main.py, src/discord_bot.py, src/telegram_bot.py, src/alerts/*, src/market/*, src/wallet/*, src/agent.py

---

## BUG (Critical)

### BUG-001
- **File:** main.py:731
- **Issue:** `handle_bot_command` starts TelegramBot without validating `telegram_bot_token`. If token is empty/None, `telebot.TeleBot(None)` will crash or behave unpredictably.
- **Fix:** Add guard: `if not config.telegram_bot_token: print("[-] Set telegram_bot_token in .env"); return`

### BUG-002
- **File:** main.py:739
- **Issue:** `handle_discord_command` starts DiscordBot without validating `discord_bot_token`. Running `python main.py discord` with empty token causes `self.run(self.token)` to fail.
- **Fix:** Add guard: `if not config.discord_bot_token: print("[-] Set discord_bot_token in .env"); return`

### BUG-003
- **File:** src/market/bankr.py:39
- **Issue:** Symbol map has wrong CoinGecko ID: `"link": "chainlist"`. Chainlink's correct ID is `"chainlink"`. Requests for LINK price return wrong/missing data.
- **Fix:** Change to `"link": "chainlink"`

### BUG-004
- **File:** src/discord_bot.py:354-362
- **Issue:** Message command `!add` has no MAX_WALLETS check. Slash `/add` limits to 10 wallets, but `!add` allows unlimited additions, bypassing the limit.
- **Fix:** Add same wallet limit check as in `add_slash` before `storage.add_wallet`

---

## BUG (High)

### BUG-005
- **File:** main.py:699-702
- **Issue:** When no command is given, prints "Examples:" but returns immediately without printing the example commands.
- **Fix:** Add the example lines before return, or remove the dangling "Examples:" print.

### BUG-006
- **File:** src/wallet/vetting.py:60-68
- **Issue:** Win/loss logic for resolved markets may be incorrect. Code checks `market.get("outcome")` (winning outcome) and `side == "BUY"` or `side == "SELL"`, but does not verify what outcome the trade was for (YES vs NO). A BUY could be buying YES or NO; only BUY+YES wins when outcome is "yes".
- **Fix:** Use `trade.get("outcome")` or equivalent to determine if the trade was for the winning side before counting as win.

### BUG-007
- **File:** src/agent.py:86-99
- **Issue:** Duplicate/overlapping condition blocks: `"jupiter"` and `"price"/"balance"/"crypto"` appear twice. The second `elif` for price/balance/crypto (lines 95-99) is dead code—never reached because the first block (61-67) handles it.
- **Fix:** Remove the duplicate block at lines 95-99.

---

## BUG (Low)

### BUG-008
- **File:** main.py:330
- **Issue:** `except Exception as e: pass` silently swallows all errors when checking wallet positions for whale alerts. Failures are invisible.
- **Fix:** Log the exception: `print(f"[!] Whale check error for {wallet.nickname}: {e}")` or use a proper logger.

### BUG-009
- **File:** src/alerts/events.py:306-308
- **Issue:** `check_crypto_prices` uses `coin_id` as dict key in `_previous_prices`, but `check_crypto_moves` uses `market_id`. Both share `_previous_prices`—coin IDs (e.g. "bitcoin") and market IDs can collide or overwrite each other.
- **Fix:** Use separate caches, e.g. `_previous_crypto_prices` for CoinGecko and keep `_previous_prices` for market odds.

### BUG-010
- **File:** src/discord_bot.py:384-391
- **Issue:** `asyncio.get_event_loop().time()` is deprecated in Python 3.10+. Prefer `asyncio.get_event_loop().time()` or `time.monotonic()` for elapsed time.
- **Fix:** Use `time.monotonic()` for start_time and elapsed, or `asyncio.get_running_loop().time()` for async contexts.

---

## API / Type Mismatches

### BUG-011
- **File:** src/wallet/portfolio_calculator.py:36
- **Issue:** Positions from Polymarket Data API use `conditionId` or `market`, not `market_id`. Code checks `pos.get("market_id")` first—may work if API includes it, but Polymarket docs suggest `conditionId`/`market`. Redundant but not wrong.
- **Fix:** Ensure order matches API: `pos.get("conditionId") or pos.get("market") or pos.get("market_id")`.

### BUG-012
- **File:** src/config/__init__.py:28-35
- **Issue:** `get_bankr_client(api_key=None)` returns `_bankr_client` which can be None. Callers (DiscordBot, TelegramBot) use `self.bankr = get_bankr_client(...)`. If api_key is empty and client was never created, `_bankr_client` is None. `is_configured()` checks `bool(self.api_key)` on the client—but if client is None, `self.bankr` is None and `self.bankr.send_prompt` would raise AttributeError.
- **Fix:** `get_bankr_client` returns None when api_key is empty. Callers should check `if self.bankr and self.bankr.is_configured()` before use. Discord/Telegram already have such checks in some paths; ensure all Bankr call paths guard against None.

---

## PERF (Performance)

### PERF-001
- **File:** src/alerts/events.py:31-32, 77-86, 109-124, 281-302
- **Issue:** `_previous_prices` and `_previous_volumes` grow unbounded. Every market_id and coin_id is stored. Long-running monitor will accumulate thousands of entries.
- **Fix:** Add max size (e.g. LRU with max 500 entries) or periodic cleanup of stale entries.

### PERF-002
- **File:** src/alerts/__init__.py:46
- **Issue:** `_last_alerts` dict in AlertDispatcher grows unbounded. Each unique market_id adds an entry; no eviction.
- **Fix:** Use a bounded cache (e.g. `cachetools.TTLCache`) or periodically prune entries older than cooldown * 2.

### PERF-003
- **File:** src/wallet/calculator.py:134
- **Issue:** `calculate_win_rate_by_category` calls `api.get_market_details(market_id)` inside a loop over trades. N+1 pattern—one API call per unique market.
- **Fix:** Batch market lookups or cache market details per run.

---

## SEC (Security)

### SEC-001
- **File:** src/telegram_bot.py:98-99
- **Issue:** User Bankr API keys stored in `self.user_bankr_keys` (in-memory dict). Keys are not encrypted at rest. If process memory is dumped, keys could be exposed.
- **Fix:** Document that keys are in-memory; for production, consider encrypted storage or short-lived tokens.

### SEC-002
- **File:** src/discord_bot.py:418-419, src/telegram_bot.py:84-86
- **Issue:** User-provided addresses from messages are passed to external APIs (Polymarket, DexScreener) without length/sanitization. Unlikely to cause injection but worth validating format.
- **Fix:** Validate address format (e.g. `is_valid_address`) before API calls; already done in some paths.

### SEC-003
- **File:** src/config/__init__.py:93-95
- **Issue:** Secrets loaded from env are stored in `config` dict. If config is logged or serialized, secrets could leak.
- **Fix:** Avoid logging full config; use `***` for secret values in debug output.

---

## Summary

| Category   | Count |
|-----------|-------|
| BUG Critical | 4 |
| BUG High     | 3 |
| BUG Low      | 3 |
| API/Type     | 2 |
| PERF         | 3 |
| SEC          | 3 |

**Priority fixes:** BUG-001, BUG-002, BUG-003, BUG-004, BUG-005, BUG-007.
