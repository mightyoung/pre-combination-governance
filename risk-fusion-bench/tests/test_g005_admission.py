import hashlib
import hmac
import json

import pytest

from rfb.admission import (
    AdmissionBlocked,
    AdmissionBuilder,
    require_verified_admission,
    sign_admission_intent,
)
from rfb.contracts.canonical_json import canonical_bytes
from rfb.live_gate import LiveGateVerifier, REQUIRED_LIVE_GATES, canonical_hash


def live_verdict(snapshot):
    panel = ["B0", "B1", "B2", "B3", "B4", "B5", "Proposed"]
    manifest_hash = canonical_hash({"m": 1})
    gate_hashes = {gate: canonical_hash({"gate": gate}) for gate in REQUIRED_LIVE_GATES}
    sealed = {
        "rows": 14,
        "segment_id": "seg-1",
        "manifest_hash": manifest_hash,
        "bundle_count": 2,
        "bundle_ids": ["b1", "b2"],
        "method_ids": panel,
        "gate_proof_hashes": gate_hashes,
    }
    sealed["proofs"] = {
        "capacity": {
            "peak_bytes": 1,
            "planning_peak_bytes": 1,
            "subbudget_borrowing": False,
            "max_sampling_interval_seconds": 1,
        },
        "durable_result": {
            "sealed": True,
            "contains_raw_dataset": False,
            "truth_isolation": "PASS",
            "complete_rows": 14,
            "manifest_hash": manifest_hash,
            "merkle_root": "d" * 64,
        },
        "archives": {
            "A": {
                "missing": 0,
                "unexpected": 0,
                "mismatch": 0,
                "readback_status": "PASS",
                "contains_raw_dataset": False,
                "storage_identity": "archive-a",
                "failure_domain": "host-a",
            },
            "B": {
                "missing": 0,
                "unexpected": 0,
                "mismatch": 0,
                "readback_status": "PASS",
                "contains_raw_dataset": False,
                "storage_identity": "archive-b",
                "failure_domain": "host-b",
            },
        },
        "regeneration": {
            "sample_plan_frozen_before_execution": True,
            "sample_count": 2,
            "replacement_sampling": False,
            "payload_commitments_match": True,
            "full_panel_replay_match": True,
        },
        "purge": {
            "ledger_states": [
                "APPROVAL_RECORDED",
                "CLAIMED",
                "PURGE_INTENT",
                "COMMITTED",
            ],
            "approval_artifact_status": "ISSUED",
            "ds_stat_used_as_authorization": False,
            "ephemeral_files_remaining": 0,
            "open_deleted_bytes": 0,
            "unexplained_space_delta": 0,
            "archive_a_reread": "PASS",
            "archive_b_reread": "PASS",
            "residual_paths": [],
        },
    }
    gate_hashes = {
        "segment_cap_gate": canonical_hash(sealed["proofs"]["capacity"]),
        "durable_result_gate": canonical_hash(sealed["proofs"]["durable_result"]),
        "result_archive_gate": canonical_hash(sealed["proofs"]["archives"]),
        "regeneration_gate": canonical_hash(sealed["proofs"]["regeneration"]),
        "dataset_purge_gate": canonical_hash(sealed["proofs"]["purge"]),
    }
    sealed["gate_proof_hashes"] = gate_hashes
    sealed_hash = canonical_hash(sealed)
    attestation_body = {
        "sealed_body": sealed,
        "schema_id": "live-closeout-attestation.v1",
        "signer_id": "closeout-1",
        "key_id": "closeout-key-1",
        "trust_epoch": "e1",
        "segment_id": "seg-1",
        "manifest_hash": manifest_hash,
        "bundle_count": 2,
        "bundle_ids": ["b1", "b2"],
        "method_ids": panel,
    }
    candidate = {
        "classification": "LIVE_CLOSEOUT_EVIDENCE",
        "terminal_state": "RECONCILED",
        "bundle_count": 2,
        "bundle_ids": ["b1", "b2"],
        "method_ids": panel,
        "contains_development_evidence": False,
        "c2_evidence_state": None,
        "sealed": True,
        "sealed_body": sealed,
        "sealed_evidence_hash": sealed_hash,
        "manifest_hash": manifest_hash,
        "segment_id": "seg-1",
        "gates": {
            gate: {
                "status": "PASS",
                "evidence_refs": [f"sealed://seg-1/{gate}"],
                "evidence_hash": gate_hashes[gate],
            }
            for gate in REQUIRED_LIVE_GATES
        },
        "closeout_attestation": {
            "schema_id": "live-closeout-attestation.v1",
            "signer_id": "closeout-1",
            "key_id": "closeout-key-1",
            "trust_epoch": "e1",
            "signature": hmac.new(
                b"closeout", canonical_bytes(attestation_body), hashlib.sha256
            ).hexdigest(),
        },
    }
    return LiveGateVerifier(
        signer_id="lv1",
        signing_key=b"live",
        trust_epoch="e1",
        closeout_attestation_key=b"closeout",
    ).verify_and_sign(
        candidate,
        source_snapshot=snapshot,
        expected_snapshot_hash=canonical_hash(snapshot),
    )


