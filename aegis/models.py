from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


class PromotionLevel(str, Enum):
    REJECTED = "REJECTED"
    RESEARCH = "RESEARCH"
    SHADOW = "SHADOW"
    CANARY_ELIGIBLE = "CANARY_ELIGIBLE"


@dataclass(frozen=True)
class StrategyEvidence:
    strategy_id: str
    total_trades: int
    net_return: float
    oos_return: float
    sharpe: float
    max_drawdown: float
    profit_factor: float
    deflated_sharpe_confidence: float
    pbo: float
    cost_survival_multiple: float
    parameter_stability: float
    regime_pass_rate: float
    paper_days: int = 0
    paper_return: float = 0.0
    live_drift_z: float = 0.0
    ruin_probability: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)
