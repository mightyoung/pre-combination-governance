"""Freeze declared, field-level facts visible at one processing prefix.

This small adapter is an audit boundary for the held-out action-policy study.
It does not infer event identity, certify lineage claims, or provide scorer
truth. Each policy arm should receive the same ``FrozenVisiblePrefix`` object
materialized once by the upstream trajectory generator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


PREFIX_PROVENANCE_FIELDS = frozenset(
    {
        "kind",
        "association_state",
        "display_card_id",
        "candidate_episode_ids",
        "dedup_episode_interval_key",
    }
)

_FORBIDDEN_FIELDS = frozenset(
    {
        "scenario_id",
        "scenario_class",
        "oracle_action_label",
        "oracle_label",
        "action_kind",
        "ground_truth",
        "ground_truth_event_id",
        "event_cluster_id",
        "truth_event_id",
    }
)
_FORBIDDEN_ACTION_KINDS = frozenset(
    {
        "ASSOCIATION_CONFIRMED",
        "RISK_ESCALATION",
        "COUNTER_EVIDENCE",
        "EVENT_SPLIT",
        "DISTINCT_EVENT_ALERT",
        "CONFIRM_NEW",
    }
)


def _parse_timestamp(value: str, label: str) -> datetime:
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


def _is_immutable_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, tuple):
        return all(_is_immutable_value(item) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class PrefixFieldFact:
    """One upstream field value with declared producer and first-known time."""

    name: str
    value: Any
    producer: str
    earliest_known_at: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("field name must be a non-empty string")
        if self.name in _FORBIDDEN_FIELDS:
            raise ValueError(f"scorer-only field is not allowed: {self.name}")
        if not isinstance(self.producer, str) or not self.producer.strip():
            raise ValueError("producer must be a non-empty string")
        if not _is_immutable_value(self.value):
            raise ValueError("field values must be immutable JSON-like scalars or tuples")
        if self.name == "kind" and self.value in _FORBIDDEN_ACTION_KINDS:
            raise ValueError("kind must be an observable alert kind, not an action label")
        known_at = _parse_timestamp(self.earliest_known_at, "earliest_known_at")
        object.__setattr__(
            self, "earliest_known_at", known_at.isoformat().replace("+00:00", "Z")
        )
        if not isinstance(self.evidence_refs, tuple) or any(
            not isinstance(ref, str) or not ref.strip() for ref in self.evidence_refs
        ):
            raise ValueError("evidence_refs must be a tuple of non-empty strings")


@dataclass(frozen=True, slots=True)
class FrozenVisiblePrefix:
    """Immutable, deterministic snapshot containing only facts known by ``as_of``."""

    as_of: str
    _fields: tuple[PrefixFieldFact, ...]

    def __post_init__(self) -> None:
        cutoff = _parse_timestamp(self.as_of, "as_of")
        if not isinstance(self._fields, tuple):
            raise ValueError("frozen fields must be a tuple")
        names: set[str] = set()
        for fact in self._fields:
            if not isinstance(fact, PrefixFieldFact):
                raise ValueError("frozen fields must contain only PrefixFieldFact values")
            if _parse_timestamp(fact.earliest_known_at, "earliest_known_at") > cutoff:
                raise ValueError(f"field {fact.name} is known after as_of")
            if fact.name in names:
                raise ValueError(f"duplicate prefix field: {fact.name}")
            names.add(fact.name)
        object.__setattr__(
            self, "as_of", cutoff.isoformat().replace("+00:00", "Z")
        )
        object.__setattr__(
            self, "_fields", tuple(sorted(self._fields, key=lambda fact: fact.name))
        )

    def value(self, name: str) -> Any:
        """Return one visible value or raise ``KeyError`` if it is not yet known."""
        for fact in self._fields:
            if fact.name == name:
                return fact.value
        raise KeyError(name)

    def as_record(self) -> dict[str, Any]:
        """Return a stable audit record including per-field provenance claims."""
        return {
            "as_of": self.as_of,
            "fields": {
                fact.name: {
                    "value": fact.value,
                    "producer": fact.producer,
                    "earliest_known_at": fact.earliest_known_at,
                    "evidence_refs": fact.evidence_refs,
                }
                for fact in self._fields
            },
        }


def freeze_visible_prefix(
    facts: tuple[PrefixFieldFact, ...] | list[PrefixFieldFact], *, as_of: str
) -> FrozenVisiblePrefix:
    """Project the latest non-conflicting version of each field known by ``as_of``.

    Future facts are excluded before field selection. If two distinct values for
    one field have the same earliest-known timestamp, the adapter fails closed
    rather than inventing a tie-breaker or merging potentially distinct events.
    """
    cutoff = _parse_timestamp(as_of, "as_of")
    if not isinstance(facts, (tuple, list)):
        raise ValueError("facts must be a tuple or list of PrefixFieldFact")

    visible: dict[str, list[tuple[datetime, PrefixFieldFact]]] = {}
    for fact in facts:
        if not isinstance(fact, PrefixFieldFact):
            raise ValueError("facts must contain only PrefixFieldFact values")
        known_at = _parse_timestamp(fact.earliest_known_at, "earliest_known_at")
        if known_at <= cutoff:
            visible.setdefault(fact.name, []).append((known_at, fact))

    selected: list[PrefixFieldFact] = []
    for name, versions in visible.items():
        latest_at = max(known_at for known_at, _ in versions)
        latest = [fact for known_at, fact in versions if known_at == latest_at]
        if len(latest) > 1:
            first = latest[0]
            if any(
                (fact.value, fact.producer, fact.evidence_refs)
                != (first.value, first.producer, first.evidence_refs)
                for fact in latest[1:]
            ):
                raise ValueError(f"ambiguous same-time facts for field: {name}")
            # PrefixFieldFact canonicalizes UTC text, so equivalent duplicate
            # facts are identical in the audit record regardless of input order.
        selected.append(latest[0])

    selected.sort(key=lambda fact: fact.name)
    normalized_as_of = cutoff.isoformat().replace("+00:00", "Z")
    return FrozenVisiblePrefix(normalized_as_of, tuple(selected))
