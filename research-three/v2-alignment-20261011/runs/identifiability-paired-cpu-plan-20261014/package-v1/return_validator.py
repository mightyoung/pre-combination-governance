"""Validate execution receipts and optional score receipts fail-closed."""

import hashlib
import json
import math
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime

PACKAGE_DIR = Path(__file__).resolve().parent
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

from bundle import BundleError, verify_frozen_bundle
from bundle import canonical_bytes
from runner import _valid_manifest, validate_qualification_evidence
from pair_inputs import build_pair_cases, canonical_json_bytes
from result_contract import ResultContractError, validate_result
from scorer import score_bundle


class ReturnValidationError(ValueError):
    pass


ATTEMPT_REQUIRED = (
    "schema_version", "task_id", "run_id", "attempt_count", "task_status",
    "terminal_exit_code", "research_acceptance", "planned_method_invocations",
    "method_start_requests", "method_invocations_started", "completed_method_invocations",
    "partial", "stop_reason", "case_ids", "method_order", "task_manifest_sha256",
    "source_commits", "schema_hashes", "public_input_sha256", "pair_inputs_sha256",
    "oracle_sha256", "oracle_case_map_sha256", "started_at_utc", "finished_at_utc",
    "plan_sha256", "wall_seconds_elapsed", "wall_seconds_scope", "cpu_quota_millis",
    "wall_seconds_limit", "container_cleanup_reserve_seconds", "memory_limit_bytes",
    "pids_limit", "max_method_output_bytes", "method_output_bytes_captured",
    "method_output_bytes_observed", "peak_rss_bytes", "cpu_usage_seconds",
    "method_start_unknown_slots", "slot_exit_records", "sandbox_image_cleanup",
    "qualification_evidence", "execution_environment", "command", "artifacts",
    "output_file", "output_sha256", "output_freeze_sha256",
)
HASH_FIELDS = (
    "task_manifest_sha256", "public_input_sha256", "pair_inputs_sha256",
    "oracle_sha256", "oracle_case_map_sha256", "plan_sha256",
)
MANIFEST_PIN_FIELDS = (
    "source_commits", "schema_hashes", "public_input_sha256", "pair_inputs_sha256",
    "oracle_sha256", "oracle_case_map_sha256", "plan_sha256",
)
RESOURCE_FIELDS = (
    "cpu_quota_millis", "wall_seconds", "memory_bytes", "pids_limit",
    "max_method_output_bytes",
)
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SLOT_FILE_RE = re.compile(r"^slot-([0-9]{4})\.(stdout|stderr)\.bin$")
SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SLOT_EXIT_FIELDS = {
    "slot", "case_id", "prefix", "method", "status", "started", "start_requested",
    "start_unknown", "container_id", "container_cleanup_status", "cli_exit_code",
    "container_exit_code", "oom_killed", "stdout_path", "stderr_path",
    "output_bytes_observed", "error",
}
ARTIFACT_FIELDS = {"path", "bytes", "sha256"}
QUALIFICATION_FIELDS = {
    "schema_version", "probe_id", "status", "script_sha256", "image_id",
    "completed_at_utc", "checks", "observed",
}
EXPECTED_CASES = (
    "38e02496822f1a85849b6a39f698e50d", "33fadeeedeed902bd0ab9dfae5420213",
    "42474559127419126b713096e9f4d3ee", "81050a121e028f59f1e6940d7c5eb477",
)
EXPECTED_METHODS = ("M0", "M1", "M2", "M3")


def _is_int(value, minimum=0):
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _require(condition, message):
    if not condition:
        raise ReturnValidationError(message)


