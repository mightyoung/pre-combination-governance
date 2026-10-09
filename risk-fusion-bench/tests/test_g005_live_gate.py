from copy import deepcopy

import pytest

import hashlib
import hmac

from rfb.contracts.canonical_json import canonical_bytes
from rfb.live_gate import (
    REQUIRED_LIVE_GATES,
    LiveGateBlocked,
    LiveGateVerifier,
    canonical_hash,
)


def candidate():
    proofs = {
        "capacity": {
            "peak_bytes": 10,
            "planning_peak_bytes": 9,
            "subbudget_borrowing": False,
            "max_sampling_interval_seconds": 30,
        },
        "durable_result": {
            "sealed": True,
            "contains_raw_dataset": False,
            "truth_isolation": "PASS",
            "complete_rows": 14,
            "manifest_hash": canonical_hash({"manifest": 1}),
            "merkle_root": "b" * 64,
        },
        "archives": {
            "A": {
                "storage_identity": "a",
                "failure_domain": "host-a",
                "missing": 0,
                "unexpected": 0,
                "mismatch": 0,
                "readback_status": "PASS",
                "contains_raw_dataset": False,
            },
            "B": {
                "storage_identity": "b",
                "failure_domain": "host-b",
                "missing": 0,
                "unexpected": 0,
                "mismatch": 0,
                "readback_status": "PASS",
                "contains_raw_dataset": False,
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
            "approval_artifact_status": "ISSUED",
            "ds_stat_used_as_authorization": False,
            "ledger_states": [
                "APPROVAL_RECORDED",
                "CLAIMED",
                "PURGE_INTENT",
                "COMMITTED",
            ],
            "ephemeral_files_remaining": 0,
            "open_deleted_bytes": 0,
            "unexplained_space_delta": 0,
            "archive_a_reread": "PASS",
            "archive_b_reread": "PASS",
            "residual_paths": [],
        },
    }
    sealed = {
        "rows": 14,
        "archive_a": "a",
        "archive_b": "b",
        "segment_id": "seg-001",
        "manifest_hash": canonical_hash({"manifest": 1}),
        "bundle_count": 2,
        "bundle_ids": ["b1", "b2"],
        "method_ids": ["B0", "B1", "B2", "B3", "B4", "B5", "Proposed"],
        "proofs": proofs,
    }
    gates = {
        gate: {
            "status": "PASS",
            "evidence_refs": [f"sealed://seg-001/{gate}"],
            "evidence_hash": canonical_hash(
                proofs[
                    {
                        "segment_cap_gate": "capacity",
                        "durable_result_gate": "durable_result",
                        "result_archive_gate": "archives",
                        "regeneration_gate": "regeneration",
                        "dataset_purge_gate": "purge",
                    }[gate]
                ]
            ),
        }
        for gate in REQUIRED_LIVE_GATES
    }
    sealed["gate_proof_hashes"] = {
        gate: canonical_hash(
            proofs[
                {
                    "segment_cap_gate": "capacity",
                    "durable_result_gate": "durable_result",
                    "result_archive_gate": "archives",
                    "regeneration_gate": "regeneration",
                    "dataset_purge_gate": "purge",
                }[gate]
            ]
        )
        for gate in REQUIRED_LIVE_GATES
    }
    attestation_body = {
        "schema_id": "live-closeout-attestation.v1",
        "signer_id": "closeout-1",
        "key_id": "closeout-key-1",
        "trust_epoch": "epoch-1",
        "sealed_body": sealed,
        "segment_id": "seg-001",
        "manifest_hash": canonical_hash({"manifest": 1}),
        "bundle_count": 2,
        "bundle_ids": ["b1", "b2"],
        "method_ids": ["B0", "B1", "B2", "B3", "B4", "B5", "Proposed"],
    }
    attestation = {
        "schema_id": "live-closeout-attestation.v1",
        "signer_id": "closeout-1",
        "key_id": "closeout-key-1",
        "trust_epoch": "epoch-1",
        "signature": hmac.new(
            b"closeout-key", canonical_bytes(attestation_body), hashlib.sha256
        ).hexdigest(),
    }
    return {
        "classification": "LIVE_CLOSEOUT_EVIDENCE",
        "terminal_state": "RECONCILED",
        "bundle_count": 2,
        "contains_development_evidence": False,
        "c2_evidence_state": None,
        "sealed": True,
        "sealed_body": sealed,
        "bundle_ids": ["b1", "b2"],
        "method_ids": ["B0", "B1", "B2", "B3", "B4", "B5", "Proposed"],
        "sealed_evidence_hash": canonical_hash(sealed),
        "manifest_hash": canonical_hash({"manifest": 1}),
        "segment_id": "seg-001",
        "gates": gates,
        "closeout_attestation": attestation,
    }


def verifier():
    return LiveGateVerifier(
        signer_id="verifier-1",
        signing_key=b"verifier-key",
        trust_epoch="epoch-2",
        closeout_attestation_key=b"closeout-key",
    )


def test_live_verdict_set_is_signed_and_snapshot_bound():
    source = {"generation_id": "g1", "checklist_hash": "a" * 64}
    out = verifier().verify_and_sign(
        candidate(),
        source_snapshot=source,
        expected_snapshot_hash=canonical_hash(source),
    )
    assert out["classification"] == "LIVE_GATE_VERDICT_SET"
    assert set(out["verdicts"]) == set(REQUIRED_LIVE_GATES)
    assert verifier().verify_signature(out)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("classification", "DEVELOPMENT_GATE_EVIDENCE"),
        ("classification", "NONCONFIRMATORY_SIZING_ONLY"),
        ("terminal_state", "SIZING_REPORTED"),
        ("bundle_count", 1),
        ("contains_development_evidence", True),
        ("c2_evidence_state", "SIZING_REPORTED"),
        ("sealed", False),
    ],
)
def test_non_live_or_incomplete_candidate_is_rejected(field, value):
    item = candidate()
    item[field] = value
    with pytest.raises(LiveGateBlocked):
        verifier().verify_and_sign(
            item,
            source_snapshot={"x": 1},
            expected_snapshot_hash=canonical_hash({"x": 1}),
        )


