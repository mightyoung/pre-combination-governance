"""Synthetic acceptance tests for the isolated alert-governance path."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import unittest

from rfb.research.alert_governance import (
    AlertLedger,
    CandidateEvent,
    DeliveryStatus,
    RelationDecision,
    score_alert_content_completeness,
    score_alert_timeliness,
    score_event_confirmation_accuracy,
)


def candidate(
    candidate_id: str,
    *,
    summary: str | None = None,
    event_time: str = "2026-10-11T08:00:00Z",
    observed_at: str = "2026-10-11T08:00:01Z",
) -> CandidateEvent:
    return CandidateEvent(
        candidate_id=candidate_id,
        event_time=event_time,
        observed_at=observed_at,
        summary=summary or f"Synthetic risk candidate {candidate_id}",
        source_id=f"sensor-{candidate_id}",
        evidence_refs=(f"synthetic://evidence/{candidate_id}",),
        risk_flag="EXPOSURE",
    )


def propose_pair(
    ledger: AlertLedger,
    left: str,
    right: str,
    *,
    at: str = "2026-10-11T08:00:05Z",
):
    ledger.add_candidate(candidate(left), alerted_at="2026-10-11T08:00:03Z")
    ledger.add_candidate(candidate(right), alerted_at="2026-10-11T08:00:04Z")
    return ledger.propose_association(
        left,
        right,
        at=at,
        rationale="Synthetic identity conflict.",
    )


def propose_triangle(ledger: AlertLedger, prefix: str):
    candidate_ids = tuple(f"{prefix}-{suffix}" for suffix in ("a", "b", "c"))
    cards = {
        candidate_id: ledger.add_candidate(
            candidate(candidate_id),
            alerted_at=f"2026-10-11T08:00:0{index + 3}Z",
        )
        for index, candidate_id in enumerate(candidate_ids)
    }
    links = {}
    for name, left, right, second in (
        ("ab", candidate_ids[0], candidate_ids[1], 6),
        ("bc", candidate_ids[1], candidate_ids[2], 7),
        ("ac", candidate_ids[0], candidate_ids[2], 8),
    ):
        links[name] = ledger.propose_association(
            left,
            right,
            at=f"2026-10-11T08:00:{second:02d}Z",
            rationale=f"Synthetic overlapping relation {name.upper()}.",
        )
    return cards, links


def ledger_snapshot(ledger: AlertLedger):
    return ledger.cards, ledger.associations, ledger.alerts


def latest_alert_for(ledger: AlertLedger, card_id: str):
    return next(alert for alert in reversed(ledger.alerts) if alert.card_id == card_id)


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
        self.assertEqual(canonical.alert_level, "PRECAUTIONARY")
        self.assertEqual(ledger.alerts[-2].card_id, second.card_id)
        self.assertEqual(ledger.alerts[-2].verification_state, "MERGED_ALIAS")
        self.assertEqual(ledger.alerts[-1].card_id, first.card_id)
        self.assertEqual(ledger.alerts[-1].verification_state, "CONFIRMED_SAME_EVENT")
        self.assertEqual(
            ledger.alerts[-1].evidence_refs, ("synthetic://review/same-event",)
        )
        self.assertIn("待核实风险提醒", ledger.alerts[-1].visible_text)
        self.assertNotIn("已确认风险提醒", ledger.alerts[-1].visible_text)

    def test_evidence_based_risk_confirmation_advances_alert_stage_without_changing_identity(self):
        ledger = AlertLedger()
        card = ledger.add_candidate(
            candidate("risk-confirm-a"), alerted_at="2026-10-11T08:00:03Z"
        )

        confirmed = ledger.confirm_risk_alert(
            card.card_id,
            at="2026-10-11T08:00:05Z",
            rationale="Synthetic evidence confirms the risk condition.",
            evidence_refs=("synthetic://risk-confirm/evidence",),
        )

        self.assertEqual(confirmed.alert_level, "CONFIRMED")
        self.assertEqual(confirmed.status, "PENDING_VERIFICATION")
        self.assertEqual(ledger.alerts[-1].alert_level, "CONFIRMED")
        self.assertEqual(ledger.alerts[-1].verification_state, "PENDING_VERIFICATION")
        self.assertIn("已确认风险提醒", ledger.alerts[-1].visible_text)

    def test_risk_confirmation_requires_evidence_and_does_not_downgrade_escalation(self):
        ledger = AlertLedger()
        card = ledger.add_candidate(
            candidate("risk-confirm-b"), alerted_at="2026-10-11T08:00:03Z"
        )
        before = ledger_snapshot(ledger)

        with self.assertRaisesRegex(ValueError, "evidence"):
            ledger.confirm_risk_alert(
                card.card_id,
                at="2026-10-11T08:00:05Z",
                rationale="Missing evidence should be rejected.",
                evidence_refs=(),
            )

        self.assertEqual(ledger_snapshot(ledger), before)
        ledger.escalate_card(
            card.card_id,
            at="2026-10-11T08:00:06Z",
            rationale="Synthetic evidence supports escalation.",
            evidence_refs=("synthetic://risk-confirm/escalation",),
        )
        confirmed = ledger.confirm_risk_alert(
            card.card_id,
            at="2026-10-11T08:00:07Z",
            rationale="Synthetic evidence also confirms the risk condition.",
            evidence_refs=("synthetic://risk-confirm/confirmation",),
        )

        self.assertEqual(confirmed.alert_level, "ESCALATED")
        self.assertEqual(ledger.alerts[-1].alert_level, "ESCALATED")
        self.assertEqual(confirmed.status, "PENDING_VERIFICATION")


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
        self.assertEqual(ledger.card_for("candidate-a").alert_level, "PRECAUTIONARY")
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
        ledger = AlertLedger()
        first = propose_pair(ledger, "pair-1-left", "pair-1-right")
        second = propose_pair(ledger, "pair-2-left", "pair-2-right")
        third = propose_pair(ledger, "pair-3-left", "pair-3-right")
        ledger.resolve_association(
            first.association_id,
            decision=RelationDecision.SAME_EVENT,
            at="2026-10-11T08:00:10Z",
            evidence_refs=("synthetic://truth/pair-1",),
        )
        ledger.resolve_association(
            second.association_id,
            decision=RelationDecision.SAME_EVENT,
            at="2026-10-11T08:00:10Z",
            evidence_refs=("synthetic://truth/pair-2",),
        )

        result = score_event_confirmation_accuracy(
            ledger,
            {
                first.association_id: "SAME_EVENT",
                second.association_id: "DISTINCT_EVENTS",
                third.association_id: "SAME_EVENT",
            },
        )

        self.assertEqual(result["pair_count"], 3)
        self.assertEqual(result["decided_pair_count"], 2)
        self.assertEqual(result["undecided_pair_count"], 1)
        self.assertEqual(result["correct_decisions"], 1)
        self.assertEqual(result["accuracy"], 0.5)

    def test_event_confirmation_accuracy_rejects_truth_for_unknown_ledger_pair(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            score_event_confirmation_accuracy(
                AlertLedger(), {"not-in-ledger": "SAME_EVENT"}
            )

    def test_distinct_decision_conflicting_with_same_event_path_is_rejected_atomically(self):
        ledger = AlertLedger()
        cards, links = propose_triangle(ledger, "conflict-after-same")
        for name, second in (("ab", 10), ("bc", 11)):
            ledger.resolve_association(
                links[name].association_id,
                decision=RelationDecision.SAME_EVENT,
                at=f"2026-10-11T08:00:{second:02d}Z",
                evidence_refs=(f"synthetic://conflict/{name}",),
            )
        before = ledger_snapshot(ledger)

        with self.assertRaisesRegex(ValueError, "conflict|connected|same-event"):
            ledger.resolve_association(
                links["ac"].association_id,
                decision=RelationDecision.DISTINCT_EVENTS,
                at="2026-10-11T08:00:12Z",
                evidence_refs=("synthetic://conflict/ac-distinct",),
            )

        self.assertEqual(ledger_snapshot(ledger), before)
        self.assertEqual(ledger.association(links["ac"].association_id).status, "PENDING")
        self.assertEqual(
            {ledger.card_for(candidate_id).card_id for candidate_id in cards},
            {cards["conflict-after-same-a"].card_id},
        )
        score = score_event_confirmation_accuracy(
            ledger, {links["ac"].association_id: "DISTINCT_EVENTS"}
        )
        self.assertEqual(score["pairs"][0]["predicted_relation"], "PENDING")
        self.assertEqual(score["pairs"][0]["component_relation"], "SAME_EVENT")
        self.assertEqual(score["pairs"][0]["status"], "UNDECIDED")

    def test_same_event_decision_cannot_bridge_an_existing_distinct_relation(self):
        ledger = AlertLedger()
        cards, links = propose_triangle(ledger, "conflict-before-same")
        ledger.resolve_association(
            links["ac"].association_id,
            decision=RelationDecision.DISTINCT_EVENTS,
            at="2026-10-11T08:00:10Z",
            evidence_refs=("synthetic://conflict/ac-distinct",),
        )
        ledger.resolve_association(
            links["ab"].association_id,
            decision=RelationDecision.SAME_EVENT,
            at="2026-10-11T08:00:11Z",
            evidence_refs=("synthetic://conflict/ab-same",),
        )
        before = ledger_snapshot(ledger)

        with self.assertRaisesRegex(ValueError, "conflict|connected|distinct"):
            ledger.resolve_association(
                links["bc"].association_id,
                decision=RelationDecision.SAME_EVENT,
                at="2026-10-11T08:00:12Z",
                evidence_refs=("synthetic://conflict/bc-same",),
            )

        self.assertEqual(ledger_snapshot(ledger), before)
        self.assertEqual(ledger.association(links["bc"].association_id).status, "PENDING")
        self.assertEqual(
            ledger.card_for("conflict-before-same-a").card_id,
            ledger.card_for("conflict-before-same-b").card_id,
        )
        self.assertNotEqual(
            ledger.card_for("conflict-before-same-b").card_id,
            ledger.card_for("conflict-before-same-c").card_id,
        )
        score = score_event_confirmation_accuracy(
            ledger, {links["ac"].association_id: "DISTINCT_EVENTS"}
        )
        self.assertEqual(score["pairs"][0]["predicted_relation"], "DISTINCT_EVENTS")
        self.assertEqual(score["pairs"][0]["component_relation"], "DISTINCT_EVENTS")
        self.assertEqual(score["pairs"][0]["status"], "CORRECT")

    def test_triangle_edge_split_is_rejected_when_other_paths_keep_it_connected(self):
        ledger = AlertLedger()
        cards, links = propose_triangle(ledger, "triangle-split")
        for name, second in (("ab", 10), ("bc", 11), ("ac", 12)):
            ledger.resolve_association(
                links[name].association_id,
                decision=RelationDecision.SAME_EVENT,
                at=f"2026-10-11T08:00:{second:02d}Z",
                evidence_refs=(f"synthetic://triangle/{name}",),
            )
        before = ledger_snapshot(ledger)

        with self.assertRaisesRegex(ValueError, "conflict|connected|path"):
            ledger.split_association(
                links["ab"].association_id,
                at="2026-10-11T08:00:13Z",
                rationale="Synthetic evidence disputes AB in a closed triangle.",
                evidence_refs=("synthetic://triangle/split-ab",),
            )

        self.assertEqual(ledger_snapshot(ledger), before)
        self.assertEqual(
            ledger.association(links["ab"].association_id).status,
            "CONFIRMED_SAME_EVENT",
        )
        self.assertEqual(
            {ledger.card_for(candidate_id).card_id for candidate_id in cards},
            {cards["triangle-split-a"].card_id},
        )
        score = score_event_confirmation_accuracy(
            ledger, {links["ab"].association_id: "SAME_EVENT"}
        )
        self.assertEqual(score["pairs"][0]["predicted_relation"], "SAME_EVENT")
        self.assertEqual(score["pairs"][0]["component_relation"], "SAME_EVENT")

    def test_overlapping_same_event_links_and_old_edge_split_preserve_all_members(self):
        ledger = AlertLedger()
        cards = {
            key: ledger.add_candidate(
                candidate(key),
                alerted_at=f"2026-10-11T08:00:0{index + 3}Z",
            )
            for index, key in enumerate(("overlap-a", "overlap-b", "overlap-c"))
        }
        ab = ledger.propose_association(
            "overlap-a",
            "overlap-b",
            at="2026-10-11T08:00:06Z",
            rationale="Synthetic overlapping link AB.",
        )
        bc = ledger.propose_association(
            "overlap-b",
            "overlap-c",
            at="2026-10-11T08:00:07Z",
            rationale="Synthetic overlapping link BC.",
        )
        ledger.resolve_association(
            ab.association_id,
            decision=RelationDecision.SAME_EVENT,
            at="2026-10-11T08:00:10Z",
            evidence_refs=("synthetic://overlap/ab",),
        )
        ledger.resolve_association(
            bc.association_id,
            decision=RelationDecision.SAME_EVENT,
            at="2026-10-11T08:00:11Z",
            evidence_refs=("synthetic://overlap/bc",),
        )

        self.assertEqual(
            {ledger.card_for(key).card_id for key in cards},
            {cards["overlap-a"].card_id},
        )
        self.assertEqual(
            ledger.card_for("overlap-a").candidate_ids,
            ("overlap-a", "overlap-b", "overlap-c"),
        )
        split = ledger.split_association(
            ab.association_id,
            at="2026-10-11T08:00:12Z",
            rationale="Synthetic later evidence splits AB; BC remains confirmed.",
            evidence_refs=("synthetic://overlap/split-ab",),
        )

        self.assertEqual(split.status, "SPLIT_TO_DISTINCT")
        self.assertEqual(ledger.association(bc.association_id).status, "CONFIRMED_SAME_EVENT")
        self.assertEqual(ledger.card_for("overlap-a").card_id, cards["overlap-a"].card_id)
        self.assertEqual(ledger.card_for("overlap-b").card_id, cards["overlap-b"].card_id)
        self.assertEqual(ledger.card_for("overlap-c").card_id, cards["overlap-b"].card_id)
        self.assertEqual(
            ledger.association(bc.association_id).canonical_card_id,
            cards["overlap-b"].card_id,
        )
        self.assertIsNone(ledger.association(ab.association_id).canonical_card_id)
        active_members = [
            member
            for card in ledger.cards
            if card.merged_into_card_id is None
            for member in card.candidate_ids
        ]
        self.assertCountEqual(active_members, ["overlap-a", "overlap-b", "overlap-c"])
        for card in ledger.cards:
            latest = latest_alert_for(ledger, card.card_id)
            self.assertGreaterEqual(
                datetime.fromisoformat(card.updated_at.replace("Z", "+00:00")),
                datetime.fromisoformat(latest.alerted_at.replace("Z", "+00:00")),
            )

    def test_non_monotonic_resolve_is_rejected_atomically_after_escalation(self):
        ledger = AlertLedger()
        association = propose_pair(ledger, "time-a", "time-b")
        card_a = ledger.card_for("time-a")
        ledger.escalate_card(
            card_a.card_id,
            at="2026-10-11T08:00:20Z",
            rationale="Synthetic escalation after review.",
            evidence_refs=("synthetic://time/escalation",),
        )
        before = ledger_snapshot(ledger)

        with self.assertRaisesRegex(ValueError, "time|precede|monotonic"):
            ledger.resolve_association(
                association.association_id,
                decision=RelationDecision.SAME_EVENT,
                at="2026-10-11T08:00:10Z",
                evidence_refs=("synthetic://time/resolve",),
            )

        self.assertEqual(ledger_snapshot(ledger), before)

    def test_non_monotonic_split_is_rejected_atomically_after_escalation(self):
        ledger = AlertLedger()
        association = propose_pair(ledger, "split-time-a", "split-time-b")
        ledger.resolve_association(
            association.association_id,
            decision=RelationDecision.SAME_EVENT,
            at="2026-10-11T08:00:10Z",
            evidence_refs=("synthetic://time/same",),
        )
        canonical = ledger.card_for("split-time-a")
        ledger.escalate_card(
            canonical.card_id,
            at="2026-10-11T08:00:20Z",
            rationale="Synthetic escalation after merge.",
            evidence_refs=("synthetic://time/escalation",),
        )
        before = ledger_snapshot(ledger)

        with self.assertRaisesRegex(ValueError, "time|precede|monotonic"):
            ledger.split_association(
                association.association_id,
                at="2026-10-11T08:00:15Z",
                rationale="Synthetic earlier split.",
                evidence_refs=("synthetic://time/split",),
            )

        self.assertEqual(ledger_snapshot(ledger), before)

    def test_identity_updates_do_not_downgrade_an_escalated_alert(self):
        ledger = AlertLedger()
        card = ledger.add_candidate(candidate("stage-a"), alerted_at="2026-10-11T08:00:03Z")
        ledger.add_candidate(candidate("stage-b"), alerted_at="2026-10-11T08:00:04Z")
        ledger.escalate_card(
            card.card_id,
            at="2026-10-11T08:00:05Z",
            rationale="Synthetic escalation before identity review.",
            evidence_refs=("synthetic://stage/escalation",),
        )
        association = ledger.propose_association(
            "stage-a",
            "stage-b",
            at="2026-10-11T08:00:06Z",
            rationale="Synthetic identity review.",
        )
        self.assertEqual(ledger.card_for("stage-a").alert_level, "ESCALATED")
        self.assertEqual(ledger.card_for("stage-a").status, "PENDING_VERIFICATION")

        ledger.resolve_association(
            association.association_id,
            decision=RelationDecision.SAME_EVENT,
            at="2026-10-11T08:00:07Z",
            evidence_refs=("synthetic://stage/same-event",),
        )
        self.assertEqual(ledger.card_for("stage-a").alert_level, "ESCALATED")
        ledger.split_association(
            association.association_id,
            at="2026-10-11T08:00:08Z",
            rationale="Synthetic evidence later separates the events.",
            evidence_refs=("synthetic://stage/split",),
        )
        self.assertEqual(ledger.card_for("stage-a").alert_level, "ESCALATED")

    def test_multilevel_alias_resolution_and_escalation_reach_final_canonical_card(self):
        ledger = AlertLedger()
        card_c = ledger.add_candidate(candidate("alias-c"), alerted_at="2026-10-11T08:00:03Z")
        ledger.add_candidate(candidate("alias-a"), alerted_at="2026-10-11T08:00:04Z")
        card_b = ledger.add_candidate(candidate("alias-b"), alerted_at="2026-10-11T08:00:05Z")
        ab = ledger.propose_association(
            "alias-a", "alias-b", at="2026-10-11T08:00:06Z", rationale="Synthetic AB."
        )
        ledger.resolve_association(
            ab.association_id,
            decision=RelationDecision.SAME_EVENT,
            at="2026-10-11T08:00:08Z",
            evidence_refs=("synthetic://alias/ab",),
        )
        ac = ledger.propose_association(
            "alias-a", "alias-c", at="2026-10-11T08:00:09Z", rationale="Synthetic AC."
        )
        ledger.resolve_association(
            ac.association_id,
            decision=RelationDecision.SAME_EVENT,
            at="2026-10-11T08:00:10Z",
            evidence_refs=("synthetic://alias/ac",),
        )

        # Reproduce a legacy alias chain left by sequential pairwise merging.
        ledger._cards[card_b.card_id] = replace(
            ledger.get_card(card_b.card_id), merged_into_card_id=ledger.card_for("alias-a").card_id
        )

        self.assertEqual(ledger.card_for("alias-b").card_id, card_c.card_id)
        escalated = ledger.escalate_card(
            card_b.card_id,
            at="2026-10-11T08:00:11Z",
            rationale="Synthetic escalation through an alias chain.",
            evidence_refs=("synthetic://alias/escalation",),
        )
        self.assertEqual(escalated.card_id, card_c.card_id)
        self.assertEqual(ledger.alerts[-1].card_id, card_c.card_id)

    def test_alias_cycle_fails_closed_in_canonical_resolver(self):
        ledger = AlertLedger()
        card_a = ledger.add_candidate(candidate("cycle-a"), alerted_at="2026-10-11T08:00:03Z")
        card_b = ledger.add_candidate(candidate("cycle-b"), alerted_at="2026-10-11T08:00:04Z")
        ledger._cards[card_a.card_id] = replace(
            ledger.get_card(card_a.card_id), merged_into_card_id=card_b.card_id
        )
        ledger._cards[card_b.card_id] = replace(
            ledger.get_card(card_b.card_id), merged_into_card_id=card_a.card_id
        )

        with self.assertRaisesRegex(ValueError, "cycle"):
            ledger.card_for("cycle-a")

    def test_microsecond_timestamps_are_ordered_by_time_not_text(self):
        ledger = AlertLedger()
        ledger.add_candidate(
            candidate(
                "micro-a",
                event_time="2026-10-11T08:00:00Z",
                observed_at="2026-10-11T08:00:00Z",
            ),
            alerted_at="2026-10-11T08:00:00.100000Z",
        )
        ledger.add_candidate(
            candidate(
                "micro-b",
                event_time="2026-10-11T08:00:00.500000Z",
                observed_at="2026-10-11T08:00:00.500000Z",
            ),
            alerted_at="2026-10-11T08:00:00.600000Z",
        )
        association = ledger.propose_association(
            "micro-a",
            "micro-b",
            at="2026-10-11T08:00:00.700000Z",
            rationale="Synthetic microsecond ordering.",
        )

        ledger.resolve_association(
            association.association_id,
            decision=RelationDecision.SAME_EVENT,
            at="2026-10-11T08:00:01Z",
            evidence_refs=("synthetic://microseconds/same",),
        )

        self.assertEqual(ledger.alerts[-1].event_time, "2026-10-11T08:00:00Z")
        self.assertEqual(ledger.alerts[-1].observed_at, "2026-10-11T08:00:00Z")

    def test_content_completeness_reports_each_of_12_missing_fields(self):
        ledger = AlertLedger()
        ledger.add_candidate(candidate("content-a"), alerted_at="2026-10-11T08:00:03Z")
        alert = ledger.alerts[-1]
        missing_values = {
            "card_id": "",
            "source_ids": (),
            "alert_level": "",
            "verification_state": "",
            "visible_text": "",
            "rationale": "",
            "reason_codes": (),
            "evidence_refs": (),
            "event_time": "",
            "observed_at": "",
            "alerted_at": "",
            "delivery_status": None,
        }

        for field, empty_value in missing_values.items():
            with self.subTest(field=field):
                result = score_alert_content_completeness(
                    replace(alert, **{field: empty_value})
                )
                self.assertFalse(result["complete"])
                self.assertEqual(result["missing_fields"], [field])
                self.assertEqual(result["complete_field_count"], 11)

    def test_same_ledger_candidate_replay_is_idempotent(self):
        ledger = AlertLedger()
        first = ledger.add_candidate(
            candidate("replay-a"), alerted_at="2026-10-11T08:00:03Z"
        )
        alerts_before = ledger.alerts

        replayed = ledger.add_candidate(
            candidate("replay-a"), alerted_at="2026-10-11T08:00:04Z"
        )

        self.assertEqual(replayed.card_id, first.card_id)
        self.assertEqual(ledger.alerts, alerts_before)


if __name__ == "__main__":
    unittest.main()
