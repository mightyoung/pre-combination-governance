"""R001 two-phase receipt and closed-result contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLASSIFICATION = {
    "execution_lane": "RESEARCH",
    "classification": "DEVELOPMENT_NONCONFIRMATORY",
    "formal_gate_effect": "NONE",
    "formal_admission_eligible": False,
    "shk001b_eligible": False,
    "contains_formal_claims": False,
}


@pytest.mark.parametrize(
    "name",
    ["remote_execution_receipt.schema.json", "final_run_receipt.schema.json"],
)
def test_receipt_schemas_share_immutable_classification(name: str):
    path = ROOT / "src" / "rfb" / "contracts" / name
    if not path.is_file():
        pytest.fail(f"R001 receipt schema missing: {path}")
    schema = json.loads(path.read_text(encoding="utf-8"))
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    assert set(CLASSIFICATION) <= required
    for field, value in CLASSIFICATION.items():
        assert props[field].get("const") == value


def test_remote_receipt_terminal_state_cannot_be_succeeded():
    from rfb.research.receipts import validate_remote_receipt  # noqa: PLC0415

    receipt = {**CLASSIFICATION, "terminal_state": "SUCCEEDED"}
    with pytest.raises((ValueError, TypeError, KeyError)):
        validate_remote_receipt(receipt)


def test_final_receipt_succeeded_requires_matching_two_copy_hash_chain():
    from rfb.research.receipts import validate_final_receipt  # noqa: PLC0415

    receipt = {
        **CLASSIFICATION,
        "terminal_state": "SUCCEEDED",
        "remote_result_tree_sha256": "a" * 64,
        "local_result_tree_sha256": "b" * 64,
    }
    with pytest.raises((ValueError, TypeError, KeyError)):
        validate_final_receipt(receipt)


@pytest.mark.parametrize(
    "secret",
    [
        "raw dataset payload",
        "scorer truth labels",
        "ssh_password=not-for-artifacts",
        "D:\\datasets\\TEP\\d01_te.csv",
        "/home/r4900g3/yhh/datasets/TEP/d01_te.csv",
        "src/rfb/formal/runner.py",
    ],
)
def test_closed_result_scan_rejects_raw_truth_credentials_and_source_paths(
    tmp_path, secret
):
    from rfb.research.receipts import scan_closed_result  # noqa: PLC0415

    result = tmp_path / "results"
    result.mkdir()
    (result / "result.json").write_text(
        json.dumps({"diagnostic": secret}), encoding="utf-8"
    )
    with pytest.raises((ValueError, PermissionError)):
        scan_closed_result(result)


def _failed_receipt(terminal_state: str):
    from rfb.research.receipts import seal_receipt  # noqa: PLC0415

    body = {
        "run_id": "r005-reopen",
        "terminal_state": terminal_state,
        "failure_code": "TEST_FAILURE",
        "runtime_format": "python_zipapp_stdlib_v1",
        "runtime_path": f"{'a' * 64}.pyz",
        "runtime_file_sha256": "a" * 64,
        "runtime_source_sha256": "b" * 64,
        "runtime_manifest_sha256": "c" * 64,
        "runtime_dependency_profile": "stdlib_only",
    }
    return seal_receipt(body)


def test_reopen_validate_remote_receipt_rechecks_publication_hash(tmp_path):
    from rfb.research.receipts import reopen_validate_remote_receipt  # noqa: PLC0415

    value = _failed_receipt("FAILED")
    path = tmp_path / "REMOTE_EXECUTION_RECEIPT.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    from rfb.contracts.canonical_json import (  # noqa: PLC0415
        canonical_bytes,
        sha256_hex,
    )

    publication_hash = sha256_hex(canonical_bytes(value))
    assert reopen_validate_remote_receipt(path, expected_hash=publication_hash)
    with pytest.raises(ValueError, match="publication hash"):
        reopen_validate_remote_receipt(path, expected_hash="0" * 64)


def test_reopen_validate_final_receipt_rejects_tampered_file(tmp_path):
    from rfb.research.receipts import reopen_validate_final_receipt  # noqa: PLC0415

    value = _failed_receipt("FAILED")
    path = tmp_path / "FINAL_RUN_RECEIPT.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    path.write_text(json.dumps({**value, "failure_code": "TAMPERED"}), encoding="utf-8")
    with pytest.raises(ValueError):
        reopen_validate_final_receipt(path, expected_hash=value["self_hash"])


def _frozen_r77_remote():
    path = (
        ROOT.parent
        / ".omx"
        / "handoff"
        / "g014-live"
        / "g014-r006-20260816T130000Z-r77"
        / "controller"
        / "results"
        / "g014-r006-20260816T130000Z-r77.receipts"
        / "REMOTE_EXECUTION_RECEIPT.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _reseal_r77_remote(*, scorer_artifact=..., **updates):
    from rfb.contracts.canonical_json import canonical_bytes, sha256_hex
    from rfb.research.models import CLASSIFICATION as MODEL_CLASSIFICATION
    from rfb.research.receipts import seal_receipt

    body = _frozen_r77_remote()
    body.pop("self_hash")
    body.update(updates)
    if scorer_artifact is not ...:
        body["scorer_artifact"] = scorer_artifact
    inner = {
        key: value
        for key, value in body.items()
        if key not in {"receipt_self_hash", *MODEL_CLASSIFICATION}
    }
    body["receipt_self_hash"] = sha256_hex(canonical_bytes(inner))
    return seal_receipt(body)


def _r77_remote_with_scorer(scorer_artifact):
    return _reseal_r77_remote(scorer_artifact=scorer_artifact)


def test_remote_scorer_artifact_schema_validator_and_reopen_chain(tmp_path):
    from rfb.contracts.canonical_json import canonical_bytes, sha256_hex
    from rfb.research.receipts import (
        reopen_validate_remote_receipt,
        validate_remote_receipt,
    )

    scorer = {
        "status": "SEALED",
        "scientific_eligible": True,
        "failure_code": None,
        "truth_content_sha256": "1" * 64,
        "prediction_seal_self_hash": "2" * 64,
        "excluded_from_result_tree": True,
        "ephemeral": True,
        "d_test_namespace_touched": False,
    }
    receipt = _r77_remote_with_scorer(scorer)
    assert validate_remote_receipt(receipt) == receipt
    path = tmp_path / "REMOTE_EXECUTION_RECEIPT.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    publication_hash = sha256_hex(canonical_bytes(receipt))
    assert (
        reopen_validate_remote_receipt(path, expected_hash=publication_hash) == receipt
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"run_id": "g014-r006-20260816T130000Z-r78"},
        {"ended_at_utc": "2026-08-20T00:00:00Z"},
    ],
)
def test_new_or_mutated_tep_receipt_cannot_omit_scorer_artifact(updates):
    from rfb.research.receipts import validate_remote_receipt

    receipt = _reseal_r77_remote(**updates)
    with pytest.raises(ValueError, match="REMOTE_TEP_SCORER_ARTIFACT_REQUIRED"):
        validate_remote_receipt(receipt)


@pytest.mark.parametrize(
    "scorer",
    [
        {
            "status": "NOT_APPLICABLE",
            "scientific_eligible": False,
            "failure_code": None,
            "excluded_from_result_tree": True,
            "ephemeral": True,
            "d_test_namespace_touched": False,
        },
        {
            "status": "SCORER_FAILED",
            "scientific_eligible": False,
            "failure_code": "SCORER_TRUTH_SEAL_FAILED",
            "prediction_seal_self_hash": "2" * 64,
            "excluded_from_result_tree": True,
            "ephemeral": True,
            "d_test_namespace_touched": False,
        },
    ],
)
def test_tep_receipt_requires_scientifically_eligible_sealed_scorer(scorer):
    from rfb.research.receipts import validate_remote_receipt

    with pytest.raises(ValueError, match="REMOTE_(TEP_SCORER|SCORER_FAILED)"):
        validate_remote_receipt(_r77_remote_with_scorer(scorer))


def test_not_applicable_scorer_remains_valid_for_non_tep_adapter():
    from rfb.research.receipts import validate_remote_receipt

    scorer = {
        "status": "NOT_APPLICABLE",
        "scientific_eligible": False,
        "failure_code": None,
        "excluded_from_result_tree": True,
        "ephemeral": True,
        "d_test_namespace_touched": False,
    }
    receipt = _reseal_r77_remote(
        scorer_artifact=scorer,
        adapter_id="tep_fixture",
    )
    assert validate_remote_receipt(receipt) == receipt


@pytest.mark.parametrize(
    "mutation",
    [
        {"excluded_from_result_tree": False},
        {"ephemeral": False},
        {"d_test_namespace_touched": True},
        {"truth": {"label": 1}},
        {"result_path": "/secret/truth"},
        {"scientific_eligible": False},
        {"failure_code": "NOT_NULL"},
    ],
)
def test_remote_scorer_artifact_rejects_boundary_or_sensitive_fields(mutation):
    from rfb.research.receipts import validate_remote_receipt

    scorer = {
        "status": "SEALED",
        "scientific_eligible": True,
        "failure_code": None,
        "truth_content_sha256": "1" * 64,
        "prediction_seal_self_hash": "2" * 64,
        "excluded_from_result_tree": True,
        "ephemeral": True,
        "d_test_namespace_touched": False,
        **mutation,
    }
    with pytest.raises(ValueError):
        validate_remote_receipt(_r77_remote_with_scorer(scorer))


def test_controller_blocks_scorer_failed_before_final_or_promotion(tmp_path):
    from rfb.research.controller import bind_downloaded_result

    scorer = {
        "status": "SCORER_FAILED",
        "scientific_eligible": False,
        "failure_code": "SCORER_TRUTH_ALIGNMENT_INVALID",
        "prediction_seal_self_hash": "2" * 64,
        "excluded_from_result_tree": True,
        "ephemeral": True,
        "d_test_namespace_touched": False,
    }
    receipt = _r77_remote_with_scorer(scorer)
    receipt_path = tmp_path / "REMOTE_EXECUTION_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(
        ValueError,
        match="REMOTE_SCORER_FAILED:SCORER_TRUTH_ALIGNMENT_INVALID",
    ):
        bind_downloaded_result(
            None,
            remote_receipt_path=receipt_path,
            lock_release_proof_path=tmp_path / "unused-proof.json",
            local_result=tmp_path / "unused-result",
            evidence_root=tmp_path / "must-not-exist",
        )
    assert not (tmp_path / "must-not-exist").exists()


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("missing", "REMOTE_TEP_SCORER_ARTIFACT_REQUIRED"),
        ("not-applicable", "REMOTE_TEP_SCORER_NOT_ELIGIBLE"),
    ],
)
def test_bind_downloaded_result_rejects_ineligible_tep_scorer_before_final(
    tmp_path, mode, error
):
    from rfb.research.controller import bind_downloaded_result

    if mode == "missing":
        receipt = _reseal_r77_remote(ended_at_utc="2026-08-20T00:00:00Z")
    else:
        receipt = _r77_remote_with_scorer(
            {
                "status": "NOT_APPLICABLE",
                "scientific_eligible": False,
                "failure_code": None,
                "excluded_from_result_tree": True,
                "ephemeral": True,
                "d_test_namespace_touched": False,
            }
        )
    receipt_path = tmp_path / "REMOTE_EXECUTION_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    evidence = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match=error):
        bind_downloaded_result(
            None,
            remote_receipt_path=receipt_path,
            lock_release_proof_path=tmp_path / "unused-proof.json",
            local_result=tmp_path / "unused-result",
            evidence_root=evidence,
        )
    assert not evidence.exists()


def test_controller_scorer_gate_accepts_valid_sealed_artifact():
    from rfb.research.receipts import require_remote_scorer_ready_for_final

    scorer = {
        "status": "SEALED",
        "scientific_eligible": True,
        "failure_code": None,
        "truth_content_sha256": "1" * 64,
        "prediction_seal_self_hash": "2" * 64,
        "excluded_from_result_tree": True,
        "ephemeral": True,
        "d_test_namespace_touched": False,
    }
    receipt = _r77_remote_with_scorer(scorer)
    assert require_remote_scorer_ready_for_final(receipt) is None


def test_r77_legacy_remote_receipt_without_scorer_field_remains_valid():
    from rfb.research.receipts import validate_remote_receipt

    receipt = _frozen_r77_remote()
    assert "scorer_artifact" not in receipt
    assert validate_remote_receipt(receipt) == receipt
