from __future__ import annotations

import numpy as np

from .gates import capital_firewall, evaluate
from .ledger import seal_evidence
from .models import StrategyEvidence
from .redteam import attack


def main() -> None:
    rng = np.random.default_rng(42)

    # Synthetic return stream only. No market connection and no orders.
    returns = rng.normal(0.00045, 0.006, 700)
    stress = attack(returns)

    evidence = StrategyEvidence(
        strategy_id="SYNTHETIC-DEMO-001",
        total_trades=420,
        net_return=0.24,
        oos_return=0.08,
        sharpe=1.42,
        max_drawdown=0.075,
        profit_factor=1.34,
        deflated_sharpe_confidence=0.97,
        pbo=0.14,
        cost_survival_multiple=2.4,
        parameter_stability=0.78,
        regime_pass_rate=0.76,
        paper_days=35,
        paper_return=0.021,
        live_drift_z=0.8,
        ruin_probability=0.006,
    )

    verdict = evaluate(evidence)
    receipt = seal_evidence(evidence)

    print("AEGIS ZERO-TRUST REPORT")
    print("=" * 54)
    print(f"Strategy:       {evidence.strategy_id}")
    print(f"Survival score: {verdict.score}/100")
    print(f"Promotion:      {verdict.level.value}")
    print(f"Capital policy: {capital_firewall(verdict) * 100:.3f}% max canary")
    print(f"Evidence hash:  {receipt.evidence_hash[:20]}...")
    print("\nHard gates:")
    for gate in verdict.gates:
        mark = "PASS" if gate.passed else "FAIL"
        print(f"  {mark:4}  {gate.name:22} actual={gate.actual} target={gate.threshold}")

    print("\nRed-team worlds:")
    for item in stress:
        mark = "SURVIVE" if item.survived else "KILLED"
        print(
            f"  {mark:7} {item.scenario:18} "
            f"return={item.compounded_return:+.2%} dd={item.max_drawdown:.2%}"
        )


if __name__ == "__main__":
    main()
