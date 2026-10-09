from __future__ import annotations

import copy
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

from rfb.research import phase0_frozen_runtime, phase0_qualification
from rfb.research.phase0_frozen_runtime import (
    RECEIPT_KINDS,
    validate_frozen_runtime,
)

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parent
OUTPUT = WORKSPACE / ".omx/handoff/g019-phase0"


def test_g019_windows_sharing_violation_is_bounded_retry(monkeypatch):
    outcomes = iter(
        (
            subprocess.CompletedProcess([], 0xC0000043, b"", b""),
            subprocess.CompletedProcess([], 0, b"ok", b""),
        )
    )
    calls = []
    monkeypatch.setattr(phase0_frozen_runtime.os, "name", "nt")
    monkeypatch.setattr(
        phase0_frozen_runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: calls.append(True) or next(outcomes),
    )
    monkeypatch.setattr(phase0_frozen_runtime.time, "sleep", lambda _value: None)

    completed = phase0_frozen_runtime._run_process(["python"])

    assert completed.returncode == 0
    assert len(calls) == 2


def test_g019_deterministic_dll_failure_is_not_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(phase0_frozen_runtime.os, "name", "nt")
    monkeypatch.setattr(
        phase0_frozen_runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: (
            calls.append(True)
            or subprocess.CompletedProcess([], 4, b"", b"ImportError: DLL load failed")
        ),
    )

    completed = phase0_frozen_runtime._run_process(["python"])

    assert completed.returncode == 4
    assert len(calls) == 1


def test_g019_windows_sharing_violation_retry_handles_text_mode(monkeypatch):
    outcomes = iter(
        (
            subprocess.CompletedProcess([], 0xC0000043, "", ""),
            subprocess.CompletedProcess([], 0, "ok", ""),
        )
    )
    monkeypatch.setattr(phase0_frozen_runtime.os, "name", "nt")
    monkeypatch.setattr(
        phase0_frozen_runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: next(outcomes),
    )
    monkeypatch.setattr(phase0_frozen_runtime.time, "sleep", lambda _value: None)

    completed = phase0_frozen_runtime._run_process(["python"], text=True)

    assert completed.stdout == "ok"


def test_g019_frozen_runtime_strict_reopen_and_exact_receipt_set():
    result = validate_frozen_runtime(OUTPUT)
    assert result["status"] == "PASS"
    assert [ref["kind"] for ref in result["receipt_refs"]] == list(RECEIPT_KINDS)


@pytest.mark.parametrize("artifact", ["manifest", "qualification", "receipt"])
def test_g019_closed_schemas_reject_resigned_unknown_fields(artifact):
    contracts = REPO / "src/rfb/contracts"
    if artifact == "manifest":
        document = json.loads(
            (OUTPUT / "runtime-manifest.json").read_text(encoding="utf-8")
        )
        schema_name = "phase0_frozen_runtime_manifest.schema.json"
    elif artifact == "qualification":
        document = json.loads(
            (OUTPUT / "qualification.json").read_text(encoding="utf-8")
        )
        schema_name = "phase0_frozen_runtime_qualification.schema.json"
    else:
        document = json.loads(
            (OUTPUT / "receipts/unit.json").read_text(encoding="utf-8")
        )
        schema_name = "phase0_frozen_runtime_receipt.schema.json"
    forged = copy.deepcopy(document)
    forged["unregistered"] = True
    schema = json.loads((contracts / schema_name).read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        validate(forged, schema)


def test_g019_receipt_raw_tamper_is_rejected(monkeypatch):
    target = (OUTPUT / "receipts/property.json").resolve()
    original = phase0_frozen_runtime._file_sha

    def forged_hash(path):
        if Path(path).resolve() == target:
            return "0" * 64
        return original(Path(path))

    monkeypatch.setattr(phase0_frozen_runtime, "_file_sha", forged_hash)
    with pytest.raises(ValueError, match="RECEIPT_RAW_HASH_MISMATCH"):
        validate_frozen_runtime(OUTPUT)


def test_g019_live_source_set_tamper_blocks_p010(monkeypatch):
    original = phase0_frozen_runtime._source_binding

    def forged_source(workspace):
        result = original(workspace)
        result["source_set_sha256"] = "0" * 64
        return result

    monkeypatch.setattr(phase0_frozen_runtime, "_source_binding", forged_source)
    audit = phase0_qualification._environment_audit()
    assert audit["status"] == "BLOCKED"
    assert audit["blocker_code"] == "BLOCKED_OFFLINE_CLOSURE_NOT_MATERIALIZED"


def test_g019_pass_only_unlocks_qualification_eligibility():
    decision = phase0_qualification.build_phase0_qualification(WORKSPACE)["decision"]
    assert decision == {
        "phase0_qualified": True,
        "authorization_eligible": True,
        "execution_authorized": False,
        "authorization_artifact_created": False,
    }


def test_g019_environment_identity_is_stable_across_relocation():
    manifest = json.loads(
        (OUTPUT / "runtime-manifest.json").read_text(encoding="utf-8")
    )
    relocated = copy.deepcopy(manifest)
    relocated["materialization"]["workspace_root"] = "E:/relocated/workspace"
    relocated["materialization"]["runtime_root"] = "E:/relocated/runtime"
    relocated["materialization"]["clean_python_root"] = "E:/relocated/python"
    assert (
        phase0_frozen_runtime._sha(
            phase0_frozen_runtime.canonical_bytes(
                phase0_frozen_runtime._identity_payload(relocated)
            )
        )
        == manifest["environment_id"]
    )


def test_g019_bytecode_is_never_silently_excluded(tmp_path):
    bytecode = tmp_path / "pkg/__pycache__/module.cpython-311.pyc"
    bytecode.parent.mkdir(parents=True)
    bytecode.write_bytes(b"forbidden")
    assert any(
        item["path"].endswith(".pyc")
        for item in phase0_frozen_runtime._relative_files(tmp_path)
    )
    with pytest.raises(ValueError, match="BYTECODE_PRESENT"):
        phase0_frozen_runtime._assert_zero_bytecode(tmp_path)


def test_g019_resigned_junit_failure_cannot_claim_pass(tmp_path):
    runtime = OUTPUT / "runtime"
    report = tmp_path / "reports/property.xml"
    report.parent.mkdir(parents=True)
    shutil.copy2(OUTPUT / "reports/property.xml", report)
    tree = ET.parse(report)
    suite = tree.getroot()
    if suite.tag != "testsuite":
        suite = suite.find("testsuite")
    case = suite.find("testcase")
    ET.SubElement(case, "failure", message="forged machine failure")
    suite.set("failures", "1")
    tree.write(report, encoding="utf-8", xml_declaration=True)
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "property.stdout").write_bytes(b"")
    (raw / "property.stderr").write_bytes(b"")
    original = json.loads(
        (OUTPUT / "receipts/property.json").read_text(encoding="utf-8")
    )
    forged = copy.deepcopy(original)
    arguments, _ = phase0_frozen_runtime._receipt_specs(tmp_path)["property"]
    forged.update(
        {
            "argv": phase0_frozen_runtime._sealed_argv(runtime, *arguments),
            "stdout_sha256": phase0_frozen_runtime._file_sha(raw / "property.stdout"),
            "stderr_sha256": phase0_frozen_runtime._file_sha(raw / "property.stderr"),
            "report_sha256": phase0_frozen_runtime._file_sha(report),
            "status": "PASS",
        }
    )
    body = {key: value for key, value in forged.items() if key != "receipt_self_sha256"}
    forged["receipt_self_sha256"] = phase0_frozen_runtime._sha(
        phase0_frozen_runtime.canonical_bytes(body)
    )
    with pytest.raises(ValueError, match="DERIVED_SUMMARY|STATUS_NOT_DERIVED"):
        phase0_frozen_runtime._validate_receipt_evidence(forged, runtime, tmp_path)


