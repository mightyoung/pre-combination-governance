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

from .alert_governance_v2 import severity_for_risk_flag


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
    NOTICE_CORRECTED = "NOTICE_CORRECTED"
    NOTICE_CANCELLED = "NOTICE_CANCELLED"


class ApplyStatus(StrEnum):
    EMITTED = "EMITTED"
    COALESCED = "COALESCED_IN_PLACE"
    DUPLICATE_REPLAY = "DUPLICATE_REPLAY_IGNORED"
    DUPLICATE_NOTICE_VERSION = "DUPLICATE_NOTICE_VERSION_IGNORED"
    STALE_NOTICE_VERSION = "STALE_NOTICE_VERSION_IGNORED"


_PROTECTED_ACTIONS = frozenset(
    {
        ActionKind.ASSOCIATION_CONFIRMED,
        ActionKind.RISK_ESCALATION,
        ActionKind.COUNTER_EVIDENCE,
        ActionKind.EVENT_SPLIT,
        ActionKind.DISTINCT_EVENT_ALERT,
        ActionKind.NOTICE_CORRECTED,
        ActionKind.NOTICE_CANCELLED,
    }
)
_RISK_STAGES = frozenset({"PRECAUTIONARY", "CONFIRMED", "ESCALATED"})
_ASSOCIATION_STATES = frozenset(
    {"SAME_CONFIRMED", "DIFFERENT_CONFIRMED", "UNKNOWN_PENDING", "CONFLICT_PENDING"}
)


def _is_single_flag_warning_to_critical(
    previous_risk_flags: tuple[str, ...], current_risk_flags: tuple[str, ...]
) -> bool:
    """Recognize only the public, mapped single-flag WARNING to CRITICAL rise."""
    if len(previous_risk_flags) != 1 or len(current_risk_flags) != 1:
        return False
    try:
        previous_severity = severity_for_risk_flag(previous_risk_flags[0])
        current_severity = severity_for_risk_flag(current_risk_flags[0])
    except ValueError:
        return False
    return previous_severity == "WARNING" and current_severity == "CRITICAL"


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
    When supplied, `notice_version` is a card-scoped experimental ordering
    input; it is not a production versioning contract.
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
    risk_flags: tuple[str, ...]
    risk_basis_ids: tuple[str, ...]
    source_times: tuple[str, ...]
    observed_at_times: tuple[str, ...]
    experiment_batch_id: str
    association_state: str
    dedup_episode_interval_key: str
    trigger_known_time: str | None = None
    detected_at: str | None = None
    notice_version: int | None = None

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
        if self.association_state not in _ASSOCIATION_STATES:
            raise ValueError("association_state must use a V2 association state")
        if not isinstance(self.dedup_episode_interval_key, str) or not self.dedup_episode_interval_key.strip():
            raise ValueError("dedup_episode_interval_key must be an explicit experiment value")
        if self.notice_version is not None and (
            isinstance(self.notice_version, bool)
            or not isinstance(self.notice_version, int)
            or self.notice_version < 1
        ):
            raise ValueError("notice_version must be a positive integer when supplied")
        _parse_utc(self.received_at, "received_at")
        for label in ("trigger_known_time", "detected_at"):
            value = getattr(self, label)
            if value is not None:
                _parse_utc(value, label)
        for label in (
            "observation_ids",
            "source_ids",
            "candidate_episode_ids",
            "association_ids",
            "evidence_refs",
            "risk_flags",
            "risk_basis_ids",
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
    risk_flags: tuple[str, ...]
    risk_basis_ids: tuple[str, ...]
    source_times: tuple[str, ...]
    observed_at_times: tuple[str, ...]
    experiment_batch_id: str
    association_state: str
    dedup_episode_interval_key: str
    trigger_known_time: str | None
    detected_at: str | None
    simulated_card_update_delay_seconds: float
    notice_version: int | None = None

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
            risk_flags=intent.risk_flags,
            risk_basis_ids=intent.risk_basis_ids,
            source_times=intent.source_times,
            observed_at_times=intent.observed_at_times,
            experiment_batch_id=intent.experiment_batch_id,
            association_state=intent.association_state,
            dedup_episode_interval_key=intent.dedup_episode_interval_key,
            trigger_known_time=intent.trigger_known_time,
            detected_at=intent.detected_at,
            simulated_card_update_delay_seconds=0.0,
            notice_version=intent.notice_version,
        )


