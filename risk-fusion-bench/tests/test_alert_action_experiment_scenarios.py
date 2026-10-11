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
            result["v2_contract_audit"]["user_visible_message"],
            "PREVIEW_ONLY_NOT_DELIVERED",
        )
        self.assertEqual(
            result["v2_contract_audit"]["suggested_verification_action"],
            "PREVIEW_ONLY_NOT_PROCEDURE_VALIDATION",
        )

    def test_notification_previews_cover_same_stream_and_all_required_fields(self):
        result = build_comparison()
        expected_intent_ids = {
            row["intent_id"] for row in result["input"]["action_intents"]
        }

        for window in result["window_results"]:
            previews_by_policy = {}
            for policy_name in ("per_association", "card_coalesce"):
                policy = window[policy_name]
                previews = policy["notification_content_previews"]
                previews_by_policy[policy_name] = {
                    row["revision_trace"]["intent_id"]: row
                    for row in previews
                    if row["preview_status"] != "DUPLICATE_REPLAY_IGNORED"
                }
                with self.subTest(window=window["window_seconds"], policy=policy_name):
                    self.assertEqual(len(previews), len(expected_intent_ids) + 1)
                    semantic_previews = [
                        row for row in previews
                        if row["preview_status"] != "DUPLICATE_REPLAY_IGNORED"
                    ]
                    self.assertEqual(
                        {row["revision_trace"]["intent_id"] for row in semantic_previews},
                        expected_intent_ids,
                    )
                    self.assertEqual(
                        sum(row["preview_status"] == "DUPLICATE_REPLAY_IGNORED" for row in previews),
                        1,
                    )
                    self.assertEqual(
                        len({row["preview_id"] for row in previews}), len(previews)
                    )
                    self.assertEqual(
                        {row["revision_trace"]["action_kind"] for row in semantic_previews},
                        {row["kind"] for row in result["input"]["action_intents"]},
                    )
                    self.assertEqual(
                        {row["association_state"] for row in semantic_previews},
                        {row["association_state"] for row in result["input"]["action_intents"]},
                    )
                    duplicate_preview = next(
                        row for row in previews
                        if row["preview_status"] == "DUPLICATE_REPLAY_IGNORED"
                    )
                    self.assertFalse(
                        duplicate_preview["replay_attempt_audit"]["new_revision_created"]
                    )
                    for preview in previews:
                        self.assertEqual(preview["field_audit"]["missing_fields"], [])
                        self.assertEqual(
                            preview["field_audit"]["business_acceptance"],
                            "NOT_EVALUATED",
                        )
                        self.assertEqual(preview["delivery_status"], "NOT_DELIVERED")
                        self.assertEqual(preview["emission_status"], "NOT_EMITTED_SIMULATION_ONLY")
                        self.assertIsNone(preview["emitted_at"])
                        self.assertIsNone(preview["visible_at"])
                        self.assertTrue(preview["user_visible_message"])
                    action_kinds = {
                        row["revision_trace"]["action_kind"] for row in semantic_previews
                    }
                    self.assertTrue(
                        {"RISK_ESCALATION", "COUNTER_EVIDENCE", "EVENT_SPLIT"}
                        <= action_kinds
                    )
                    self.assertTrue(
                        {"UNKNOWN_PENDING", "CONFLICT_PENDING"}
                        <= {row["association_state"] for row in semantic_previews}
                    )
            for intent_id in expected_intent_ids:
                per_association = previews_by_policy["per_association"][intent_id]
                card_coalesce = previews_by_policy["card_coalesce"][intent_id]
                for field in (
                    "kind",
                    "severity",
                    "risk_state",
                    "risk_basis_ids",
                    "uncertainty_reason",
                    "affected_observation_ids",
                    "display_card_id",
                    "candidate_episode_ids",
                    "association_state",
                    "user_visible_message",
                    "suggested_verification_action",
                    "trigger_known_time",
                    "detected_at",
                    "emitted_at",
                    "visible_at",
                    "content_revision",
                    "dedup_episode_interval_key",
                ):
                    self.assertEqual(
                        per_association[field], card_coalesce[field],
                        msg=f"window={window['window_seconds']} intent={intent_id} field={field}",
                    )
            for policy_name in ("per_association", "card_coalesce"):
                split_previews = [
                    row
                    for row in window[policy_name]["notification_content_previews"]
                    if row["revision_trace"]["action_kind"] == "EVENT_SPLIT"
                ]
                self.assertTrue(split_previews)
                for preview in split_previews:
                    self.assertIn("独立事件卡", preview["user_visible_message"])
                    self.assertIn("未实际创建事件卡", preview["user_visible_message"])
                    self.assertIn("历史链接", preview["user_visible_message"])

    def test_historical_failed_baseline_is_carried_forward_without_reconstruction(self):
        result = build_comparison()
        baseline = result["historical_baseline"]

        self.assertEqual(baseline["checks_executed"], 1464)
        self.assertEqual(baseline["round_status"], "FAILED")
        self.assertEqual(baseline["method_records"], 20)
        self.assertFalse(baseline["method_records_are_independent_samples"])
        self.assertFalse(baseline["rerun_this_time"])
        self.assertEqual(baseline["legacy_metric_status"], "NOT_RECONSTRUCTED")

    def test_exact_replay_preserves_original_revision_times_and_audits_attempt_time(self):
        result = build_comparison()
        replay = result["input"]["exact_replay_attempt"]
        original = next(
            row
            for row in result["input"]["action_intents"]
            if row["intent_id"] == replay["intent_id"]
        )

        for window in result["window_results"]:
            for policy_name in ("per_association", "card_coalesce"):
                previews = window[policy_name]["notification_content_previews"]
                original_preview = next(
                    row
                    for row in previews
                    if row["preview_status"] == "PREVIEW_ONLY"
                    and row["revision_trace"]["intent_id"] == replay["intent_id"]
                )
                duplicate_preview = next(
                    row
                    for row in previews
                    if row["preview_status"] == "DUPLICATE_REPLAY_IGNORED"
                )
                with self.subTest(window=window["window_seconds"], policy=policy_name):
                    self.assertEqual(
                        duplicate_preview["time_evidence"],
                        original_preview["time_evidence"],
                    )
                    self.assertEqual(
                        duplicate_preview["revision_trace"],
                        original_preview["revision_trace"],
                    )
                    self.assertEqual(
                        duplicate_preview["replay_attempt_audit"],
                        {
                            "duplicate_of_intent_id": replay["intent_id"],
                            "original_received_at": original["received_at"],
                            "attempted_received_at": replay["received_at"],
                            "decision_status": "DUPLICATE_REPLAY_IGNORED",
                            "content_revision": original_preview["content_revision"],
                            "new_revision_created": False,
                        },
                    )

    def test_html_keeps_original_first_decision_time_separate_from_replay_time(self):
        rendered = scenarios.render_html(build_comparison())
        decision_section = rendered.split(
            "<h2>CARD_COALESCE / 5 秒：逐条决策与时间证据</h2>", 1
        )[1].split("</section>", 1)[0]

        self.assertIn(
            "<tbody><tr><td>2026-10-11T08:00:10Z</td>",
            decision_section,
        )
        self.assertIn("<td>2026-10-11T08:00:40Z</td>", decision_section)
        self.assertIn("重放到达时间（审计）：2026-10-11T08:00:40Z", rendered)

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
        self.assertIn("PREVIEW_ONLY_NOT_DELIVERED", rendered)
        self.assertIn("模拟动作决策表示策略如何处理输入，不代表实际产生提醒", rendered)
        self.assertIn("CONFLICT_PENDING", rendered)
        self.assertIn("未实际创建事件卡", rendered)
        self.assertIn("用户可见内容预览（仅模拟）", rendered)
        self.assertIn("每条必填字段审计", rendered)
        self.assertIn("本表展示增量通知内容，不是累积后的整张可见卡", rendered)
        self.assertIn("task_ids 接口当前不支持", rendered)
        self.assertNotIn("https://", rendered)


if __name__ == "__main__":
    unittest.main()
