from __future__ import annotations

import json
import math
import statistics
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone

from .execution import book_microstructure, fetch_order_book


KRAKEN_URL = "https://api.kraken.com/0/public/OHLC"
COST_PER_POSITION_CHANGE = 0.0006  # 6 bps research assumption per position change.


@dataclass(frozen=True)
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


ASSETS = {
    "BTC": "XBTUSD",
    "ETH": "ETHUSD",
}

TIMEFRAMES = {
    "15m": 15,
    "1h": 60,
    "4h": 240,
}

STRATEGIES = ("Trend", "Momentum", "Mean Reversion", "Breakout")


def fetch_ohlc(pair: str, interval: int = 60, *, closed_only: bool = True) -> list[Candle]:
    query = urllib.parse.urlencode({"pair": pair, "interval": interval, "assetVersion": 1})
    request = urllib.request.Request(
        f"{KRAKEN_URL}?{query}",
        headers={"User-Agent": "AEGIS-Research-Lab/2.0"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if payload.get("error"):
        raise RuntimeError(f"Kraken error: {payload['error']}")

    result = payload["result"]
    key = next(k for k in result if k != "last")
    rows = result[key]

    candles = [
        Candle(
            ts=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[6]),
        )
        for row in rows
    ]
    # Kraken documents the final row as the current, not-yet-committed candle.
    # Drop it so research and paper decisions cannot repaint on an unfinished bar.
    if closed_only and len(candles) > 1:
        candles = candles[:-1]

    if len(candles) < 120:
        raise RuntimeError("Not enough closed OHLC history returned by Kraken.")
    return candles


def sma(values: list[float], end: int, length: int) -> float | None:
    if end + 1 < length:
        return None
    window = values[end - length + 1 : end + 1]
    return sum(window) / length


def stddev(values: list[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def strategy_positions(
    closes: list[float],
    strategy: str,
    variant: int = 0,
) -> list[int]:
    n = len(closes)
    pos = [0] * n

    if strategy == "Trend":
        fast = 18 + variant * 2
        slow = 55 + variant * 3
        for i in range(n):
            f = sma(closes, i, fast)
            s = sma(closes, i, slow)
            if f is not None and s is not None:
                pos[i] = 1 if f > s else 0

    elif strategy == "Momentum":
        lookback = 18 + variant * 4
        slow = 60
        for i in range(n):
            m = sma(closes, i, slow)
            if i >= lookback and m is not None:
                ret = closes[i] / closes[i - lookback] - 1.0
                pos[i] = 1 if ret > 0 and closes[i] > m else 0

    elif strategy == "Mean Reversion":
        lookback = 20 + variant * 2
        current = 0
        for i in range(n):
            if i + 1 < lookback:
                continue
            window = closes[i - lookback + 1 : i + 1]
            mean = sum(window) / lookback
            sd = stddev(window)
            z = (closes[i] - mean) / sd if sd > 0 else 0.0
            if z < -1.15:
                current = 1
            elif z > -0.05:
                current = 0
            pos[i] = current

    elif strategy == "Breakout":
        entry = 24 + variant * 4
        exit_len = 10 + variant * 2
        current = 0
        for i in range(n):
            if i >= entry:
                previous = closes[i - entry : i]
                if closes[i] > max(previous):
                    current = 1
            if i >= exit_len and current:
                previous_exit = closes[i - exit_len : i]
                if closes[i] < min(previous_exit):
                    current = 0
            pos[i] = current

    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    return pos


def strategy_returns(
    closes: list[float],
    positions: list[int],
    *,
    cost_per_change: float = COST_PER_POSITION_CHANGE,
) -> list[float]:
    if len(closes) != len(positions):
        raise ValueError("closes and positions length mismatch")

    out = [0.0]
    previous_position = 0
    for i in range(1, len(closes)):
        held = positions[i - 1]
        market_return = closes[i] / closes[i - 1] - 1.0
        turnover = abs(held - previous_position)
        out.append(held * market_return - turnover * cost_per_change)
        previous_position = held
    return out


def compounded_return(returns: list[float]) -> float:
    equity = 1.0
    for value in returns:
        equity *= 1.0 + value
    return equity - 1.0


def max_drawdown(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, 1.0 - equity / peak)
    return worst


def annualized_sharpe(returns: list[float], interval_minutes: int = 60) -> float:
    if len(returns) < 3:
        return 0.0
    mean = statistics.fmean(returns)
    sd = statistics.pstdev(returns)
    if sd == 0:
        return 0.0
    bars_per_year = (60.0 / interval_minutes) * 24.0 * 365.0
    return mean / sd * math.sqrt(bars_per_year)


def profit_factor(returns: list[float]) -> float:
    gains = sum(x for x in returns if x > 0)
    losses = abs(sum(x for x in returns if x < 0))
    if losses == 0:
        return 99.0 if gains > 0 else 0.0
    return gains / losses


def trade_count(positions: list[int]) -> int:
    count = 0
    prev = 0
    for value in positions:
        if value == 1 and prev == 0:
            count += 1
        prev = value
    return count


def win_rate(returns: list[float]) -> float:
    active = [x for x in returns if abs(x) > 1e-12]
    if not active:
        return 0.0
    return sum(1 for x in active if x > 0) / len(active)


def market_snapshot(symbol: str, candles: list[Candle], interval_minutes: int = 60) -> dict:
    closes = [c.close for c in candles]
    price = closes[-1]
    bars_24h = max(1, int(24 * 60 / interval_minutes))
    bars_7d = max(1, int(7 * 24 * 60 / interval_minutes))
    ret24 = (
        price / closes[-1 - bars_24h] - 1
        if len(closes) > bars_24h
        else 0.0
    )
    ret7d = (
        price / closes[-1 - bars_7d] - 1
        if len(closes) > bars_7d
        else 0.0
    )

    bar_returns = [
        closes[i] / closes[i - 1] - 1.0
        for i in range(1, len(closes))
    ]
    recent_count = min(len(bar_returns), bars_7d)
    recent = bar_returns[-recent_count:]
    bars_per_year = (60.0 / interval_minutes) * 24.0 * 365.0
    vol = stddev(recent) * math.sqrt(bars_per_year)

    ma50 = sum(closes[-50:]) / 50
    ma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else ma50
    if price > ma50 > ma200:
        regime = "BULL"
    elif price < ma50 < ma200:
        regime = "BEAR"
    else:
        regime = "MIXED"

    return {
        "symbol": symbol,
        "price": price,
        "change_24h": ret24,
        "change_7d": ret7d,
        "annualized_volatility": vol,
        "regime": regime,
        "last_candle_utc": datetime.fromtimestamp(
            candles[-1].ts, tz=timezone.utc
        ).isoformat(),
        "bars": len(candles),
    }


def evaluate_agent(
    symbol: str,
    strategy: str,
    candles: list[Candle],
    *,
    variant: int = 0,
    interval_minutes: int = 60,
) -> dict:
    closes = [c.close for c in candles]
    positions = strategy_positions(closes, strategy, variant)
    returns = strategy_returns(closes, positions)

    split = max(80, int(len(closes) * 0.70))
    oos_closes = closes[split - 1 :]
    oos_positions = strategy_positions(oos_closes, strategy, variant)
    oos_returns = strategy_returns(oos_closes, oos_positions)

    returns_2x = strategy_returns(
        closes, positions, cost_per_change=COST_PER_POSITION_CHANGE * 2
    )
    returns_3x = strategy_returns(
        closes, positions, cost_per_change=COST_PER_POSITION_CHANGE * 3
    )

    total = compounded_return(returns)
    oos = compounded_return(oos_returns)
    dd = max_drawdown(returns)
    pf = profit_factor(returns)
    sharpe = annualized_sharpe(returns, interval_minutes)
    trades = trade_count(positions)

    stress = {
        "baseline_positive": total > 0,
        "oos_positive": oos > 0,
        "cost_2x_positive": compounded_return(returns_2x) > 0,
        "cost_3x_positive": compounded_return(returns_3x) > 0,
    }
    stress_passes = sum(1 for x in stress.values() if x)

    score = 100.0
    score -= min(45.0, dd * 280.0)
    if oos <= 0:
        score -= 18.0
    if pf < 1.15:
        score -= min(20.0, (1.15 - pf) * 35.0)
    if sharpe < 0.5:
        score -= 10.0
    score -= (4 - stress_passes) * 6.0
    if trades < 4:
        score -= 8.0
    score = round(max(0.0, min(100.0, score)), 2)

    if dd > 0.15 or pf < 0.75:
        status = "ELIMINATED"
    elif score >= 68 and oos > 0 and stress["cost_2x_positive"]:
        status = "ACTIVE"
    else:
        status = "PROBATION"

    return {
        "agent_id": f"{symbol.lower()}-{strategy.lower().replace(' ', '-')}-g{variant}",
        "asset": symbol,
        "strategy": strategy,
        "generation": variant,
        "status": status,
        "survival_score": score,
        "total_return": total,
        "oos_return": oos,
        "max_drawdown": dd,
        "profit_factor": pf,
        "sharpe": sharpe,
        "trades": trades,
        "win_rate": win_rate(returns),
        "latest_signal": "LONG" if positions[-1] else "FLAT",
        "stress": stress,
        "stress_passes": stress_passes,
        "cost_assumption_bps": COST_PER_POSITION_CHANGE * 10000,
        "interval_minutes": interval_minutes,
    }




def fetch_microstructure_matrix() -> dict[str, dict]:
    output: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(ASSETS)) as pool:
        futures = {
            pool.submit(fetch_order_book, pair, 100): symbol
            for symbol, pair in ASSETS.items()
        }
        for future in as_completed(futures):
            symbol = futures[future]
            output[symbol] = book_microstructure(
                future.result(),
                notional_quote=10_000.0,
            )
    return output


def fetch_market_matrix() -> dict[tuple[str, str], list[Candle]]:
    """Fetch every asset/timeframe concurrently instead of serial REST calls."""
    output: dict[tuple[str, str], list[Candle]] = {}
    tasks = {}

    with ThreadPoolExecutor(max_workers=6) as pool:
        for symbol, pair in ASSETS.items():
            for tf_name, interval in TIMEFRAMES.items():
                future = pool.submit(
                    fetch_ohlc,
                    pair,
                    interval,
                    closed_only=True,
                )
                tasks[future] = (symbol, tf_name)

        for future in as_completed(tasks):
            output[tasks[future]] = future.result()

    return output


def merge_timeframe_evidence(
    symbol: str,
    strategy: str,
    variant: int,
    matrix: dict[tuple[str, str], list[Candle]],
) -> dict:
    evidence = {
        tf_name: evaluate_agent(
            symbol,
            strategy,
            matrix[(symbol, tf_name)],
            variant=variant,
            interval_minutes=interval,
        )
        for tf_name, interval in TIMEFRAMES.items()
    }

    primary = dict(evidence["1h"])

    confirmations = sum(
        1
        for result in evidence.values()
        if (
            result["total_return"] > 0
            and result["oos_return"] > 0
            and result["stress"]["cost_2x_positive"]
        )
    )

    score = round(
        0.25 * evidence["15m"]["survival_score"]
        + 0.50 * evidence["1h"]["survival_score"]
        + 0.25 * evidence["4h"]["survival_score"],
        2,
    )

    hard_failure = any(
        result["max_drawdown"] > 0.20
        for result in evidence.values()
    )

    if hard_failure or score < 35:
        status = "ELIMINATED"
    elif (
        score >= 68
        and confirmations >= 2
        and primary["oos_return"] > 0
        and primary["stress"]["cost_2x_positive"]
    ):
        status = "ACTIVE"
    else:
        status = "PROBATION"

    primary["status"] = status
    primary["survival_score"] = score
    primary["timeframe_confirmations"] = confirmations
    primary["timeframe_total"] = len(TIMEFRAMES)
    primary["timeframe_evidence"] = {
        name: {
            "return": result["total_return"],
            "oos_return": result["oos_return"],
            "max_drawdown": result["max_drawdown"],
            "profit_factor": result["profit_factor"],
            "sharpe": result["sharpe"],
            "score": result["survival_score"],
            "stress_passes": result["stress_passes"],
        }
        for name, result in evidence.items()
    }
    return primary


def build_live_floor() -> dict:
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        matrix_future = pool.submit(fetch_market_matrix)
        micro_future = pool.submit(fetch_microstructure_matrix)
        matrix = matrix_future.result()
        microstructure = micro_future.result()
    fetched = time.perf_counter()

    markets = []
    for symbol in ASSETS:
        snapshot = market_snapshot(
            symbol,
            matrix[(symbol, "15m")],
            TIMEFRAMES["15m"],
        )
        snapshot["microstructure"] = microstructure.get(symbol, {})
        markets.append(snapshot)

    agents = []
    for symbol in ASSETS:
        for idx, strategy in enumerate(STRATEGIES):
            agents.append(
                merge_timeframe_evidence(
                    symbol,
                    strategy,
                    idx % 2,
                    matrix,
                )
            )

    active = sorted(
        [a for a in agents if a["status"] == "ACTIVE"],
        key=lambda x: x["survival_score"],
        reverse=True,
    )
    probation = sorted(
        [a for a in agents if a["status"] == "PROBATION"],
        key=lambda x: x["survival_score"],
        reverse=True,
    )
    eliminated = sorted(
        [a for a in agents if a["status"] == "ELIMINATED"],
        key=lambda x: x["survival_score"],
        reverse=True,
    )

    replacements = [
        {
            "agent_id": dead["agent_id"].rsplit("-g", 1)[0]
            + f"-g{dead['generation'] + 1}",
            "parent": dead["agent_id"],
            "asset": dead["asset"],
            "strategy": dead["strategy"],
            "generation": dead["generation"] + 1,
            "status": "QUARANTINE",
            "note": "Replacement spawned; fresh multi-timeframe evidence required.",
        }
        for dead in eliminated
    ]

    red_team = sorted(
        agents,
        key=lambda x: (
            x["timeframe_confirmations"],
            x["stress_passes"],
            x["survival_score"],
        ),
    )[:4]

    finished = time.perf_counter()

    return {
        "ok": True,
        "engine": "AEGIS Zero-Trust Quant Lab",
        "mode": "LIVE_MULTI_TIMEFRAME_RESEARCH",
        "source": "Kraken public OHLC · closed candles only",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "capital_firewall": "LOCKED",
        "live_execution_enabled": False,
        "markets": markets,
        "rooms": {
            "strategy": active,
            "probation": probation,
            "red_team": red_team,
            "graveyard": eliminated,
            "replacement": replacements,
        },
        "summary": {
            "agents": len(agents),
            "active": len(active),
            "probation": len(probation),
            "eliminated": len(eliminated),
            "replacements": len(replacements),
        },
        "performance": {
            "fetch_ms": round((fetched - started) * 1000, 1),
            "evaluation_ms": round((finished - fetched) * 1000, 1),
            "total_ms": round((finished - started) * 1000, 1),
            "parallel_market_requests": len(ASSETS) * len(TIMEFRAMES) + len(ASSETS),
        },
        "method": {
            "history": "Kraken rolling windows at 15m / 1h / 4h",
            "timeframes": list(TIMEFRAMES.keys()),
            "closed_candles_only": True,
            "oos_split": "Last 30% of each timeframe",
            "cost_model": "research stress uses 6 bps transitions; forward paper uses live L2 VWAP + configurable Kraken taker fee",
            "strategies": list(STRATEGIES),
            "activation_rule": "Multi-timeframe confirmation + OOS + 2x cost survival",
            "rule": "Risk failures are penalized more heavily than missed return targets.",
        },
    }
