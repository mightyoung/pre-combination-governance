"""Validate returned evidence bundles for the PCG CPU-only V2 replay task."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
import re
from typing import Any


TASK_ID = "PCG-LINEAGE-CPU-REPLAY-001"
SCHEMA_VERSION = "pcg.user_cpu_replay_result.v1"
BASE_RUNNER_COMMIT = "c969913eacb56cda1236009ffa9390bd6f62cd3c"
SOURCE_SAMPLE_SHA256 = "9bfbd8a6600deb0c230fea2294f3673a2c726e5c8285687cb9531cd88a64d599"
SOURCE_SAMPLE_BYTES = 2537
PRE_RUN_MANIFEST_SHA256 = "cdf77fe8a5bd5db08aaa9f7a967f47c733a3bd5fcfb3737eb59a515f404d22a7"
SCORER_TRUTH_MANIFEST_SHA256 = "16129b5109059a3e844bb930eeb938653134a4789d0bbed8c1e4ea6057c33d24"
EXPECTED_METHOD_OUTPUTS_SHA256 = "15ee4c362160bfb1381da9a2e304f09224e73c265dc95fba949135d5694c66cb"
RUNNER_COMMAND = (
    "PYTHONPATH=risk-fusion-bench/src python "
    "research-three/v2-alignment-20261011/runs/"
    "two-hop-lineage-controlled-synthetic-20261012-v2/run_two_hop_lineage_v2.py"
)
SCORER_COMMAND = (
    "PYTHONPATH=risk-fusion-bench/src python "
    "research-three/v2-alignment-20261011/runs/"
    "two-hop-lineage-controlled-synthetic-20261012-v2/score_two_hop_lineage_v2.py"
)
EXPECTED_COMMANDS = (RUNNER_COMMAND, SCORER_COMMAND)

PASS_ARTIFACTS = {
    "METHOD_OUTPUTS_V2.json",
    "METHOD_OUTPUT_FREEZE_V2.json",
    "RUNNER_CHECKS_V2.json",
    "SCORED_RESULT_V2.json",
    "ALIAS_HOP1_V2.json",
    "ALIAS_HOP2_V2.json",
    "SIDEINPUT_NEGATIVE_HOP2_V2.json",
    "PRE_RUN_MANIFEST_V2.json",
    "SCORER_TRUTH_MANIFEST_V2.json",
    "commands.txt",
    "environment.json",
    "stdout.log",
    "stderr.log",
}
FAILURE_ARTIFACTS = {"commands.txt", "environment.json", "stdout.log", "stderr.log"}
RESULT_FIELDS = {
    "schema_version", "task_id", "run_id", "task_status", "target_runner_commit",
    "observed_runner_commit", "execution", "expected_input_pins", "observed_input_pins",
    "outcome", "failure_reasons", "artifacts",
}
EXECUTION_FIELDS = {
    "started_at_utc", "finished_at_utc", "python_version", "platform", "cpu_count",
    "gpu_used", "network_calls_after_checkout", "model_called", "notification_called",
    "packages_installed_for_task", "commands", "wall_time_seconds", "peak_memory_mib",
    "runner_exit_code", "scorer_exit_code",
}
PIN_FIELDS = {
    "pre_run_manifest_sha256", "scorer_truth_manifest_sha256", "source_sample_sha256",
    "source_sample_bytes",
}
OUTCOME_FIELDS = {
    "method_outputs_sha256", "runner_checks_total", "runner_checks_passed", "full_receipt_chain",
    "missing_hop2_receipt", "hash_only", "side_input_receipt_status", "side_input_lineage_status",
    "production_truth_denominator", "production_accuracy", "wrong_confirmed_attribution_status",
    "pair_rows_independent",
}
ARTIFACT_FIELDS = {"path", "bytes", "sha256"}
COUNT_FIELDS = {"confirmed", "unknown"}


class HandoffValidationError(ValueError):
    """Raised when a returned run bundle is malformed or contradicts its claims."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffValidationError(f"cannot read JSON {path.name}: {exc}") from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HandoffValidationError(message)


def _require_exact_fields(value: Any, expected: set[str], label: str) -> None:
    _require(isinstance(value, dict), f"{label} must be an object")
    actual = set(value)
    unexpected = sorted(actual - expected)
    missing = sorted(expected - actual)
    _require(not unexpected, f"unexpected {label} fields: {unexpected}")
    _require(not missing, f"missing {label} fields: {missing}")


