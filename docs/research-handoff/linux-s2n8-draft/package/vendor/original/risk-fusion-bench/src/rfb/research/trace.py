"""Revision 6, hash-linked research lifecycle trace.

The trace is deliberately a small, dependency-free contract.  Its twenty
steps are fixed by the R005 addendum; callers may attach evidence hashes but
cannot add, reorder, or aggregate away lifecycle events.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

from jsonschema import ValidationError
from jsonschema import validate as schema_validate

from rfb.contracts.canonical_json import canonical_bytes, sha256_hex
from .models import CLASSIFICATION, validate_classification

ZERO_HASH = "0" * 64
SCHEMA_VERSION = "1.0.0"

# Approved R6 event/actor table.  Keep this ordered and immutable at the API
# boundary: the order is itself part of the evidence contract.
EVENT_ACTOR_TABLE: tuple[tuple[int, str, str], ...] = (
    (1, "LOCAL_MANIFEST_VALIDATED", "controller"),
    (2, "LOCAL_RUNTIME_BUILT", "controller"),
    (3, "HOST_KEY_VERIFIED", "controller"),
    (4, "BOOTSTRAP_PARENT_PREFLIGHT_OBSERVED", "bootstrap_transport"),
    (5, "RUN_ROOT_CREATED_DURABLE", "bootstrap_transport"),
    (6, "RUNTIME_PARTIALS_UPLOADED", "controller"),
    (7, "RUNTIME_SEALED_DURABLE", "bootstrap_transport"),
    (8, "RUNTIME_FULL_PREFLIGHT_OBSERVED", "sealed_runtime"),
    (9, "EXECUTION_MANIFEST_CONSTRUCTED", "controller"),
    (10, "EXECUTION_MANIFEST_SEALED_DURABLE", "sealed_runtime"),
    (11, "WORKER_FIXED_ARGV_LAUNCHED", "controller"),
    (12, "EXECUTION_MANIFEST_VERIFIED_BEFORE_PARSE", "sealed_runtime"),
    (13, "PARENT_WIDE_LOCK_ACQUIRED", "sealed_runtime"),
    (14, "LAUNCH_RECHECK_ACCEPTED", "sealed_runtime"),
    (15, "ADAPTER_EXIT_AND_POST_RECHECK_ACCEPTED", "sealed_runtime"),
    (16, "RESULT_TREE_SEALED_DURABLE", "sealed_runtime"),
    (17, "REMOTE_RECEIPT_SEALED_READBACK_VERIFIED", "sealed_runtime"),
    (18, "LOCK_RELEASED_AFTER_RECEIPT", "sealed_runtime"),
    (19, "REMOTE_EVIDENCE_REVERIFIED_AND_LOCAL_COPY_SEALED", "controller"),
    (20, "COPY_AND_FINAL_RECEIPTS_SEALED_VERIFIED", "controller"),
)
EVENTS = {step: (event, actor) for step, event, actor in EVENT_ACTOR_TABLE}
# Per-event proof cardinality is explicit so the contract can evolve without
# silently making evidence optional.  Every approved R6 event needs both sides.
STEP_MIN_PROOF_HASHES = {step: (1, 1) for step, _, _ in EVENT_ACTOR_TABLE}


class TraceValidationError(ValueError):
    """Raised when a lifecycle trace is not a closed R6 trace."""


def _schema() -> dict[str, Any]:
    path = (
        Path(__file__).parent.parent
        / "contracts"
        / "research_lifecycle_trace.schema.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash_body(record: Mapping[str, Any]) -> str:
    return sha256_hex(
        canonical_bytes({k: v for k, v in record.items() if k != "trace_hash"})
    )


def make_record(
    *,
    run_id: str,
    step_id: int,
    approved_remote_parent: str,
    remote_run_root: str | None = None,
    input_hashes: Mapping[str, str] | None = None,
    output_hashes: Mapping[str, str] | None = None,
    status: str = "SUCCEEDED",
    failure: Any = None,
    previous_trace_hash: str = ZERO_HASH,
    timestamp_utc: str | None = None,
    monotonic_ns: int = 0,
) -> dict[str, Any]:
    """Create one canonical record and calculate its hash-linked trace hash."""
    if step_id not in EVENTS:
        raise TraceValidationError(f"unknown step_id: {step_id}")
    min_inputs, min_outputs = STEP_MIN_PROOF_HASHES[step_id]
    if len(input_hashes or {}) < min_inputs or len(output_hashes or {}) < min_outputs:
        raise TraceValidationError(
            f"step {step_id} requires nonempty input and output proof hashes"
        )
    event, actor = EVENTS[step_id]
    body: dict[str, Any] = {
        "run_id": run_id,
        "step_id": step_id,
        "event": event,
        "actor": actor,
        "approved_remote_parent": approved_remote_parent,
        "remote_run_root": remote_run_root,
        "timestamp_utc": timestamp_utc or _utc_now(),
        "monotonic_ns": monotonic_ns,
        "input_hashes": dict(input_hashes or {}),
        "output_hashes": dict(output_hashes or {}),
        "status": status,
        "failure": dict(failure) if isinstance(failure, Mapping) else failure,
        "previous_trace_hash": previous_trace_hash,
    }
    body.update(CLASSIFICATION)
    body["trace_hash"] = _hash_body(body)
    return body


def build_trace(
    *,
    run_id: str,
    approved_remote_parent: str,
    remote_run_root: str | None = None,
    records: Sequence[Mapping[str, Any]] | None = None,
    terminal_status: str = "SUCCEEDED",
) -> dict[str, Any]:
    """Build a trace document from caller-supplied, evidence-bearing records."""
    if records is None:
        raise TraceValidationError("synthetic lifecycle traces are not permitted")
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "approved_remote_parent": approved_remote_parent,
        "remote_run_root": remote_run_root,
        "terminal_status": terminal_status,
        "records": [dict(record) for record in records],
    }


class LifecycleTraceRecorder:
    """Incrementally record the fixed R6 lifecycle, then seal it."""

    def __init__(
        self,
        *,
        run_id: str,
        approved_remote_parent: str,
        remote_run_root: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.approved_remote_parent = approved_remote_parent
        self.remote_run_root = remote_run_root
        self.records: list[dict[str, Any]] = []

    @property
    def next_step_id(self) -> int:
        return len(self.records) + 1

    @classmethod
    def from_records(
        cls,
        *,
        run_id: str,
        approved_remote_parent: str,
        records: Sequence[Mapping[str, Any]],
        remote_run_root: str | None = None,
    ) -> "LifecycleTraceRecorder":
        """Resume after validating a contiguous, evidence-bearing prefix."""
        validate_trace_prefix(
            records,
            run_id=run_id,
            approved_remote_parent=approved_remote_parent,
            remote_run_root=remote_run_root,
        )
        recorder = cls(
            run_id=run_id,
            approved_remote_parent=approved_remote_parent,
            remote_run_root=remote_run_root,
        )
        recorder.records = [dict(record) for record in records]
        return recorder

    def append(
        self,
        *,
        input_hashes: Mapping[str, str],
        output_hashes: Mapping[str, str],
        status: str = "SUCCEEDED",
        failure: Any = None,
        timestamp_utc: str | None = None,
        monotonic_ns: int | None = None,
    ) -> dict[str, Any]:
        step = self.next_step_id
        if step > len(EVENT_ACTOR_TABLE):
            raise TraceValidationError("all lifecycle steps have already been recorded")
        previous = self.records[-1]["trace_hash"] if self.records else ZERO_HASH
        record = make_record(
            run_id=self.run_id,
            step_id=step,
            approved_remote_parent=self.approved_remote_parent,
            remote_run_root=self.remote_run_root,
            input_hashes=input_hashes,
            output_hashes=output_hashes,
            status=status,
            failure=failure,
            previous_trace_hash=previous,
            timestamp_utc=timestamp_utc,
            monotonic_ns=time.monotonic_ns() if monotonic_ns is None else monotonic_ns,
        )
        self.records.append(record)
        return record

    record = append

    def seal(self, *, terminal_status: str = "SUCCEEDED") -> dict[str, Any]:
        if len(self.records) != len(EVENT_ACTOR_TABLE):
            raise TraceValidationError("cannot seal before all 20 lifecycle steps")
        trace = build_trace(
            run_id=self.run_id,
            approved_remote_parent=self.approved_remote_parent,
            remote_run_root=self.remote_run_root,
            records=self.records,
            terminal_status=terminal_status,
        )
        validate_trace(trace, require_success=terminal_status == "SUCCEEDED")
        return trace


def validate_trace(
    trace: Mapping[str, Any], *, require_success: bool = True
) -> Mapping[str, Any]:
    """Validate schema, exact event table, immutable classification and hash chain."""
    try:
        schema_validate(dict(trace), _schema())
    except ValidationError as exc:
        raise TraceValidationError(str(exc)) from exc
    records = trace["records"]
    if len(records) != 20:
        raise TraceValidationError("trace must contain exactly 20 lifecycle records")
    _validate_records(
        records,
        run_id=trace["run_id"],
        approved_remote_parent=trace["approved_remote_parent"],
        remote_run_root=trace["remote_run_root"],
        require_success=require_success,
    )
    if require_success and trace["terminal_status"] != "SUCCEEDED":
        raise TraceValidationError("trace terminal status is not SUCCEEDED")
    return trace


def _validate_records(
    records: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    approved_remote_parent: str,
    remote_run_root: str | None,
    require_success: bool = True,
) -> None:
    if not 1 <= len(records) <= 20:
        raise TraceValidationError("trace prefix must contain between 1 and 20 records")
    previous = ZERO_HASH
    # monotonic_ns is comparable only within one host/clock domain.  The
    # lifecycle intentionally crosses Windows controller and Linux remote
    # actors, so global numeric ordering would reject every genuine trace.
    last_mono_by_actor: dict[str, int] = {}
    for expected_step, record in enumerate(records, 1):
        if record["step_id"] != expected_step:
            raise TraceValidationError("missing, duplicate, or reordered step_id")
        event, actor = EVENTS[expected_step]
        if record["event"] != event or record["actor"] != actor:
            raise TraceValidationError("event/actor table mismatch")
        if record["run_id"] != run_id:
            raise TraceValidationError("run_id mismatch")
        if record["approved_remote_parent"] != approved_remote_parent:
            raise TraceValidationError("approved_remote_parent mismatch")
        if record["remote_run_root"] != remote_run_root:
            raise TraceValidationError("remote_run_root mismatch")
        validate_classification(
            {key: record.get(key) for key in CLASSIFICATION}, exact=True
        )
        if record["previous_trace_hash"] != previous:
            raise TraceValidationError("trace hash chain predecessor mismatch")
        if record["trace_hash"] != _hash_body(record):
            raise TraceValidationError("trace hash mismatch")
        min_inputs, min_outputs = STEP_MIN_PROOF_HASHES[expected_step]
        if (
            len(record["input_hashes"]) < min_inputs
            or len(record["output_hashes"]) < min_outputs
        ):
            raise TraceValidationError("event proof hashes are incomplete")
        actor_mono = int(record["monotonic_ns"])
        if actor_mono < last_mono_by_actor.get(record["actor"], -1):
            raise TraceValidationError("actor monotonic timestamps reordered")
        last_mono_by_actor[record["actor"]] = actor_mono
        if record["status"] != "SUCCEEDED" and require_success:
            raise TraceValidationError(
                "successful trace contains failed lifecycle step"
            )
        previous = record["trace_hash"]


def validate_trace_prefix(
    records: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    approved_remote_parent: str,
    remote_run_root: str | None = None,
) -> Sequence[Mapping[str, Any]]:
    """Validate a contiguous prefix (steps 1..N) without requiring closure."""
    if not 1 <= len(records) < 20:
        raise TraceValidationError("trace prefix must contain steps 1..N with N < 20")
    _validate_records(
        records,
        run_id=run_id,
        approved_remote_parent=approved_remote_parent,
        remote_run_root=remote_run_root,
    )
    return records


def validate_lifecycle_trace(
    trace: Mapping[str, Any], *, require_success: bool = True
) -> Mapping[str, Any]:
    """Compatibility spelling for integration callers."""
    return validate_trace(trace, require_success=require_success)


__all__ = [
    "EVENT_ACTOR_TABLE",
    "EVENTS",
    "STEP_MIN_PROOF_HASHES",
    "ZERO_HASH",
    "TraceValidationError",
    "make_record",
    "build_trace",
    "validate_trace",
    "validate_lifecycle_trace",
    "validate_trace_prefix",
    "LifecycleTraceRecorder",
]