def builder(ds_key=b"ds", stat_key=b"stat"):
    return AdmissionBuilder(
        live_verifier_keys={"lv1": {"key": b"live", "trust_epoch": "e1"}},
        signer_keys={
            "DS": {"key": ds_key, "key_id": "ds-1", "trust_epoch": "e2"},
            "STAT": {"key": stat_key, "key_id": "stat-1", "trust_epoch": "e2"},
        },
    )


def inputs():
    checklist = {"runtime_gate": "PASS"} | {
        gate: "PASS" for gate in REQUIRED_LIVE_GATES
    }
    verdict = live_verdict(checklist)
    context = {
        "runtime_baseline_hash": "1" * 64,
        "source_tree_hash": "2" * 64,
        "container_hash": "3" * 64,
        "method_registry_hash": "4" * 64,
        "archive_a_identity": "archive-a",
        "archive_a_readback_root": "5" * 64,
        "archive_b_identity": "archive-b",
        "archive_b_readback_root": "6" * 64,
        "segment_id": "seg-1",
        "segment_manifest_hash": verdict["manifest_hash"],
        "raw_dataset_retained": False,
        "effect_peeking": False,
        "formal_start_allowed": True,
        "checklist_snapshot_hash": canonical_hash(checklist),
        "verdict_set_hash": canonical_hash(verdict),
        "predecessor_generation_id": "pred-generation",
        "successor_generation_id": "succ-generation",
        "current_generation_id": "succ-generation",
        "verdict_predecessor_generation_id": "pred-generation",
        "source_snapshot_predecessor_generation_id": "pred-generation",
        "successor_receipt": {
            "generation_id": "succ-generation",
            "parent_generation": "pred-generation",
            "status": "COMMITTED",
        },
        "successor_manifest": {
            "generation_id": "succ-generation",
            "parent_generation": "pred-generation",
        },
        "successor_receipt_hash": canonical_hash(
            {
                "generation_id": "succ-generation",
                "parent_generation": "pred-generation",
                "status": "COMMITTED",
            }
        ),
        "successor_manifest_hash": canonical_hash(
            {"generation_id": "succ-generation", "parent_generation": "pred-generation"}
        ),
        "current_checklist_snapshot_hash": canonical_hash(checklist),
        "trusted_authority": {
            "generation_id": "succ-generation",
            "checklist_hash": canonical_hash(checklist),
        },
    }

    def audit(status, binding, previous=""):
        row = {
            "status": status,
            "event_id": status.lower(),
            "binding": binding,
            "previous_hash": previous,
        }
        row["entry_hash"] = canonical_hash(row)
        return row

    binding = {
        "request_id": "req-1",
        "operation_id": "op-1",
        "generation_id": "succ-generation",
        "predecessor_generation_id": "pred-generation",
        "predecessor_checklist_hash": canonical_hash({}),
        "successor_checklist_hash": canonical_hash(checklist),
        "source_hash": canonical_hash(verdict),
        "projection_policy_id": "frozen-default",
        "projection_policy_version": "1",
        "receipt_hash": "7" * 64,
        "manifest_hash": "8" * 64,
    }
    prepared = audit("BROKER_PREPARED", binding)
    committed = audit("BROKER_COMMITTED", binding, prepared["entry_hash"])
    context["broker_projection_proof"] = {
        "audit_chain": [prepared, committed],
        "prepared": prepared,
        "committed": committed,
        "predecessor_checklist_hash": binding["predecessor_checklist_hash"],
        "verdict_artifact_hash": binding["source_hash"],
        "projection_policy_id": "frozen-default",
        "projection_policy_version": "1",
        "receipt_hash": binding["receipt_hash"],
        "manifest_hash": binding["manifest_hash"],
        "current_generation_id": "succ-generation",
        "current_checklist_hash": canonical_hash(checklist),
    }
    return checklist, verdict, context