def test_stale_snapshot_and_tampered_seal_are_rejected():
    with pytest.raises(LiveGateBlocked, match="snapshot"):
        verifier().verify_and_sign(
            candidate(), source_snapshot={"x": 1}, expected_snapshot_hash="0" * 64
        )
    item = candidate()
    item["sealed_body"]["rows"] = 15
    with pytest.raises(LiveGateBlocked, match="sealed|attestation"):
        verifier().verify_and_sign(
            item,
            source_snapshot={"x": 1},
            expected_snapshot_hash=canonical_hash({"x": 1}),
        )


def test_missing_or_nonpass_gate_is_rejected():
    item = candidate()
    item["gates"].pop("dataset_purge_gate")
    with pytest.raises(LiveGateBlocked, match="five"):
        verifier().verify_and_sign(
            item,
            source_snapshot={"x": 1},
            expected_snapshot_hash=canonical_hash({"x": 1}),
        )
    item = candidate()
    item["gates"]["regeneration_gate"]["status"] = "PENDING"
    with pytest.raises(LiveGateBlocked, match="regeneration"):
        verifier().verify_and_sign(
            item,
            source_snapshot={"x": 1},
            expected_snapshot_hash=canonical_hash({"x": 1}),
        )


@pytest.mark.parametrize(
    "ledger_states",
    [
        ["APPROVAL_RECORDED", "CLAIMED", "PURGE_INTENT"],
        ["APPROVAL_RECORDED", "CLAIMED", "PURGE_INTENT", "COMMITTED", "REPLAY"],
        ["APPROVAL_RECORDED", "CLAIMED", "PURGE_INTENT", "COMMITTED", "COMMITTED"],
        ["APPROVAL_RECORDED", "PURGE_INTENT", "CLAIMED", "COMMITTED"],
        ["APPROVAL_RECORDED", "CLAIMED", "PURGE_INTENT", "PURGE_INTENT"],
    ],
)
def test_purge_ledger_requires_exact_ordered_tuple(ledger_states):
    item = candidate()
    item["sealed_body"]["proofs"]["purge"]["ledger_states"] = ledger_states
    with pytest.raises(LiveGateBlocked, match="exactly match"):
        verifier().verify_and_sign(
            item,
            source_snapshot={"x": 1},
            expected_snapshot_hash=canonical_hash({"x": 1}),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("peak_bytes", -1),
        ("planning_peak_bytes", -1),
        ("max_sampling_interval_seconds", -1),
        ("peak_bytes", 25_000_000_001),
        ("planning_peak_bytes", 22_000_000_001),
        ("max_sampling_interval_seconds", 31),
    ],
)
def test_capacity_proof_rejects_negative_or_impossible_values(field, value):
    item = candidate()
    item["sealed_body"]["proofs"]["capacity"][field] = value
    with pytest.raises(LiveGateBlocked, match="non-negative|capacity proof"):
        verifier().verify_and_sign(
            item,
            source_snapshot={"x": 1},
            expected_snapshot_hash=canonical_hash({"x": 1}),
        )


@pytest.mark.parametrize("field", ["schema_id", "signer_id", "key_id", "trust_epoch"])
def test_closeout_attestation_record_tampering_is_rejected(field):
    item = candidate()
    item["closeout_attestation"][field] = "tampered"
    with pytest.raises(LiveGateBlocked, match="attestation"):
        verifier().verify_and_sign(
            item,
            source_snapshot={"x": 1},
            expected_snapshot_hash=canonical_hash({"x": 1}),
        )


def test_closeout_attester_identity_must_be_independent():
    item = candidate()
    item["closeout_attestation"]["signer_id"] = "verifier-1"
    with pytest.raises(LiveGateBlocked, match="independent"):
        verifier().verify_and_sign(
            item,
            source_snapshot={"x": 1},
            expected_snapshot_hash=canonical_hash({"x": 1}),
        )


def test_closeout_attestation_key_must_be_distinct():
    with pytest.raises(ValueError, match="distinct"):
        LiveGateVerifier(
            signer_id="verifier-1",
            signing_key=b"same-key",
            trust_epoch="epoch-2",
            closeout_attestation_key=b"same-key",
        )


def test_signature_tampering_is_detected():
    source = {"x": 1}
    out = verifier().verify_and_sign(
        candidate(),
        source_snapshot=source,
        expected_snapshot_hash=canonical_hash(source),
    )
    tampered = deepcopy(out)
    tampered["verdicts"]["segment_cap_gate"]["evidence_refs"] = ["evil"]
    assert not verifier().verify_signature(tampered)
