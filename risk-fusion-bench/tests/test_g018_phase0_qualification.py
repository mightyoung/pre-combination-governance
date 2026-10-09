from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

from rfb.contracts.canonical_json import canonical_bytes
from rfb.research import phase0_qualification
from rfb.research.phase0_qualification import (
    build_phase0_qualification,
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
    receipt_body = {
        key: value for key, value in receipt.items() if key != "receipt_self_sha256"
    }
    receipt["receipt_self_sha256"] = hashlib.sha256(
        canonical_bytes(receipt_body)
    ).hexdigest()
    receipt_path.write_bytes(canonical_bytes(receipt))


def test_manifest_is_closed_self_bound_and_fail_closed_on_unfrozen_environment():
    manifest = build_phase0_qualification(WORKSPACE)
    schema = json.loads(
        (
            REPO / "src/rfb/contracts/phase0_qualification_manifest.schema.json"
        ).read_text(encoding="utf-8")
    )
    validate(manifest, schema)
    assert manifest["bindings"]["preregistration_sha256"] == (
        "28da62ba38df360de52b87d373b7fcb498967c8af21bd2b83084e6680b023550"
    )
    assert manifest["bindings"]["scope_decision_sha256"] == (
        "d738590057a64099faf7d287773040a08b265ced8a2aa4280288e601655ff80c"
    )
    assert [row["id"] for row in manifest["requirements"]] == [
        f"P0-{index:02d}" for index in range(1, 11)
    ]
    prereg = json.loads(
        (WORKSPACE / ".omx/plans/MMEPreregistration-v1.json").read_text(
            encoding="utf-8"
        )
    )
    originals = {
        row["id"]: row["requirement"]
        for row in prereg["phase0_entry_gate"]["requirements"]
    }
    for row in manifest["requirements"]:
        assert row["requirement"] == originals[row["id"]]
        assert (
            row["requirement_sha256"]
            == hashlib.sha256(row["requirement"].encode()).hexdigest()
        )
        assert (
            row["source_refs"]
            and row["test_refs"]
            and row["audit_refs"]
            and row["review_receipts"]
        )
    p010 = manifest["requirements"][-1]
    assert p010["status"] == "PASS"
    assert p010["blocker_code"] is None
    assert manifest["decision"] == {
        "phase0_qualified": True,
        "authorization_eligible": True,
        "execution_authorized": False,
        "authorization_artifact_created": False,
    }
    unsigned = {
        key: value for key, value in manifest.items() if key != "manifest_self_sha256"
    }
    assert (
        manifest["manifest_self_sha256"]
        == hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
    )


def test_namespace_audits_are_executable_zero_violation_and_formal_boundary_stable():
    manifest = build_phase0_qualification(WORKSPACE)
    assert set(manifest["audits"]) == {
        "credential",
        "truth_path",
        "candidate_write",
        "d_test",
        "environment",
        "lifecycle_qualification",
    }
    for name in ("credential", "truth_path", "candidate_write", "d_test"):
        audit = manifest["audits"][name]
        assert audit["scope"] and audit["allowlist"] and audit["command"]
        assert (
            audit["command_sha256"]
            == hashlib.sha256(audit["command"].encode()).hexdigest()
        )
        assert audit["violations"] == []
        assert audit["status"] == "PASS"
    assert (
        len(
            next(row for row in manifest["requirements"] if row["id"] == "P0-09")[
                "audit_refs"
            ]
        )
        == 4
    )
    boundary = manifest["formal_boundary"]
    assert (
        boundary["gate_checklist_before_sha256"]
        == boundary["gate_checklist_after_sha256"]
    )
    assert (
        boundary["gate_checklist_after_sha256"]
        == "923be30aa19a9c475d49ac5aa00703fdc6fd98cb29ccfd73fbbf3483a8535331"
    )
    assert boundary["formal_stage_admission_present"] is False
    assert boundary["d_test_present"] is False
    assert boundary["remote_actions"] is False
    assert boundary["mme_blocks_executed"] == 0


def test_writer_emits_canonical_manifest_and_external_raw_hash_receipt(tmp_path):
    manifest_path, receipt_path = write_phase0_qualification(WORKSPACE, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert manifest_path.read_bytes() == canonical_bytes(manifest)
    assert (
        receipt["manifest_raw_bytes_sha256"]
        == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    )
    assert receipt["manifest_self_sha256"] == manifest["manifest_self_sha256"]
    assert receipt["receipt_self_sha256"]
    assert (
        validate_phase0_qualification(WORKSPACE, manifest_path, receipt_path)
        == manifest
    )
    assert not (tmp_path / "MMEExecutionAuthorization.json").exists()


def test_scanner_process_failure_returns_machine_readable_blocked_evidence(
    monkeypatch,
):
    def fail(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 9, stdout="", stderr="unavailable")

    monkeypatch.setattr(phase0_qualification.subprocess, "run", fail)
    audit = phase0_qualification._execute_scanner(WORKSPACE, "credential")
    assert audit["status"] == "BLOCKED"
    assert audit["exit_code"] == 9
    assert audit["violations"] == ["SCANNER_UNAVAILABLE"]
    assert audit["argv"] and audit["scope"] and audit["allowlist"]


def test_reopen_validator_accepts_derived_scanner_block_and_rejects_false_pass(
    tmp_path,
):
    manifest_path, receipt_path = write_phase0_qualification(WORKSPACE, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    audit = manifest["audits"]["credential"]
    audit.update(
        status="BLOCKED",
        exit_code=9,
        violations=["SCANNER_UNAVAILABLE"],
        scope=["requested scanner:credential"],
        allowlist=["none; scanner execution is mandatory"],
    )
    audit_body = {key: value for key, value in audit.items() if key != "report_sha256"}
    audit["report_sha256"] = hashlib.sha256(canonical_bytes(audit_body)).hexdigest()
    p009 = next(row for row in manifest["requirements"] if row["id"] == "P0-09")
    p009.update(status="BLOCKED", blocker_code="BLOCKED_AUDIT_SCANNER_UNAVAILABLE")
    manifest["decision"].update(
        phase0_qualified=False,
        authorization_eligible=False,
    )
    for ref in p009["audit_refs"]:
        if ref["audit_id"] == "credential":
            ref["report_sha256"] = audit["report_sha256"]
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
    receipt_body = {
        key: value for key, value in receipt.items() if key != "receipt_self_sha256"
    }
    receipt["receipt_self_sha256"] = hashlib.sha256(
        canonical_bytes(receipt_body)
    ).hexdigest()
    receipt_path.write_bytes(canonical_bytes(receipt))
    assert (
        validate_phase0_qualification(WORKSPACE, manifest_path, receipt_path)[
            "requirements"
        ][8]["status"]
        == "BLOCKED"
    )
    manifest["requirements"][8].update(status="PASS", blocker_code=None)
    unsigned = {
        key: value for key, value in manifest.items() if key != "manifest_self_sha256"
    }
    manifest["manifest_self_sha256"] = hashlib.sha256(
        canonical_bytes(unsigned)
    ).hexdigest()
    manifest_path.write_bytes(canonical_bytes(manifest))
    with pytest.raises(ValueError, match="REQUIREMENT_STATUS_NOT_DERIVED"):
        validate_phase0_qualification(WORKSPACE, manifest_path, receipt_path)


@pytest.mark.parametrize("mutation", ["missing", "replacement", "extra", "ordinary"])
def test_reopen_validator_requires_exact_fixed_test_suite_topology(tmp_path, mutation):
    manifest_path, receipt_path = write_phase0_qualification(WORKSPACE, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    row = manifest["requirements"][1]
    if mutation == "missing":
        row["test_refs"] = []
    elif mutation == "replacement":
        row["test_refs"] = manifest["requirements"][4]["test_refs"]
    elif mutation == "extra":
        row["test_refs"].append(manifest["requirements"][4]["test_refs"][0])
    else:
        row["test_refs"] = [row["source_refs"][0]]
    _resign(manifest_path, receipt_path, manifest)
    with pytest.raises((ValueError, ValidationError)):
        validate_phase0_qualification(WORKSPACE, manifest_path, receipt_path)


def test_p002_acceptance_checks_and_review_record_are_semantically_bound(tmp_path):
    manifest_path, receipt_path = write_phase0_qualification(WORKSPACE, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    p002 = manifest["requirements"][1]
    assert [item["check_id"] for item in p002["acceptance_checks"]] == list(
        phase0_qualification.P002_ACCEPTANCE_CHECKS
    )
    p002["acceptance_checks"][0]["observed"] = "FAIL"
    _resign(manifest_path, receipt_path, manifest)
    with pytest.raises((ValueError, ValidationError)):
        validate_phase0_qualification(WORKSPACE, manifest_path, receipt_path)
    manifest_path, receipt_path = write_phase0_qualification(WORKSPACE, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["requirements"][1]["review_receipts"][0]["artifact_sha256"] = "0" * 64
    _resign(manifest_path, receipt_path, manifest)
    with pytest.raises(ValueError, match="REVIEW_RECEIPT_HASH_MISMATCH"):
        validate_phase0_qualification(WORKSPACE, manifest_path, receipt_path)


@pytest.mark.parametrize("field", ["scope", "argv"])
def test_reopen_validator_rejects_resigned_fake_scanner_contract(tmp_path, field):
    manifest_path, receipt_path = write_phase0_qualification(WORKSPACE, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    audit = manifest["audits"]["credential"]
    audit[field] = ["fake"]
    if field == "argv":
        audit["argv_sha256"] = hashlib.sha256(canonical_bytes(audit[field])).hexdigest()
    audit_body = {key: value for key, value in audit.items() if key != "report_sha256"}
    audit["report_sha256"] = hashlib.sha256(canonical_bytes(audit_body)).hexdigest()
    for ref in manifest["requirements"][8]["audit_refs"]:
        if ref["audit_id"] == "credential":
            ref["report_sha256"] = audit["report_sha256"]
    _resign(manifest_path, receipt_path, manifest)
    with pytest.raises(ValueError, match="SCANNER_"):
        validate_phase0_qualification(WORKSPACE, manifest_path, receipt_path)


@pytest.mark.parametrize(
    "protected_name",
    ["FORMAL_STAGE_ADMISSION-v6.13.json", "MMEExecutionAuthorization.json"],
)
def test_reopen_validator_rechecks_protected_namespaces(
    tmp_path, monkeypatch, protected_name
):
    manifest_path, receipt_path = write_phase0_qualification(WORKSPACE, tmp_path)
    original_exists = Path.exists

    def simulated_exists(path):
        if path == WORKSPACE / protected_name:
            return True
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", simulated_exists)
    with pytest.raises(ValueError, match="PROTECTED_NAMESPACE_PRESENT"):
        validate_phase0_qualification(WORKSPACE, manifest_path, receipt_path)


def test_builder_derives_qualification_decision_from_all_requirement_statuses(
    monkeypatch,
):
    audit = phase0_qualification._environment_audit()
    audit.update(
        status="PASS",
        blocker_code=None,
        violations=[],
        sealed_linux_runtime=True,
        pip_check_returncode=0,
        frozen_runtime_checks={
            key: "PASS"
            for key in (
                "unit",
                "property",
                "integration",
                "reproducibility",
                "schema",
                "artifact_hash",
            )
        },
    )
    body = {key: value for key, value in audit.items() if key != "report_sha256"}
    audit["report_sha256"] = hashlib.sha256(canonical_bytes(body)).hexdigest()
    monkeypatch.setattr(phase0_qualification, "_environment_audit", lambda: audit)
    decision = build_phase0_qualification(WORKSPACE)["decision"]
    assert decision == {
        "phase0_qualified": True,
        "authorization_eligible": True,
        "execution_authorized": False,
        "authorization_artifact_created": False,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "self",
        "source",
        "requirement",
        "duplicate-id",
        "integer-id",
        "time-inversion",
        "raw-receipt",
    ],
)
def test_reopen_validator_rejects_tampering(tmp_path, mutation):
    manifest_path, receipt_path = write_phase0_qualification(WORKSPACE, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if mutation == "self":
        manifest["manifest_self_sha256"] = "0" * 64
    elif mutation == "source":
        manifest["bindings"]["research_source_set"][0]["sha256"] = "0" * 64
    elif mutation == "requirement":
        manifest["requirements"][0]["requirement"] += " altered"
    elif mutation == "duplicate-id":
        manifest["requirements"][1]["id"] = "P0-01"
    elif mutation == "integer-id":
        manifest["requirements"][0]["id"] = 1
    elif mutation == "time-inversion":
        receipt["generated_at_utc"] = "2000-01-01T00:00:00Z"
    else:
        receipt["manifest_raw_bytes_sha256"] = "0" * 64
    if mutation not in {"self", "time-inversion", "raw-receipt"}:
        unsigned = {
            key: value
            for key, value in manifest.items()
            if key != "manifest_self_sha256"
        }
        manifest["manifest_self_sha256"] = hashlib.sha256(
            canonical_bytes(unsigned)
        ).hexdigest()
    manifest_path.write_bytes(canonical_bytes(manifest))
    if mutation not in {"time-inversion", "raw-receipt"}:
        receipt["manifest_raw_bytes_sha256"] = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        receipt["manifest_self_sha256"] = manifest["manifest_self_sha256"]
    receipt_body = {
        key: value for key, value in receipt.items() if key != "receipt_self_sha256"
    }
    receipt["receipt_self_sha256"] = hashlib.sha256(
        canonical_bytes(receipt_body)
    ).hexdigest()
    receipt_path.write_bytes(canonical_bytes(receipt))
    with pytest.raises((ValueError, ValidationError)):
        validate_phase0_qualification(WORKSPACE, manifest_path, receipt_path)
