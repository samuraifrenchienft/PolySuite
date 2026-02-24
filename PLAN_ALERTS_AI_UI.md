# Plan: Alerts, AI, Fetching & UI Improvements

## Checklist (execute in order)

### Phase 1: Whale Reports – Reduce Frequency
- [x] 1.1 Add `whale_alert_cooldown` config (default 1800 = 30 min)
- [x] 1.2 Add `last_whale_alert_time` in main.py; skip whale send if within cooldown
- [x] 1.3 Increase whale check interval from 60s to 300s (5 min)
- [x] 1.4 Optionally raise `whale_min_size` to 75000 (configurable)

### Phase 2: Fetching – Crypto & Sports
- [x] 2.1 Add `order=volume` to `get_active_markets` in api.py (fallback if API fails)
- [x] 2.2 Add `get_sports_markets_from_events(tag_id=1)` for sports via Polymarket events API
- [x] 2.3 Increase limit for `check_sports_markets` and `check_politics_markets` to 400
- [x] 2.4 Use tag 1 from Polymarket /sports (sports/competitive)
- [x] 2.5 Fallback to keyword filter when tag fetch yields no sports

### Phase 3: AI Engine – Better Integration
- [x] 3.1 Add `ai_filter_low_value_alerts` config – skip LOW opportunity + low volume alerts
- [x] 3.2 Convergence already has AI reasoning (analyze_wallet)
- [x] 3.3 Add whale analysis cooldown – skip AI for whale batch if batch size < 3
- [ ] 3.4 Unify AI clients (deferred – different prompts/use cases)

### Phase 4: Report Widgets / Cards
- [x] 4.1 Discord embeds: Color per type (whale=0xe67e22)
- [x] 4.2 Add footer with "PolySuite • {timestamp}" to embeds
- [x] 4.3 Formatter: Add section separators (━━━) and clearer hierarchy
- [x] 4.4 Dashboard: Card layout, CSS variables, category badges, volume bars
