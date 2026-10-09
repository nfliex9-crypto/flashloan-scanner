"""AEGIS Windows MT5 Demo connector. No MT5 trade_send or private DB credentials.

Run beside an MT5 terminal already logged into a DEMO account. A 43-char
website pairing code is saved in Windows Credential Manager (keyring).
Only POST /api/mt5_link?action=sync with a bounded, read-only snapshot.
"""
from __future__ import annotations

import getpass
import json
import sys
import time
import urllib.error
import urllib.request

from demo_adapters import DemoConnectionError, read_mt5_demo_gold

API_URL = "https://flashloan-scanner-git-agent-city-v1-flashloan.vercel.app/api/mt5_link"
CREDENTIAL_SERVICE = "AEGIS_MT5_DEMO_READ_ONLY"
CREDENTIAL_KEY = "agent-city-v1"
POLL_SECONDS = 60


def sync(token: str, symbol: str) -> dict:
    snapshot = read_mt5_demo_gold(symbol=symbol, days=14)
    # Restrict every payload to recent confirmed broker-side rows.
    snapshot["fills"] = sorted(
        snapshot["fills"], key=lambda row: row["executed_at"])[-200:]
    snapshot["open_positions"] = snapshot["open_positions"][:100]
    raw = json.dumps({"action": "sync", "snapshot": snapshot}).encode("utf-8")
    if len(raw) > 100_000:
        raise ValueError("Broker ledger exceeds the safe upload limit")
    request = urllib.request.Request(API_URL, data=raw, method="POST",
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json",
                 "User-Agent": "AEGIS-MT5-DEMO-READONLY/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=25) as reply:
            response = json.loads(reply.read(4096))
    except urllib.error.HTTPError as exc:
        # The API returns only error codes. Never echo signed URLs, secrets
        # or MT5 login / broker account identifiers.
        try:
            data = json.loads(exc.read(1024))
            reason = str(data.get("error", "http_error"))
        except (ValueError, UnicodeDecodeError, AttributeError):
            reason = "endpoint_or_deployment_protection_unavailable"
        raise RuntimeError("Sync refused (HTTP " + str(exc.code) + "): " +
                           reason[:85]) from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("AEGIS server unavailable or blocked by Vercel protection") from None
    if response.get("ok") is not True:
        raise RuntimeError("AEGIS refused the demo-only ledger")
    return response


def run() -> int:
    try:
        import keyring
    except ImportError:
        print("Install keyring with pip (Windows Credential Manager); stopping.")
        return 2
    print("AEGIS / MT5 DEMO CONNECTOR (READ ONLY)")
    print("Never enter an MT5 trading password here. Open your MT5 Demo terminal first.")
    symbol = input("Gold instrument (Enter for XAUUSD): ").strip() or "XAUUSD"
    token = keyring.get_password(CREDENTIAL_SERVICE, CREDENTIAL_KEY)
    if not token:
        token = getpass.getpass("Paste the pairing code from AEGIS website: ").strip()
    if len(token) < 40 or len(token) > 60 or not all(c.isalnum() or c in "_-" for c in token):
        print("Invalid pairing code. Generate another in the website.")
        return 2
    first = True
    while True:
        try:
            response = sync(token, symbol)
            if first:
                keyring.set_password(CREDENTIAL_SERVICE, CREDENTIAL_KEY, token)
                first = False
            print(time.strftime("%Y-%m-%d %H:%M:%S"),
                  "MT5 DEMO verified; broker ledger synchronized; new deals:",
                  response.get("new_fills", 0))
        except (DemoConnectionError, ValueError, RuntimeError) as exc:
            # Only safe adapter/HTTP messages, never broker credentials.
            print(time.strftime("%Y-%m-%d %H:%M:%S"), type(exc).__name__,
                  str(exc)[:130])
            if ("401" in str(exc) or "403" in str(exc) or "410" in str(exc)):
                keyring.delete_password(CREDENTIAL_SERVICE, CREDENTIAL_KEY) if keyring.get_password(
                    CREDENTIAL_SERVICE, CREDENTIAL_KEY) else None
                print("The pairing was revoked, expired or points to a different demo account.")
                return 2
        except KeyboardInterrupt:
            print("Connector stopped. No MT5 orders sent.")
            return 0
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        sys.exit(0)
