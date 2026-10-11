"""Tests for the synthetic policy comparison input and its evidence accounting."""

from __future__ import annotations

import unittest

from rfb.research import alert_action_experiment_scenarios as scenarios
from rfb.research.alert_action_experiment_scenarios import build_comparison


class ReminderActionScenarioTests(unittest.TestCase):
    def test_same_action_stream_runs_through_both_policies_and_retains_revisions(self):
        result = build_comparison()
        intents = result["input"]["action_intents"]
        expected_ids = {row["intent_id"] for row in intents}
        expected_evidence = {
            ref for row in intents for ref in row["evidence_refs"]
        }
        retained_fields = (
            "association_ids",
            "observation_ids",
            "source_ids",
            "candidate_episode_ids",
        )

        for window_result in result["window_results"]:
            with self.subTest(window=window_result["window_seconds"]):
                for policy_name in ("per_association", "card_coalesce"):
                    policy_result = window_result[policy_name]
                    actual_ids = {
                        row["intent_id"] for row in policy_result["card_revisions"]
                    }
                    actual_evidence = {
                        ref
                        for row in policy_result["card_revisions"]
                        for ref in row["evidence_refs"]
                    }
                    self.assertEqual(actual_ids, expected_ids)
                    self.assertEqual(actual_evidence, expected_evidence)
                    for field in retained_fields:
                        self.assertEqual(
                            {value for row in policy_result["card_revisions"] for value in row[field]},
                            {value for row in intents for value in row[field]},
                        )
                    self.assertEqual(
                        policy_result["semantic_card_revision_count"], len(expected_ids)
                    )
                    self.assertEqual(policy_result["missed_important_update_ids"], [])
                    self.assertIsNone(policy_result["actual_visible_at"])
                    self.assertTrue(
                        all(
                            row["delivery_status"] == "NOT_DELIVERED"
                            and row["actual_visible_at"] is None
                            for row in policy_result["notifications"]
                        )
                    )

        self.assertEqual([row["window_seconds"] for row in result["window_results"]], [0, 5])
        self.assertLess(
            result["window_results"][1]["card_coalesce"]["notification_action_count"],
            result["window_results"][1]["per_association"]["notification_action_count"],
        )

    def test_forced_scenarios_are_explicit_and_stale_replay_is_rejected(self):
        result = build_comparison()
        cases = result["forced_cases"]

        for name in (
            "exact_replay",
            "stale_replay",
            "complementary_sources",
            "risk_escalation",
            "counterevidence",
            "association_split",
            "distinct_event",
            "cross_window",
            "out_of_order_source_time",
        ):
            self.assertIn(name, cases)

        self.assertEqual(cases["exact_replay"]["status"], "DUPLICATE_REPLAY_IGNORED")
        self.assertEqual(cases["stale_replay"]["status"], "REJECTED_CONTENT_CONFLICT")
        for window_result in result["window_results"]:
            for policy_name in ("per_association", "card_coalesce"):
                policy = window_result[policy_name]
                self.assertEqual(
                    policy["exact_replay"]["revision_count_before"],
                    policy["exact_replay"]["revision_count_after"],
                )
                self.assertEqual(
                    policy["stale_replay"]["revision_count_before"],
                    policy["stale_replay"]["revision_count_after"],
                )
        candidate_5s = result["window_results"][1]["card_coalesce"]
        self.assertEqual(
            sorted(candidate_5s["simulated_coalesced_update_ages_seconds"]), [0, 5]
        )
        outside_id = cases["out_of_order_source_time"]["processing_order_intent_ids"][1]
        outside_decision = next(
            row for row in candidate_5s["decisions"] if row["intent_id"] == outside_id
        )
        self.assertEqual(outside_decision["status"], "EMITTED")
        self.assertEqual(
            outside_decision["decision_reason"],
            "NO_SAME_CARD_KIND_STAGE_BATCH_WITHIN_WINDOW",
        )
        self.assertEqual(cases["cross_window"]["boundary_seconds"], 5)
        self.assertLess(
            cases["out_of_order_source_time"]["processing_order_source_times"][1],
            cases["out_of_order_source_time"]["processing_order_source_times"][0],
        )
        actions_by_id = {
            row["intent_id"]: row for row in result["input"]["action_intents"]
        }
        out_of_order_ids = cases["out_of_order_source_time"][
            "processing_order_intent_ids"
        ]
        self.assertGreater(
            actions_by_id[out_of_order_ids[0]]["source_times"][-1],
            actions_by_id[out_of_order_ids[1]]["source_times"][-1],
        )
        self.assertFalse(result["execution_boundary"]["old_1464_trial_rerun"])
        self.assertEqual(
            result["execution_boundary"]["actual_delivery_or_visibility"], "UNKNOWN_NOT_RUN"
        )

    def test_historical_failed_baseline_is_carried_forward_without_reconstruction(self):
        result = build_comparison()
        baseline = result["historical_baseline"]

        self.assertEqual(baseline["checks_executed"], 1464)
        self.assertEqual(baseline["round_status"], "FAILED")
        self.assertEqual(baseline["method_records"], 20)
        self.assertFalse(baseline["method_records_are_independent_samples"])
        self.assertFalse(baseline["rerun_this_time"])
        self.assertEqual(baseline["legacy_metric_status"], "NOT_RECONSTRUCTED")

    def test_html_rendering_is_standalone_and_labels_unknown_delivery(self):
        self.assertTrue(callable(getattr(scenarios, "render_html", None)))
        rendered = scenarios.render_html(build_comparison())

        self.assertTrue(rendered.lstrip().lower().startswith("<!doctype html>"))
        self.assertIn("NOT_DELIVERED", rendered)
        self.assertIn("1464", rendered)
        self.assertIn("CARD_COALESCE", rendered)
        self.assertIn("SAME_CARD_KIND_STAGE_BATCH_WITHIN_WINDOW", rendered)
        self.assertNotIn("https://", rendered)


if __name__ == "__main__":
    unittest.main()