def test_g019_cross_contract_receipt_reuse_is_rejected():
    receipt = json.loads((OUTPUT / "receipts/unit.json").read_text(encoding="utf-8"))
    forged = copy.deepcopy(receipt)
    forged["receipt_derivation_contract_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="DERIVATION_CONTRACT_MISMATCH"):
        phase0_frozen_runtime._validate_receipt_evidence(
            forged, OUTPUT / "runtime", OUTPUT
        )


@pytest.mark.parametrize("forged_pids", [(-1001, -1002), (-1001, 1002)])
def test_g019_resigned_fake_repro_pids_cannot_claim_pass(tmp_path, forged_pids):
    runtime = OUTPUT / "runtime"
    document = json.loads(
        (OUTPUT / "reports/reproducibility.json").read_text(encoding="utf-8")
    )
    forged_document = copy.deepcopy(document)
    for run, pid in zip(forged_document["runs"], forged_pids, strict=True):
        run["pid"] = pid
    forged_document["status"] = "PASS"
    report = tmp_path / "reports/reproducibility.json"
    report.parent.mkdir(parents=True)
    report_raw = phase0_frozen_runtime.canonical_bytes(forged_document) + b"\n"
    report.write_bytes(report_raw)
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "reproducibility.stdout").write_bytes(report_raw)
    (raw / "reproducibility.stderr").write_bytes(b"")
    receipt = json.loads(
        (OUTPUT / "receipts/reproducibility.json").read_text(encoding="utf-8")
    )
    forged = copy.deepcopy(receipt)
    arguments, _ = phase0_frozen_runtime._receipt_specs(tmp_path)["reproducibility"]
    forged.update(
        {
            "argv": phase0_frozen_runtime._sealed_argv(runtime, *arguments),
            "stdout_sha256": phase0_frozen_runtime._file_sha(
                raw / "reproducibility.stdout"
            ),
            "stderr_sha256": phase0_frozen_runtime._file_sha(
                raw / "reproducibility.stderr"
            ),
            "report_sha256": phase0_frozen_runtime._file_sha(report),
            "derived_summary_sha256": phase0_frozen_runtime._sha(
                phase0_frozen_runtime.canonical_bytes(forged_document)
            ),
            "status": "PASS",
        }
    )
    body = {key: value for key, value in forged.items() if key != "receipt_self_sha256"}
    forged["receipt_self_sha256"] = phase0_frozen_runtime._sha(
        phase0_frozen_runtime.canonical_bytes(body)
    )
    with pytest.raises(ValueError, match="JSON_MACHINE_REPORT_STATUS_NOT_DERIVED"):
        phase0_frozen_runtime._validate_receipt_evidence(forged, runtime, tmp_path)


def test_g019_strict_reopen_actively_reruns_reproducibility(monkeypatch):
    persisted = json.loads(
        (OUTPUT / "reports/reproducibility.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (OUTPUT / "runtime-manifest.json").read_text(encoding="utf-8")
    )
    calls = []

    def forged_active(runtime, output):
        calls.append((runtime, output))
        result = copy.deepcopy(persisted)
        result["runs"][0]["output_sha256"] = "0" * 64
        return result

    monkeypatch.setattr(phase0_frozen_runtime, "_repro_semantics", forged_active)
    with pytest.raises(ValueError, match="ACTIVE_REPRO_VALIDATION_FAILED"):
        phase0_frozen_runtime._validate_active_reproducibility(
            persisted,
            OUTPUT / "runtime",
            OUTPUT,
            manifest["runtime_files"],
        )
    assert len(calls) == 1
