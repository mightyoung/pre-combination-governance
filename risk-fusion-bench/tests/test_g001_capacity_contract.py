from test_g001_c3_adversarial import valid_c2_report
from rfb.orchestration import plan_c3

OTHER = {
    "scratch_partial": 1_000_000_000,
    "retry_quarantine_wal": 500_000_000,
    "emergency_reserve": 3_000_000_000,
}


def test_c3_two_segments():
    r = plan_c3(
        c2_report=valid_c2_report(),
        frozen_planning_upper_bound_dataset_bytes=1_000_000_000,
        frozen_planning_upper_bound_result_bytes=1_000_000_000,
        frozen_planning_upper_bound_total_peak_bytes=1_000_000_000,
        other_subbudget_bounds=OTHER,
    )
    assert r.report["n_segment"] >= 2
    assert r.report["storage_disposition"] == "QUARANTINED_NO_DELETE"


def test_c3_omitted_other_is_blocked():
    r = plan_c3(
        c2_report=valid_c2_report(),
        frozen_planning_upper_bound_dataset_bytes=1,
        frozen_planning_upper_bound_result_bytes=1,
        frozen_planning_upper_bound_total_peak_bytes=1,
    ).report
    assert r["planning_decision"] == "BLOCKED_NO_CAPACITY"
    assert r["planning_input_valid"] is False
