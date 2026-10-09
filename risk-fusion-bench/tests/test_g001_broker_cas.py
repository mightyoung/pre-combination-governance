import hashlib
import hmac
import json
import os
import socket
from dataclasses import replace

import pytest
from rfb.broker import (
    BrokerBlocked,
    CASPolicyBroker,
    ChecklistCommitter,
    sign_acl_attestation,
)
from rfb.broker.policy import REQUIRED_LIVE_GATES
from g001_fixture_helpers import strict_genesis
from rfb.authority.generation import (
    canonical_hash,
)
from rfb.contracts.canonical_json import canonical_bytes


class Dur:
    def fsync_file(self, p):
        pass

    def fsync_dir(self, p):
        pass


def _live_artifact():
    gates = {
        g: {"status": "PASS", "evidence_refs": [g + ":e"], "evidence_hash": "a" * 64}
        for g in (
            "segment_cap_gate",
            "durable_result_gate",
            "result_archive_gate",
            "regeneration_gate",
            "dataset_purge_gate",
        )
    }
    snapshot = {"runtime_gate": "PASS", **{g: "PASS" for g in gates}}
    body = {
        "schema_id": "live-gate-verdict-set.v1",
        "classification": "LIVE_GATE_VERDICT_SET",
        "signer_role": "LiveGateVerifier",
        "signer_id": "fixture",
        "trust_epoch": "epoch-1",
        "source_snapshot": snapshot,
        "source_snapshot_hash": canonical_hash(snapshot),
        "sealed_evidence_hash": "b" * 64,
        "segment_id": "seg-1",
        "manifest_hash": "c" * 64,
        "verdicts": gates,
        "issued_at": "2026-01-01T00:00:00+00:00",
    }
    return {
        **body,
        "signature": hmac.new(
            b"source", canonical_bytes(body), hashlib.sha256
        ).hexdigest(),
    }


def setup(tmp_path):
    key = b"root"
    genesis, _migrator, _legacy, _hashes, _freeze = strict_genesis(tmp_path, key=key)
    broker = CASPolicyBroker(
        tmp_path,
        submitter_keys={
            "ChecklistCommitter": b"k",
            "LiveGateVerifier": {"key": b"source", "trust_epoch": "epoch-1"},
        },
        signing_key=key,
        durability_provider=Dur(),
        acl_attestation=sign_acl_attestation(
            key=b"acl",
            root=tmp_path,
            trust_epoch="acl-1",
            generation_id=genesis["generation_id"],
            checklist_hash=canonical_hash({}),
            attester_id="acl-attester",
            key_id="acl-key-1",
            acl_entries=[{"principal": "broker", "access": "write"}],
        ),
        acl_attestation_key=b"acl",
        acl_attester_id="acl-attester",
        acl_attester_key_id="acl-key-1",
        acl_trust_epoch="acl-1",
    )
    src = _live_artifact()
    src["source_snapshot"] = {}
    src["source_snapshot_hash"] = canonical_hash({})
    body = dict(src)
    body.pop("signature", None)
    src["signature"] = hmac.new(
        b"source", canonical_bytes(body), hashlib.sha256
    ).hexdigest()
    ch = broker.current_authority()["checklist_hash"]
    proof = {
        "source_artifact": src,
        "source_snapshot": "snap",
        "source_hash": canonical_hash(src),
        "source_schema_id": "live-gate-verdict-set.v1",
        "trust_epoch": "epoch-1",
    }
    sig = hmac.new(b"source", canonical_bytes(proof), hashlib.sha256).hexdigest()
    kw = {
        "source_artifact": src,
        "source_snapshot": "snap",
        "source_hash": canonical_hash(src),
        "source_signer_role": "LiveGateVerifier",
        "source_signature": sig,
        "source_schema_id": "live-gate-verdict-set.v1",
        "trust_epoch": "epoch-1",
        "projection_policy_id": "frozen-default",
        "projection_policy_version": "1",
        "expected_current_generation_id": genesis["generation_id"],
        "expected_checklist_hash": ch,
        "patch": {
            "checklist": {**{g: src["verdicts"][g] for g in REQUIRED_LIVE_GATES}}
        },
    }
    return broker, ChecklistCommitter(b"k").envelope(**kw), kw


