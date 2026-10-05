from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class StressScenario:
    name: str
    volatility_multiplier: float = 1.0
    return_shift: float = 0.0
    fee_drag_per_bar: float = 0.0
    shock_probability: float = 0.0
    shock_size: float = 0.0


DEFAULT_SCENARIOS = (
    StressScenario("baseline"),
    StressScenario("vol_x2", volatility_multiplier=2.0),
    StressScenario("fees_x3_proxy", fee_drag_per_bar=0.00015),
    StressScenario("negative_drift", return_shift=-0.00010),
    StressScenario("gap_shocks", shock_probability=0.01, shock_size=-0.03),
    StressScenario(
        "combined_crisis",
        volatility_multiplier=2.5,
        return_shift=-0.00015,
        fee_drag_per_bar=0.00020,
        shock_probability=0.015,
        shock_size=-0.04,
    ),
)


def forge_returns(
    returns: np.ndarray,
    scenario: StressScenario,
    *,
    seed: int = 7,
) -> np.ndarray:
    """Create a deterministic counterfactual return path for robustness testing."""
    r = np.asarray(returns, dtype=float)
    if r.ndim != 1:
        raise ValueError("returns must be a 1D array")
    if len(r) == 0:
        raise ValueError("returns cannot be empty")

    mean = float(np.mean(r))
    stressed = mean + (r - mean) * scenario.volatility_multiplier
    stressed = stressed + scenario.return_shift - scenario.fee_drag_per_bar

    if scenario.shock_probability > 0 and scenario.shock_size != 0:
        rng = np.random.default_rng(seed)
        mask = rng.random(len(stressed)) < scenario.shock_probability
        stressed = stressed.copy()
        stressed[mask] += scenario.shock_size

    return stressed
