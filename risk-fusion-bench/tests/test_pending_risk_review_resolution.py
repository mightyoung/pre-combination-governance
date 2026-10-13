"""Offline risk-review contract tests independent of event identity."""

from __future__ import annotations

import unittest

from rfb.research.event_card_resolution import (
    PendingAssociation,
    resolve_pending_association,
)
from rfb.research.pending_risk_review_resolution import (
    RiskReviewAssessment,
    resolve_pending_risk_review,
)


BASE = "2026-10-13T08:00:00Z"


def stamp(seconds: int) -> str:
    from datetime import datetime, timedelta, timezone

    value = datetime.fromisoformat(BASE.replace("Z", "+00:00")) + timedelta(
        seconds=seconds
    )
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def synthetic_pending_review(*, current_grade: str = "WARNING") -> dict[str, object]:
    return {
        "review_id": "SYNTH-REVIEW-001",
        "display_card_id": "SYNTH-CARD-A",
        "source_intent_id": "SYNTH-UNVERSIONED-HIGH-RISK",
        "risk_signal_grade": "CRITICAL",
        "current_versioned_risk_grade": current_grade,
        "status": "PENDING_VERIFICATION",
        "confirmed": False,
        "received_at_processing_time": stamp(1),
        "evidence_refs": ["synthetic://risk-review/signal"],
        "delivery_status": "NOT_DELIVERED",
    }


class PendingRiskReviewResolutionTests(unittest.TestCase):
    def test_insufficient_evidence_keeps_review_pending_and_identity_unknown(self) -> None:
        record = synthetic_pending_review()
        decision = resolve_pending_risk_review(
            record,
            association_state="UNKNOWN_PENDING",
            assessment=RiskReviewAssessment.INSUFFICIENT_EVIDENCE,
            reviewed_at=stamp(2),
        )

        self.assertEqual(decision.review_status, "PENDING_VERIFICATION")
        self.assertEqual(decision.outcome_code, "INSUFFICIENT_EVIDENCE_RETAINED")
        self.assertEqual(decision.association_state_before, "UNKNOWN_PENDING")
        self.assertEqual(decision.association_state_after, "UNKNOWN_PENDING")
        self.assertEqual(decision.identity_resolution, "NOT_PERFORMED")
        self.assertFalse(decision.notification_created)
        self.assertEqual(decision.delivery_status, "NOT_DELIVERED")
        self.assertEqual(record["status"], "PENDING_VERIFICATION")

    def test_verified_risk_upgrade_does_not_confirm_event_identity(self) -> None:
        decision = resolve_pending_risk_review(
            synthetic_pending_review(current_grade="WARNING"),
            association_state="UNKNOWN_PENDING",
            assessment="CONFIRMED",
            reviewed_at=stamp(4),
            evidence_known_at=stamp(3),
            evidence_refs=("synthetic://risk-review/adjudication",),
            verified_risk_grade="CRITICAL",
        )

        self.assertEqual(decision.outcome_code, "RISK_UPGRADE_CONFIRMED")
        self.assertEqual(decision.risk_grade_transition, "UPGRADE")
        self.assertEqual(decision.association_state_after, "UNKNOWN_PENDING")
        self.assertEqual(decision.identity_resolution, "NOT_PERFORMED")
        self.assertFalse(decision.notification_created)

    def test_confirmed_signal_with_unknown_baseline_is_not_called_an_upgrade(self) -> None:
        decision = resolve_pending_risk_review(
            synthetic_pending_review(current_grade="UNKNOWN"),
            association_state="CONFLICT_PENDING",
            assessment="CONFIRMED",
            reviewed_at=stamp(4),
            evidence_known_at=stamp(3),
            evidence_refs=("synthetic://risk-review/adjudication",),
            verified_risk_grade="CRITICAL",
        )

        self.assertEqual(decision.outcome_code, "RISK_SIGNAL_CONFIRMED_BASELINE_UNKNOWN")
        self.assertEqual(decision.risk_grade_transition, "UNCOMPARABLE_BASELINE_UNKNOWN")
        self.assertEqual(decision.association_state_after, "CONFLICT_PENDING")

    def test_refuted_risk_signal_keeps_association_state_unchanged(self) -> None:
        decision = resolve_pending_risk_review(
            synthetic_pending_review(),
            association_state="UNKNOWN_PENDING",
            assessment="REFUTED",
            reviewed_at=stamp(4),
            evidence_known_at=stamp(3),
            evidence_refs=("synthetic://risk-review/refutation",),
        )

        self.assertEqual(decision.review_status, "RESOLVED_REFUTED")
        self.assertEqual(decision.outcome_code, "RISK_SIGNAL_REFUTED")
        self.assertEqual(decision.association_state_after, "UNKNOWN_PENDING")
        self.assertEqual(decision.identity_resolution, "NOT_PERFORMED")

    def test_risk_review_and_later_different_split_are_separate_transitions(self) -> None:
        pending_review = synthetic_pending_review()
        risk_decision = resolve_pending_risk_review(
            pending_review,
            association_state="UNKNOWN_PENDING",
            assessment="CONFIRMED",
            reviewed_at=stamp(4),
            evidence_known_at=stamp(3),
            evidence_refs=("synthetic://risk-review/adjudication",),
            verified_risk_grade="CRITICAL",
        )
        pending_association = PendingAssociation(
            association_id="SYNTH-ASSOCIATION-A-B",
            display_card_id="SYNTH-CARD-A",
            candidate_episode_ids=("SYNTH-EPISODE-A", "SYNTH-EPISODE-B"),
            association_state="UNKNOWN_PENDING",
            pending_at=stamp(1),
            evidence_refs=("synthetic://association/pending",),
        )
        identity_resolution = resolve_pending_association(
            pending_association,
            association_state="DIFFERENT_CONFIRMED",
            identity_evidence_known_at=stamp(5),
            resolved_at=stamp(6),
            evidence_refs=("synthetic://association/adjudication",),
            new_display_card_id="SYNTH-CARD-B",
        )

        self.assertEqual(risk_decision.association_state_after, "UNKNOWN_PENDING")
        self.assertEqual(identity_resolution.association_state, "DIFFERENT_CONFIRMED")
        first, second = identity_resolution.display_cards
        self.assertEqual(first.history_link_card_ids, ("SYNTH-CARD-B",))
        self.assertEqual(second.history_link_card_ids, ("SYNTH-CARD-A",))

    def test_requires_evidence_and_nonretroactive_times_to_resolve(self) -> None:
        with self.assertRaisesRegex(ValueError, "evidence_refs"):
            resolve_pending_risk_review(
                synthetic_pending_review(),
                association_state="UNKNOWN_PENDING",
                assessment="CONFIRMED",
                reviewed_at=stamp(4),
                evidence_known_at=stamp(3),
                evidence_refs=(),
                verified_risk_grade="CRITICAL",
            )
        with self.assertRaisesRegex(ValueError, "precedes the pending review"):
            resolve_pending_risk_review(
                synthetic_pending_review(),
                association_state="UNKNOWN_PENDING",
                assessment="CONFIRMED",
                reviewed_at=stamp(4),
                evidence_known_at=stamp(0),
                evidence_refs=("synthetic://risk-review/adjudication",),
                verified_risk_grade="CRITICAL",
            )


if __name__ == "__main__":
    unittest.main()