def signed_document(
    b=None, output=None, allow_write=False, *, ds_key=b"ds", stat_key=b"stat"
):
    b = b or builder()
    checklist, verdict, context = inputs()
    dry = b.dry_run(checklist_snapshot=checklist, verdict_set=verdict, context=context)
    ds = sign_admission_intent(
        role="DS",
        key_id="ds-1",
        trust_epoch="e2",
        key=ds_key,
        digest=dry["admission_intent_digest"],
    )
    stat = sign_admission_intent(
        role="STAT",
        key_id="stat-1",
        trust_epoch="e2",
        key=stat_key,
        digest=dry["admission_intent_digest"],
    )
    return b.build(
        checklist_snapshot=checklist,
        verdict_set=verdict,
        context=context,
        ds_signature=ds,
        stat_signature=stat,
        output_path=output,
        allow_write=allow_write,
    )


def test_dry_run_is_ready_but_does_not_write(tmp_path):
    checklist, verdict, context = inputs()
    dry = builder().dry_run(
        checklist_snapshot=checklist, verdict_set=verdict, context=context
    )
    assert dry["ready"] and dry["missing"] == []
    assert not (tmp_path / "FORMAL_STAGE_ADMISSION-v6.13.json").exists()


def test_verdict_is_bound_to_exact_checklist_snapshot():
    checklist, verdict, context = inputs()
    changed = dict(checklist) | {"projection_revision": "different"}
    changed_context = dict(context) | {
        "checklist_snapshot_hash": canonical_hash(changed)
    }
    dry = builder().dry_run(
        checklist_snapshot=changed,
        verdict_set=verdict,
        context=changed_context,
    )
    assert not dry["ready"]
    assert "live_verdict_set.checklist_snapshot_binding" in dry["missing"]


def test_verdict_segment_and_manifest_must_match_context():
    checklist, verdict, context = inputs()
    for field, value, expected in (
        ("segment_id", "other-segment", "context.segment_id.verdict_binding"),
        (
            "segment_manifest_hash",
            "f" * 64,
            "context.segment_manifest_hash.verdict_binding",
        ),
    ):
        changed = dict(context) | {field: value}
        dry = builder().dry_run(
            checklist_snapshot=checklist,
            verdict_set=verdict,
            context=changed,
        )
        assert not dry["ready"]
        assert expected in dry["missing"]


def test_explicit_write_and_shk_guard(tmp_path):
    path = tmp_path / "FORMAL_STAGE_ADMISSION-v6.13.json"
    b = builder()
    document = signed_document(b, path, True)
    assert b.verify_document(document)
    assert (
        require_verified_admission(
            path,
            b,
            expected_checklist_snapshot_hash=document["intent"][
                "checklist_snapshot_hash"
            ],
        )["status"]
        == "ADMITTED"
    )


def test_write_is_denied_by_default(tmp_path):
    with pytest.raises(AdmissionBlocked, match="allow_write"):
        signed_document(builder(), tmp_path / "admission.json", False)


@pytest.mark.parametrize("field", REQUIRED_LIVE_GATES)
def test_any_nonpass_gate_blocks(field):
    checklist, verdict, context = inputs()
    checklist[field] = "PENDING"
    context["checklist_snapshot_hash"] = canonical_hash(checklist)
    dry = builder().dry_run(
        checklist_snapshot=checklist, verdict_set=verdict, context=context
    )
    assert not dry["ready"] and f"checklist.{field}" in dry["missing"]


def test_same_key_and_different_digest_are_rejected():
    with pytest.raises(AdmissionBlocked, match="distinct"):
        signed_document(
            builder(ds_key=b"same", stat_key=b"same"),
            ds_key=b"same",
            stat_key=b"same",
        )

    b = builder()
    checklist, verdict, context = inputs()
    dry = b.dry_run(checklist_snapshot=checklist, verdict_set=verdict, context=context)
    ds = sign_admission_intent(
        role="DS",
        key_id="ds-1",
        trust_epoch="e2",
        key=b"ds",
        digest=dry["admission_intent_digest"],
    )
    stat = sign_admission_intent(
        role="STAT",
        key_id="stat-1",
        trust_epoch="e2",
        key=b"stat",
        digest="0" * 64,
    )
    with pytest.raises(AdmissionBlocked, match="different"):
        b.build(
            checklist_snapshot=checklist,
            verdict_set=verdict,
            context=context,
            ds_signature=ds,
            stat_signature=stat,
        )


