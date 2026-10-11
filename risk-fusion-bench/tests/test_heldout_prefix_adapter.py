"""Leakage and identity-equivariance tests for the held-out prefix adapter."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from rfb.research.alert_action_experiment import (
    ActionIntent,
    ActionKind,
    PolicyMode,
    ReminderActionLedger,
)

try:
    from rfb.research.frozen_prefix_adapter import (
        PREFIX_PROVENANCE_FIELDS,
        FrozenVisiblePrefix,
        PrefixFieldFact,
        freeze_visible_prefix,
    )
except ImportError:
    PREFIX_PROVENANCE_FIELDS = None
    FrozenVisiblePrefix = None
    PrefixFieldFact = None
    freeze_visible_prefix = None


BASE = datetime(2026, 10, 11, 8, 0, 0, tzinfo=timezone.utc)


def stamp(seconds: int) -> str:
    return (BASE + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def facts_at(second: int, row: int, *, risk_flags=("EXPOSURE",)):
    at = stamp(second)
    values = {
        "kind": "PENDING_VERIFICATION_RISK_ALERT",
        "association_state": "UNKNOWN_PENDING",
        "display_card_id": "CARD-A",
        "candidate_episode_ids": ("EP-A", "EP-B"),
        "dedup_episode_interval_key": "INTERVAL-AB",
        "risk_stage": "PRECAUTIONARY",
        "risk_flags": tuple(risk_flags),
        "risk_basis_ids": (f"RISK-BASIS-{row}",),
        "observation_ids": (f"OBS-{row}",),
        "source_ids": (f"DEVICE-{row}",),
        "association_ids": (f"ASSOC-{row}",),
        "evidence_refs": (f"EVIDENCE-{row}",),
        "source_times": (stamp(max(0, second - 2)),),
        "observed_at_times": (stamp(max(0, second - 1)),),
        "experiment_batch_id": "BATCH-FROZEN",
        "trigger_known_time": stamp(max(0, second - 1)),
        "detected_at": stamp(max(0, second - 1)),
    }
    return tuple(
        PrefixFieldFact(
            name=name,
            value=value,
            producer=f"upstream:{name}:v1",
            earliest_known_at=at,
            evidence_refs=(f"LINEAGE-{name}-{row}",),
        )
        for name, value in values.items()
    )


def prefix_frames(history):
    return tuple(
        freeze_visible_prefix(history, as_of=stamp(second))
        for second in (0, 1)
    )


def policy_intents(frames):
    intents = []
    for index, frame in enumerate(frames):
        intents.append(
            ActionIntent(
                intent_id=f"intent-{frame.value('association_ids')[0]}",
                display_card_id=frame.value("display_card_id"),
                kind=ActionKind.ASSOCIATION_PENDING,
                risk_stage=frame.value("risk_stage"),
                received_at=frame.as_of,
                observation_ids=frame.value("observation_ids"),
                source_ids=frame.value("source_ids"),
                candidate_episode_ids=frame.value("candidate_episode_ids"),
                association_ids=frame.value("association_ids"),
                evidence_refs=frame.value("evidence_refs"),
                risk_flags=frame.value("risk_flags"),
                risk_basis_ids=frame.value("risk_basis_ids"),
                source_times=frame.value("source_times"),
                observed_at_times=frame.value("observed_at_times"),
                experiment_batch_id=frame.value("experiment_batch_id"),
                association_state=frame.value("association_state"),
                dedup_episode_interval_key=frame.value(
                    "dedup_episode_interval_key"
                ),
                trigger_known_time=frame.value("trigger_known_time"),
                detected_at=frame.value("detected_at"),
            )
        )
    return tuple(intents)


def run_policy_arms(frames):
    """Materialize intents once, then feed both arms the same frozen rows."""
    intents = policy_intents(frames)
    results = {}
    for mode in (PolicyMode.PER_ASSOCIATION, PolicyMode.CARD_COALESCE):
        ledger = ReminderActionLedger(mode=mode, merge_window_seconds=5)
        for intent in intents:
            ledger.apply(intent)
        results[mode] = {
            "decision_shape": tuple(
                (decision.status.value, decision.decision_reason)
                for decision in ledger.decisions
            ),
            "notification_count": ledger.notification_action_count,
            "revision_count": sum(
                len(ledger.card_revisions_for(card_id))
                for card_id in {row.display_card_id for row in intents}
            ),
            "update_counts": tuple(
                len(notification.updates) for notification in ledger.notifications
            ),
            "notifications": ledger.notifications,
            "revisions": tuple(
                revision
                for card_id in {row.display_card_id for row in intents}
                for revision in ledger.card_revisions_for(card_id)
            ),
        }
    return results


def rename_fact(fact, id_map):
    list_fields = {
        "candidate_episode_ids",
        "risk_basis_ids",
        "observation_ids",
        "source_ids",
        "association_ids",
        "evidence_refs",
    }
    if fact.name in list_fields:
        value = tuple(id_map.get(item, item) for item in fact.value)
    elif fact.name in {"display_card_id", "dedup_episode_interval_key", "experiment_batch_id"}:
        value = id_map.get(fact.value, fact.value)
    else:
        value = fact.value
    return replace(fact, value=value)


class FrozenPrefixAdapterTests(unittest.TestCase):
    def require_adapter(self):
        self.assertIsNotNone(
            PrefixFieldFact,
            "the frozen visible-prefix adapter has not been implemented",
        )
        self.assertIsNotNone(freeze_visible_prefix)

    def test_same_visible_prefix_ignores_different_future_suffixes_for_both_arms(self):
        self.require_adapter()
        common = facts_at(0, 0) + facts_at(1, 1)
        suffix_a = (
            PrefixFieldFact(
                "risk_flags", ("EXPOSURE_HIGH",), "upstream:risk:v1", stamp(2)
            ),
            PrefixFieldFact(
                "association_state", "DIFFERENT_CONFIRMED", "upstream:identity:v1", stamp(2)
            ),
            PrefixFieldFact(
                "candidate_episode_ids", ("EP-C",), "upstream:episodes:v1", stamp(2)
            ),
        )
        suffix_b = (
            PrefixFieldFact(
                "risk_flags", ("EXPOSURE", "CONFLICT_REVIEW"), "upstream:risk:v1", stamp(2)
            ),
            PrefixFieldFact(
                "association_state", "CONFLICT_PENDING", "upstream:identity:v1", stamp(2)
            ),
            PrefixFieldFact(
                "candidate_episode_ids", ("EP-D", "EP-E"), "upstream:episodes:v1", stamp(2)
            ),
        )

        frames_a = prefix_frames(common + suffix_a)
        frames_b = prefix_frames(common + suffix_b)

        self.assertEqual(
            [frame.as_record() for frame in frames_a],
            [frame.as_record() for frame in frames_b],
        )
        for frame in frames_a:
            frame_record = frame.as_record()["fields"]
            for field in PREFIX_PROVENANCE_FIELDS:
                self.assertTrue(frame_record[field]["producer"])
                self.assertTrue(frame_record[field]["earliest_known_at"])
        self.assertEqual(run_policy_arms(frames_a), run_policy_arms(frames_b))

    def test_random_consistent_id_renaming_preserves_policy_shape(self):
        self.require_adapter()
        history = facts_at(0, 0) + facts_at(1, 1)
        id_map = {
            "CARD-A": "CARD-Z91",
            "EP-A": "EP-Z17",
            "EP-B": "EP-Z04",
            "INTERVAL-AB": "INTERVAL-Z62",
            "BATCH-FROZEN": "BATCH-Z13",
            "OBS-0": "OBS-Z45",
            "OBS-1": "OBS-Z08",
            "DEVICE-0": "DEVICE-Z29",
            "DEVICE-1": "DEVICE-Z11",
            "ASSOC-0": "ASSOC-Z72",
            "ASSOC-1": "ASSOC-Z03",
            "EVIDENCE-0": "EVIDENCE-Z65",
            "EVIDENCE-1": "EVIDENCE-Z31",
            "RISK-BASIS-0": "RISK-BASIS-Z88",
            "RISK-BASIS-1": "RISK-BASIS-Z20",
        }
        renamed_history = tuple(rename_fact(fact, id_map) for fact in history)
        base_frames = prefix_frames(history)
        renamed_frames = prefix_frames(renamed_history)
        base_outputs = run_policy_arms(base_frames)
        renamed_outputs = run_policy_arms(renamed_frames)

        for mode in (PolicyMode.PER_ASSOCIATION, PolicyMode.CARD_COALESCE):
            with self.subTest(mode=mode):
                for key in (
                    "decision_shape",
                    "notification_count",
                    "revision_count",
                    "update_counts",
                ):
                    self.assertEqual(base_outputs[mode][key], renamed_outputs[mode][key])
                self.assertEqual(
                    [id_map[row.display_card_id] for row in base_outputs[mode]["notifications"]],
                    [row.display_card_id for row in renamed_outputs[mode]["notifications"]],
                )
                for original, renamed in zip(
                    base_outputs[mode]["revisions"],
                    renamed_outputs[mode]["revisions"],
                    strict=True,
                ):
                    self.assertEqual(renamed.display_card_id, id_map[original.display_card_id])
                    self.assertEqual(
                        renamed.candidate_episode_ids,
                        tuple(id_map[item] for item in original.candidate_episode_ids),
                    )
                    self.assertEqual(
                        renamed.observation_ids,
                        tuple(id_map[item] for item in original.observation_ids),
                    )

    def test_adapter_rejects_scenario_and_oracle_action_fields(self):
        self.require_adapter()
        for name, value in (
            ("scenario_id", "SCN-1"),
            ("oracle_action_label", "EVENT_SPLIT"),
            ("action_kind", "RISK_ESCALATION"),
            ("kind", "EVENT_SPLIT"),
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    PrefixFieldFact(name, value, "upstream:test:v1", stamp(0))

    def test_same_time_conflicting_field_facts_fail_closed(self):
        self.require_adapter()
        facts = (
            PrefixFieldFact(
                "association_state", "UNKNOWN_PENDING", "upstream:a:v1", stamp(0)
            ),
            PrefixFieldFact(
                "association_state", "DIFFERENT_CONFIRMED", "upstream:b:v1", stamp(0)
            ),
        )
        with self.assertRaisesRegex(ValueError, "ambiguous same-time facts"):
            freeze_visible_prefix(facts, as_of=stamp(0))

    def test_public_prefix_constructor_rejects_future_fact(self):
        self.require_adapter()
        future_fact = PrefixFieldFact(
            "risk_flags",
            ("EXPOSURE_HIGH",),
            "upstream:risk:v1",
            stamp(1),
        )
        with self.assertRaisesRegex(ValueError, "after as_of"):
            FrozenVisiblePrefix(as_of=stamp(0), _fields=(future_fact,))

    def test_public_prefix_constructor_rejects_duplicate_field_versions(self):
        self.require_adapter()
        pending_fact = PrefixFieldFact(
            "association_state",
            "UNKNOWN_PENDING",
            "upstream:identity:v1",
            stamp(0),
        )
        confirmed_fact = PrefixFieldFact(
            "association_state",
            "DIFFERENT_CONFIRMED",
            "upstream:identity:v1",
            stamp(1),
        )
        with self.assertRaisesRegex(ValueError, "duplicate prefix field"):
            FrozenVisiblePrefix(
                as_of=stamp(1), _fields=(pending_fact, confirmed_fact)
            )

    def test_adapter_requires_generator_and_earliest_known_time_for_lineage_fields(self):
        self.require_adapter()
        with self.assertRaises(ValueError):
            PrefixFieldFact("association_state", "UNKNOWN_PENDING", "", stamp(0))
        with self.assertRaises(ValueError):
            PrefixFieldFact(
                "display_card_id", "CARD-A", "upstream:card:v1", "not-a-time"
            )


if __name__ == "__main__":
    unittest.main()
