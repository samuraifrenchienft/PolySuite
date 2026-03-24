# PolySuite Architecture Refactor Plan

> Goal: Better architecture, cleaner code, more efficient execution, embedded data insights — while keeping strategy logic intact.

---

## Phase 1: Critical Fixes ✅

| # | Task | Status |
|---|------|--------|
| 1 | Implement `SignalGenerator` | Done |
| 2 | Centralize DB/paths in `src/config/paths.py` | Done |
| 3 | Remove duplicate imports (PositionAlerter) | Done |

---

## Phase 2: Detector Factory & Scan Pipeline ✅

| # | Task | Purpose |
|---|------|---------|
| 4 | Create `DetectorFactory(config, storage, api_factory)` | Done — `src/core/detector_factory.py` |
| 5 | Create `ScanPipeline` | Done — `src/core/scan_pipeline.py` |
| 6 | Unify insider modules | Deferred — InsiderSignalDetector used consistently |

---

## Phase 3: Strategy Data & Insights ✅

| # | Task | Purpose |
|---|------|---------|
| 7 | Add `scan_results` table | Done — `ScanResultsStorage` in `src/analytics/scan_results_storage.py` |
| 8 | Embed insights in dashboard | Strategy metrics API provides data |
| 9 | Strategy metrics API | Done — `/api/strategy/metrics` |

---

## Phase 4: Cleanup & Polish

| # | Task | Purpose |
|---|------|---------|
| 10 | Alert interface (`AlertBackend`) | Future — unified send API for Discord/Telegram |
| 11 | Standardize config access | Prefer `config.get()` with defaults (in place) |
| 12 | Consolidate backup naming | `polysuite_*.db` everywhere (future) |

---

## File Structure (Target)

```
src/
├── config/
│   ├── __init__.py      # Config class
│   └── paths.py         # DB_PATH, COPY_TARGETS_PATH, etc.
├── core/
│   ├── detector_factory.py   # DetectorFactory
│   ├── scan_pipeline.py      # ScanPipeline
│   └── alert_backend.py      # AlertBackend interface (future)
├── analytics/
│   ├── smart_money.py
│   └── signals.py            # SignalGenerator
├── alerts/                    # Strategy logic (unchanged)
├── wallet/                    # Wallet domain (unchanged)
├── market/                    # APIs (unchanged)
└── ...
```

---

## Data Flow (Target)

```
Config + Paths (centralized)
    ↓
DetectorFactory → ConvergenceDetector, InsiderSignalDetector, ContrarianDetector
    ↓
ScanPipeline.run() → normalized results
    ↓
Storage (WalletStorage + ScanResultsStorage)
    ↓
AlertBackend.send_*() → Discord / Telegram
```
