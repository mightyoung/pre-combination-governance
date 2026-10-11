"""Synthetic unit tests for explicit pending-to-identity resolution."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

try:
    from rfb.research.event_card_resolution import (
        EventDisplayCard,
        PendingAssociation,
        resolve_pending_association,
    )
except ImportError:
    EventDisplayCard = None
    PendingAssociation = None
    resolve_pending_association = None


BASE = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)


def stamp(seconds: int) -> str:
    return (BASE + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def pending(*, state="UNKNOWN_PENDING"):
    if PendingAssociation is None:
        return None
    return PendingAssociation(
        association_id="ASSOC-AB",
        display_card_id="CARD-A",
        candidate_episode_ids=("EP-A", "EP-B"),
        association_state=state,
        pending_at=stamp(0),
        evidence_refs=("synthetic://pending/ab",),
    )


class EventCardResolutionTests(unittest.TestCase):
    def require_implementation(self):
        self.assertIsNotNone(
            PendingAssociation,
            "explicit pending-to-identity resolution has not been implemented",
        )
        self.assertIsNotNone(EventDisplayCard)
        self.assertIsNotNone(resolve_pending_association)

    def test_pending_keeps_episode_candidates_independent_under_stable_card(self):
        self.require_implementation()
        candidate = pending()
        self.assertEqual(candidate.display_card_id, "CARD-A")
        self.assertEqual(candidate.candidate_episode_ids, ("EP-A", "EP-B"))
        self.assertEqual(candidate.association_state, "UNKNOWN_PENDING")

    def test_confirmed_different_creates_two_cards_with_reciprocal_history_links(self):
        self.require_implementation()
        result = resolve_pending_association(
            pending(state="CONFLICT_PENDING"),
            association_state="DIFFERENT_CONFIRMED",
            identity_evidence_known_at=stamp(6),
            resolved_at=stamp(8),
            evidence_refs=("synthetic://identity/different-ab",),
            new_display_card_id="CARD-B",
        )

        self.assertEqual(result.reason_code, "DIFFERENT_CONFIRMED_AFTER_PENDING")
        self.assertEqual(result.resolved_at, stamp(8))
        self.assertEqual(result.evidence_refs, ("synthetic://identity/different-ab",))
        self.assertEqual(
            result.display_cards,
            (
                EventDisplayCard("CARD-A", ("EP-A",), ("CARD-B",)),
                EventDisplayCard("CARD-B", ("EP-B",), ("CARD-A",)),
            ),
        )

    def test_confirmed_same_keeps_one_card_and_both_episode_references(self):
        self.require_implementation()
        result = resolve_pending_association(
            pending(),
            association_state="SAME_CONFIRMED",
            identity_evidence_known_at=stamp(3),
            resolved_at=stamp(5),
            evidence_refs=("synthetic://identity/same-ab",),
        )

        self.assertEqual(len(result.display_cards), 1)
        self.assertEqual(result.display_cards[0].card_id, "CARD-A")
        self.assertEqual(result.display_cards[0].episode_ids, ("EP-A", "EP-B"))
        self.assertEqual(result.display_cards[0].history_link_card_ids, ())

    def test_split_fails_closed_without_identity_evidence_or_stable_new_card_id(self):
        self.require_implementation()
        with self.assertRaises(ValueError):
            resolve_pending_association(
                pending(),
                association_state="DIFFERENT_CONFIRMED",
                identity_evidence_known_at=stamp(3),
                resolved_at=stamp(5),
                evidence_refs=(),
                new_display_card_id="CARD-B",
            )
        with self.assertRaises(ValueError):
            resolve_pending_association(
                pending(),
                association_state="DIFFERENT_CONFIRMED",
                identity_evidence_known_at=stamp(3),
                resolved_at=stamp(5),
                evidence_refs=("synthetic://identity/different-ab",),
            )

    def test_pending_or_early_resolution_cannot_be_marked_confirmed(self):
        self.require_implementation()
        for state, resolved_at in (
            ("UNKNOWN_PENDING", stamp(5)),
            ("DIFFERENT_CONFIRMED", stamp(-1)),
        ):
            with self.subTest(state=state, resolved_at=resolved_at):
                with self.assertRaises(ValueError):
                    resolve_pending_association(
                        pending(),
                        association_state=state,
                        identity_evidence_known_at=stamp(2),
                        resolved_at=resolved_at,
                        evidence_refs=("synthetic://identity/check",),
                        new_display_card_id=(
                            "CARD-B" if state == "DIFFERENT_CONFIRMED" else None
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
