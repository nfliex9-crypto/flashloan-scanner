from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .execution import (
    DEFAULT_TAKER_FEE_BPS,
    OrderBook,
    buy_with_quote,
    fetch_order_book,
    sell_quantity,
)
from .live_lab import ASSETS, STRATEGIES, fetch_ohlc, strategy_positions


STATE_PATH = Path("data/paper_state.json")
INTERVAL_MINUTES = 15
INITIAL_EQUITY = 10_000.0
STATE_VERSION = 2


def agent_id(symbol: str, strategy: str, variant: int) -> str:
    return f"{symbol.lower()}-{strategy.lower().replace(' ', '-')}-g{variant}"


def signal_for(candles, strategy: str, variant: int) -> int:
    closes = [c.close for c in candles]
    return strategy_positions(closes, strategy, variant)[-1]


def fresh_state(*, migrated_from: int | None = None) -> dict:
    state = {
        "version": STATE_VERSION,
        "mode": "FORWARD_PAPER_L2_EXECUTION",
        "interval_minutes": INTERVAL_MINUTES,
        "initial_equity_per_agent": INITIAL_EQUITY,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "last_run_utc": None,
        "source": "Kraken closed 15m OHLC + live L2 order book",
        "execution_model": {
            "type": "market_order_vwap",
            "book_depth": 100,
            "taker_fee_bps": DEFAULT_TAKER_FEE_BPS,
            "fills": "live order book at worker run time",
            "missed_bars": "no historical fill backfill; current live book only",
        },
        "agents": {},
    }
    if migrated_from is not None:
        state["migration_note"] = (
            f"Paper ledger reset from v{migrated_from} to v{STATE_VERSION} "
            "because the execution model changed to L2 order-book fills."
        )
    return state


def load_state() -> dict:
    if not STATE_PATH.exists():
        return fresh_state()

    old = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if int(old.get("version", 1)) != STATE_VERSION:
        return fresh_state(migrated_from=int(old.get("version", 1)))
    return old


def liquidation_value(cash: float, quantity: float, book: OrderBook) -> float:
    if quantity <= 0:
        return cash
    fill = sell_quantity(book, quantity)
    return cash + fill.net_quote


def _record(agent: dict, *, ts: int, price: float, event: str) -> None:
    history = list(agent.get("history", []))
    history.append(
        {
            "ts": ts,
            "equity": round(float(agent["equity"]), 6),
            "cash": round(float(agent["cash"]), 6),
            "asset_qty": round(float(agent["asset_qty"]), 12),
            "position": int(agent["position"]),
            "price": price,
            "event": event,
        }
    )
    agent["history"] = history[-500:]


def _apply_buy(agent: dict, book: OrderBook) -> dict:
    cash_before = float(agent["cash"])
    fill = buy_with_quote(book, cash_before)
    spent = fill.gross_quote + fill.fee_quote

    agent["cash"] = max(0.0, cash_before - spent)
    agent["asset_qty"] = float(agent["asset_qty"]) + fill.filled_quantity
    agent["position"] = 1 if agent["asset_qty"] > 0 else 0
    agent["total_fees_usd"] += fill.fee_quote
    agent["total_slippage_usd"] += max(
        0.0,
        (fill.vwap - fill.best_price) * fill.filled_quantity,
    )
    agent["open_trade_start_equity"] = cash_before
    agent["last_fill"] = fill.to_dict()
    return fill.to_dict()


def _apply_sell(agent: dict, book: OrderBook) -> dict:
    qty = float(agent["asset_qty"])
    fill = sell_quantity(book, qty)

    agent["cash"] = float(agent["cash"]) + fill.net_quote
    agent["asset_qty"] = max(0.0, qty - fill.filled_quantity)
    agent["position"] = 1 if agent["asset_qty"] > 1e-12 else 0
    agent["total_fees_usd"] += fill.fee_quote
    agent["total_slippage_usd"] += max(
        0.0,
        (fill.best_price - fill.vwap) * fill.filled_quantity,
    )
    agent["last_fill"] = fill.to_dict()

    if agent["position"] == 0:
        start_equity = agent.get("open_trade_start_equity")
        if start_equity:
            trade_return = float(agent["cash"]) / float(start_equity) - 1.0
            agent["last_trade_return"] = trade_return
            agent["closed_trades"] += 1
            if trade_return > 0:
                agent["winning_trades"] += 1
        agent["open_trade_start_equity"] = None

    return fill.to_dict()


def _update_risk(agent: dict, book: OrderBook) -> None:
    equity = liquidation_value(
        float(agent["cash"]),
        float(agent["asset_qty"]),
        book,
    )
    peak = max(float(agent["peak_equity"]), equity)
    drawdown = 1.0 - equity / peak if peak > 0 else 0.0

    agent["equity"] = equity
    agent["peak_equity"] = peak
    agent["max_drawdown"] = max(float(agent["max_drawdown"]), drawdown)


