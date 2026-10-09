from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Mapping

from jsonschema import Draft202012Validator

from ..contracts.canonical_json import canonical_bytes, sha256_hex

_BUDGETS = {
    "scratch_partial": 2_000_000_000,
    "retry_quarantine_wal": 1_000_000_000,
    "emergency_reserve": 3_000_000_000,
}
_REQUIRED_OTHER = frozenset(_BUDGETS)
_ALLOCATABLE_OTHER = ("scratch_partial", "retry_quarantine_wal")
_MAX_BOUND = 10**30
_FROZEN_EMERGENCY_RESERVE = 3_000_000_000
_SINGLE_BUNDLE_PEAK_LIMIT = 22_000_000_000


@dataclass(frozen=True)
class C3PlanningReport:
    report: dict

    @property
    def planning_decision(self):
        return self.report["planning_decision"]


def _check(value):
    if value is None:
        return "MISSING_BOUND"
    if isinstance(value, bool):
        return "NONINTEGER_BYTE_BOUND"
    if isinstance(value, float):
        return (
            "NONFINITE_BOUND" if not math.isfinite(value) else "NONINTEGER_BYTE_BOUND"
        )
    if not isinstance(value, int):
        return "NONINTEGER_BYTE_BOUND"
    if value <= 0:
        return "NONPOSITIVE_BOUND"
    if value > _MAX_BOUND:
        return "ARITHMETIC_OVERFLOW"
    return None


def _schema():
    return json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "contracts"
            / "c3_planning_report.schema.json"
        ).read_text(encoding="utf-8")
    )


def _validate_c2(c2_report):
    """Validate the sealed C2 sizing artifact before allowing C3 counts."""
    if not isinstance(c2_report, Mapping):
        return "MISSING_C2_REPORT"
    try:
        Draft202012Validator(_c2_schema()).validate(c2_report)
    except Exception:
        return "INVALID_C2_REPORT"
    peaks = [item.get("planning_peak_bytes") for item in c2_report.get("telemetry", [])]
    if not peaks or any(_check(value) for value in peaks):
        return "INVALID_C2_PEAK_TELEMETRY"
    supplied = c2_report.get("report_sha256")
    body = dict(c2_report)
    body.pop("report_sha256", None)
    if supplied != sha256_hex(canonical_bytes(body)):
        return "C2_REPORT_SELF_HASH_MISMATCH"
    return None


def _c2_schema():
    return json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "contracts"
            / "c2_sizing_report.schema.json"
        ).read_text(encoding="utf-8")
    )


