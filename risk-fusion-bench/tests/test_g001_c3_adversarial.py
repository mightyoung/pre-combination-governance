import math

from rfb.orchestration.c3 import plan_c3
from rfb.contracts.canonical_json import canonical_bytes, sha256_hex


def valid_c2_report():
    rows = [
        {
            "method_id": m,
            "terminal_state": "SEALED",
            "panel_closed": True,
            "result_sha256": "a" * 64,
            "durable_manifest_sha256": "b" * 64,
        }
        for m in ("B0", "B1", "B2", "B3", "B4", "B5", "Proposed")
    ]
    telemetry = [
        {"state": state, "sampled_at": i, "planning_peak_bytes": 1_000_000_000}
        for i, state in enumerate(
            ("PLANNED", "ADMITTED", "MATERIALIZING", "EXECUTING", "RESULT_SEALED_LOCAL")
        )
    ]
    body = {
        "schema_version": "c2-sizing-report.v1",
        "classification": "NONCONFIRMATORY_SIZING_ONLY",
        "terminal_state": "SIZING_REPORTED",
        "live_gate_effect": "NONE",
        "regeneration_eligible": False,
        "purge_eligible": False,
        "method_ranking_emitted": False,
        "panel_closed": True,
        "contains_raw_dataset": False,
        "gpu_not_used": True,
        "c2_evidence_state": "SIZING_REPORTED",
        "storage_disposition": "QUARANTINED_NO_DELETE",
        "planning_decision": "PENDING_C3_CALCULATION",
        "manifest_sha256": "c" * 64,
        "telemetry": telemetry,
        "terminal_rows": rows,
        "capacity_transitions": telemetry[-2:],
    }
    body["report_sha256"] = sha256_hex(canonical_bytes(body))
    return body


OTHER = {
    "scratch_partial": 1_000_000_000,
    "retry_quarantine_wal": 500_000_000,
    "emergency_reserve": 3_000_000_000,
}
BASE = {
    "frozen_planning_upper_bound_dataset_bytes": 8_000_000_000,
    "frozen_planning_upper_bound_result_bytes": 1_500_000_000,
    "frozen_planning_upper_bound_total_peak_bytes": 11_000_000_000,
    "other_subbudget_bounds": OTHER,
    "c2_report": valid_c2_report(),
}


def test_zero_capacity_is_invalid_and_blocked():
    r = plan_c3(
        **{**BASE, "frozen_planning_upper_bound_dataset_bytes": 20_000_000_000}
    ).report
    assert r["planning_input_valid"] is True and r["n_dataset"] == 0
    assert (
        r["planning_failure_code"] == "ZERO_CAPACITY_DATASET"
        and r["planning_decision"] == "BLOCKED_NO_CAPACITY"
    )


def test_invalid_bounds_have_null_counts():
    r = plan_c3(**{**BASE, "frozen_planning_upper_bound_result_bytes": True}).report
    assert r["planning_input_valid"] is False
    assert all(
        r[k] is None
        for k in ("n_dataset", "n_result", "n_peak", "n_other", "n_segment")
    )


def test_c2_invalid_is_structured_and_single_bundle_precedes():
    bad = plan_c3(**{**BASE, "c2_peak_bytes": math.nan}).report
    assert (
        bad["planning_decision"] == "BLOCKED_NO_CAPACITY"
        and "c2_peak_bytes" in bad["invalid_bound_fields"]
    )
    over_c2 = valid_c2_report()
    for item in over_c2["telemetry"]:
        item["planning_peak_bytes"] = 22_000_000_001
    over_c2.pop("report_sha256")
    over_c2["report_sha256"] = sha256_hex(canonical_bytes(over_c2))
    over = plan_c3(**{**BASE, "c2_report": over_c2}).report
    assert (
        over["planning_decision"] == "BLOCKED_SINGLE_BUNDLE_CAPACITY"
        and over["planning_input_valid"] is False
    )


def test_n_one_requires_regeneration_and_n_two_is_eligible():
    one = plan_c3(
        frozen_planning_upper_bound_dataset_bytes=16_000_000_000,
        frozen_planning_upper_bound_result_bytes=3_000_000_000,
        frozen_planning_upper_bound_total_peak_bytes=22_000_000_000,
        other_subbudget_bounds=OTHER,
        c2_report=valid_c2_report(),
    ).report
    assert (
        one["n_segment"] == 1
        and one["planning_decision"] == "BLOCKED_SEGMENT_TOO_SMALL_FOR_REGENERATION"
    )
    two = plan_c3(**BASE).report
    assert (
        two["n_segment"] == 2
        and two["planning_decision"] == "ELIGIBLE_FOR_SEPARATE_CLOSEOUT_REHEARSAL"
    )


