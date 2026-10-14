import hashlib
import errno
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


PACKAGE = Path(__file__).resolve().parents[1]
CASE_IDS = [
    "38e02496822f1a85849b6a39f698e50d", "33fadeeedeed902bd0ab9dfae5420213",
    "42474559127419126b713096e9f4d3ee", "81050a121e028f59f1e6940d7c5eb477",
]
METHODS = ["M0", "M1", "M2", "M3"]
RESOURCES = {"cpu_quota_millis": 1000, "wall_seconds": 60,
             "memory_bytes": 268435456, "pids_limit": 16,
             "max_method_output_bytes": 65536}


def load_module(name):
    if name in sys.modules:
        return sys.modules[name]
    module_path = PACKAGE / (name + ".py")
    if not module_path.is_file():
        raise AssertionError("missing feature: " + name + " is not implemented")
    if str(PACKAGE) not in sys.path:
        sys.path.insert(0, str(PACKAGE))
    spec = importlib.util.spec_from_file_location("pcg_pair_" + name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[name] = module
    return module


def make_test_manifest(root):
    manifest = json.loads((PACKAGE / "TASK_MANIFEST.json").read_text())
    manifest["resource_profile_status"] = "PRE_REGISTERED"
    manifest["resources"] = dict(RESOURCES)
    for relative in manifest["execution_file_hashes"]:
        path = PACKAGE / relative
        manifest["execution_file_hashes"][relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    for filename in manifest["schema_hashes"]:
        path = PACKAGE / "schemas" / filename
        manifest["schema_hashes"][filename] = hashlib.sha256(path.read_bytes()).hexdigest()
    path = root / "synthetic-task-manifest.json"
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8") + b"\n"
    path.write_bytes(raw)
    (root / manifest["pair_inputs_path"]).write_bytes(
        (PACKAGE / manifest["pair_inputs_path"]).read_bytes())
    return path, manifest, hashlib.sha256(raw).hexdigest()


def qualification_evidence(runner, resources):
    image_id = "sha256:" + "a" * 64
    checks = {name: "PASS" for name in runner.QUALIFICATION_CHECKS}
    return {
        "schema_version": 1,
        "probe_id": runner.QUALIFICATION_PROBE_ID,
        "status": "VERIFIED",
        "script_sha256": runner._sha256((runner._QUALIFICATION_DIAGNOSTIC_PROGRAM
                                         + runner._QUALIFICATION_OOM_PROGRAM).encode()),
        "image_id": image_id,
        "completed_at_utc": "2026-10-14T00:00:00+00:00",
        "checks": checks,
        "observed": {
            "resources": dict(resources),
            "host_canary_baseline": {
                "effective_uid": 65534, "effective_gid": 65534,
                "readable": True, "sha256": "e" * 64,
                "errno": None, "reason": None,
            },
            "diagnostic_probes": {
                "host_file": {"readable": False, "errno": errno.ENOENT,
                              "reason": "PATH_NOT_VISIBLE", "sha256": None},
                "network": {
                    "positive_control": {"connected": True, "errno": 0,
                                         "reason": "CONNECTED"},
                    "external_control": {"connected": False,
                                         "errno": errno.ENETUNREACH,
                                         "reason": "NETWORK_UNREACHABLE"},
                },
            },
            "effective_resources": {
                "cpu_quota_millis": resources["cpu_quota_millis"],
                "memory_bytes": resources["memory_bytes"],
                "memory_swap_bytes": 0,
                "pids_limit": resources["pids_limit"],
            },
            "diagnostic_container": {
                "container_id": "synthetic-diagnostic", "config_valid": True,
                "return_code": 0, "state": {"ExitCode": 0, "OOMKilled": False,
                                              "Running": False, "Status": "exited"},
                "removed": True, "absent_after_cleanup": True,
                "error": None, "cleanup_error": None,
            },
            "oom_container": {
                "container_id": "synthetic-oom", "config_valid": True,
                "return_code": 137, "state": {"ExitCode": 137, "OOMKilled": True,
                                               "Running": False, "Status": "exited"},
                "removed": True, "absent_after_cleanup": True,
                "error": None, "cleanup_error": None, "overlimit_marker_seen": True,
            },
        },
    }


def result_for(cards):
    return {
        "cards": cards, "possible": [], "risk": "EXPOSURE", "priority": "REVIEW",
        "notify": False, "fused": {}, "independent_evidence": 0,
        "role": "event rules shared; DS motion fusion diagnostic only",
        "context_evidence": {"status": "ABSENT", "accepted": [], "rejected": []},
        "notification_reasons": [], "card_updates": [],
        "risk_state_update": None, "review_notification_reasons": [],
    }


def add_artifact_files(run_dir, record_count, start_requested_count,
                       run_id, manifest_sha, qualification, slot_rows):
    common = {}
    intent = {
        "task_id": "PCG-IDENTIFIABILITY-PAIRED-CPU-001",
        "run_id": run_id, "attempt_count": 1, "state": "IN_PROGRESS",
        "manifest_sha256": manifest_sha, "started_at_utc": "2026-10-14T00:00:00+00:00",
        "sandbox_image_id": qualification["image_id"],
        "qualification_evidence": qualification,
    }
    common["intent.json"] = json.dumps(intent, sort_keys=True,
                                       separators=(",", ":")).encode() + b"\n"
    for slot_number in range(1, record_count + 1):
        (run_dir / ("container-" + format(slot_number, "04d") + ".cid")).write_text(
            "synthetic-container-" + format(slot_number, "04d") + "\n")
    for slot_number in range(1, start_requested_count + 1):
        if slot_number <= len(slot_rows):
            slot = slot_rows[slot_number - 1]
            result = slot["result"]
            stdout = json.dumps(result, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False).encode() + b"\n"
        else:
            stdout = b""
        common["slot-" + format(slot_number, "04d") + ".stdout.bin"] = stdout
        common["slot-" + format(slot_number, "04d") + ".stderr.bin"] = b""
    output_bytes_captured = sum(
        len(raw) for name, raw in common.items()
        if name.endswith(".stdout.bin") or name.endswith(".stderr.bin"))
    terminal_progress = {
        "run_id": run_id,
        "state": "PASS" if record_count == 80 else "FAIL",
        "method_start_requests": start_requested_count,
        "method_invocations_started": start_requested_count,
        "completed_method_invocations": len(slot_rows),
        "planned_method_invocations": 80,
        "stop_reason": None if record_count == 80 else "synthetic partial",
        "sandbox_image_cleanup": "REMOVED",
        "output_bytes_captured": output_bytes_captured,
    }
    events = []
    for slot_number in range(1, start_requested_count + 1):
        if slot_number <= len(slot_rows):
            slot = slot_rows[slot_number - 1]
            case_id, prefix, method = slot["case_id"], slot["prefix"], slot["method"]
        else:
            case_index = (slot_number - 1) // 20
            within_case = (slot_number - 1) % 20
            case_id = CASE_IDS[case_index]
            prefix = within_case // 4 + 1
            method = METHODS[within_case % 4]
        key = {
            "slot": slot_number,
            "case_id": case_id,
            "prefix": prefix,
            "method": method,
            "container_id": "synthetic-container-" + format(slot_number, "04d"),
        }
        config = {
            "host_config": {
                "NanoCpus": RESOURCES["cpu_quota_millis"] * 1_000_000,
                "Memory": RESOURCES["memory_bytes"],
                "MemorySwap": RESOURCES["memory_bytes"],
                "PidsLimit": RESOURCES["pids_limit"],
                "NetworkMode": "none", "ReadonlyRootfs": True,
                "Privileged": False,
            },
            "container_config": {"User": "65534:65534",
                                 "WorkingDir": "/task/source"},
        }
        config_hash = hashlib.sha256(json.dumps(
            config, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        rows = (
            {"event": "CONTAINER_CREATED", **key,
             "create_argv": ["docker", "create", "synthetic"]},
            {"event": "CONTAINER_CONFIG_INSPECTED", **key, "validated": True,
             "issues": [], "configuration": config,
             "configuration_sha256": config_hash},
            {"event": "METHOD_START_REQUESTED", **key},
            {"event": "METHOD_PROCESS_FINISHED", **key, "started": True,
             "started_at": "2026-10-14T00:00:01+00:00",
             "container_exit_code": 0, "cli_exit_code": 0,
             "oom_killed": False, "stop_reason": None},
        )
        for event in rows:
            event["event_at_utc"] = "2026-10-14T00:00:01+00:00"
            events.append(json.dumps(event, sort_keys=True, separators=(",", ":")))
    common["slot-events.jsonl"] = ("\n".join(events) + "\n").encode()
    for name, raw in common.items():
        (run_dir / name).write_bytes(raw)
    load_module("runner")._write_progress(run_dir, terminal_progress)
    return [
        {"path": path.name, "bytes": len(path.read_bytes()),
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(run_dir.iterdir()) if path.is_file()
    ]


def bind_output_counts(records, artifacts):
    sizes = {artifact["path"]: artifact["bytes"] for artifact in artifacts}
    for record in records:
        if record["start_requested"]:
            record["output_bytes_observed"] = (
                sizes[record["stdout_path"]] + sizes[record["stderr_path"]])


def slot_record(number, case_id, prefix, method, *, status="PASS", exit_code=0,
                oom=False, cleanup="REMOVED", error=None, requested=True,
                started=True, unknown=False):
    return {
        "slot": number, "case_id": case_id, "prefix": prefix, "method": method,
        "status": status, "started": started, "start_requested": requested,
        "start_unknown": unknown,
        "container_id": "synthetic-container-" + format(number, "04d") if requested else None,
        "container_cleanup_status": cleanup if requested else None,
        "cli_exit_code": exit_code if requested and not unknown else None,
        "container_exit_code": exit_code if started and not unknown else None,
        "oom_killed": oom,
        "stdout_path": ("slot-" + format(number, "04d") + ".stdout.bin") if requested else None,
        "stderr_path": ("slot-" + format(number, "04d") + ".stderr.bin") if requested else None,
        "output_bytes_observed": 0,
        "error": error,
    }


def common_attempt(runner, manifest, manifest_sha, run_id, status,
                   requests, started, completed, stop_reason, slot_records,
                   unknown_slots, artifacts):
    qualification = qualification_evidence(runner, RESOURCES)
    return {
        "schema_version": 1,
        "task_id": manifest["task_id"],
        "run_id": run_id,
        "attempt_count": 1,
        "task_status": status,
        "terminal_exit_code": 0 if status == "PASS" else 30,
        "research_acceptance": "NOT_EVALUATED",
        "planned_method_invocations": 80,
        "method_start_requests": requests,
        "method_invocations_started": started,
        "completed_method_invocations": completed,
        "partial": status != "PASS",
        "stop_reason": stop_reason,
        "case_ids": manifest["case_ids"],
        "method_order": manifest["method_order"],
        "task_manifest_sha256": manifest_sha,
        "source_commits": manifest["source_commits"],
        "schema_hashes": manifest["schema_hashes"],
        "public_input_sha256": manifest["public_input_sha256"],
        "pair_inputs_sha256": manifest["pair_inputs_sha256"],
        "oracle_sha256": manifest["oracle_sha256"],
        "oracle_case_map_sha256": manifest["oracle_case_map_sha256"],
        "plan_sha256": manifest["plan_sha256"],
        "started_at_utc": "2026-10-14T00:00:00+00:00",
        "finished_at_utc": "2026-10-14T00:00:02+00:00",
        "wall_seconds_elapsed": 2,
        "wall_seconds_scope": "sandbox_lifecycle_through_image_cleanup",
        "cpu_quota_millis": RESOURCES["cpu_quota_millis"],
        "wall_seconds_limit": RESOURCES["wall_seconds"],
        "container_cleanup_reserve_seconds": 9,
        "memory_limit_bytes": RESOURCES["memory_bytes"],
        "pids_limit": RESOURCES["pids_limit"],
        "max_method_output_bytes": RESOURCES["max_method_output_bytes"],
        "method_output_bytes_captured": sum(
            artifact["bytes"] for artifact in artifacts
            if ".stdout.bin" in artifact["path"] or ".stderr.bin" in artifact["path"]),
        "method_output_bytes_observed": sum(
            artifact["bytes"] for artifact in artifacts
            if ".stdout.bin" in artifact["path"] or ".stderr.bin" in artifact["path"]),
        "peak_rss_bytes": "UNKNOWN",
        "cpu_usage_seconds": "UNKNOWN",
        "method_start_unknown_slots": unknown_slots,
        "slot_exit_records": slot_records,
        "sandbox_image_cleanup": "REMOVED",
        "qualification_evidence": qualification,
        "execution_environment": {
            "python_executable": "/synthetic/python3",
            "python_binary_sha256": "d" * 64,
            "python_version": "3.12.synthetic",
            "platform": "linux",
            "docker_server_version": "synthetic-docker",
            "docker_cgroup_version": "2",
            "docker_required_resource_capabilities": {
                "memory_limit": True, "swap_limit": True,
                "cpu_quota": True, "pids_limit": True,
            },
            "sandbox_image_id": qualification["image_id"],
            "sandbox_endpoint_type": "local_unix_socket",
        },
        "command": ["runner.py", "--task-manifest", "TASK_MANIFEST.json",
                    "--run-id", run_id, "--output-root", "/synthetic/returns"],
        "artifacts": artifacts,
    }


def complete_slots(bundle):
    manifest = json.loads((PACKAGE / "TASK_MANIFEST.json").read_text())
    pair_path = PACKAGE / manifest["pair_inputs_path"]
    pair_inputs = json.loads(pair_path.read_text())
    previous = {(case_id, method): {} for case_id in CASE_IDS for method in METHODS}
    slots = []
    for case in pair_inputs["cases"]:
        case_id = case["case_id"]
        for prefix in range(1, 6):
            visible = case["rows"][:prefix]
            cards = {row["id"]: "card-" + row["id"]
                     for row in visible if row.get("alarm") is True}
            for method in METHODS:
                result = result_for(cards)
                payload = {"method": method, "prefix": visible,
                           "old": previous[(case_id, method)]}
                slots.append({
                    "case_id": case_id, "prefix": prefix, "method": method,
                    "input_sha256": hashlib.sha256(bundle.canonical_bytes(payload)).hexdigest(),
                    "output_sha256": hashlib.sha256(bundle.canonical_bytes(result)).hexdigest(),
                    "result": result,
                })
                previous[(case_id, method)] = {
                    key: result[key] for key in ("cards", "risk", "priority")
                }
    return slots


class ReturnValidatorTests(unittest.TestCase):
    def test_partial_failure_is_valid_only_with_actual_counts_and_reason(self):
        bundle = load_module("bundle")
        runner = load_module("runner")
        validator = load_module("return_validator")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "run"
            run_dir.mkdir()
            manifest_path, manifest, manifest_sha = make_test_manifest(root)
            slot = complete_slots(bundle)[0]
            records = [
                slot_record(1, CASE_IDS[0], 1, "M0"),
                slot_record(2, CASE_IDS[0], 1, "M1", status="FAIL", exit_code=9,
                            error="synthetic_child_exit"),
            ]
            qualification = qualification_evidence(runner, RESOURCES)
            artifacts = add_artifact_files(run_dir, 2, 2, "synthetic-partial",
                                           manifest_sha, qualification, [slot])
            bind_output_counts(records, artifacts)
            attempt = common_attempt(runner, manifest, manifest_sha, "synthetic-partial",
                                     "FAIL", 2, 2, 1, "synthetic_child_exit", records, [], artifacts)
            bundle.freeze_bundle(run_dir, [slot], attempt)
            report = validator.validate_return(run_dir, task_manifest_path=manifest_path)
            self.assertEqual("VALID_PARTIAL_EXECUTION", report["validation_status"])
            self.assertEqual(1, report["completed_method_invocations"])
            self.assertEqual("NOT_EVALUATED", report["research_acceptance"])

    def test_complete_pass_requires_matching_score_and_strict_receipt(self):
        bundle = load_module("bundle")
        runner = load_module("runner")
        scorer = load_module("scorer")
        validator = load_module("return_validator")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "run"
            run_dir.mkdir()
            manifest_path, manifest, manifest_sha = make_test_manifest(root)
            slots = complete_slots(bundle)
            records = []
            number = 0
            for case_id in CASE_IDS:
                for prefix in range(1, 6):
                    for method in METHODS:
                        number += 1
                        records.append(slot_record(number, case_id, prefix, method))
            qualification = qualification_evidence(runner, RESOURCES)
            artifacts = add_artifact_files(run_dir, 80, 80, "synthetic-pass",
                                           manifest_sha, qualification, slots)
            bind_output_counts(records, artifacts)
            attempt = common_attempt(runner, manifest, manifest_sha, "synthetic-pass",
                                     "PASS", 80, 80, 80, None, records, [], artifacts)
            attempt["partial"] = False
            receipt = bundle.freeze_bundle(run_dir, slots, attempt)
            pending = validator.validate_return(
                run_dir, task_manifest_path=manifest_path)
            self.assertEqual("VALID_EXECUTION_SCORE_PENDING",
                             pending["validation_status"])
            score_path = root / "score.json"
            scorer.score_bundle(
                run_dir, manifest_path,
                PACKAGE / "scorer_source" / "oracle.physical.json",
                PACKAGE / "scorer_source" / "ORACLE_CASE_MAP.json",
                score_path,
            )
            valid = validator.validate_return(
                run_dir, score_path, manifest_path,
                PACKAGE / "scorer_source" / "oracle.physical.json",
                PACKAGE / "scorer_source" / "ORACLE_CASE_MAP.json",
            )
            self.assertEqual("VALID_COMPLETE_RETURN", valid["validation_status"])

            attempt_path = run_dir / "attempt.json"
            good_attempt = json.loads(attempt_path.read_text())
            files = {path.name: path.read_bytes() for path in run_dir.iterdir()}
            corruptions = {
                "boolean_attempt_count": lambda value: value.update(attempt_count=True),
                "boolean_terminal_exit": lambda value: value.update(terminal_exit_code=False),
                "missing_stdout_artifact": lambda value: value.update(artifacts=[{
                    "path": "missing.stdout.bin", "bytes": 9, "sha256": "c" * 64,
                }]),
                "child_exit_oom_and_failed_cleanup": lambda value: value.update(
                    slot_exit_records=[{
                        "slot": 1, "case_id": CASE_IDS[0], "prefix": 1, "method": "M0",
                        "status": "FAIL", "started": True, "start_requested": True,
                        "start_unknown": False, "container_id": "synthetic-container-0001",
                        "container_cleanup_status": "FAILED", "cli_exit_code": 9,
                        "container_exit_code": 9, "oom_killed": True,
                        "stdout_path": "slot-0001.stdout.bin", "stderr_path": "slot-0001.stderr.bin",
                        "output_bytes_observed": 0, "error": "synthetic OOM",
                    }]),
                "failed_image_cleanup": lambda value: value.update(sandbox_image_cleanup="FAILED"),
                "wall_time_over_limit": lambda value: value.update(wall_seconds_elapsed=61),
                "missing_memory_limit": lambda value: value.update(memory_limit_bytes=None),
                "unknown_start_state": lambda value: value.update(
                    method_start_unknown_slots=[{"slot": 1, "case_id": CASE_IDS[0],
                                                "prefix": 1, "method": "M0"}]),
                "artifact_hash_mismatch": lambda value: value.update(artifacts=[
                    {**value["artifacts"][0], "sha256": "0" * 64}]),
                "artifact_path_traversal": lambda value: value.update(artifacts=[
                    {**value["artifacts"][0], "path": "../private.bin"}]),
                "empty_execution_environment": lambda value: value.update(
                    execution_environment={}),
                "empty_command": lambda value: value.update(command=[]),
                "command_run_id_mismatch": lambda value: value.update(command=[
                    "runner.py", "--task-manifest", "TASK_MANIFEST.json",
                    "--run-id", "another-run", "--output-root", "/synthetic/returns"]),
            }
            for label, corrupt in corruptions.items():
                with self.subTest(corruption=label):
                    bad_attempt = json.loads(json.dumps(good_attempt))
                    corrupt(bad_attempt)
                    attempt_path.write_bytes(bundle.canonical_bytes(bad_attempt) + b"\n")
                    with self.assertRaises(validator.ReturnValidationError):
                        validator.validate_return(
                            run_dir, score_path, manifest_path,
                            PACKAGE / "scorer_source" / "oracle.physical.json",
                            PACKAGE / "scorer_source" / "ORACLE_CASE_MAP.json",
                        )
            attempt_path.write_bytes(bundle.canonical_bytes(good_attempt) + b"\n")

            for missing_name in (
                "progress.json", "slot-events.jsonl",
                "container-0001.cid", "container-0080.cid",
            ):
                with self.subTest(missing_observation=missing_name):
                    for path in run_dir.iterdir():
                        path.unlink()
                    for filename, raw in files.items():
                        (run_dir / filename).write_bytes(raw)
                    bad_attempt = json.loads(json.dumps(good_attempt))
                    (run_dir / missing_name).unlink()
                    bad_attempt["artifacts"] = [
                        item for item in bad_attempt["artifacts"]
                        if item["path"] != missing_name
                    ]
                    attempt_path.write_bytes(bundle.canonical_bytes(bad_attempt) + b"\n")
                    with self.assertRaisesRegex(
                        validator.ReturnValidationError,
                        "required observation artifact",
                    ):
                        validator.validate_return(
                            run_dir, score_path, manifest_path,
                            PACKAGE / "scorer_source" / "oracle.physical.json",
                            PACKAGE / "scorer_source" / "ORACLE_CASE_MAP.json",
                        )
            for path in run_dir.iterdir():
                path.unlink()
            for filename, raw in files.items():
                (run_dir / filename).write_bytes(raw)
            attempt_path.write_bytes(bundle.canonical_bytes(good_attempt) + b"\n")

            forged = json.loads(score_path.read_text())
            forged["first_alert_checks"].pop()
            score_path.write_text(json.dumps(forged))
            with self.assertRaisesRegex(validator.ReturnValidationError,
                                        "differ from the deterministic scorer"):
                validator.validate_return(
                    run_dir, score_path, manifest_path,
                    PACKAGE / "scorer_source" / "oracle.physical.json",
                    PACKAGE / "scorer_source" / "ORACLE_CASE_MAP.json",
                )


if __name__ == "__main__":
    unittest.main()
