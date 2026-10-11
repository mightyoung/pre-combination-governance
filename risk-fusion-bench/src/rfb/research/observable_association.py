"""Observable-only event-association development rules.

This module sees measurement fields and their availability times only. It does
not read scenario labels, event identity, card state, or scorer truth. All rule
outputs are proposals and cannot confirm an event identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import math
from typing import Any, Protocol, runtime_checkable


_ALLOWED_FIELD_NAMES = frozenset(
    {
        "asset_id",
        "asset_binding_status",
        "modality",
        "value",
        "unit",
        "value_error",
        "position_m",
        "position_error_m",
        "quality_status",
        "calibration_status",
        "source_time",
        "risk_flag",
        "acquisition_lineage",
    }
)
_ENUM_VALUES = {
    "asset_binding_status": frozenset({"VERIFIED", "UNKNOWN", "CONFLICTING"}),
    "modality": frozenset({"TEMPERATURE", "THERMAL_IMAGE", "VIBRATION", "UNKNOWN"}),
    "quality_status": frozenset({"GOOD", "DEGRADED", "UNKNOWN"}),
    "calibration_status": frozenset({"CURRENT", "EXPIRED", "UNKNOWN"}),
    "risk_flag": frozenset(
        {"EXPOSURE", "EXPOSURE_HIGH", "RECOVERY", "NORMAL", "UNKNOWN"}
    ),
}
_NUMERIC_FIELDS = frozenset({"value", "value_error", "position_error_m"})


def _timestamp(value: str, label: str) -> datetime:
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


def _format_timestamp(value: datetime) -> str:
    precision = "microseconds" if value.microsecond else "seconds"
    return value.astimezone(timezone.utc).isoformat(timespec=precision).replace(
        "+00:00", "Z"
    )


def _is_json_like(value: Any) -> bool:
    if value is None or type(value) in (str, int, bool):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is tuple:
        return all(_is_json_like(item) for item in value)
    return False


def _validate_field_value(name: str, value: Any) -> None:
    if not _is_json_like(value):
        raise ValueError("field values must be finite JSON-like scalars or tuples")
    if name in _ENUM_VALUES and value not in _ENUM_VALUES[name]:
        raise ValueError(f"{name} has an unsupported observable value")
    if name == "asset_id" and value is not None and (
        not isinstance(value, str) or not value.strip()
    ):
        raise ValueError("asset_id must be a non-empty string or None")
    if name in _NUMERIC_FIELDS and value is not None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be numeric or None")
        if name != "value" and value < 0:
            raise ValueError(f"{name} cannot be negative")
    if name == "position_m" and value is not None:
        if (
            not isinstance(value, tuple)
            or len(value) != 2
            or any(isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)) for coordinate in value)
        ):
            raise ValueError("position_m must be a pair of numeric coordinates or None")
    if name == "source_time" and value is not None:
        _timestamp(value, "source_time")
    if name == "acquisition_lineage" and value is not None:
        if (
            not isinstance(value, tuple)
            or not value
            or any(not isinstance(part, str) or not part.strip() for part in value)
        ):
            raise ValueError("acquisition_lineage must be a non-empty tuple of strings")


@dataclass(frozen=True, slots=True)
class KnownField:
    """One allowlisted field with source availability and first-known times."""

    name: str
    value: Any
    actual_available_at: str
    earliest_known_at: str

    def __post_init__(self) -> None:
        if self.name not in _ALLOWED_FIELD_NAMES:
            raise ValueError(f"field is not observable to the algorithm: {self.name}")
        _validate_field_value(self.name, self.value)
        actual = _timestamp(self.actual_available_at, "actual_available_at")
        known = _timestamp(self.earliest_known_at, "earliest_known_at")
        if known < actual:
            raise ValueError("earliest_known_at cannot precede actual_available_at")
        object.__setattr__(self, "actual_available_at", _format_timestamp(actual))
        object.__setattr__(self, "earliest_known_at", _format_timestamp(known))


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    """An observation ID, its arrival, and only allowlisted field facts."""

    observation_id: str
    id_actual_available_at: str
    id_earliest_known_at: str
    received_at: str
    fields: tuple[KnownField, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.observation_id, str) or not self.observation_id.strip():
            raise ValueError("observation_id must be a non-empty opaque ID")
        actual = _timestamp(self.id_actual_available_at, "id_actual_available_at")
        known = _timestamp(self.id_earliest_known_at, "id_earliest_known_at")
        received = _timestamp(self.received_at, "received_at")
        if known < actual:
            raise ValueError("observation ID earliest-known time precedes availability")
        if not isinstance(self.fields, tuple) or any(
            not isinstance(field, KnownField) for field in self.fields
        ):
            raise ValueError("fields must be a tuple of KnownField values")
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("one record cannot repeat a field name")
        object.__setattr__(self, "id_actual_available_at", _format_timestamp(actual))
        object.__setattr__(self, "id_earliest_known_at", _format_timestamp(known))
        object.__setattr__(self, "received_at", _format_timestamp(received))


@dataclass(frozen=True, slots=True)
class FrozenObservation:
    """One deduplicated observation containing only facts known by the cutoff."""

    observation_id: str
    received_at: str
    fields: tuple[KnownField, ...]
    id_actual_available_at: str | None = None
    id_earliest_known_at: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.observation_id, str) or not self.observation_id.strip():
            raise ValueError("observation_id must be a non-empty opaque ID")
        received = _timestamp(self.received_at, "received_at")
        if not isinstance(self.fields, tuple) or any(
            not isinstance(field, KnownField) for field in self.fields
        ):
            raise ValueError("fields must be a tuple of KnownField values")
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("one frozen observation cannot repeat a field name")

        id_actual = self.id_actual_available_at
        id_known = self.id_earliest_known_at
        if id_actual is None and id_known is None:
            # A manually constructed observation without ID provenance is only
            # considered known when it has arrived; this is conservative.
            id_actual = id_known = _format_timestamp(received)
        elif id_actual is None or id_known is None:
            raise ValueError("observation ID availability times must be supplied together")
        actual = _timestamp(id_actual, "id_actual_available_at")
        known = _timestamp(id_known, "id_earliest_known_at")
        if known < actual:
            raise ValueError("observation ID earliest-known time precedes availability")

        object.__setattr__(self, "received_at", _format_timestamp(received))
        object.__setattr__(self, "id_actual_available_at", _format_timestamp(actual))
        object.__setattr__(self, "id_earliest_known_at", _format_timestamp(known))

    def value(self, name: str) -> Any:
        for field in self.fields:
            if field.name == name:
                return field.value
        return None

    def field(self, name: str) -> KnownField | None:
        return next((field for field in self.fields if field.name == name), None)


@dataclass(frozen=True, slots=True)
class FrozenObservablePrefix:
    """Immutable inference input; hidden facts and labels are not represented."""

    as_of: str
    observations: tuple[FrozenObservation, ...]

    def __post_init__(self) -> None:
        cutoff = _timestamp(self.as_of, "as_of")
        object.__setattr__(self, "as_of", _format_timestamp(cutoff))
        self.validate_visibility()

    def validate_visibility(self) -> None:
        """Reject future facts even when a prefix was built or changed directly."""
        cutoff = _timestamp(self.as_of, "as_of")
        if not isinstance(self.observations, tuple) or any(
            not isinstance(item, FrozenObservation) for item in self.observations
        ):
            raise ValueError("observations must be a tuple of FrozenObservation values")

        seen_ids: set[str] = set()
        for observation in self.observations:
            if observation.observation_id in seen_ids:
                raise ValueError("observable prefix cannot repeat an observation ID")
            seen_ids.add(observation.observation_id)

            id_actual = _timestamp(
                observation.id_actual_available_at, "id_actual_available_at"
            )
            id_known = _timestamp(
                observation.id_earliest_known_at, "id_earliest_known_at"
            )
            if id_known < id_actual:
                raise ValueError("observation ID earliest-known time precedes availability")
            if id_known > cutoff:
                raise ValueError("observation ID was not known by prefix as_of")

            received = _timestamp(observation.received_at, "received_at")
            if received > cutoff:
                raise ValueError("observation arrived after prefix as_of")
            if not isinstance(observation.fields, tuple) or any(
                not isinstance(field, KnownField) for field in observation.fields
            ):
                raise ValueError("fields must be a tuple of KnownField values")
            for field in observation.fields:
                actual = _timestamp(field.actual_available_at, "actual_available_at")
                known = _timestamp(field.earliest_known_at, "earliest_known_at")
                if known < actual:
                    raise ValueError("field earliest-known time precedes actual availability")
                if known > cutoff:
                    raise ValueError("field was not known by prefix as_of")

    def observation(self, observation_id: str) -> FrozenObservation:
        self.validate_visibility()
        for observation in self.observations:
            if observation.observation_id == observation_id:
                return observation
        raise KeyError(observation_id)


def _compatible_lineage(first: Any, second: Any) -> bool:
    if first == second:
        return True
    return (
        isinstance(first, tuple)
        and isinstance(second, tuple)
        and bool(first)
        and bool(second)
        and first[0] == second[0]
    )


def _merge_observation_records(
    observation_id: str,
    records: list[ObservationRecord],
    *,
    as_of: datetime,
) -> FrozenObservation | None:
    visible_records = [
        record
        for record in records
        if _timestamp(record.received_at, "received_at") <= as_of
        and _timestamp(record.id_earliest_known_at, "id_earliest_known_at") <= as_of
    ]
    if not visible_records:
        return None
    actual_id_times = {record.id_actual_available_at for record in visible_records}
    if len(actual_id_times) != 1:
        raise ValueError("one observation_id cannot have conflicting availability times")

    facts_by_name: dict[str, list[KnownField]] = {}
    for record in visible_records:
        for fact in record.fields:
            if _timestamp(fact.earliest_known_at, "earliest_known_at") <= as_of:
                facts_by_name.setdefault(fact.name, []).append(fact)

    merged: list[KnownField] = []
    for name, facts in facts_by_name.items():
        facts.sort(key=lambda fact: _timestamp(fact.earliest_known_at, "earliest_known_at"))
        first = facts[0]
        for fact in facts[1:]:
            if fact.value == first.value:
                continue
            if name == "acquisition_lineage" and _compatible_lineage(
                first.value, fact.value
            ):
                continue
            if name == "risk_flag" and _timestamp(
                fact.earliest_known_at, "earliest_known_at"
            ) > _timestamp(first.earliest_known_at, "earliest_known_at"):
                continue
            raise ValueError(
                f"conflicting immutable field {name} for observation {observation_id}"
            )
        latest_time = max(
            _timestamp(fact.earliest_known_at, "earliest_known_at") for fact in facts
        )
        latest_facts = [
            fact
            for fact in facts
            if _timestamp(fact.earliest_known_at, "earliest_known_at") == latest_time
        ]
        if name == "risk_flag":
            selected = latest_facts[0]
            if any(fact.value != selected.value for fact in latest_facts[1:]):
                raise ValueError(f"ambiguous same-time risk_flag for {observation_id}")
        else:
            selected = first
            if name == "acquisition_lineage":
                if any(not _compatible_lineage(first.value, fact.value) for fact in facts):
                    raise ValueError(f"conflicting acquisition roots for {observation_id}")
        merged.append(selected)

    received_at = min(
        visible_records,
        key=lambda item: _timestamp(item.received_at, "received_at"),
    ).received_at
    return FrozenObservation(
        observation_id=observation_id,
        received_at=received_at,
        fields=tuple(sorted(merged, key=lambda fact: fact.name)),
        id_actual_available_at=next(iter(actual_id_times)),
        id_earliest_known_at=min(
            (record.id_earliest_known_at for record in visible_records),
            key=lambda value: _timestamp(value, "id_earliest_known_at"),
        ),
    )


def freeze_observable_prefix(
    records: tuple[ObservationRecord, ...] | list[ObservationRecord],
    *,
    as_of: str,
) -> FrozenObservablePrefix:
    """Filter by actual known/received times and collapse exact observation replays."""
    cutoff = _timestamp(as_of, "as_of")
    if not isinstance(records, (tuple, list)):
        raise ValueError("records must be a tuple or list of ObservationRecord")
    grouped: dict[str, list[ObservationRecord]] = {}
    for record in records:
        if not isinstance(record, ObservationRecord):
            raise ValueError("records must contain only ObservationRecord values")
        grouped.setdefault(record.observation_id, []).append(record)
    observations = tuple(
        frozen
        for observation_id in sorted(grouped)
        if (frozen := _merge_observation_records(
            observation_id, grouped[observation_id], as_of=cutoff
        ))
        is not None
    )
    return FrozenObservablePrefix(_format_timestamp(cutoff), observations)


class ProposalAction(StrEnum):
    """Non-final actions over a pair of observation candidates."""

    LINK_CANDIDATES = "LINK_CANDIDATES"
    RETAIN_SEPARATELY = "RETAIN_SEPARATELY"
    ABSTAIN = "ABSTAIN"


@dataclass(frozen=True, slots=True)
class InferenceConfig:
    """Synthetic development settings; none are production thresholds."""

    candidate_pair_window_seconds: int = 120
    same_asset_candidate_horizon_seconds: int = 600
    candidate_radius_m: float = 8.0
    position_margin_m: float = 1.0
    value_tolerance_c: float = 2.5
    parameter_status: str = "SYNTHETIC_TEST_VALUE_NOT_FOR_PRODUCTION"

    def __post_init__(self) -> None:
        for name in (
            "candidate_pair_window_seconds",
            "same_asset_candidate_horizon_seconds",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        for name in ("candidate_radius_m", "position_margin_m", "value_tolerance_c"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a non-negative finite number")
            if not math.isfinite(float(value)) or value < 0:
                raise ValueError(f"{name} must be a non-negative finite number")
        if self.parameter_status != "SYNTHETIC_TEST_VALUE_NOT_FOR_PRODUCTION":
            raise ValueError("inference parameters must remain marked synthetic-only")


@dataclass(frozen=True, slots=True)
class CandidatePair:
    """A method-independent pair of observable record IDs."""

    left_observation_id: str
    right_observation_id: str

    def __post_init__(self) -> None:
        for name in ("left_observation_id", "right_observation_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty observation ID")
        if self.left_observation_id == self.right_observation_id:
            raise ValueError("candidate pair must contain two distinct observations")
        left, right = sorted((self.left_observation_id, self.right_observation_id))
        object.__setattr__(self, "left_observation_id", left)
        object.__setattr__(self, "right_observation_id", right)


@dataclass(frozen=True, slots=True)
class AssociationProposal:
    """An explainable, non-final action produced from an observable prefix."""

    method: str
    pair: CandidatePair
    action: ProposalAction
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    independent_lineage_root_count: int
    decided_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.method, str) or not self.method.strip():
            raise ValueError("method must be a non-empty name")
        if not isinstance(self.pair, CandidatePair):
            raise TypeError("pair must be a CandidatePair")
        try:
            object.__setattr__(self, "action", ProposalAction(self.action))
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported candidate proposal action") from exc
        for name in ("reason_codes", "evidence_refs"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(
                not isinstance(item, str) or not item.strip() for item in values
            ):
                raise ValueError(f"{name} must be a tuple of non-empty strings")
        if isinstance(self.independent_lineage_root_count, bool) or not isinstance(
            self.independent_lineage_root_count, int
        ) or self.independent_lineage_root_count < 0:
            raise ValueError("independent_lineage_root_count must be a non-negative integer")
        decided = _timestamp(self.decided_at, "decided_at")
        object.__setattr__(self, "decided_at", _format_timestamp(decided))


@runtime_checkable
class AssociationMethod(Protocol):
    """Shared callable boundary for rule arms and a future Dempster-Shafer arm."""

    def __call__(
        self,
        prefix: FrozenObservablePrefix,
        pair: CandidatePair,
        *,
        config: InferenceConfig,
    ) -> AssociationProposal: ...


@dataclass(frozen=True, slots=True)
class FrozenAssociationOutput:
    """Canonical algorithm result captured before scorer-only truth is read."""

    canonical_json: bytes
    sha256: str


def _known_field(observation: FrozenObservation, name: str) -> KnownField | None:
    return observation.field(name)


def _field_value(observation: FrozenObservation, name: str) -> Any:
    return observation.value(name)


def _source_time(observation: FrozenObservation) -> datetime | None:
    value = _field_value(observation, "source_time")
    return _timestamp(value, "source_time") if value is not None else None


def _risk_is_abnormal(observation: FrozenObservation) -> bool:
    return _field_value(observation, "risk_flag") in {"EXPOSURE", "EXPOSURE_HIGH"}


def _position(observation: FrozenObservation) -> tuple[float, float] | None:
    value = _field_value(observation, "position_m")
    if value is None:
        return None
    return float(value[0]), float(value[1])


def _position_error(observation: FrozenObservation) -> float | None:
    value = _field_value(observation, "position_error_m")
    return None if value is None else float(value)


def _distance(
    first: tuple[float, float], second: tuple[float, float]
) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _asset_binding(observation: FrozenObservation) -> tuple[str | None, str | None]:
    return (
        _field_value(observation, "asset_id"),
        _field_value(observation, "asset_binding_status"),
    )


def _lineage_root(observation: FrozenObservation) -> str | None:
    value = _field_value(observation, "acquisition_lineage")
    if not value:
        return None
    return value[0]


def _root_count(left: FrozenObservation, right: FrozenObservation) -> int:
    roots = {_lineage_root(item) for item in (left, right)} - {None}
    return len(roots)


def _evidence_refs(pair: CandidatePair) -> tuple[str, ...]:
    return tuple(
        f"synthetic://observable/{observation_id}"
        for observation_id in (pair.left_observation_id, pair.right_observation_id)
    )


def _pair_observations(
    prefix: FrozenObservablePrefix, pair: CandidatePair
) -> tuple[FrozenObservation, FrozenObservation]:
    return prefix.observation(pair.left_observation_id), prefix.observation(
        pair.right_observation_id
    )


def _common_relation_guard(
    prefix: FrozenObservablePrefix,
    pair: CandidatePair,
    *,
    config: InferenceConfig,
    method: str,
) -> AssociationProposal | tuple[FrozenObservation, FrozenObservation]:
    left, right = _pair_observations(prefix, pair)
    roots = _root_count(left, right)

    left_asset, left_binding = _asset_binding(left)
    right_asset, right_binding = _asset_binding(right)
    if left_binding != "VERIFIED" or right_binding != "VERIFIED":
        return AssociationProposal(
            method,
            pair,
            ProposalAction.ABSTAIN,
            ("ASSET_BINDING_UNKNOWN_OR_UNVERIFIED",),
            _evidence_refs(pair),
            roots,
            prefix.as_of,
        )
    if not left_asset or not right_asset:
        return AssociationProposal(
            method,
            pair,
            ProposalAction.ABSTAIN,
            ("ASSET_BINDING_VALUE_MISSING",),
            _evidence_refs(pair),
            roots,
            prefix.as_of,
        )
    if left_asset != right_asset:
        return AssociationProposal(
            method,
            pair,
            ProposalAction.RETAIN_SEPARATELY,
            ("VERIFIED_ASSET_MISMATCH",),
            _evidence_refs(pair),
            roots,
            prefix.as_of,
        )

    left_time, right_time = _source_time(left), _source_time(right)
    if left_time is None or right_time is None:
        return AssociationProposal(
            method,
            pair,
            ProposalAction.ABSTAIN,
            ("SOURCE_TIME_UNKNOWN",),
            _evidence_refs(pair),
            roots,
            prefix.as_of,
        )
    low, high = sorted((left_time, right_time))
    if _has_recovery_between(prefix, left_asset, low, high):
        return AssociationProposal(
            method,
            pair,
            ProposalAction.RETAIN_SEPARATELY,
            ("OBSERVED_RECOVERY_BOUNDARY",),
            _evidence_refs(pair),
            roots,
            prefix.as_of,
        )
    elapsed = abs((right_time - left_time).total_seconds())
    if elapsed > config.candidate_pair_window_seconds:
        return AssociationProposal(
            method,
            pair,
            ProposalAction.ABSTAIN,
            ("SOURCE_TIME_GAP_OUTSIDE_SYNTHETIC_RULE_WINDOW",),
            _evidence_refs(pair),
            roots,
            prefix.as_of,
        )

    left_position, right_position = _position(left), _position(right)
    left_error, right_error = _position_error(left), _position_error(right)
    if (
        left_position is None
        or right_position is None
        or left_error is None
        or right_error is None
    ):
        return AssociationProposal(
            method,
            pair,
            ProposalAction.ABSTAIN,
            ("POSITION_OR_ERROR_UNKNOWN",),
            _evidence_refs(pair),
            roots,
            prefix.as_of,
        )
    if _distance(left_position, right_position) > (
        left_error + right_error + config.position_margin_m
    ):
        return AssociationProposal(
            method,
            pair,
            ProposalAction.ABSTAIN,
            ("POSITION_OUTSIDE_SYNTHETIC_ERROR_ENVELOPE",),
            _evidence_refs(pair),
            roots,
            prefix.as_of,
        )
    return left, right


def _has_recovery_between(
    prefix: FrozenObservablePrefix,
    asset_id: str,
    start: datetime,
    end: datetime,
) -> bool:
    for observation in prefix.observations:
        item_asset, binding = _asset_binding(observation)
        source_time = _source_time(observation)
        if (
            item_asset == asset_id
            and binding == "VERIFIED"
            and _field_value(observation, "risk_flag") == "RECOVERY"
            and source_time is not None
            and start < source_time < end
        ):
            return True
    return False


def build_candidate_universe(
    prefix: FrozenObservablePrefix, *, config: InferenceConfig
) -> tuple[CandidatePair, ...]:
    """Build one pair set from observable time/position/asset proximity only."""
    if not isinstance(prefix, FrozenObservablePrefix):
        raise TypeError("prefix must be a FrozenObservablePrefix")
    prefix.validate_visibility()
    if not isinstance(config, InferenceConfig):
        raise TypeError("config must be an InferenceConfig")
    candidates = [
        observation
        for observation in prefix.observations
        if _risk_is_abnormal(observation)
    ]
    pairs: set[CandidatePair] = set()
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            left_asset, left_binding = _asset_binding(left)
            right_asset, right_binding = _asset_binding(right)
            left_time, right_time = _source_time(left), _source_time(right)
            elapsed = (
                abs((right_time - left_time).total_seconds())
                if left_time is not None and right_time is not None
                else None
            )
            verified_same_asset = (
                left_binding == right_binding == "VERIFIED"
                and left_asset is not None
                and left_asset == right_asset
            )
            same_asset_candidate = verified_same_asset and (
                elapsed is None or elapsed <= config.same_asset_candidate_horizon_seconds
            )
            spatial_candidate = False
            left_position, right_position = _position(left), _position(right)
            if (
                elapsed is not None
                and elapsed <= config.candidate_pair_window_seconds
                and left_position is not None
                and right_position is not None
            ):
                left_error = _position_error(left) or 0.0
                right_error = _position_error(right) or 0.0
                spatial_candidate = _distance(left_position, right_position) <= (
                    config.candidate_radius_m + left_error + right_error
                )
            if same_asset_candidate or spatial_candidate:
                pairs.add(CandidatePair(left.observation_id, right.observation_id))
    return tuple(
        sorted(
            pairs,
            key=lambda pair: (pair.left_observation_id, pair.right_observation_id),
        )
    )


def time_asset_rule(
    prefix: FrozenObservablePrefix,
    pair: CandidatePair,
    *,
    config: InferenceConfig,
) -> AssociationProposal:
    """A conservative time/asset/position baseline with explicit abstention."""
    guarded = _common_relation_guard(
        prefix, pair, config=config, method="TIME_ASSET_RULE"
    )
    if isinstance(guarded, AssociationProposal):
        return guarded
    return AssociationProposal(
        "TIME_ASSET_RULE",
        pair,
        ProposalAction.LINK_CANDIDATES,
        ("VERIFIED_ASSET_MATCH", "TIME_AND_POSITION_COMPATIBLE"),
        _evidence_refs(pair),
        _root_count(*guarded),
        prefix.as_of,
    )


def multi_evidence_rule(
    prefix: FrozenObservablePrefix,
    pair: CandidatePair,
    *,
    config: InferenceConfig,
) -> AssociationProposal:
    """Require independent, calibrated, cross-modal support before linking."""
    guarded = _common_relation_guard(
        prefix, pair, config=config, method="MULTI_EVIDENCE_RULE"
    )
    if isinstance(guarded, AssociationProposal):
        return guarded
    left, right = guarded
    roots = _root_count(left, right)
    quality = (_field_value(left, "quality_status"), _field_value(right, "quality_status"))
    calibration = (
        _field_value(left, "calibration_status"),
        _field_value(right, "calibration_status"),
    )
    if quality != ("GOOD", "GOOD") or calibration != ("CURRENT", "CURRENT"):
        return AssociationProposal(
            "MULTI_EVIDENCE_RULE",
            pair,
            ProposalAction.ABSTAIN,
            ("QUALITY_OR_CALIBRATION_NOT_VERIFIED",),
            _evidence_refs(pair),
            roots,
            prefix.as_of,
        )

    modalities = {_field_value(left, "modality"), _field_value(right, "modality")}
    if modalities != {"TEMPERATURE", "THERMAL_IMAGE"}:
        return AssociationProposal(
            "MULTI_EVIDENCE_RULE",
            pair,
            ProposalAction.ABSTAIN,
            ("NO_COMPLEMENTARY_MODALITIES",),
            _evidence_refs(pair),
            roots,
            prefix.as_of,
        )
    if not (_risk_is_abnormal(left) and _risk_is_abnormal(right)):
        return AssociationProposal(
            "MULTI_EVIDENCE_RULE",
            pair,
            ProposalAction.ABSTAIN,
            ("RISK_EVIDENCE_NOT_POSITIVE_ON_BOTH_RECORDS",),
            _evidence_refs(pair),
            roots,
            prefix.as_of,
        )
    if roots < 2:
        return AssociationProposal(
            "MULTI_EVIDENCE_RULE",
            pair,
            ProposalAction.ABSTAIN,
            ("NO_INDEPENDENT_ACQUISITION_ROOTS",),
            _evidence_refs(pair),
            roots,
            prefix.as_of,
        )

    left_unit, right_unit = _field_value(left, "unit"), _field_value(right, "unit")
    if left_unit not in {"degC", "°C", "C"} or right_unit not in {
        "degC",
        "°C",
        "C",
    }:
        return AssociationProposal(
            "MULTI_EVIDENCE_RULE",
            pair,
            ProposalAction.ABSTAIN,
            ("UNIT_NOT_COMPARABLE_FOR_SYNTHETIC_RULE",),
            _evidence_refs(pair),
            roots,
            prefix.as_of,
        )
    left_value, right_value = _field_value(left, "value"), _field_value(right, "value")
    left_error, right_error = _field_value(left, "value_error"), _field_value(right, "value_error")
    if (
        left_value is None
        or right_value is None
        or left_error is None
        or right_error is None
    ):
        return AssociationProposal(
            "MULTI_EVIDENCE_RULE",
            pair,
            ProposalAction.ABSTAIN,
            ("VALUE_OR_ERROR_UNKNOWN",),
            _evidence_refs(pair),
            roots,
            prefix.as_of,
        )
    if abs(float(left_value) - float(right_value)) > (
        float(left_error) + float(right_error) + config.value_tolerance_c
    ):
        return AssociationProposal(
            "MULTI_EVIDENCE_RULE",
            pair,
            ProposalAction.ABSTAIN,
            ("VALUES_OUTSIDE_SYNTHETIC_ERROR_ENVELOPE",),
            _evidence_refs(pair),
            roots,
            prefix.as_of,
        )
    return AssociationProposal(
        "MULTI_EVIDENCE_RULE",
        pair,
        ProposalAction.LINK_CANDIDATES,
        (
            "VERIFIED_ASSET_MATCH",
            "TIME_AND_POSITION_COMPATIBLE",
            "CROSS_MODAL_SUPPORT",
            "QUALITY_CALIBRATION_VALID",
            "INDEPENDENT_ACQUISITION_ROOTS",
        ),
        _evidence_refs(pair),
        roots,
        prefix.as_of,
    )


def freeze_proposals(
    proposals: tuple[AssociationProposal, ...] | list[AssociationProposal],
) -> FrozenAssociationOutput:
    """Serialize canonical method output without scorer-only truth data."""
    if not isinstance(proposals, (tuple, list)) or any(
        not isinstance(proposal, AssociationProposal) for proposal in proposals
    ):
        raise ValueError("proposals must contain only AssociationProposal values")
    rows = [
        {
            "method": proposal.method,
            "pair": {
                "left_observation_id": proposal.pair.left_observation_id,
                "right_observation_id": proposal.pair.right_observation_id,
            },
            "action": proposal.action.value,
            "reason_codes": list(proposal.reason_codes),
            "evidence_refs": list(proposal.evidence_refs),
            "independent_lineage_root_count": proposal.independent_lineage_root_count,
            "decided_at": proposal.decided_at,
        }
        for proposal in proposals
    ]
    rows.sort(
        key=lambda row: (
            row["method"],
            row["pair"]["left_observation_id"],
            row["pair"]["right_observation_id"],
        )
    )
    payload = json.dumps(
        {"output_version": "observable-association-v1", "proposals": rows},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return FrozenAssociationOutput(payload, hashlib.sha256(payload).hexdigest())


def apply_proposal_to_alert_ledger(proposal: Any, ledger: Any) -> Any:
    """Send only a link proposal to the existing ledger's pending-association API."""
    from .alert_governance import AlertLedger

    if not isinstance(proposal, AssociationProposal):
        raise TypeError("proposal must be an AssociationProposal")
    if not isinstance(ledger, AlertLedger):
        raise TypeError("ledger must be an AlertLedger")
    if proposal.action is not ProposalAction.LINK_CANDIDATES:
        return None
    return ledger.propose_association(
        proposal.pair.left_observation_id,
        proposal.pair.right_observation_id,
        at=proposal.decided_at,
        rationale=(
            f"Observable rule proposal {proposal.method}; identity remains pending review."
        ),
        evidence_refs=proposal.evidence_refs,
    )
