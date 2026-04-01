"""Re-vet all tracked wallets with the fixed scoring logic."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from src.config import Config
from src.config.paths import DB_PATH
from src.wallet.storage import WalletStorage
from src.wallet.vetting import WalletVetting
from src.market.api import APIClientFactory

config = Config()
storage = WalletStorage(db_path=DB_PATH)
api_factory = APIClientFactory(config)
vetter = WalletVetting(api_factory, config=config)

wallets = storage.list_wallets()
total = len(wallets)
print(f"Re-vetting {total} wallets with fixed scoring...\n")

passed = failed = errors = 0
for i, w in enumerate(wallets, 1):
    print(f"[{i}/{total}] {w.address[:18]}...", end=" ", flush=True)
    try:
        result = vetter.vet_wallet(w.address, min_bet=10, platform="polymarket")
        if not result:
            print("no trades / skipped")
            failed += 1
            continue

        storage.update_wallet_vetting(
            w.address,
            bot_score=result.get("bot_score"),
            unresolved_exposure_usd=None,
            total_pnl=result.get("total_pnl"),
            roi_pct=result.get("roi_pct"),
            conviction_score=result.get("conviction_score"),
            is_specialty=bool(result.get("is_specialty")),
            specialty_note=result.get("specialty_note"),
            specialty_market_id=result.get("specialty_market_id"),
            specialty_category=result.get("specialty_category"),
            specialty_roi_pct=result.get("specialty_roi_pct"),
            is_win_streak_badge=result.get("is_win_streak_badge", False),
            tier="vetted" if result.get("passed") else "watch",
            total_trades=result.get("total_trades"),
            wins=result.get("total_wins"),
            win_rate=result.get("win_rate_real"),
            trade_volume=result.get("total_volume"),
        )

        tag = "PASS" if result.get("passed") else "fail"
        bot = result.get("bot_score", 0)
        spec = result.get("specialty_category") or ""
        print(f"{tag}  bot={bot}  spec={spec or 'none'}")
        if result.get("passed"):
            passed += 1
        else:
            failed += 1

    except Exception as e:
        print(f"ERROR: {e}")
        errors += 1

print(f"\nDone. {passed} passed | {failed} failed | {errors} errors out of {total} wallets.")
