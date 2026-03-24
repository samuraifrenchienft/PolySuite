# Bot Functions Checklist — Develop or Cut

Updated with your decisions.

---

## Your Decisions

| Item | Decision |
|------|----------|
| **Jupiter** | Keep — developing prediction markets |
| **Signals** | Develop — notice on wallet upload complete; popup with important data when signal; run on vetted wallets |
| **Markets tab** | Yes — add Markets tab |
| **Kalshi** | Cut except high-volume markets (fees problem) |
| **Wallet detail modal** | Yes — with analysis (positions + history) |
| **Convergence** | **HIGH PRIORITY** — develop first |

---

## Priority Order

### HIGH PRIORITY
1. **Convergence** — Add "Check Convergence" button in Alerts tab; wire convergence to dashboard

### TODO (develop later)
2. **Markets tab** — List active/resolved markets
3. **Wallet detail modal** — Click row → modal with positions, history, analysis
4. **Signals** — Notice when wallet upload complete; popup when signal; run on vetted wallets
5. **check_positions** — Wire into Alerts tab
6. **check_odds** — Wire into Alerts tab
7. **Jupiter** — Prediction markets integration

### Cut / Defer
- **Kalshi** — Cut except high-volume markets (fees)

---

## Signals — What Exists

See `SIGNALS_OVERVIEW.md` for full detail. Summary:

- **Convergence** — 2+ high-performers in same market (ConvergenceDetector)
- **Insider** — Fresh wallet + large trade + win (InsiderSignalDetector)
- **Contrarian** — Minority vs majority volume
- **TradeSignal** — Executable trade (trade_executor)
- **CLI `signals`** — Broken (SignalGenerator not defined)

**Gap:** Monitor uses high performers, not vetted. You want strategy on vetted wallets.
