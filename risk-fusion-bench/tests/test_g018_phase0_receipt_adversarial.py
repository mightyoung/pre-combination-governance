from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from rfb.contracts.canonical_json import canonical_bytes
from rfb.research import phase0_qualification
from rfb.research.phase0_qualification import (
    validate_phase0_qualification,
    write_phase0_qualification,
)

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parent


def _resign(manifest_path, receipt_path, manifest):
    unsigned = {
        key: value for key, value in manifest.items() if key != "manifest_self_sha256"
    }
    manifest["manifest_self_sha256"] = hashlib.sha256(
        canonical_bytes(unsigned)
    ).hexdigest()
    manifest_path.write_bytes(canonical_bytes(manifest))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["manifest_self_sha256"] = manifest["manifest_self_sha256"]
    receipt["manifest_raw_bytes_sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    body = {
        key: value for key, value in receipt.items() if key != "receipt_self_sha256"
    }
    receipt["receipt_self_sha256"] = hashlib.sha256(canonical_bytes(body)).hexdigest()
    receipt_path.write_bytes(canonical_bytes(receipt))


def test_resigned_single_node_g017_receipt_cannot_claim_full_suite(
    tmp_path, monkeypatch
):
    manifest_path, raw_receipt_path = write_phase0_qualification(WORKSPACE, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evidence_path = (
        WORKSPACE / ".omx/handoff/g018-phase0/evidence/g017.test-receipt.json"
    )
    forged = json.loads(evidence_path.read_text(encoding="utf-8"))
    forged["targets"] = [phase0_qualification.G017_NODES[-1]]
    forged["argv"][-1:] = forged["targets"]
    forged["passed"] = 1
    body = {key: value for key, value in forged.items() if key != "receipt_self_sha256"}
    forged["receipt_self_sha256"] = hashlib.sha256(canonical_bytes(body)).hexdigest()
    forged_raw = canonical_bytes(forged)
    for row in manifest["requirements"]:
        if row["test_refs"][0]["node_id"] == "g017":
            row["test_refs"][0]["sha256"] = hashlib.sha256(forged_raw).hexdigest()
    _resign(manifest_path, raw_receipt_path, manifest)
    original_read_bytes = Path.read_bytes

    def substituted_read_bytes(path):
        if path.resolve() == evidence_path.resolve():
            return forged_raw
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", substituted_read_bytes)
    with pytest.raises(ValueError, match="TEST_RECEIPT_EXECUTION_CONTRACT_MISMATCH"):
        validate_phase0_qualification(WORKSPACE, manifest_path, raw_receipt_path)


@pytest.mark.parametrize(
    "mutation",
    [
        "prefix-collision",
        "duplicate",
        "goal-started",
        "active",
        "empty-evidence",
        "self-claim",
    ],
)
def test_review_record_selection_rejects_noncompleted_or_nonindependent_evidence(
    mutation,
):
    goal_id = phase0_qualification.REVIEW_GOAL_IDS["G017"]
    record = {
        "goalId": goal_id,
        "event": "goal_completed",
        "status": "complete",
        "evidence": "Independent code review APPROVE.",
    }
    records = [record]
    if mutation == "prefix-collision":
        record["goalId"] += "-collision"
    elif mutation == "duplicate":
        records.append(dict(record))
    elif mutation == "goal-started":
        record["event"] = "goal_started"
    elif mutation == "active":
        record["status"] = "active"
    elif mutation == "empty-evidence":
        record["evidence"] = ""
    else:
        record["evidence"] = "Implementation complete by author."
    with pytest.raises(ValueError):
        phase0_qualification._select_review_record(records, "G017")


@pytest.mark.parametrize(
    "evidence",
    [
        "Not independently reviewed; reviewer did not approve.",
        "Independent review REQUEST CHANGES; this does not pass.",
    ],
)
def test_free_text_cannot_substitute_for_structured_review_approval(evidence):
    record = {
        "goalId": phase0_qualification.REVIEW_GOAL_IDS["G017"],
        "event": "goal_completed",
        "status": "complete",
        "evidence": evidence,
    }
    with pytest.raises(ValueError):
        phase0_qualification._select_review_record([record], "G017")


def test_only_structured_independent_approve_is_accepted():
    record = {
        "goalId": phase0_qualification.REVIEW_GOAL_IDS["G017"],
        "event": "goal_completed",
        "status": "complete",
        "decision": "APPROVE",
        "reviewer_role": "independent",
        "reviewer_id": "reviewer:G017",
        "producer_id": "author:G017",
        "evidence": "unparsed free text",
    }
    assert phase0_qualification._select_review_record([record], "G017") == record


def test_resigned_review_locator_prefix_collision_is_rejected(tmp_path):
    manifest_path, receipt_path = write_phase0_qualification(WORKSPACE, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["requirements"][0]["review_receipts"][0]["goal_id"] += "-collision"
    _resign(manifest_path, receipt_path, manifest)
    with pytest.raises((ValueError, ValidationError)):
        validate_phase0_qualification(WORKSPACE, manifest_path, receipt_path)
