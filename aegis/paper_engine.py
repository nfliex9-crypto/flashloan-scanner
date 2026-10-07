from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .live_lab import (
    ASSETS,
    Candle,
    evaluate_agent,
    fetch_ohlc,
    market_snapshot,
    strategy_positions,
)


@dataclass(frozen=True)
class RiskConfig:
    starting_equity: float = 100_000.0
    risk_per_trade: float = 0.0025
    max_position_notional_pct: float = 0.20
    atr_stop_multiple: float = 1.50
    reward_to_risk: float = 2.00
    fee_bps_per_side: float = 3.0
    slippage_bps_per_side: float = 2.0
    max_agent_drawdown_pct: float = 0.05

    def to_dict(self) -> dict:
        return asdict(self)


def _atr_at(candles: list[Candle], end: int, length: int = 14) -> float:
    if not candles:
        return 0.0
    start = max(1, end - length + 1)
    trs: list[float] = []
    for i in range(start, end + 1):
        current = candles[i]
        previous = candles[i - 1]
        trs.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return sum(trs) / len(trs) if trs else max(candles[end].high - candles[end].low, 0.0)


def _fill_price(raw_price: float, side: str, slippage_bps: float) -> float:
    slip = slippage_bps / 10_000.0
    if side == "BUY":
        return raw_price * (1.0 + slip)
    if side == "SELL":
        return raw_price * (1.0 - slip)
    raise ValueError(f"Unknown side: {side}")


def _fee(notional: float, fee_bps: float) -> float:
    return abs(notional) * fee_bps / 10_000.0


def _position_size(
    equity: float,
    entry: float,
    stop: float,
    config: RiskConfig,
) -> tuple[float, float, float]:
    stop_distance = max(entry - stop, entry * 0.001)
    risk_budget = max(0.0, equity * config.risk_per_trade)
    risk_qty = risk_budget / stop_distance if stop_distance > 0 else 0.0
    max_notional = max(0.0, equity * config.max_position_notional_pct)
    cap_qty = max_notional / entry if entry > 0 else 0.0
    qty = max(0.0, min(risk_qty, cap_qty))
    return qty, risk_budget, qty * entry


def _forward_return(candles: list[Candle], entry_index: int, horizon: int = 12) -> float:
    if entry_index >= len(candles):
        return 0.0
    entry = candles[entry_index].open
    end = min(len(candles) - 1, entry_index + horizon)
    if entry <= 0:
        return 0.0
    return candles[end].close / entry - 1.0


def _signal_reason(strategy: str) -> str:
    reasons = {
        "Trend": "Fast trend average crossed above the slow trend average.",
        "Momentum": "Positive lookback momentum aligned with the slow trend filter.",
        "Mean Reversion": "Price reached a statistically stretched downside deviation.",
        "Breakout": "Price closed above the prior breakout window.",
    }
    return reasons.get(strategy, "Strategy signal changed from flat to long.")


