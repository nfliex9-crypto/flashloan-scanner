from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


PAPER_BASE_URL = "https://paper-api.alpaca.markets"
ALLOWED_CRYPTO = {"BTC/USD", "ETH/USD"}


@dataclass(frozen=True)
class PaperCredentials:
    key_id: str
    secret_key: str

    @property
    def configured(self) -> bool:
        return bool(self.key_id and self.secret_key)


def credentials() -> PaperCredentials:
    return PaperCredentials(
        key_id=os.getenv("ALPACA_PAPER_API_KEY", "").strip(),
        secret_key=os.getenv("ALPACA_PAPER_API_SECRET", "").strip(),
    )


def is_configured() -> bool:
    return credentials().configured


def _request(
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
) -> dict | list:
    creds = credentials()
    if not creds.configured:
        raise RuntimeError("Alpaca paper credentials are not configured")

    data = None
    headers = {
        "APCA-API-KEY-ID": creds.key_id,
        "APCA-API-SECRET-KEY": creds.secret_key,
        "Accept": "application/json",
        "User-Agent": "AEGIS-Paper-Broker/1.0",
    }

    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        PAPER_BASE_URL + path,
        data=data,
        method=method,
        headers=headers,
    )

    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Alpaca paper API HTTP {exc.code}: {detail[:240]}"
        ) from exc


def account() -> dict:
    raw = _request("/v2/account")
    return {
        "id": raw.get("id"),
        "status": raw.get("status"),
        "currency": raw.get("currency"),
        "cash": float(raw.get("cash") or 0),
        "equity": float(raw.get("equity") or 0),
        "buying_power": float(raw.get("buying_power") or 0),
        "portfolio_value": float(raw.get("portfolio_value") or 0),
        "trading_blocked": bool(raw.get("trading_blocked")),
        "account_blocked": bool(raw.get("account_blocked")),
        "pattern_day_trader": bool(raw.get("pattern_day_trader")),
    }


def positions() -> list[dict]:
    raw = _request("/v2/positions")
    out = []
    for row in raw:
        out.append(
            {
                "symbol": row.get("symbol"),
                "qty": float(row.get("qty") or 0),
                "market_value": float(row.get("market_value") or 0),
                "cost_basis": float(row.get("cost_basis") or 0),
                "unrealized_pl": float(row.get("unrealized_pl") or 0),
                "unrealized_plpc": float(row.get("unrealized_plpc") or 0),
                "current_price": float(row.get("current_price") or 0),
                "side": row.get("side"),
            }
        )
    return out


def orders(limit: int = 20) -> list[dict]:
    raw = _request(
        f"/v2/orders?status=all&limit={max(1, min(limit, 100))}&direction=desc"
    )
    return [
        {
            "id": row.get("id"),
            "symbol": row.get("symbol"),
            "side": row.get("side"),
            "type": row.get("type"),
            "status": row.get("status"),
            "qty": row.get("qty"),
            "notional": row.get("notional"),
            "filled_qty": row.get("filled_qty"),
            "filled_avg_price": row.get("filled_avg_price"),
            "created_at": row.get("created_at"),
            "filled_at": row.get("filled_at"),
        }
        for row in raw
    ]


def place_market_order(
    *,
    symbol: str,
    side: str,
    notional_usd: float,
) -> dict:
    if symbol not in ALLOWED_CRYPTO:
        raise ValueError(f"unsupported paper symbol: {symbol}")

    side = side.lower().strip()
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")

    max_order = float(os.getenv("AEGIS_PAPER_MAX_ORDER_USD", "1000"))
    notional_usd = float(notional_usd)

    if notional_usd <= 0:
        raise ValueError("notional must be positive")
    if notional_usd > max_order:
        raise ValueError(
            f"paper order exceeds AEGIS_PAPER_MAX_ORDER_USD={max_order:.2f}"
        )

    raw = _request(
        "/v2/orders",
        method="POST",
        body={
            "symbol": symbol,
            "notional": f"{notional_usd:.2f}",
            "side": side,
            "type": "market",
            "time_in_force": "gtc",
        },
    )

    return {
        "id": raw.get("id"),
        "symbol": raw.get("symbol"),
        "side": raw.get("side"),
        "type": raw.get("type"),
        "status": raw.get("status"),
        "notional": raw.get("notional"),
        "qty": raw.get("qty"),
        "created_at": raw.get("created_at"),
    }
