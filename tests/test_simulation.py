import unittest
from funded_trader.rules import D, RuleProfile
from funded_trader.simulation import bootstrap

class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.rules = RuleProfile("test", D(50000), D(2000), D(3000),
                                 mode="static", daily_loss_limit=None)
    def test_seed_reproducibility(self):
        a = bootstrap([D(-300), D(200), D(500)], self.rules, trials=100, seed=8)
        b = bootstrap([D(-300), D(200), D(500)], self.rules, trials=100, seed=8)
        self.assertEqual(a, b)
        self.assertEqual(a.trials, a.passed+a.failed+a.unfinished)
    def test_all_losses_fail(self):
        s = bootstrap([D(-1000)], self.rules, trials=10, max_trades=10)
        self.assertEqual(s.failed, 10)
    def test_all_wins_pass(self):
        s = bootstrap([D(1000)], self.rules, trials=10, max_trades=10)
        self.assertEqual(s.passed, 10)
    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            bootstrap([], self.rules)