def simulate_agent(
    *,
    symbol: str,
    strategy: str,
    candles: list[Candle],
    status: str,
    survival_score: float,
    allocation: float,
    variant: int,
    config: RiskConfig,
) -> dict:
    closes = [c.close for c in candles]
    positions = strategy_positions(closes, strategy, variant)

    equity = allocation
    peak = allocation
    circuit_open = True
    open_position: dict | None = None
    trades: list[dict] = []
    ghosts: list[dict] = []

    for i in range(1, len(candles) - 1):
        signal = positions[i]
        previous_signal = positions[i - 1]
        next_bar = candles[i + 1]

        if open_position is None and signal == 1 and previous_signal == 0:
            reason = None
            if status != "ACTIVE":
                reason = f"Agent status {status}: shadow-only signal."
            elif not circuit_open:
                reason = "Agent drawdown circuit breaker is open."

            atr = _atr_at(candles, i)
            raw_entry = next_bar.open
            entry = _fill_price(raw_entry, "BUY", config.slippage_bps_per_side)
            stop_distance = max(
                atr * config.atr_stop_multiple,
                entry * 0.0025,
            )
            stop = max(0.0, entry - stop_distance)
            target = entry + stop_distance * config.reward_to_risk
            qty, risk_budget, notional = _position_size(equity, entry, stop, config)

            if not math.isfinite(qty) or qty <= 0:
                reason = reason or "Risk engine produced zero position size."

            if reason is not None:
                ghosts.append(
                    {
                        "agent_id": f"{symbol.lower()}-{strategy.lower().replace(' ', '-')}-g{variant}",
                        "asset": symbol,
                        "strategy": strategy,
                        "signal_ts": next_bar.ts,
                        "signal_price": raw_entry,
                        "reason": reason,
                        "forward_12h_return": _forward_return(candles, i + 1),
                        "survival_score": survival_score,
                    }
                )
                continue

            entry_fee = _fee(notional, config.fee_bps_per_side)
            entry_slippage = max(0.0, entry - raw_entry) * qty
            equity -= entry_fee

            open_position = {
                "agent_id": f"{symbol.lower()}-{strategy.lower().replace(' ', '-')}-g{variant}",
                "asset": symbol,
                "strategy": strategy,
                "generation": variant,
                "entry_ts": next_bar.ts,
                "entry_index": i + 1,
                "raw_entry": raw_entry,
                "entry": entry,
                "stop": stop,
                "target": target,
                "qty": qty,
                "risk_budget": risk_budget,
                "notional": notional,
                "entry_fee": entry_fee,
                "entry_slippage": entry_slippage,
                "signal_reason": _signal_reason(strategy),
                "survival_score": survival_score,
            }
            continue

        if open_position is None:
            continue

        stop_hit = next_bar.low <= open_position["stop"]
        target_hit = next_bar.high >= open_position["target"]
        signal_exit = signal == 0 and previous_signal == 1

        if not (stop_hit or target_hit or signal_exit):
            continue

        if stop_hit and target_hit:
            raw_exit = open_position["stop"]
            exit_reason = "STOP_AMBIGUOUS_BAR"
        elif stop_hit:
            raw_exit = open_position["stop"]
            exit_reason = "STOP"
        elif target_hit:
            raw_exit = open_position["target"]
            exit_reason = "TARGET"
        else:
            raw_exit = next_bar.open
            exit_reason = "SIGNAL_EXIT"

        exit_price = _fill_price(raw_exit, "SELL", config.slippage_bps_per_side)
        qty = open_position["qty"]
        gross = (exit_price - open_position["entry"]) * qty
        exit_notional = exit_price * qty
        exit_fee = _fee(exit_notional, config.fee_bps_per_side)
        fees = open_position["entry_fee"] + exit_fee
        exit_slippage = max(0.0, raw_exit - exit_price) * qty
        slippage = open_position["entry_slippage"] + exit_slippage
        pnl = gross - fees

        equity += gross - exit_fee
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak if peak > 0 else 0.0

        risk = max(open_position["risk_budget"], 1e-9)
        trades.append(
            {
                "agent_id": open_position["agent_id"],
                "asset": symbol,
                "strategy": strategy,
                "entry_ts": open_position["entry_ts"],
                "exit_ts": next_bar.ts,
                "entry": open_position["entry"],
                "exit": exit_price,
                "stop": open_position["stop"],
                "target": open_position["target"],
                "qty": qty,
                "notional": open_position["notional"],
                "gross_pnl": gross,
                "fees": fees,
                "slippage_cost": slippage,
                "net_pnl": pnl,
                "r_multiple": pnl / risk,
                "result": "WIN" if pnl > 0 else "LOSS",
                "exit_reason": exit_reason,
                "signal_reason": open_position["signal_reason"],
                "survival_score": survival_score,
                "drawdown_after": drawdown,
            }
        )

        if drawdown >= config.max_agent_drawdown_pct:
            circuit_open = False

        open_position = None

    marked_open = None
    if open_position is not None:
        mark = candles[-1].close
        qty = open_position["qty"]
        est_exit_fee = _fee(mark * qty, config.fee_bps_per_side)
        unrealized = (
            (mark - open_position["entry"]) * qty
            - open_position["entry_fee"]
            - est_exit_fee
        )
        marked_open = {
            **open_position,
            "mark": mark,
            "unrealized_pnl": unrealized,
        }

    gains = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
    losses = abs(sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0))
    pf = gains / losses if losses > 0 else (99.0 if gains > 0 else 0.0)
    wins = sum(1 for t in trades if t["net_pnl"] > 0)

    return {
        "agent_id": f"{symbol.lower()}-{strategy.lower().replace(' ', '-')}-g{variant}",
        "asset": symbol,
        "strategy": strategy,
        "status": status,
        "survival_score": survival_score,
        "allocation": allocation,
        "ending_equity_closed": equity,
        "realized_pnl": sum(t["net_pnl"] for t in trades),
        "unrealized_pnl": marked_open["unrealized_pnl"] if marked_open else 0.0,
        "trades": trades,
        "ghosts": ghosts,
        "trade_count": len(trades),
        "win_rate": wins / len(trades) if trades else 0.0,
        "profit_factor": pf,
        "circuit_open": circuit_open,
        "open_position": marked_open,
        "latest_signal": "LONG" if positions[-1] else "FLAT",
    }


