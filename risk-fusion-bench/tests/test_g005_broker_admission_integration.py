import hashlib
import hmac
import json
import copy
import sys
from pathlib import Path

from rfb.broker import CASPolicyBroker, ChecklistCommitter, sign_acl_attestation
from rfb.contracts.canonical_json import canonical_bytes
from rfb.live_gate import canonical_hash

# Keep sibling fixtures importable when pytest is invoked with only PYTHONPATH=src.
_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from test_g005_admission import builder, inputs, live_verdict  # noqa: E402
from g001_fixture_helpers import Durability, strict_genesis  # noqa: E402


def test_real_broker_projection_admission_roundtrip(tmp_path):
    key = b"generation-key"
    pred = {"runtime_gate": "PASS"}
    genesis, _m, _legacy, _hashes, _freeze = strict_genesis(
        tmp_path, key=key, checklist=pred
    )
    broker = CASPolicyBroker(
        tmp_path,
        submitter_keys={
            "ChecklistCommitter": b"submitter",
            "LiveGateVerifier": {"key": b"live", "trust_epoch": "e1"},
        },
        signing_key=key,
        durability_provider=Durability(),
        acl_attestation=sign_acl_attestation(
            key=b"acl",
            root=tmp_path,
            trust_epoch="acl-e",
            generation_id=genesis["generation_id"],
            checklist_hash=canonical_hash(pred),
            attester_id="acl-attester",
            key_id="acl-key-1",
            acl_entries=[{"principal": "broker", "access": "write"}],
        ),
        acl_attestation_key=b"acl",
        acl_trust_epoch="acl-e",
        acl_attester_id="acl-attester",
        acl_attester_key_id="acl-key-1",
    )
    checklist, _verdict, context = inputs()
    artifact = live_verdict(pred)
    artifact["source_snapshot"] = pred
    artifact["source_snapshot_hash"] = canonical_hash(pred)
    body = dict(artifact)
    body.pop("signature", None)
    artifact["signature"] = hmac.new(
        b"live", canonical_bytes(body), hashlib.sha256
    ).hexdigest()
    proof = {
        "source_artifact": artifact,
        "source_snapshot": "fixture",
        "source_hash": canonical_hash(artifact),
        "source_schema_id": "live-gate-verdict-set.v1",
        "trust_epoch": "e1",
    }
    source_sig = hmac.new(b"live", canonical_bytes(proof), hashlib.sha256).hexdigest()
    patch = {"checklist": checklist}
    envelope = ChecklistCommitter(b"submitter").envelope(
        source_artifact=artifact,
        source_snapshot="fixture",
        source_hash=proof["source_hash"],
        source_signer_role="LiveGateVerifier",
        source_signature=source_sig,
        source_schema_id=proof["source_schema_id"],
        trust_epoch="e1",
        projection_policy_id="frozen-default",
        projection_policy_version="1",
        expected_current_generation_id=genesis["generation_id"],
        expected_checklist_hash=broker.current_authority()["checklist_hash"],
        patch=patch,
    )
    envelope = ChecklistCommitter(b"submitter").envelope(
        **(
            {
                k: v
                for k, v in envelope.__dict__.items()
                if k not in ("submitter_role", "submitter_signature")
            }
            | {"patch": broker.projection(envelope)}
        )
    )
    out = broker.submit(envelope)
    successor = out
    checklist = envelope.patch["checklist"]
    rows = [
        json.loads(line)
        for line in (tmp_path / "authority_audit.jsonl").read_text().splitlines()
    ]
    prepared = next(r for r in rows if r["status"] == "BROKER_PREPARED")
    committed = next(r for r in rows if r["status"] == "BROKER_COMMITTED")
    binding = committed["binding"]
    context.update(
        {
            "predecessor_checklist_snapshot": pred,
            "predecessor_checklist_hash": canonical_hash(pred),
            "successor_checklist_snapshot": checklist,
            "successor_checklist_hash": canonical_hash(checklist),
            "successor_receipt": successor["receipt"],
            "successor_manifest": successor["manifest"],
            "successor_receipt_hash": canonical_hash(successor["receipt"]),
            "successor_manifest_hash": canonical_hash(successor["manifest"]),
            "current_checklist_snapshot_hash": canonical_hash(checklist),
            "trusted_authority": {
                "generation_id": successor["generation_id"],
                "checklist_hash": canonical_hash(checklist),
                "generation_binding": successor["generation_id"],
            },
            "predecessor_generation_id": binding["predecessor_generation_id"],
            "successor_generation_id": successor["generation_id"],
            "current_generation_id": successor["generation_id"],
            "verdict_predecessor_generation_id": binding["predecessor_generation_id"],
            "source_snapshot_predecessor_generation_id": binding[
                "predecessor_generation_id"
            ],
            "checklist_snapshot_hash": canonical_hash(checklist),
            "verdict_set_hash": canonical_hash(artifact),
        }
    )
    context["broker_projection_proof"] = {
        "audit_chain": rows,
        "prepared": prepared,
        "committed": committed,
        "predecessor_checklist_hash": binding["predecessor_checklist_hash"],
        "verdict_artifact_hash": binding["source_hash"],
        "projection_policy_id": binding["projection_policy_id"],
        "projection_policy_version": binding["projection_policy_version"],
        "receipt_hash": binding["receipt_hash"],
        "manifest_hash": binding["manifest_hash"],
        "current_generation_id": successor["generation_id"],
        "current_checklist_hash": canonical_hash(checklist),
        "successor_checklist_hash": canonical_hash(checklist),
    }
    dry = builder().dry_run(
        checklist_snapshot=checklist, verdict_set=artifact, context=context
    )
    assert dry["ready"] is True
    tampered = dict(context["broker_projection_proof"])
    tampered["manifest_hash"] = "0" * 64
    bad = dict(context)
    bad["broker_projection_proof"] = tampered
    assert (
        builder().dry_run(
            checklist_snapshot=checklist, verdict_set=artifact, context=bad
        )["ready"]
        is False
    )

    reordered = dict(context["broker_projection_proof"])
    reordered["audit_chain"] = list(reversed(reordered["audit_chain"]))
    bad = dict(context)
    bad["broker_projection_proof"] = reordered
    assert (
        builder().dry_run(
            checklist_snapshot=checklist, verdict_set=artifact, context=bad
        )["ready"]
        is False
    )

    parent_tampered = copy.deepcopy(context)
    parent_tampered["successor_manifest"]["parent_generation"] = "wrong-parent"
    assert (
        builder().dry_run(
            checklist_snapshot=checklist, verdict_set=artifact, context=parent_tampered
        )["ready"]
        is False
    )
