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
    batch_id: str = "BATCH-1",
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
        observed_at_times=(stamp(min(source_seconds, received_seconds)),),
        candidate_episode_ids=(f"episode-{association_id}-left", f"episode-{association_id}-right"),
        association_ids=(association_id,),
        evidence_refs=(f"synthetic://association/{association_id}",),
        experiment_batch_id=batch_id,
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
        experiment_batch_id="BATCH-1",
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
            "SAME_CARD_KIND_STAGE_BATCH_WITHIN_WINDOW",
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
            source_times=(stamp(0),),
            observed_at_times=(stamp(0),),
            experiment_batch_id="BATCH-1",
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
