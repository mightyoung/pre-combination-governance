"""Regression coverage for the non-fixture worker capacity sampler."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from rfb.research import worker


def _preflight(root: Path, *, peak: int = 100) -> dict:
    return {
        "root": str(root.resolve()),
        "hostname": "host",
        "mount_identity": "mount",
        "source_tree_sha256": "a" * 64,
        "package_inventory_sha256": "b" * 64,
        "config_sha256": "c" * 64,
        "input_manifest_sha256": "d" * 64,
        "dataset_manifest_sha256": "e" * 64,
        "dataset_manifest_verified": True,
        "gpu_policy": "cpu_only",
        "gpu_identity": "CPU_ONLY",
        "capacity_available": True,
        "capacity_measurement_status": "MEASURED",
        "capacity_unavailable_fields": [],
        "capacity_peak_bytes": peak,
        "capacity_state": "PLANNED",
        "project_tree_allocated_bytes": peak,
        "filesystem_used_delta_bytes": 0,
        "owned_external_layers_bytes": 0,
        "open_deleted_bytes": 0,
        "filesystem_used_bytes": 1,
        "filesystem_baseline_bytes": 1,
        "filesystem_free_bytes": 300_000_000_000,
        "owned_process_snapshot_sha256": "4" * 64,
        "foreign_process_snapshot_sha256": "5" * 64,
        "gpu_inventory_sha256": "f" * 64,
        "gpu_process_snapshot_sha256": "1" * 64,
    }


class _Spec:
    adapter_id = "tep_nonconfirmatory_v1"
    fixture_only = False
    implementation_sha256 = "3" * 64

    def __init__(self, started: threading.Event, release: threading.Event):
        self.started = started
        self.release = release

    def execute(self, _manifest, output):
        self.started.set()
        assert self.release.wait(1), "test adapter was not released"
        output.mkdir()
        (output / "tep_result.json").write_text(
            json.dumps({"method_event_count": 1}), encoding="utf-8"
        )

    @staticmethod
    def fixed_argv(_path):
        return ["worker"]

    @staticmethod
    def minimal_environment(*, root):
        return {"RFB_RESEARCH_ROOT": str(root)}


def _run_case(tmp_path: Path, monkeypatch, values):
    root = tmp_path / "remote"
    root.mkdir()
    preflight = _preflight(root)
    manifest = {
        "run_id": "sampler",
        "approved_remote_parent": str(tmp_path.resolve()),
        "remote_run_root": str(root.resolve()),
        "dataset_root": str(tmp_path / "dataset"),
        "adapter_id": "tep_nonconfirmatory_v1",
        "controller_nonce": "2" * 32,
        "preflight_evidence": preflight,
        "preflight_evidence_sha256": "ignored",
    }
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")
    started, release = threading.Event(), threading.Event()
    calls = []

    def collect(*_args, **_kwargs):
        calls.append(len(calls))
        if values:
            value = values.pop(0)
        else:
            value = preflight
        return dict(value)

    spec = _Spec(started, release)
    monkeypatch.setattr(worker, "CAPACITY_SAMPLE_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(worker, "validate_manifest", lambda value: value)
    monkeypatch.setattr(worker, "validate_adapter_contract", lambda _value: None)
    monkeypatch.setattr(worker, "_validate_preflight_binding", lambda _value: None)
    monkeypatch.setattr(worker, "resolve_adapter", lambda _value: spec)
    monkeypatch.setattr(worker, "collect_preflight", collect)
    monkeypatch.setattr(worker, "verify_after_run", lambda *_args: None)
    return source, release, calls


def test_sampler_peak_at_exact_hard_limit_is_allowed(tmp_path, monkeypatch):
    source, release, calls = _run_case(
        tmp_path,
        monkeypatch,
        [
            _preflight(tmp_path / "remote"),
            _preflight(tmp_path / "remote", peak=worker.HARD_PEAK_BYTES),
        ],
    )
    timer = threading.Timer(0.05, release.set)
    timer.start()
    worker.run_worker(source)
    timer.join()
    assert len(calls) >= 2
    assert not [t for t in threading.enumerate() if t.name.startswith("rfb-")]


def test_sampler_peak_over_hard_limit_fails_closed_and_joins_threads(
    tmp_path, monkeypatch
):
    source, release, calls = _run_case(
        tmp_path,
        monkeypatch,
        [
            _preflight(tmp_path / "remote"),
            _preflight(tmp_path / "remote", peak=worker.HARD_PEAK_BYTES + 1),
        ],
    )
    timer = threading.Timer(0.05, release.set)
    timer.start()
    with pytest.raises(ValueError, match="SAFE_HALT_CAP_BREACH"):
        worker.run_worker(source)
    timer.join()
    assert len(calls) >= 2
    assert not [t for t in threading.enumerate() if t.name.startswith("rfb-")]


def test_sampler_unavailable_measurement_fails_closed_and_joins_threads(
    tmp_path, monkeypatch
):
    unavailable = _preflight(tmp_path / "remote")
    unavailable["capacity_measurement_status"] = "UNAVAILABLE"
    unavailable["capacity_unavailable_fields"] = ["filesystem_used_bytes"]
    source, release, calls = _run_case(
        tmp_path, monkeypatch, [_preflight(tmp_path / "remote"), unavailable]
    )
    timer = threading.Timer(0.05, release.set)
    timer.start()
    with pytest.raises(ValueError, match="PREFLIGHT_CAPACITY_UNAVAILABLE"):
        worker.run_worker(source)
    timer.join()
    assert len(calls) >= 2
    assert not [t for t in threading.enumerate() if t.name.startswith("rfb-")]


def test_sampler_records_samples_and_peak_in_remote_receipt(tmp_path, monkeypatch):
    source, release, calls = _run_case(
        tmp_path,
        monkeypatch,
        [_preflight(tmp_path / "remote"), _preflight(tmp_path / "remote", peak=200)],
    )
    # Keep the adapter alive long enough to guarantee at least one interval.
    timer = threading.Timer(0.05, release.set)
    timer.start()
    receipt = worker.run_worker(source)
    timer.join()
    peaks = receipt["resource_peaks"]
    assert peaks["sample_count"] >= 3
    assert peaks["sample_peak_bytes"] == 200
    assert peaks["observed_peak_bytes"] == 200
    assert peaks["project_tree_allocated_bytes"] == 200
    assert len(calls) >= 3
    assert not [t for t in threading.enumerate() if t.name.startswith("rfb-")]