def new_agent(
    symbol: str,
    strategy: str,
    variant: int,
    candles,
    book: OrderBook,
) -> dict:
    signal = signal_for(candles, strategy, variant)

    agent = {
        "agent_id": agent_id(symbol, strategy, variant),
        "asset": symbol,
        "strategy": strategy,
        "generation": variant,
        "interval_minutes": INTERVAL_MINUTES,
        "initial_equity": INITIAL_EQUITY,
        "cash": INITIAL_EQUITY,
        "asset_qty": 0.0,
        "equity": INITIAL_EQUITY,
        "peak_equity": INITIAL_EQUITY,
        "max_drawdown": 0.0,
        "position": 0,
        "open_trade_start_equity": None,
        "last_closed_ts": candles[-1].ts,
        "last_price": candles[-1].close,
        "closed_trades": 0,
        "winning_trades": 0,
        "last_trade_return": None,
        "updates": 1,
        "last_event": "INIT_FLAT",
        "last_fill": None,
        "total_fees_usd": 0.0,
        "total_slippage_usd": 0.0,
        "missed_bar_events": 0,
        "history": [],
    }

    if signal:
        _apply_buy(agent, book)
        agent["last_event"] = "INIT_LONG_L2"

    _update_risk(agent, book)
    _record(
        agent,
        ts=candles[-1].ts,
        price=candles[-1].close,
        event=agent["last_event"],
    )
    return agent


def advance_agent(
    agent: dict,
    strategy: str,
    variant: int,
    candles,
    book: OrderBook,
) -> bool:
    timestamps = [c.ts for c in candles]
    last_ts = int(agent["last_closed_ts"])

    if last_ts not in timestamps:
        agent["missed_bar_events"] += 1
        new_signal = signal_for(candles, strategy, variant)

        if new_signal != int(agent["position"]):
            if new_signal:
                _apply_buy(agent, book)
                event = "REANCHOR_ENTER_LONG_L2"
            else:
                _apply_sell(agent, book)
                event = "REANCHOR_EXIT_LONG_L2"
        else:
            event = "REANCHORED_NO_BACKFILL"

        agent["last_closed_ts"] = candles[-1].ts
        agent["last_price"] = candles[-1].close
        agent["updates"] += 1
        agent["last_event"] = event
        _update_risk(agent, book)
        _record(
            agent,
            ts=candles[-1].ts,
            price=candles[-1].close,
            event=event,
        )
        return True

    start = timestamps.index(last_ts)
    if start >= len(candles) - 1:
        return False

    # If more than one bar was missed, do not invent historical fills.
    if len(candles) - 1 - start > 1:
        agent["missed_bar_events"] += 1
        latest_signal = signal_for(candles, strategy, variant)

        if latest_signal != int(agent["position"]):
            if latest_signal:
                _apply_buy(agent, book)
                event = "GAP_ENTER_LONG_L2"
            else:
                _apply_sell(agent, book)
                event = "GAP_EXIT_LONG_L2"
        else:
            event = "GAP_NO_BACKFILL"

        agent["last_closed_ts"] = candles[-1].ts
        agent["last_price"] = candles[-1].close
        agent["updates"] += 1
        agent["last_event"] = event
        _update_risk(agent, book)
        _record(
            agent,
            ts=candles[-1].ts,
            price=candles[-1].close,
            event=event,
        )
        return True

    candle = candles[-1]
    new_signal = signal_for(candles, strategy, variant)
    current = int(agent["position"])

    if new_signal != current:
        if new_signal:
            _apply_buy(agent, book)
            event = "ENTER_LONG_L2"
        else:
            _apply_sell(agent, book)
            event = "EXIT_LONG_L2"
    else:
        event = "HOLD_LONG" if current else "HOLD_FLAT"

    agent["last_closed_ts"] = candle.ts
    agent["last_price"] = candle.close
    agent["updates"] += 1
    agent["last_event"] = event
    _update_risk(agent, book)
    _record(agent, ts=candle.ts, price=candle.close, event=event)
    return True


def fetch_symbol_inputs(symbol: str, pair: str):
    with ThreadPoolExecutor(max_workers=2) as pool:
        candle_future = pool.submit(
            fetch_ohlc,
            pair,
            INTERVAL_MINUTES,
            closed_only=True,
        )
        book_future = pool.submit(fetch_order_book, pair, 100)
        return candle_future.result(), book_future.result()


def run_tick() -> dict:
    state = load_state()
    changed = False

    for symbol, pair in ASSETS.items():
        candles, book = fetch_symbol_inputs(symbol, pair)

        for idx, strategy in enumerate(STRATEGIES):
            variant = idx % 2
            key = agent_id(symbol, strategy, variant)

            if key not in state["agents"]:
                state["agents"][key] = new_agent(
                    symbol,
                    strategy,
                    variant,
                    candles,
                    book,
                )
                changed = True
            else:
                changed = (
                    advance_agent(
                        state["agents"][key],
                        strategy,
                        variant,
                        candles,
                        book,
                    )
                    or changed
                )

    if changed:
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
            "total_fees_usd": sum(
                float(a["total_fees_usd"]) for a in state["agents"].values()
            ),
            "total_slippage_usd": sum(
                float(a["total_slippage_usd"]) for a in state["agents"].values()
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
        "AEGIS L2 paper tick",
        "changed=" + str(result["changed"]),
        "agents=" + str(len(state.get("agents", {}))),
        "last_run=" + str(state.get("last_run_utc")),
    )


if __name__ == "__main__":
    main()