def test_cas_commit(tmp_path):
    broker, e, _ = setup(tmp_path)
    assert broker.submit(e)["audit_status"] in {"BROKER_COMMITTED", "COMMITTED"}


def test_stale_pair_rejected(tmp_path):
    broker, _e, kw = setup(tmp_path)
    kw["expected_current_generation_id"] = "0" * 32
    with pytest.raises(BrokerBlocked):
        broker.submit(ChecklistCommitter(b"k").envelope(**kw))


def test_pseudoprojection_rejected(tmp_path):
    broker, _e, kw = setup(tmp_path)
    kw["patch"] = {"evil": 1}
    with pytest.raises(BrokerBlocked):
        broker.submit(ChecklistCommitter(b"k").envelope(**kw))


def test_missing_proof_rejected(tmp_path):
    broker, _e, kw = setup(tmp_path)
    kw["source_hash"] = "0" * 64
    with pytest.raises(BrokerBlocked):
        broker.submit(ChecklistCommitter(b"k").envelope(**kw))


def test_after_cas_recovery(tmp_path):
    broker, e, _ = setup(tmp_path)
    with pytest.raises(RuntimeError):
        broker.submit(e, crash_at="cas")
    rows = [
        __import__("json").loads(x)
        for x in (tmp_path / "authority_audit.jsonl").read_text().splitlines()
        if x
    ]
    p = next(r for r in rows if r["status"] == "BROKER_PREPARED")
    out = broker.recover_commit(
        p["binding"]["request_id"], p["binding"]["generation_id"]
    )
    assert out["generation_id"] == p["binding"]["generation_id"]


def test_lock_live_expired_owner_is_not_reclaimed(tmp_path):
    broker, _, _ = setup(tmp_path)

    lock = tmp_path / ".broker.lock"
    lock.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "nonce": "live",
                "host": socket.gethostname(),
                "expires_at": 0,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(BrokerBlocked, match="live owner"):
        with broker._lock():
            raise AssertionError("live lock was reclaimed")
    assert lock.exists()


def test_prepared_before_cas_recovery_is_idempotent(tmp_path):
    broker, envelope, _ = setup(tmp_path)
    with pytest.raises(RuntimeError, match="simulated crash"):
        broker.submit(envelope, crash_at="prepared")
    row = next(
        json.loads(x)
        for x in (tmp_path / "authority_audit.jsonl").read_text().splitlines()
        if "BROKER_PREPARED" in x
    )
    out = broker.recover_commit(
        row["binding"]["request_id"], row["binding"]["generation_id"]
    )
    assert out["generation_id"] == row["binding"]["generation_id"]
    assert (
        broker.recover_commit(
            row["binding"]["request_id"], row["binding"]["generation_id"]
        )["generation_id"]
        == out["generation_id"]
    )


def test_rollback_temp_symlink_is_rejected(tmp_path):
    broker, _, _ = setup(tmp_path)
    target = tmp_path / "target"
    target.write_text("x")
    link = tmp_path / "CURRENT.rollback.x.tmp"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink unavailable")
    with pytest.raises(FileExistsError):
        broker._atomic_current("a" * 32, link.name)


def test_pseudo_checklist_source_rejected(tmp_path):
    broker, envelope, _ = setup(tmp_path)
    pseudo = replace(
        envelope,
        source_artifact={"checklist": {"runtime_gate": "PASS"}},
        source_hash="0" * 64,
        submitter_signature="",
    )
    pseudo = envelope.__class__.sign(
        key=b"k",
        **{k: v for k, v in pseudo.__dict__.items() if k != "submitter_signature"},
    )
    with pytest.raises(BrokerBlocked):
        broker.submit(pseudo)


