from __future__ import annotations

import json
import os
import urllib.request

from .alpaca_paper import (
    account,
    close_position,
    is_configured,
    place_market_order,
    positions,
)
from .brain import assess_agent
from .evolution import Genome, positions_for_genome
from .live_lab import ASSETS, fetch_ohlc


EVOLUTION_URL = (
    "https://raw.githubusercontent.com/"
    "nfliex9-crypto/flashloan-scanner/"
    "evolution-state/data/evolution_state.json"
)
PAPER_URL = (
    "https://raw.githubusercontent.com/"
    "nfliex9-crypto/flashloan-scanner/"
    "paper-state/data/paper_state.json"
)

SYMBOL_MAP = {
    "BTC": "BTC/USD",
    "ETH": "ETH/USD",
}


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AEGIS-AutoPaper/1.0"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


def enabled() -> bool:
    return os.getenv("AEGIS_AUTOPAPER_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def normalized_position_symbols(rows: list[dict]) -> set[str]:
    out = set()
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        out.add(symbol.replace("/", ""))
    return out


def paper_agent_for(
    paper: dict,
    *,
    asset: str,
    strategy: str,
) -> dict | None:
    for row in paper.get("agents", {}).values():
        if row.get("asset") == asset and row.get("strategy") == strategy:
            return row
    return None


def choose_champion(evolution: dict, asset: str) -> dict | None:
    rows = [
        row
        for row in evolution.get("incumbents", {}).values()
        if row.get("symbol") == asset
        and row.get("status") != "ELIMINATED"
    ]
    if not rows:
        return None

    rows.sort(
        key=lambda row: (
            int(row.get("evaluation", {}).get("confirmations") or 0),
            float(row.get("evaluation", {}).get("score") or 0),
        ),
        reverse=True,
    )
    return rows[0]


def current_signal(asset: str, champion: dict) -> int:
    pair = ASSETS[asset]
    candles = fetch_ohlc(pair, 15, closed_only=True)
    closes = [c.close for c in candles]

    raw = champion.get("genome") or {}
    genome = Genome(
        genome_id=raw["genome_id"],
        strategy=raw["strategy"],
        generation=int(raw["generation"]),
        params=raw["params"],
        parent_id=raw.get("parent_id"),
    )
    return positions_for_genome(closes, genome)[-1]


def brain_cap(
    asset: str,
    champion: dict,
    paper: dict,
) -> tuple[float, str, float]:
    ev = champion.get("evaluation", {})
    pa = paper_agent_for(
        paper,
        asset=asset,
        strategy=champion.get("strategy", ""),
    )

    if pa:
        initial = float(pa.get("initial_equity") or 10_000)
        equity = float(pa.get("equity") or initial)
        paper_return = equity / initial - 1.0 if initial else 0.0
        drag = (
            float(pa.get("total_fees_usd") or 0)
            + float(pa.get("total_slippage_usd") or 0)
        ) / initial if initial else 0.0
        paper_dd = float(pa.get("max_drawdown") or 0)
        closed = int(pa.get("closed_trades") or 0)
        updates = int(pa.get("updates") or 0)
        agent_id = pa.get("agent_id") or f"{asset}:{champion.get('strategy')}"
    else:
        paper_return = 0.0
        drag = 0.0
        paper_dd = 0.0
        closed = 0
        updates = 0
        agent_id = f"{asset}:{champion.get('strategy')}"

    verdict = assess_agent(
        agent_id=agent_id,
        research_score=float(ev.get("score") or 0),
        timeframe_confirmations=int(ev.get("confirmations") or 0),
        paper_return=paper_return,
        paper_drawdown=paper_dd,
        closed_trades=closed,
        paper_updates=updates,
        execution_drag_pct=drag,
    )

    return (
        verdict.max_risk_multiplier,
        verdict.action,
        verdict.trust_score,
    )


def target_notional(
    equity: float,
    risk_multiplier: float,
) -> float:
    base_risk_pct = max(0.01, min(env_float("AEGIS_BASE_RISK_PCT", 0.50), 5.0))
    stop_pct = max(0.25, min(env_float("AEGIS_STOP_PCT", 2.0), 25.0))
    max_position_pct = max(
        1.0,
        min(env_float("AEGIS_MAX_POSITION_PCT", 10.0), 50.0),
    )

    effective_risk = base_risk_pct * max(0.0, min(risk_multiplier, 1.0))
    risk_budget = equity * effective_risk / 100.0
    by_stop = risk_budget / (stop_pct / 100.0)
    by_position = equity * max_position_pct / 100.0
    return max(0.0, min(by_stop, by_position))


def run() -> dict:
    if not enabled():
        return {"ok": True, "enabled": False, "message": "AEGIS auto-paper is disabled."}

    if not is_configured():
        return {"ok": False, "enabled": True, "error": "Alpaca paper credentials missing."}

    evolution = fetch_json(EVOLUTION_URL)
    paper = fetch_json(PAPER_URL)

    acct = account()
    if acct.get("trading_blocked") or acct.get("account_blocked"):
        return {"ok": False, "enabled": True, "error": "Paper account is blocked."}

    equity = float(acct.get("equity") or 0)
    current_positions = positions()
    held = normalized_position_symbols(current_positions)

    actions = []

    for asset in ("BTC", "ETH"):
        champion = choose_champion(evolution, asset)
        if not champion:
            actions.append({"asset": asset, "action": "SKIP", "reason": "no champion"})
            continue

        signal = current_signal(asset, champion)
        multiplier, brain_action, trust = brain_cap(asset, champion, paper)
        symbol = SYMBOL_MAP[asset]
        held_now = symbol.replace("/", "") in held

        if brain_action == "QUARANTINE" or multiplier <= 0:
            if held_now:
                order = close_position(symbol)
                actions.append(
                    {
                        "asset": asset,
                        "action": "CLOSE_PAPER",
                        "reason": "brain quarantine",
                        "trust": trust,
                        "order": order,
                    }
                )
            else:
                actions.append(
                    {
                        "asset": asset,
                        "action": "SKIP",
                        "reason": "brain quarantine",
                        "trust": trust,
                    }
                )
            continue

        if signal == 1 and not held_now:
            notional = target_notional(equity, multiplier)
            minimum = env_float("AEGIS_MIN_PAPER_ORDER_USD", 25.0)
            if notional < minimum:
                actions.append(
                    {
                        "asset": asset,
                        "action": "SKIP",
                        "reason": "risk-sized order below minimum",
                        "trust": trust,
                        "notional": notional,
                    }
                )
                continue

            order = place_market_order(
                symbol=symbol,
                side="buy",
                notional_usd=notional,
            )
            actions.append(
                {
                    "asset": asset,
                    "action": "BUY_PAPER",
                    "strategy": champion.get("strategy"),
                    "trust": trust,
                    "risk_multiplier": multiplier,
                    "notional": notional,
                    "order": order,
                }
            )

        elif signal == 0 and held_now:
            order = close_position(symbol)
            actions.append(
                {
                    "asset": asset,
                    "action": "CLOSE_PAPER",
                    "strategy": champion.get("strategy"),
                    "trust": trust,
                    "order": order,
                }
            )

        else:
            actions.append(
                {
                    "asset": asset,
                    "action": "HOLD" if held_now else "FLAT",
                    "strategy": champion.get("strategy"),
                    "signal": signal,
                    "trust": trust,
                    "risk_multiplier": multiplier,
                }
            )

    return {
        "ok": True,
        "enabled": True,
        "paper_only": True,
        "account_equity": equity,
        "actions": actions,
    }


def main() -> None:
    result = run()
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
