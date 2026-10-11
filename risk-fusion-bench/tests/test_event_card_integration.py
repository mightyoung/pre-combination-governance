"""Small synthetic integration checks across identity, action, and card preview."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
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
        detected_at=stamp(0),
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


class EventCardIntegrationTests(unittest.TestCase):
    def require_preview_builder(self):
        self.assertIsNotNone(
            build_event_card_preview,
            "the complete event-card preview is not connected to the action ledger",
        )

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
        self.assertEqual(same_card["history_link_card_ids"], [])
        self.assertEqual(same_card["content_revision_count"], 2)
        self.assertEqual(len(same_card["revision_history"]), 2)
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
        )
        new_event_alert = make_intent(
            "new-event-alert",
            card_id="CARD-B",
            kind=ActionKind.DISTINCT_EVENT_ALERT,
            state="DIFFERENT_CONFIRMED",
            episodes=("EP-B",),
            received_seconds=3,
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
            )
        )
        invalid_resolved_history_ledger.apply(
            make_intent(
                "valid-card-b-alert-after-invalid-history",
                card_id="CARD-B",
                kind=ActionKind.DISTINCT_EVENT_ALERT,
                state="DIFFERENT_CONFIRMED",
                episodes=("EP-B",),
                received_seconds=1,
            )
        )
        with self.assertRaisesRegex(ValueError, "resolved card episodes"):
            build_event_card_preview(
                different_resolution,
                card_id="CARD-B",
                ledger=invalid_resolved_history_ledger,
            )


if __name__ == "__main__":
    unittest.main()