def test_submitter_source_pairing_rejected(tmp_path):
    broker, envelope, _ = setup(tmp_path)
    bad = replace(
        envelope,
        source_signer_role="RuntimeFreezeAuthority",
        source_schema_id="runtime-baseline.v1",
        submitter_signature="",
    )
    bad = envelope.__class__.sign(
        key=b"k",
        **{k: v for k, v in bad.__dict__.items() if k != "submitter_signature"},
    )
    with pytest.raises(BrokerBlocked):
        broker.submit(bad)


def test_runtime_acl_missing_fails_closed(tmp_path):
    broker, _, _ = setup(tmp_path)
    broker.acl_attestation_key = b""
    with pytest.raises(BrokerBlocked, match="ACL"):
        broker._verify_acl(
            broker.current_authority()["generation_id"],
            broker.current_authority()["checklist_hash"],
        )


@pytest.mark.parametrize(
    "field",
    ["root_identity", "trust_epoch", "generation_id", "checklist_hash", "signature"],
)
def test_acl_attestation_tamper_or_wrong_binding_rejected(tmp_path, field):
    broker, _, _ = setup(tmp_path)
    att = dict(broker.acl_attestation)
    if field == "root_identity":
        att[field] = "0" * 64
    elif field == "trust_epoch":
        att[field] = "wrong"
    elif field == "generation_id":
        att[field] = "0" * 32
    elif field == "checklist_hash":
        att[field] = "0" * 64
    else:
        att[field] = "0" * 64
    broker.acl_attestation = att
    with pytest.raises(BrokerBlocked, match="ACL attestation"):
        broker._verify_acl(
            broker.current_authority()["generation_id"],
            broker.current_authority()["checklist_hash"],
        )


def test_recovery_revalidates_current_source_revocation(tmp_path):
    broker, envelope, _ = setup(tmp_path)
    with pytest.raises(RuntimeError, match="simulated crash"):
        broker.submit(envelope, crash_at="prepared")
    broker.keys["LiveGateVerifier"] = {
        "key": b"source",
        "trust_epoch": "epoch-1",
        "revoked": True,
    }
    row = next(
        json.loads(x)
        for x in (tmp_path / "authority_audit.jsonl").read_text().splitlines()
        if "BROKER_PREPARED" in x
    )
    with pytest.raises(BrokerBlocked, match="source proof"):
        broker.recover_commit(
            row["binding"]["request_id"], row["binding"]["generation_id"]
        )


def test_recovery_rejects_changed_acl_proof(tmp_path):
    broker, envelope, _ = setup(tmp_path)
    with pytest.raises(RuntimeError, match="simulated crash"):
        broker.submit(envelope, crash_at="prepared")
    broker.acl_attestation["trust_epoch"] = "tampered"
    row = next(
        json.loads(x)
        for x in (tmp_path / "authority_audit.jsonl").read_text().splitlines()
        if "BROKER_PREPARED" in x
    )
    with pytest.raises(BrokerBlocked, match="ACL proof changed"):
        broker.recover_commit(
            row["binding"]["request_id"], row["binding"]["generation_id"]
        )


def test_recovery_rejects_missing_prepared_projection_binding(tmp_path):
    broker, envelope, _ = setup(tmp_path)
    with pytest.raises(RuntimeError, match="simulated crash"):
        broker.submit(envelope, crash_at="prepared")
    rows = [
        json.loads(x)
        for x in (tmp_path / "authority_audit.jsonl").read_text().splitlines()
        if x
    ]
    prepared = next(r for r in rows if r["status"] == "BROKER_PREPARED")
    prepared["binding"].pop("patch")
    audit = tmp_path / "authority_audit.jsonl"
    audit.write_text(
        "\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(BrokerBlocked, match="audit hash chain tampered"):
        broker.recover_commit(
            prepared["binding"]["request_id"], prepared["binding"]["generation_id"]
        )
