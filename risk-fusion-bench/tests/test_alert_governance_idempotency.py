"""Synthetic characterization of observation, match, and action idempotency."""

from __future__ import annotations

import unittest

from rfb.research.alert_governance import AlertLedger, CandidateEvent


def observation(
    candidate_id: str,
    source_id: str,
    evidence_ref: str,
    *,
    observed_at: str = "2026-10-11T08:00:01Z",
) -> CandidateEvent:
    return CandidateEvent(
        candidate_id=candidate_id,
        event_time="2026-10-11T08:00:00Z",
        observed_at=observed_at,
        summary=f"Synthetic observation {candidate_id}",
        source_id=source_id,
        evidence_refs=(evidence_ref,),
        risk_flag="EXPOSURE",
    )


class IdempotencyLayerCharacterizationTests(unittest.TestCase):
    def test_exact_observation_replay_does_not_add_card_evidence_or_alert(self):
        ledger = AlertLedger()
        first = observation("obs-a", "device-a", "synthetic://obs/a")
        card = ledger.add_candidate(first, alerted_at="2026-10-11T08:00:03Z")
        alerts_before = ledger.alerts

        replayed_card = ledger.add_candidate(
            first, alerted_at="2026-10-11T09:00:00Z"
        )

        self.assertEqual(replayed_card.card_id, card.card_id)
        self.assertEqual(replayed_card.candidate_ids, ("obs-a",))
        self.assertEqual(ledger.alerts, alerts_before)
        self.assertEqual(len(ledger.cards), 1)
        self.assertEqual(ledger.alerts[0].evidence_refs, ("synthetic://obs/a",))
        self.assertEqual(ledger.alerts[0].observed_at, "2026-10-11T08:00:01Z")

    def test_replaying_old_candidate_id_with_new_observed_time_is_rejected_atomically(self):
        ledger = AlertLedger()
        original = observation("obs-a", "device-a", "synthetic://obs/a")
        ledger.add_candidate(original, alerted_at="2026-10-11T08:00:03Z")
        before = (ledger.cards, ledger.associations, ledger.alerts)
        refreshed = observation(
            "obs-a",
            "device-a",
            "synthetic://obs/a",
            observed_at="2026-10-11T09:00:00Z",
        )

        with self.assertRaisesRegex(ValueError, "different content"):
            ledger.add_candidate(refreshed, alerted_at="2026-10-11T09:00:01Z")

        self.assertEqual((ledger.cards, ledger.associations, ledger.alerts), before)
        self.assertEqual(ledger.alerts[0].observed_at, "2026-10-11T08:00:01Z")

    def test_complementary_observation_from_another_device_is_retained(self):
        ledger = AlertLedger()
        first = observation("obs-a", "device-a", "synthetic://obs/a")
        second = observation(
            "obs-b",
            "device-b",
            "synthetic://obs/b-complementary",
            observed_at="2026-10-11T08:00:02Z",
        )
        first_card = ledger.add_candidate(first, alerted_at="2026-10-11T08:00:03Z")
        second_card = ledger.add_candidate(second, alerted_at="2026-10-11T08:00:04Z")

        association = ledger.propose_association(
            "obs-a",
            "obs-b",
            at="2026-10-11T08:00:05Z",
            rationale="Synthetic observations may describe the same event.",
            evidence_refs=("synthetic://match/a-b",),
        )

        self.assertNotEqual(first_card.card_id, second_card.card_id)
        self.assertEqual(first_card.candidate_ids, ("obs-a",))
        self.assertEqual(second_card.candidate_ids, ("obs-b",))
        self.assertEqual(association.status, "PENDING")
        self.assertEqual(association.candidate_ids, ("obs-a", "obs-b"))
        candidate_alerts = [
            alert for alert in ledger.alerts if "CANDIDATE_RISK_FLAG" in alert.reason_codes
        ]
        self.assertEqual(len(candidate_alerts), 2)
        self.assertEqual(
            {alert.source_ids[0] for alert in candidate_alerts},
            {"device-a", "device-b"},
        )
        self.assertEqual(
            {alert.evidence_refs[0] for alert in candidate_alerts},
            {"synthetic://obs/a", "synthetic://obs/b-complementary"},
        )

    def test_same_match_replay_is_idempotent_but_overlapping_match_repeats_card_action(self):
        ledger = AlertLedger()
        cards = {}
        for index, candidate_id in enumerate(("obs-a", "obs-b", "obs-c"), start=3):
            cards[candidate_id] = ledger.add_candidate(
                observation(
                    candidate_id,
                    f"device-{candidate_id[-1]}",
                    f"synthetic://obs/{candidate_id}",
                ),
                alerted_at=f"2026-10-11T08:00:{index:02d}Z",
            )

        first_match = ledger.propose_association(
            "obs-a",
            "obs-b",
            at="2026-10-11T08:00:06Z",
            rationale="Synthetic overlap A-B.",
            evidence_refs=("synthetic://match/a-b",),
        )
        alerts_after_first_match = ledger.alerts
        replayed_match = ledger.propose_association(
            "obs-b",
            "obs-a",
            at="2026-10-11T08:00:08Z",
            rationale="Synthetic replay A-B.",
            evidence_refs=("synthetic://match/a-b",),
        )
        self.assertEqual(replayed_match.association_id, first_match.association_id)
        self.assertEqual(ledger.alerts, alerts_after_first_match)

        second_match = ledger.propose_association(
            "obs-a",
            "obs-c",
            at="2026-10-11T08:00:09Z",
            rationale="Synthetic overlap A-C.",
            evidence_refs=("synthetic://match/a-c",),
        )
        self.assertNotEqual(first_match.association_id, second_match.association_id)
        card_a_actions = [
            alert
            for alert in ledger.alerts
            if alert.card_id == cards["obs-a"].card_id
            and alert.reason_codes == ("IDENTITY_LINK_PENDING",)
        ]
        self.assertEqual(len(card_a_actions), 2)
        self.assertNotEqual(card_a_actions[0].evidence_refs, card_a_actions[1].evidence_refs)


if __name__ == "__main__":
    unittest.main()