def test_emergency_reserve_is_not_allocated_per_bundle_or_segment_count():
    report = plan_c3(**BASE).report
    assert report["emergency_reserve_per_bundle_bytes"] == 0
    assert report["n_other"] == 2
    reserve_only = plan_c3(
        **{**BASE, "other_subbudget_bounds": {**OTHER, "scratch_partial": 0}}
    ).report
    assert reserve_only["planning_input_valid"] is False
    assert reserve_only["planning_failure_code"] == "NONPOSITIVE_BOUND"
    assert reserve_only["n_other"] is None and reserve_only["n_segment"] is None


def test_wrong_emergency_reserve_is_invalid():
    report = plan_c3(
        **{
            **BASE,
            "other_subbudget_bounds": {**OTHER, "emergency_reserve": 1_500_000_000},
        }
    ).report
    assert report["planning_input_valid"] is False
    assert report["planning_failure_code"] == "FROZEN_EMERGENCY_RESERVE_MISMATCH"
    assert report["planning_decision"] == "BLOCKED_NO_CAPACITY"
    assert all(
        report[k] is None
        for k in ("n_dataset", "n_result", "n_peak", "n_other", "n_segment")
    )


def test_zero_bounds_are_structured_and_negative_bounds_remain_invalid():
    zero = plan_c3(**{**BASE, "frozen_planning_upper_bound_result_bytes": 0}).report
    assert zero["planning_input_valid"] is False
    assert zero["planning_failure_code"] == "NONPOSITIVE_BOUND"
    assert zero["n_result"] is None and zero["n_segment"] is None
    negative = plan_c3(
        **{**BASE, "frozen_planning_upper_bound_result_bytes": -1}
    ).report
    assert negative["planning_input_valid"] is False
    assert negative["planning_failure_code"] == "NONPOSITIVE_BOUND"
    assert negative["n_result"] is None and negative["n_segment"] is None


def test_missing_c2_artifact_blocks_with_null_counts():
    report = plan_c3(**{k: v for k, v in BASE.items() if k != "c2_report"}).report
    assert report["planning_decision"] == "BLOCKED_NO_CAPACITY"
    assert report["planning_failure_code"] == "MISSING_C2_REPORT"
    assert report["n_segment"] is None


def test_tampered_c2_self_hash_and_peak_block():
    tampered = valid_c2_report()
    tampered["planning_decision"] = "BLOCKED_NO_CAPACITY"
    report = plan_c3(**{**BASE, "c2_report": tampered}).report
    assert report["planning_decision"] == "BLOCKED_NO_CAPACITY"
    assert report["planning_failure_code"] == "C2_REPORT_SELF_HASH_MISMATCH"
    bad_peak = valid_c2_report()
    bad_peak["telemetry"][0]["planning_peak_bytes"] = 0
    report = plan_c3(**{**BASE, "c2_report": bad_peak}).report
    assert report["planning_decision"] == "BLOCKED_NO_CAPACITY"
    assert report["planning_failure_code"] == "INVALID_C2_PEAK_TELEMETRY"


def test_c2_peak_override_must_match_sealed_report():
    report = plan_c3(**{**BASE, "c2_peak_bytes": 999_999_999}).report
    assert report["planning_input_valid"] is False
    assert report["planning_failure_code"] == "C2_PEAK_OVERRIDE_MISMATCH"
    assert report["planning_decision"] == "BLOCKED_NO_CAPACITY"


def test_c2_malformed_peak_report_fails_closed_even_with_valid_hash():
    malformed = valid_c2_report()
    malformed["telemetry"][0].pop("planning_peak_bytes")
    malformed.pop("report_sha256")
    malformed["report_sha256"] = sha256_hex(canonical_bytes(malformed))
    result = plan_c3(**{**BASE, "c2_report": malformed}).report
    assert result["planning_input_valid"] is False
    assert result["planning_failure_code"] == "INVALID_C2_PEAK_TELEMETRY"
    assert result["planning_decision"] == "BLOCKED_NO_CAPACITY"


def test_frozen_peak_bound_cannot_understate_sealed_c2_peak():
    report = plan_c3(
        **{**BASE, "frozen_planning_upper_bound_total_peak_bytes": 999_999_999}
    ).report
    assert report["planning_input_valid"] is False
    assert report["planning_failure_code"] == "FROZEN_PEAK_BOUND_BELOW_C2_PEAK"
    assert report["planning_decision"] == "BLOCKED_NO_CAPACITY"
