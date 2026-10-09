from __future__ import annotations
import json
import pytest
from rfb.capacity import (
    CAPACITY_DRAIN_BYTES,
    CAPACITY_HARD_LIMIT_BYTES,
    PLANNING_PEAK_LIMIT_BYTES,
    CapacityState,
    capacity_state,
    validate_planning_peak,
)
from rfb.capacity_probe import (
    ProbeUnavailable,
    append_telemetry_jsonl,
    open_deleted_bytes,
    probe_capacity,
)


def test_capacity_exact_boundaries_and_planning_peak():
    assert (
        validate_planning_peak(PLANNING_PEAK_LIMIT_BYTES) == PLANNING_PEAK_LIMIT_BYTES
    )
    with pytest.raises(ValueError):
        validate_planning_peak(PLANNING_PEAK_LIMIT_BYTES + 1)
    assert capacity_state(CAPACITY_DRAIN_BYTES) is CapacityState.DRAIN_AND_SEAL
    assert capacity_state(CAPACITY_HARD_LIMIT_BYTES) is CapacityState.DRAIN_AND_SEAL
    assert (
        capacity_state(CAPACITY_HARD_LIMIT_BYTES + 1)
        is CapacityState.SAFE_HALT_CAP_BREACH
    )


def test_probe_requires_external_and_non_posix_open_deleted_value(
    tmp_path, monkeypatch
):
    with pytest.raises(ProbeUnavailable):
        probe_capacity(tmp_path, trusted_open_deleted_bytes=0)
    monkeypatch.setattr("rfb.capacity_probe.os.name", "nt")
    with pytest.raises(ProbeUnavailable):
        open_deleted_bytes()
    assert open_deleted_bytes(trusted_open_deleted_bytes=7) == 7


def test_probe_and_canonical_writer_roundtrip(tmp_path):
    (tmp_path / "x.partial").write_bytes(b"abc")
    telemetry = probe_capacity(
        tmp_path,
        filesystem_baseline_bytes=0,
        owned_external_layers_bytes=0,
        trusted_open_deleted_bytes=3,
    )
    record = telemetry.as_dict()
    assert record["schema_version"] == "capacity-telemetry.v6.13"
    assert record["sampling_interval_seconds"] == 30
    assert record["open_deleted_bytes"] == 3
    out = tmp_path / "telemetry.jsonl"
    append_telemetry_jsonl(out, telemetry)
    raw = out.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw) == record


def test_posix_proc_fixture_reads_deleted_file_size(tmp_path, monkeypatch):
    deleted = tmp_path / "deleted.bin"
    deleted.write_bytes(b"12345")
    fd = tmp_path / "123" / "fd"
    fd.mkdir(parents=True)
    fd_file = fd / "4"
    fd_file.write_bytes(b"12345")
    monkeypatch.setattr("rfb.capacity_probe.os.name", "posix")
    monkeypatch.setattr("rfb.capacity_probe.Path", type(tmp_path))
    monkeypatch.setattr(
        "rfb.capacity_probe.os.readlink", lambda _: f"{deleted} (deleted)"
    )
    assert open_deleted_bytes(proc_root=tmp_path) == 5


def test_capacity_probe_rejects_non_integral_byte_inputs(tmp_path):
    for value in (True, 1.5, "7"):
        with pytest.raises(ValueError):
            open_deleted_bytes(trusted_open_deleted_bytes=value)
    with pytest.raises(ValueError):
        probe_capacity(
            tmp_path,
            filesystem_baseline_bytes=1.5,
            owned_external_layers_bytes=0,
            trusted_open_deleted_bytes=0,
        )


def test_posix_open_deleted_fails_closed_on_proc_error(tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace

    original_scandir = os.scandir

    def failing_scandir(path):
        if str(path) == str(tmp_path):
            raise PermissionError("denied")
        return original_scandir(path)

    fake_os = SimpleNamespace(
        name="posix", scandir=failing_scandir, readlink=os.readlink, stat=os.stat
    )
    monkeypatch.setattr("rfb.capacity_probe.os", fake_os)
    with pytest.raises(ProbeUnavailable):
        open_deleted_bytes(proc_root=tmp_path)


def test_project_allocation_rejects_symlink(tmp_path):
    target = tmp_path / "outside.txt"
    target.write_text("x")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    from rfb.capacity_probe import project_allocated_bytes

    with pytest.raises(RuntimeError):
        project_allocated_bytes(tmp_path)


def test_telemetry_mapping_must_match_derived_fields(tmp_path):
    telemetry = probe_capacity(
        tmp_path, owned_external_layers_bytes=0, trusted_open_deleted_bytes=0
    )
    record = telemetry.as_dict()
    record["capacity_bytes"] += 1
    with pytest.raises(ValueError):
        append_telemetry_jsonl(tmp_path / "bad.jsonl", record)
