from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from rfb.capacity import (
    CAPACITY_DRAIN_BYTES,
    CAPACITY_HARD_LIMIT_BYTES,
    CapacityState,
    CapacityTelemetry,
    capacity_state,
    observed_capacity_bytes,
    should_sample,
    validate_subbudgets,
)
from rfb.formal.lifecycle import FormalLifecycle, LifecycleError, LifecycleState
from rfb.formal.truth import TruthIsolationError, sanitize_observations


def test_capacity_thresholds_are_decimal_and_fail_closed():
    assert capacity_state(CAPACITY_DRAIN_BYTES - 1) is CapacityState.NORMAL
    assert capacity_state(CAPACITY_DRAIN_BYTES) is CapacityState.DRAIN_AND_SEAL
    assert (
        capacity_state(CAPACITY_HARD_LIMIT_BYTES + 1)
        is CapacityState.SAFE_HALT_CAP_BREACH
    )
    assert observed_capacity_bytes(3, 4, 5) == 9
    assert CapacityTelemetry(1, 2, open_deleted_bytes=10).capacity_bytes == 12


@pytest.mark.parametrize("bad", [-1, 1.5, True, "1", None])
def test_capacity_rejects_bad_types_and_negative_values(bad):
    with pytest.raises(ValueError):
        observed_capacity_bytes(bad, 0)


def test_capacity_subbudgets_do_not_allow_borrowing():
    with pytest.raises(ValueError):
        validate_subbudgets({"ephemeral_dataset": 16_000_000_001})
    with pytest.raises(ValueError):
        validate_subbudgets({"ephemeral_dataset": 1, "unknown": 1})
    assert validate_subbudgets({}) == {
        k: 0
        for k in (
            "ephemeral_dataset",
            "durable_result_staging",
            "scratch_partial",
            "retry_quarantine_wal",
            "emergency_reserve",
        )
    }


def test_capacity_sampling_uses_30_second_interval_and_transition_override():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert should_sample(t0, t0 + timedelta(seconds=29)) is False
    assert should_sample(t0, t0 + timedelta(seconds=30)) is True
    assert should_sample(t0, t0 + timedelta(seconds=1), transition=True) is True
    with pytest.raises(ValueError):
        should_sample(datetime(2026, 1, 1), t0)


def test_capacity_canonical_bytes_are_stable():
    a = CapacityTelemetry(1, 2).canonical_bytes()
    b = CapacityTelemetry(1, 2).canonical_bytes()
    assert a == b


def test_lifecycle_rejects_illegal_transition_and_seal_with_missing_success_rows():
    life = FormalLifecycle("tx", expected_rows=["r1"])
    with pytest.raises(LifecycleError):
        life.seal()
    life.start().finish(LifecycleState.SUCCEEDED)
    with pytest.raises(LifecycleError, match="missing expected"):
        life.seal()


def test_lifecycle_has_exactly_one_terminal_and_idempotent_row_recording():
    life = FormalLifecycle("tx", expected_rows=["r1"])
    life.start()
    assert life.record_row("r1", {"x": 1}) is True
    assert life.record_row("r1", {"x": 1}) is False
    with pytest.raises(LifecycleError):
        life.record_row("r1", {"x": 2})
    life.finish(LifecycleState.SUCCEEDED).seal()
    assert [e.state for e in life.events].count(LifecycleState.SUCCEEDED) == 1
    with pytest.raises(LifecycleError):
        life.finish(LifecycleState.FAILED)


def test_lifecycle_replay_and_hash_tamper_are_detected():
    life = FormalLifecycle("tx", expected_rows=["r1"])
    life.start().record_row("r1", {"x": 1})
    life.finish(LifecycleState.SUCCEEDED).seal()
    assert FormalLifecycle.replay("tx", life.events, ["r1"]).validate()
    tampered = list(life.events)
    tampered[1] = type(tampered[1])(
        tampered[1].sequence,
        tampered[1].state,
        "other",
        tampered[1].payload,
        tampered[1].previous_hash,
        tampered[1].event_hash,
    )
    with pytest.raises(LifecycleError):
        FormalLifecycle.replay("tx", tampered, ["r1"])


@pytest.mark.parametrize(
    "bad",
    [{"truth": 1}, {"nested": {"raw_payload": 1}}, {"x": b"bytes"}, {1: "non-string"}],
)
def test_truth_isolation_rejects_direct_nested_serialized_and_bytes_leakage(bad):
    with pytest.raises(TruthIsolationError):
        sanitize_observations(bad)


def test_lifecycle_seal_rejects_unexpected_row_set():
    life = FormalLifecycle("tx", expected_rows=["r1"])
    life.start()
    assert life.record_row("other", {"x": 1}) is True
    life.finish(LifecycleState.SUCCEEDED)
    with pytest.raises(LifecycleError, match="missing expected"):
        life.seal()


def test_lifecycle_sealed_events_are_immutable_snapshot():
    life = FormalLifecycle("tx", expected_rows=["r1"])
    life.start()
    assert life.record_row("r1", {"x": 1}) is True
    life.finish(LifecycleState.SUCCEEDED).seal()
    events = life.events
    with pytest.raises(AttributeError):
        events.append(None)
    assert life.validate()


def test_capacity_emergency_reserve_is_unallocatable():
    with pytest.raises(ValueError, match="emergency_reserve"):
        validate_subbudgets({"emergency_reserve": 1})
