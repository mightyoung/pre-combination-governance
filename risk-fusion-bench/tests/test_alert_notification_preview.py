"""Tests for preview-only public V2 reminder payload construction."""

from __future__ import annotations

import unittest

from rfb.research.alert_action_experiment import ActionIntent, ActionKind
from rfb.research.alert_notification_preview import (
    PUBLIC_V2_NOTIFICATION_REQUIRED_FIELDS,
    audit_notification_preview,
    build_notification_content_preview,
)


STAMP = "2026-10-11T08:00:10Z"


def intent(
    *,
    state: str = "UNKNOWN_PENDING",
    risk_flags: tuple[str, ...] = ("EXPOSURE",),
) -> ActionIntent:
    return ActionIntent(
        intent_id="intent-preview-1",
        display_card_id="CARD-PREVIEW-A",
        kind=ActionKind.ASSOCIATION_PENDING,
        risk_stage="PRECAUTIONARY",
        received_at=STAMP,
        observation_ids=("observation-A", "observation-B"),
        source_ids=("device-A", "device-B"),
        candidate_episode_ids=("episode-A", "episode-B"),
        association_ids=("association-A-B",),
        evidence_refs=("synthetic://association/A-B", "synthetic://observation/A"),
        risk_flags=risk_flags,
        risk_basis_ids=("synthetic://risk/exposure-A",),
        source_times=("2026-10-11T08:00:01Z",),
        observed_at_times=("2026-10-11T08:00:02Z",),
        experiment_batch_id="SYNTH-BATCH-1",
        association_state=state,
        dedup_episode_interval_key="SYNTHETIC-INTERVAL-A-B",
        trigger_known_time=STAMP,
        detected_at=STAMP,
    )


def build_preview(
    *, state: str = "UNKNOWN_PENDING", risk_flags: tuple[str, ...] = ("EXPOSURE",)
) -> dict:
    return build_notification_content_preview(
        intent(state=state, risk_flags=risk_flags),
        notification_id="EXPERIMENT-NOTIFY-0001",
        content_revision=1,
        decision_status="EMITTED",
        revision_trace={
            "intent_id": "intent-preview-1",
            "content_revision": 1,
            "previous_intent_id": None,
            "evidence_refs": ["synthetic://association/A-B", "synthetic://observation/A"],
        },
    )


class NotificationContentPreviewTests(unittest.TestCase):
    def test_preview_contains_all_public_fields_and_required_message_context(self):
        preview = build_preview()

        self.assertEqual(
            set(PUBLIC_V2_NOTIFICATION_REQUIRED_FIELDS) - set(preview), set()
        )
        self.assertEqual(preview["kind"], "PENDING_VERIFICATION_RISK_ALERT")
        self.assertEqual(preview["severity"], "WARNING")
        self.assertEqual(preview["association_state"], "UNKNOWN_PENDING")
        self.assertEqual(preview["candidate_episode_ids"], ["episode-A", "episode-B"])
        self.assertIn("按既定处置流程核查", preview["user_visible_message"])
        self.assertIn("任务：当前接口不支持绑定", preview["user_visible_message"])
        self.assertIn("CARD-PREVIEW-A", preview["user_visible_message"])
        self.assertEqual(preview["task_ids"], [])
        self.assertEqual(
            preview["task_context_status"], "UNSUPPORTED_BY_CURRENT_INTERFACE"
        )
        self.assertEqual(preview["delivery_status"], "NOT_DELIVERED")
        self.assertIsNone(preview["emitted_at"])
        self.assertIsNone(preview["visible_at"])
        self.assertEqual(preview["revision_trace"]["intent_id"], "intent-preview-1")

        audit = preview["field_audit"]
        self.assertEqual(audit["missing_fields"], [])
        self.assertEqual(audit["business_acceptance"], "NOT_EVALUATED")
        self.assertEqual(audit["fields"]["visible_at"]["status"], "UNKNOWN_NOT_RUN")
        self.assertEqual(audit["fields"]["emitted_at"]["status"], "NOT_EMITTED")

    def test_multiflag_severity_stays_unresolved_without_ranking_flags(self):
        preview = build_preview(risk_flags=("EXPOSURE", "EXPOSURE_HIGH"))

        self.assertIsNone(preview["severity"])
        self.assertEqual(
            preview["field_audit"]["fields"]["severity"]["status"],
            "PENDING_MULTIFLAG_POLICY",
        )
        self.assertIn("多风险标记等级规则待定义", preview["user_visible_message"])
        self.assertEqual(preview["risk_state"]["risk_flags"], ["EXPOSURE", "EXPOSURE_HIGH"])

    def test_conflict_state_has_a_specific_uncertainty_reason(self):
        preview = build_preview(state="CONFLICT_PENDING")

        self.assertIn("证据冲突", preview["uncertainty_reason"])
        self.assertIn("冲突", preview["user_visible_message"])

    def test_field_audit_reports_required_fields_removed_after_construction(self):
        preview = build_preview()
        preview.pop("visible_at")

        audit = audit_notification_preview(preview)

        self.assertEqual(audit["missing_fields"], ["visible_at"])
        self.assertFalse(audit["all_required_fields_present"])
        self.assertEqual(audit["business_acceptance"], "NOT_EVALUATED")


if __name__ == "__main__":
    unittest.main()