def test_shk_guard_rejects_stale_authority_snapshot(tmp_path):
    path = tmp_path / "FORMAL_STAGE_ADMISSION-v6.13.json"
    b = builder()
    signed_document(b, path, True)
    with pytest.raises(AdmissionBlocked, match="stale"):
        require_verified_admission(
            path,
            b,
            expected_checklist_snapshot_hash="f" * 64,
        )


def test_missing_or_tampered_admission_keeps_shk_blocked(tmp_path):
    b = builder()
    path = tmp_path / "FORMAL_STAGE_ADMISSION-v6.13.json"
    with pytest.raises(AdmissionBlocked, match="absent"):
        require_verified_admission(path, b, expected_checklist_snapshot_hash="a" * 64)
    signed_document(b, path, True)
    item = json.loads(path.read_text(encoding="utf-8"))
    item["effect_peeking"] = True
    path.write_text(json.dumps(item), encoding="utf-8")
    with pytest.raises(AdmissionBlocked, match="verification"):
        require_verified_admission(path, b, expected_checklist_snapshot_hash="a" * 64)


@pytest.mark.parametrize(
    "field",
    [
        "predecessor_generation_id",
        "successor_generation_id",
        "current_generation_id",
        "successor_receipt",
        "successor_manifest",
        "trusted_authority",
    ],
)
def test_complete_lineage_is_mandatory(field):
    checklist, verdict, context = inputs()
    context.pop(field)
    dry = builder().dry_run(
        checklist_snapshot=checklist, verdict_set=verdict, context=context
    )
    assert not dry["ready"] and any(field in item for item in dry["missing"])


def test_lineage_rejects_inconsistent_current_and_tampered_parent():
    checklist, verdict, context = inputs()
    for changed, expected in (
        ({"current_generation_id": "pred-generation"}, "trusted_successor"),
        ({"successor_receipt_hash": "0" * 64}, "successor_receipt_hash"),
        (
            {
                "successor_manifest": {
                    "generation_id": "succ-generation",
                    "parent_generation": "other",
                }
            },
            "parent_binding",
        ),
    ):
        dry = builder().dry_run(
            checklist_snapshot=checklist,
            verdict_set=verdict,
            context=context | changed,
        )
        assert not dry["ready"] and any(expected in item for item in dry["missing"])


def test_verdict_and_source_snapshot_must_name_predecessor():
    checklist, verdict, context = inputs()
    dry = builder().dry_run(
        checklist_snapshot=checklist,
        verdict_set=verdict,
        context=context | {"verdict_predecessor_generation_id": "succ-generation"},
    )
    assert not dry["ready"]


def test_broker_projection_proof_tamper_and_reorder_fail():
    checklist, verdict, context = inputs()
    proof = context["broker_projection_proof"]
    for changed in (
        {"audit_chain": list(reversed(proof["audit_chain"]))},
        {
            "committed": dict(proof["committed"])
            | {
                "binding": dict(proof["committed"]["binding"])
                | {"manifest_hash": "0" * 64}
            }
        },
    ):
        bad = dict(context)
        bad["broker_projection_proof"] = dict(proof) | changed
        dry = builder().dry_run(
            checklist_snapshot=checklist, verdict_set=verdict, context=bad
        )
        assert not dry["ready"]
        assert any(
            item.startswith("context.broker_projection_proof")
            for item in dry["missing"]
        )


def test_trust_store_rejects_cross_role_key_alias_and_duplicate_id():
    checklist, verdict, context = inputs()
    b = AdmissionBuilder(
        live_verifier_keys={
            "lv1": {"key": b"shared", "trust_epoch": "e1", "key_id": "same-id"}
        },
        signer_keys={
            "DS": {"key": b"shared", "key_id": "same-id", "trust_epoch": "e2"},
            "STAT": {"key": b"stat", "key_id": "stat-1", "trust_epoch": "e2"},
        },
    )
    dry = b.dry_run(checklist_snapshot=checklist, verdict_set=verdict, context=context)
    assert not dry["ready"]
    assert "trust_store.duplicate_key_material.distinct" in dry["missing"]
    assert "trust_store.duplicate_key_id" in dry["missing"]
