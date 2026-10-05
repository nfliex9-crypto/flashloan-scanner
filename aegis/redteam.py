from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .market_forge import DEFAULT_SCENARIOS, StressScenario, forge_returns


@dataclass(frozen=True)
class StressResult:
    scenario: str
    compounded_return: float
    max_drawdown: float
    survived: bool


def _max_drawdown(returns: np.ndarray) -> float:
    equity = np.cumprod(1.0 + returns)
    peaks = np.maximum.accumulate(equity)
    drawdowns = 1.0 - equity / peaks
    return float(np.max(drawdowns))


def _compounded_return(returns: np.ndarray) -> float:
    return float(np.prod(1.0 + returns) - 1.0)


def attack(
    returns: np.ndarray,
    *,
    scenarios: tuple[StressScenario, ...] = DEFAULT_SCENARIOS,
    max_allowed_drawdown: float = 0.15,
) -> tuple[StressResult, ...]:
    """Try to break a return stream under predefined counterfactual worlds."""
    results = []
    for scenario in scenarios:
        stressed = forge_returns(returns, scenario)
        total = _compounded_return(stressed)
        dd = _max_drawdown(stressed)
        results.append(
            StressResult(
                scenario=scenario.name,
                compounded_return=round(total, 6),
                max_drawdown=round(dd, 6),
                survived=(total > 0 and dd <= max_allowed_drawdown),
            )
        )
    return tuple(results)
