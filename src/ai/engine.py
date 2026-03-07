"""AI engine for Prediction Suite - alert-first decision support.

Design goals:
- Deterministic alert logic must work without AI providers.
- LLM calls should refine reasons/confidence, not gate signal generation.
- Chat-style AI is secondary to alert quality.
"""

import os
import requests
from typing import List, Dict, Optional


SYSTEM_MESSAGE = """You are the AI Engine for Prediction Suite, a prediction market monitoring bot.

TASKS (use exact format):
1. CATEGORIZE: Return CATEGORY: [crypto/sports/politics/economy/entertainment/other]
2. SCORE: Return SCORE: [0-100] and REASON: [1 sentence]
3. SENTIMENT: Return SENTIMENT: [BULLISH/BEARISH/NEUTRAL], REASON: [1 sentence]
4. WALLET: Return STRATEGY: [brief], CONFIDENCE: [high/medium/low], REASON: [1-2 sentences]
5. ANOMALY: Return ANOMALY: [YES/NO], TYPE: [if yes], REASON: [1 sentence]
6. SUMMARY: Return SUMMARY: [3 sentences], TOP_PICKS: [2-3 markets]
7. ANALYZE WHALE: Check triggers (CONVERGENCE, WHALE_ENTRY, EARLY_MOVER, CONTRARIAN)
8. ANALYZE MARKET: Check triggers (LIQUID, TRENDING, MOVEMENT, CATEGORY)
9. ENTRY_ZONE: Return ENTRY_ZONE: [BUY_YES/BUY_NO/WAIT/AVOID], REASON: [1-2 sentences], CONFIDENCE: [high/medium/low]

TRIGGERS TO LOOK FOR:
- CURATED: convergence (>2 wallets same market), large size, early entry, contrarian
- MARKET: volume > $10k, trending topic, probability movement

RULES:
- Use exact format requested
- Be concise - max 2 sentences
- Only prediction market analysis
- No financial advice
- Always check for TRIGGERS above
- Provide a confidence score for all predictions
- Explain the reasoning behind your predictions
"""


