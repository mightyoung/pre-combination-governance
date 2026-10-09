from test_g001_c3_adversarial import valid_c2_report
from pathlib import Path

import pytest
from rfb.contracts.canonical_json import canonical_bytes, sha256_hex
from rfb.orchestration import plan_c3, validate_manifest, validate_trusted_probe


def manifest():
    m = {
        "dataset_domain": "TEP",
        "bundle_count": 1,
        "panel": ["B0", "B1", "B2", "B3", "B4", "B5", "Proposed"],
        "D_test": False,
        "input_sha256": "a" * 64,
        "allocation_commitment": "b" * 64,
        "segment_id": "manifest-only",
        "segment_root_base": str(Path.cwd()),
        "run_id": "manifest-run",
        "probe_mount": "test-mount",
        "probe_owner": "test-owner",
        "probe_mode": "0700",
        "execution_mode": "LOCAL_FIXTURE_NONCONFIRMATORY",
    }
    m["manifest_sha256"] = sha256_hex(canonical_bytes(m))
    return m


def test_manifest_and_probe():
    assert validate_manifest(manifest())["dataset_domain"] == "TEP"
    with pytest.raises(ValueError):
        validate_trusted_probe(3)
    with pytest.raises(ValueError):
        validate_manifest({**manifest(), "dataset_domain": "MIMII"})


def test_c3_decisions():
    r = plan_c3(
        c2_report=valid_c2_report(),
        frozen_planning_upper_bound_dataset_bytes=16_000_000_000,
        frozen_planning_upper_bound_result_bytes=1,
        frozen_planning_upper_bound_total_peak_bytes=1_000_000_000,
        other_subbudget_bounds={
            "scratch_partial": 2_000_000_000,
            "retry_quarantine_wal": 1_000_000_000,
            "emergency_reserve": 3_000_000_000,
        },
    )
    assert r.planning_decision == "BLOCKED_SEGMENT_TOO_SMALL_FOR_REGENERATION"
    r = plan_c3(
        c2_report=valid_c2_report(),
        frozen_planning_upper_bound_dataset_bytes=0,
        frozen_planning_upper_bound_result_bytes=1,
        frozen_planning_upper_bound_total_peak_bytes=1,
        other_subbudget_bounds={
            "scratch_partial": 2_000_000_000,
            "retry_quarantine_wal": 1_000_000_000,
            "emergency_reserve": 3_000_000_000,
        },
    )
    assert (
        r.planning_decision == "BLOCKED_NO_CAPACITY"
        and r.report["c2_evidence_state"] == "SIZING_REPORTED"
    )