def _is_utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0


def _parse_python_version(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    match = re.match(r"^(\d+)\.(\d+)(?:\.|$)", value)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _load_artifacts(bundle_dir: Path, manifest: Any) -> dict[str, Path]:
    _require(isinstance(manifest, list), "artifacts must be an array")
    loaded: dict[str, Path] = {}
    for row in manifest:
        _require_exact_fields(row, ARTIFACT_FIELDS, "artifact entry")
        path_value = row.get("path")
        _require(isinstance(path_value, str) and path_value not in {"", "."}, "artifact path is required")
        _require("\\" not in path_value, f"unsafe artifact path: {path_value}")
        relative = Path(path_value)
        _require(not relative.is_absolute() and len(relative.parts) == 1 and relative.name == path_value,
                 f"unsafe artifact path: {path_value}")
        _require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", path_value) is not None,
                 f"artifact path does not match the result schema: {path_value}")
        _require(path_value != "TASK_RESULT.json", "TASK_RESULT.json cannot hash itself")
        _require(path_value not in loaded, f"duplicate artifact path: {path_value}")
        artifact = bundle_dir / relative
        _require(not artifact.is_symlink(), f"symlink artifact is not accepted: {path_value}")
        _require(artifact.is_file(), f"missing artifact: {path_value}")
        raw = artifact.read_bytes()
        _require(isinstance(row.get("sha256"), str) and row["sha256"] == _sha256(raw),
                 f"SHA-256 mismatch: {path_value}")
        _require(type(row.get("bytes")) is int and row["bytes"] == len(raw),
                 f"byte length mismatch: {path_value}")
        loaded[path_value] = artifact
    return loaded


