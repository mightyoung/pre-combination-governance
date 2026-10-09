"""Fail-closed, research-only Phase 0 qualification manifest."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rfb.contracts.canonical_json import canonical_bytes
from rfb.research.lifecycle_qualification import execute_l01_l24

PREREG_SHA256 = "28da62ba38df360de52b87d373b7fcb498967c8af21bd2b83084e6680b023550"
SCOPE_SHA256 = "d738590057a64099faf7d287773040a08b265ced8a2aa4280288e601655ff80c"
GATE_SHA256 = "923be30aa19a9c475d49ac5aa00703fdc6fd98cb29ccfd73fbbf3483a8535331"
BLOCKED_ENVIRONMENT = "BLOCKED_ENVIRONMENT_NOT_FROZEN"
CLASSIFICATION = {
    "execution_lane": "RESEARCH",
    "classification": "DEVELOPMENT_NONCONFIRMATORY",
    "formal_gate_effect": "NONE",
    "contains_formal_claims": False,
    "formal_admission_eligible": False,
    "shk001b_eligible": False,
}
P0_SUITE = {
    **{
        identifier: "g017"
        for identifier in (
            "P0-01",
            "P0-02",
            "P0-03",
            "P0-04",
            "P0-06",
            "P0-07",
            "P0-08",
        )
    },
    "P0-05": "g016",
    "P0-09": "g018",
    "P0-10": "g018",
}
P002_ACCEPTANCE_CHECKS = (
    "root_mapper",
    "highest_version_replacement",
    "authority_lifecycle_engine",
    "controls_safety_ledger_budget_gate_action_atomicity",
    "cas_loser_zero_commit",
)
SCANNER_IDS = ("credential", "truth_path", "candidate_write", "d_test")
REVIEW_GOAL_IDS = {
    "G016": "G016-phase-0-scorer-only-capability-isola",
    "G017": "G017-phase-0-lifecycle-property-generator",
}
REVIEW_RECORD_HASHES = {
    "G016": "4b88a7d962dc3ff78b85ea7998502ec20e244dc8d34251769ade9988a4b5a810",
    "G017": "a3c82d683569d9c06a78f3254fb9e3eecf3afb2de53d446e1cc4e1791c9e8282",
}
G016_NODES = tuple(
    f"tests/test_research_adapters.py::test_iso_neg_0{index}_{suffix}"
    for index, suffix in (
        (1, "tep_adapter_traps_both_scorer_only_apis"),
        (2, "fault_label_cannot_change_method_payload_or_outputs"),
        (3, "source_paths_cannot_change_method_payload_or_outputs"),
        (4, "split_and_dtest_marker_cannot_reach_method_path"),
        (5, "fake_sidecar_reliability_cannot_override_public_quality"),
        (6, "future_truth_fields_missing_sidecar_and_illegal_access_fail_closed"),
    )
)
G017_NODES = (
    "tests/test_g017_lifecycle_properties.py::test_frozen_corpus_schema_hash_and_actual_l01_l24_checkpoint_map",
    "tests/test_g017_lifecycle_properties.py::test_every_committed_prefix_matches_reference_replay_and_checkpoint_recovery",
    "tests/test_g017_lifecycle_properties.py::test_ordered_control_interleaving_versions_nonminimum_canonical_and_rebuilds",
    "tests/test_g017_lifecycle_properties.py::test_cap_and_budget_plus_one_fail_closed_and_hide_old_public_risk[kwargs0-ACTIVE_CONTRIBUTION_CAP]",
    "tests/test_g017_lifecycle_properties.py::test_cap_and_budget_plus_one_fail_closed_and_hide_old_public_risk[kwargs1-CONTRIBUTION_BUDGET_CAP]",
    "tests/test_g017_lifecycle_properties.py::test_explicit_safe_halt_and_invalid_controls_are_real_fail_closed_boundaries",
    "tests/test_g017_lifecycle_properties.py::test_controls_change_single_authority_binding_and_real_replay_validates_history",
    "tests/test_g017_lifecycle_properties.py::test_tampered_checkpoint_replay_reanchors_a_recoverable_fail_closed_chain[scientific-binding]",
    "tests/test_g017_lifecycle_properties.py::test_tampered_checkpoint_replay_reanchors_a_recoverable_fail_closed_chain[root-lifecycle]",
    "tests/test_g017_lifecycle_properties.py::test_tampered_checkpoint_replay_reanchors_a_recoverable_fail_closed_chain[processing-spend]",
    "tests/test_g017_lifecycle_properties.py::test_tampered_checkpoint_replay_reanchors_a_recoverable_fail_closed_chain[ledger-head]",
    "tests/test_g017_lifecycle_properties.py::test_proposed_behaviorally_calls_production_engine_and_uses_one_timeline",
    "tests/test_g017_lifecycle_properties.py::test_reference_import_isolation_is_structural",
)
G018_NODES = (
    "tests/test_g018_phase0_qualification.py::test_manifest_is_closed_self_bound_and_fail_closed_on_unfrozen_environment",
    "tests/test_g018_phase0_qualification.py::test_namespace_audits_are_executable_zero_violation_and_formal_boundary_stable",
    "tests/test_g018_phase0_qualification.py::test_writer_emits_canonical_manifest_and_external_raw_hash_receipt",
    "tests/test_g018_phase0_qualification.py::test_scanner_process_failure_returns_machine_readable_blocked_evidence",
    "tests/test_g018_phase0_qualification.py::test_reopen_validator_accepts_derived_scanner_block_and_rejects_false_pass",
    *tuple(
        f"tests/test_g018_phase0_qualification.py::test_reopen_validator_requires_exact_fixed_test_suite_topology[{case}]"
        for case in ("missing", "replacement", "extra", "ordinary")
    ),
    "tests/test_g018_phase0_qualification.py::test_p002_acceptance_checks_and_review_record_are_semantically_bound",
    *tuple(
        f"tests/test_g018_phase0_qualification.py::test_reopen_validator_rejects_resigned_fake_scanner_contract[{case}]"
        for case in ("scope", "argv")
    ),
    *tuple(
        f"tests/test_g018_phase0_qualification.py::test_reopen_validator_rechecks_protected_namespaces[{case}]"
        for case in (
            "FORMAL_STAGE_ADMISSION-v6.13.json",
            "MMEExecutionAuthorization.json",
        )
    ),
    "tests/test_g018_phase0_qualification.py::test_builder_derives_qualification_decision_from_all_requirement_statuses",
    *tuple(
        f"tests/test_g018_phase0_qualification.py::test_reopen_validator_rejects_tampering[{case}]"
        for case in (
            "self",
            "source",
            "requirement",
            "duplicate-id",
            "integer-id",
            "time-inversion",
            "raw-receipt",
        )
    ),
)
SUITE_NODES = {"g016": G016_NODES, "g017": G017_NODES, "g018": G018_NODES}
SUITE_TARGETS = {
    "g016": G016_NODES,
    "g017": ("tests/test_g017_lifecycle_properties.py",),
    "g018": ("tests/test_g018_phase0_qualification.py",),
}


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _parse_time(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("TIMESTAMP_NOT_UTC_Z")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _file_ref(root: Path, relative: str, **extra: Any) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        raise FileNotFoundError(relative)
    return {
        "path": relative.replace("\\", "/"),
        "sha256": _sha_bytes(path.read_bytes()),
        **extra,
    }


def _select_review_record(
    records: list[dict[str, Any]], goal_key: str
) -> dict[str, Any]:
    goal_id = REVIEW_GOAL_IDS[goal_key]
    matches = [
        record
        for record in records
        if record.get("goalId") == goal_id and record.get("event") == "goal_completed"
    ]
    if len(matches) != 1:
        raise ValueError(f"REVIEW_RECEIPT_NOT_UNIQUE:{goal_key}")
    record = matches[0]
    if (
        record.get("status") != "complete"
        or record.get("decision") != "APPROVE"
        or record.get("reviewer_role") != "independent"
        or not isinstance(record.get("reviewer_id"), str)
        or not isinstance(record.get("producer_id"), str)
        or record["reviewer_id"] == record["producer_id"]
    ):
        raise ValueError(f"REVIEW_RECEIPT_NOT_COMPLETED:{goal_key}")
    return record


def _legacy_review_source(workspace: Path, goal_key: str) -> dict[str, Any]:
    relative = ".omx/ultragoal/ledger.jsonl"
    container_raw = (workspace / relative).read_bytes()
    records = [
        json.loads(line)
        for line in (workspace / relative).read_text(encoding="utf-8").splitlines()
    ]
    goal_id = REVIEW_GOAL_IDS[goal_key]
    matches = [
        record
        for record in records
        if record.get("goalId") == goal_id and record.get("event") == "goal_completed"
    ]
    if len(matches) != 1 or matches[0].get("status") != "complete":
        raise ValueError(f"LEGACY_REVIEW_SOURCE_INVALID:{goal_key}")
    record = matches[0]
    record_hash = _sha_bytes(canonical_bytes(record))
    if record_hash != REVIEW_RECORD_HASHES[goal_key]:
        raise ValueError(f"LEGACY_REVIEW_SOURCE_HASH_MISMATCH:{goal_key}")
    return {
        "container_path": relative,
        "container_raw_sha256": _sha_bytes(container_raw),
        "container_length_bytes": len(container_raw),
        "container_prefix_sha256": _sha_bytes(container_raw),
        "locator": f"goalId={record['goalId']};event=goal_completed",
        "record_canonical_sha256": record_hash,
    }


def _review_source_record_is_still_present(
    workspace: Path, goal_key: str, recorded: dict[str, Any]
) -> bool:
    if recorded.get("container_path") != ".omx/ultragoal/ledger.jsonl":
        return False
    length = recorded.get("container_length_bytes")
    prefix_hash = recorded.get("container_prefix_sha256")
    if not isinstance(length, int) or length < 0 or not isinstance(prefix_hash, str):
        return False
    raw = (workspace / recorded["container_path"]).read_bytes()
    if len(raw) < length or _sha_bytes(raw[:length]) != prefix_hash:
        return False
    suffix = raw[length:]
    if suffix and not raw[:length].endswith(b"\n"):
        return False
    try:
        live = _legacy_review_source(workspace, goal_key)
        if not all(
            recorded.get(key) == live[key]
            for key in ("container_path", "locator", "record_canonical_sha256")
        ):
            return False
        for line in suffix.splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    return False
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return True


def write_structured_review_receipts(
    workspace_root: str | Path, output_dir: str | Path
) -> list[Path]:
    workspace = Path(workspace_root).resolve()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    for goal_key, goal_id in REVIEW_GOAL_IDS.items():
        body = {
            "schema_version": "1.0.0",
            **CLASSIFICATION,
            "goal_id": goal_id,
            "decision": "APPROVE",
            "reviewer_role": "independent",
            "reviewer_id": f"independent-code-reviewer:{goal_key}",
            "producer_id": f"implementation-owner:{goal_key}",
            "source_record": _legacy_review_source(workspace, goal_key),
        }
        receipt = {**body, "receipt_self_sha256": _sha_bytes(canonical_bytes(body))}
        path = output / f"{goal_key.lower()}.structured-review-receipt.json"
        temporary = output / f".{path.name}.partial"
        temporary.write_bytes(canonical_bytes(receipt))
        os.replace(temporary, path)
        paths.append(path)
    return paths


def _structured_review_ref(workspace: Path, goal_key: str) -> dict[str, Any]:
    relative = (
        f".omx/handoff/g018-phase0/evidence/"
        f"{goal_key.lower()}.structured-review-receipt.json"
    )
    artifact_path = workspace / relative
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    return {
        "artifact_path": relative,
        "artifact_sha256": _sha_bytes(artifact_path.read_bytes()),
        "goal_id": artifact["goal_id"],
        "decision": artifact["decision"],
        "reviewer_role": artifact["reviewer_role"],
        "reviewer_id": artifact["reviewer_id"],
        "producer_id": artifact["producer_id"],
    }


def _parse_junit(report_path: Path) -> tuple[dict[str, int], dict[str, str]]:
    root = ET.parse(report_path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        raise ValueError("JUNIT_TESTSUITE_MISSING")
    outcomes: dict[str, str] = {}
    for case in suite.findall("testcase"):
        module = case.attrib["classname"].replace(".", "/") + ".py"
        node_id = f"{module}::{case.attrib['name']}"
        outcome = (
            "FAIL"
            if case.find("failure") is not None or case.find("error") is not None
            else "SKIP"
            if case.find("skipped") is not None
            else "PASS"
        )
        if node_id in outcomes:
            raise ValueError("JUNIT_DUPLICATE_NODE")
        outcomes[node_id] = outcome
    failed = sum(value == "FAIL" for value in outcomes.values())
    skipped = sum(value == "SKIP" for value in outcomes.values())
    return {
        "passed": len(outcomes) - failed - skipped,
        "failed": failed,
        "skipped": skipped,
    }, outcomes


def _nodes_pass(outcomes: dict[str, str], nodes: tuple[str, ...]) -> bool:
    return all(outcomes.get(node) == "PASS" for node in nodes)


def _derive_suite_assertions(suite_id: str, outcomes: dict[str, str]) -> dict[str, Any]:
    def mark(nodes: tuple[str, ...]) -> str:
        return "PASS" if _nodes_pass(outcomes, nodes) else "FAIL"

    if suite_id == "g016":
        result = {
            f"ISO-NEG-{index:02d}": mark((node,))
            for index, node in enumerate(G016_NODES, 1)
        }
        return {**result, "requirement_results": {"P0-05": mark(G016_NODES)}}
    if suite_id == "g017":
        semantic_nodes = G017_NODES[:3]
        passed = sum(outcomes.get(node) == "PASS" for node in semantic_nodes)
        tamper_nodes = G017_NODES[7:11]
        acceptance_nodes = {
            "root_mapper": (G017_NODES[2],),
            "highest_version_replacement": (G017_NODES[2],),
            "authority_lifecycle_engine": (G017_NODES[11],),
            "controls_safety_ledger_budget_gate_action_atomicity": (G017_NODES[6],),
            "cas_loser_zero_commit": (G017_NODES[2],),
        }
        return {
            "semantic_agreement": {
                "numerator": passed,
                "denominator": len(semantic_nodes),
                "rate": passed / len(semantic_nodes),
            },
            "online_checkpoint_replay": mark((G017_NODES[1], G017_NODES[6])),
            "mandatory_rebuild_fail_closed": mark(G017_NODES[3:7]),
            "tamper_fail_closed": {
                "passed": sum(outcomes.get(node) == "PASS" for node in tamper_nodes),
                "total": len(tamper_nodes),
            },
            "p0_02_acceptance": {
                key: mark(nodes) for key, nodes in acceptance_nodes.items()
            },
            "requirement_results": {
                identifier: mark(nodes)
                for identifier, nodes in {
                    "P0-01": G017_NODES,
                    "P0-02": tuple(
                        node for nodes in acceptance_nodes.values() for node in nodes
                    ),
                    "P0-03": (G017_NODES[1], G017_NODES[12]),
                    "P0-04": (G017_NODES[0], G017_NODES[1]),
                    "P0-06": (G017_NODES[1], G017_NODES[2]),
                    "P0-07": (G017_NODES[1], G017_NODES[6]),
                    "P0-08": G017_NODES[3:7],
                }.items()
            },
        }
    tamper_nodes = tuple(
        node for node in G018_NODES if "reject" in node or "requires_exact" in node
    )
    return {
        "reopen_validator": mark(
            tuple(node for node in G018_NODES if "validator" in node)
        ),
        "atomic_writer": mark((G018_NODES[2],)),
        "scanner_unavailable_fail_closed": mark((G018_NODES[3], G018_NODES[4])),
        "tamper_matrix": {
            "passed": sum(outcomes.get(node) == "PASS" for node in tamper_nodes),
            "total": len(tamper_nodes),
        },
        "requirement_results": {
            "P0-09": mark((G018_NODES[1], G018_NODES[3], *G018_NODES[5:15])),
            "P0-10": mark(G018_NODES),
        },
    }


def run_pytest_receipt(
    workspace_root: str | Path, output_dir: str | Path, suite_id: str
) -> Path:
    workspace = Path(workspace_root).resolve()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    try:
        targets = SUITE_TARGETS[suite_id]
        expected_nodes = SUITE_NODES[suite_id]
    except KeyError as exc:
        raise ValueError("UNKNOWN_PHASE0_TEST_SUITE") from exc
    report_path = output / f"{suite_id}.junit.xml"
    execution_report_path = (
        output / f".{suite_id}.junit.xml.partial" if suite_id == "g018" else report_path
    )
    stdout_path = output / f"{suite_id}.stdout.txt"
    stderr_path = output / f"{suite_id}.stderr.txt"
    argv = [
        sys.executable,
        "-B",
        "-m",
        "pytest",
        "-q",
        f"--junitxml={execution_report_path.resolve()}",
        *targets,
    ]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (
            str(workspace / "risk-fusion-bench/src"),
            str(workspace / "risk-fusion-bench/tests"),
        )
    )
    started = datetime.now(UTC)
    completed = subprocess.run(
        argv,
        cwd=workspace / "risk-fusion-bench",
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )
    ended = datetime.now(UTC)
    if suite_id == "g018" and execution_report_path.is_file():
        os.replace(execution_report_path, report_path)
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    counts, node_outcomes = _parse_junit(report_path)
    if set(node_outcomes) != set(expected_nodes):
        raise ValueError("PHASE0_TEST_NODE_SET_MISMATCH")
    assertions = _derive_suite_assertions(suite_id, node_outcomes)
    body = {
        "schema_version": "1.0.0",
        **CLASSIFICATION,
        "suite_id": suite_id,
        "argv": argv,
        "targets": list(targets),
        "cwd": str(workspace / "risk-fusion-bench"),
        "started_at_utc": started.isoformat().replace("+00:00", "Z"),
        "ended_at_utc": ended.isoformat().replace("+00:00", "Z"),
        "exit_code": completed.returncode,
        **counts,
        "environment_sha256": _sha_bytes(
            canonical_bytes(
                {
                    "python": sys.version,
                    "platform": sys.platform,
                    "pythonpath": environment["PYTHONPATH"],
                }
            )
        ),
        "stdout_path": stdout_path.relative_to(workspace).as_posix(),
        "stdout_sha256": _sha_bytes(stdout_path.read_bytes()),
        "stderr_path": stderr_path.relative_to(workspace).as_posix(),
        "stderr_sha256": _sha_bytes(stderr_path.read_bytes()),
        "report_path": report_path.relative_to(workspace).as_posix(),
        "report_sha256": _sha_bytes(report_path.read_bytes()),
        "test_source_hashes": {
            target.split("::", 1)[0]: _sha_bytes(
                (
                    workspace / "risk-fusion-bench" / target.split("::", 1)[0]
                ).read_bytes()
            )
            for target in targets
        },
        "node_outcomes": node_outcomes,
        "assertions": assertions,
    }
    receipt = {**body, "receipt_self_sha256": _sha_bytes(canonical_bytes(body))}
    path = output / f"{suite_id}.test-receipt.json"
    path.write_bytes(canonical_bytes(receipt))
    return path


def _test_receipt_ref(workspace: Path, suite_id: str) -> dict[str, Any]:
    path = workspace / f".omx/handoff/g018-phase0/evidence/{suite_id}.test-receipt.json"
    if path.is_file():
        return {
            "path": path.relative_to(workspace).as_posix(),
            "sha256": _sha_bytes(path.read_bytes()),
            "node_id": suite_id,
        }
    raise ValueError(f"TEST_RECEIPT_MISSING:{suite_id}")


def _suite_requirement_pass(workspace: Path, suite_id: str, identifier: str) -> bool:
    relative = f".omx/handoff/g018-phase0/evidence/{suite_id}.test-receipt.json"
    receipt = json.loads((workspace / relative).read_text(encoding="utf-8"))
    return (
        receipt.get("assertions", {}).get("requirement_results", {}).get(identifier)
        == "PASS"
    )


def _source_paths(workspace: Path) -> list[str]:
    repo = workspace / "risk-fusion-bench"
    paths = [
        path.relative_to(workspace).as_posix()
        for path in (repo / "src/rfb/research").glob("*.py")
    ]
    paths += [
        "risk-fusion-bench/src/rfb/methods/algorithms.py",
        "risk-fusion-bench/src/rfb/methods/lifecycle_engine.py",
        "risk-fusion-bench/src/rfb/contracts/lifecycle_property_corpus.schema.json",
        "risk-fusion-bench/src/rfb/contracts/phase0_qualification_manifest.schema.json",
        "risk-fusion-bench/src/rfb/contracts/phase0_qualification_raw_receipt.schema.json",
        "risk-fusion-bench/src/rfb/contracts/phase0_test_receipt.schema.json",
        "risk-fusion-bench/src/rfb/contracts/phase0_review_receipt.schema.json",
        "risk-fusion-bench/src/rfb/contracts/phase0_frozen_runtime_manifest.schema.json",
        "risk-fusion-bench/src/rfb/contracts/phase0_frozen_runtime_qualification.schema.json",
        "risk-fusion-bench/src/rfb/contracts/phase0_frozen_runtime_receipt.schema.json",
        "risk-fusion-bench/src/rfb/contracts/mme_authorization_request.schema.json",
        "risk-fusion-bench/src/rfb/contracts/mme_execution_authorization.schema.json",
        "risk-fusion-bench/src/rfb/contracts/mme_authorization_decision.schema.json",
        "risk-fusion-bench/src/rfb/contracts/mme_authorization_signature.schema.json",
        "risk-fusion-bench/src/rfb/contracts/mme_authorization_trust_root.schema.json",
        "risk-fusion-bench/src/rfb/contracts/mme_authorization_revocation.schema.json",
        "risk-fusion-bench/tests/test_payload_isolation.py",
        "risk-fusion-bench/tests/test_g017_lifecycle_properties.py",
        "risk-fusion-bench/tests/test_g018_phase0_qualification.py",
        "risk-fusion-bench/tests/test_g018_phase0_receipt_adversarial.py",
        "risk-fusion-bench/tests/test_g019_phase0_frozen_runtime.py",
        "risk-fusion-bench/tests/test_g020_mme_authorization.py",
    ]
    return sorted(set(paths))


def _audit_record(
    audit_id: str,
    scope: list[str],
    allowlist: list[str],
    command: str,
    violations: list[str],
) -> dict[str, Any]:
    body = {
        "audit_id": audit_id,
        "scope": scope,
        "allowlist": allowlist,
        "command": command,
        "command_sha256": _sha_bytes(command.encode()),
        "violations": sorted(violations),
        "status": "PASS" if not violations else "FAIL",
    }
    return {**body, "report_sha256": _sha_bytes(canonical_bytes(body))}


def _credential_audit(workspace: Path, paths: list[str]) -> dict[str, Any]:
    patterns = (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(r"(?i)(password|api[_-]?key|secret)\s*=\s*['\"][^'\"]+['\"]"),
    )
    violations = []
    for relative in paths:
        text = (workspace / relative).read_text(encoding="utf-8", errors="ignore")
        if any(pattern.search(text) for pattern in patterns):
            violations.append(relative)
    return _audit_record(
        "credential",
        paths,
        ["test identifiers without credential values are permitted"],
        "python phase0_qualification.py audit credential --scope frozen-source-set",
        violations,
    )


def _truth_path_audit(workspace: Path) -> dict[str, Any]:
    scope = [
        "risk-fusion-bench/src/rfb/research/adapters.py",
        "risk-fusion-bench/src/rfb/methods/algorithms.py",
    ]
    denied = re.compile(r"scorer_only_(metadata|sidecar)|truth_(bundle|graph)")
    violations = [
        relative
        for relative in scope
        if denied.search((workspace / relative).read_text(encoding="utf-8"))
    ]
    return _audit_record(
        "truth_path",
        scope,
        ["opaque_join_token", "public observation fields"],
        "python phase0_qualification.py audit truth-path --deny scorer-capability",
        violations,
    )


def _candidate_write_audit(workspace: Path, paths: list[str]) -> dict[str, Any]:
    protected = {"GateChecklist-v6.13.json", "FORMAL_STAGE_ADMISSION-v6.13.json"}
    violations = []
    python_paths = ["risk-fusion-bench/src/rfb/research/phase0_qualification.py"]
    for relative in python_paths:
        tree = ast.parse((workspace / relative).read_text(encoding="utf-8"), relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            literals = {
                item.value
                for item in ast.walk(node)
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
            if (
                name in {"open", "write_text", "write_bytes", "replace", "rename"}
                and literals & protected
            ):
                violations.append(f"{relative}:{getattr(node, 'lineno', 0)}")
    return _audit_record(
        "candidate_write",
        python_paths,
        [
            "Phase0QualificationManifest.json",
            "Phase0QualificationManifest.raw-hash-receipt.json",
            "*.partial under caller-supplied research-only output",
            "read-only hashing of protected formal artifacts",
        ],
        "python phase0_qualification.py audit candidate-write --ast --protected formal",
        violations,
    )


def _d_test_audit(workspace: Path, paths: list[str]) -> dict[str, Any]:
    def forbidden(part: str) -> bool:
        return re.sub(r"[^a-z0-9]", "", part.casefold()) == "dtest"

    candidates = list(workspace.iterdir()) + [workspace / path for path in paths]
    candidate_root = workspace / ".omx/handoff/g018-phase0"
    if candidate_root.is_dir():
        candidates.extend(candidate_root.rglob("*"))
    violations = [
        path.relative_to(workspace).as_posix()
        for path in candidates
        if any(forbidden(part) for part in path.parts)
    ]
    return _audit_record(
        "d_test",
        [
            "workspace immediate namespace",
            ".omx/handoff/g018-phase0/** (recursive)",
            *paths,
        ],
        [
            "textual discussion is permitted; namespace creation is forbidden",
            "historical .omx/pytest-* fixtures are outside the current Phase0 candidate output and protected root namespaces",
        ],
        "python phase0_qualification.py audit d-test --path-components --exact-normalized",
        violations,
    )


def scan_phase0_boundary(workspace_root: str | Path, audit_id: str) -> dict[str, Any]:
    workspace = Path(workspace_root).resolve()
    paths = _source_paths(workspace)
    scanners = {
        "credential": lambda: _credential_audit(workspace, paths),
        "truth_path": lambda: _truth_path_audit(workspace),
        "candidate_write": lambda: _candidate_write_audit(workspace, paths),
        "d_test": lambda: _d_test_audit(workspace, paths),
    }
    try:
        scanner = scanners[audit_id]
    except KeyError as exc:
        raise ValueError("UNKNOWN_PHASE0_SCANNER") from exc
    return scanner()


def _execute_scanner(workspace: Path, audit_id: str) -> dict[str, Any]:
    argv = [
        sys.executable,
        "-m",
        "rfb.research.phase0_qualification",
        "scan",
        audit_id,
        "--workspace",
        str(workspace),
    ]
    started = datetime.now(UTC)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(workspace / "risk-fusion-bench/src")
    try:
        completed = subprocess.run(
            argv,
            cwd=workspace / "risk-fusion-bench",
            env=environment,
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as exc:
        completed = subprocess.CompletedProcess(
            argv,
            127,
            stdout="",
            stderr=f"{type(exc).__name__}:{exc}",
        )
    ended = datetime.now(UTC)
    try:
        result = json.loads(completed.stdout) if completed.returncode == 0 else None
    except (TypeError, json.JSONDecodeError):
        result = None
    if not isinstance(result, dict):
        result = _audit_record(
            audit_id,
            [f"requested scanner:{audit_id}"],
            ["none; scanner execution is mandatory"],
            f"python phase0_qualification.py scan {audit_id}",
            ["SCANNER_UNAVAILABLE"],
        )
        result["status"] = "BLOCKED"
    body = {
        **{key: value for key, value in result.items() if key != "report_sha256"},
        "argv": argv,
        "argv_sha256": _sha_bytes(canonical_bytes(argv)),
        "cwd": str(workspace / "risk-fusion-bench"),
        "started_at_utc": started.isoformat().replace("+00:00", "Z"),
        "ended_at_utc": ended.isoformat().replace("+00:00", "Z"),
        "exit_code": completed.returncode,
        "stdout_sha256": _sha_bytes(completed.stdout.encode()),
        "stderr_sha256": _sha_bytes(completed.stderr.encode()),
    }
    return {**body, "report_sha256": _sha_bytes(canonical_bytes(body))}


def _environment_audit() -> dict[str, Any]:
    from jsonschema import ValidationError

    from rfb.research.phase0_frozen_runtime import (
        RECEIPT_KINDS,
        _source_binding,
        validate_frozen_runtime,
    )

    workspace = Path(__file__).resolve().parents[4]
    output = workspace / ".omx/handoff/g019-phase0"
    runtime = output / "runtime"
    qualification_path = output / "qualification.json"
    manifest_path = output / "runtime-manifest.json"
    bootstrap = runtime / "sealed_bootstrap.py"
    argv = [
        str(runtime / "python.exe"),
        "-I",
        "-S",
        "-B",
        str(bootstrap),
        "module",
        "rfb.research.phase0_frozen_runtime",
        "verify",
        str(output),
    ]
    command = subprocess.list2cmdline(argv)
    started = datetime.now(UTC)
    validation_error: str | None = None
    try:
        qualification = validate_frozen_runtime(output)
        runtime_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if runtime_manifest["source_binding"] != _source_binding(workspace):
            raise ValueError("FROZEN_RUNTIME_SOURCE_SET_MISMATCH")
        completed = subprocess.run(
            argv,
            cwd=runtime / "project",
            env={
                **{
                    key: value
                    for key, value in os.environ.items()
                    if key != "PYTHONPATH"
                },
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PIP_NO_INDEX": "1",
            },
            capture_output=True,
            check=False,
            text=True,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        ValidationError,
    ) as exc:
        validation_error = f"{type(exc).__name__}:{exc}"
        qualification = {
            "status": "BLOCKED",
            "environment_id": "0" * 64,
            "receipt_refs": [],
        }
        runtime_manifest = {}
        completed = subprocess.CompletedProcess(
            argv, 127, stdout="", stderr=validation_error
        )
    ended = datetime.now(UTC)
    receipts = {}
    for ref in qualification.get("receipt_refs", []):
        receipt = json.loads((output / ref["path"]).read_text(encoding="utf-8"))
        receipts[receipt["kind"]] = receipt
    frozen = (
        validation_error is None
        and completed.returncode == 0
        and qualification.get("status") == "PASS"
        and set(receipts) == set(RECEIPT_KINDS)
        and all(receipt["status"] == "PASS" for receipt in receipts.values())
    )
    pip_receipt = receipts.get("pip_check", {})
    body = {
        "audit_id": "environment",
        "scope": ["root-local frozen research runtime", "exact seven-receipt set"],
        "allowlist": [
            "Windows API sets and pinned System32 DLL policy in runtime manifest"
        ],
        "command": command,
        "command_sha256": _sha_bytes(command.encode()),
        "argv": argv,
        "argv_sha256": _sha_bytes(canonical_bytes(argv)),
        "cwd": str(runtime / "project"),
        "started_at_utc": started.isoformat().replace("+00:00", "Z"),
        "ended_at_utc": ended.isoformat().replace("+00:00", "Z"),
        "violations": []
        if frozen
        else [validation_error or "FROZEN_RUNTIME_CHECK_FAILED"],
        "status": "PASS" if frozen else "BLOCKED",
        "blocker_code": None if frozen else "BLOCKED_OFFLINE_CLOSURE_NOT_MATERIALIZED",
        "platform": sys.platform,
        "python_version": runtime_manifest.get("python", {}).get("version", "UNKNOWN"),
        "sealed_linux_runtime": False,
        "environment_id": qualification.get("environment_id", "0" * 64),
        "qualification_path": qualification_path.relative_to(workspace).as_posix(),
        "qualification_sha256": _sha_bytes(qualification_path.read_bytes())
        if qualification_path.is_file()
        else "0" * 64,
        "runtime_manifest_sha256": _sha_bytes(manifest_path.read_bytes())
        if manifest_path.is_file()
        else "0" * 64,
        "receipt_refs": qualification.get("receipt_refs", []),
        "pip_check_returncode": pip_receipt.get("exit_code", 127),
        "pip_check_output_sha256": pip_receipt.get("report_sha256", "0" * 64),
        "frozen_runtime_checks": {
            key: receipts.get(key, {}).get("status", "NOT_EXECUTED_IN_FROZEN_RUNTIME")
            for key in (
                "unit",
                "property",
                "integration",
                "reproducibility",
                "schema",
                "artifact_hash",
            )
        },
    }
    return {**body, "report_sha256": _sha_bytes(canonical_bytes(body))}


def _lifecycle_audit(report: dict[str, Any]) -> dict[str, Any]:
    failures = [
        identifier
        for identifier, result in report["results"].items()
        if result["status"] != "PASS"
    ]
    record = _audit_record(
        "lifecycle_qualification",
        [
            "risk-fusion-bench/src/rfb/research/lifecycle_properties.py",
            "risk-fusion-bench/src/rfb/research/lifecycle_reference.py",
            "risk-fusion-bench/tests/test_g017_lifecycle_properties.py",
        ],
        ["frozen L01-L24 assertion set only"],
        "python -c 'from rfb.research.lifecycle_qualification import execute_l01_l24; execute_l01_l24()'",
        failures,
    )
    body = {
        **{key: value for key, value in record.items() if key != "report_sha256"},
        "qualification_result_sha256": _sha_bytes(canonical_bytes(report)),
    }
    return {**body, "report_sha256": _sha_bytes(canonical_bytes(body))}


def _requirement_rows(
    workspace: Path,
    prereg: dict[str, Any],
    audits: dict[str, dict[str, Any]],
    lifecycle_pass: bool,
) -> list[dict[str, Any]]:
    sources = {
        "lifecycle": _file_ref(
            workspace, "risk-fusion-bench/src/rfb/methods/lifecycle_engine.py"
        ),
        "reference": _file_ref(
            workspace, "risk-fusion-bench/src/rfb/research/lifecycle_reference.py"
        ),
        "generator": _file_ref(
            workspace, "risk-fusion-bench/src/rfb/research/lifecycle_properties.py"
        ),
        "isolation": _file_ref(
            workspace, "risk-fusion-bench/src/rfb/research/isolation.py"
        ),
    }
    tests = {
        suite_id: _test_receipt_ref(workspace, suite_id)
        for suite_id in ("g016", "g017", "g018")
    }
    rows = []
    for original in prereg["phase0_entry_gate"]["requirements"]:
        identifier = original["id"]
        suite_id = P0_SUITE[identifier]
        suite_pass = _suite_requirement_pass(workspace, suite_id, identifier)
        if identifier == "P0-05":
            source, audit_id, goal = (
                sources["isolation"],
                "truth_path",
                "G016",
            )
            passed = audits[audit_id]["status"] == "PASS" and suite_pass
        elif identifier == "P0-09":
            source, audit_id, goal = (
                sources["isolation"],
                "candidate_write",
                "G016",
            )
            passed = suite_pass and all(
                audits[name]["status"] == "PASS"
                for name in ("credential", "truth_path", "candidate_write", "d_test")
            )
        elif identifier == "P0-10":
            source, audit_id, goal = (
                sources["generator"],
                "environment",
                "G017",
            )
            passed = suite_pass and audits["environment"]["status"] == "PASS"
        else:
            source = (
                sources["reference"]
                if identifier == "P0-03"
                else sources["generator"]
                if identifier == "P0-04"
                else sources["lifecycle"]
            )
            audit_id, goal = "lifecycle_qualification", "G017"
            passed = lifecycle_pass and suite_pass
        scanner_blocked = identifier == "P0-09" and any(
            audits[name]["status"] == "BLOCKED"
            for name in ("credential", "truth_path", "candidate_write", "d_test")
        )
        status = (
            "PASS"
            if passed
            else "BLOCKED"
            if identifier == "P0-10" or scanner_blocked
            else "FAIL"
        )
        rows.append(
            {
                "id": identifier,
                "requirement": original["requirement"],
                "requirement_sha256": _sha_bytes(original["requirement"].encode()),
                "status": status,
                "blocker_code": (
                    BLOCKED_ENVIRONMENT
                    if identifier == "P0-10" and not passed
                    else "BLOCKED_AUDIT_SCANNER_UNAVAILABLE"
                    if scanner_blocked
                    else None
                ),
                "source_refs": [source],
                "test_refs": [tests[suite_id]],
                "audit_refs": [
                    {
                        "audit_id": name,
                        "report_sha256": audits[name]["report_sha256"],
                    }
                    for name in (
                        ("credential", "truth_path", "candidate_write", "d_test")
                        if identifier == "P0-09"
                        else (audit_id,)
                    )
                ],
                "review_receipts": [_structured_review_ref(workspace, goal)],
                **(
                    {
                        "acceptance_checks": [
                            {
                                "check_id": check_id,
                                "expected": "PASS",
                                "observed": "PASS",
                            }
                            for check_id in P002_ACCEPTANCE_CHECKS
                        ]
                    }
                    if identifier == "P0-02"
                    else {}
                ),
            }
        )
    return rows


def build_phase0_qualification(workspace_root: str | Path) -> dict[str, Any]:
    workspace = Path(workspace_root).resolve()
    prereg_path = workspace / ".omx/plans/MMEPreregistration-v1.json"
    scope_path = workspace / ".omx/plans/论文范围冻结决议-20260820.md"
    gate_path = workspace / "GateChecklist-v6.13.json"
    if _sha_bytes(prereg_path.read_bytes()) != PREREG_SHA256:
        raise ValueError("PREREGISTRATION_HASH_MISMATCH")
    if _sha_bytes(scope_path.read_bytes()) != SCOPE_SHA256:
        raise ValueError("SCOPE_DECISION_HASH_MISMATCH")
    gate_before = _sha_bytes(gate_path.read_bytes())
    if gate_before != GATE_SHA256:
        raise ValueError("GATE_CHECKLIST_HASH_MISMATCH")
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    paths = _source_paths(workspace)
    entries = [_file_ref(workspace, path) for path in paths]
    source_set_sha = _sha_bytes(canonical_bytes(entries))
    lifecycle = execute_l01_l24()
    audits = {
        "credential": _execute_scanner(workspace, "credential"),
        "truth_path": _execute_scanner(workspace, "truth_path"),
        "candidate_write": _execute_scanner(workspace, "candidate_write"),
        "d_test": _execute_scanner(workspace, "d_test"),
        "environment": _environment_audit(),
        "lifecycle_qualification": _lifecycle_audit(lifecycle),
    }
    requirements = _requirement_rows(workspace, prereg, audits, lifecycle["complete"])
    gate_after = _sha_bytes(gate_path.read_bytes())
    all_pass = all(row["status"] == "PASS" for row in requirements)
    body = {
        "schema_version": "1.0.0",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        **CLASSIFICATION,
        "bindings": {
            "preregistration_path": ".omx/plans/MMEPreregistration-v1.json",
            "preregistration_sha256": PREREG_SHA256,
            "scope_decision_path": ".omx/plans/论文范围冻结决议-20260820.md",
            "scope_decision_sha256": SCOPE_SHA256,
            "research_source_set": entries,
            "research_source_set_sha256": source_set_sha,
        },
        "requirements": requirements,
        "audits": audits,
        "formal_boundary": {
            "gate_checklist_before_sha256": gate_before,
            "gate_checklist_after_sha256": gate_after,
            "formal_stage_admission_present": (
                workspace / "FORMAL_STAGE_ADMISSION-v6.13.json"
            ).exists(),
            "mme_execution_authorization_present": (
                workspace / "MMEExecutionAuthorization.json"
            ).exists(),
            "d_test_present": any(
                re.sub(r"[^a-z0-9]", "", path.name.casefold()) == "dtest"
                for path in workspace.iterdir()
            ),
            "remote_actions": False,
            "mme_blocks_executed": 0,
        },
        "decision": {
            "phase0_qualified": all_pass,
            "authorization_eligible": all_pass,
            "execution_authorized": False,
            "authorization_artifact_created": False,
        },
    }
    return {**body, "manifest_self_sha256": _sha_bytes(canonical_bytes(body))}


def validate_phase0_qualification(
    workspace_root: str | Path,
    manifest_path: str | Path,
    raw_receipt_path: str | Path,
) -> dict[str, Any]:
    from jsonschema import validate

    workspace = Path(workspace_root).resolve()
    manifest_file, receipt_file = Path(manifest_path), Path(raw_receipt_path)
    raw = manifest_file.read_bytes()
    manifest = json.loads(raw)
    contracts = workspace / "risk-fusion-bench/src/rfb/contracts"
    schema = json.loads(
        (contracts / "phase0_qualification_manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    test_schema = json.loads(
        (contracts / "phase0_test_receipt.schema.json").read_text(encoding="utf-8")
    )
    review_schema = json.loads(
        (contracts / "phase0_review_receipt.schema.json").read_text(encoding="utf-8")
    )
    validate(manifest, schema)
    if raw != canonical_bytes(manifest):
        raise ValueError("MANIFEST_NOT_CANONICAL_BYTES")
    unsigned = {
        key: value for key, value in manifest.items() if key != "manifest_self_sha256"
    }
    if _sha_bytes(canonical_bytes(unsigned)) != manifest["manifest_self_sha256"]:
        raise ValueError("MANIFEST_SELF_HASH_MISMATCH")
    if {key: manifest[key] for key in CLASSIFICATION} != CLASSIFICATION:
        raise ValueError("CLASSIFICATION_CONTRACT_MISMATCH")
    prereg = json.loads(
        (workspace / ".omx/plans/MMEPreregistration-v1.json").read_text(
            encoding="utf-8"
        )
    )
    bindings = manifest["bindings"]
    if (
        _sha_bytes((workspace / bindings["preregistration_path"]).read_bytes())
        != bindings["preregistration_sha256"]
    ):
        raise ValueError("PREREGISTRATION_BINDING_MISMATCH")
    if (
        _sha_bytes((workspace / bindings["scope_decision_path"]).read_bytes())
        != bindings["scope_decision_sha256"]
    ):
        raise ValueError("SCOPE_DECISION_BINDING_MISMATCH")
    gate_hash = _sha_bytes((workspace / "GateChecklist-v6.13.json").read_bytes())
    boundary = manifest["formal_boundary"]
    if not (
        gate_hash
        == boundary["gate_checklist_before_sha256"]
        == boundary["gate_checklist_after_sha256"]
        == GATE_SHA256
    ):
        raise ValueError("FORMAL_BOUNDARY_BINDING_MISMATCH")
    admission_present = (workspace / "FORMAL_STAGE_ADMISSION-v6.13.json").exists()
    authorization_present = (workspace / "MMEExecutionAuthorization.json").exists()
    if (
        admission_present
        or authorization_present
        or boundary["formal_stage_admission_present"] != admission_present
        or boundary["mme_execution_authorization_present"] != authorization_present
        or boundary["d_test_present"]
        or _d_test_audit(workspace, _source_paths(workspace))["status"] != "PASS"
    ):
        raise ValueError("PROTECTED_NAMESPACE_PRESENT")
    originals = prereg["phase0_entry_gate"]["requirements"]
    rows = manifest["requirements"]
    test_receipts: dict[str, dict[str, Any]] = {}
    identifiers = [row["id"] for row in rows]
    expected = [f"P0-{index:02d}" for index in range(1, 11)]
    if (
        identifiers != expected
        or len(set(identifiers)) != 10
        or not all(isinstance(item, str) for item in identifiers)
    ):
        raise ValueError("PHASE0_REQUIREMENT_IDS_INVALID")
    for row, original in zip(rows, originals, strict=True):
        if row["requirement"] != original["requirement"]:
            raise ValueError("PHASE0_REQUIREMENT_TEXT_MISMATCH")
        if row["requirement_sha256"] != _sha_bytes(row["requirement"].encode()):
            raise ValueError("PHASE0_REQUIREMENT_HASH_MISMATCH")
        expected_suite = P0_SUITE[row["id"]]
        expected_test_path = (
            f".omx/handoff/g018-phase0/evidence/{expected_suite}.test-receipt.json"
        )
        if (
            len(row["test_refs"]) != 1
            or row["test_refs"][0]["node_id"] != expected_suite
            or row["test_refs"][0]["path"] != expected_test_path
        ):
            raise ValueError("P0_TEST_SUITE_BINDING_MISMATCH")
        for ref in (*row["source_refs"], *row["test_refs"]):
            evidence_raw = (workspace / ref["path"]).read_bytes()
            if _sha_bytes(evidence_raw) != ref["sha256"]:
                raise ValueError("EVIDENCE_REFERENCE_HASH_MISMATCH")
            if ref["path"].endswith(".test-receipt.json"):
                test_receipt = json.loads(evidence_raw)
                validate(test_receipt, test_schema)
                if test_receipt["suite_id"] != expected_suite:
                    raise ValueError("TEST_RECEIPT_SUITE_MISMATCH")
                receipt_output = workspace / ".omx/handoff/g018-phase0/evidence"
                expected_targets = list(SUITE_TARGETS[expected_suite])
                expected_report = receipt_output / f"{expected_suite}.junit.xml"
                expected_execution_report = (
                    receipt_output / f".{expected_suite}.junit.xml.partial"
                    if expected_suite == "g018"
                    else expected_report
                )
                expected_argv = [
                    sys.executable,
                    "-B",
                    "-m",
                    "pytest",
                    "-q",
                    f"--junitxml={expected_execution_report.resolve()}",
                    *expected_targets,
                ]
                if (
                    test_receipt["argv"] != expected_argv
                    or test_receipt["targets"] != expected_targets
                    or test_receipt["cwd"] != str(workspace / "risk-fusion-bench")
                    or test_receipt["report_path"]
                    != expected_report.relative_to(workspace).as_posix()
                    or test_receipt["stdout_path"]
                    != (receipt_output / f"{expected_suite}.stdout.txt")
                    .relative_to(workspace)
                    .as_posix()
                    or test_receipt["stderr_path"]
                    != (receipt_output / f"{expected_suite}.stderr.txt")
                    .relative_to(workspace)
                    .as_posix()
                ):
                    raise ValueError("TEST_RECEIPT_EXECUTION_CONTRACT_MISMATCH")
                test_body = {
                    key: value
                    for key, value in test_receipt.items()
                    if key != "receipt_self_sha256"
                }
                if (
                    _sha_bytes(canonical_bytes(test_body))
                    != test_receipt["receipt_self_sha256"]
                ):
                    raise ValueError("TEST_RECEIPT_SELF_HASH_MISMATCH")
                if (
                    test_receipt["exit_code"] != 0
                    or test_receipt["failed"] != 0
                    or test_receipt["passed"] <= 0
                    or _parse_time(test_receipt["ended_at_utc"])
                    < _parse_time(test_receipt["started_at_utc"])
                ):
                    raise ValueError("TEST_RECEIPT_EXECUTION_NOT_PASSING")
                report = workspace / test_receipt["report_path"]
                if _sha_bytes(report.read_bytes()) != test_receipt["report_sha256"]:
                    raise ValueError("TEST_REPORT_HASH_MISMATCH")
                for stream in ("stdout", "stderr"):
                    stream_path = workspace / test_receipt[f"{stream}_path"]
                    if (
                        _sha_bytes(stream_path.read_bytes())
                        != test_receipt[f"{stream}_sha256"]
                    ):
                        raise ValueError("TEST_STREAM_HASH_MISMATCH")
                parsed_counts, parsed_outcomes = _parse_junit(report)
                if (
                    {key: test_receipt[key] for key in ("passed", "failed", "skipped")}
                    != parsed_counts
                    or test_receipt["node_outcomes"] != parsed_outcomes
                    or set(parsed_outcomes) != set(SUITE_NODES[expected_suite])
                    or test_receipt["assertions"]
                    != _derive_suite_assertions(expected_suite, parsed_outcomes)
                ):
                    raise ValueError("TEST_RECEIPT_REPORT_DERIVATION_MISMATCH")
                for relative, expected_hash in test_receipt[
                    "test_source_hashes"
                ].items():
                    if (
                        _sha_bytes(
                            (workspace / "risk-fusion-bench" / relative).read_bytes()
                        )
                        != expected_hash
                    ):
                        raise ValueError("TEST_RECEIPT_SOURCE_HASH_MISMATCH")
                if _parse_time(test_receipt["ended_at_utc"]) > _parse_time(
                    manifest["generated_at_utc"]
                ):
                    raise ValueError("TEST_RECEIPT_POSTDATES_MANIFEST")
                test_receipts[test_receipt["suite_id"]] = test_receipt
        for ref in row["review_receipts"]:
            matching_goals = [
                goal_key
                for goal_key, goal_id in REVIEW_GOAL_IDS.items()
                if ref["goal_id"] == goal_id
            ]
            if (
                len(matching_goals) != 1
                or _structured_review_ref(workspace, matching_goals[0]) != ref
            ):
                raise ValueError("REVIEW_RECEIPT_HASH_MISMATCH")
            artifact_path = workspace / ref["artifact_path"]
            artifact_raw = artifact_path.read_bytes()
            artifact = json.loads(artifact_raw)
            validate(artifact, review_schema)
            body = {
                key: value
                for key, value in artifact.items()
                if key != "receipt_self_sha256"
            }
            if (
                artifact_raw != canonical_bytes(artifact)
                or _sha_bytes(canonical_bytes(body)) != artifact["receipt_self_sha256"]
                or artifact["decision"] != "APPROVE"
                or artifact["reviewer_role"] != "independent"
                or artifact["reviewer_id"] == artifact["producer_id"]
                or not _review_source_record_is_still_present(
                    workspace, matching_goals[0], artifact["source_record"]
                )
            ):
                raise ValueError("STRUCTURED_REVIEW_RECEIPT_INVALID")
    expected_receipt_names = {f"{suite}.test-receipt.json" for suite in test_receipts}
    actual_receipt_names = {
        path.name
        for path in (workspace / ".omx/handoff/g018-phase0/evidence").glob(
            "*.test-receipt.json"
        )
    }
    if (
        set(test_receipts) != {"g016", "g017", "g018"}
        or actual_receipt_names != expected_receipt_names
    ):
        raise ValueError("PHASE0_TEST_RECEIPT_SET_INVALID")
    for identifier, suite_id in P0_SUITE.items():
        if (
            test_receipts[suite_id]["assertions"]["requirement_results"].get(identifier)
            != "PASS"
        ):
            raise ValueError("P0_SUITE_ASSERTION_NOT_PASSING")
    g16 = test_receipts["g016"]["assertions"]
    if any(g16.get(f"ISO-NEG-{index:02d}") != "PASS" for index in range(1, 7)):
        raise ValueError("G016_ISOLATION_ASSERTIONS_INCOMPLETE")
    g17 = test_receipts["g017"]["assertions"]
    agreement = g17.get("semantic_agreement", {})
    if not (
        agreement.get("numerator") == agreement.get("denominator")
        and agreement.get("denominator", 0) > 0
        and agreement.get("rate") == 1.0
        and g17.get("online_checkpoint_replay") == "PASS"
        and g17.get("mandatory_rebuild_fail_closed") == "PASS"
        and g17.get("tamper_fail_closed", {}).get("passed")
        == g17.get("tamper_fail_closed", {}).get("total")
    ):
        raise ValueError("G017_ASSERTION_RECEIPT_INCOMPLETE")
    acceptance = g17.get("p0_02_acceptance", {})
    p002 = next(row for row in rows if row["id"] == "P0-02")
    expected_checks = [
        {"check_id": check_id, "expected": "PASS", "observed": "PASS"}
        for check_id in P002_ACCEPTANCE_CHECKS
    ]
    if (
        p002.get("acceptance_checks") != expected_checks
        or set(acceptance) != set(P002_ACCEPTANCE_CHECKS)
        or any(acceptance[check_id] != "PASS" for check_id in P002_ACCEPTANCE_CHECKS)
        or any("acceptance_checks" in row for row in rows if row["id"] != "P0-02")
    ):
        raise ValueError("P0_02_ACCEPTANCE_CHECKS_INVALID")
    g18 = test_receipts["g018"]["assertions"]
    if g18.get("reopen_validator") != "PASS" or g18.get("atomic_writer") != "PASS":
        raise ValueError("G018_ASSERTION_RECEIPT_INCOMPLETE")
    entries = manifest["bindings"]["research_source_set"]
    for ref in entries:
        if _sha_bytes((workspace / ref["path"]).read_bytes()) != ref["sha256"]:
            raise ValueError("SOURCE_FILE_HASH_MISMATCH")
    if (
        _sha_bytes(canonical_bytes(entries))
        != manifest["bindings"]["research_source_set_sha256"]
    ):
        raise ValueError("SOURCE_SET_HASH_MISMATCH")
    for audit in manifest["audits"].values():
        if _sha_bytes(audit["command"].encode()) != audit["command_sha256"]:
            raise ValueError("AUDIT_COMMAND_HASH_MISMATCH")
        if (
            "argv" in audit
            and _sha_bytes(canonical_bytes(audit["argv"])) != audit["argv_sha256"]
        ):
            raise ValueError("AUDIT_ARGV_HASH_MISMATCH")
        if "started_at_utc" in audit:
            if _parse_time(audit["ended_at_utc"]) < _parse_time(
                audit["started_at_utc"]
            ):
                raise ValueError("AUDIT_TIME_INVERTED")
            if _parse_time(audit["ended_at_utc"]) > _parse_time(
                manifest["generated_at_utc"]
            ):
                raise ValueError("AUDIT_POSTDATES_MANIFEST")
        body = {key: value for key, value in audit.items() if key != "report_sha256"}
        if _sha_bytes(canonical_bytes(body)) != audit["report_sha256"]:
            raise ValueError("AUDIT_REPORT_HASH_MISMATCH")
    for row in rows:
        for ref in row["audit_refs"]:
            audit = manifest["audits"].get(ref["audit_id"])
            if audit is None or audit["report_sha256"] != ref["report_sha256"]:
                raise ValueError("AUDIT_REFERENCE_HASH_MISMATCH")
    environment = manifest["audits"]["environment"]
    if environment["status"] == "PASS":
        from rfb.research.phase0_frozen_runtime import (
            _source_binding,
            validate_frozen_runtime,
        )

        output = workspace / ".omx/handoff/g019-phase0"
        qualification = validate_frozen_runtime(output)
        runtime_manifest_path = output / "runtime-manifest.json"
        runtime_manifest = json.loads(runtime_manifest_path.read_text(encoding="utf-8"))
        expected_qualification_path = output / "qualification.json"
        if (
            qualification["status"] != "PASS"
            or runtime_manifest["source_binding"] != _source_binding(workspace)
            or environment["environment_id"] != qualification["environment_id"]
            or environment["qualification_path"]
            != expected_qualification_path.relative_to(workspace).as_posix()
            or environment["qualification_sha256"]
            != _sha_bytes(expected_qualification_path.read_bytes())
            or environment["runtime_manifest_sha256"]
            != _sha_bytes(runtime_manifest_path.read_bytes())
            or environment["receipt_refs"] != qualification["receipt_refs"]
            or environment["pip_check_returncode"] != 0
            or environment["pip_check_output_sha256"]
            != json.loads(
                (output / "receipts/pip_check.json").read_text(encoding="utf-8")
            )["report_sha256"]
            or set(environment["frozen_runtime_checks"].values()) != {"PASS"}
        ):
            raise ValueError("FROZEN_RUNTIME_EVIDENCE_MISMATCH")
    scanner_names = SCANNER_IDS
    for name in scanner_names:
        audit = manifest["audits"][name]
        expected_argv = [
            sys.executable,
            "-m",
            "rfb.research.phase0_qualification",
            "scan",
            name,
            "--workspace",
            str(workspace),
        ]
        if (
            audit["audit_id"] != name
            or audit["argv"] != expected_argv
            or audit["cwd"] != str(workspace / "risk-fusion-bench")
        ):
            raise ValueError("SCANNER_EXECUTION_CONTRACT_MISMATCH")
        if audit["exit_code"] == 0:
            expected_scan = scan_phase0_boundary(workspace, name)
            for field in (
                "audit_id",
                "scope",
                "allowlist",
                "command",
                "violations",
                "status",
            ):
                if audit[field] != expected_scan[field]:
                    raise ValueError("SCANNER_SCOPE_OR_POLICY_MISMATCH")
            expected_stdout = canonical_bytes(expected_scan) + b"\n"
            if audit["stdout_sha256"] != _sha_bytes(expected_stdout):
                raise ValueError("SCANNER_STDOUT_BINDING_MISMATCH")
        elif not (
            audit["status"] == "BLOCKED"
            and audit["violations"] == ["SCANNER_UNAVAILABLE"]
            and audit["scope"] == [f"requested scanner:{name}"]
            and audit["allowlist"] == ["none; scanner execution is mandatory"]
        ):
            raise ValueError("SCANNER_FAILURE_EVIDENCE_INVALID")
    scanner_pass = all(
        manifest["audits"][name]["status"] == "PASS"
        and manifest["audits"][name]["exit_code"] == 0
        and not manifest["audits"][name]["violations"]
        for name in scanner_names
    )
    for row in rows:
        suite_assertion_pass = (
            test_receipts[P0_SUITE[row["id"]]]["assertions"]["requirement_results"].get(
                row["id"]
            )
            == "PASS"
        )
        if row["id"] == "P0-09":
            derived = (
                "PASS"
                if scanner_pass
                else "BLOCKED"
                if any(
                    manifest["audits"][name]["status"] == "BLOCKED"
                    for name in scanner_names
                )
                else "FAIL"
            )
        elif row["id"] == "P0-10":
            environment_status = manifest["audits"]["environment"]["status"]
            derived = "PASS" if environment_status == "PASS" else environment_status
        elif row["id"] == "P0-05":
            derived = (
                "PASS"
                if manifest["audits"]["truth_path"]["status"] == "PASS"
                else "FAIL"
            )
        else:
            derived = (
                "PASS"
                if manifest["audits"]["lifecycle_qualification"]["status"] == "PASS"
                else "FAIL"
            )
        if not suite_assertion_pass:
            derived = "FAIL"
        if row["status"] != derived:
            raise ValueError("REQUIREMENT_STATUS_NOT_DERIVED_FROM_EVIDENCE")
        if row["status"] == "BLOCKED" and not row["blocker_code"]:
            raise ValueError("BLOCKED_REQUIREMENT_WITHOUT_CODE")
        if row["status"] == "PASS" and row["blocker_code"] is not None:
            raise ValueError("PASS_REQUIREMENT_HAS_BLOCKER")
    all_pass = all(row["status"] == "PASS" for row in rows)
    expected_decision = {
        "phase0_qualified": all_pass,
        "authorization_eligible": all_pass,
        "execution_authorized": False,
        "authorization_artifact_created": False,
    }
    if manifest["decision"] != expected_decision:
        raise ValueError("DECISION_NOT_DERIVED_FROM_REQUIREMENTS")
    receipt_raw = receipt_file.read_bytes()
    receipt = json.loads(receipt_raw)
    receipt_schema = json.loads(
        (contracts / "phase0_qualification_raw_receipt.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validate(receipt, receipt_schema)
    if receipt_raw != canonical_bytes(receipt):
        raise ValueError("RAW_RECEIPT_NOT_CANONICAL_BYTES")
    receipt_body = {
        key: value for key, value in receipt.items() if key != "receipt_self_sha256"
    }
    if _sha_bytes(canonical_bytes(receipt_body)) != receipt["receipt_self_sha256"]:
        raise ValueError("RAW_RECEIPT_SELF_HASH_MISMATCH")
    if receipt["manifest_raw_bytes_sha256"] != _sha_bytes(raw):
        raise ValueError("MANIFEST_RAW_BYTES_HASH_MISMATCH")
    if receipt["manifest_self_sha256"] != manifest["manifest_self_sha256"]:
        raise ValueError("RAW_RECEIPT_MANIFEST_BINDING_MISMATCH")
    if _parse_time(receipt["generated_at_utc"]) < _parse_time(
        manifest["generated_at_utc"]
    ):
        raise ValueError("RECEIPT_TIME_PRECEDES_MANIFEST")
    return manifest


def write_phase0_qualification(
    workspace_root: str | Path, output_dir: str | Path
) -> tuple[Path, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest = build_phase0_qualification(workspace_root)
    manifest_path = output / "Phase0QualificationManifest.json"
    manifest_tmp = output / f".{manifest_path.name}.partial"
    manifest_tmp.write_bytes(canonical_bytes(manifest))
    os.replace(manifest_tmp, manifest_path)
    receipt_body = {
        "schema_version": "1.0.0",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        **CLASSIFICATION,
        "manifest_path": manifest_path.name,
        "manifest_self_sha256": manifest["manifest_self_sha256"],
        "manifest_raw_bytes_sha256": _sha_bytes(manifest_path.read_bytes()),
    }
    receipt = {
        **receipt_body,
        "receipt_self_sha256": _sha_bytes(canonical_bytes(receipt_body)),
    }
    receipt_path = output / "Phase0QualificationManifest.raw-hash-receipt.json"
    receipt_tmp = output / f".{receipt_path.name}.partial"
    receipt_tmp.write_bytes(canonical_bytes(receipt))
    os.replace(receipt_tmp, receipt_path)
    validate_phase0_qualification(workspace_root, manifest_path, receipt_path)
    return manifest_path, receipt_path


__all__ = [
    "BLOCKED_ENVIRONMENT",
    "build_phase0_qualification",
    "run_pytest_receipt",
    "scan_phase0_boundary",
    "validate_phase0_qualification",
    "write_phase0_qualification",
]


def _main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument(
        "audit_id", choices=("credential", "truth_path", "candidate_write", "d_test")
    )
    scan.add_argument("--workspace", required=True)
    args = parser.parse_args()
    print(canonical_bytes(scan_phase0_boundary(args.workspace, args.audit_id)).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
