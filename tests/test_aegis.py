import numpy as np

from aegis.gates import capital_firewall, evaluate
from aegis.ledger import seal_evidence
from aegis.market_forge import StressScenario, forge_returns
from aegis.models import PromotionLevel, StrategyEvidence
from aegis.survival import survival_score


def strong_evidence(**overrides):
    data = dict(
        strategy_id="TEST-001",
        total_trades=300,
        net_return=0.20,
        oos_return=0.07,
        sharpe=1.5,
        max_drawdown=0.07,
        profit_factor=1.4,
        deflated_sharpe_confidence=0.97,
        pbo=0.12,
        cost_survival_multiple=2.5,
        parameter_stability=0.8,
        regime_pass_rate=0.8,
        paper_days=35,
        paper_return=0.02,
        live_drift_z=0.5,
        ruin_probability=0.005,
    )
    data.update(overrides)
    return StrategyEvidence(**data)


def test_strong_strategy_can_reach_canary_eligibility():
    verdict = evaluate(strong_evidence())
    assert verdict.level is PromotionLevel.CANARY_ELIGIBLE
    assert verdict.passed_all
    assert capital_firewall(verdict) >= 0


def test_one_hard_failure_blocks_capital():
    verdict = evaluate(strong_evidence(max_drawdown=0.25))
    assert verdict.level is PromotionLevel.REJECTED
    assert capital_firewall(verdict) == 0.0


def test_evidence_hash_changes_when_evidence_changes():
    a = seal_evidence(strong_evidence()).evidence_hash
    b = seal_evidence(strong_evidence(pbo=0.13)).evidence_hash
    assert a != b


def test_survival_score_is_bounded():
    score = survival_score(strong_evidence())
    assert 0 <= score <= 100


def test_market_forge_is_deterministic():
    r = np.array([0.01, -0.01, 0.005, 0.003] * 20)
    s = StressScenario("shock", shock_probability=0.2, shock_size=-0.03)
    a = forge_returns(r, s, seed=9)
    b = forge_returns(r, s, seed=9)
    assert np.array_equal(a, b)