def _compare_scorer_claims(result: dict[str, Any], scorer: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    expected_conditions = {
        "full_receipt_chain": ("FULL_RECEIPT_CHAIN", {"confirmed": 3, "unknown": 0}),
        "missing_hop2_receipt": ("MISSING_INTERMEDIATE_RECEIPT", {"confirmed": 1, "unknown": 2}),
        "hash_only": ("HASH_ONLY_DEDUP", {"confirmed": 0, "unknown": 3}),
    }
    outcome = result.get("outcome")
    if not isinstance(outcome, dict):
        return ["outcome summary is missing"]
    for field, (condition_id, expected) in expected_conditions.items():
        display = field.replace("_", "-")
        actual_count = scorer.get("conditions", {}).get(condition_id, {}).get("counts", {})
        observed = {
            "confirmed": actual_count.get("confirmed_shared_ancestor"),
            "unknown": actual_count.get("unknown"),
        }
        if observed != expected:
            mismatches.append(f"{display} counts differ from frozen expectation")
        if outcome.get(field) != observed:
            mismatches.append(f"{display} summary differs from SCORED_RESULT_V2.json")
    side_input = scorer.get("side_input_negative_control", {})
    if outcome.get("side_input_receipt_status") != side_input.get("receipt_validation_status"):
        mismatches.append("side-input receipt status differs from SCORED_RESULT_V2.json")
    if outcome.get("side_input_lineage_status") != side_input.get("lineage_status"):
        mismatches.append("side-input lineage status differs from SCORED_RESULT_V2.json")
    for field in ("production_truth_denominator", "production_accuracy", "wrong_confirmed_attribution_status"):
        if outcome.get(field) != scorer.get(field):
            mismatches.append(f"{field} differs from SCORED_RESULT_V2.json")
    if outcome.get("pair_rows_independent") is not scorer.get("pair_rows_are_independent_samples"):
        mismatches.append("pair independence summary differs from SCORED_RESULT_V2.json")
    return mismatches


def _verify_result_schema(repo_root: Path) -> None:
    schema_path = (repo_root / "research-three/v2-alignment-20261011/runs/"
                   "two-hop-lineage-controlled-synthetic-20261012-v2/"
                   "USER_CPU_REPLAY_RESULT_V1.schema.json")
    schema = _read_json(schema_path)
    _require(isinstance(schema, dict), "result schema must contain an object")
    _require(schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema",
             "result schema must declare JSON Schema draft 2020-12")
    properties = schema.get("properties", {})
    _require(schema.get("additionalProperties") is False, "result schema must reject undeclared fields")
    _require_exact_fields(properties, RESULT_FIELDS, "result schema property")
    _require(set(schema.get("required", [])) == RESULT_FIELDS,
             "result schema required fields are out of sync with the validator")

    def check_object_contract(object_schema: Any, fields: set[str], label: str) -> dict[str, Any]:
        _require(isinstance(object_schema, dict) and object_schema.get("type") == "object",
                 f"result schema {label} must be an object")
        _require(object_schema.get("additionalProperties") is False,
                 f"result schema {label} must reject undeclared fields")
        object_properties = object_schema.get("properties", {})
        _require_exact_fields(object_properties, fields, f"result schema {label} property")
        _require(set(object_schema.get("required", [])) == fields,
                 f"result schema {label} required fields are out of sync with the validator")
        return object_properties

    execution_properties = check_object_contract(properties.get("execution"), EXECUTION_FIELDS, "execution")
    pin_properties = check_object_contract(properties.get("expected_input_pins"), PIN_FIELDS, "expected_input_pins")
    observed_pin_branch = properties.get("observed_input_pins", {}).get("oneOf", [{}, {}])[1]
    check_object_contract(observed_pin_branch, PIN_FIELDS, "observed_input_pins")
    outcome_branch = properties.get("outcome", {}).get("oneOf", [{}, {}])[1]
    outcome_properties = check_object_contract(outcome_branch, OUTCOME_FIELDS, "outcome")
    artifact_schema = properties.get("artifacts", {}).get("items")
    check_object_contract(artifact_schema, ARTIFACT_FIELDS, "artifact entry")
    count_properties = check_object_contract(schema.get("$defs", {}).get("counts"), COUNT_FIELDS, "count summary")
    _require(execution_properties["gpu_used"].get("const") is False
             and execution_properties["network_calls_after_checkout"].get("const") is False
             and execution_properties["model_called"].get("const") is False
             and execution_properties["notification_called"].get("const") is False,
             "result schema must prohibit GPU, network, model, and notification use")
    _require(outcome_properties["full_receipt_chain"].get("$ref") == "#/$defs/counts"
             and outcome_properties["missing_hop2_receipt"].get("$ref") == "#/$defs/counts"
             and outcome_properties["hash_only"].get("$ref") == "#/$defs/counts"
             and count_properties.keys() == COUNT_FIELDS,
             "result schema count summary is out of sync with the validator")
    _require(properties.get("schema_version", {}).get("const") == SCHEMA_VERSION,
             "result schema version is out of sync with the validator")
    _require(properties.get("task_id", {}).get("const") == TASK_ID,
             "result schema task ID is out of sync with the validator")
    _require(properties.get("target_runner_commit", {}).get("const") == BASE_RUNNER_COMMIT,
             "result schema runner commit is out of sync with the validator")
    expected_pins = {
        "pre_run_manifest_sha256": PRE_RUN_MANIFEST_SHA256,
        "scorer_truth_manifest_sha256": SCORER_TRUTH_MANIFEST_SHA256,
        "source_sample_sha256": SOURCE_SAMPLE_SHA256,
        "source_sample_bytes": SOURCE_SAMPLE_BYTES,
    }
    _require(all(pin_properties.get(key, {}).get("const") == value for key, value in expected_pins.items()),
             "result schema input pins are out of sync with the validator")


def validate_user_cpu_replay_bundle(bundle_dir: Path, repo_root: Path) -> dict[str, Any]:
    """Verify bundle structure and frozen V2 mechanics without claiming accuracy."""
    bundle_dir = Path(bundle_dir).resolve()
    repo_root = Path(repo_root).resolve()
    _verify_result_schema(repo_root)
    result_path = bundle_dir / "TASK_RESULT.json"
    result = _read_json(result_path)
    _require_exact_fields(result, RESULT_FIELDS, "result")
    _require(result.get("schema_version") == SCHEMA_VERSION, "unsupported schema_version")
    _require(result.get("task_id") == TASK_ID, "task_id does not match this task")
    run_id = result.get("run_id")
    _require(isinstance(run_id, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,100}", run_id) is not None,
             "run_id must be a unique path-safe identifier")
    status = result.get("task_status")
    _require(status in {"PASS", "FAIL", "BLOCKED"}, "task_status must be PASS, FAIL, or BLOCKED")
    _require(result.get("target_runner_commit") == BASE_RUNNER_COMMIT,
             "target_runner_commit is not the pinned V2 runner revision")
    observed_commit = result.get("observed_runner_commit")
    if observed_commit is not None:
        _require(isinstance(observed_commit, str) and re.fullmatch(r"[0-9a-f]{40}", observed_commit) is not None,
                 "observed_runner_commit must be a full lowercase Git SHA or null")
    if status == "PASS":
        _require(observed_commit == BASE_RUNNER_COMMIT, "passing run used the wrong runner commit")

    execution = result.get("execution")
    _require_exact_fields(execution, EXECUTION_FIELDS, "execution")
    _require(_is_utc_timestamp(execution.get("started_at_utc")), "started_at_utc must be a UTC Z timestamp")
    _require(_is_utc_timestamp(execution.get("finished_at_utc")), "finished_at_utc must be a UTC Z timestamp")
    started_at = datetime.fromisoformat(execution["started_at_utc"][:-1] + "+00:00")
    finished_at = datetime.fromisoformat(execution["finished_at_utc"][:-1] + "+00:00")
    _require(finished_at >= started_at, "finished_at_utc predates started_at_utc")
    python_version = _parse_python_version(execution.get("python_version"))
    _require(python_version is not None and python_version >= (3, 11), "Python >=3.11 is required")
    _require(isinstance(execution.get("platform"), str) and execution["platform"], "execution.platform is required")
    _require(type(execution.get("cpu_count")) is int and execution["cpu_count"] >= 1, "cpu_count must be a positive integer")
    for field in ("gpu_used", "network_calls_after_checkout", "model_called", "notification_called"):
        _require(execution.get(field) is False, f"{field} must be false for this CPU-only task")
    _require(execution.get("packages_installed_for_task") == [], "this task must not install packages")
    commands = execution.get("commands")
    _require(isinstance(commands, list) and commands and all(isinstance(item, str) and item for item in commands),
             "execution.commands must list the exact commands")
    if status == "PASS":
        _require(all(command in commands for command in EXPECTED_COMMANDS),
                 "passing run must record both frozen runner entry-point commands")
    exit_codes = (execution.get("runner_exit_code"), execution.get("scorer_exit_code"))
    _require(all(value is None or type(value) is int for value in exit_codes),
             "runner and scorer exit codes must be integers or null")
    for field, maximum in (("wall_time_seconds", 300), ("peak_memory_mib", 1024)):
        value = execution.get(field)
        _require(value is None or (type(value) in (int, float) and 0 <= value <= maximum),
                 f"{field} must be null or within the task ceiling")
    if status == "PASS":
        _require(exit_codes == (0, 0), "passing run requires runner and scorer exit code 0")
    else:
        reasons = result.get("failure_reasons")
        _require(isinstance(reasons, list) and len(reasons) > 0 and all(isinstance(item, str) and item for item in reasons),
                 "FAIL/BLOCKED task results require failure_reasons")
    if status == "PASS":
        _require(result.get("failure_reasons") == [], "passing run cannot list failure_reasons")

    expected_pins = result.get("expected_input_pins")
    _require_exact_fields(expected_pins, PIN_FIELDS, "expected_input_pins")
    _require(expected_pins.get("pre_run_manifest_sha256") == PRE_RUN_MANIFEST_SHA256,
             "expected pre-run manifest pin mismatch")
    _require(expected_pins.get("scorer_truth_manifest_sha256") == SCORER_TRUTH_MANIFEST_SHA256,
             "expected scorer truth manifest pin mismatch")
    _require(expected_pins.get("source_sample_sha256") == SOURCE_SAMPLE_SHA256,
             "expected source sample hash pin mismatch")
    _require(expected_pins.get("source_sample_bytes") == SOURCE_SAMPLE_BYTES,
             "expected source sample byte-length pin mismatch")
    observed_pins = result.get("observed_input_pins")
    if observed_pins is not None:
        _require_exact_fields(observed_pins, PIN_FIELDS, "observed_input_pins")
        for field in ("pre_run_manifest_sha256", "scorer_truth_manifest_sha256", "source_sample_sha256"):
            _require(isinstance(observed_pins[field], str)
                     and re.fullmatch(r"[0-9a-f]{64}", observed_pins[field]) is not None,
                     f"observed_input_pins.{field} must be a lowercase SHA-256 digest")
        _require(type(observed_pins["source_sample_bytes"]) is int
                 and observed_pins["source_sample_bytes"] >= 0,
                 "observed_input_pins.source_sample_bytes must be a nonnegative integer")
        if status == "PASS":
            _require(observed_pins == expected_pins, "observed input pins differ from the frozen inputs")

    artifacts = _load_artifacts(bundle_dir, result.get("artifacts"))
    required = PASS_ARTIFACTS if status == "PASS" else FAILURE_ARTIFACTS
    _require(required.issubset(artifacts), f"missing required artifacts: {sorted(required - set(artifacts))}")
    if "commands.txt" in artifacts:
        recorded_commands = artifacts["commands.txt"].read_text(encoding="utf-8").splitlines()
        _require(recorded_commands == commands, "commands.txt differs from execution.commands")
    if "environment.json" in artifacts:
        environment = _read_json(artifacts["environment.json"])
        _require(isinstance(environment, dict), "environment.json must contain an object")
        for field in (
            "python_version",
            "platform",
            "cpu_count",
            "gpu_used",
            "network_calls_after_checkout",
            "model_called",
            "notification_called",
            "packages_installed_for_task",
        ):
            _require(environment.get(field) == execution.get(field),
                     f"environment.json {field} differs from TASK_RESULT.json")

    notes: list[str] = []
    candidate_outcome = result.get("outcome")
    if candidate_outcome is not None:
        _require_exact_fields(candidate_outcome, OUTCOME_FIELDS, "outcome")
        _require(isinstance(candidate_outcome["method_outputs_sha256"], str)
                 and re.fullmatch(r"[0-9a-f]{64}", candidate_outcome["method_outputs_sha256"]) is not None,
                 "outcome.method_outputs_sha256 must be a lowercase SHA-256 digest")
        for field in ("runner_checks_total", "runner_checks_passed", "production_truth_denominator"):
            _require(type(candidate_outcome[field]) is int and candidate_outcome[field] >= 0,
                     f"outcome.{field} must be a nonnegative integer")
        for field in ("side_input_receipt_status", "side_input_lineage_status", "production_accuracy",
                      "wrong_confirmed_attribution_status"):
            _require(isinstance(candidate_outcome[field], str), f"outcome.{field} must be a string")
        _require(type(candidate_outcome["pair_rows_independent"]) is bool,
                 "outcome.pair_rows_independent must be a boolean")
        for field in ("full_receipt_chain", "missing_hop2_receipt", "hash_only"):
            _require_exact_fields(candidate_outcome[field], COUNT_FIELDS, f"outcome.{field}")
            _require(all(type(candidate_outcome[field][name]) is int and candidate_outcome[field][name] >= 0
                         for name in COUNT_FIELDS), f"outcome.{field} counts must be nonnegative integers")
    if status != "PASS":
        notes.append("task outcome did not pass; bundle validity does not change that outcome")
    for filename, expected_hash in (
        ("PRE_RUN_MANIFEST_V2.json", PRE_RUN_MANIFEST_SHA256),
        ("SCORER_TRUTH_MANIFEST_V2.json", SCORER_TRUTH_MANIFEST_SHA256),
    ):
        if filename in artifacts:
            _require(_sha256(artifacts[filename].read_bytes()) == expected_hash,
                     f"{filename} differs from the pinned manifest")
    if status == "PASS":
        for filename in ("PRE_RUN_MANIFEST_V2.json", "SCORER_TRUTH_MANIFEST_V2.json"):
            _require((repo_root / "research-three/v2-alignment-20261011/runs/"
                      "two-hop-lineage-controlled-synthetic-20261012-v2" / filename).is_file(),
                     f"repository baseline missing {filename}")
            baseline = (repo_root / "research-three/v2-alignment-20261011/runs/"
                        "two-hop-lineage-controlled-synthetic-20261012-v2" / filename).read_bytes()
            _require(_sha256(baseline) == (PRE_RUN_MANIFEST_SHA256 if filename.startswith("PRE_RUN")
                                         else SCORER_TRUTH_MANIFEST_SHA256),
                     f"repository baseline {filename} changed")
            manifest = _read_json(artifacts[filename])
            _require(isinstance(manifest.get("files"), list), f"{filename} has no file list")
            for entry in manifest["files"]:
                _require(isinstance(entry, dict) and isinstance(entry.get("path"), str),
                         f"{filename} contains a malformed file entry")
                source_path = (repo_root / entry["path"]).resolve()
                _require(source_path.is_relative_to(repo_root) and source_path.is_file(),
                         f"{filename} references a missing or unsafe repository path")
                raw = source_path.read_bytes()
                _require(len(raw) == entry.get("bytes") and _sha256(raw) == entry.get("sha256"),
                         f"frozen input changed: {entry['path']}")

        method_bytes = artifacts["METHOD_OUTPUTS_V2.json"].read_bytes()
        method_hash = _sha256(method_bytes)
        _require(method_hash == EXPECTED_METHOD_OUTPUTS_SHA256, "method output hash differs from frozen replay")
        method_freeze = _read_json(artifacts["METHOD_OUTPUT_FREEZE_V2.json"])
        _require(method_freeze.get("sha256") == method_hash and method_freeze.get("bytes") == len(method_bytes),
                 "method-output freeze does not match method output bytes")
        runner = _read_json(artifacts["RUNNER_CHECKS_V2.json"])
        _require(runner.get("pre_run_commit") == BASE_RUNNER_COMMIT, "runner used an unexpected pre-run commit")
        _require(runner.get("pre_run_manifest_sha256") == PRE_RUN_MANIFEST_SHA256,
                 "runner recorded an unexpected pre-run manifest")
        _require(runner.get("method_outputs_sha256_at_freeze") == method_hash,
                 "runner recorded an unexpected method-output hash")
        _require(runner.get("method_runner_read_truth_log") is False, "method runner truth-isolation check failed")
        _require(runner.get("network_or_model_or_notification_called") is False,
                 "runner records a prohibited external/model/notification call")
        checks = runner.get("checks")
        _require(isinstance(checks, dict) and len(checks) == 16 and all(value is True for value in checks.values()),
                 "runner must report all 16 frozen checks true")

        scored = _read_json(artifacts["SCORED_RESULT_V2.json"])
        _require(scored.get("method_outputs_sha256_at_freeze") == method_hash,
                 "scorer is not bound to the frozen method output")
        _require(scored.get("production_truth_denominator") == 0, "production truth denominator must remain zero")
        _require(scored.get("production_accuracy") == "NOT_COMPUTABLE", "production accuracy must remain not computable")
        _require(scored.get("wrong_confirmed_attribution_status") == "NOT_EVALUATED_NO_INDEPENDENT_PRODUCTION_TRUTH",
                 "production attribution accuracy must remain unevaluated")
        _require(scored.get("pair_rows_are_independent_samples") is False,
                 "the fixed pair rows must not be represented as independent samples")
        _require(scored.get("synthetic_truth_fixture_used_for_accuracy") is False,
                 "synthetic truth cannot be used as production accuracy")
        _require(scored.get("network_or_model_or_notification_called") is False,
                 "scorer records a prohibited external/model/notification call")

        outcome = result.get("outcome")
        _require(outcome.get("method_outputs_sha256") == method_hash, "TASK_RESULT method-output hash mismatch")
        _require(outcome.get("runner_checks_total") == 16 and outcome.get("runner_checks_passed") == 16,
                 "TASK_RESULT runner check totals do not match")
        mismatches = _compare_scorer_claims(result, scored)
        _require(not mismatches, "; ".join(mismatches))
        _require(outcome.get("full_receipt_chain") == {"confirmed": 3, "unknown": 0},
                 "full-receipt counts differ from frozen expectation")
        _require(outcome.get("missing_hop2_receipt") == {"confirmed": 1, "unknown": 2},
                 "missing-receipt counts differ from frozen expectation")
        _require(outcome.get("hash_only") == {"confirmed": 0, "unknown": 3},
                 "hash-only counts differ from frozen expectation")
        _require(outcome.get("side_input_receipt_status") == "UNDECLARED_SIDE_INPUT"
                 and outcome.get("side_input_lineage_status") == "UNKNOWN",
                 "side-input negative control did not fail closed")

    return {
        "bundle_valid": True,
        "task_status": status,
        "artifacts_verified": len(artifacts),
        "checks_passed": 16 if status == "PASS" else None,
        "notes": notes,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path,
                        default=Path(__file__).resolve().parents[4])
    args = parser.parse_args()
    try:
        report = validate_user_cpu_replay_bundle(args.bundle_dir, args.repo_root)
    except HandoffValidationError as exc:
        print(json.dumps({"bundle_valid": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
