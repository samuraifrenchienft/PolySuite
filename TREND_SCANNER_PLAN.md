# Trend Scanner Plan - AI Meme Coin & Trend Detection

## What It Does

Scans for new meme coins and trends using AI to filter out scams/pumps:

| Source | Data | API | Cost |
|--------|------|-----|------|
| pump.fun | New token launches | pump.fun API | FREE |
| DexScreener | Trending tokens | DexScreener API | FREE |
| Twitter/X | Trending topics | Twitter API | PAID |
| DexScreener | Token price/momentum | DexScreener API | FREE |

## How AI Filters

AI analyzes each token:
- Name pattern (rug checks)
- Volume consistency  
- Price movement (pump detection)
- Social signals

Response:
```
ALERT: [YES/NO]
REASON: [1 sentence]
```

## Implementation

### Phase 1: DexScreener Only (FREE)
- [ ] Get trending Solana tokens
- [ ] Get new tokens
- [ ] Add AI filtering

### Phase 2: pump.fun Integration
- [ ] Add pump.fun API
- [ ] Scan new launches
- [ ] AI filters scams

### Phase 3: Twitter (Future)
- [ ] Add Twitter API
- [ ] Track mentions
- [ ] Detect viral coins

## Integration Points

In main.py loop:
```python
# Every 15 minutes
if current_time - last_trend_scan > 900:
    alerts = scanner.scan_all()
    for alert in alerts:
        combined.send_health(f"🚨 TREND: {alert['token']}")
```

## Files to Create/Modify

| File | Change |
|------|--------|
| `src/alerts/trendscanner.py` | NEW - Trend scanner |
| `main.py` | Add scan to loop |

## API Keys Needed

| Service | Status | Notes |
|---------|--------|-------|
| DexScreener | ✅ Already working | FREE |
| pump.fun | 🔬 Research | May need key |
| Twitter/X | ❌ Not started | Paid - future |

## Priority

1. DexScreener trending (easiest, free)
2. AI filter integration
3. pump.fun (if API works)
4. Twitter (later, needs paid API)

---

## Future: NFT Mint Alerts (Low Priority)

Track new NFT mints and alerts:

| Source | Data | API |
|--------|------|-----|
| Tensor | Tensor NFT trades | Coming Soon |
| MagicEden | NFT mints | Free API |
| OpenSea | New collections | Free API |

### Features
- Detect new NFT mint launches
- Alert on high volume mints
- AI analyze collection potential
- Floor price tracking

### When to Add
- Low priority - after trend scanner is working
- Good for engagement
- Easy to add later

---

Want me to implement Phase 1 now?
