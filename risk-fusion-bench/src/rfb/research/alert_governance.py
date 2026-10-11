"""Pure-software alert cards and event-identity review lifecycle.

This module records synthetic alert evidence only. It has no transport adapter
and cannot mark a card delivered.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from enum import StrEnum


class DeliveryStatus(StrEnum):
    """The two outcomes this software can honestly emit without a transport."""

    SIMULATED = "SIMULATED"
    NOT_DELIVERED = "NOT_DELIVERED"


class RelationDecision(StrEnum):
    SAME_EVENT = "SAME_EVENT"
    DISTINCT_EVENTS = "DISTINCT_EVENTS"


_ALERT_LEVEL_RANK = {"PRECAUTIONARY": 0, "CONFIRMED": 1, "ESCALATED": 2}


def _highest_alert_level(*levels: str) -> str:
    return max(levels, key=lambda level: _ALERT_LEVEL_RANK.get(level, -1))


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
    status: str
    rationale: str
    evidence_refs: tuple[str, ...]
    created_at: str
    updated_at: str
    history: tuple[AssociationTransition, ...]
    canonical_card_id: str | None = None


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
        self._base_alert_levels: dict[str, str] = {}
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
        self._base_alert_levels[card_id] = "PRECAUTIONARY"
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
        try:
            left_origin = self._origin_card_by_candidate[left_candidate_id]
            right_origin = self._origin_card_by_candidate[right_candidate_id]
        except KeyError as exc:
            raise KeyError(f"unknown candidate_id: {exc.args[0]}") from exc
        left = self.get_card(self._canonical_card_id(left_origin))
        right = self.get_card(self._canonical_card_id(right_origin))
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
        affected_card_ids = self._combined_component_cards(
            left.card_id, right.card_id
        )
        self._preflight_card_times(at_value, affected_card_ids, "association")

        candidate_ids = (left_candidate_id, right_candidate_id)
        card_ids = (left.card_id, right.card_id)
        initial = AssociationTransition("PENDING", at_value, rationale, refs)
        association = EventAssociation(
            association_id=association_id,
            candidate_ids=candidate_ids,
            card_ids=card_ids,
            status="PENDING",
            rationale=rationale,
            evidence_refs=refs,
            created_at=at_value,
            updated_at=at_value,
            history=(initial,),
        )
        self._associations[association_id] = association

        component_candidate_ids = tuple(
            candidate_id
            for card_id in affected_card_ids
            for candidate_id in self._source_candidate_ids(card_id)
        )
        shared_refs = tuple(
            dict.fromkeys(
                ref
                for item in component_candidate_ids
                for ref in self._candidates[item].evidence_refs
            )
        )
        shared_refs = tuple(dict.fromkeys(shared_refs + refs))
        for card_id in card_ids:
            card = self._cards[card_id]
            self._emit_alert(
                card_id,
                card.candidate_ids,
                at=at_value,
                alert_level=card.alert_level,
                verification_state="ASSOCIATION_PENDING",
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
        affected_card_ids = self._affected_card_ids(association)
        self._preflight_association_time(at_value, association, affected_card_ids)
        self._preflight_identity_decision(association, decision)

        new_status = (
            "CONFIRMED_SAME_EVENT"
            if decision is RelationDecision.SAME_EVENT
            else "CONFIRMED_DISTINCT"
        )
        rationale = (
            "证据支持两条候选记录属于同一事件；持续使用原稳定卡。"
            if decision is RelationDecision.SAME_EVENT
            else "证据支持两条候选记录属于不同事件；保持独立卡片。"
        )
        updated = replace(
            association,
            status=new_status,
            rationale=rationale,
            evidence_refs=refs,
            updated_at=at_value,
            history=association.history
            + (AssociationTransition(new_status, at_value, rationale, refs),),
        )
        self._associations[association_id] = updated
        self._rebuild_components()
        self._emit_association_alerts(
            affected_card_ids,
            at=at_value,
            rationale=rationale,
            reason_codes=(f"EVENT_LINK_{new_status}",),
            evidence_refs=refs,
        )
        canonical_card_id = (
            self.card_for(association.candidate_ids[0]).card_id
            if decision is RelationDecision.SAME_EVENT
            else None
        )
        updated = replace(updated, canonical_card_id=canonical_card_id)
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
        affected_card_ids = self._affected_card_ids(association)
        self._preflight_association_time(at_value, association, affected_card_ids)
        components_without_edge = self._identity_components(
            excluding_association_id=association_id
        )
        component_by_card = {
            card_id: component
            for component in components_without_edge
            for card_id in component
        }
        left_card_id = self._origin_card_by_candidate[association.candidate_ids[0]]
        right_card_id = self._origin_card_by_candidate[association.candidate_ids[1]]
        if component_by_card[left_card_id] == component_by_card[right_card_id]:
            raise ValueError(
                "cannot split edge while another confirmed same-event path keeps "
                "candidates connected"
            )
        updated = replace(
            association,
            status="SPLIT_TO_DISTINCT",
            rationale=rationale,
            evidence_refs=refs,
            updated_at=at_value,
            history=association.history
            + (AssociationTransition("SPLIT_TO_DISTINCT", at_value, rationale, refs),),
            canonical_card_id=None,
        )
        self._associations[association_id] = updated
        self._rebuild_components()
        self._emit_association_alerts(
            affected_card_ids,
            at=at_value,
            rationale=rationale,
            reason_codes=("EVENT_LINK_SPLIT_TO_DISTINCT",),
            evidence_refs=refs,
        )
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
        canonical_card_id = self._canonical_card_id(card_id)
        card_ids = self._component_card_ids(canonical_card_id)
        at_value = _timestamp(at, "at")
        self._preflight_card_times(at_value, card_ids, "escalation")
        for member_card_id in card_ids:
            self._base_alert_levels[member_card_id] = "ESCALATED"
        self._rebuild_components()
        card = self.get_card(canonical_card_id)
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

    def confirm_risk_alert(
        self,
        card_id: str,
        *,
        at: str | datetime,
        rationale: str,
        evidence_refs: Iterable[str],
    ) -> DisplayCard:
        """Advance the risk-alert stage without changing event identity."""
        refs = _refs(evidence_refs)
        if not refs:
            raise ValueError("evidence references are required to confirm a risk alert")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("rationale must be non-empty")
        canonical_card_id = self._canonical_card_id(card_id)
        card_ids = self._component_card_ids(canonical_card_id)
        at_value = _timestamp(at, "at")
        self._preflight_card_times(at_value, card_ids, "risk confirmation")
        for member_card_id in card_ids:
            self._base_alert_levels[member_card_id] = _highest_alert_level(
                self._base_alert_levels[member_card_id], "CONFIRMED"
            )
        self._rebuild_components()
        card = self.get_card(canonical_card_id)
        self._emit_alert(
            card.card_id,
            card.candidate_ids,
            at=at_value,
            alert_level="CONFIRMED",
            verification_state=card.status,
            rationale=rationale,
            reason_codes=("EVIDENCE_BASED_RISK_CONFIRMATION",),
            evidence_refs=refs,
        )
        return self._cards[card.card_id]

    def card_for(self, candidate_id: str) -> DisplayCard:
        try:
            origin_id = self._origin_card_by_candidate[candidate_id]
        except KeyError as exc:
            raise KeyError(f"unknown candidate_id: {candidate_id}") from exc
        return self.get_card(self._canonical_card_id(origin_id))

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

    def _canonical_card_id(self, card_id: str) -> str:
        if card_id not in self._cards:
            raise KeyError(f"unknown card_id: {card_id}")
        visited: set[str] = set()
        current = card_id
        while True:
            if current in visited:
                raise ValueError(f"alias cycle detected at card_id: {current}")
            visited.add(current)
            target = self._cards[current].merged_into_card_id
            if target is None:
                return current
            if target not in self._cards:
                raise ValueError(f"alias target does not exist: {target}")
            current = target

    def _component_card_ids(self, card_id: str) -> tuple[str, ...]:
        canonical = self._canonical_card_id(card_id)
        return tuple(
            item
            for item in sorted(self._cards)
            if self._canonical_card_id(item) == canonical
        )

    def _combined_component_cards(self, *card_ids: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    member
                    for card_id in card_ids
                    for member in self._component_card_ids(card_id)
                }
            )
        )

    def _source_candidate_ids(self, card_id: str) -> tuple[str, ...]:
        return self._ordered_candidates(
            candidate_id
            for candidate_id, origin_card_id in self._origin_card_by_candidate.items()
            if origin_card_id == card_id
        )

    def _affected_card_ids(self, association: EventAssociation) -> tuple[str, ...]:
        source_card_ids = tuple(
            self._origin_card_by_candidate[candidate_id]
            for candidate_id in association.candidate_ids
        )
        return self._combined_component_cards(*source_card_ids)

    def _preflight_card_times(
        self, at: str, card_ids: Iterable[str], operation: str
    ) -> None:
        stale = [
            card_id
            for card_id in card_ids
            if _parse_timestamp(at)
            < _parse_timestamp(self._cards[card_id].updated_at)
        ]
        if stale:
            raise ValueError(
                f"{operation} time precedes affected card update: {', '.join(stale)}"
            )

    def _preflight_association_time(
        self,
        at: str,
        association: EventAssociation,
        card_ids: Iterable[str],
    ) -> None:
        if _parse_timestamp(at) < _parse_timestamp(association.updated_at):
            raise ValueError("transition time precedes association update")
        self._preflight_card_times(at, card_ids, "association transition")

    def _identity_components(
        self, *, excluding_association_id: str | None = None
    ) -> tuple[tuple[str, ...], ...]:
        parent = {card_id: card_id for card_id in self._cards}

        def find(card_id: str) -> str:
            while parent[card_id] != card_id:
                parent[card_id] = parent[parent[card_id]]
                card_id = parent[card_id]
            return card_id

        def union(left: str, right: str) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[max(left_root, right_root)] = min(left_root, right_root)

        for association in self._associations.values():
            if association.association_id == excluding_association_id:
                continue
            if association.status != "CONFIRMED_SAME_EVENT":
                continue
            left = self._origin_card_by_candidate[association.candidate_ids[0]]
            right = self._origin_card_by_candidate[association.candidate_ids[1]]
            union(left, right)

        for association in self._associations.values():
            if association.status not in {"CONFIRMED_DISTINCT", "SPLIT_TO_DISTINCT"}:
                continue
            left = self._origin_card_by_candidate[association.candidate_ids[0]]
            right = self._origin_card_by_candidate[association.candidate_ids[1]]
            if find(left) == find(right):
                raise ValueError(
                    "ledger conflict: distinct relation is connected by a "
                    "confirmed same-event path"
                )

        groups: dict[str, list[str]] = {}
        for card_id in self._cards:
            groups.setdefault(find(card_id), []).append(card_id)
        return tuple(tuple(sorted(group)) for group in groups.values())

    def _is_distinct_member(self, card_id: str) -> bool:
        source_ids = set(self._source_candidate_ids(card_id))
        return any(
            association.status in {"CONFIRMED_DISTINCT", "SPLIT_TO_DISTINCT"}
            and source_ids.intersection(association.candidate_ids)
            for association in self._associations.values()
        )

    def _rebuild_components(self) -> None:
        for members in self._identity_components():
            canonical = min(
                members,
                key=lambda card_id: (
                    _parse_timestamp(self._cards[card_id].created_at), card_id
                ),
            )
            candidate_ids = self._ordered_candidates(
                candidate_id
                for card_id in members
                for candidate_id in self._source_candidate_ids(card_id)
            )
            group_level = _highest_alert_level(
                *(self._base_alert_levels[card_id] for card_id in members)
            )
            for card_id in members:
                card = self._cards[card_id]
                if card_id == canonical:
                    status = (
                        "CONFIRMED_SAME_EVENT"
                        if len(members) > 1
                        else "CONFIRMED_DISTINCT"
                        if self._is_distinct_member(card_id)
                        else "PENDING_VERIFICATION"
                    )
                    self._cards[card_id] = replace(
                        card,
                        candidate_ids=candidate_ids,
                        status=status,
                        alert_level=group_level,
                        merged_into_card_id=None,
                    )
                else:
                    self._cards[card_id] = replace(
                        card,
                        candidate_ids=self._source_candidate_ids(card_id),
                        status="MERGED_ALIAS",
                        alert_level=self._base_alert_levels[card_id],
                        merged_into_card_id=canonical,
                    )
        for association in tuple(self._associations.values()):
            if association.status != "CONFIRMED_SAME_EVENT":
                continue
            origin_card_id = self._origin_card_by_candidate[
                association.candidate_ids[0]
            ]
            canonical_card_id = self._canonical_card_id(origin_card_id)
            if association.canonical_card_id != canonical_card_id:
                self._associations[association.association_id] = replace(
                    association, canonical_card_id=canonical_card_id
                )

    def _preflight_identity_decision(
        self, association: EventAssociation, decision: RelationDecision
    ) -> None:
        components = self._identity_components()
        component_by_card = {
            card_id: component
            for component in components
            for card_id in component
        }
        left_card_id = self._origin_card_by_candidate[association.candidate_ids[0]]
        right_card_id = self._origin_card_by_candidate[association.candidate_ids[1]]
        left_component = component_by_card[left_card_id]
        right_component = component_by_card[right_card_id]

        if decision is RelationDecision.DISTINCT_EVENTS:
            if left_component == right_component:
                raise ValueError(
                    "distinct relation conflicts with an existing confirmed "
                    "same-event path"
                )
            return

        if left_component == right_component:
            return
        for constraint in self._associations.values():
            if constraint.status not in {"CONFIRMED_DISTINCT", "SPLIT_TO_DISTINCT"}:
                continue
            constraint_left = self._origin_card_by_candidate[
                constraint.candidate_ids[0]
            ]
            constraint_right = self._origin_card_by_candidate[
                constraint.candidate_ids[1]
            ]
            if (
                component_by_card[constraint_left] == left_component
                and component_by_card[constraint_right] == right_component
            ) or (
                component_by_card[constraint_left] == right_component
                and component_by_card[constraint_right] == left_component
            ):
                raise ValueError(
                    "same-event relation conflicts with an existing confirmed "
                    "distinct constraint"
                )

    def _emit_association_alerts(
        self,
        card_ids: Iterable[str],
        *,
        at: str,
        rationale: str,
        reason_codes: tuple[str, ...],
        evidence_refs: tuple[str, ...],
    ) -> None:
        for card_id in card_ids:
            card = self._cards[card_id]
            self._emit_alert(
                card_id,
                card.candidate_ids,
                at=at,
                alert_level=card.alert_level,
                verification_state=card.status,
                rationale=rationale,
                reason_codes=reason_codes,
                evidence_refs=evidence_refs,
            )

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
        event_time = min(
            rows, key=lambda row: _parse_timestamp(row.event_time)
        ).event_time
        observed_at = min(
            rows, key=lambda row: _parse_timestamp(row.observed_at)
        ).observed_at
        source_ids = tuple(sorted({row.source_id for row in rows}))
        risk_flags = tuple(sorted({row.risk_flag for row in rows}))
        summaries = " / ".join(row.summary for row in rows)
        effective_level = _highest_alert_level(card.alert_level, alert_level)
        label = {
            "PRECAUTIONARY": "待核实风险提醒",
            "CONFIRMED": "已确认风险提醒",
            "ESCALATED": "已升级风险提醒",
        }.get(effective_level, "风险提醒")
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
            alert_level=effective_level,
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
        self._base_alert_levels[card_id] = _highest_alert_level(
            self._base_alert_levels[card_id], effective_level
        )
        self._cards[card_id] = replace(
            card,
            candidate_ids=members,
            alert_level=effective_level,
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
    delivery_status = getattr(alert.delivery_status, "value", alert.delivery_status)
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
        "delivery_status": delivery_status,
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
        "delivery_status": delivery_status,
    }


def score_event_confirmation_accuracy(
    ledger: AlertLedger,
    true_relations: Mapping[str, str],
) -> dict[str, object]:
    """Score ledger decisions against truth labels keyed by real association ID."""
    if not isinstance(ledger, AlertLedger):
        raise TypeError("ledger must be an AlertLedger")
    if not isinstance(true_relations, Mapping):
        raise TypeError("true_relations must map ledger association IDs to relations")
    associations = {row.association_id: row for row in ledger.associations}
    unknown = set(true_relations) - set(associations)
    if unknown:
        raise ValueError(f"truth labels reference unknown ledger associations: {sorted(unknown)}")
    component_by_card = {
        card_id: component
        for component in ledger._identity_components()
        for card_id in component
    }

    scored_rows: list[dict[str, str]] = []
    correct = 0
    decided = 0
    for association in ledger.associations:
        if association.association_id not in true_relations:
            continue
        truth = true_relations[association.association_id]
        if truth not in {
            RelationDecision.SAME_EVENT.value,
            RelationDecision.DISTINCT_EVENTS.value,
        }:
            raise ValueError("truth relation must be SAME_EVENT or DISTINCT_EVENTS")
        left_card_id = ledger._origin_card_by_candidate[association.candidate_ids[0]]
        right_card_id = ledger._origin_card_by_candidate[association.candidate_ids[1]]
        component_relation = (
            RelationDecision.SAME_EVENT.value
            if component_by_card[left_card_id] == component_by_card[right_card_id]
            else RelationDecision.DISTINCT_EVENTS.value
        )
        if association.status == "PENDING":
            predicted = "PENDING"
        elif association.status == "CONFIRMED_SAME_EVENT":
            if component_relation != RelationDecision.SAME_EVENT.value:
                raise ValueError("ledger conflict: same-event status disagrees with components")
            predicted = RelationDecision.SAME_EVENT.value
        elif association.status in {"CONFIRMED_DISTINCT", "SPLIT_TO_DISTINCT"}:
            if component_relation != RelationDecision.DISTINCT_EVENTS.value:
                raise ValueError("ledger conflict: distinct status disagrees with components")
            predicted = RelationDecision.DISTINCT_EVENTS.value
        else:
            raise ValueError(f"unsupported ledger association state: {association.status}")
        if predicted == "PENDING":
            status = "UNDECIDED"
        else:
            decided += 1
            is_correct = predicted == truth
            correct += int(is_correct)
            status = "CORRECT" if is_correct else "INCORRECT"
        scored_rows.append(
            {
                "association_id": association.association_id,
                "ledger_status": association.status,
                "component_relation": component_relation,
                "predicted_relation": predicted,
                "true_relation": truth,
                "status": status,
            }
        )
    pair_count = len(scored_rows)
    return {
        "prediction_source": "AlertLedger.associations",
        "association_count": len(associations),
        "pair_count": pair_count,
        "unlabeled_pair_count": len(associations) - pair_count,
        "decided_pair_count": decided,
        "undecided_pair_count": pair_count - decided,
        "correct_decisions": correct,
        "incorrect_decisions": decided - correct,
        "accuracy": correct / decided if decided else None,
        "status": "SCORED" if decided else "UNAVAILABLE_NO_RESOLVED_PAIRS",
        "pairs": scored_rows,
    }