def _is_datetime(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _load_manifest(path, attempt):
    manifest_path = Path(path).resolve()
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReturnValidationError("pinned task manifest is unreadable JSON") from error
    _require(isinstance(manifest, dict), "pinned task manifest must be an object")
    _require(manifest.get("task_id") == "PCG-IDENTIFIABILITY-PAIRED-CPU-001",
             "task manifest task ID differs from the reviewed plan")
    _require(hashlib.sha256(manifest_bytes).hexdigest() == attempt.get("task_manifest_sha256"),
             "attempt task manifest SHA-256 mismatch")
    _require(manifest.get("task_id") == attempt.get("task_id"),
             "attempt task ID differs from task manifest")
    _require(manifest.get("resource_profile_status") == "PRE_REGISTERED",
             "execution receipt cannot bind an unregistered resource profile")
    resources = manifest.get("resources")
    _require(isinstance(resources, dict) and set(resources) == set(RESOURCE_FIELDS),
             "task manifest resource profile is incomplete")
    for field in RESOURCE_FIELDS:
        _require(_is_int(resources.get(field), 1),
                 "task manifest resource is not a positive integer: " + field)
    _require(resources["cpu_quota_millis"] == 1000,
             "task manifest CPU quota differs from the reviewed plan")
    manifest_issues = _valid_manifest(manifest)
    _require(not manifest_issues,
             "task manifest differs from the reviewed plan: " + "; ".join(manifest_issues))
    for filename, expected_hash in manifest.get("schema_hashes", {}).items():
        schema_path = PACKAGE_DIR / "schemas" / filename
        _require(schema_path.is_file()
                 and hashlib.sha256(schema_path.read_bytes()).hexdigest() == expected_hash,
                 "task manifest schema hash mismatch: " + filename)
    for relative, expected_hash in manifest.get("execution_file_hashes", {}).items():
        execution_path = (PACKAGE_DIR / relative).resolve()
        _require(execution_path.is_relative_to(PACKAGE_DIR)
                 and execution_path.is_file()
                 and hashlib.sha256(execution_path.read_bytes()).hexdigest() == expected_hash,
                 "task manifest execution source hash mismatch: " + relative)
    pair_path = manifest_path.parent / manifest["pair_inputs_path"]
    _require(pair_path.is_file()
             and hashlib.sha256(pair_path.read_bytes()).hexdigest() == manifest["pair_inputs_sha256"],
             "paired method input does not match the task manifest")
    for attempt_field, resource_field in (
            ("cpu_quota_millis", "cpu_quota_millis"),
            ("wall_seconds_limit", "wall_seconds"),
            ("memory_limit_bytes", "memory_bytes"),
            ("pids_limit", "pids_limit"),
            ("max_method_output_bytes", "max_method_output_bytes")):
        _require(attempt.get(attempt_field) == resources[resource_field],
                 "attempt resource differs from task manifest: " + attempt_field)
    for field in MANIFEST_PIN_FIELDS:
        _require(attempt.get(field) == manifest.get(field),
                 "attempt pin differs from task manifest: " + field)
    _require(attempt.get("case_ids") == manifest.get("case_ids") == list(EXPECTED_CASES),
             "attempt case IDs differ from the reviewed plan")
    _require(attempt.get("method_order") == list(EXPECTED_METHODS),
             "attempt method order differs from the reviewed plan")
    return manifest, resources


def _validate_qualification(attempt, resources):
    evidence = attempt.get("qualification_evidence")
    _require(isinstance(evidence, dict) and set(evidence) == QUALIFICATION_FIELDS,
             "qualification evidence is missing or has unknown fields")
    _require(validate_qualification_evidence(evidence, resources),
             "qualification evidence is incomplete, unverified, or profile-mismatched")
    observed = evidence.get("observed", {})
    diagnostic = observed.get("diagnostic_container", {})
    oom = observed.get("oom_container", {})
    for label, container in (("diagnostic", diagnostic), ("OOM", oom)):
        expected_fields = {"container_id", "config_valid", "return_code", "state",
                           "removed", "absent_after_cleanup", "error", "cleanup_error"}
        if label == "OOM":
            expected_fields.add("overlimit_marker_seen")
        _require(isinstance(container, dict) and set(container) == expected_fields,
                 "qualification " + label + " container evidence has unknown/missing fields")
        _require(isinstance(container.get("container_id"), str)
                 and container.get("container_id"),
                 "qualification " + label + " container ID is missing")
        _require(container.get("config_valid") is True
                 and container.get("removed") is True
                 and container.get("absent_after_cleanup") is True
                 and container.get("error") is None
                 and container.get("cleanup_error") is None,
                 "qualification " + label + " container cleanup/config evidence is invalid")
    diagnostic_state = diagnostic.get("state")
    oom_state = oom.get("state")
    _require(isinstance(diagnostic_state, dict)
             and diagnostic_state.get("ExitCode") == 0
             and diagnostic_state.get("OOMKilled") is False
             and diagnostic_state.get("Running") is False
             and diagnostic_state.get("Status") == "exited"
             and diagnostic.get("return_code") == 0,
             "qualification diagnostic container did not pass")
    _require(isinstance(oom_state, dict)
             and oom_state.get("ExitCode") == 137
             and oom_state.get("OOMKilled") is True
             and oom_state.get("Running") is False
             and oom_state.get("Status") == "exited"
             and oom.get("return_code") in (1, 137)
             and oom.get("overlimit_marker_seen") is True,
             "qualification memory over-limit kill was not confirmed")


def _validate_scalar_schema(attempt):
    missing = [key for key in ATTEMPT_REQUIRED if key not in attempt]
    _require(not missing, "attempt receipt is missing schema fields: " + ", ".join(missing))
    for field in ("schema_version", "attempt_count", "planned_method_invocations",
                  "method_start_requests", "method_invocations_started",
                  "completed_method_invocations", "terminal_exit_code", "cpu_quota_millis",
                  "wall_seconds_limit", "container_cleanup_reserve_seconds",
                  "memory_limit_bytes", "pids_limit", "max_method_output_bytes",
                  "method_output_bytes_captured", "method_output_bytes_observed"):
        _require(_is_int(attempt.get(field)),
                 "attempt field must be a non-boolean integer: " + field)
    for field in ("wall_seconds_elapsed",):
        value = attempt.get(field)
        _require(isinstance(value, (int, float)) and not isinstance(value, bool)
                 and math.isfinite(value) and value >= 0,
                 "attempt field must be a finite nonnegative number: " + field)
    _require(attempt["schema_version"] == 1 and attempt["attempt_count"] == 1,
             "attempt schema version/count is invalid")
    _require(attempt["planned_method_invocations"] == 80,
             "planned method invocation count differs from the reviewed plan")
    _require(attempt["cpu_quota_millis"] == 1000
             and attempt["container_cleanup_reserve_seconds"] == 9,
             "attempt CPU or cleanup reserve differs from the reviewed plan")
    _require(attempt["method_start_requests"] <= 80
             and attempt["method_invocations_started"] <= attempt["method_start_requests"]
             and attempt["completed_method_invocations"] <= attempt["method_invocations_started"],
             "attempt execution counts are inconsistent")
    _require(attempt["method_output_bytes_captured"] <= attempt["max_method_output_bytes"]
             and attempt["method_output_bytes_observed"] >= attempt["method_output_bytes_captured"],
             "attempt output byte counters are inconsistent")
    _require(attempt.get("research_acceptance") == "NOT_EVALUATED",
             "execution receipt must preserve research acceptance as NOT_EVALUATED")
    _require(attempt.get("wall_seconds_scope") == "sandbox_lifecycle_through_image_cleanup",
             "attempt wall-time scope is invalid")
    _require(_is_datetime(attempt.get("started_at_utc"))
             and _is_datetime(attempt.get("finished_at_utc")),
             "attempt start/finish time evidence is invalid")
    _require(attempt.get("run_id") and isinstance(attempt.get("run_id"), str)
             and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", attempt["run_id"])
             and ".." not in attempt["run_id"], "attempt run ID is invalid")
    for field in HASH_FIELDS:
        _require(isinstance(attempt.get(field), str) and HASH_RE.fullmatch(attempt[field]),
                 "attempt SHA-256 field is invalid: " + field)
    _require(isinstance(attempt.get("source_commits"), dict)
             and isinstance(attempt.get("schema_hashes"), dict),
             "attempt source/schema pins must be objects")
    _require(all(isinstance(value, str) and HASH_RE.fullmatch(value)
                 for value in attempt["schema_hashes"].values()),
             "attempt schema pin is not a SHA-256 value")
    _require(isinstance(attempt.get("execution_environment"), dict)
             and isinstance(attempt.get("command"), list)
             and all(isinstance(value, str) for value in attempt["command"]),
             "attempt execution environment or command is malformed")
    for field in ("peak_rss_bytes", "cpu_usage_seconds"):
        value = attempt.get(field)
        _require(value == "UNKNOWN" or
                 (_is_int(value) if field == "peak_rss_bytes" else
                  isinstance(value, (int, float)) and not isinstance(value, bool)
                  and math.isfinite(value) and value >= 0),
                 "attempt resource usage field is invalid: " + field)


def _planned_slot(slot_number, case_ids):
    per_case = 20
    case_index = (slot_number - 1) // per_case
    within_case = (slot_number - 1) % per_case
    prefix = within_case // 4 + 1
    method = EXPECTED_METHODS[within_case % 4]
    return case_ids[case_index], prefix, method


def _validate_execution_records(attempt, slots, resources):
    status = attempt["task_status"]
    _require(status in ("PASS", "FAIL", "BLOCKED"), "attempt task status is invalid")
    records = attempt.get("slot_exit_records")
    _require(isinstance(records, list) and len(records) <= 80,
             "slot exit records must be an array of at most 80 entries")
    unknown_slots = attempt.get("method_start_unknown_slots")
    _require(isinstance(unknown_slots, list), "unknown-start evidence must be an array")
    _require(attempt.get("sandbox_image_cleanup") in ("REMOVED", "FAILED"),
             "sandbox image cleanup state is invalid")
    if status == "PASS":
        _require(attempt.get("terminal_exit_code") == 0 and attempt.get("partial") is False
                 and attempt.get("stop_reason") is None,
                 "PASS status/exit/partial/stop fields are inconsistent")
        _require(attempt["method_start_requests"] == 80
                 and attempt["method_invocations_started"] == 80
                 and attempt["completed_method_invocations"] == 80
                 and len(slots) == 80 and len(records) == 80,
                 "PASS requires 80 actual, completed, recorded slots")
        _require(attempt["wall_seconds_elapsed"] <= resources["wall_seconds"],
                 "PASS wall time exceeds its registered limit")
        _require(attempt["method_output_bytes_observed"]
                 == attempt["method_output_bytes_captured"]
                 and attempt["method_output_bytes_observed"]
                 <= attempt["max_method_output_bytes"],
                 "PASS output byte counters exceed or disagree with the cap")
        _require(attempt.get("sandbox_image_cleanup") == "REMOVED",
                 "PASS requires confirmed sandbox image cleanup")
        _require(not unknown_slots, "PASS cannot contain unknown method starts")
    else:
        expected_exit = 20 if status == "BLOCKED" else 30
        _require(attempt.get("terminal_exit_code") == expected_exit
                 and attempt.get("partial") is True
                 and isinstance(attempt.get("stop_reason"), str)
                 and attempt.get("stop_reason"),
                 "partial status/exit/stop fields are inconsistent")

    starts = 0
    requests = 0
    observed_output_bytes = 0
    unknown = []
    referenced_logs = set()
    record_slot_keys = []
    for index, record in enumerate(records, 1):
        _require(isinstance(record, dict), "slot exit record must be an object")
        _require(set(record) == SLOT_EXIT_FIELDS,
                 "slot exit record has missing or unknown schema fields")
        expected = _planned_slot(index, attempt["case_ids"])
        slot_number = record.get("slot")
        _require(_is_int(slot_number, 1) and slot_number == index,
                 "slot exit records must be a sequential prefix")
        key = (record.get("case_id"), record.get("prefix"), record.get("method"))
        _require(_is_int(record.get("prefix"), 1)
                 and key == expected, "slot exit record does not match the frozen plan")
        record_slot_keys.append(key)
        _require(record.get("status") in ("PASS", "FAIL", "BLOCKED"),
                 "slot exit status is unknown")
        for field in ("started", "start_requested", "start_unknown", "oom_killed"):
            _require(isinstance(record.get(field), bool),
                     "slot exit flag must be boolean: " + field)
        _require(not record["started"] or record["start_requested"],
                 "a confirmed start must have a start request")
        _require(not record["start_unknown"] or record["start_requested"],
                 "an unknown start must have a start request")
        _require(not (record["started"] and record["start_unknown"]),
                 "slot cannot be both started and start-unknown")
        if record["start_requested"]:
            requests += 1
        if record["started"]:
            starts += 1
        if record["start_unknown"]:
            unknown.append({"slot": slot_number, "case_id": key[0],
                            "prefix": key[1], "method": key[2]})
        for field in ("cli_exit_code", "container_exit_code"):
            value = record.get(field)
            _require(value is None or _is_int(value),
                     "slot exit code must be null or a non-boolean integer: " + field)
        _require(record.get("container_cleanup_status") in (None, "REMOVED", "FAILED"),
                 "slot cleanup state is unknown")
        _require(record.get("error") is None or isinstance(record.get("error"), str),
                 "slot error evidence is malformed")
        output_observed = record.get("output_bytes_observed", 0)
        _require(_is_int(output_observed), "slot output byte count is invalid")
        observed_output_bytes += output_observed
        container_id = record.get("container_id")
        _require(container_id is None or isinstance(container_id, str),
                 "slot container ID is malformed")
        if record["started"]:
            _require(container_id, "confirmed slot start is missing a container ID")
            _require(record.get("container_cleanup_status") in ("REMOVED", "FAILED"),
                     "confirmed slot start is missing cleanup evidence")
        if record["start_requested"]:
            _require(isinstance(container_id, str) and container_id,
                     "requested slot start is missing a container ID")
            _require(record.get("container_cleanup_status") in ("REMOVED", "FAILED"),
                     "requested slot start is missing cleanup evidence")
            expected_stdout = "slot-" + format(slot_number, "04d") + ".stdout.bin"
            expected_stderr = "slot-" + format(slot_number, "04d") + ".stderr.bin"
            _require(record.get("stdout_path") == expected_stdout
                     and record.get("stderr_path") == expected_stderr,
                     "start request is missing its stdout/stderr artifact paths")
            referenced_logs.update((expected_stdout, expected_stderr))
        else:
            _require(record.get("stdout_path") is None and record.get("stderr_path") is None,
                     "slot without a start request cannot claim log files")
        if record.get("status") == "PASS":
            _require(record.get("status") == "PASS" and record["started"] is True
                     and record["start_requested"] is True
                     and record["start_unknown"] is False
                     and record.get("cli_exit_code") == 0
                     and record.get("container_exit_code") == 0
                     and record.get("oom_killed") is False
                     and record.get("container_cleanup_status") == "REMOVED"
                     and record.get("error") is None,
                     "PASS child record contains a failed, unknown, or unclean slot")
        if status == "PASS":
            _require(record.get("status") == "PASS",
                     "complete PASS contains a non-PASS child slot")
    _require(requests == attempt["method_start_requests"]
             and starts == attempt["method_invocations_started"],
             "attempt execution counts do not match slot evidence")
    _require(observed_output_bytes == attempt["method_output_bytes_observed"],
             "attempt observed output bytes do not match per-slot evidence")
    _require(unknown_slots == unknown,
             "unknown-start summary does not match slot exit records")
    _require(len(slots) == attempt["completed_method_invocations"],
             "completed slot count does not match frozen output rows")
    for index, slot in enumerate(slots, 1):
        _require(index <= len(record_slot_keys)
                 and record_slot_keys[index - 1] ==
                 (slot.get("case_id"), slot.get("prefix"), slot.get("method")),
                 "frozen output slot has no matching execution record")
    return referenced_logs


def _validate_artifacts(bundle_dir, attempt, referenced_logs, score_path):
    root = Path(bundle_dir).resolve()
    entries = list(root.iterdir())
    _require(all(not path.is_symlink() for path in entries),
             "bundle contains a symlink")
    _require(all(path.is_file() for path in entries),
             "bundle contains a non-file artifact")
    artifacts = attempt.get("artifacts")
    _require(isinstance(artifacts, list), "attempt artifacts must be an array")
    artifact_records = {}
    for artifact in artifacts:
        _require(isinstance(artifact, dict), "artifact record must be an object")
        _require(set(artifact) == ARTIFACT_FIELDS,
                 "artifact record has missing or unknown schema fields")
        path_name = artifact.get("path")
        _require(isinstance(path_name, str) and SAFE_FILE_RE.fullmatch(path_name)
                 and Path(path_name).name == path_name,
                 "artifact path must be a safe direct child filename")
        _require(path_name not in artifact_records,
                 "attempt contains a duplicate artifact path")
        _require(_is_int(artifact.get("bytes")) and isinstance(artifact.get("sha256"), str)
                 and HASH_RE.fullmatch(artifact["sha256"]),
                 "artifact size or SHA-256 is invalid")
        artifact_path = root / path_name
        _require(artifact_path.is_file() and not artifact_path.is_symlink(),
                 "declared artifact is missing or is not a regular file: " + path_name)
        try:
            raw = artifact_path.read_bytes()
        except OSError as error:
            raise ReturnValidationError("declared artifact cannot be read: " + path_name) from error
        _require(len(raw) == artifact["bytes"]
                 and hashlib.sha256(raw).hexdigest() == artifact["sha256"],
                 "declared artifact bytes/SHA-256 mismatch: " + path_name)
        artifact_records[path_name] = artifact
    _require(referenced_logs <= set(artifact_records),
             "started slot log is missing from the declared artifact set")
    log_bytes = sum(artifact_records[name]["bytes"] for name in referenced_logs)
    _require(log_bytes == attempt["method_output_bytes_captured"],
             "captured output byte count differs from stdout/stderr artifacts")
    reserved = {"attempt.json", "OUTPUT_FREEZE.json", attempt["output_file"]}
    expected = set(artifact_records) | reserved
    score_file = None
    if score_path is not None:
        candidate = Path(score_path).resolve()
        if candidate.parent == root:
            _require(candidate.name == "score.json", "in-bundle score path must be score.json")
            score_file = "score.json"
            expected.add(score_file)
    actual = {path.name for path in entries}
    _require(actual == expected,
             "bundle file set differs from declared artifacts and reserved receipts")
    intent_path = root / "intent.json"
    try:
        intent = json.loads(intent_path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReturnValidationError("single-attempt intent is unreadable") from error
    _require(isinstance(intent, dict)
             and set(intent) == {"task_id", "run_id", "attempt_count", "state",
                                 "manifest_sha256", "started_at_utc", "sandbox_image_id",
                                 "qualification_evidence"}
             and intent.get("task_id") == attempt.get("task_id")
             and intent.get("run_id") == attempt.get("run_id")
             and type(intent.get("attempt_count")) is int
             and intent.get("attempt_count") == 1
             and intent.get("state") == "IN_PROGRESS"
             and intent.get("manifest_sha256") == attempt.get("task_manifest_sha256")
             and _is_datetime(intent.get("started_at_utc"))
             and intent.get("sandbox_image_id") ==
             attempt.get("qualification_evidence", {}).get("image_id")
             and intent.get("qualification_evidence") == attempt.get("qualification_evidence"),
             "single-attempt intent does not bind the verified qualification evidence")
    return artifact_records


def _validate_frozen_slots(bundle_dir, verified, manifest, manifest_path):
    pair_path = Path(manifest_path).resolve().parent / manifest["pair_inputs_path"]
    try:
        pair_bytes = pair_path.read_bytes()
        pair_inputs = json.loads(pair_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReturnValidationError("paired method input is unreadable JSON") from error
    _require(hashlib.sha256(pair_bytes).hexdigest() == manifest["pair_inputs_sha256"],
             "paired method input SHA-256 mismatch")
    cases = pair_inputs.get("cases") if isinstance(pair_inputs, dict) else None
    _require(isinstance(cases, list)
             and all(isinstance(case, dict) for case in cases)
             and [case.get("case_id") for case in cases] == manifest["case_ids"]
             and all(isinstance(case.get("rows"), list) and len(case["rows"]) == 5
                     for case in cases),
             "paired method input cases do not match the task manifest")
    public_path = PACKAGE_DIR / "frozen_source" / "public-input.json"
    try:
        public_bytes = public_path.read_bytes()
        public_input = json.loads(public_bytes)
        expected_pairs = build_pair_cases(public_input, manifest["opaque_case_ids"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise ReturnValidationError("pinned public input cannot reconstruct paired cases") from error
    _require(hashlib.sha256(public_bytes).hexdigest() == manifest["public_input_sha256"]
             and pair_bytes == canonical_json_bytes(expected_pairs) + b"\n",
             "paired method input is not the frozen A/B/C/D transformation")
    rows_by_case = {case["case_id"]: case["rows"] for case in cases}
    attempt = verified.attempt
    records_by_key = {
        (record["case_id"], record["prefix"], record["method"]): record
        for record in attempt["slot_exit_records"]
    }
    previous = {(case_id, method): {} for case_id in manifest["case_ids"]
                for method in manifest["method_order"]}
    for slot in verified.slots:
        case_id = slot["case_id"]
        prefix = slot["prefix"]
        method = slot["method"]
        visible = rows_by_case[case_id][:prefix]
        payload = {"method": method, "prefix": visible,
                   "old": previous[(case_id, method)]}
        _require(hashlib.sha256(canonical_bytes(payload)).hexdigest()
                 == slot["input_sha256"], "frozen method-visible input hash mismatch")
        result = slot.get("result")
        expected_ids = {row["id"] for row in visible if row.get("alarm") is True}
        try:
            validate_result(result, expected_ids)
            result_bytes = canonical_bytes(result)
        except (ResultContractError, ValueError, TypeError) as error:
            raise ReturnValidationError("frozen method result violates the result contract") from error
        _require(hashlib.sha256(result_bytes).hexdigest() == slot["output_sha256"],
                 "frozen method output hash mismatch")
        record = records_by_key.get((case_id, prefix, method))
        _require(isinstance(record, dict) and record.get("start_requested") is True,
                 "frozen method output has no requested child execution")
        stdout_path = Path(bundle_dir).resolve() / record["stdout_path"]
        try:
            stdout_result = json.loads(stdout_path.read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ReturnValidationError("frozen method stdout is missing or invalid JSON") from error
        _require(canonical_bytes(stdout_result) == result_bytes,
                 "frozen output differs from the captured child stdout")
        previous[(case_id, method)] = {
            key: result[key] for key in ("cards", "risk", "priority")
        }


def validate_return(bundle_dir, score_path=None, task_manifest_path=None,
                    oracle_path=None, oracle_case_map_path=None):
    try:
        verified = verify_frozen_bundle(bundle_dir, require_complete=False)
    except BundleError as error:
        raise ReturnValidationError(str(error)) from error
    except Exception as error:
        raise ReturnValidationError("frozen bundle structure is invalid: "
                                    + type(error).__name__ + ": " + str(error)) from error
    attempt = verified.attempt
    _require(isinstance(attempt, dict), "attempt receipt must be a JSON object")
    _validate_scalar_schema(attempt)
    manifest_path = Path(task_manifest_path or PACKAGE_DIR / "TASK_MANIFEST.json")
    manifest, resources = _load_manifest(manifest_path, attempt)
    _validate_qualification(attempt, resources)
    status = attempt["task_status"]
    referenced_logs = _validate_execution_records(attempt, verified.slots, resources)
    _validate_artifacts(bundle_dir, attempt, referenced_logs, score_path)
    _validate_frozen_slots(bundle_dir, verified, manifest, manifest_path)

    score = None
    score_bytes = None
    if score_path is not None:
        try:
            score_bytes = Path(score_path).read_bytes()
            score = json.loads(score_bytes)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ReturnValidationError("score receipt is unreadable JSON") from error
        if not isinstance(score, dict):
            raise ReturnValidationError("score receipt must be a JSON object")
        if score.get("run_id") != attempt.get("run_id"):
            raise ReturnValidationError("score run ID does not match execution receipt")
        if score.get("task_id") != attempt.get("task_id"):
            raise ReturnValidationError("score task ID does not match execution receipt")

    if status == "PASS":
        if score is None:
            validation_status = "VALID_EXECUTION_SCORE_PENDING"
            acceptance = attempt["research_acceptance"]
        else:
            manifest = Path(manifest_path)
            oracle = Path(oracle_path or PACKAGE_DIR / "scorer_source" / "oracle.physical.json")
            case_map = Path(oracle_case_map_path or PACKAGE_DIR / "scorer_source" / "ORACLE_CASE_MAP.json")
            try:
                with tempfile.TemporaryDirectory(prefix="pcg-score-recompute-") as temp_dir:
                    expected_score = score_bundle(
                        bundle_dir, manifest, oracle, case_map,
                        Path(temp_dir) / "recomputed-score.json",
                    )
            except Exception as error:
                raise ReturnValidationError(
                    "complete score could not be recomputed from the frozen bundle: "
                    + type(error).__name__ + ": " + str(error)
                ) from error
            if score_bytes != canonical_bytes(expected_score) + b"\n":
                raise ReturnValidationError(
                    "score receipt bytes differ from the deterministic scorer output"
                )
            validation_status = "VALID_COMPLETE_RETURN"
            acceptance = score["research_acceptance"]
    else:
        if score is not None:
            raise ReturnValidationError("partial execution must not receive research scoring")
        if attempt.get("research_acceptance") != "NOT_EVALUATED":
            raise ReturnValidationError("partial execution acceptance must be NOT_EVALUATED")
        validation_status = "VALID_PARTIAL_EXECUTION"
        acceptance = "NOT_EVALUATED"

    return {
        "validation_status": validation_status,
        "run_id": attempt["run_id"],
        "task_status": status,
        "research_acceptance": acceptance,
        "planned_method_invocations": attempt["planned_method_invocations"],
        "method_start_requests": attempt["method_start_requests"],
        "method_invocations_started": attempt["method_invocations_started"],
        "completed_method_invocations": attempt["completed_method_invocations"],
        "partial": attempt["partial"],
        "stop_reason": attempt["stop_reason"],
        "output_sha256": attempt["output_sha256"],
    }


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--score")
    parser.add_argument("--task-manifest", default=str(PACKAGE_DIR / "TASK_MANIFEST.json"))
    parser.add_argument("--oracle", default=str(PACKAGE_DIR / "scorer_source" / "oracle.physical.json"))
    parser.add_argument("--oracle-case-map", default=str(PACKAGE_DIR / "scorer_source" / "ORACLE_CASE_MAP.json"))
    args = parser.parse_args(argv)
    report = validate_return(args.bundle, args.score, args.task_manifest,
                             args.oracle, args.oracle_case_map)
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
