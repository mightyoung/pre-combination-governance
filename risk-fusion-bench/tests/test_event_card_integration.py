"""Small synthetic integration checks across identity, action, and card preview."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest

from rfb.research.alert_action_experiment import (
    ActionIntent,
    ActionKind,
    ApplyStatus,
    PolicyMode,
    ReminderActionLedger,
)
from rfb.research.event_card_resolution import (
    PendingAssociation,
    resolve_pending_association,
)
from rfb.research.frozen_prefix_adapter import PrefixFieldFact, freeze_visible_prefix
try:
    from rfb.research.alert_notification_preview import build_event_card_preview
except ImportError:
    build_event_card_preview = None


BASE = datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc)
EPISODES = ("EP-A", "EP-B")
ASSOCIATION_ID = "ASSOC-A-B"


def stamp(seconds: int) -> str:
    return (BASE + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def make_intent(
    intent_id: str,
    *,
    card_id: str = "CARD-A",
    kind: ActionKind = ActionKind.ASSOCIATION_PENDING,
    state: str = "UNKNOWN_PENDING",
    episodes: tuple[str, ...] = EPISODES,
    risk_flags: tuple[str, ...] = ("EXPOSURE",),
    received_seconds: int = 0,
    detected_seconds: int = 0,
) -> ActionIntent:
    return ActionIntent(
        intent_id=intent_id,
        display_card_id=card_id,
        kind=kind,
        risk_stage="PRECAUTIONARY",
        received_at=stamp(received_seconds),
        observation_ids=tuple(f"OBS-{episode}" for episode in episodes),
        source_ids=tuple(f"DEVICE-{episode}" for episode in episodes),
        candidate_episode_ids=episodes,
        association_ids=(ASSOCIATION_ID,),
        evidence_refs=(f"synthetic://evidence/{intent_id}",),
        risk_flags=risk_flags,
        risk_basis_ids=(f"synthetic://risk/{intent_id}",),
        source_times=(stamp(0),),
        observed_at_times=(stamp(0),),
        experiment_batch_id="SYNTH-BATCH-INTEGRATION",
        association_state=state,
        dedup_episode_interval_key="SYNTH-INTERVAL-A-B",
        trigger_known_time=stamp(0),
        detected_at=stamp(detected_seconds),
    )


def new_ledger() -> ReminderActionLedger:
    return ReminderActionLedger(mode=PolicyMode.CARD_COALESCE, merge_window_seconds=5)


def pending_association() -> PendingAssociation:
    return PendingAssociation(
        association_id=ASSOCIATION_ID,
        display_card_id="CARD-A",
        candidate_episode_ids=EPISODES,
        association_state="UNKNOWN_PENDING",
        pending_at=stamp(0),
        evidence_refs=("synthetic://pending/A-B",),
    )


def prefix_facts(
    *, association_state: str, risk_flags: tuple[str, ...], known_seconds: int
) -> tuple[PrefixFieldFact, ...]:
    values = {
        "display_card_id": "CARD-A",
        "candidate_episode_ids": EPISODES,
        "association_ids": (ASSOCIATION_ID,),
        "risk_stage": "PRECAUTIONARY",
        "risk_flags": risk_flags,
        "risk_basis_ids": ("synthetic://risk/prefix",),
        "observation_ids": ("OBS-EP-A", "OBS-EP-B"),
        "source_ids": ("DEVICE-EP-A", "DEVICE-EP-B"),
        "evidence_refs": ("synthetic://evidence/prefix",),
        "source_times": (stamp(0),),
        "observed_at_times": (stamp(0),),
        "experiment_batch_id": "SYNTH-BATCH-FROZEN-PREFIX",
        "association_state": association_state,
        "dedup_episode_interval_key": "SYNTH-INTERVAL-A-B",
        "trigger_known_time": stamp(0),
        "detected_at": stamp(known_seconds),
    }
    known_at = stamp(known_seconds)
    return tuple(
        PrefixFieldFact(
            name=name,
            value=value,
            producer=f"synthetic-upstream:{name}:v1",
            earliest_known_at=known_at,
            evidence_refs=(f"synthetic://prefix/{name}/{known_seconds}",),
        )
        for name, value in values.items()
    )


def intent_from_frozen_prefix(prefix, *, intent_id: str) -> ActionIntent:
    return ActionIntent(
        intent_id=intent_id,
        display_card_id=prefix.value("display_card_id"),
        kind=ActionKind.ASSOCIATION_PENDING,
        risk_stage=prefix.value("risk_stage"),
        received_at=prefix.as_of,
        observation_ids=prefix.value("observation_ids"),
        source_ids=prefix.value("source_ids"),
        candidate_episode_ids=prefix.value("candidate_episode_ids"),
        association_ids=prefix.value("association_ids"),
        evidence_refs=prefix.value("evidence_refs"),
        risk_flags=prefix.value("risk_flags"),
        risk_basis_ids=prefix.value("risk_basis_ids"),
        source_times=prefix.value("source_times"),
        observed_at_times=prefix.value("observed_at_times"),
        experiment_batch_id=prefix.value("experiment_batch_id"),
        association_state=prefix.value("association_state"),
        dedup_episode_interval_key=prefix.value("dedup_episode_interval_key"),
        trigger_known_time=prefix.value("trigger_known_time"),
        detected_at=prefix.value("detected_at"),
    )


class EventCardIntegrationTests(unittest.TestCase):
    def require_preview_builder(self):
        self.assertIsNotNone(
            build_event_card_preview,
            "the complete event-card preview is not connected to the action ledger",
        )

    def test_complete_future_suffixes_freeze_to_the_same_card_preview_at_one_as_of(self):
        self.require_preview_builder()
        common_prefix = prefix_facts(
            association_state="UNKNOWN_PENDING",
            risk_flags=("EXPOSURE",),
            known_seconds=0,
        )
        future_same = prefix_facts(
            association_state="SAME_CONFIRMED",
            risk_flags=("EXPOSURE_HIGH",),
            known_seconds=2,
        )
        future_different = prefix_facts(
            association_state="DIFFERENT_CONFIRMED",
            risk_flags=("EXPOSURE", "CONFLICT_REVIEW"),
            known_seconds=2,
        )
        self.assertNotEqual(future_same, future_different)

        same_prefix = freeze_visible_prefix(
            common_prefix + future_same, as_of=stamp(1)
        )
        different_prefix = freeze_visible_prefix(
            common_prefix + future_different, as_of=stamp(1)
        )
        self.assertEqual(same_prefix.as_record(), different_prefix.as_record())
        self.assertNotEqual(
            freeze_visible_prefix(common_prefix + future_same, as_of=stamp(3)).as_record(),
            freeze_visible_prefix(common_prefix + future_different, as_of=stamp(3)).as_record(),
        )

        same_ledger = new_ledger()
        different_ledger = new_ledger()
        same_ledger.apply(
            intent_from_frozen_prefix(same_prefix, intent_id="frozen-prefix-pending")
        )
        different_ledger.apply(
            intent_from_frozen_prefix(different_prefix, intent_id="frozen-prefix-pending")
        )
        same_preview = build_event_card_preview(
            pending_association(), card_id="CARD-A", ledger=same_ledger
        )
        different_preview = build_event_card_preview(
            pending_association(), card_id="CARD-A", ledger=different_ledger
        )
        self.assertEqual(same_preview, different_preview)
        self.assertEqual(same_preview["association_state"], "UNKNOWN_PENDING")
        self.assertEqual(same_preview["candidate_episode_ids"], list(EPISODES))

    def test_identical_prefix_forks_to_external_same_merge_and_different_split(self):
        self.require_preview_builder()
        prefix_intent = make_intent("prefix-pending")
        pending = pending_association()
        same_ledger = new_ledger()
        different_ledger = new_ledger()
        self.assertEqual(same_ledger.apply(prefix_intent).status, ApplyStatus.EMITTED)
        self.assertEqual(different_ledger.apply(prefix_intent).status, ApplyStatus.EMITTED)

        same_prefix_preview = build_event_card_preview(
            pending, card_id="CARD-A", ledger=same_ledger
        )
        different_prefix_preview = build_event_card_preview(
            pending, card_id="CARD-A", ledger=different_ledger
        )
        self.assertEqual(same_prefix_preview, different_prefix_preview)
        self.assertEqual(same_prefix_preview["delivery_status"], "NOT_DELIVERED")
        self.assertEqual(same_prefix_preview["event_episode_ids"], [])
        self.assertEqual(same_prefix_preview["candidate_episode_ids"], list(EPISODES))
        self.assertEqual(
            same_prefix_preview["identity_ledger_alignment"]["status"],
            "MATCHED_LEDGER_HISTORY",
        )
        empty_history_preview = build_event_card_preview(
            pending, card_id="CARD-A", ledger=new_ledger()
        )
        self.assertEqual(
            empty_history_preview["identity_ledger_alignment"]["status"],
            "NO_LEDGER_HISTORY_TO_COMPARE",
        )

        same_resolution = resolve_pending_association(
            pending,
            association_state="SAME_CONFIRMED",
            identity_evidence_known_at=stamp(2),
            resolved_at=stamp(3),
            evidence_refs=("synthetic://identity/SAME/A-B",),
        )
        same_confirmation = make_intent(
            "same-confirmation",
            kind=ActionKind.ASSOCIATION_CONFIRMED,
            state="SAME_CONFIRMED",
            received_seconds=3,
            detected_seconds=2,
        )
        same_ledger.apply(same_confirmation)
        same_card = build_event_card_preview(
            same_resolution, card_id="CARD-A", ledger=same_ledger
        )

        self.assertEqual(same_card["association_state"], "SAME_CONFIRMED")
        self.assertEqual(same_card["event_episode_ids"], list(EPISODES))
        self.assertEqual(
            same_card["identity_ledger_alignment"]["status"],
            "MATCHED_LEDGER_HISTORY",
        )
        same_temporal_alignment = same_card["identity_ledger_alignment"][
            "temporal_alignment"
        ]
        self.assertEqual(same_temporal_alignment["status"], "ALIGNED")
        self.assertEqual(
            same_temporal_alignment["identity_evidence_known_at"], stamp(2)
        )
        self.assertEqual(same_temporal_alignment["identity_resolved_at"], stamp(3))
        self.assertEqual(
            same_temporal_alignment["earliest_resolved_revision_received_at"],
            stamp(3),
        )
        self.assertEqual(
            same_temporal_alignment["earliest_identity_transition_detected_at"],
            stamp(2),
        )
        self.assertEqual(same_card["history_link_card_ids"], [])
        self.assertEqual(same_card["content_revision_count"], 2)
        self.assertEqual(len(same_card["revision_history"]), 2)
        self.assertEqual(
            same_card["revision_history"][0]["association_state"],
            "UNKNOWN_PENDING",
        )
        self.assertEqual(same_card["current_content"]["trigger_known_time"], stamp(0))
        self.assertEqual(
            same_card["identity_resolution"]["state_source"],
            "EXTERNALLY_SUPPLIED_RESOLUTION",
        )
        self.assertTrue(same_card["card_preview_audit"]["all_required_fields_present"])
        self.assertTrue(
            all(
                preview["field_audit"]["all_required_fields_present"]
                for preview in same_card["revision_history"]
            )
        )
        self.assertEqual(same_card["delivery_status"], "NOT_DELIVERED")
        self.assertEqual(same_card["business_acceptance"], "NOT_EVALUATED")

        different_resolution = resolve_pending_association(
            pending,
            association_state="DIFFERENT_CONFIRMED",
            identity_evidence_known_at=stamp(2),
            resolved_at=stamp(3),
            evidence_refs=("synthetic://identity/DIFFERENT/A-B",),
            new_display_card_id="CARD-B",
        )
        split_update = make_intent(
            "different-split",
            kind=ActionKind.EVENT_SPLIT,
            state="DIFFERENT_CONFIRMED",
            episodes=("EP-A",),
            received_seconds=3,
            detected_seconds=2,
        )
        new_event_alert = make_intent(
            "new-event-alert",
            card_id="CARD-B",
            kind=ActionKind.DISTINCT_EVENT_ALERT,
            state="DIFFERENT_CONFIRMED",
            episodes=("EP-B",),
            received_seconds=3,
            detected_seconds=2,
        )
        different_ledger.apply(split_update)
        different_ledger.apply(new_event_alert)
        old_card = build_event_card_preview(
            different_resolution, card_id="CARD-A", ledger=different_ledger
        )
        new_card = build_event_card_preview(
            different_resolution, card_id="CARD-B", ledger=different_ledger
        )

        self.assertEqual(old_card["event_episode_ids"], ["EP-A"])
        self.assertEqual(old_card["history_link_card_ids"], ["CARD-B"])
        self.assertEqual(new_card["event_episode_ids"], ["EP-B"])
        self.assertEqual(new_card["history_link_card_ids"], ["CARD-A"])
        self.assertEqual(old_card["association_state"], "DIFFERENT_CONFIRMED")
        self.assertEqual(new_card["association_state"], "DIFFERENT_CONFIRMED")
        self.assertEqual(
            old_card["identity_resolution"]["state_source"],
            "EXTERNALLY_SUPPLIED_RESOLUTION",
        )
        for card_preview in (old_card, new_card):
            self.assertEqual(
                card_preview["identity_ledger_alignment"]["status"],
                "MATCHED_LEDGER_HISTORY",
            )
            self.assertEqual(
                card_preview["identity_ledger_alignment"]["temporal_alignment"]["status"],
                "ALIGNED",
            )
            self.assertTrue(card_preview["card_preview_audit"]["all_required_fields_present"])
            self.assertTrue(
                all(
                    revision["field_audit"]["all_required_fields_present"]
                    for revision in card_preview["revision_history"]
                )
            )
            self.assertTrue(
                all(
                    revision["task_context_status"]
                    == "UNSUPPORTED_BY_CURRENT_INTERFACE"
                    for revision in card_preview["revision_history"]
                )
            )
        self.assertEqual(old_card["delivery_status"], "NOT_DELIVERED")
        self.assertEqual(new_card["delivery_status"], "NOT_DELIVERED")
        self.assertEqual(old_card["business_acceptance"], "NOT_EVALUATED")
        self.assertEqual(new_card["business_acceptance"], "NOT_EVALUATED")

    def test_duplicate_replay_does_not_resend_and_severity_upgrade_creates_reminder(self):
        self.require_preview_builder()
        pending = pending_association()
        initial = make_intent("initial-reminder")
        ledger = new_ledger()
        ledger.apply(initial)
        count_before_replay = ledger.notification_action_count
        revisions_before_replay = len(ledger.card_revisions_for("CARD-A"))

        replay = replace(initial, received_at=stamp(1))
        replay_decision = ledger.apply(replay)
        self.assertEqual(replay_decision.status, ApplyStatus.DUPLICATE_REPLAY)
        self.assertEqual(ledger.notification_action_count, count_before_replay)
        self.assertEqual(len(ledger.card_revisions_for("CARD-A")), revisions_before_replay)

        escalation_reminder = replace(
            initial,
            intent_id="critical-upgrade-reminder",
            received_at=stamp(2),
            risk_flags=("EXPOSURE_HIGH",),
            evidence_refs=("synthetic://evidence/critical-upgrade",),
            risk_basis_ids=("synthetic://risk/critical-upgrade",),
        )
        upgrade_decision = ledger.apply(escalation_reminder)
        self.assertEqual(upgrade_decision.status, ApplyStatus.EMITTED)
        self.assertEqual(upgrade_decision.decision_reason, "SINGLE_FLAG_SEVERITY_ESCALATION")
        self.assertEqual(ledger.notification_action_count, count_before_replay + 1)

        preview = build_event_card_preview(pending, card_id="CARD-A", ledger=ledger)
        self.assertEqual(preview["notification_action_count"], 2)
        self.assertEqual(preview["content_revision_count"], 2)
        self.assertEqual(preview["current_content"]["severity"], "CRITICAL")
        self.assertEqual(preview["delivery_status"], "NOT_DELIVERED")
        self.assertIsNone(preview["emitted_at"])
        self.assertIsNone(preview["visible_at"])
        self.assertEqual(preview["replay_attempt_count"], 1)
        self.assertFalse(preview["replay_attempts"][0]["new_notification_created"])
        self.assertFalse(preview["replay_attempts"][0]["new_revision_created"])

    def test_synthetic_card_lifecycle_pilot_preserves_correction_and_cancel_history(self):
        self.assertTrue(
            hasattr(ActionKind, "NOTICE_CORRECTED"),
            "correction must be a typed protected action",
        )
        self.assertTrue(
            hasattr(ActionKind, "NOTICE_CANCELLED"),
            "cancellation must be a typed protected action",
        )
        from rfb.research.event_card_lifecycle_pilot import (
            run_synthetic_card_lifecycle_pilot,
        )

        repo_root = Path(__file__).resolve().parents[2]
        spec_path = (
            repo_root
            / "research-three"
            / "v2-alignment-20261011"
            / "runs"
            / "synthetic-card-lifecycle-pilot-20261012"
            / "INPUT_AND_EXPECTATIONS.json"
        )
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        result = run_synthetic_card_lifecycle_pilot(spec)
        expected = spec["expected"]

        self.assertEqual(result["classification"], "SYNTHETIC_MECHANISM_CHECK_ONLY")
        self.assertTrue(result["synthetic_only"])
        self.assertEqual(
            [row["decision_status"] for row in result["timeline"]],
            expected["decision_statuses"],
        )
        self.assertEqual(
            [row["notification_action_count"] for row in result["timeline"]],
            expected["notification_action_counts_after_each_step"],
        )
        self.assertEqual(
            [row["card_revision_count"] for row in result["timeline"]],
            expected["card_revision_counts_after_each_step"],
        )
        self.assertEqual(
            [row["notice_lifecycle_status"] for row in result["timeline"]],
            expected["notice_lifecycle_states_after_each_step"],
        )
        self.assertEqual(
            [row["display_card_id"] for row in result["timeline"]],
            [spec["context"]["display_card_id"]] * len(spec["steps"]),
        )

        final_card = result["final_card"]
        self.assertEqual(final_card["notice_lifecycle_status"], "CANCELLED")
        self.assertEqual(final_card["content_revision_count"], expected["final_card_revision_count"])
        self.assertEqual(
            final_card["notification_action_count"],
            expected["final_notification_action_count"],
        )
        self.assertEqual(
            [revision["revision_trace"]["intent_id"] for revision in final_card["revision_history"]],
            expected["final_history_intent_ids"],
        )
        self.assertEqual(final_card["association_state"], expected["association_state_remains"])
        self.assertEqual(final_card["replay_attempt_count"], expected["replay_attempt_count"])
        self.assertEqual(final_card["delivery_status"], expected["delivery_status"])
        self.assertEqual(
            result["counterexample"]["notice_lifecycle_status"],
            spec["counterexample"]["expected"]["final_notice_lifecycle_status"],
        )
        self.assertEqual(
            result["counterexample"]["decision_statuses"],
            spec["counterexample"]["expected"]["decision_statuses"],
        )
        self.assertEqual(
            result["counterexample"]["notification_action_counts"],
            spec["counterexample"]["expected"]["notification_action_counts_after_each_step"],
        )

    def test_rejects_identity_episode_or_association_mismatch_with_ledger(self):
        self.require_preview_builder()
        pending = pending_association()
        ledger = new_ledger()
        ledger.apply(make_intent("identity-mismatch-prefix"))

        other_episodes = replace(
            pending, candidate_episode_ids=("EP-X", "EP-Y")
        )
        with self.assertRaisesRegex(ValueError, "candidate episodes"):
            build_event_card_preview(other_episodes, card_id="CARD-A", ledger=ledger)

        other_association = replace(pending, association_id="ASSOC-OTHER")
        with self.assertRaisesRegex(ValueError, "association ID"):
            build_event_card_preview(other_association, card_id="CARD-A", ledger=ledger)

        partial_pending_ledger = new_ledger()
        partial_pending_ledger.apply(
            make_intent("partial-pending-episodes", episodes=("EP-A",))
        )
        with self.assertRaisesRegex(ValueError, "pending candidate episodes"):
            build_event_card_preview(
                pending, card_id="CARD-A", ledger=partial_pending_ledger
            )

        incomplete_history_ledger = new_ledger()
        incomplete_history_ledger.apply(
            make_intent("partial-pending-history", episodes=("EP-A",))
        )
        incomplete_history_ledger.apply(
            make_intent(
                "later-pending-risk-update",
                kind=ActionKind.RISK_ESCALATION,
                received_seconds=1,
            )
        )
        with self.assertRaisesRegex(ValueError, "pending candidate episodes"):
            build_event_card_preview(
                pending, card_id="CARD-A", ledger=incomplete_history_ledger
            )

    def test_rejects_resolved_identity_ahead_of_latest_ledger_revision(self):
        self.require_preview_builder()
        pending = pending_association()
        ledger = new_ledger()
        ledger.apply(make_intent("unresolved-ledger-prefix"))
        different_resolution = resolve_pending_association(
            pending,
            association_state="DIFFERENT_CONFIRMED",
            identity_evidence_known_at=stamp(2),
            resolved_at=stamp(3),
            evidence_refs=("synthetic://identity/DIFFERENT/A-B",),
            new_display_card_id="CARD-B",
        )

        with self.assertRaisesRegex(ValueError, "latest ledger revision"):
            build_event_card_preview(
                different_resolution, card_id="CARD-A", ledger=ledger
            )

        wrong_card_episode_ledger = new_ledger()
        wrong_card_episode_ledger.apply(
            make_intent(
                "wrong-episode-on-card-b",
                card_id="CARD-B",
                kind=ActionKind.DISTINCT_EVENT_ALERT,
                state="DIFFERENT_CONFIRMED",
                episodes=("EP-A",),
                received_seconds=3,
                detected_seconds=2,
            )
        )
        with self.assertRaisesRegex(ValueError, "resolved card episodes"):
            build_event_card_preview(
                different_resolution,
                card_id="CARD-B",
                ledger=wrong_card_episode_ledger,
            )

        invalid_resolved_history_ledger = new_ledger()
        invalid_resolved_history_ledger.apply(
            make_intent(
                "wrong-card-history-episode",
                card_id="CARD-B",
                kind=ActionKind.RISK_ESCALATION,
                state="DIFFERENT_CONFIRMED",
                episodes=("EP-A",),
                received_seconds=3,
            )
        )
        invalid_resolved_history_ledger.apply(
            make_intent(
                "valid-card-b-alert-after-invalid-history",
                card_id="CARD-B",
                kind=ActionKind.DISTINCT_EVENT_ALERT,
                state="DIFFERENT_CONFIRMED",
                episodes=("EP-B",),
                received_seconds=4,
                detected_seconds=2,
            )
        )
        with self.assertRaisesRegex(ValueError, "resolved card episodes"):
            build_event_card_preview(
                different_resolution,
                card_id="CARD-B",
                ledger=invalid_resolved_history_ledger,
            )

    def test_rejects_confirmation_revision_before_identity_resolution_time(self):
        self.require_preview_builder()
        pending = pending_association()
        resolution = resolve_pending_association(
            pending,
            association_state="SAME_CONFIRMED",
            identity_evidence_known_at=stamp(2),
            resolved_at=stamp(3),
            evidence_refs=("synthetic://identity/SAME/A-B",),
        )
        ledger = new_ledger()
        ledger.apply(make_intent("pending-before-identity", received_seconds=0))
        early_confirmation = make_intent(
            "early-same-confirmation",
            kind=ActionKind.ASSOCIATION_CONFIRMED,
            state="SAME_CONFIRMED",
            received_seconds=1,
            detected_seconds=1,
        )
        ledger.apply(early_confirmation)

        with self.assertRaisesRegex(ValueError, "precedes identity resolution"):
            build_event_card_preview(resolution, card_id="CARD-A", ledger=ledger)

    def test_rejects_confirmation_detection_before_identity_evidence_is_known(self):
        self.require_preview_builder()
        pending = pending_association()
        resolution = resolve_pending_association(
            pending,
            association_state="SAME_CONFIRMED",
            identity_evidence_known_at=stamp(2),
            resolved_at=stamp(3),
            evidence_refs=("synthetic://identity/SAME/A-B",),
        )
        ledger = new_ledger()
        ledger.apply(make_intent("pending-before-identity", received_seconds=0))
        late_confirmation = make_intent(
            "late-same-confirmation-with-early-detection",
            kind=ActionKind.ASSOCIATION_CONFIRMED,
            state="SAME_CONFIRMED",
            received_seconds=3,
            detected_seconds=1,
        )
        ledger.apply(late_confirmation)

        with self.assertRaisesRegex(ValueError, "detected before identity evidence"):
            build_event_card_preview(resolution, card_id="CARD-A", ledger=ledger)


if __name__ == "__main__":
    unittest.main()
