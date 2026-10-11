"""Experimental notification coalescing policies, isolated from AlertLedger.

This module compares per-association reminders with card-level coalescing. It
is a pure in-memory experiment harness, not the default alert path. The intent
ID, batch ID, and window are experiment inputs, not approved production keys
or intervals. Card evidence revisions are recorded immediately and separately
from whether a new notification action is emitted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum


class PolicyMode(StrEnum):
    PER_ASSOCIATION = "PER_ASSOCIATION"
    CARD_COALESCE = "CARD_COALESCE"


class ActionKind(StrEnum):
    ASSOCIATION_PENDING = "ASSOCIATION_PENDING"
    ASSOCIATION_CONFIRMED = "ASSOCIATION_CONFIRMED"
    RISK_ESCALATION = "RISK_ESCALATION"
    COUNTER_EVIDENCE = "COUNTER_EVIDENCE"
    EVENT_SPLIT = "EVENT_SPLIT"
    DISTINCT_EVENT_ALERT = "DISTINCT_EVENT_ALERT"


class ApplyStatus(StrEnum):
    EMITTED = "EMITTED"
    COALESCED = "COALESCED_IN_PLACE"
    DUPLICATE_REPLAY = "DUPLICATE_REPLAY_IGNORED"


_PROTECTED_ACTIONS = frozenset(
    {
        ActionKind.ASSOCIATION_CONFIRMED,
        ActionKind.RISK_ESCALATION,
        ActionKind.COUNTER_EVIDENCE,
        ActionKind.EVENT_SPLIT,
        ActionKind.DISTINCT_EVENT_ALERT,
    }
)
_RISK_STAGES = frozenset({"PRECAUTIONARY", "CONFIRMED", "ESCALATED"})


def _parse_utc(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be an ISO-8601 string with UTC offset")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 string with UTC offset") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _string_tuple(values: tuple[str, ...], label: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{label} must be a tuple of strings")
    if (not allow_empty and not values) or any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{label} must contain non-empty strings")
    return values


@dataclass(frozen=True, slots=True)
class ActionIntent:
    """One semantic card update and its possible notification action.

    `received_at` is synthetic processing time. Source and observation times
    remain separate immutable values; the experiment never refreshes them.
    """

    intent_id: str
    display_card_id: str
    kind: ActionKind
    risk_stage: str
    received_at: str
    observation_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    candidate_episode_ids: tuple[str, ...]
    association_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    source_times: tuple[str, ...]
    observed_at_times: tuple[str, ...]
    experiment_batch_id: str

    def __post_init__(self) -> None:
        for label in ("intent_id", "display_card_id", "risk_stage", "experiment_batch_id"):
            value = getattr(self, label)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must be a non-empty string")
        try:
            object.__setattr__(self, "kind", ActionKind(self.kind))
        except (TypeError, ValueError) as exc:
            raise ValueError("kind must be a known experiment ActionKind") from exc
        if self.risk_stage not in _RISK_STAGES:
            raise ValueError("risk_stage must use an existing alert stage")
        _parse_utc(self.received_at, "received_at")
        for label in (
            "observation_ids",
            "source_ids",
            "candidate_episode_ids",
            "association_ids",
            "evidence_refs",
            "source_times",
            "observed_at_times",
        ):
            values = _string_tuple(
                getattr(self, label),
                label,
                allow_empty=label in {"association_ids"},
            )
            object.__setattr__(self, label, values)
        if not self.evidence_refs:
            raise ValueError("evidence_refs are required for an experimental update")
        for value in self.source_times:
            _parse_utc(value, "source_time")
        for value in self.observed_at_times:
            _parse_utc(value, "observed_at")


@dataclass(frozen=True, slots=True)
class CardRevision:
    revision: int
    intent_id: str
    display_card_id: str
    kind: ActionKind
    risk_stage: str
    received_at: str
    observation_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    candidate_episode_ids: tuple[str, ...]
    association_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    source_times: tuple[str, ...]
    observed_at_times: tuple[str, ...]
    experiment_batch_id: str
    simulated_card_update_delay_seconds: float

    @classmethod
    def from_intent(cls, revision: int, intent: ActionIntent) -> CardRevision:
        return cls(
            revision=revision,
            intent_id=intent.intent_id,
            display_card_id=intent.display_card_id,
            kind=intent.kind,
            risk_stage=intent.risk_stage,
            received_at=intent.received_at,
            observation_ids=intent.observation_ids,
            source_ids=intent.source_ids,
            candidate_episode_ids=intent.candidate_episode_ids,
            association_ids=intent.association_ids,
            evidence_refs=intent.evidence_refs,
            source_times=intent.source_times,
            observed_at_times=intent.observed_at_times,
            experiment_batch_id=intent.experiment_batch_id,
            simulated_card_update_delay_seconds=0.0,
        )


@dataclass(frozen=True, slots=True)
class ActionNotification:
    """Synthetic notification record; no transport or visible receipt exists."""

    experiment_notification_id: str
    display_card_id: str
    kind: ActionKind
    risk_stage: str
    experiment_batch_id: str
    first_received_at: str
    latest_received_at: str
    updates: tuple[CardRevision, ...]

    @property
    def content_revision_count(self) -> int:
        return len(self.updates)


@dataclass(frozen=True, slots=True)
class ApplyDecision:
    intent_id: str
    status: ApplyStatus
    experiment_notification_id: str | None
    card_revision: int | None
    simulated_card_update_delay_seconds: float | None
    actual_visible_at: None = None
    decision_reason: str = ""
    coalescing_elapsed_seconds: float | None = None
    coalescing_window_seconds: float | None = None


class ReminderActionLedger:
    """Run one explicit action policy over an ordered synthetic intent stream."""

    def __init__(self, *, mode: PolicyMode, merge_window_seconds: float) -> None:
        try:
            self.mode = PolicyMode(mode)
        except (TypeError, ValueError) as exc:
            raise ValueError("mode must be PER_ASSOCIATION or CARD_COALESCE") from exc
        if isinstance(merge_window_seconds, bool) or not isinstance(merge_window_seconds, (int, float)):
            raise ValueError("merge_window_seconds must be a non-negative finite number")
        if not math.isfinite(float(merge_window_seconds)) or merge_window_seconds < 0:
            raise ValueError("merge_window_seconds must be a non-negative finite number")
        self.merge_window_seconds = float(merge_window_seconds)
        self._card_revisions: dict[str, list[CardRevision]] = {}
        self._notifications: list[ActionNotification] = []
        self._decisions: list[ApplyDecision] = []
        self._seen_intents: dict[str, ActionIntent] = {}
        self._decision_by_intent: dict[str, ApplyDecision] = {}

    @property
    def notifications(self) -> tuple[ActionNotification, ...]:
        return tuple(self._notifications)

    @property
    def decisions(self) -> tuple[ApplyDecision, ...]:
        return tuple(self._decisions)

    @property
    def notification_action_count(self) -> int:
        return len(self._notifications)

    @property
    def coalesced_update_count(self) -> int:
        return sum(decision.status is ApplyStatus.COALESCED for decision in self._decisions)

    @property
    def duplicate_replay_count(self) -> int:
        return sum(decision.status is ApplyStatus.DUPLICATE_REPLAY for decision in self._decisions)

    def card_revisions_for(self, display_card_id: str) -> tuple[CardRevision, ...]:
        return tuple(self._card_revisions.get(display_card_id, ()))

    def missed_important_update_ids(self) -> tuple[str, ...]:
        represented = {
            update.intent_id
            for notification in self._notifications
            for update in notification.updates
        }
        return tuple(
            intent_id
            for intent_id, intent in self._seen_intents.items()
            if intent.kind in _PROTECTED_ACTIONS and intent_id not in represented
        )

    def apply(self, intent: ActionIntent) -> ApplyDecision:
        if not isinstance(intent, ActionIntent):
            raise TypeError("intent must be an ActionIntent")
        previous = self._seen_intents.get(intent.intent_id)
        if previous is not None:
            if not self._same_semantics(previous, intent):
                raise ValueError("intent_id already exists with different semantic content")
            original = self._decision_by_intent[intent.intent_id]
            decision = ApplyDecision(
                intent_id=intent.intent_id,
                status=ApplyStatus.DUPLICATE_REPLAY,
                experiment_notification_id=original.experiment_notification_id,
                card_revision=None,
                simulated_card_update_delay_seconds=None,
                decision_reason="EXACT_INTENT_REPLAY_NO_REFRESH",
            )
            self._decisions.append(decision)
            return decision

        revisions = self._card_revisions.setdefault(intent.display_card_id, [])
        card_revision = CardRevision.from_intent(len(revisions) + 1, intent)
        revisions.append(card_revision)

        target_index = None
        if (
            self.mode is PolicyMode.CARD_COALESCE
            and intent.kind is ActionKind.ASSOCIATION_PENDING
            and intent.kind not in _PROTECTED_ACTIONS
        ):
            target_index = self._coalescing_target(intent)

        if target_index is None:
            notification_id = f"EXPERIMENT-NOTIFY-{len(self._notifications) + 1:04d}"
            notification = ActionNotification(
                experiment_notification_id=notification_id,
                display_card_id=intent.display_card_id,
                kind=intent.kind,
                risk_stage=intent.risk_stage,
                experiment_batch_id=intent.experiment_batch_id,
                first_received_at=intent.received_at,
                latest_received_at=intent.received_at,
                updates=(card_revision,),
            )
            self._notifications.append(notification)
            status = ApplyStatus.EMITTED
            coalescing_elapsed = None
            if self.mode is PolicyMode.PER_ASSOCIATION:
                decision_reason = "PER_ASSOCIATION_POLICY"
            elif intent.kind in _PROTECTED_ACTIONS:
                decision_reason = "PROTECTED_ACTION_KIND"
            elif intent.kind is ActionKind.ASSOCIATION_PENDING:
                decision_reason = "NO_SAME_CARD_KIND_STAGE_BATCH_WITHIN_WINDOW"
            else:
                decision_reason = "NO_COALESCING_RULE_FOR_ACTION_KIND"
        else:
            prior = self._notifications[target_index]
            coalescing_elapsed = (
                _parse_utc(intent.received_at, "received_at")
                - _parse_utc(prior.first_received_at, "first_received_at")
            ).total_seconds()
            latest = max(
                (
                    _parse_utc(prior.latest_received_at, "latest_received_at"),
                    _parse_utc(intent.received_at, "received_at"),
                )
            ).isoformat().replace("+00:00", "Z")
            notification = replace(
                prior,
                latest_received_at=latest,
                updates=prior.updates + (card_revision,),
            )
            self._notifications[target_index] = notification
            notification_id = notification.experiment_notification_id
            status = ApplyStatus.COALESCED
            decision_reason = "SAME_CARD_KIND_STAGE_BATCH_WITHIN_WINDOW"

        decision = ApplyDecision(
            intent_id=intent.intent_id,
            status=status,
            experiment_notification_id=notification_id,
            card_revision=card_revision.revision,
            simulated_card_update_delay_seconds=0.0,
            decision_reason=decision_reason,
            coalescing_elapsed_seconds=coalescing_elapsed,
            coalescing_window_seconds=(
                self.merge_window_seconds
                if self.mode is PolicyMode.CARD_COALESCE
                and intent.kind is ActionKind.ASSOCIATION_PENDING
                else None
            ),
        )
        self._seen_intents[intent.intent_id] = intent
        self._decision_by_intent[intent.intent_id] = decision
        self._decisions.append(decision)
        return decision

    @staticmethod
    def _same_semantics(first: ActionIntent, replay: ActionIntent) -> bool:
        return replace(replay, received_at=first.received_at) == first

    def _coalescing_target(self, intent: ActionIntent) -> int | None:
        received = _parse_utc(intent.received_at, "received_at")
        for index in range(len(self._notifications) - 1, -1, -1):
            notification = self._notifications[index]
            if (
                notification.display_card_id != intent.display_card_id
                or notification.kind is not intent.kind
                or notification.risk_stage != intent.risk_stage
                or notification.experiment_batch_id != intent.experiment_batch_id
            ):
                continue
            elapsed = (received - _parse_utc(notification.first_received_at, "first_received_at")).total_seconds()
            if 0 <= elapsed <= self.merge_window_seconds:
                return index
        return None


def protected_action_kinds() -> frozenset[ActionKind]:
    """Return kinds that must always have their own notification action."""
    return _PROTECTED_ACTIONS
