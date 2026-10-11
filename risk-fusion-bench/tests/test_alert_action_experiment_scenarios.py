"""Tests for the synthetic policy comparison input and its evidence accounting."""

from __future__ import annotations

import unittest

from rfb.research import alert_action_experiment_scenarios as scenarios
from rfb.research.alert_action_experiment_scenarios import build_comparison


class ReminderActionScenarioTests(unittest.TestCase):
    def test_same_action_stream_runs_through_both_policies_and_retains_revisions(self):
        result = build_comparison()
        intents = result["input"]["action_intents"]
        self.assertEqual(len(intents), 23)
        self.assertFalse(result["input"]["input_records_are_independent_samples"])
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
            "risk_escalation_inside_window",
            "conflict_pending_update",
            "counterevidence",
            "association_split",
            "pending_merge_then_counter_and_split",
            "distinct_event",
            "cross_window",
            "cross_card_duplicate",
            "cross_episode_duplicate",
            "out_of_order_source_time",
            "late_old_observation",
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
            "NO_MATCHING_EPISODE_INTERVAL_KEY_WITHIN_WINDOW",
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

    def test_v2_episode_and_time_boundaries_are_auditable_for_both_policies(self):
        result = build_comparison()
        cases = result["forced_cases"]
        window = result["window_results"][1]
        candidate = window["card_coalesce"]
        decisions = {row["intent_id"]: row for row in candidate["decisions"]}

        self.assertEqual(
            decisions[cases["risk_escalation_inside_window"]["intent_id"]]["status"],
            "EMITTED",
        )
        self.assertEqual(
            decisions[cases["risk_escalation_inside_window"]["intent_id"]]["decision_reason"],
            "PROTECTED_ACTION_KIND",
        )
        conflict = cases["conflict_pending_update"]
        self.assertEqual(
            decisions[conflict["intent_id"]]["status"],
            "EMITTED",
        )
        self.assertEqual(
            decisions[conflict["intent_id"]]["decision_reason"],
            "NO_MATCHING_EPISODE_INTERVAL_KEY_WITHIN_WINDOW",
        )
        self.assertNotEqual(
            decisions[cases["cross_card_duplicate"]["intent_ids"][0]]["experiment_notification_id"],
            decisions[cases["cross_card_duplicate"]["intent_ids"][1]]["experiment_notification_id"],
        )
        self.assertEqual(
            decisions[cases["cross_episode_duplicate"]["intent_id"]]["status"],
            "EMITTED",
        )

        late = cases["late_old_observation"]
        self.assertLess(late["source_time"], late["observed_at"])
        self.assertLess(late["observed_at"], late["trigger_known_time"])
        self.assertLess(late["trigger_known_time"], late["detected_at"])
        self.assertLess(late["detected_at"], late["processing_received_at"])
        self.assertEqual(late["observed_at"], late["card_revision_observed_at"])
        self.assertNotEqual(late["card_revision_observed_at"], late["processing_received_at"])

        for policy_name in ("per_association", "card_coalesce"):
            policy = window[policy_name]
            intent_ids = {
                row["intent_id"] for row in policy["card_revisions"]
            }
            self.assertEqual(intent_ids, {row["intent_id"] for row in result["input"]["action_intents"]})
            self.assertEqual(policy["missed_important_update_ids"], [])
            late_revision = next(
                row for row in policy["card_revisions"]
                if row["intent_id"] == late["intent_id"]
            )
            self.assertEqual(late_revision["source_times"][0], late["source_time"])
            self.assertEqual(late_revision["observed_at_times"][0], late["observed_at"])
            self.assertEqual(late_revision["trigger_known_time"], late["trigger_known_time"])
            self.assertEqual(late_revision["detected_at"], late["detected_at"])
            self.assertEqual(late_revision["received_at"], late["processing_received_at"])

        self.assertEqual(
            result["v2_contract_audit"]["dedup_episode_interval_key"],
            "EXPERIMENT_INPUT_NOT_FROZEN",
        )
        self.assertEqual(
            result["v2_contract_audit"]["user_visible_message"], "NOT_GENERATED"
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
        self.assertIn("SAME_CARD_EPISODE_INTERVAL_KEY_WITHIN_WINDOW", rendered)
        self.assertIn("same_card_is_event_equivalence", rendered)
        self.assertIn("EXPERIMENT_INPUT_NOT_FROZEN", rendered)
        self.assertIn("trigger_known_time", rendered)
        self.assertIn("detected_at", rendered)
        self.assertIn("visible_at", rendered)
        self.assertIn("NOT_GENERATED", rendered)
        self.assertIn("CONFLICT_PENDING", rendered)
        self.assertNotIn("https://", rendered)


if __name__ == "__main__":
    unittest.main()
