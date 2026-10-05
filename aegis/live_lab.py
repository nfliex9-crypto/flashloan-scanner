from __future__ import annotations

import json
import math
import statistics
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone


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


def fetch_ohlc(pair: str, interval: int = 60) -> list[Candle]:
    query = urllib.parse.urlencode({"pair": pair, "interval": interval})
    request = urllib.request.Request(
        f"{KRAKEN_URL}?{query}",
        headers={"User-Agent": "AEGIS-Research-Lab/1.0"},
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
    if len(candles) < 120:
        raise RuntimeError("Not enough OHLC history returned by Kraken.")
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


def annualized_sharpe(returns: list[float]) -> float:
    if len(returns) < 3:
        return 0.0
    mean = statistics.fmean(returns)
    sd = statistics.pstdev(returns)
    if sd == 0:
        return 0.0
    return mean / sd * math.sqrt(24 * 365)


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


def market_snapshot(symbol: str, candles: list[Candle]) -> dict:
    closes = [c.close for c in candles]
    price = closes[-1]
    ret24 = price / closes[-25] - 1 if len(closes) >= 25 else 0.0
    ret7d = price / closes[-169] - 1 if len(closes) >= 169 else 0.0

    hourly = [
        closes[i] / closes[i - 1] - 1.0
        for i in range(1, len(closes))
    ]
    recent = hourly[-168:] if len(hourly) >= 168 else hourly
    vol = stddev(recent) * math.sqrt(24 * 365)

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
    sharpe = annualized_sharpe(returns)
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
    }


def build_live_floor() -> dict:
    candles_by_symbol = {
        symbol: fetch_ohlc(pair)
        for symbol, pair in ASSETS.items()
    }

    markets = [
        market_snapshot(symbol, candles)
        for symbol, candles in candles_by_symbol.items()
    ]

    strategies = ("Trend", "Momentum", "Mean Reversion", "Breakout")
    agents = []
    for symbol, candles in candles_by_symbol.items():
        for idx, strategy in enumerate(strategies):
            agents.append(
                evaluate_agent(
                    symbol,
                    strategy,
                    candles,
                    variant=idx % 2,
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

    replacements = []
    for dead in eliminated:
        replacements.append(
            {
                "agent_id": dead["agent_id"].rsplit("-g", 1)[0]
                + f"-g{dead['generation'] + 1}",
                "parent": dead["agent_id"],
                "asset": dead["asset"],
                "strategy": dead["strategy"],
                "generation": dead["generation"] + 1,
                "status": "QUARANTINE",
                "note": "Replacement spawned; must earn fresh evidence before promotion.",
            }
        )

    red_team = sorted(
        agents,
        key=lambda x: (x["stress_passes"], x["survival_score"]),
    )[:4]

    return {
        "ok": True,
        "engine": "AEGIS Zero-Trust Quant Lab",
        "mode": "LIVE_DATA_RESEARCH",
        "source": "Kraken public OHLC · 1h candles",
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
        "method": {
            "history": "Latest hourly OHLC window returned by Kraken",
            "oos_split": "Last 30% of bars",
            "cost_model": "6 bps per position change; stress at 2x and 3x",
            "strategies": list(strategies),
            "rule": "Risk failures are penalized more heavily than missed return targets.",
        },
    }
