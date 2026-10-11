"""Tests for an isolated, parameterized reminder-coalescing experiment."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace
import unittest

from rfb.research.alert_action_experiment import (
    ActionIntent,
    ActionKind,
    ApplyStatus,
    PolicyMode,
    ReminderActionLedger,
)


BASE = datetime(2026, 10, 11, 8, 0, 0, tzinfo=timezone.utc)


def stamp(seconds: int) -> str:
    return (BASE + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def pending(
    intent_id: str,
    association_id: str,
    *,
    card_id: str = "CARD-A",
    received_seconds: int = 0,
    source_seconds: int = 0,
    observed_seconds: int | None = None,
    batch_id: str = "BATCH-1",
    episode_ids: tuple[str, ...] | None = None,
    interval_key: str = "SYNTHETIC-TEST-INTERVAL",
    association_state: str = "UNKNOWN_PENDING",
    trigger_known_seconds: int | None = None,
    detected_seconds: int | None = None,
) -> ActionIntent:
    return ActionIntent(
        intent_id=intent_id,
        display_card_id=card_id,
        kind=ActionKind.ASSOCIATION_PENDING,
        risk_stage="PRECAUTIONARY",
        received_at=stamp(received_seconds),
        observation_ids=(f"observation-{association_id}-left", f"observation-{association_id}-right"),
        source_ids=(f"device-{association_id}-left", f"device-{association_id}-right"),
        source_times=(stamp(source_seconds),),
        observed_at_times=(
            stamp(
                min(source_seconds, received_seconds)
                if observed_seconds is None
                else observed_seconds
            ),
        ),
        candidate_episode_ids=episode_ids
        or ("episode-shared-card-a", f"episode-{association_id}"),
        association_ids=(association_id,),
        evidence_refs=(f"synthetic://association/{association_id}",),
        risk_flags=("EXPOSURE",),
        risk_basis_ids=(f"synthetic://risk/{association_id}",),
        experiment_batch_id=batch_id,
        association_state=association_state,
        dedup_episode_interval_key=interval_key,
        trigger_known_time=(
            stamp(trigger_known_seconds) if trigger_known_seconds is not None else None
        ),
        detected_at=stamp(detected_seconds) if detected_seconds is not None else None,
    )


def protected(
    intent_id: str,
    kind: ActionKind,
    *,
    card_id: str = "CARD-A",
    received_seconds: int = 1,
    risk_stage: str = "PRECAUTIONARY",
) -> ActionIntent:
    return ActionIntent(
        intent_id=intent_id,
        display_card_id=card_id,
        kind=kind,
        risk_stage=risk_stage,
        received_at=stamp(received_seconds),
        observation_ids=("obs-a", "obs-b"),
        source_ids=("device-a", "device-b"),
        source_times=(stamp(0),),
        observed_at_times=(stamp(0),),
        candidate_episode_ids=("episode-a", "episode-b"),
        association_ids=(f"association-{intent_id}",),
        evidence_refs=(f"synthetic://evidence/{intent_id}",),
        risk_flags=("EXPOSURE",),
        risk_basis_ids=(f"synthetic://risk/{intent_id}",),
        experiment_batch_id="BATCH-1",
        association_state=(
            "DIFFERENT_CONFIRMED"
            if kind in {ActionKind.COUNTER_EVIDENCE, ActionKind.EVENT_SPLIT}
            else "SAME_CONFIRMED"
            if kind is ActionKind.ASSOCIATION_CONFIRMED
            else "UNKNOWN_PENDING"
        ),
        dedup_episode_interval_key=f"SYNTHETIC-TEST-INTERVAL-{card_id}",
    )


def ledger(mode: PolicyMode, window: float = 5) -> ReminderActionLedger:
    return ReminderActionLedger(mode=mode, merge_window_seconds=window)


class ReminderActionExperimentTests(unittest.TestCase):
    def test_card_policy_coalesces_only_inside_inclusive_window_and_keeps_revisions(self):
        inputs = (
            pending("intent-ab", "assoc-ab", received_seconds=0, source_seconds=0),
            pending("intent-ac", "assoc-ac", received_seconds=3, source_seconds=1),
            pending("intent-ad", "assoc-ad", received_seconds=5, source_seconds=2),
            pending("intent-ae", "assoc-ae", received_seconds=6, source_seconds=3),
        )
        per_association = ledger(PolicyMode.PER_ASSOCIATION, window=5)
        card_coalesced = ledger(PolicyMode.CARD_COALESCE, window=5)
        for intent in inputs:
            per_association.apply(intent)
            card_coalesced.apply(intent)

        self.assertEqual(len(per_association.notifications), 4)
        self.assertEqual(len(card_coalesced.notifications), 2)
        revisions = card_coalesced.card_revisions_for("CARD-A")
        self.assertEqual(len(revisions), 4)
        self.assertEqual(
            {association for row in revisions for association in row.association_ids},
            {"assoc-ab", "assoc-ac", "assoc-ad", "assoc-ae"},
        )
        self.assertEqual(
            {ref for row in revisions for ref in row.evidence_refs},
            {f"synthetic://association/{name}" for name in ("assoc-ab", "assoc-ac", "assoc-ad", "assoc-ae")},
        )
        self.assertEqual(len(card_coalesced.notifications[0].updates), 3)
        self.assertEqual(len(card_coalesced.notifications[1].updates), 1)
        self.assertEqual(
            {source_id for update in card_coalesced.notifications[0].updates for source_id in update.source_ids},
            {
                f"device-{name}-left"
                for name in ("assoc-ab", "assoc-ac", "assoc-ad")
            }
            | {
                f"device-{name}-right"
                for name in ("assoc-ab", "assoc-ac", "assoc-ad")
            },
        )
        self.assertEqual(
            [decision.status for decision in card_coalesced.decisions],
            [ApplyStatus.EMITTED, ApplyStatus.COALESCED, ApplyStatus.COALESCED, ApplyStatus.EMITTED],
        )
        self.assertEqual(
            getattr(card_coalesced.decisions[1], "decision_reason", None),
            "SAME_CARD_EPISODE_INTERVAL_KEY_WITHIN_WINDOW",
        )
        self.assertEqual(
            getattr(card_coalesced.decisions[1], "coalescing_elapsed_seconds", None),
            3,
        )
        self.assertEqual(
            getattr(card_coalesced.decisions[1], "coalescing_window_seconds", None),
            5,
        )

    def test_zero_window_coalesces_only_same_processing_instant(self):
        inputs = (
            pending("intent-ab", "assoc-ab", received_seconds=0),
            pending("intent-ac", "assoc-ac", received_seconds=0),
            pending("intent-ad", "assoc-ad", received_seconds=1),
        )
        candidate = ledger(PolicyMode.CARD_COALESCE, window=0)

        for intent in inputs:
            candidate.apply(intent)

        self.assertEqual(len(candidate.notifications), 2)
        self.assertEqual(len(candidate.card_revisions_for("CARD-A")), 3)
        self.assertEqual(len(candidate.notifications[0].updates), 2)

    def test_cross_episode_pending_updates_on_same_card_do_not_coalesce(self):
        candidate = ledger(PolicyMode.CARD_COALESCE, window=5)
        first = pending(
            "intent-episode-one", "assoc-episode-one", received_seconds=0,
            episode_ids=("episode-one",),
        )
        second = pending(
            "intent-episode-two", "assoc-episode-two", received_seconds=1,
            episode_ids=("episode-two",),
        )

        candidate.apply(first)
        candidate.apply(second)

        self.assertEqual(len(candidate.notifications), 2)
        self.assertEqual(len(candidate.card_revisions_for("CARD-A")), 2)
        self.assertEqual(
            {revision.candidate_episode_ids[0] for revision in candidate.card_revisions_for("CARD-A")},
            {"episode-one", "episode-two"},
        )

    def test_same_episode_update_on_another_display_card_does_not_coalesce(self):
        candidate = ledger(PolicyMode.CARD_COALESCE, window=5)
        original = pending(
            "intent-card-a", "assoc-shared", received_seconds=0,
            episode_ids=("episode-shared",),
        )
        other_card = replace(
            original,
            intent_id="intent-card-b",
            display_card_id="CARD-B",
            received_at=stamp(1),
        )

        candidate.apply(original)
        candidate.apply(other_card)

        self.assertEqual(len(candidate.notifications), 2)
        self.assertEqual(len(candidate.card_revisions_for("CARD-A")), 1)
        self.assertEqual(len(candidate.card_revisions_for("CARD-B")), 1)

    def test_same_card_and_episode_with_different_interval_key_does_not_coalesce(self):
        candidate = ledger(PolicyMode.CARD_COALESCE, window=5)
        shared_episodes = ("episode-shared", "episode-neighbor")
        first = pending(
            "intent-interval-one", "assoc-interval-one", received_seconds=0,
            episode_ids=shared_episodes, interval_key="SYNTHETIC-INTERVAL-ONE",
        )
        second = pending(
            "intent-interval-two", "assoc-interval-two", received_seconds=1,
            episode_ids=shared_episodes, interval_key="SYNTHETIC-INTERVAL-TWO",
        )

        candidate.apply(first)
        candidate.apply(second)

        self.assertEqual(len(candidate.notifications), 2)
        self.assertEqual(len(candidate.card_revisions_for("CARD-A")), 2)

    def test_conflict_pending_update_is_not_coalesced_with_unknown_pending(self):
        candidate = ledger(PolicyMode.CARD_COALESCE, window=5)
        shared_episodes = ("episode-a", "episode-b")
        first = pending(
            "intent-unknown-pending", "assoc-unknown", received_seconds=0,
            episode_ids=shared_episodes, interval_key="SYNTHETIC-INTERVAL-AB",
            association_state="UNKNOWN_PENDING",
        )
        conflict = pending(
            "intent-conflict-pending", "assoc-conflict", received_seconds=1,
            episode_ids=shared_episodes, interval_key="SYNTHETIC-INTERVAL-AB",
            association_state="CONFLICT_PENDING",
        )

        candidate.apply(first)
        candidate.apply(conflict)

        self.assertEqual(len(candidate.notifications), 2)
        self.assertEqual(
            [item.association_state for item in candidate.notifications],
            ["UNKNOWN_PENDING", "CONFLICT_PENDING"],
        )

    def test_escalation_counterevidence_and_split_survive_a_pending_merge(self):
        candidate = ledger(PolicyMode.CARD_COALESCE, window=5)
        pending_first = pending(
            "intent-pending-first", "assoc-ab", received_seconds=0,
            episode_ids=("episode-a", "episode-b"),
        )
        pending_repeat = pending(
            "intent-pending-repeat", "assoc-ac", received_seconds=1,
            episode_ids=("episode-a", "episode-c"),
        )
        escalation = protected(
            "intent-window-escalation", ActionKind.RISK_ESCALATION,
            received_seconds=2, risk_stage="ESCALATED",
        )
        counterevidence = protected(
            "intent-window-counterevidence", ActionKind.COUNTER_EVIDENCE,
            received_seconds=3,
        )
        split = protected(
            "intent-window-split", ActionKind.EVENT_SPLIT,
            received_seconds=4,
        )

        decisions = [
            candidate.apply(item)
            for item in (pending_first, pending_repeat, escalation, counterevidence, split)
        ]

        self.assertEqual(
            [decision.status for decision in decisions],
            [
                ApplyStatus.EMITTED,
                ApplyStatus.COALESCED,
                ApplyStatus.EMITTED,
                ApplyStatus.EMITTED,
                ApplyStatus.EMITTED,
            ],
        )
        self.assertEqual(len(candidate.card_revisions_for("CARD-A")), 5)
        self.assertEqual(len(candidate.notifications), 4)
        self.assertEqual(candidate.missed_important_update_ids(), ())
        self.assertEqual(
            {revision.intent_id for notification in candidate.notifications for revision in notification.updates},
            {item.intent_id for item in (pending_first, pending_repeat, escalation, counterevidence, split)},
        )

    def test_late_old_observation_keeps_source_observed_and_processing_times_separate(self):
        candidate = ledger(PolicyMode.CARD_COALESCE, window=5)
        late_old_observation = pending(
            "intent-late-old-observation",
            "assoc-late-old",
            received_seconds=24,
            source_seconds=1,
            observed_seconds=18,
            episode_ids=("episode-late-old",),
        )

        candidate.apply(late_old_observation)
        revision = candidate.card_revisions_for("CARD-A")[0]

        self.assertEqual(revision.source_times, (stamp(1),))
        self.assertEqual(revision.observed_at_times, (stamp(18),))
        self.assertEqual(revision.received_at, stamp(24))
        self.assertNotEqual(revision.observed_at_times[0], revision.received_at)

    def test_v2_time_and_episode_interval_fields_are_explicit_on_action_intent(self):
        fields = getattr(ActionIntent, "__dataclass_fields__", {})

        for name in (
            "dedup_episode_interval_key",
            "association_state",
            "risk_flags",
            "risk_basis_ids",
            "trigger_known_time",
            "detected_at",
        ):
            with self.subTest(field=name):
                self.assertIn(name, fields)

    def test_exact_replay_with_new_arrival_time_does_not_refresh_old_record(self):
        candidate = ledger(PolicyMode.CARD_COALESCE, window=5)
        original = pending("intent-ab", "assoc-ab", received_seconds=0, source_seconds=-30)
        replayed_today = replace(original, received_at=stamp(100))

        candidate.apply(original)
        replay_decision = candidate.apply(replayed_today)

        self.assertEqual(replay_decision.status, ApplyStatus.DUPLICATE_REPLAY)
        self.assertEqual(len(candidate.notifications), 1)
        self.assertEqual(len(candidate.card_revisions_for("CARD-A")), 1)
        self.assertEqual(candidate.notifications[0].updates[0].received_at, original.received_at)
        self.assertEqual(candidate.notifications[0].updates[0].source_times, original.source_times)

    def test_out_of_order_source_times_are_kept_as_distinct_card_revisions(self):
        candidate = ledger(PolicyMode.CARD_COALESCE, window=5)
        earlier_source_arrives_later = (
            pending("intent-newer-source", "assoc-newer", received_seconds=10, source_seconds=8),
            pending("intent-older-source", "assoc-older", received_seconds=11, source_seconds=2),
        )

        for intent in earlier_source_arrives_later:
            candidate.apply(intent)

        revisions = candidate.card_revisions_for("CARD-A")
        self.assertEqual(len(revisions), 2)
        self.assertEqual([row.source_times for row in revisions], [(stamp(8),), (stamp(2),)])
        self.assertEqual([row.received_at for row in revisions], [stamp(10), stamp(11)])
        self.assertEqual(len(candidate.notifications), 1)
        self.assertEqual(len(candidate.notifications[0].updates), 2)

    def test_batch_is_an_explicit_coalescing_boundary(self):
        candidate = ledger(PolicyMode.CARD_COALESCE, window=5)
        candidate.apply(pending("intent-ab", "assoc-ab", received_seconds=0, batch_id="BATCH-1"))
        candidate.apply(pending("intent-ac", "assoc-ac", received_seconds=1, batch_id="BATCH-2"))

        self.assertEqual(len(candidate.notifications), 2)
        self.assertEqual(len(candidate.card_revisions_for("CARD-A")), 2)

    def test_escalation_counterevidence_split_and_distinct_event_are_never_coalesced(self):
        candidate = ledger(PolicyMode.CARD_COALESCE, window=10)
        inputs = (
            pending("intent-pending", "assoc-pending", received_seconds=0),
            protected(
                "intent-escalation",
                ActionKind.RISK_ESCALATION,
                received_seconds=1,
                risk_stage="ESCALATED",
            ),
            protected("intent-counterevidence", ActionKind.COUNTER_EVIDENCE, received_seconds=2),
            protected("intent-split", ActionKind.EVENT_SPLIT, received_seconds=3),
            pending(
                "intent-distinct-event",
                "assoc-distinct-event",
                card_id="CARD-DISTINCT",
                received_seconds=1,
            ),
        )

        decisions = [candidate.apply(intent) for intent in inputs]

        self.assertEqual(len(candidate.notifications), 5)
        self.assertEqual(len(candidate.card_revisions_for("CARD-A")), 4)
        self.assertEqual(len(candidate.card_revisions_for("CARD-DISTINCT")), 1)
        for decision in decisions[1:]:
            self.assertEqual(decision.status, ApplyStatus.EMITTED)
        self.assertEqual(
            {notification.display_card_id for notification in candidate.notifications},
            {"CARD-A", "CARD-DISTINCT"},
        )

    def test_confirmed_relation_revision_is_not_folded_into_pending_update(self):
        candidate = ledger(PolicyMode.CARD_COALESCE, window=10)
        pending_update = pending("intent-ab-pending", "assoc-ab", received_seconds=0)
        confirmation = ActionIntent(
            intent_id="intent-ab-confirmed",
            display_card_id="CARD-A",
            kind=ActionKind.ASSOCIATION_CONFIRMED,
            risk_stage="PRECAUTIONARY",
            received_at=stamp(1),
            observation_ids=("obs-a", "obs-b"),
            source_ids=("device-a", "device-b"),
            candidate_episode_ids=("episode-a", "episode-b"),
            association_ids=("assoc-ab",),
            evidence_refs=("synthetic://confirmation/ab",),
            risk_flags=("EXPOSURE",),
            risk_basis_ids=("synthetic://risk/confirmation-ab",),
            source_times=(stamp(0),),
            observed_at_times=(stamp(0),),
            experiment_batch_id="BATCH-1",
            association_state="SAME_CONFIRMED",
            dedup_episode_interval_key="SYNTHETIC-TEST-INTERVAL-CARD-A",
        )

        first = candidate.apply(pending_update)
        second = candidate.apply(confirmation)

        self.assertEqual(first.status, ApplyStatus.EMITTED)
        self.assertEqual(second.status, ApplyStatus.EMITTED)
        self.assertEqual(len(candidate.notifications), 2)
        self.assertEqual(len(candidate.card_revisions_for("CARD-A")), 2)

    def test_card_updates_are_immediate_in_simulated_time_not_actual_visibility(self):
        candidate = ledger(PolicyMode.CARD_COALESCE, window=5)
        first = pending("intent-ab", "assoc-ab", received_seconds=0)
        second = pending("intent-ac", "assoc-ac", received_seconds=3)

        candidate.apply(first)
        decision = candidate.apply(second)

        self.assertEqual(decision.status, ApplyStatus.COALESCED)
        self.assertEqual(decision.simulated_card_update_delay_seconds, 0)
        self.assertIsNone(decision.actual_visible_at)
        self.assertEqual(candidate.card_revisions_for("CARD-A")[-1].received_at, second.received_at)


if __name__ == "__main__":
    unittest.main()
