# PolySuite — security notes

## Dashboard (Flask)

| Variable | Purpose |
|----------|---------|
| `DASHBOARD_REQUIRE_AUTH` | Set to `true` or `1` to require `X-API-KEY` on every dashboard/API request. |
| `DASHBOARD_API_KEY` | Shared secret sent as header `X-API-KEY`. Required when auth is enabled. |

**Production:** enable both. The app logs a warning at startup if `DASHBOARD_REQUIRE_AUTH` is true but the API key is empty, and an info line if auth is disabled.

## Secrets

- Prefer environment variables for tokens (see `SECRET_KEYS` in `src/config/__init__.py`).
- Do not commit `config.json` if it contains live keys; use `.env` (not committed) for local dev.

## Logging

- Set `LOG_LEVEL` (default `INFO`) for stderr logging from `main.py` and library modules.
- Avoid logging full API keys or session tokens.

## Third-party APIs

- Polymarket, Pump Archive, DexScreener, and others are called over HTTPS; review trust before production deploy.
