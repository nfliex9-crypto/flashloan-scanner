from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .live_lab import (
    ASSETS,
    COST_PER_POSITION_CHANGE,
    STRATEGIES,
    fetch_ohlc,
    strategy_positions,
)


STATE_PATH = Path("data/paper_state.json")
INTERVAL_MINUTES = 15
INITIAL_EQUITY = 10_000.0


def agent_id(symbol: str, strategy: str, variant: int) -> str:
    return f"{symbol.lower()}-{strategy.lower().replace(' ', '-')}-g{variant}"


def signal_for(candles, strategy: str, variant: int) -> int:
    closes = [c.close for c in candles]
    return strategy_positions(closes, strategy, variant)[-1]


def new_agent(symbol: str, strategy: str, variant: int, candles) -> dict:
    signal = signal_for(candles, strategy, variant)
    equity = INITIAL_EQUITY
    event = "INIT_FLAT"
    entry_equity = None

    if signal:
        entry_equity = equity
        equity *= 1.0 - COST_PER_POSITION_CHANGE
        event = "INIT_LONG"

    return {
        "agent_id": agent_id(symbol, strategy, variant),
        "asset": symbol,
        "strategy": strategy,
        "generation": variant,
        "interval_minutes": INTERVAL_MINUTES,
        "initial_equity": INITIAL_EQUITY,
        "equity": equity,
        "peak_equity": max(INITIAL_EQUITY, equity),
        "max_drawdown": 0.0,
        "position": signal,
        "entry_equity_before_cost": entry_equity,
        "last_closed_ts": candles[-1].ts,
        "last_price": candles[-1].close,
        "closed_trades": 0,
        "winning_trades": 0,
        "last_trade_return": None,
        "updates": 1,
        "last_event": event,
        "history": [
            {
                "ts": candles[-1].ts,
                "equity": round(equity, 6),
                "position": signal,
                "price": candles[-1].close,
                "event": event,
            }
        ],
    }


def advance_agent(agent: dict, strategy: str, variant: int, candles) -> bool:
    timestamps = [c.ts for c in candles]
    last_ts = int(agent["last_closed_ts"])

    if last_ts not in timestamps:
        # Kraken exposes a rolling window. If the worker was offline too long,
        # re-anchor instead of inventing performance for missing candles.
        agent["last_closed_ts"] = candles[-1].ts
        agent["last_price"] = candles[-1].close
        agent["position"] = signal_for(candles, strategy, variant)
        agent["entry_equity_before_cost"] = None
        agent["last_event"] = "REANCHORED"
        return True

    start = timestamps.index(last_ts)
    if start >= len(candles) - 1:
        return False

    changed = False

    for i in range(start + 1, len(candles)):
        previous_close = candles[i - 1].close
        candle = candles[i]
        equity = float(agent["equity"])
        position = int(agent["position"])

        # Existing position experiences the next closed-bar return.
        if position:
            equity *= candle.close / previous_close

        new_signal = strategy_positions(
            [c.close for c in candles[: i + 1]],
            strategy,
            variant,
        )[-1]

        event = "HOLD_LONG" if position else "HOLD_FLAT"

        if new_signal != position:
            equity_before_cost = equity
            equity *= 1.0 - COST_PER_POSITION_CHANGE

            if position == 0 and new_signal == 1:
                agent["entry_equity_before_cost"] = equity_before_cost
                event = "ENTER_LONG"

            elif position == 1 and new_signal == 0:
                entry = agent.get("entry_equity_before_cost")
                if entry:
                    trade_return = equity / float(entry) - 1.0
                    agent["last_trade_return"] = trade_return
                    agent["closed_trades"] = int(agent["closed_trades"]) + 1
                    if trade_return > 0:
                        agent["winning_trades"] = int(agent["winning_trades"]) + 1
                agent["entry_equity_before_cost"] = None
                event = "EXIT_LONG"

            position = new_signal

        peak = max(float(agent["peak_equity"]), equity)
        drawdown = 1.0 - equity / peak if peak > 0 else 0.0

        agent["equity"] = equity
        agent["peak_equity"] = peak
        agent["max_drawdown"] = max(float(agent["max_drawdown"]), drawdown)
        agent["position"] = position
        agent["last_closed_ts"] = candle.ts
        agent["last_price"] = candle.close
        agent["updates"] = int(agent["updates"]) + 1
        agent["last_event"] = event

        history = list(agent.get("history", []))
        history.append(
            {
                "ts": candle.ts,
                "equity": round(equity, 6),
                "position": position,
                "price": candle.close,
                "event": event,
            }
        )
        agent["history"] = history[-500:]
        changed = True

    return changed


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))

    return {
        "version": 1,
        "mode": "FORWARD_PAPER_ONLY",
        "interval_minutes": INTERVAL_MINUTES,
        "initial_equity_per_agent": INITIAL_EQUITY,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "last_run_utc": None,
        "source": "Kraken public OHLC · closed 15m candles",
        "agents": {},
    }


def run_tick() -> dict:
    state = load_state()
    changed = False

    for symbol, pair in ASSETS.items():
        candles = fetch_ohlc(pair, INTERVAL_MINUTES, closed_only=True)

        for idx, strategy in enumerate(STRATEGIES):
            variant = idx % 2
            key = agent_id(symbol, strategy, variant)

            if key not in state["agents"]:
                state["agents"][key] = new_agent(
                    symbol, strategy, variant, candles
                )
                changed = True
            else:
                changed = (
                    advance_agent(
                        state["agents"][key],
                        strategy,
                        variant,
                        candles,
                    )
                    or changed
                )

    state["last_run_utc"] = datetime.now(timezone.utc).isoformat()
    state["agent_count"] = len(state["agents"])

    equities = [float(a["equity"]) for a in state["agents"].values()]
    state["summary"] = {
        "average_equity": (
            sum(equities) / len(equities) if equities else INITIAL_EQUITY
        ),
        "best_equity": max(equities) if equities else INITIAL_EQUITY,
        "worst_equity": min(equities) if equities else INITIAL_EQUITY,
        "total_closed_trades": sum(
            int(a["closed_trades"]) for a in state["agents"].values()
        ),
        "max_observed_drawdown": max(
            (float(a["max_drawdown"]) for a in state["agents"].values()),
            default=0.0,
        ),
    }

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {"changed": changed, "state": state}


def main() -> None:
    result = run_tick()
    state = result["state"]
    print(
        "AEGIS paper tick",
        "changed=" + str(result["changed"]),
        "agents=" + str(state["agent_count"]),
        "last_run=" + str(state["last_run_utc"]),
    )


if __name__ == "__main__":
    main()
