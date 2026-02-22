#!/usr/bin/env python3
"""Test Bankr integration as used by Discord bot.

Run: python test_bankr_discord.py

Uses 1 of 100 free daily messages if BANKR_API_KEY is set.
"""

import os
import sys
import time
from dotenv import load_dotenv
load_dotenv()

BANKR_KEY = os.getenv("BANKR_API_KEY", "")


def test_bankr_flow():
    if not BANKR_KEY:
        print("No BANKR_API_KEY - skipping live test")
        return False

    from src.market.bankr import BankrClient
    client = BankrClient(BANKR_KEY)
    prompt = "what is the price of ETH?"
    print(f"Submitting: {prompt}")

    job_id, error_msg = client.send_prompt(prompt)
    if not job_id:
        print(f"FAIL: {error_msg}")
        return False

    for i in range(60):
        time.sleep(2)
        status = client.get_job_status(job_id)
        if status and status.get("status") == "completed":
            result = status.get("result") or status.get("response", "")
            print(f"SUCCESS: {result[:200]}...")
            return True
        if status and status.get("status") == "failed":
            print(f"FAIL: {status.get('error')}")
            return False

    print("TIMEOUT")
    return False


if __name__ == "__main__":
    ok = test_bankr_flow()
    sys.exit(0 if ok else 1)
