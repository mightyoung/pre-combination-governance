"""Fail-closed v6.13 decimal-byte capacity telemetry."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from numbers import Integral
from typing import Any, Mapping
from .contracts.canonical_json import canonical_bytes

DECIMAL_GB = 1_000_000_000
CAPACITY_DRAIN_BYTES = 24 * DECIMAL_GB
CAPACITY_HARD_LIMIT_BYTES = 25 * DECIMAL_GB
PLANNING_PEAK_LIMIT_BYTES = 22 * DECIMAL_GB
SAMPLE_INTERVAL_SECONDS = 30
SUBBUDGETS = {
    "ephemeral_dataset": 16 * DECIMAL_GB,
    "durable_result_staging": 3 * DECIMAL_GB,
    "scratch_partial": 2 * DECIMAL_GB,
    "retry_quarantine_wal": 1 * DECIMAL_GB,
    "emergency_reserve": 3 * DECIMAL_GB,
}


class CapacityState(StrEnum):
    NORMAL = "NORMAL"
    DRAIN_AND_SEAL = "DRAIN_AND_SEAL"
    SAFE_HALT_CAP_BREACH = "SAFE_HALT_CAP_BREACH"


def _bytes(v: Any, n: str) -> int:
    if isinstance(v, bool) or not isinstance(v, Integral) or int(v) < 0:
        raise ValueError(f"{n} must be a non-negative integer")
    return int(v)


def observed_capacity_bytes(
    project_tree_allocated_bytes: int,
    filesystem_used_delta_bytes: int,
    owned_external_layers_bytes: int = 0,
) -> int:
    return max(
        _bytes(project_tree_allocated_bytes, "project_tree_allocated_bytes"),
        _bytes(filesystem_used_delta_bytes, "filesystem_used_delta_bytes")
        + _bytes(owned_external_layers_bytes, "owned_external_layers_bytes"),
    )


def capacity_state(capacity_bytes: int) -> CapacityState:
    v = _bytes(capacity_bytes, "capacity_bytes")
    if v > CAPACITY_HARD_LIMIT_BYTES:
        return CapacityState.SAFE_HALT_CAP_BREACH
    if v >= CAPACITY_DRAIN_BYTES:
        return CapacityState.DRAIN_AND_SEAL
    return CapacityState.NORMAL


def validate_planning_peak(planning_peak_bytes: int) -> int:
    value = _bytes(planning_peak_bytes, "planning_peak_bytes")
    if value > PLANNING_PEAK_LIMIT_BYTES:
        raise ValueError("planning peak exceeds fixed 22 GB limit")
    return value


def validate_subbudgets(usage: Mapping[str, int]) -> dict[str, int]:
    if not isinstance(usage, Mapping):
        raise ValueError("usage must be a mapping")
    if set(usage) - set(SUBBUDGETS):
        raise ValueError("unknown subbudget")
    out = {k: _bytes(usage.get(k, 0), k) for k in SUBBUDGETS}
    for k, v in out.items():
        if v > SUBBUDGETS[k]:
            raise ValueError(f"subbudget {k} exceeds fixed limit")
    if out["emergency_reserve"] != 0:
        raise ValueError("emergency_reserve is unallocatable and cannot be used")
    return out


@dataclass(frozen=True)
class CapacityTelemetry:
    project_tree_allocated_bytes: int
    filesystem_used_delta_bytes: int
    owned_external_layers_bytes: int = 0
    open_deleted_bytes: int = 0
    sampled_at: str | None = None
    segment_state: str | None = None
    sample_reason: str = "interval"
    segment_id: str | None = None
    subbudget_usage: Mapping[str, int] | None = None
    planning_peak_bytes: int | None = None

    def __post_init__(self) -> None:
        for n in (
            "project_tree_allocated_bytes",
            "filesystem_used_delta_bytes",
            "owned_external_layers_bytes",
            "open_deleted_bytes",
        ):
            _bytes(getattr(self, n), n)
        for n in ("sampled_at", "segment_state", "segment_id"):
            value = getattr(self, n)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{n} must be a string or null")
        if not isinstance(self.sample_reason, str):
            raise ValueError("sample_reason must be a string")
        if self.sample_reason not in {"interval", "transition", "manual"}:
            raise ValueError("unsupported sample_reason")
        validate_subbudgets(self.subbudget_usage or {})
        if self.planning_peak_bytes is not None:
            validate_planning_peak(self.planning_peak_bytes)

    @property
    def capacity_bytes(self) -> int:
        return observed_capacity_bytes(
            self.project_tree_allocated_bytes,
            self.filesystem_used_delta_bytes,
            self.owned_external_layers_bytes + self.open_deleted_bytes,
        )

    @property
    def state(self) -> CapacityState:
        return capacity_state(self.capacity_bytes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "capacity-telemetry.v6.13",
            "segment_id": self.segment_id,
            "project_tree_allocated_bytes": self.project_tree_allocated_bytes,
            "filesystem_used_delta_bytes": self.filesystem_used_delta_bytes,
            "owned_external_layers_bytes": self.owned_external_layers_bytes,
            "open_deleted_bytes": self.open_deleted_bytes,
            "capacity_bytes": self.capacity_bytes,
            "state": self.state.value,
            "sampled_at": self.sampled_at,
            "segment_state": self.segment_state,
            "sample_reason": self.sample_reason,
            "reason": self.sample_reason,
            "sampling_interval_seconds": SAMPLE_INTERVAL_SECONDS,
            "formula": "max(project_tree_allocated_bytes, filesystem_used_delta_bytes + owned_external_layers_bytes + open_deleted_bytes)",
            "subbudget_usage": validate_subbudgets(self.subbudget_usage or {}),
            "subbudget_limits": dict(SUBBUDGETS),
            "planning_peak_bytes": self.planning_peak_bytes,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self.as_dict())


def should_sample(
    last_sampled_at: datetime | None,
    now: datetime | None = None,
    *,
    transition: bool = False,
) -> bool:
    if transition or last_sampled_at is None:
        return True
    if last_sampled_at.tzinfo is None:
        raise ValueError("last_sampled_at must be timezone-aware")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return (now - last_sampled_at).total_seconds() >= SAMPLE_INTERVAL_SECONDS
