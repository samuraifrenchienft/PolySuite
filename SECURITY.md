# Security Notes

## API Key Storage

### Bankr API Keys (SEC-001)

User Bankr API keys (from `/connect` or similar) are stored **in memory only**. They are not persisted to disk or database.

- **Single-user deployments:** Acceptable; keys are lost on restart.
- **Multi-user deployments:** Consider encrypted storage (e.g. per-user encrypted vault) for production. Keys in memory can be exposed via memory dumps or debuggers.

### Config and Secrets

- **Config.** Secrets are loaded from `.env` (preferred) or `config.json`.
- **Logging.** `Config.__repr__` and `get_safe_for_logging()` redact secrets. Use these when logging config.
- **Strict mode.** Set `POLYSUITE_STRICT_SECRETS=1` to require secrets from environment variables only.

## Address Validation

- **Ethereum:** `is_valid_eth_address()` enforces length (42 chars) and optional EIP-55 checksum.
- **Solana:** `is_valid_solana_address()` validates base58 format and length (32–44 chars).

## Flask Secret Key (MED-007)

In production, set `FLASK_SECRET_KEY` in `.env` to a stable value (e.g. `openssl rand -hex 32`). Without it, Flask uses a new random key per restart, invalidating sessions and signed cookies.

## Credential Storage (Copy Trading)

- **CREDENTIAL_ENCRYPTION_KEY:** Required for storing Polymarket/Kalshi API credentials. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Store in `.env` only. **Never log or expose this key.**
- Credentials are encrypted with AES (Fernet) and stored in `data/polysuite.db` in the `user_credentials` table.
