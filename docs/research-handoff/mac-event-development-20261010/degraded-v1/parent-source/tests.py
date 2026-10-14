"""Prepared tests only; not run while execution is blocked.

13 deterministic method/reference invocations, maximum. Test failures and
passes must both be retained on a subsequently authorized execution path.
"""
import unittest
from fractions import Fraction as F
import methods


def obs(i, t=0, **overrides):
    value = dict(id=i, acquisition=i, asset="A", target="motion", value="RUN",
                 source_time=t, confirmed_time=t, quality="GOOD", alarm=True,
                 presence=True, task="J", relationship="VALID", recovery=False)
    value.update(overrides)
    return value


class ContractTests(unittest.TestCase):
    def test_normalized_conflict_numeric_reference(self):
        result = methods.fuse([{"RUN": F(4, 5), "STOP": F(0), "U": F(1, 5)},
                               {"RUN": F(0), "STOP": F(4, 5), "U": F(1, 5)}], True)
        self.assertEqual(result, {"RUN": F(4, 9), "STOP": F(4, 9),
                                  "U": F(1, 9), "EMPTY": F(0), "conflict": F(16, 25)})

    def test_unnormalized_conflict_retained(self):
        result = methods.fuse([{"RUN": F(4, 5), "STOP": F(0), "U": F(1, 5)},
                               {"RUN": F(0), "STOP": F(4, 5), "U": F(1, 5)}], False)
        self.assertEqual(result["EMPTY"], F(16, 25))

    def test_total_conflict_rejects_normalization(self):
        self.assertIsNone(methods.fuse([{"RUN": F(1), "STOP": F(0), "U": F(0)},
                                      {"RUN": F(0), "STOP": F(1), "U": F(0)}], True))

    def test_single_support_is_not_accident_probability(self):
        self.assertEqual(methods.fuse([{"RUN": F(4, 5), "STOP": F(0), "U": F(1, 5)}], True)["U"], F(1, 5))

    def test_repeated_acquisition_not_independent(self):
        a = obs("a")
        b = obs("b", acquisition="a")
        self.assertEqual(len(methods.latest_evidence([a, b], 0)), 1)

    def test_old_source_with_recent_confirmation_is_usable(self):
        self.assertEqual(len(methods.latest_evidence([obs("a", confirmed_time=4)], 4)), 1)

    def test_bad_quality_not_usable(self):
        self.assertEqual(methods.latest_evidence([obs("a", quality="BAD")], 0), [])

    def test_missing_relationship_keeps_cards_separate(self):
        cards, _ = methods.rule_cards([obs("a", relationship="MISSING"), obs("b", relationship="MISSING")])
        self.assertNotEqual(cards["a"], cards["b"])

    def test_confirmed_recovery_separates_recurrence(self):
        cards, _ = methods.rule_cards([obs("a"), obs("clear", 1, alarm=False, recovery=True, presence=False), obs("b", 2)])
        self.assertNotEqual(cards["a"], cards["b"])

    def test_stale_recovery_does_not_split_newer_alarm(self):
        cards, _ = methods.rule_cards([obs("a", 2), obs("clear", 1, confirmed_time=2, alarm=False, recovery=True), obs("b", 3)])
        self.assertEqual(cards["a"], cards["b"])

    def test_window_uses_arrival_order_is_weak_counterexample(self):
        cards = methods.window_cards([obs("a"), obs("b", 1)], 2)
        self.assertEqual(cards["a"], cards["b"])

    def test_waiting_never_increases_physical_risk(self):
        result = methods.assess([obs("a"), obs("wait1", 1, target="heartbeat", alarm=False, presence=True),
                                 obs("wait2", 2, target="heartbeat", alarm=False, presence=True)], "M1")
        self.assertNotEqual(result["risk"], "SAFE")
        self.assertEqual(result["priority"], "FOLLOW_UP")

    def test_current_danger_evidence_can_upgrade_risk(self):
        self.assertEqual(methods.assess([obs("a", danger_level="HIGH")], "M1")["risk"], "EXPOSURE_HIGH")


if __name__ == "__main__":
    unittest.main()