class AIFilter:
    """AI-powered market filtering with dual providers."""

    def __init__(self):
        # Primary: Groq (unlimited)
        self.groq_key = os.getenv("Groq_api_key") or os.getenv("GROQ_API_KEY")
        self.groq_url = "https://api.groq.com/openai/v1"
        self.groq_model = "llama-3.3-70b-versatile"

        # Backup: OpenRouter Qwen
        self.openrouter_key = os.getenv("Openrouter_api_key") or os.getenv(
            "OPENROUTER_API_KEY"
        )
        self.openrouter_url = "https://openrouter.ai/api/v1"
        # Use a text model for alert reasoning (vision model here is unnecessary).
        self.openrouter_model = os.getenv(
            "OPENROUTER_MODEL", "deepseek/deepseek-chat-v3-0324:free"
        )

        # Ollama for local models
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "dolphin-phi:latest")
        self.ollama_enabled = os.getenv("OLLAMA_ENABLED", "").lower() in (
            "1",
            "true",
            "yes",
        )
        self.timeout_seconds = int(os.getenv("AI_HTTP_TIMEOUT_SECONDS", "12") or "12")

    def is_available(self) -> bool:
        """True when at least one AI provider is configured."""
        return bool(self.groq_key or self.openrouter_key or self.ollama_enabled)

    def _call_groq(self, prompt: str, max_tokens: int = 200) -> Optional[str]:
        if not self.groq_key:
            return None
        try:
            resp = requests.post(
                f"{self.groq_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.groq_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.groq_model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_MESSAGE},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": max_tokens,
                },
                timeout=self.timeout_seconds,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[AI-Groq] Error: {e}")
        return None

    def _call_openrouter(self, prompt: str, max_tokens: int = 200) -> Optional[str]:
        if not self.openrouter_key:
            return None
        try:
            resp = requests.post(
                f"{self.openrouter_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openrouter_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.openrouter_model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_MESSAGE},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": max_tokens,
                },
                timeout=self.timeout_seconds,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[AI-OpenRouter] Error: {e}")
        return None

    def _call_ollama(self, prompt: str, max_tokens: int = 200) -> Optional[str]:
        if not self.ollama_enabled:
            return None
        try:
            import ollama

            response = ollama.chat(
                model=self.ollama_model,
                messages=[
                    {"role": "system", "content": SYSTEM_MESSAGE},
                    {"role": "user", "content": prompt},
                ],
                options={"temperature": 0.3, "num_predict": max_tokens},
            )
            return response["message"]["content"]
        except ImportError:
            print(
                "[AI-Ollama] Ollama SDK not installed. Please run `pip install ollama`"
            )
        except Exception as e:
            print(f"[AI-Ollama] Error: {e}")
        return None

    def _call(self, prompt: str, max_tokens: int = 200) -> Optional[str]:
        # Try Groq first (primary)
        result = self._call_groq(prompt, max_tokens)
        if result:
            return result
        # Fallback to OpenRouter
        result = self._call_openrouter(prompt, max_tokens)
        if result:
            return result
        # Optional local fallback (disabled by default).
        return self._call_ollama(prompt, max_tokens)

    @staticmethod
    def _safe_yes_price(market: Dict) -> float:
        import json

        raw_prices = market.get("outcomePrices")
        try:
            prices = json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
            if prices and len(prices) >= 1:
                p = float(prices[0])
                if 0 <= p <= 1:
                    return p
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
        try:
            p = float(market.get("yes_pct", 0.5) or 0.5)
            return max(0.0, min(1.0, p))
        except (TypeError, ValueError):
            return 0.5

    def _heuristic_entry_zone(self, market: Dict) -> Dict:
        """Deterministic baseline used even when AI is offline."""
        question_full = market.get("question") or ""
        question = question_full[:80]
        q_lower = question_full.lower()
        volume = float(market.get("volume", 0) or 0)
        yes_pct = self._safe_yes_price(market)
        category = str(market.get("category", "") or "").lower()
        market_type = str(market.get("market_type", "") or "").lower()

        short_term = any(
            t in q_lower
            for t in (
                "5 min",
                "15 min",
                "5m",
                "15m",
                "hourly",
                "up or down",
            )
        )
        confidence = "low"
        reason = "Insufficient edge."
        zone = "WAIT"
        is_combo = (
            "combo" in category
            or market_type == "combo"
            or (q_lower.count("yes ") + q_lower.count("no ")) >= 3
        )

        # Combo/parlay-specific strategy: favor fade of expensive multi-leg favorites.
        if is_combo:
            if volume < 1000:
                return {
                    "entry_zone": "AVOID",
                    "reason": "Low-liquidity combo market; high variance and execution risk.",
                    "confidence": "low",
                }
            if yes_pct >= 0.70:
                zone, confidence = "BUY_NO", "medium"
                reason = (
                    f"Combo favorite overpriced at {yes_pct:.0%}; fading multi-leg chalk."
                )
            elif yes_pct <= 0.30:
                zone, confidence = "BUY_YES", "medium"
                reason = f"Combo longshot discounted at {yes_pct:.0%}; asymmetric upside."
            else:
                zone, confidence = "WAIT", "low"
                reason = "Combo probability near fair band; no clear edge."

        # Most useful behavior for alerts: only emit directional calls when edge is clear.
        elif volume >= 25000 and yes_pct <= 0.12:
            zone, confidence = "BUY_NO", "high"
            reason = (
                f"Extreme YES underpricing ({yes_pct:.0%}) on liquid market (${volume:,.0f})."
            )
        elif volume >= 25000 and yes_pct >= 0.88:
            zone, confidence = "BUY_YES", "high"
            reason = (
                f"Strong YES dominance ({yes_pct:.0%}) with solid liquidity (${volume:,.0f})."
            )
        elif volume >= 10000 and yes_pct <= 0.18:
            zone, confidence = "BUY_NO", "medium"
            reason = f"YES is stretched low ({yes_pct:.0%}); potential mean reversion."
        elif volume >= 10000 and yes_pct >= 0.82:
            zone, confidence = "BUY_YES", "medium"
            reason = f"YES has persistent momentum ({yes_pct:.0%}) on decent volume."
        elif short_term and volume < 10000:
            zone, confidence = "AVOID", "medium"
            reason = "Short-term market with low liquidity; noise and fee risk."
        elif volume < 3000:
            zone, confidence = "WAIT", "low"
            reason = "Low liquidity market."

        if short_term and zone in ("BUY_YES", "BUY_NO"):
            reason += " Short timeframe: tighten risk and size."

        # Profitability guardrail: do not suggest near-certain legs with negligible upside.
        if zone in ("BUY_YES", "BUY_NO"):
            side_price = yes_pct if zone == "BUY_YES" else (1 - yes_pct)
            if side_price >= 0.97:
                zone, confidence = "WAIT", "low"
                reason = (
                    f"Low upside: implied payout {(1.0 / side_price):.2f}x before fees/slippage."
                )
            else:
                gross_return_pct = ((1.0 / side_price) - 1.0) * 100.0
                if gross_return_pct < 8.0:
                    zone, confidence = "WAIT", "low"
                    reason = (
                        f"Low upside: {gross_return_pct:.1f}% gross before fees/slippage."
                    )

        return {"entry_zone": zone, "reason": reason, "confidence": confidence}

    def categorize(self, question: str) -> str:
        """Task 1: Categorize market."""
        prompt = f"CATEGORIZE: {question}"
        result = self._call(prompt)
        if result:
            for cat in [
                "crypto",
                "sports",
                "politics",
                "economy",
                "entertainment",
                "other",
            ]:
                if cat in result.lower():
                    return cat
        return "other"

    def score_opportunity(self, question: str, volume: float, price: float) -> tuple:
        """Task 2: Score opportunity 0-100."""
        prompt = f"SCORE: Market: '{question}' Volume: ${volume:,.0f} Price: {price}"
        result = self._call(prompt)
        score = 50
        reason = "Default score"
        if result:
            for line in result.split("\n"):
                if "SCORE:" in line:
                    try:
                        nums = "".join(filter(str.isdigit, line.split("SCORE:")[1][:3]))
                        if nums:
                            score = int(nums)
                    except (ValueError, IndexError):
                        pass
                if "REASON:" in line:
                    reason = line.split("REASON:")[1].strip()
        return score, reason

    def analyze_sentiment(self, question: str, price: float = None) -> str:
        """Task 4: Sentiment analysis."""
        prompt = f"SENTIMENT: {question}"
        if price:
            prompt += f" Price: {price}"

        result = self._call(prompt)
        if result:
            if "BULLISH" in result.upper():
                return "bullish"
            elif "BEARISH" in result.upper():
                return "bearish"
        return "neutral"

    def analyze_whale_trades(self, trades: List[Dict]) -> str:
        """Task 9: Analyze curated wallet activity - patterns and risks.

        Detects: convergence, large entry, early mover, contrarian
        """
        if not trades:
            return ""

        # Group by market
        by_market = {}
        for t in trades:
            q = t.get("question", "unknown")[:30]
            if q not in by_market:
                by_market[q] = []
            by_market[q].append(t)

        # Check for convergence
        convergence_markets = [m for m, ts in by_market.items() if len(ts) >= 2]

        # Get top trades
        top = sorted(trades, key=lambda x: x.get("size", 0), reverse=True)[:5]
        summary = "\n".join(
            [
                f"- {t.get('wallet', '?')}: {t.get('side', '?').upper()} ${t.get('size', 0):,.0f} on {t.get('question', '?')[:30]}"
                for t in top
            ]
        )

        prompt = f"""ANALYZE WHALE TRADES - Find patterns:

{summary}

PATTERNS:
- CONVERGENCE: {len(convergence_markets)} markets with multiple wallets
- WHALE_ENTRY: {any(t.get("size", 0) > 50000 for t in trades) and "Yes (> $50k)" or "No"}
- LARGE_ACTIVITY: Total ${sum(t.get("size", 0) for t in trades):,.0f} across {len(trades)} trades

Reply format:
PATTERN: [CONVERGENCE/LARGE_ACTIVITY/NONE]
DETAILS: [which markets, trade sizes]
RISKS: [any copy trade risks]"""

        result = self._call(prompt, max_tokens=250)
        return result[:250] if result else ""

    def analyze_new_market(self, market: Dict) -> Dict:
        """Task 10: Analyze new market - present facts only.

        Shows: volume, category, time sensitivity, risks (fee, expiring soon)
        """
        import json

        question = market.get("question", "")[:100]
        volume = float(market.get("volume", 0) or 0)
        prob = float(market.get("probability", 0.5) or 0.5)
        # Derive probability from outcomePrices if available
        raw_prices = market.get("outcomePrices")
        if raw_prices:
            try:
                prices = (
                    json.loads(raw_prices)
                    if isinstance(raw_prices, str)
                    else raw_prices
                )
                if prices and len(prices) >= 1:
                    prob = float(prices[0])
            except (ValueError, TypeError):
                pass

        # Detect category
        q_lower = question.lower()
        category = "other"
        if any(w in q_lower for w in ["bitcoin", "btc", "eth", "ethereum", "crypto"]):
            category = "crypto"
        elif any(
            w in q_lower
            for w in ["trump", "biden", "election", "president", "congress"]
        ):
            category = "politics"
        elif any(w in q_lower for w in ["nba", "nfl", "super bowl", "game", "win"]):
            category = "sports"

        # Check fee risk
        fee_risk = False
        if any(
            t in q_lower
            for t in ["5 min", "15 min", "1 hour", "hourly", "5min", "15min"]
        ):
            fee_risk = True

        # Volume level
        vol_level = "LOW"
        if volume > 10000:
            vol_level = "MEDIUM"
        if volume > 100000:
            vol_level = "HIGH"

        # Probability movement
        prob_movement = "OPEN"  # still time to enter
        if prob > 0.7:
            prob_movement = "LATE"  # might be too late

        prompt = f"""ANALYZE NEW MARKET - Present facts only:

{question}
Volume: ${volume:,.0f} ({vol_level})
Probability: {prob:.0%}
Category: {category}

FACTS:
- Volume: {vol_level} (${volume:,.0f})
- Probability: {prob:.0%} - {prob_movement}
- Category: {category}
{fee_risk and "⚠️ FEE RISK: Short timeframe - fees may exceed profit" or ""}

Reply format:
FACTS: [volume level, probability, category]
RISKS: [fee risk if applicable, expiring soon if applicable]
NOTE: [user decides]"""

        result = self._call(prompt)
        # Parse trigger and opportunity from response
        trigger = ""
        opportunity = "MEDIUM"
        if result:
            for line in result.split("\n"):
                if "TRIGGER:" in line.upper():
                    trigger = line.split(":")[-1].strip() if ":" in line else ""
                if "OPPORTUNITY:" in line.upper() or "HIGH" in line.upper():
                    if "HIGH" in line.upper():
                        opportunity = "HIGH"
                    elif "LOW" in line.upper():
                        opportunity = "LOW"
        return {
            "opportunity": opportunity,
            "volume": vol_level,
            "category": category,
            "fee_risk": fee_risk,
            "analysis": result[:200] if result else "",
            "trigger": trigger,
        }

    def analyze_wallet(self, trades: List[Dict]) -> Dict:
        """Task 5: Wallet strategy - consensus and confidence from side/price/size."""
        parts = []
        for t in trades[:5]:
            side = t.get("side", "?")
            ep = t.get("entry_price")
            size = t.get("size")
            q = t.get("question", "")[:30]
            try:
                ep_val = float(ep) if ep is not None else None
            except (ValueError, TypeError):
                ep_val = None
            s = f"{side} @ {ep_val:.2f}" if ep_val is not None else str(side)
            try:
                sz = float(size) if size is not None else 0
                if sz > 0:
                    s += f" (${sz:,.0f})"
            except (ValueError, TypeError):
                pass
            s += f" on {q}"
            parts.append(s)
        trade_str = "\n".join(parts) if parts else "No trades"
        prompt = f"""WALLET CONVERGENCE - Do these wallets agree on direction?
{trade_str}

Reply: CONCENSUS: [YES/NO/SPLIT] - do they agree?
CONFIDENCE: [high/medium/low]
REASON: [1-2 sentences]
"""

        result = self._call(prompt)
        return {
            "strategy": "Unknown",
            "confidence": "low",
            "analysis": result or "No analysis",
        }

    def detect_anomaly(self, trade: Dict, history: List[Dict]) -> Dict:
        """Task 6: Anomaly detection."""
        prompt = f"ANOMALY: Trade: {trade.get('side')} {trade.get('question', '')[:30]} Amount: ${trade.get('amount', 0):,.0f}"

        result = self._call(prompt)
        if result:
            return {"anomaly": "YES" in result.upper(), "analysis": result}
        return {"anomaly": False}

    def summarize_markets(self, markets: List) -> Dict:
        """Task 7: Summarize markets."""
        market_list = []
        for m in markets[:10]:
            # Handle both dict and dataclass
            if hasattr(m, "question"):
                market_list.append(f"- {m.question[:60]}")
            else:
                market_list.append(f"- {m.get('question', '')[:60]}")

        market_str = "\n".join(market_list)
        prompt = f"SUMMARY: Markets:\n{market_str}"

        result = self._call(prompt)

        # Clean up response
        if result:
            result = result.strip()
            if result.upper().startswith("SUMMARY:"):
                result = result[8:].strip()

        return {"summary": result or "No summary", "top_picks": []}

    def analyze_entry_zones(self, markets: List[Dict]) -> List[Dict]:
        """Task 11: Entry zone analysis - BUY_YES/BUY_NO/WAIT/AVOID based on outcomePrices, volume, trades.

        Input: markets with question, volume, outcomePrices, optional recent_trades.
        Returns: list of {entry_zone, reason, confidence} in same order as markets.
        """
        if not markets:
            return []

        import json

        market_inputs = []
        for m in markets[:10]:
            q = m.get("question", "")[:80]
            vol = float(m.get("volume", 0) or 0)
            raw_prices = m.get("outcomePrices")
            prices = (
                json.loads(raw_prices)
                if isinstance(raw_prices, str)
                else (raw_prices or [])
            )
            yes_pct = float(prices[0]) if prices and len(prices) >= 1 else 0.5
            no_pct = float(prices[1]) if prices and len(prices) >= 2 else 1 - yes_pct
            trades = m.get("recent_trades", [])
            trade_summary = ""
            if trades:
                sides = [t.get("side", "?") for t in trades[:10]]
                trade_summary = f" Recent flow: {', '.join(str(s) for s in sides[:5])}"

            market_inputs.append(
                f"- {q} | Vol: ${vol:,.0f} | YES: {yes_pct:.0%} NO: {no_pct:.0%}{trade_summary}\n  Social Media Sentiment: [Placeholder]\n  News Analysis: [Placeholder]"
            )

        prompt = f"""ENTRY ZONE ANALYSIS - Prediction market strategy:

For each market, consider:
1. YES/NO split from outcomePrices - is crowd skewed?
2. Volume level - liquidity for entry/exit
3. Recent trades (if provided) - flow direction
4. Timeframe - 5M/15M = fee risk

Markets:
{chr(10).join(market_inputs)}

Return for EACH market (one block per market):
ENTRY_ZONE: [BUY_YES/BUY_NO/WAIT/AVOID]
REASON: [1-2 sentences based on sentiment, volume, news, and other data points]
CONFIDENCE: [high/medium/low]"""

        result = self._call(prompt, max_tokens=400)
        heuristic = [self._heuristic_entry_zone(m) for m in markets]
        results = []
        if not result:
            return heuristic

        # Parse response - extract entry_zone, reason, confidence per block
        current = {}
        for line in result.split("\n"):
            line = line.strip()
            if "ENTRY_ZONE:" in line.upper():
                for zone in ["BUY_YES", "BUY_NO", "WAIT", "AVOID"]:
                    if zone in line.upper():
                        current["entry_zone"] = zone
                        break
            elif "REASON:" in line.upper():
                current["reason"] = (
                    line.split("REASON:")[-1].split("CONFIDENCE:")[0].strip()
                )
            elif "CONFIDENCE:" in line.upper():
                for c in ["high", "medium", "low"]:
                    if c in line.lower():
                        current["confidence"] = c
                        break
                if current:
                    results.append(
                        {
                            "entry_zone": current.get("entry_zone", "WAIT"),
                            "reason": current.get("reason", ""),
                            "confidence": current.get("confidence", "low"),
                        }
                    )
                    current = {}

        # Merge with deterministic baseline: keep strong heuristic calls when AI is weak.
        for i, m in enumerate(markets):
            if i >= len(results):
                results.append(heuristic[i])
                continue
            ai_pick = results[i]
            base_pick = heuristic[i]
            if ai_pick.get("entry_zone") in ("WAIT", "AVOID") and base_pick.get(
                "entry_zone"
            ) in ("BUY_YES", "BUY_NO"):
                results[i] = base_pick
            elif not ai_pick.get("reason"):
                ai_pick["reason"] = base_pick.get("reason", "")
        return results[: len(markets)]


# Singleton
ai_filter = AIFilter()