@dataclass(frozen=True, slots=True)
class ActionNotification:
    """Synthetic notification record; no transport or visible receipt exists."""

    experiment_notification_id: str
    display_card_id: str
    kind: ActionKind
    risk_stage: str
    experiment_batch_id: str
    association_state: str
    dedup_episode_interval_key: str
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
    """Run one action policy over a synthetic stream, optionally version-gated."""

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
        self._notice_versions_by_card: dict[str, dict[int, ActionIntent]] = {}
        self._latest_notice_version_by_card: dict[str, int] = {}

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

    @property
    def duplicate_notice_version_count(self) -> int:
        return sum(
            decision.status is ApplyStatus.DUPLICATE_NOTICE_VERSION
            for decision in self._decisions
        )

    @property
    def stale_notice_version_count(self) -> int:
        return sum(
            decision.status is ApplyStatus.STALE_NOTICE_VERSION
            for decision in self._decisions
        )

    def card_revisions_for(self, display_card_id: str) -> tuple[CardRevision, ...]:
        return tuple(self._card_revisions.get(display_card_id, ()))

    def missed_important_update_ids(self) -> tuple[str, ...]:
        represented = {
            update.intent_id
            for notification in self._notifications
            for update in notification.updates
        }
        intentionally_ignored = {
            decision.intent_id
            for decision in self._decisions
            if decision.status
            in {
                ApplyStatus.DUPLICATE_REPLAY,
                ApplyStatus.DUPLICATE_NOTICE_VERSION,
                ApplyStatus.STALE_NOTICE_VERSION,
            }
        }
        return tuple(
            intent_id
            for intent_id, intent in self._seen_intents.items()
            if intent.kind in _PROTECTED_ACTIONS
            and intent_id not in represented
            and intent_id not in intentionally_ignored
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

        if intent.notice_version is not None:
            version = intent.notice_version
            versions_for_card = self._notice_versions_by_card.setdefault(
                intent.display_card_id, {}
            )
            previous_version = versions_for_card.get(version)
            if previous_version is not None and not self._same_notice_version_semantics(
                previous_version, intent
            ):
                raise ValueError(
                    "notice_version already exists with different semantic content"
                )
            latest_version = self._latest_notice_version_by_card.get(
                intent.display_card_id
            )
            if latest_version is not None and version < latest_version:
                versions_for_card.setdefault(version, intent)
                decision = self._record_ignored_notice_version(
                    intent,
                    status=ApplyStatus.STALE_NOTICE_VERSION,
                    reason="LOWER_NOTICE_VERSION_THAN_LATEST",
                )
                return decision
            if previous_version is not None:
                return self._record_ignored_notice_version(
                    intent,
                    status=ApplyStatus.DUPLICATE_NOTICE_VERSION,
                    reason="SAME_NOTICE_VERSION_DUPLICATE_NO_REFRESH",
                )

        revisions = self._card_revisions.setdefault(intent.display_card_id, [])
        card_revision = CardRevision.from_intent(len(revisions) + 1, intent)
        revisions.append(card_revision)

        target_index = None
        coalescing_decision_reason = None
        if (
            self.mode is PolicyMode.CARD_COALESCE
            and intent.kind is ActionKind.ASSOCIATION_PENDING
            and intent.kind not in _PROTECTED_ACTIONS
        ):
            target_index = self._coalescing_target(intent)
            if target_index is not None:
                previous_risk_flags = self._notifications[target_index].updates[-1].risk_flags
                if _is_single_flag_warning_to_critical(
                    previous_risk_flags, intent.risk_flags
                ):
                    target_index = None
                    coalescing_decision_reason = "SINGLE_FLAG_SEVERITY_ESCALATION"

        if target_index is None:
            notification_id = f"EXPERIMENT-NOTIFY-{len(self._notifications) + 1:04d}"
            notification = ActionNotification(
                experiment_notification_id=notification_id,
                display_card_id=intent.display_card_id,
                kind=intent.kind,
                risk_stage=intent.risk_stage,
                experiment_batch_id=intent.experiment_batch_id,
                association_state=intent.association_state,
                dedup_episode_interval_key=intent.dedup_episode_interval_key,
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
            elif coalescing_decision_reason is not None:
                decision_reason = coalescing_decision_reason
            elif intent.kind is ActionKind.ASSOCIATION_PENDING:
                decision_reason = "NO_MATCHING_EPISODE_INTERVAL_KEY_WITHIN_WINDOW"
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
            decision_reason = "SAME_CARD_EPISODE_INTERVAL_KEY_WITHIN_WINDOW"

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
        if intent.notice_version is not None:
            self._notice_versions_by_card.setdefault(intent.display_card_id, {})[
                intent.notice_version
            ] = intent
            self._latest_notice_version_by_card[intent.display_card_id] = (
                intent.notice_version
            )
        return decision

    def _record_ignored_notice_version(
        self,
        intent: ActionIntent,
        *,
        status: ApplyStatus,
        reason: str,
    ) -> ApplyDecision:
        decision = ApplyDecision(
            intent_id=intent.intent_id,
            status=status,
            experiment_notification_id=None,
            card_revision=None,
            simulated_card_update_delay_seconds=None,
            decision_reason=reason,
        )
        self._seen_intents[intent.intent_id] = intent
        self._decision_by_intent[intent.intent_id] = decision
        self._decisions.append(decision)
        return decision

    @staticmethod
    def _same_semantics(first: ActionIntent, replay: ActionIntent) -> bool:
        return replace(replay, received_at=first.received_at) == first

    @staticmethod
    def _same_notice_version_semantics(
        first: ActionIntent, replay: ActionIntent
    ) -> bool:
        return replace(
            replay,
            intent_id=first.intent_id,
            received_at=first.received_at,
        ) == first

    def _coalescing_target(self, intent: ActionIntent) -> int | None:
        received = _parse_utc(intent.received_at, "received_at")
        for index in range(len(self._notifications) - 1, -1, -1):
            notification = self._notifications[index]
            if (
                notification.display_card_id != intent.display_card_id
                or notification.kind is not intent.kind
                or notification.risk_stage != intent.risk_stage
                or notification.association_state != intent.association_state
                or notification.experiment_batch_id != intent.experiment_batch_id
                or notification.dedup_episode_interval_key
                != intent.dedup_episode_interval_key
            ):
                continue
            first_episode_ids = set(notification.updates[0].candidate_episode_ids)
            if not first_episode_ids.intersection(intent.candidate_episode_ids):
                continue
            elapsed = (received - _parse_utc(notification.first_received_at, "first_received_at")).total_seconds()
            if 0 <= elapsed <= self.merge_window_seconds:
                return index
        return None


def protected_action_kinds() -> frozenset[ActionKind]:
    """Return kinds that must always have their own notification action."""
    return _PROTECTED_ACTIONS
