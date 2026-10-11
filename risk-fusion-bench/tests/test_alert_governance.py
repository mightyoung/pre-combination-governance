"""Synthetic acceptance tests for the isolated alert-governance path."""

from __future__ import annotations

import unittest

from rfb.research.alert_governance import (
    AlertLedger,
    CandidateEvent,
    DeliveryStatus,
    EventConfirmationResult,
    RelationDecision,
    score_alert_content_completeness,
    score_alert_timeliness,
    score_event_confirmation_accuracy,
)


def candidate(candidate_id: str, *, summary: str | None = None) -> CandidateEvent:
    return CandidateEvent(
        candidate_id=candidate_id,
        event_time="2026-10-11T08:00:00Z",
        observed_at="2026-10-11T08:00:01Z",
        summary=summary or f"Synthetic risk candidate {candidate_id}",
        source_id=f"sensor-{candidate_id}",
        evidence_refs=(f"synthetic://evidence/{candidate_id}",),
        risk_flag="EXPOSURE",
    )


class AlertGovernanceTests(unittest.TestCase):
    def test_candidate_gets_stable_card_and_explicit_simulated_first_alert(self):
        ledger = AlertLedger(delivery_status=DeliveryStatus.SIMULATED)

        card = ledger.add_candidate(
            candidate("candidate-a"), alerted_at="2026-10-11T08:00:03Z"
        )
        alert = ledger.alerts[-1]
        replay_card = AlertLedger(delivery_status=DeliveryStatus.SIMULATED).add_candidate(
            candidate("candidate-a"), alerted_at="2026-10-11T08:00:03Z"
        )

        self.assertEqual(card.card_id, replay_card.card_id)
        self.assertEqual(card.candidate_ids, ("candidate-a",))
        self.assertEqual(alert.card_id, card.card_id)
        self.assertEqual(alert.alert_level, "PRECAUTIONARY")
        self.assertIn("待核实", alert.visible_text)
        self.assertIn("EXPOSURE", alert.visible_text)
        self.assertEqual(alert.evidence_refs, ("synthetic://evidence/candidate-a",))
        self.assertEqual(alert.event_time, "2026-10-11T08:00:00Z")
        self.assertEqual(alert.observed_at, "2026-10-11T08:00:01Z")
        self.assertEqual(alert.alerted_at, "2026-10-11T08:00:03Z")
        self.assertEqual(alert.source_ids, ("sensor-candidate-a",))
        self.assertIn("事件时间=2026-10-11T08:00:00Z", alert.visible_text)
        self.assertIn("来源=sensor-candidate-a", alert.visible_text)
        self.assertIn("提醒生成=2026-10-11T08:00:03Z", alert.visible_text)
        self.assertIn("送达时间=未记录", alert.visible_text)
        self.assertIs(alert.delivery_status, DeliveryStatus.SIMULATED)
        self.assertIsNone(alert.delivered_at)


    def test_pending_identity_association_keeps_two_independent_cards(self):
        ledger = AlertLedger()
        first = ledger.add_candidate(
            candidate("candidate-a"), alerted_at="2026-10-11T08:00:03Z"
        )
        second = ledger.add_candidate(
            candidate("candidate-b"), alerted_at="2026-10-11T08:00:04Z"
        )

        association = ledger.propose_association(
            "candidate-a",
            "candidate-b",
            at="2026-10-11T08:00:05Z",
            rationale="Synthetic identity conflict; review before linking.",
        )

        self.assertEqual(association.status, "PENDING")
        self.assertEqual(ledger.card_for("candidate-a").card_id, first.card_id)
        self.assertEqual(ledger.card_for("candidate-b").card_id, second.card_id)
        self.assertNotEqual(first.card_id, second.card_id)
        self.assertEqual(ledger.get_card(first.card_id).candidate_ids, ("candidate-a",))
        self.assertEqual(ledger.get_card(second.card_id).candidate_ids, ("candidate-b",))
        self.assertTrue(
            all(alert.delivery_status is DeliveryStatus.SIMULATED for alert in ledger.alerts)
        )


    def test_confirmed_same_event_updates_canonical_card_and_retains_alias_id(self):
        ledger = AlertLedger()
        first = ledger.add_candidate(
            candidate("candidate-a"), alerted_at="2026-10-11T08:00:03Z"
        )
        second = ledger.add_candidate(
            candidate("candidate-b"), alerted_at="2026-10-11T08:00:04Z"
        )
        association = ledger.propose_association(
            "candidate-a",
            "candidate-b",
            at="2026-10-11T08:00:05Z",
            rationale="Synthetic identity conflict.",
        )

        resolved = ledger.resolve_association(
            association.association_id,
            decision=RelationDecision.SAME_EVENT,
            at="2026-10-11T08:00:10Z",
            evidence_refs=("synthetic://review/same-event",),
        )

        canonical = ledger.card_for("candidate-a")
        self.assertEqual(resolved.status, "CONFIRMED_SAME_EVENT")
        self.assertEqual(canonical.card_id, first.card_id)
        self.assertEqual(ledger.card_for("candidate-b").card_id, first.card_id)
        self.assertEqual(canonical.candidate_ids, ("candidate-a", "candidate-b"))
        self.assertEqual(ledger.get_card(second.card_id).merged_into_card_id, first.card_id)
        self.assertEqual(ledger.get_card(second.card_id).card_id, second.card_id)
        self.assertEqual(ledger.alerts[-2].card_id, second.card_id)
        self.assertEqual(ledger.alerts[-2].verification_state, "MERGED_ALIAS")
        self.assertEqual(ledger.alerts[-1].card_id, first.card_id)
        self.assertEqual(
            ledger.alerts[-1].evidence_refs, ("synthetic://review/same-event",)
        )


    def test_evidence_backed_split_restores_original_stable_card_ids(self):
        ledger = AlertLedger()
        first = ledger.add_candidate(
            candidate("candidate-a"), alerted_at="2026-10-11T08:00:03Z"
        )
        second = ledger.add_candidate(
            candidate("candidate-b"), alerted_at="2026-10-11T08:00:04Z"
        )
        association = ledger.propose_association(
            "candidate-a",
            "candidate-b",
            at="2026-10-11T08:00:05Z",
            rationale="Synthetic identity conflict.",
        )
        ledger.resolve_association(
            association.association_id,
            decision=RelationDecision.SAME_EVENT,
            at="2026-10-11T08:00:10Z",
            evidence_refs=("synthetic://review/initial-identity",),
        )

        split = ledger.split_association(
            association.association_id,
            at="2026-10-11T08:00:20Z",
            rationale="New synthetic evidence contradicts the prior link.",
            evidence_refs=("synthetic://review/split",),
        )

        self.assertEqual(split.status, "SPLIT_TO_DISTINCT")
        self.assertEqual(ledger.card_for("candidate-a").card_id, first.card_id)
        self.assertEqual(ledger.card_for("candidate-b").card_id, second.card_id)
        self.assertEqual(ledger.get_card(first.card_id).candidate_ids, ("candidate-a",))
        self.assertEqual(ledger.get_card(second.card_id).candidate_ids, ("candidate-b",))
        self.assertEqual(
            [item.to_status for item in split.history],
            ["PENDING", "CONFIRMED_SAME_EVENT", "SPLIT_TO_DISTINCT"],
        )


    def test_confirmed_distinct_decision_keeps_both_cards_separate(self):
        ledger = AlertLedger()
        first = ledger.add_candidate(
            candidate("candidate-a"), alerted_at="2026-10-11T08:00:03Z"
        )
        second = ledger.add_candidate(
            candidate("candidate-b"), alerted_at="2026-10-11T08:00:04Z"
        )
        association = ledger.propose_association(
            "candidate-a",
            "candidate-b",
            at="2026-10-11T08:00:05Z",
            rationale="Synthetic identity conflict.",
        )

        result = ledger.resolve_association(
            association.association_id,
            decision=RelationDecision.DISTINCT_EVENTS,
            at="2026-10-11T08:00:10Z",
            evidence_refs=("synthetic://review/distinct-events",),
        )

        self.assertEqual(result.status, "CONFIRMED_DISTINCT")
        self.assertEqual(ledger.card_for("candidate-a").card_id, first.card_id)
        self.assertEqual(ledger.card_for("candidate-b").card_id, second.card_id)
        self.assertIsNone(ledger.get_card(first.card_id).merged_into_card_id)
        self.assertIsNone(ledger.get_card(second.card_id).merged_into_card_id)


    def test_association_cannot_be_confirmed_without_evidence_references(self):
        ledger = AlertLedger()
        ledger.add_candidate(candidate("candidate-a"), alerted_at="2026-10-11T08:00:03Z")
        ledger.add_candidate(candidate("candidate-b"), alerted_at="2026-10-11T08:00:04Z")
        association = ledger.propose_association(
            "candidate-a",
            "candidate-b",
            at="2026-10-11T08:00:05Z",
            rationale="Synthetic identity conflict.",
        )

        with self.assertRaisesRegex(ValueError, "evidence"):
            ledger.resolve_association(
                association.association_id,
                decision=RelationDecision.SAME_EVENT,
                at="2026-10-11T08:00:10Z",
                evidence_refs=(),
            )
        self.assertEqual(ledger.association(association.association_id).status, "PENDING")
        self.assertNotEqual(
            ledger.card_for("candidate-a").card_id,
            ledger.card_for("candidate-b").card_id,
        )


    def test_timeliness_reports_emission_but_refuses_to_infer_delivery(self):
        ledger = AlertLedger(delivery_status=DeliveryStatus.SIMULATED)
        ledger.add_candidate(candidate("candidate-a"), alerted_at="2026-10-11T08:00:03Z")

        result = score_alert_timeliness(ledger.alerts[0], deadline_seconds=30)

        self.assertEqual(result["emission_latency_seconds"], 2.0)
        self.assertIsNone(result["delivery_latency_seconds"])
        self.assertEqual(result["delivery_status"], "SIMULATED")
        self.assertEqual(result["emission_timeliness_status"], "TIMELY")
        self.assertEqual(
            result["delivery_timeliness_status"], "UNSCORABLE_NO_DELIVERY_RECEIPT"
        )


    def test_content_completeness_is_separate_from_delivery_and_confirmation(self):
        ledger = AlertLedger(delivery_status=DeliveryStatus.NOT_DELIVERED)
        ledger.add_candidate(candidate("candidate-a"), alerted_at="2026-10-11T08:00:03Z")

        result = score_alert_content_completeness(ledger.alerts[0])

        self.assertIs(result["complete"], True)
        self.assertEqual(result["missing_fields"], [])
        self.assertGreaterEqual(result["required_field_count"], 8)
        self.assertEqual(result["delivery_status"], "NOT_DELIVERED")


    def test_escalation_requires_evidence_and_keeps_delivery_unconfirmed(self):
        ledger = AlertLedger(delivery_status=DeliveryStatus.NOT_DELIVERED)
        card = ledger.add_candidate(
            candidate("candidate-a"), alerted_at="2026-10-11T08:00:03Z"
        )

        escalated = ledger.escalate_card(
            card.card_id,
            at="2026-10-11T08:00:07Z",
            rationale="Synthetic review confirms a higher response priority.",
            evidence_refs=("synthetic://review/escalation",),
        )

        self.assertEqual(escalated.card_id, card.card_id)
        self.assertEqual(escalated.alert_level, "ESCALATED")
        self.assertEqual(ledger.alerts[-1].delivery_status, DeliveryStatus.NOT_DELIVERED)
        self.assertIsNone(ledger.alerts[-1].delivered_at)


    def test_event_confirmation_accuracy_excludes_pending_pairs_from_accuracy(self):
        result = score_event_confirmation_accuracy(
            (
                EventConfirmationResult("pair-1", "SAME_EVENT", "SAME_EVENT"),
                EventConfirmationResult("pair-2", "SAME_EVENT", "DISTINCT_EVENTS"),
                EventConfirmationResult("pair-3", "PENDING", "SAME_EVENT"),
            )
        )

        self.assertEqual(result["pair_count"], 3)
        self.assertEqual(result["decided_pair_count"], 2)
        self.assertEqual(result["undecided_pair_count"], 1)
        self.assertEqual(result["correct_decisions"], 1)
        self.assertEqual(result["accuracy"], 0.5)


if __name__ == "__main__":
    unittest.main()
