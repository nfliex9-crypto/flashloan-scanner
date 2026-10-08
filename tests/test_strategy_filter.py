"""Costed forward evidence gates are deterministic and have no live execution."""
from aegis.strategy_filter import evaluate_strategy, shadow_entry_allowed


def test_sparse_samples_never_quarantine_or_promote():
    x=evaluate_strategy(trades=2,wins=0,net=-250,profit_factor=0,
                        max_drawdown=.001)
    assert x["state"]=="COLLECTING"
    assert x["allow_new_shadow_entry"]
    assert x["live_execution_enabled"] is False


def test_forward_loser_quarantined_after_twenty_fills():
    x=evaluate_strategy(trades=20,wins=4,net=-1800,profit_factor=.35,
                        max_drawdown=.025)
    assert x["state"]=="QUARANTINED"
    assert not x["allow_new_shadow_entry"]


def test_drawdown_circuit_latched_even_without_many_trades():
    x=evaluate_strategy(trades=3,wins=3,net=100,profit_factor=99,
                        max_drawdown=.052)
    assert x["state"]=="QUARANTINED"


def test_backtest_winner_does_not_get_fake_forward_promotion():
    x=evaluate_strategy(trades=0,wins=0,net=0,profit_factor=0,max_drawdown=0)
    assert x["state"]=="COLLECTING"
    assert x["live_execution_enabled"] is False


def test_evidence_leader_is_rank_only_not_live_authorization():
    x=evaluate_strategy(trades=30,wins=20,net=1000,
                        profit_factor=1.75,max_drawdown=.02)
    assert x["state"]=="LEADING"
    assert x["live_execution_enabled"] is False


class FakeCursor:
    def __init__(self,account,stats):
        self.account=account
        self.stats=stats
        self.calls=0
    def execute(self,*args):self.calls+=1
    def fetchone(self):return self.account if self.calls==1 else self.stats


def test_quarantine_blocks_shadow_entry_after_costed_losses():
    cur=FakeCursor({"max_drawdown":.01},
                   {"trades":25,"net":-600,"gains":200,"losses":1000})
    allowed,reason=shadow_entry_allowed(cur,"btc-trend-g0")
    assert allowed is False
    assert "costed trades" in reason


def test_shadow_circuit_blocks_before_running_pnl_query():
    cur=FakeCursor({"max_drawdown":.051},{})
    allowed,reason=shadow_entry_allowed(cur,"xau-trend-g0")
    assert allowed is False
    assert cur.calls==1
