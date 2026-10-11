"""Pure transition from a pending episode relation to explicit event cards.

This is a software-only identity resolution result. It neither infers whether
episodes match nor renders or delivers a user notification. A DIFFERENT
decision requires a caller-supplied stable new card ID and creates reciprocal
history links; unresolved candidates remain separate while pending.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


_PENDING_STATES = frozenset({"UNKNOWN_PENDING", "CONFLICT_PENDING"})
_RESOLVED_STATES = frozenset({"SAME_CONFIRMED", "DIFFERENT_CONFIRMED"})


def _parse_utc(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be an ISO-8601 timestamp with UTC offset")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"{label} must be an ISO-8601 timestamp with UTC offset"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _normalize_utc(value: str, label: str) -> str:
    return _parse_utc(value, label).isoformat().replace("+00:00", "Z")


def _require_ids(values: tuple[str, ...], label: str, *, count: int | None = None) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise ValueError(f"{label} must be a tuple of non-empty strings")
    if count is not None and len(values) != count:
        raise ValueError(f"{label} must contain exactly {count} values")
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must not contain duplicates")


def _require_card_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a stable, non-empty display card ID")


@dataclass(frozen=True, slots=True)
class PendingAssociation:
    """Two independent episode candidates shown on one stable pending card."""

    association_id: str
    display_card_id: str
    candidate_episode_ids: tuple[str, str]
    association_state: str
    pending_at: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.association_id, str) or not self.association_id.strip():
            raise ValueError("association_id must be a non-empty string")
        _require_card_id(self.display_card_id, "display_card_id")
        _require_ids(self.candidate_episode_ids, "candidate_episode_ids", count=2)
        if self.association_state not in _PENDING_STATES:
            raise ValueError("association_state must remain UNKNOWN_PENDING or CONFLICT_PENDING")
        _normalize_utc(self.pending_at, "pending_at")
        _require_ids(self.evidence_refs, "evidence_refs")
        if not self.evidence_refs:
            raise ValueError("pending evidence_refs are required")


@dataclass(frozen=True, slots=True)
class EventDisplayCard:
    """Event identity references and history links for one display card."""

    card_id: str
    episode_ids: tuple[str, ...]
    history_link_card_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_card_id(self.card_id, "card_id")
        _require_ids(self.episode_ids, "episode_ids")
        if not self.episode_ids:
            raise ValueError("event display cards require at least one episode ID")
        _require_ids(self.history_link_card_ids, "history_link_card_ids")
        if self.card_id in self.history_link_card_ids:
            raise ValueError("a card cannot link to itself")


@dataclass(frozen=True, slots=True)
class AssociationResolution:
    """Explainable, time-stamped result of resolving one pending relation."""

    association_id: str
    association_state: str
    reason_code: str
    pending_at: str
    identity_evidence_known_at: str
    resolved_at: str
    evidence_refs: tuple[str, ...]
    display_cards: tuple[EventDisplayCard, ...]


def resolve_pending_association(
    pending: PendingAssociation,
    *,
    association_state: str,
    identity_evidence_known_at: str,
    resolved_at: str,
    evidence_refs: tuple[str, ...],
    new_display_card_id: str | None = None,
) -> AssociationResolution:
    """Resolve an existing pending pair without inferring identity.

    The caller must supply an independently justified final state, evidence
    references and times. For DIFFERENT_CONFIRMED, the caller must also supply
    the stable ID of the new card; this function never invents IDs or silently
    folds distinct candidates together.
    """
    if not isinstance(pending, PendingAssociation):
        raise TypeError("pending must be a PendingAssociation")
    if association_state not in _RESOLVED_STATES:
        raise ValueError("association_state must be SAME_CONFIRMED or DIFFERENT_CONFIRMED")
    _require_ids(evidence_refs, "evidence_refs")
    if not evidence_refs:
        raise ValueError("identity evidence_refs are required for confirmation")

    pending_time = _parse_utc(pending.pending_at, "pending_at")
    evidence_time = _parse_utc(identity_evidence_known_at, "identity_evidence_known_at")
    resolution_time = _parse_utc(resolved_at, "resolved_at")
    if evidence_time < pending_time:
        raise ValueError("identity evidence cannot be known before the pending state")
    if resolution_time < evidence_time:
        raise ValueError("resolution cannot precede identity evidence availability")

    first_episode, second_episode = pending.candidate_episode_ids
    if association_state == "SAME_CONFIRMED":
        if new_display_card_id is not None:
            raise ValueError("SAME_CONFIRMED must retain the existing display card")
        reason_code = "SAME_CONFIRMED_AFTER_PENDING"
        cards = (
            EventDisplayCard(
                card_id=pending.display_card_id,
                episode_ids=(first_episode, second_episode),
                history_link_card_ids=(),
            ),
        )
    else:
        if new_display_card_id is None:
            raise ValueError("DIFFERENT_CONFIRMED requires a stable new display card ID")
        _require_card_id(new_display_card_id, "new_display_card_id")
        if new_display_card_id == pending.display_card_id:
            raise ValueError("new display card ID must differ from the existing card")
        reason_code = "DIFFERENT_CONFIRMED_AFTER_PENDING"
        cards = (
            EventDisplayCard(
                card_id=pending.display_card_id,
                episode_ids=(first_episode,),
                history_link_card_ids=(new_display_card_id,),
            ),
            EventDisplayCard(
                card_id=new_display_card_id,
                episode_ids=(second_episode,),
                history_link_card_ids=(pending.display_card_id,),
            ),
        )

    return AssociationResolution(
        association_id=pending.association_id,
        association_state=association_state,
        reason_code=reason_code,
        pending_at=_normalize_utc(pending.pending_at, "pending_at"),
        identity_evidence_known_at=_normalize_utc(
            identity_evidence_known_at, "identity_evidence_known_at"
        ),
        resolved_at=_normalize_utc(resolved_at, "resolved_at"),
        evidence_refs=evidence_refs,
        display_cards=cards,
    )
