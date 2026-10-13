"""Resolve pending risk-signal reviews without inferring event identity.

This offline contract consumes an explicit caller-supplied assessment and
evidence. It does not authenticate the assessor, update an event card, merge or
split candidate events, create a notification, or mark delivery as complete.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class RiskReviewAssessment(StrEnum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONFIRMED = "CONFIRMED"
    REFUTED = "REFUTED"


_ASSOCIATION_STATES = frozenset(
    {"SAME_CONFIRMED", "DIFFERENT_CONFIRMED", "UNKNOWN_PENDING", "CONFLICT_PENDING"}
)
_RISK_GRADE_RANK = {"LOW": 0, "WARNING": 1, "CRITICAL": 2}


def _parse_utc(value: Any, label: str) -> datetime:
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


def _normalize_utc(value: Any, label: str) -> str:
    return _parse_utc(value, label).isoformat().replace("+00:00", "Z")


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _evidence_refs(value: Any, *, required: bool) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError("evidence_refs must be a list or tuple of non-empty strings")
    refs = tuple(value)
    if required and not refs:
        raise ValueError("evidence_refs are required to resolve a risk review")
    if len(set(refs)) != len(refs):
        raise ValueError("evidence_refs must not contain duplicates")
    return refs


@dataclass(frozen=True, slots=True)
class RiskReviewDecision:
    review_id: str
    display_card_id: str
    source_intent_id: str
    assessment: RiskReviewAssessment
    review_status: str
    outcome_code: str
    original_risk_signal_grade: str
    current_versioned_risk_grade: str
    verified_risk_grade: str | None
    risk_grade_transition: str
    association_state_before: str
    association_state_after: str
    identity_resolution: str
    evidence_refs: tuple[str, ...]
    evidence_known_at: str | None
    reviewed_at: str
    card_content_changed: bool
    notification_created: bool
    delivery_status: str


def resolve_pending_risk_review(
    pending_review: Mapping[str, Any],
    *,
    association_state: str,
    assessment: RiskReviewAssessment | str,
    reviewed_at: str,
    evidence_refs: list[str] | tuple[str, ...] = (),
    evidence_known_at: str | None = None,
    verified_risk_grade: str | None = None,
) -> RiskReviewDecision:
    """Return a risk-signal review decision while preserving event association.

    The mapping uses the existing pending-review record fields. ``CONFIRMED``
    confirms only the risk signal supplied by the caller; it never confirms
    whether candidate observations are the same or different events. A
    ``DIFFERENT_CONFIRMED`` split remains a separate call to
    ``resolve_pending_association`` with its own identity evidence.
    """
    if not isinstance(pending_review, Mapping):
        raise TypeError("pending_review must be a mapping")
    required = (
        "review_id",
        "display_card_id",
        "source_intent_id",
        "risk_signal_grade",
        "current_versioned_risk_grade",
        "status",
        "confirmed",
        "received_at_processing_time",
    )
    missing = [name for name in required if name not in pending_review]
    if missing:
        raise ValueError(f"pending_review is missing required fields: {missing}")

    review_id = _require_text(pending_review["review_id"], "review_id")
    display_card_id = _require_text(pending_review["display_card_id"], "display_card_id")
    source_intent_id = _require_text(pending_review["source_intent_id"], "source_intent_id")
    is_pending = pending_review["status"] == "PENDING_VERIFICATION"
    is_unconfirmed = pending_review["confirmed"] is False
    if not (is_pending and is_unconfirmed):
        raise ValueError("pending_review must be unconfirmed and PENDING_VERIFICATION")
    if association_state not in _ASSOCIATION_STATES:
        raise ValueError("association_state must use a V2 association state")

    try:
        assessment = RiskReviewAssessment(assessment)
    except (TypeError, ValueError) as exc:
        raise ValueError("assessment must be INSUFFICIENT_EVIDENCE, CONFIRMED, or REFUTED") from exc

    received_at = _parse_utc(
        pending_review["received_at_processing_time"], "received_at_processing_time"
    )
    reviewed_at_normalized = _normalize_utc(reviewed_at, "reviewed_at")
    reviewed_time = _parse_utc(reviewed_at_normalized, "reviewed_at")
    if reviewed_time < received_at:
        raise ValueError("reviewed_at precedes the pending review")

    requires_evidence = assessment is not RiskReviewAssessment.INSUFFICIENT_EVIDENCE
    refs = _evidence_refs(evidence_refs, required=requires_evidence)
    evidence_time: datetime | None = None
    evidence_known_at_normalized: str | None = None
    if evidence_known_at is not None:
        evidence_known_at_normalized = _normalize_utc(evidence_known_at, "evidence_known_at")
        evidence_time = _parse_utc(evidence_known_at_normalized, "evidence_known_at")

    baseline_grade = _require_text(
        pending_review["current_versioned_risk_grade"], "current_versioned_risk_grade"
    ).strip().upper()
    signal_grade = _require_text(
        pending_review["risk_signal_grade"], "risk_signal_grade"
    ).strip().upper()

    if assessment is RiskReviewAssessment.INSUFFICIENT_EVIDENCE:
        if verified_risk_grade is not None:
            raise ValueError("verified_risk_grade is not accepted when evidence is insufficient")
        if evidence_time is not None and evidence_time < received_at:
            raise ValueError("evidence_known_at precedes the pending review")
        review_status = "PENDING_VERIFICATION"
        outcome_code = "INSUFFICIENT_EVIDENCE_RETAINED"
        grade_transition = "UNRESOLVED"
        verified_grade = None
    else:
        if not refs:
            raise ValueError("evidence_refs are required to resolve a risk review")
        if evidence_time is None:
            raise ValueError("evidence_known_at is required to resolve a risk review")
        if evidence_time < received_at:
            raise ValueError("evidence_known_at precedes the pending review")
        if reviewed_time < evidence_time:
            raise ValueError("reviewed_at precedes evidence availability")
        if assessment is RiskReviewAssessment.REFUTED:
            if verified_risk_grade is not None:
                raise ValueError("verified_risk_grade must be omitted for a refuted signal")
            review_status = "RESOLVED_REFUTED"
            outcome_code = "RISK_SIGNAL_REFUTED"
            grade_transition = "NO_UPGRADE"
            verified_grade = None
        else:
            if not isinstance(verified_risk_grade, str):
                raise ValueError("verified_risk_grade is required for a confirmed risk signal")
            verified_grade = verified_risk_grade.strip().upper()
            if verified_grade not in _RISK_GRADE_RANK:
                raise ValueError("verified_risk_grade must be LOW, WARNING, or CRITICAL")
            review_status = "RESOLVED_CONFIRMED"
            if baseline_grade not in _RISK_GRADE_RANK:
                outcome_code = "RISK_SIGNAL_CONFIRMED_BASELINE_UNKNOWN"
                grade_transition = "UNCOMPARABLE_BASELINE_UNKNOWN"
            elif _RISK_GRADE_RANK[verified_grade] > _RISK_GRADE_RANK[baseline_grade]:
                outcome_code = "RISK_UPGRADE_CONFIRMED"
                grade_transition = "UPGRADE"
            elif _RISK_GRADE_RANK[verified_grade] == _RISK_GRADE_RANK[baseline_grade]:
                outcome_code = "RISK_SIGNAL_CONFIRMED_NO_GRADE_CHANGE"
                grade_transition = "NO_GRADE_CHANGE"
            else:
                outcome_code = "VERIFIED_GRADE_BELOW_BASELINE"
                grade_transition = "DOWNGRADE"

    return RiskReviewDecision(
        review_id=review_id,
        display_card_id=display_card_id,
        source_intent_id=source_intent_id,
        assessment=assessment,
        review_status=review_status,
        outcome_code=outcome_code,
        original_risk_signal_grade=signal_grade,
        current_versioned_risk_grade=baseline_grade,
        verified_risk_grade=verified_grade,
        risk_grade_transition=grade_transition,
        association_state_before=association_state,
        association_state_after=association_state,
        identity_resolution="NOT_PERFORMED",
        evidence_refs=refs,
        evidence_known_at=evidence_known_at_normalized,
        reviewed_at=reviewed_at_normalized,
        card_content_changed=False,
        notification_created=False,
        delivery_status="NOT_DELIVERED",
    )
