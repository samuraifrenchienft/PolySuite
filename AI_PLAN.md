# AI Integration Plan - Rate Limit Aware

## The Problem
OpenRouter FREE: Only **50 calls/day** - not enough for real-time AI

## Solution: Multiple Free Cloud AI Services

| Source | Free/Day | Notes |
|--------|----------|-------|
| Groq | Unlimited | PRIMARY - fast, cloud |
| OpenRouter (free models) | 50 | BACKUP |
| Together.ai | ~50-100 | BACKUP |

**NO local - must be cloud for 24/7 operation**

---

## Multi-Source Architecture (Cloud Only)

```python
class AIService:
    """Tries multiple AI services, uses first available."""
    
    def __init__(self):
        self.services = [
            GroqService(),      # Unlimited free - PRIMARY
            OpenRouterService(), # 50/day - BACKUP
            TogetherAIService(),  # ~50-100/day - BACKUP
        ]
    
    def analyze(self, prompt):
        for service in self.services:
            try:
                return service.analyze(prompt)
            except Exception as e:
                print(f"[AI] {service.name} failed: {e}")
                continue
        return "AI unavailable"
```

---

## Free Cloud Services Setup

### 1. Groq (PRIMARY - UNLIMITED)
- **Website:** groq.com
- **Free:** Unlimited inference
- **Models:** Llama, Mixtral, Gemma
- **24/7:** ✅ Yes - cloud based
- **Setup:** Sign up → Get API key → Add to .env

### 2. OpenRouter (BACKUP - 50/day)
- **Website:** openrouter.ai
- **Free:** 50 calls/day
- **Models:** DeepSeek R1, Llama 3.3
- **24/7:** ✅ Yes - cloud based

### 3. Together.ai (BACKUP - ~50-100/day)
- **Website:** together.ai
- **Free:** Limited free tier
- **Models:** Llama, Mixtral
- **24/7:** ✅ Yes - cloud based

---

## AI Usage Schedule

### When AI IS Called

| Trigger | Frequency | Purpose |
|---------|-----------|---------|
| New Market Alert | Every new market | Sentiment |
| Whale Trade | Every trade | Explain wallet |
| Daily Summary | 1x per day | Market overview |
| Convergence | On detection | Explain opportunity |
| Manual /scan | On command | Wallet analysis |

### When AI is NOT Called
- Every market scan (too frequent)
- Every price check
- Every arbitrage check

---

## Actual Usage (With Groq = Unlimited)

| Feature | Calls/Day | Status |
|---------|-----------|--------|
| New Market (20/day) | 20 | ✅ Unlimited via Groq |
| Whale Trades | 10 | ✅ Unlimited |
| Daily Summary | 1 | ✅ Unlimited |
| Manual /scan | 5 | ✅ Unlimited |
| **TOTAL** | **~36** | ✅ UNLIMITED |

With Groq as primary, we have **effectively unlimited** AI calls.

---

## Backup Strategy

```python
# Priority order:
1. Groq (unlimited free) - USE FIRST
2. OpenRouter (50/day) - FALLBACK
3. Ollama (local) - FALLBACK
4. Return "AI unavailable" - LAST RESORT
```

---

## Implementation

### Step 1: Get Groq API Key (PRIMARY)
- Go to **groq.com**
- Sign up (free)
- Get API key
- Add to .env: `GROQ_API_KEY=your_key`

### Step 2: Get OpenRouter API Key (BACKUP)
- Go to **openrouter.ai**  
- Sign up (free)
- Get API key
- Add to .env: `OPENROUTER_API_KEY=your_key`

### Step 3: (Optional) Together.ai
- Go to **together.ai**
- Sign up for free tier
- Add to .env: `TOGETHER_API_KEY=your_key`

---

## Files to Create/Modify

| File | Change |
|------|--------|
| `.env` | Add GROQ_API_KEY, OPENROUTER_API_KEY |
| `src/ai/service.py` | NEW - Multi-source AI client |
| `src/alerts/events.py` | Add AI sentiment |
| `src/alerts/insider.py` | Add AI wallet analysis |

---

## Summary

**Goal: Unlimited AI calls**

1. **Primary:** Groq (unlimited free)
2. **Backup 1:** OpenRouter (50/day)
3. **Backup 2:** Ollama (local unlimited)

This gives us effectively unlimited AI for free.
