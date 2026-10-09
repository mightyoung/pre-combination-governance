import pytest

from rfb.research.worker import _gpu_allocation_verdict


def _evidence(rows):
    return {"gpu_process_snapshot": rows}


def test_gpu_allocation_allows_existing_processes():
    rows = [{"pid": 101, "used_memory_mib": 128}]
    verdict = _gpu_allocation_verdict(_evidence(rows), _evidence(rows), fixture_only=False)
    assert verdict["status"] == "PASS"
    assert verdict["new_pids"] == []


def test_gpu_allocation_rejects_new_process():
    before = _evidence([{"pid": 101, "used_memory_mib": 128}])
    after = _evidence(
        [
            {"pid": 101, "used_memory_mib": 128},
            {"pid": 202, "used_memory_mib": 256},
        ]
    )
    with pytest.raises(ValueError, match="SAFE_HALT_GPU_ALLOCATION"):
        _gpu_allocation_verdict(before, after, fixture_only=False)


def test_gpu_allocation_rejects_transient_sample_process():
    before = _evidence([{"pid": 101, "used_memory_mib": 128}])
    post = _evidence([{"pid": 101, "used_memory_mib": 128}])
    transient = _evidence(
        [
            {"pid": 101, "used_memory_mib": 128},
            {"pid": 303, "used_memory_mib": 64},
        ]
    )
    with pytest.raises(ValueError, match="SAFE_HALT_GPU_ALLOCATION"):
        _gpu_allocation_verdict(before, post, fixture_only=False, samples=[transient])


def test_gpu_allocation_fails_closed_without_snapshot():
    evidence = {"gpu_probe_status": "OBSERVED_NOT_USED"}
    with pytest.raises(ValueError, match="PREFLIGHT_GPU_PROCESS_SNAPSHOT_UNAVAILABLE"):
        _gpu_allocation_verdict(evidence, evidence, fixture_only=False)
