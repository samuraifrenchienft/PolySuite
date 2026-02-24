# Multi-Stage Sweep Findings

## Stage 1: Bugs & Code Quality ✅ FIXED
- **main.py**: Bare `except:` → `except Exception:` (swallows KeyboardInterrupt)
- **main.py**: `import json` moved to top
- **main.py**: `formatter` imported once at top, removed 5+ inline imports

## Stage 2: Redundancy ✅ FIXED
- **events.py**: Added `fetch_markets_for_categories()` - 1 API call instead of 3 for crypto/sports/politics
- **main.py**: Cleanup uses `all_market_ids` from batch fetch - no extra get_active_markets

## Stage 3: Performance ✅ FIXED
- **API calls per cycle**: Reduced from ~6 to ~3 (batch fetch + crypto_short_term + check_new_events)
- **EventAlerter**: `fetch_markets_for_categories(500)` returns crypto, sports, politics, all_market_ids
