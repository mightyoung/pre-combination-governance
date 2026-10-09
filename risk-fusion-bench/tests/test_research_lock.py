from __future__ import annotations
import json
import time
import pytest
from rfb.research.lock import (
    ResearchLock,
    LockBusy,
    LockTombstoneError,
    _rename_noreplace,
)


def test_collision_identity_heartbeat_and_no_auto_unlock(tmp_path):
    lock = ResearchLock(tmp_path, "a" * 64).acquire()
    rec = json.loads(lock.path.read_text(encoding="utf-8"))
    assert lock.path.name == ".rfb-research-run.lock"
    assert {
        "boot_id",
        "pid",
        "start_ticks",
        "process_group",
        "nonce",
        "manifest_hash",
    } <= set(rec)
    with pytest.raises(LockBusy):
        ResearchLock(tmp_path, "a" * 64).acquire()
    before = rec["heartbeat_at"]
    lock.heartbeat()
    assert json.loads(lock.path.read_text(encoding="utf-8"))["heartbeat_at"] >= before
    with pytest.raises(LockTombstoneError):
        lock.release()


def test_verified_tombstone_requires_stale_and_binding(tmp_path):
    lock = ResearchLock(tmp_path, "b" * 64).acquire()
    lock.record["heartbeat_at"] = time.time() - 120
    lock.path.write_text(json.dumps(lock.record), encoding="utf-8")
    with pytest.raises(LockTombstoneError):
        ResearchLock.verified_tombstone(tmp_path, expected_manifest_hash="c" * 64)
    # Current process identity is still live, so tombstoning is rejected.
    with pytest.raises(LockTombstoneError):
        ResearchLock.verified_tombstone(tmp_path, expected_manifest_hash="b" * 64)


def test_lock_release_collision_preserves_existing_tombstone(tmp_path):
    lock = ResearchLock(tmp_path, "d" * 64).acquire()
    tomb = lock.path.with_name(lock.path.name + f".{lock.nonce}.tombstone")
    tomb.write_text('{"sentinel":true}', encoding="utf-8")

    with pytest.raises(LockTombstoneError, match="tombstone already exists"):
        lock.release_owned()

    assert lock.path.exists()
    assert tomb.read_text(encoding="utf-8") == '{"sentinel":true}'


def test_atomic_directory_rename_never_replaces_collision(tmp_path):
    source = tmp_path / "run.results.partial"
    destination = tmp_path / "run.results"
    source.mkdir()
    (source / "new.txt").write_text("new", encoding="utf-8")
    destination.mkdir()
    (destination / "existing.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(OSError):
        _rename_noreplace(source, destination)

    assert destination.joinpath("existing.txt").read_text(encoding="utf-8") == "keep"
    assert source.joinpath("new.txt").read_text(encoding="utf-8") == "new"


def test_parent_wide_lock_rejects_distinct_run_roots(tmp_path):
    parent = tmp_path / "approved"
    first_root = parent / "run-a"
    second_root = parent / "run-b"
    first = ResearchLock(
        parent,
        "e" * 64,
        run_id="run-a",
        remote_run_root=first_root,
        controller_nonce="nonce-a",
    ).acquire()
    record = json.loads(first.path.read_text(encoding="utf-8"))
    assert first.path == parent / ".rfb-research-run.lock"
    assert record["remote_run_root"] == str(first_root.resolve())
    assert record["run_id"] == "run-a"
    assert record["controller_nonce"] == "nonce-a"
    with pytest.raises(LockBusy):
        ResearchLock(
            parent,
            "f" * 64,
            run_id="run-b",
            remote_run_root=second_root,
            controller_nonce="nonce-b",
        ).acquire()


def test_parent_wide_lock_rejects_symlink_run_root(tmp_path):
    parent = tmp_path / "approved"
    target = tmp_path / "target"
    target.mkdir()
    link = parent / "run-link"
    parent.mkdir()
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable")
    with pytest.raises(LockTombstoneError, match="symlink"):
        ResearchLock(parent, "a" * 64, remote_run_root=link).acquire()