def plan_c3(
    *,
    frozen_planning_upper_bound_dataset_bytes,
    frozen_planning_upper_bound_result_bytes,
    frozen_planning_upper_bound_total_peak_bytes,
    other_subbudget_bounds=None,
    c2_peak_bytes=None,
    c2_report=None,
):
    raw = {
        "dataset": frozen_planning_upper_bound_dataset_bytes,
        "result": frozen_planning_upper_bound_result_bytes,
        "peak": frozen_planning_upper_bound_total_peak_bytes,
    }
    invalid = []
    failures = []
    for name, value in raw.items():
        if failure := _check(value):
            invalid.append(f"frozen_planning_upper_bound_{name}_bytes")
            failures.append(failure)
    others = (
        other_subbudget_bounds if isinstance(other_subbudget_bounds, dict) else None
    )
    if others is None:
        invalid.append("other_subbudget_bounds")
        failures.append("MISSING_BOUND")
        others = {}
    else:
        for key in sorted(_REQUIRED_OTHER - set(others)):
            invalid.append(f"other_subbudget_bounds.{key}")
            failures.append("MISSING_BOUND")
        for key in sorted(set(others) - _REQUIRED_OTHER):
            invalid.append(f"other_subbudget_bounds.{key}")
            failures.append("UNKNOWN_BOUND")
        for key in sorted(_REQUIRED_OTHER & set(others)):
            if failure := _check(others[key]):
                invalid.append(f"other_subbudget_bounds.{key}")
                failures.append(failure)
        if (
            "emergency_reserve" in others
            and others["emergency_reserve"] != _FROZEN_EMERGENCY_RESERVE
        ):
            invalid.append("other_subbudget_bounds.emergency_reserve")
            failures.append("FROZEN_EMERGENCY_RESERVE_MISMATCH")
    c2_failure = _validate_c2(c2_report)
    c2_peak_from_report = None
    single_bundle_cap_breach = False
    if not c2_failure:
        # The sealed report is the sole authority for the observed C2 peak.
        # Keep the parameter only for API compatibility, and reject any
        # understated (or otherwise divergent) override.
        c2_peak_from_report = max(
            item["planning_peak_bytes"] for item in c2_report["telemetry"]
        )
        if c2_peak_bytes is None:
            c2_peak_bytes = c2_peak_from_report
        else:
            override_failure = _check(c2_peak_bytes)
            if override_failure:
                invalid.append("c2_peak_bytes")
                failures.append(override_failure)
                c2_failure = override_failure
            elif c2_peak_bytes != c2_peak_from_report:
                invalid.append("c2_peak_bytes")
                failures.append("C2_PEAK_OVERRIDE_MISMATCH")
                c2_failure = "C2_PEAK_OVERRIDE_MISMATCH"
        if c2_peak_from_report > _SINGLE_BUNDLE_PEAK_LIMIT:
            invalid.append("c2_report.telemetry.planning_peak_bytes")
            failures.append("C2_PEAK_EXCEEDS_SINGLE_BUNDLE_CAPACITY")
            c2_failure = "C2_PEAK_EXCEEDS_SINGLE_BUNDLE_CAPACITY"
            single_bundle_cap_breach = True
        elif c2_peak_from_report > raw["peak"] and c2_failure is None:
            # A frozen planning bound must dominate every observed C2 value;
            # otherwise the segment count would be based on an understated
            # safety bound.
            invalid.append("frozen_planning_upper_bound_peak_bytes")
            failures.append("FROZEN_PEAK_BOUND_BELOW_C2_PEAK")
            c2_failure = "FROZEN_PEAK_BOUND_BELOW_C2_PEAK"
    if c2_failure:
        invalid.append("c2_report")
        if c2_failure not in failures:
            failures.append(c2_failure)
    valid = not invalid
    counts = {
        "n_dataset": None,
        "n_result": None,
        "n_peak": None,
        "n_other": None,
        "n_segment": None,
    }
    failure_code = failures[0] if failures else None
    if valid:
        counts["n_dataset"] = 16_000_000_000 // raw["dataset"]
        counts["n_result"] = 3_000_000_000 // raw["result"]
        counts["n_peak"] = 22_000_000_000 // raw["peak"]
        # Emergency reserve is a protected, non-allocatable floor.
        counts["n_other"] = min(_BUDGETS[k] // others[k] for k in _ALLOCATABLE_OTHER)
        counts["n_segment"] = min(
            counts[k] for k in ("n_dataset", "n_result", "n_peak", "n_other")
        )
        for key, code in (
            ("n_dataset", "ZERO_CAPACITY_DATASET"),
            ("n_result", "ZERO_CAPACITY_RESULT"),
            ("n_peak", "ZERO_CAPACITY_PEAK"),
            ("n_other", "ZERO_CAPACITY_OTHER"),
        ):
            if counts[key] == 0:
                failure_code = code
                break
    decision = (
        "BLOCKED_NO_CAPACITY"
        if not valid or counts["n_segment"] == 0
        else (
            "BLOCKED_SEGMENT_TOO_SMALL_FOR_REGENERATION"
            if counts["n_segment"] == 1
            else "ELIGIBLE_FOR_SEPARATE_CLOSEOUT_REHEARSAL"
        )
    )
    if single_bundle_cap_breach:
        decision = "BLOCKED_SINGLE_BUNDLE_CAPACITY"
    elif c2_failure:
        decision = "BLOCKED_NO_CAPACITY"
    report = {
        "schema_version": "c3-planning-report.v1",
        "planning_input_valid": valid,
        "planning_failure_code": failure_code,
        "invalid_bound_fields": invalid,
        **{
            f"frozen_planning_upper_bound_{k}_bytes": (raw[k] if valid else None)
            for k in raw
        },
        "other_subbudget_bounds": {
            k: (others.get(k) if valid else None) for k in sorted(_REQUIRED_OTHER)
        },
        "emergency_reserve_per_bundle_bytes": 0,
        **counts,
        "planning_decision": decision,
        "c2_evidence_state": "SIZING_REPORTED",
        "storage_disposition": "QUARANTINED_NO_DELETE",
        "c2_report_sha256": c2_report.get("report_sha256")
        if isinstance(c2_report, Mapping)
        else None,
        "c2_manifest_sha256": c2_report.get("manifest_sha256")
        if isinstance(c2_report, Mapping)
        else None,
    }
    report["self_hash"] = sha256_hex(canonical_bytes(report))
    Draft202012Validator(_schema()).validate(report)
    return C3PlanningReport(report)