def _portfolio_drawdown(trades: list[dict], starting_equity: float) -> float:
    equity = starting_equity
    peak = starting_equity
    worst = 0.0
    for trade in sorted(trades, key=lambda x: x["exit_ts"]):
        equity += trade["net_pnl"]
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, 1.0 - equity / peak)
    return worst


def build_agent_city(config: RiskConfig | None = None) -> dict:
    config = config or RiskConfig()
    candles_by_symbol = {
        symbol: fetch_ohlc(pair)
        for symbol, pair in ASSETS.items()
    }

    markets = [
        market_snapshot(symbol, candles)
        for symbol, candles in candles_by_symbol.items()
    ]

    strategies = ("Trend", "Momentum", "Mean Reversion", "Breakout")
    evaluated: list[dict] = []
    for symbol, candles in candles_by_symbol.items():
        for idx, strategy in enumerate(strategies):
            evaluated.append(
                evaluate_agent(
                    symbol,
                    strategy,
                    candles,
                    variant=idx % 2,
                )
            )

    active_count = sum(1 for agent in evaluated if agent["status"] == "ACTIVE")
    allocation = config.starting_equity / max(1, active_count)

    agent_results: list[dict] = []
    all_trades: list[dict] = []
    all_ghosts: list[dict] = []
    open_positions: list[dict] = []

    for agent in evaluated:
        result = simulate_agent(
            symbol=agent["asset"],
            strategy=agent["strategy"],
            candles=candles_by_symbol[agent["asset"]],
            status=agent["status"],
            survival_score=agent["survival_score"],
            allocation=allocation if agent["status"] == "ACTIVE" else 0.0,
            variant=agent["generation"],
            config=config,
        )
        result["research"] = {
            "total_return": agent["total_return"],
            "oos_return": agent["oos_return"],
            "max_drawdown": agent["max_drawdown"],
            "sharpe": agent["sharpe"],
            "stress_passes": agent["stress_passes"],
        }
        agent_results.append(result)
        all_trades.extend(result["trades"])
        all_ghosts.extend(result["ghosts"])
        if result["open_position"] is not None:
            open_positions.append(result["open_position"])

    all_trades.sort(key=lambda x: x["exit_ts"], reverse=True)
    all_ghosts.sort(key=lambda x: x["signal_ts"], reverse=True)

    realized = sum(t["net_pnl"] for t in all_trades)
    unrealized = sum(p["unrealized_pnl"] for p in open_positions)
    total_fees = sum(t["fees"] for t in all_trades)
    total_slippage = sum(t["slippage_cost"] for t in all_trades)
    gains = sum(t["net_pnl"] for t in all_trades if t["net_pnl"] > 0)
    losses = abs(sum(t["net_pnl"] for t in all_trades if t["net_pnl"] < 0))
    wins = sum(1 for t in all_trades if t["net_pnl"] > 0)
    profit_factor = gains / losses if losses > 0 else (99.0 if gains > 0 else 0.0)

    return {
        "ok": True,
        "engine": "AEGIS Agent City v1",
        "mode": "LIVE_DATA_PAPER_RECONSTRUCTION",
        "source": "Kraken public OHLC · 1h candles",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "capital_firewall": "LOCKED",
        "live_execution_enabled": False,
        "paper_execution": {
            "persistent_broker_session": False,
            "description": (
                "Deterministic paper reconstruction from live market candles. "
                "Signals are generated on a closed bar and filled on the next bar "
                "with explicit fees and slippage. No real orders are sent."
            ),
        },
        "markets": markets,
        "vault": {
            "starting_equity": config.starting_equity,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "net_pnl": realized + unrealized,
            "marked_equity": config.starting_equity + realized + unrealized,
            "fees": total_fees,
            "slippage_cost": total_slippage,
            "max_drawdown": _portfolio_drawdown(all_trades, config.starting_equity),
            "profit_factor": profit_factor,
            "win_rate": wins / len(all_trades) if all_trades else 0.0,
            "closed_trades": len(all_trades),
            "open_positions": len(open_positions),
            "active_agents": active_count,
        },
        "risk": config.to_dict(),
        "agents": sorted(
            agent_results,
            key=lambda x: (
                x["status"] == "ACTIVE",
                x["survival_score"],
                x["realized_pnl"],
            ),
            reverse=True,
        ),
        "trades": all_trades[:30],
        "ghost_trades": all_ghosts[:30],
        "open_positions": open_positions,
        "next_stage": {
            "name": "Persistent Paper Broker",
            "requires": "Durable storage for positions, fills, equity and audit events.",
            "promotion_rule": (
                "Only promote a strategy after sufficient paper days/trades, "
                "positive out-of-sample evidence, cost stress survival and "
                "drawdown limits."
            ),
        },
    }
