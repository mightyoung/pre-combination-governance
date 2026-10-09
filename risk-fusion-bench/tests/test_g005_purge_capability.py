import json
import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from rfb.purge_capability import (
    PurgeBlocked,
    PurgeLedger,
    execute_purge,
    freeze_allowlist,
    issue_capability,
    issue_execution_approval,
    issue_no_writer_attestation,
)


def test_unlinked_crash_recovery(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX descriptor protocol")
    root = make_root(tmp_path)
    values = artifacts(root)
    ledger = PurgeLedger(tmp_path / "unlinked")
    with pytest.raises(RuntimeError):
        execute(root, ledger, values, crash_at="unlinked")
    assert any(r["state"] == "UNLINK_QUARANTINED" for r in ledger.rows())
    result = execute(root, ledger, values)
    assert result["status"] == "COMMITTED" and not (root / "scratch.tmp").exists()


def test_abort_after_prior_commit_is_readable(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX descriptor protocol")
    root = make_root(tmp_path)
    values = artifacts(root)
    ledger = PurgeLedger(tmp_path / "partial")
    (root / "scratch.tmp").write_bytes(b"tampered")
    with pytest.raises(PurgeBlocked):
        execute(root, ledger, values)

    rows = ledger.rows()
    aborted = [r for r in rows if r["state"] == "ABORTED"]
    assert (
        any(r["state"] == "UNLINK_COMMITTED" for r in rows)
        and aborted[-1]["relative"] == "scratch.tmp"
    )
    with pytest.raises(PurgeBlocked):
        ledger.append("COMMITTED", aborted[-1])


NOW = datetime(2026, 7, 31, tzinfo=UTC)


def identities(same=False):
    issuer = {
        "role": "PurgeCapabilityIssuer",
        "identity": "issuer",
        "key_id": "issuer-key",
        "trust_epoch": "e1",
        "key": b"issuer",
    }
    approver = {
        "role": "DestructiveApprover",
        "identity": "issuer" if same else "approver",
        "key_id": "issuer-key" if same else "approver-key",
        "trust_epoch": "e1",
        "key": b"issuer" if same else b"approver",
    }
    attester = {
        "role": "PurgeNoWriterAttester",
        "identity": "attester",
        "key_id": "attester-key",
        "trust_epoch": "e1",
        "key": b"attester",
    }
    if same:
        attester["key_id"] = "issuer-key"
    return issuer, approver, attester


def make_root(tmp_path):
    root = tmp_path / "segment"
    (root / "ephemeral").mkdir(parents=True)
    (root / "ephemeral" / "a.bin").write_bytes(b"a")
    (root / "scratch.tmp").write_bytes(b"b")
    return root


def artifacts(root, same=False):
    issuer, approver, attester = identities(same)
    st = root.stat()
    identity = {
        "mount": "server:/export",
        "st_dev": int(st.st_dev),
        "st_ino": int(st.st_ino),
        "identity_verified": True,
    }
    allowlist = freeze_allowlist(["ephemeral/a.bin", "scratch.tmp"])
    capability = issue_capability(
        issuer=issuer,
        segment_id="seg-1",
        root=str(root),
        root_identity=identity,
        manifest_hash="a" * 64,
        allowlist=allowlist,
        nonce="n-1",
        operation_id="op-1",
        prerequisites={
            "result_sealed_local": "PASS",
            "result_archive_a": "PASS",
            "result_archive_b": "PASS",
            "regen_verified": "PASS",
            "contains_raw_dataset": False,
            "truth_isolation": "PASS",
        },
        now=NOW,
    )
    approval = issue_execution_approval(
        approver=approver,
        capability=capability,
        issuer_trust=issuer,
        now=NOW,
    )
    attestation = issue_no_writer_attestation(
        attester=attester,
        root=root,
        root_identity=identity,
        operation_id="op-1",
        allowlist_hash=capability["allowlist_hash"],
        target_bindings=capability["target_bindings"],
        now=NOW,
        facts={"exclusive_writer": True},
    )
    return issuer, approver, attester, identity, capability, approval, attestation


def execute(root, ledger, artifacts_tuple, **extra):
    issuer, approver, attester, identity, capability, approval, attestation = (
        artifacts_tuple
    )
    return execute_purge(
        root=root,
        capability=capability,
        approval=approval,
        issuer_trust=issuer,
        approver_trust=approver,
        attester_trust=attester,
        no_writer_attestation=attestation,
        current_root_identity=identity,
        ledger=ledger,
        now=NOW + timedelta(seconds=1),
        **extra,
    )


def test_allowlisted_purge_and_idempotent_retry(tmp_path):
    root = make_root(tmp_path)
    values = artifacts(root)
    ledger = PurgeLedger(tmp_path / "ledger.jsonl")
    if os.name == "nt":
        with pytest.raises(PurgeBlocked, match="handle-relative"):
            execute(root, ledger, values)
        assert (root / "ephemeral" / "a.bin").exists()
        return
    assert execute(root, ledger, values)["status"] == "COMMITTED"
    assert not (root / "ephemeral" / "a.bin").exists()
    assert execute(root, ledger, values) == {"status": "COMMITTED", "deleted": []}


def test_capability_and_approval_match_closed_schemas(tmp_path):
    _, _, _, _, capability, approval, _ = artifacts(make_root(tmp_path))
    contracts = Path(__file__).parents[1] / "src" / "rfb" / "contracts"
    for name, document in (
        ("purge_capability.schema.json", capability),
        ("purge_execution_approval.schema.json", approval),
    ):
        schema = json.loads((contracts / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(document)


@pytest.mark.parametrize("crash", ["claimed", "intent"])
def test_crash_recovery(tmp_path, crash):
    root = make_root(tmp_path)
    values = artifacts(root)
    ledger = PurgeLedger(tmp_path / "ledger.jsonl")
    with pytest.raises(RuntimeError):
        execute(root, ledger, values, crash_at=crash)
    if os.name == "nt":
        with pytest.raises(PurgeBlocked, match="handle-relative"):
            execute(root, ledger, values)
        return
    assert execute(root, ledger, values)["status"] == "COMMITTED"


def test_issuer_and_approver_are_distinct(tmp_path):
    with pytest.raises(PurgeBlocked, match="distinct"):
        artifacts(make_root(tmp_path), same=True)


def test_expiry_and_root_drift_fail_closed(tmp_path):
    root = make_root(tmp_path)
    issuer, approver, attester, identity, capability, approval, attestation = artifacts(
        root
    )
    with pytest.raises(PurgeBlocked, match="expired"):
        execute_purge(
            root=root,
            capability=capability,
            approval=approval,
            issuer_trust=issuer,
            approver_trust=approver,
            attester_trust=attester,
            no_writer_attestation=attestation,
            current_root_identity=identity,
            ledger=PurgeLedger(tmp_path / "x"),
            now=NOW + timedelta(hours=1),
        )
    with pytest.raises(PurgeBlocked, match="drift"):
        execute_purge(
            root=root,
            capability=capability,
            approval=approval,
            issuer_trust=issuer,
            approver_trust=approver,
            attester_trust=attester,
            no_writer_attestation=attestation,
            current_root_identity=identity | {"st_ino": 10},
            ledger=PurgeLedger(tmp_path / "y"),
            now=NOW + timedelta(seconds=1),
        )


@pytest.mark.parametrize("path", ["../x", "C:/x", "/x", "a/../../x"])
def test_allowlist_rejects_escape(path):
    with pytest.raises(PurgeBlocked):
        freeze_allowlist([path])


def test_symlink_target_is_rejected(tmp_path):
    root = make_root(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("x")
    link = root / "ephemeral" / "a.bin"
    link.unlink()
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink unavailable")
    with pytest.raises(PurgeBlocked, match="symlink"):
        execute(root, PurgeLedger(tmp_path / "l"), artifacts(root))


def test_binding_change_and_nonce_replay_are_rejected(tmp_path):
    root = make_root(tmp_path)
    values = artifacts(root)
    ledger = PurgeLedger(tmp_path / "ledger")
    if os.name == "nt":
        with pytest.raises(PurgeBlocked, match="handle-relative"):
            execute(root, ledger, values)
        return
    execute(root, ledger, values)
    row = ledger.rows()[0]
    with pytest.raises(PurgeBlocked, match="changed"):
        ledger.assert_binding(row | {"root": "other"})
    with pytest.raises(PurgeBlocked, match="replay"):
        ledger.assert_binding(row | {"operation_id": "op-2"})


def test_active_operation_lock_rejects_concurrent_executor(tmp_path):
    root = make_root(tmp_path)
    values = artifacts(root)
    identity = values[3]
    lock = root / ".rfb-purge-operation.lock"
    lock.write_text(
        json.dumps(
            {
                "operation_id": "op-1",
                "nonce": "n-1",
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "root_identity": identity,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PurgeBlocked, match="already active"):
        execute(root, PurgeLedger(tmp_path / "locked-ledger"), values)


def test_target_binding_rejects_hash_swap_before_unlink(tmp_path):
    root = make_root(tmp_path)
    values = artifacts(root)
    target = root / "scratch.tmp"
    target.write_bytes(b"tampered")
    with pytest.raises(PurgeBlocked, match="target identity|hash|handle-relative"):
        execute(root, PurgeLedger(tmp_path / "tamper-ledger"), values)
    assert target.exists()


def test_no_writer_attestation_required_and_tamper_fails_closed(tmp_path):
    root = make_root(tmp_path)
    values = artifacts(root)
    issuer, approver, attester, identity, cap, app, att = values
    kwargs = dict(
        root=root,
        capability=cap,
        approval=app,
        issuer_trust=issuer,
        approver_trust=approver,
        current_root_identity=identity,
        ledger=PurgeLedger(tmp_path / "att-ledger"),
        now=NOW + timedelta(seconds=1),
    )
    with pytest.raises(PurgeBlocked, match="attester"):
        execute_purge(**kwargs)
    forged = dict(att)
    forged["signature"] = "0" * 64
    with pytest.raises(PurgeBlocked, match="signature"):
        execute_purge(**kwargs, attester_trust=attester, no_writer_attestation=forged)


def test_no_writer_attestation_binding_and_fact_negatives(tmp_path):
    root = make_root(tmp_path)
    issuer, approver, attester, identity, cap, app, att = artifacts(root)
    base = dict(
        root=root,
        capability=cap,
        approval=app,
        issuer_trust=issuer,
        approver_trust=approver,
        attester_trust=attester,
        current_root_identity=identity,
        ledger=PurgeLedger(tmp_path / "bind-ledger"),
        now=NOW + timedelta(seconds=1),
    )
    for field, value in (
        ("root", "other"),
        ("operation_id", "other"),
        ("allowlist_hash", "f" * 64),
        ("target_bindings", {}),
    ):
        forged = dict(att)
        forged[field] = value
        with pytest.raises(PurgeBlocked, match="binding|signature"):
            execute_purge(**base, no_writer_attestation=forged)
    forged = dict(att)
    forged["facts"] = {"exclusive_writer": "yes"}
    with pytest.raises(PurgeBlocked, match="exclusive|signature"):
        execute_purge(**base, no_writer_attestation=forged)


def test_same_attester_key_as_issuer_is_rejected(tmp_path):
    root = make_root(tmp_path)
    issuer, approver, _, identity, cap, app, _ = artifacts(root)
    bad = dict(issuer)
    bad["role"] = "PurgeNoWriterAttester"
    bad["identity"] = "other"
    att = issue_no_writer_attestation(
        attester=bad,
        root=root,
        root_identity=identity,
        operation_id=cap["operation_id"],
        allowlist_hash=cap["allowlist_hash"],
        target_bindings=cap["target_bindings"],
        now=NOW,
        facts={"exclusive_writer": True},
    )
    with pytest.raises(PurgeBlocked, match="independent"):
        execute_purge(
            root=root,
            capability=cap,
            approval=app,
            issuer_trust=issuer,
            approver_trust=approver,
            attester_trust=bad,
            no_writer_attestation=att,
            current_root_identity=identity,
            ledger=PurgeLedger(tmp_path / "same-ledger"),
            now=NOW + timedelta(seconds=1),
        )


def test_mutation_after_verification_fails_closed(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("Windows fail-closed handle unavailable")
    root = make_root(tmp_path)
    values = artifacts(root)
    target = root / "scratch.tmp"
    original = os.unlink
    fired = {"v": False}

    def race(path, *args, **kwargs):
        if not fired["v"]:
            fired["v"] = True
            target.unlink()
            target.write_bytes(b"replacement")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", race)
    with pytest.raises(PurgeBlocked):
        execute(root, PurgeLedger(tmp_path / "race"), values)
    assert target.exists()


def test_expired_approval_recorded_state_rejects(tmp_path):
    root = make_root(tmp_path)
    values = artifacts(root)
    issuer, approver, attester, identity, cap, app, att = values
    ledger = PurgeLedger(tmp_path / "expired")
    binding = {
        "operation_id": cap["operation_id"],
        "segment_id": cap["segment_id"],
        "root": cap["root"],
        "manifest_hash": cap["manifest_hash"],
        "allowlist_hash": cap["allowlist_hash"],
        "target_bindings": cap["target_bindings"],
        "nonce": cap["nonce"],
        "capability_hash": __import__(
            "rfb.purge_capability", fromlist=["canonical_hash"]
        ).canonical_hash(cap),
        "approval_hash": __import__(
            "rfb.purge_capability", fromlist=["canonical_hash"]
        ).canonical_hash(app),
    }
    ledger.append("APPROVAL_RECORDED", binding)
    with pytest.raises(PurgeBlocked, match="expired"):
        execute_purge(
            root=root,
            capability=cap,
            approval=app,
            issuer_trust=issuer,
            approver_trust=approver,
            attester_trust=attester,
            no_writer_attestation=att,
            current_root_identity=identity,
            ledger=ledger,
            now=NOW + timedelta(hours=1),
        )
    assert (root / "scratch.tmp").exists()


def test_crash_after_unlink_requires_exact_reconciliation(tmp_path):
    if os.name == "nt":
        pytest.skip("Windows fail-closed handle unavailable")
    # The implementation's explicit crash hooks cover pre-unlink states; ensure no residual retry can authorize replacement.
    root = make_root(tmp_path)
    values = artifacts(root)
    ledger = PurgeLedger(tmp_path / "abort")
    with pytest.raises(RuntimeError):
        execute(root, ledger, values, crash_at="intent")
    (root / "scratch.tmp").unlink()
    (root / "scratch.tmp").write_bytes(b"replacement")
    with pytest.raises(PurgeBlocked):
        execute(root, ledger, values)


def test_quarantine_phase_rows_and_recovery(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX descriptor protocol")
    root = make_root(tmp_path)
    artifacts(root)
    for crash in ("prepared", "renamed", "quarantined", "unlinked", "committed"):
        run_root = tmp_path / crash
        run_root.mkdir()
        (run_root / "ephemeral").mkdir()
        (run_root / "ephemeral" / "a.bin").write_bytes(b"a")
        (run_root / "scratch.tmp").write_bytes(b"b")
        vals = artifacts(run_root)
        ledger = PurgeLedger(run_root / "ledger.jsonl")
        with pytest.raises(RuntimeError):
            execute(run_root, ledger, vals, crash_at=crash)
        states = [row["state"] for row in ledger.rows()]
        assert "UNLINK_PREPARED" in states
        if crash == "renamed":
            assert not (run_root / "ephemeral" / "a.bin").exists()
            assert any(
                (run_root / name).is_dir() for name in [".rfb-purge-quarantine-op-1"]
            )
        if crash in {"quarantined", "committed", "unlinked"}:
            assert "UNLINK_QUARANTINED" in states
        execute(run_root, ledger, vals)
        assert ledger.state(vals[4]["operation_id"]) == "COMMITTED"
        assert not (run_root / "scratch.tmp").exists()


def test_same_leaf_race_before_rename_records_aborted(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX descriptor protocol")
    root = make_root(tmp_path)
    values = artifacts(root)
    ledger = PurgeLedger(tmp_path / "race-ledger.jsonl")
    target = root / "scratch.tmp"
    original = __import__("os").rename
    fired = {"value": False}

    def race(src, dst, **kwargs):
        if not fired["value"]:
            fired["value"] = True
            target.unlink()
            target.write_bytes(b"replacement")
        return original(src, dst, **kwargs)

    monkeypatch.setattr("os.rename", race)
    with pytest.raises(PurgeBlocked, match="identity|ABORTED"):
        execute(root, ledger, values)
    assert target.exists() and target.read_bytes() == b"replacement"
    assert any(row["state"] == "ABORTED" for row in ledger.rows())
