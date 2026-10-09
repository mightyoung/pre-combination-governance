"""Post-fix adversarial probes for the R001/R003 contract boundary."""

from __future__ import annotations

import json

import pytest

from rfb.research.controller import prepare_legacy_r006 as prepare_run
from rfb.research.receipts import (
    result_tree_manifest,
    scan_closed_result,
    seal_receipt,
    validate_final_receipt,
    validate_remote_receipt,
)


def _manifest(**updates):
    value = {
        "run_id": "r004-probe",
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
        "adapter_id": "tep_fixture",
    }
    value.update(updates)
    return value


@pytest.mark.parametrize("run_id", ["../escape", "formal/runner", "D:\\formal\\run"])
def test_prepare_rejects_path_escape_and_formal_run_id(tmp_path, run_id):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest(run_id=run_id)), encoding="utf-8")
    with pytest.raises(ValueError):
        prepare_run(path)


def test_prepare_rejects_arbitrary_manifest_extras(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(_manifest(shell=True, argv=["rm", "-rf", "/"])), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        prepare_run(path)


def test_remote_receipt_rejects_missing_self_hash_and_result_tree():
    body = {
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
        "terminal_state": "RESULT_SEALED_REMOTE",
        "run_id": "r004",
        "manifest_sha256": "a" * 64,
        "directory_durable": True,
        "formal_artifacts_created": [],
        "shk001b_started": False,
    }
    with pytest.raises(ValueError):
        validate_remote_receipt(body)


def test_final_receipt_rejects_forged_minimal_success():
    with pytest.raises(ValueError):
        validate_final_receipt(
            seal_receipt(
                {
                    "terminal_state": "SUCCEEDED",
                    "remote_result_tree_sha256": "a" * 64,
                    "local_result_tree_sha256": "a" * 64,
                }
            )
        )


def test_result_manifest_rejects_unallowlisted_file_and_binary_raw_payload(tmp_path):
    root = tmp_path / "results"
    root.mkdir()
    (root / "allowed.json").write_text("{}", encoding="utf-8")
    (root / "raw.bin").write_bytes(b"truth\x00payload")
    with pytest.raises(ValueError, match="unallowlisted|raw|truth"):
        result_tree_manifest(root, allowlist={"allowed.json"})
    with pytest.raises(ValueError):
        scan_closed_result(root)


def test_result_manifest_hashes_are_stable_and_allowlist_closed(tmp_path):
    root = tmp_path / "results"
    root.mkdir()
    (root / "result.json").write_text("{}", encoding="utf-8")
    first = result_tree_manifest(root, allowlist={"result.json"})
    second = result_tree_manifest(root, allowlist={"result.json"})
    assert first == second and first["result.json"]["sha256"]
