"""Pure-software alert cards and event-identity review lifecycle.

This module records synthetic alert evidence only. It has no transport adapter
and cannot mark a card delivered.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from collections.abc import Iterable, Sequence


class DeliveryStatus(StrEnum):
    """The two outcomes this software can honestly emit without a transport."""

    SIMULATED = "SIMULATED"
    NOT_DELIVERED = "NOT_DELIVERED"


class RelationDecision(StrEnum):
    SAME_EVENT = "SAME_EVENT"
    DISTINCT_EVENTS = "DISTINCT_EVENTS"


@dataclass(frozen=True, slots=True)
class CandidateEvent:
    candidate_id: str
    event_time: str
    observed_at: str
    summary: str
    source_id: str
    evidence_refs: tuple[str, ...] = ()
    risk_flag: str = "EXPOSURE"

    def __post_init__(self) -> None:
        for field_name in ("candidate_id", "summary", "source_id", "risk_flag"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        event_time = _timestamp(self.event_time, "event_time")
        observed_at = _timestamp(self.observed_at, "observed_at")
        if _parse_timestamp(event_time) > _parse_timestamp(observed_at):
            raise ValueError("event_time cannot be after observed_at")
        object.__setattr__(self, "event_time", event_time)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs))


@dataclass(frozen=True, slots=True)
class AlertRecord:
    alert_id: str
    card_id: str
    revision: int
    candidate_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    alert_level: str
    verification_state: str
    risk_flag: str
    visible_text: str
    rationale: str
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    event_time: str
    observed_at: str
    alerted_at: str
    delivery_status: DeliveryStatus
    delivered_at: None = None


@dataclass(frozen=True, slots=True)
class DisplayCard:
    card_id: str
    candidate_ids: tuple[str, ...]
    status: str
    alert_level: str
    merged_into_card_id: str | None
    created_at: str
    updated_at: str
    latest_alert_id: str


@dataclass(frozen=True, slots=True)
class AssociationTransition:
    to_status: str
    at: str
    rationale: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EventAssociation:
    association_id: str
    candidate_ids: tuple[str, str]
    card_ids: tuple[str, str]
    member_groups: tuple[tuple[str, ...], tuple[str, ...]]
    status: str
    rationale: str
    evidence_refs: tuple[str, ...]
    created_at: str
    updated_at: str
    history: tuple[AssociationTransition, ...]
    canonical_card_id: str | None = None


@dataclass(frozen=True, slots=True)
class EventConfirmationResult:
    association_id: str
    predicted_relation: str
    true_relation: str

    def __post_init__(self) -> None:
        if not self.association_id:
            raise ValueError("association_id must be non-empty")
        if self.predicted_relation not in {
            "PENDING",
            RelationDecision.SAME_EVENT.value,
            RelationDecision.DISTINCT_EVENTS.value,
        }:
            raise ValueError("predicted_relation must be PENDING or a resolved relation")
        if self.true_relation not in {
            RelationDecision.SAME_EVENT.value,
            RelationDecision.DISTINCT_EVENTS.value,
        }:
            raise ValueError("true_relation must be a resolved relation")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("timestamp must be ISO-8601 with a UTC offset") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _timestamp(value: str | datetime, name: str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must include a UTC offset")
        parsed = value.astimezone(timezone.utc)
    elif isinstance(value, str):
        parsed = _parse_timestamp(value)
    else:
        raise ValueError(f"{name} must be an ISO-8601 timestamp")
    precision = "microseconds" if parsed.microsecond else "seconds"
    return parsed.isoformat(timespec=precision).replace("+00:00", "Z")


def _refs(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("evidence references must be a collection of strings")
    try:
        refs = tuple(values)
    except TypeError as exc:
        raise ValueError("evidence references must be iterable") from exc
    if any(not isinstance(ref, str) or not ref.strip() for ref in refs):
        raise ValueError("evidence references must be non-empty strings")
    if len(set(refs)) != len(refs):
        raise ValueError("evidence references must be unique")
    return refs


def _stable_id(prefix: str, values: Sequence[str]) -> str:
    payload = "\x00".join(values).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()}"


class AlertLedger:
    """In-memory ledger for deterministic candidate, card, and alert records."""

    def __init__(
        self, *, delivery_status: DeliveryStatus = DeliveryStatus.SIMULATED
    ) -> None:
        try:
            delivery_status = DeliveryStatus(delivery_status)
        except (TypeError, ValueError) as exc:
            raise ValueError("delivery_status must be SIMULATED or NOT_DELIVERED") from exc
        self.delivery_status = delivery_status
        self._candidates: dict[str, CandidateEvent] = {}
        self._origin_card_by_candidate: dict[str, str] = {}
        self._cards: dict[str, DisplayCard] = {}
        self._associations: dict[str, EventAssociation] = {}
        self._alerts: list[AlertRecord] = []
        self._revisions: dict[str, int] = {}

    @property
    def alerts(self) -> tuple[AlertRecord, ...]:
        return tuple(self._alerts)

    @property
    def cards(self) -> tuple[DisplayCard, ...]:
        return tuple(self._cards[key] for key in sorted(self._cards))

    @property
    def associations(self) -> tuple[EventAssociation, ...]:
        return tuple(self._associations[key] for key in sorted(self._associations))

    def add_candidate(
        self, candidate: CandidateEvent, *, alerted_at: str | datetime
    ) -> DisplayCard:
        if not isinstance(candidate, CandidateEvent):
            raise TypeError("candidate must be a CandidateEvent")
        at = _timestamp(alerted_at, "alerted_at")
        if _parse_timestamp(at) < _parse_timestamp(candidate.observed_at):
            raise ValueError("alerted_at cannot precede observed_at")
        existing = self._candidates.get(candidate.candidate_id)
        if existing is not None:
            if existing != candidate:
                raise ValueError("candidate_id already exists with different content")
            return self.card_for(candidate.candidate_id)

        card_id = _stable_id("CARD", (candidate.candidate_id,))
        if card_id in self._cards:
            raise ValueError("stable card ID collision")
        self._candidates[candidate.candidate_id] = candidate
        self._origin_card_by_candidate[candidate.candidate_id] = card_id
        self._cards[card_id] = DisplayCard(
            card_id=card_id,
            candidate_ids=(candidate.candidate_id,),
            status="PENDING_VERIFICATION",
            alert_level="PRECAUTIONARY",
            merged_into_card_id=None,
            created_at=at,
            updated_at=at,
            latest_alert_id="",
        )
        self._emit_alert(
            card_id,
            (candidate.candidate_id,),
            at=at,
            alert_level="PRECAUTIONARY",
            verification_state="PENDING_VERIFICATION",
            rationale=(
                f"收到候选风险标记 {candidate.risk_flag}；事件身份待核实。"
            ),
            reason_codes=("CANDIDATE_RISK_FLAG", "EVENT_IDENTITY_PENDING"),
            evidence_refs=candidate.evidence_refs,
        )
        return self._cards[card_id]

    def propose_association(
        self,
        left_candidate_id: str,
        right_candidate_id: str,
        *,
        at: str | datetime,
        rationale: str,
        evidence_refs: Iterable[str] = (),
    ) -> EventAssociation:
        if left_candidate_id == right_candidate_id:
            raise ValueError("an association requires two different candidates")
        left = self.card_for(left_candidate_id)
        right = self.card_for(right_candidate_id)
        if left.card_id == right.card_id:
            raise ValueError("candidates already resolve to the same display card")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("rationale must be non-empty")
        at_value = _timestamp(at, "at")
        refs = _refs(evidence_refs)
        association_id = _stable_id(
            "ASSOC", tuple(sorted((left_candidate_id, right_candidate_id)))
        )
        existing = self._associations.get(association_id)
        if existing is not None:
            if existing.status == "PENDING":
                return existing
            raise ValueError("association already has a terminal decision")
        if _parse_timestamp(at_value) < max(
            _parse_timestamp(left.updated_at), _parse_timestamp(right.updated_at)
        ):
            raise ValueError("association time cannot precede either card update")

        candidate_ids = (left_candidate_id, right_candidate_id)
        card_ids = (left.card_id, right.card_id)
        member_groups = (left.candidate_ids, right.candidate_ids)
        initial = AssociationTransition("PENDING", at_value, rationale, refs)
        association = EventAssociation(
            association_id=association_id,
            candidate_ids=candidate_ids,
            card_ids=card_ids,
            member_groups=member_groups,
            status="PENDING",
            rationale=rationale,
            evidence_refs=refs,
            created_at=at_value,
            updated_at=at_value,
            history=(initial,),
        )
        self._associations[association_id] = association

        shared_refs = tuple(
            dict.fromkeys(
                ref
                for group in member_groups
                for item in group
                for ref in self._candidates[item].evidence_refs
            )
        )
        shared_refs = tuple(dict.fromkeys(shared_refs + refs))
        for card_id, members in zip(card_ids, member_groups, strict=True):
            self._emit_alert(
                card_id,
                members,
                at=at_value,
                alert_level="PRECAUTIONARY",
                verification_state="PENDING_VERIFICATION",
                rationale=(
                    f"关联待核实：{rationale}；两张候选卡继续独立显示。"
                ),
                reason_codes=("IDENTITY_LINK_PENDING",),
                evidence_refs=shared_refs,
            )
        return association

    def resolve_association(
        self,
        association_id: str,
        *,
        decision: RelationDecision,
        at: str | datetime,
        evidence_refs: Iterable[str],
    ) -> EventAssociation:
        try:
            decision = RelationDecision(decision)
        except (TypeError, ValueError) as exc:
            raise ValueError("decision must be SAME_EVENT or DISTINCT_EVENTS") from exc
        refs = _refs(evidence_refs)
        if not refs:
            raise ValueError("evidence references are required to resolve an association")
        association = self.association(association_id)
        if association.status != "PENDING":
            raise ValueError("only a pending association can be resolved")
        at_value = _timestamp(at, "at")
        if _parse_timestamp(at_value) < _parse_timestamp(association.updated_at):
            raise ValueError("resolution time cannot precede the pending association")

        history_item: AssociationTransition
        canonical_card_id: str | None = None
        if decision is RelationDecision.SAME_EVENT:
            canonical_card_id = min(
                association.card_ids,
                key=lambda card_id: (
                    _parse_timestamp(self._cards[card_id].created_at), card_id
                ),
            )
            alias_card_id = next(
                card_id for card_id in association.card_ids if card_id != canonical_card_id
            )
            combined = self._ordered_candidates(
                association.member_groups[0] + association.member_groups[1]
            )
            self._cards[canonical_card_id] = replace(
                self._cards[canonical_card_id],
                candidate_ids=combined,
                status="CONFIRMED_SAME_EVENT",
                merged_into_card_id=None,
                updated_at=at_value,
            )
            alias_members = association.member_groups[
                association.card_ids.index(alias_card_id)
            ]
            self._cards[alias_card_id] = replace(
                self._cards[alias_card_id],
                candidate_ids=alias_members,
                status="MERGED_ALIAS",
                merged_into_card_id=canonical_card_id,
                updated_at=at_value,
            )
            rationale = "证据支持两条候选记录属于同一事件；持续使用原稳定卡。"
            self._emit_alert(
                alias_card_id,
                alias_members,
                at=at_value,
                alert_level="CONFIRMED",
                verification_state="MERGED_ALIAS",
                rationale=f"此稳定卡保留为历史别名；当前事件卡为 {canonical_card_id}。",
                reason_codes=("CARD_ALIAS_TO_CANONICAL",),
                evidence_refs=refs,
            )
            self._emit_alert(
                canonical_card_id,
                combined,
                at=at_value,
                alert_level="CONFIRMED",
                verification_state="CONFIRMED_SAME_EVENT",
                rationale=rationale,
                reason_codes=("EVENT_LINK_CONFIRMED_SAME",),
                evidence_refs=refs,
            )
            new_status = "CONFIRMED_SAME_EVENT"
        else:
            rationale = "证据支持两条候选记录属于不同事件；保持两张稳定卡。"
            for card_id, members in zip(
                association.card_ids, association.member_groups, strict=True
            ):
                self._cards[card_id] = replace(
                    self._cards[card_id],
                    candidate_ids=members,
                    status="CONFIRMED_DISTINCT",
                    merged_into_card_id=None,
                    updated_at=at_value,
                )
                self._emit_alert(
                    card_id,
                    members,
                    at=at_value,
                    alert_level="CONFIRMED",
                    verification_state="CONFIRMED_DISTINCT",
                    rationale=rationale,
                    reason_codes=("EVENT_LINK_CONFIRMED_DISTINCT",),
                    evidence_refs=refs,
                )
            new_status = "CONFIRMED_DISTINCT"

        history_item = AssociationTransition(new_status, at_value, rationale, refs)
        updated = replace(
            association,
            status=new_status,
            rationale=rationale,
            evidence_refs=refs,
            updated_at=at_value,
            history=association.history + (history_item,),
            canonical_card_id=canonical_card_id,
        )
        self._associations[association_id] = updated
        return updated

    def split_association(
        self,
        association_id: str,
        *,
        at: str | datetime,
        rationale: str,
        evidence_refs: Iterable[str],
    ) -> EventAssociation:
        association = self.association(association_id)
        if association.status != "CONFIRMED_SAME_EVENT":
            raise ValueError("only a confirmed same-event association can be split")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("rationale must be non-empty")
        refs = _refs(evidence_refs)
        if not refs:
            raise ValueError("evidence references are required to split an association")
        at_value = _timestamp(at, "at")
        if _parse_timestamp(at_value) < _parse_timestamp(association.updated_at):
            raise ValueError("split time cannot precede the prior association decision")

        for card_id, members in zip(
            association.card_ids, association.member_groups, strict=True
        ):
            self._cards[card_id] = replace(
                self._cards[card_id],
                candidate_ids=members,
                status="CONFIRMED_DISTINCT",
                alert_level="CONFIRMED",
                merged_into_card_id=None,
                updated_at=at_value,
            )
            self._emit_alert(
                card_id,
                members,
                at=at_value,
                alert_level="CONFIRMED",
                verification_state="CONFIRMED_DISTINCT",
                rationale=rationale,
                reason_codes=("EVENT_LINK_SPLIT_TO_DISTINCT",),
                evidence_refs=refs,
            )

        history_item = AssociationTransition(
            "SPLIT_TO_DISTINCT", at_value, rationale, refs
        )
        updated = replace(
            association,
            status="SPLIT_TO_DISTINCT",
            rationale=rationale,
            evidence_refs=refs,
            updated_at=at_value,
            history=association.history + (history_item,),
            canonical_card_id=None,
        )
        self._associations[association_id] = updated
        return updated

    def escalate_card(
        self,
        card_id: str,
        *,
        at: str | datetime,
        rationale: str,
        evidence_refs: Iterable[str],
    ) -> DisplayCard:
        refs = _refs(evidence_refs)
        if not refs:
            raise ValueError("evidence references are required to escalate an alert")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("rationale must be non-empty")
        card = self.get_card(card_id)
        if card.merged_into_card_id is not None:
            card = self.get_card(card.merged_into_card_id)
        at_value = _timestamp(at, "at")
        if _parse_timestamp(at_value) < _parse_timestamp(card.updated_at):
            raise ValueError("escalation time cannot precede the card update")
        self._emit_alert(
            card.card_id,
            card.candidate_ids,
            at=at_value,
            alert_level="ESCALATED",
            verification_state=card.status,
            rationale=rationale,
            reason_codes=("EVIDENCE_BASED_ESCALATION",),
            evidence_refs=refs,
        )
        return self._cards[card.card_id]

    def card_for(self, candidate_id: str) -> DisplayCard:
        try:
            origin_id = self._origin_card_by_candidate[candidate_id]
        except KeyError as exc:
            raise KeyError(f"unknown candidate_id: {candidate_id}") from exc
        card = self._cards[origin_id]
        if card.merged_into_card_id is not None:
            return self._cards[card.merged_into_card_id]
        return card

    def get_card(self, card_id: str) -> DisplayCard:
        try:
            return self._cards[card_id]
        except KeyError as exc:
            raise KeyError(f"unknown card_id: {card_id}") from exc

    def association(self, association_id: str) -> EventAssociation:
        try:
            return self._associations[association_id]
        except KeyError as exc:
            raise KeyError(f"unknown association_id: {association_id}") from exc

    def _ordered_candidates(self, candidate_ids: Iterable[str]) -> tuple[str, ...]:
        return tuple(
            sorted(
                set(candidate_ids),
                key=lambda candidate_id: (
                    _parse_timestamp(self._candidates[candidate_id].observed_at),
                    candidate_id,
                ),
            )
        )

    def _emit_alert(
        self,
        card_id: str,
        candidate_ids: tuple[str, ...],
        *,
        at: str,
        alert_level: str,
        verification_state: str,
        rationale: str,
        reason_codes: tuple[str, ...],
        evidence_refs: tuple[str, ...],
    ) -> AlertRecord:
        at = _timestamp(at, "alerted_at")
        card = self._cards[card_id]
        if _parse_timestamp(at) < _parse_timestamp(card.updated_at):
            raise ValueError("alert time cannot precede its card update")
        members = self._ordered_candidates(candidate_ids)
        if not members:
            raise ValueError("an alert requires at least one candidate")
        revision = self._revisions.get(card_id, 0) + 1
        self._revisions[card_id] = revision
        alert_id = f"{card_id}-R{revision:04d}"
        rows = [self._candidates[item] for item in members]
        event_time = min(rows, key=lambda row: row.event_time).event_time
        observed_at = min(rows, key=lambda row: row.observed_at).observed_at
        source_ids = tuple(sorted({row.source_id for row in rows}))
        risk_flags = tuple(sorted({row.risk_flag for row in rows}))
        summaries = " / ".join(row.summary for row in rows)
        label = {
            "PRECAUTIONARY": "待核实风险提醒",
            "CONFIRMED": "已确认风险提醒",
            "ESCALATED": "已升级风险提醒",
        }.get(alert_level, "风险提醒")
        evidence_text = ", ".join(evidence_refs) if evidence_refs else "暂无证据引用"
        visible_text = (
            f"{label}：{summaries}；状态={verification_state}；"
            f"来源={','.join(source_ids)}；风险标记={','.join(risk_flags)}；"
            f"理由={rationale}；"
            f"证据={evidence_text}；事件时间={event_time}；"
            f"首次观测={observed_at}；提醒生成={at}；"
            f"送达状态={self.delivery_status.value}；送达时间=未记录。"
        )
        alert = AlertRecord(
            alert_id=alert_id,
            card_id=card_id,
            revision=revision,
            candidate_ids=members,
            source_ids=source_ids,
            alert_level=alert_level,
            verification_state=verification_state,
            risk_flag=",".join(risk_flags),
            visible_text=visible_text,
            rationale=rationale,
            reason_codes=reason_codes,
            evidence_refs=evidence_refs,
            event_time=event_time,
            observed_at=observed_at,
            alerted_at=at,
            delivery_status=self.delivery_status,
            delivered_at=None,
        )
        self._alerts.append(alert)
        self._cards[card_id] = replace(
            card,
            candidate_ids=members,
            status=verification_state,
            alert_level=alert_level,
            updated_at=at,
            latest_alert_id=alert_id,
        )
        return alert


def score_alert_timeliness(
    alert: AlertRecord, *, deadline_seconds: float | None = None
) -> dict[str, object]:
    """Report software emission latency and keep delivery timeliness separate."""
    if deadline_seconds is not None and (
        isinstance(deadline_seconds, bool)
        or not isinstance(deadline_seconds, (int, float))
        or not math.isfinite(float(deadline_seconds))
        or deadline_seconds < 0
    ):
        raise ValueError("deadline_seconds must be a finite non-negative number")
    latency = (
        _parse_timestamp(alert.alerted_at) - _parse_timestamp(alert.observed_at)
    ).total_seconds()
    if latency < 0:
        raise ValueError("alerted_at cannot precede observed_at")
    emission_status = (
        "MEASURED_NO_THRESHOLD"
        if deadline_seconds is None
        else "TIMELY"
        if latency <= deadline_seconds
        else "LATE"
    )
    return {
        "alert_id": alert.alert_id,
        "delivery_status": alert.delivery_status.value,
        "emission_latency_seconds": round(latency, 6),
        "emission_timeliness_status": emission_status,
        "configured_deadline_seconds": deadline_seconds,
        "delivery_latency_seconds": None,
        "delivery_timeliness_status": "UNSCORABLE_NO_DELIVERY_RECEIPT",
    }


def score_alert_content_completeness(alert: AlertRecord) -> dict[str, object]:
    fields: dict[str, object] = {
        "card_id": alert.card_id,
        "source_ids": alert.source_ids,
        "alert_level": alert.alert_level,
        "verification_state": alert.verification_state,
        "visible_text": alert.visible_text,
        "rationale": alert.rationale,
        "reason_codes": alert.reason_codes,
        "evidence_refs": alert.evidence_refs,
        "event_time": alert.event_time,
        "observed_at": alert.observed_at,
        "alerted_at": alert.alerted_at,
        "delivery_status": alert.delivery_status.value,
    }
    missing = [
        name
        for name, value in fields.items()
        if (not value) or (isinstance(value, (tuple, list)) and not value)
    ]
    complete_count = len(fields) - len(missing)
    return {
        "alert_id": alert.alert_id,
        "complete": not missing,
        "complete_field_count": complete_count,
        "required_field_count": len(fields),
        "completeness_ratio": complete_count / len(fields),
        "missing_fields": missing,
        "delivery_status": alert.delivery_status.value,
    }


def score_event_confirmation_accuracy(
    results: Sequence[EventConfirmationResult],
) -> dict[str, object]:
    """Score resolved identity decisions; leave pending pairs in a separate count."""
    rows = tuple(results)
    ids = [row.association_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("association_id values must be unique")
    scored_rows: list[dict[str, str]] = []
    correct = 0
    decided = 0
    for row in rows:
        if row.predicted_relation == "PENDING":
            status = "UNDECIDED"
        else:
            decided += 1
            is_correct = row.predicted_relation == row.true_relation
            correct += int(is_correct)
            status = "CORRECT" if is_correct else "INCORRECT"
        scored_rows.append(
            {
                "association_id": row.association_id,
                "predicted_relation": row.predicted_relation,
                "true_relation": row.true_relation,
                "status": status,
            }
        )
    return {
        "pair_count": len(rows),
        "decided_pair_count": decided,
        "undecided_pair_count": len(rows) - decided,
        "correct_decisions": correct,
        "incorrect_decisions": decided - correct,
        "accuracy": correct / decided if decided else None,
        "status": "SCORED" if decided else "UNAVAILABLE_NO_RESOLVED_PAIRS",
        "pairs": scored_rows,
    }
