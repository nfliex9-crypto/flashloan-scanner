import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from funded_trader.rules import AccountState, RuleProfile, Contract, size_position, D

t0 = datetime(2026, 1, 5, 23, tzinfo=timezone.utc)
def rule(**overrides):
    kw = dict(name="test", initial_balance=D(50000), max_loss=D(2000),
              profit_target=D(3000), mode="eod_trailing", daily_loss_limit=D(1200))
    kw.update(overrides)
    return RuleProfile(**kw)

class RiskTests(unittest.TestCase):
    def test_initial_state(self):
        a = AccountState(rule())
        self.assertEqual(a.floor, D(48000))
        self.assertEqual(a.cushion, D(2000))

    def test_eod_high_moves_next_session_not_intraday(self):
        a = AccountState(rule())
        a.close_trade(t0, 1500)
        self.assertEqual(a.floor, D(48000))
        a.start_event(t0 + timedelta(days=1))
        self.assertEqual(a.floor, D(49500))

    def test_eod_cap_at_initial(self):
        a = AccountState(rule())
        a.close_trade(t0, 4000)
        a.start_event(t0 + timedelta(days=1))
        self.assertEqual(a.floor, D(50000))

    def test_static_floor(self):
        a = AccountState(rule(mode="static"))
        a.close_trade(t0, 4000)
        a.start_event(t0 + timedelta(days=1))
        self.assertEqual(a.floor, D(48000))

    def test_intraday_drawdown_tracks_floating_peak(self):
        a = AccountState(rule(mode="intraday_trailing", daily_loss_limit=None,
                               lock_floor_at_initial=False))
        a.observe_equity(t0, 500)
        self.assertEqual(a.floor, D(48500))
        a.observe_equity(t0 + timedelta(minutes=1), -1600)
        self.assertTrue(a.breached)

    def test_daily_loss(self):
        a = AccountState(rule())
        a.close_trade(t0, -1200)
        self.assertTrue(a.breached)

    def test_consistency(self):
        a = AccountState(rule(consistency_fraction=D("0.4"), daily_loss_limit=None))
        a.close_trade(t0, 2000)
        a.close_trade(t0 + timedelta(days=1), 1000)
        self.assertFalse(a.eligible)
        self.assertEqual(a.consistency_ratio, D(2)/D(3))
        for i in range(2, 6):
            a.close_trade(t0 + timedelta(days=i), 600)
        self.assertTrue(a.eligible)

    def test_sizing_and_fee(self):
        a = AccountState(rule())
        a.observe_equity(t0, 0)
        c = Contract("MES", D("0.25"), D("1.25"), D("2.5"))
        d = size_position(a, c, stop_distance=D("5"), risk_budget=D("100"), slippage_ticks=2)
        self.assertTrue(d.approved)
        self.assertEqual(d.quantity, 3)
        self.assertEqual(d.maximum_loss, D("90"))

    def test_zero_budget_and_no_session(self):
        a = AccountState(rule())
        c = Contract("MES", D(".25"), D("1.25"), D("2"))
        self.assertEqual(size_position(a, c, D("5"), D(75)).reason, "NO_SESSION_SNAPSHOT")
        a.observe_equity(t0, 0)
        self.assertEqual(size_position(a, c, D("5"), D(0)).reason, "INVALID_RISK_INPUT")

    def test_timezone_required(self):
        a = AccountState(rule())
        with self.assertRaises(ValueError):
            a.observe_equity(datetime(2026, 1, 5), 0)
