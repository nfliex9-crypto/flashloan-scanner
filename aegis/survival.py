from __future__ import annotations

from .models import StrategyEvidence


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def survival_score(e: StrategyEvidence) -> float:
    """0-100 robustness score. Return is intentionally a minor component."""
    dd = _clamp(1.0 - e.max_drawdown / 0.20)
    pbo = _clamp(1.0 - e.pbo)
    dsr = _clamp(e.deflated_sharpe_confidence)
    cost = _clamp(e.cost_survival_multiple / 3.0)
    params = _clamp(e.parameter_stability)
    regimes = _clamp(e.regime_pass_rate)
    ruin = _clamp(1.0 - e.ruin_probability / 0.05)
    oos = _clamp((e.oos_return + 0.10) / 0.30)
    pf = _clamp((e.profit_factor - 1.0) / 1.0)

    weighted = (
        0.18 * dd
        + 0.16 * pbo
        + 0.14 * dsr
        + 0.12 * cost
        + 0.12 * params
        + 0.12 * regimes
        + 0.10 * ruin
        + 0.03 * oos
        + 0.03 * pf
    )
    return round(weighted * 100.0, 2)
