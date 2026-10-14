from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from rfb.research.user_cpu_replay_handoff import (
    BASE_RUNNER_COMMIT,
    RUNNER_COMMAND,
    RESULT_SCHEMA_SHA256,
    SCORER_COMMAND,
    HandoffValidationError,
    validate_user_cpu_replay_bundle,
)
from rfb.research.user_cpu_replay_runner import execute_user_cpu_replay


# Synthetic validator fixtures wrap the already-frozen V2 output files. They
# do not invoke the runner/scorer or claim a new replay.
REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_RUN = (
    REPO_ROOT
    / "research-three/v2-alignment-20261011/runs/"
    "two-hop-lineage-controlled-synthetic-20261012-v2"
)
PASS_ARTIFACTS = (
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
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class UserCpuReplayHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.bundle_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_bundle(self, status: str = "PASS") -> dict:
        artifacts: list[dict[str, object]] = []
        for name in PASS_ARTIFACTS:
            source = SOURCE_RUN / name
            if name == "commands.txt":
                source_bytes = f"{RUNNER_COMMAND}\n{SCORER_COMMAND}\n".encode()
            elif name == "environment.json":
                source_bytes = json.dumps(
                    {
                        "python_version": "3.11.0",
                        "platform": "test-platform",
                        "cpu_count": 1,
                        "gpu_used": False,
                        "network_calls_after_checkout": False,
                        "model_called": False,
                        "notification_called": False,
                        "packages_installed_for_task": [],
                    },
                    sort_keys=True,
                    indent=2,
                ).encode() + b"\n"
            elif name == "stdout.log":
                source_bytes = b"runner and scorer completed\n"
            elif name == "stderr.log":
                source_bytes = b""
            else:
                source_bytes = source.read_bytes()
            if name == "RUNNER_CHECKS_V2.json":
                runner = json.loads(source_bytes)
                runner["pre_run_commit"] = BASE_RUNNER_COMMIT
                source_bytes = json.dumps(runner, ensure_ascii=False, indent=2).encode() + b"\n"
            (self.bundle_dir / name).write_bytes(source_bytes)
            artifacts.append({"path": name, "bytes": len(source_bytes), "sha256": sha256(source_bytes)})

        result = {
            "schema_version": "pcg.user_cpu_replay_result.v1",
            "task_id": "PCG-LINEAGE-CPU-REPLAY-001",
            "run_id": "user-cpu-replay-20261012T080000Z-test",
            "task_status": status,
            "target_runner_commit": BASE_RUNNER_COMMIT,
            "handoff_code_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
            ).strip(),
            "result_schema_sha256": RESULT_SCHEMA_SHA256,
            "observed_runner_commit": BASE_RUNNER_COMMIT,
            "execution": {
                "started_at_utc": "2026-10-12T08:00:00Z",
                "finished_at_utc": "2026-10-12T08:00:01Z",
                "python_version": "3.11.0",
                "platform": "test-platform",
                "cpu_count": 1,
                "gpu_used": False,
                "network_calls_after_checkout": False,
                "model_called": False,
                "notification_called": False,
                "packages_installed_for_task": [],
                "commands": [
                    RUNNER_COMMAND,
                    SCORER_COMMAND,
                ],
                "wall_time_seconds": 1.0,
                "peak_memory_mib": 16.0,
                "runner_exit_code": 0 if status == "PASS" else None,
                "scorer_exit_code": 0 if status == "PASS" else None,
            },
            "expected_input_pins": {
                "pre_run_manifest_sha256": sha256((SOURCE_RUN / "PRE_RUN_MANIFEST_V2.json").read_bytes()),
                "scorer_truth_manifest_sha256": sha256((SOURCE_RUN / "SCORER_TRUTH_MANIFEST_V2.json").read_bytes()),
                "source_sample_sha256": "9bfbd8a6600deb0c230fea2294f3673a2c726e5c8285687cb9531cd88a64d599",
                "source_sample_bytes": 2537,
            },
            "observed_input_pins": {
                "pre_run_manifest_sha256": sha256((SOURCE_RUN / "PRE_RUN_MANIFEST_V2.json").read_bytes()),
                "scorer_truth_manifest_sha256": sha256((SOURCE_RUN / "SCORER_TRUTH_MANIFEST_V2.json").read_bytes()),
                "source_sample_sha256": "9bfbd8a6600deb0c230fea2294f3673a2c726e5c8285687cb9531cd88a64d599",
                "source_sample_bytes": 2537,
            },
            "outcome": {
                "method_outputs_sha256": "15ee4c362160bfb1381da9a2e304f09224e73c265dc95fba949135d5694c66cb",
                "runner_checks_total": 16,
                "runner_checks_passed": 16,
                "full_receipt_chain": {"confirmed": 3, "unknown": 0},
                "missing_hop2_receipt": {"confirmed": 1, "unknown": 2},
                "hash_only": {"confirmed": 0, "unknown": 3},
                "side_input_receipt_status": "UNDECLARED_SIDE_INPUT",
                "side_input_lineage_status": "UNKNOWN",
                "production_truth_denominator": 0,
                "production_accuracy": "NOT_COMPUTABLE",
                "wrong_confirmed_attribution_status": "NOT_EVALUATED_NO_INDEPENDENT_PRODUCTION_TRUTH",
                "pair_rows_independent": False,
            },
            "failure_reasons": [] if status == "PASS" else ["test blocked before replay"],
            "artifacts": artifacts,
        }
        (self.bundle_dir / "TASK_RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
        return result

    def replace_runner_checks(self, checks: dict[str, object]) -> None:
        runner_path = self.bundle_dir / "RUNNER_CHECKS_V2.json"
        runner = json.loads(runner_path.read_text())
        runner["checks"] = checks
        runner_bytes = json.dumps(runner, ensure_ascii=False, indent=2).encode() + b"\n"
        runner_path.write_bytes(runner_bytes)

        result_path = self.bundle_dir / "TASK_RESULT.json"
        result = json.loads(result_path.read_text())
        for artifact in result["artifacts"]:
            if artifact["path"] == runner_path.name:
                artifact["bytes"] = len(runner_bytes)
                artifact["sha256"] = sha256(runner_bytes)
                break
        else:
            self.fail("RUNNER_CHECKS_V2.json missing from TASK_RESULT artifact manifest")
        result_path.write_text(json.dumps(result, indent=2) + "\n")

    def test_accepts_pass_bundle_with_frozen_mechanics_counts(self) -> None:
        self.write_bundle()

        report = validate_user_cpu_replay_bundle(self.bundle_dir, REPO_ROOT)

        self.assertTrue(report["bundle_valid"])
        self.assertEqual(report["task_status"], "PASS")
        self.assertEqual(report["checks_passed"], 16)

    def test_rejects_pass_bundle_with_null_observed_input_pins(self) -> None:
        result = self.write_bundle()
        result["observed_input_pins"] = None
        (self.bundle_dir / "TASK_RESULT.json").write_text(json.dumps(result, indent=2) + "\n")

        with self.assertRaisesRegex(HandoffValidationError, "PASS.*observed_input_pins"):
            validate_user_cpu_replay_bundle(self.bundle_dir, REPO_ROOT)

    def test_rejects_pass_bundle_with_arbitrary_sixteen_check_names(self) -> None:
        self.write_bundle()
        self.replace_runner_checks({f"alternate_check_{index:02d}": True for index in range(16)})

        with self.assertRaisesRegex(HandoffValidationError, "runner check names"):
            validate_user_cpu_replay_bundle(self.bundle_dir, REPO_ROOT)

    def test_rejects_pass_bundle_after_a_frozen_check_is_renamed(self) -> None:
        self.write_bundle()
        runner = json.loads((self.bundle_dir / "RUNNER_CHECKS_V2.json").read_text())
        checks = runner["checks"]
        checks["renamed_source_hash_check"] = checks.pop("source_hash_matches_frozen_input")
        self.replace_runner_checks(checks)

        with self.assertRaisesRegex(HandoffValidationError, "runner check names"):
            validate_user_cpu_replay_bundle(self.bundle_dir, REPO_ROOT)

    def test_rejects_missing_check_replaced_with_unfrozen_name(self) -> None:
        self.write_bundle()
        runner = json.loads((self.bundle_dir / "RUNNER_CHECKS_V2.json").read_text())
        checks = runner["checks"]
        checks.pop("all_frozen_expectations_passed")
        checks["unfrozen_replacement_check"] = True
        self.replace_runner_checks(checks)

        with self.assertRaisesRegex(HandoffValidationError, "runner check names"):
            validate_user_cpu_replay_bundle(self.bundle_dir, REPO_ROOT)

    def test_rejects_truthy_non_boolean_runner_check_value(self) -> None:
        self.write_bundle()
        runner = json.loads((self.bundle_dir / "RUNNER_CHECKS_V2.json").read_text())
        runner["checks"]["source_hash_matches_frozen_input"] = 1
        self.replace_runner_checks(runner["checks"])

        with self.assertRaisesRegex(HandoffValidationError, "runner check values"):
            validate_user_cpu_replay_bundle(self.bundle_dir, REPO_ROOT)

    def test_rejects_artifact_changed_after_manifest_was_written(self) -> None:
        self.write_bundle()
        (self.bundle_dir / "METHOD_OUTPUTS_V2.json").write_bytes(b"changed\n")

        with self.assertRaisesRegex(HandoffValidationError, "SHA-256 mismatch"):
            validate_user_cpu_replay_bundle(self.bundle_dir, REPO_ROOT)

    def test_rejects_parent_path_in_artifact_manifest(self) -> None:
        result = self.write_bundle()
        result["artifacts"][0]["path"] = "../METHOD_OUTPUTS_V2.json"
        (self.bundle_dir / "TASK_RESULT.json").write_text(json.dumps(result))

        with self.assertRaisesRegex(HandoffValidationError, "unsafe artifact path"):
            validate_user_cpu_replay_bundle(self.bundle_dir, REPO_ROOT)

    def test_rejects_fields_not_declared_by_result_schema(self) -> None:
        result = self.write_bundle()
        result["unreviewed_extension"] = {"status": "PASS"}
        (self.bundle_dir / "TASK_RESULT.json").write_text(json.dumps(result))

        with self.assertRaisesRegex(HandoffValidationError, "unexpected result fields"):
            validate_user_cpu_replay_bundle(self.bundle_dir, REPO_ROOT)

    def test_rejects_fields_not_declared_in_nested_execution_schema(self) -> None:
        result = self.write_bundle()
        result["execution"]["unreviewed_extension"] = True
        (self.bundle_dir / "TASK_RESULT.json").write_text(json.dumps(result))

        with self.assertRaisesRegex(HandoffValidationError, "unexpected execution fields"):
            validate_user_cpu_replay_bundle(self.bundle_dir, REPO_ROOT)

    def test_rejects_fields_not_declared_in_artifact_schema(self) -> None:
        result = self.write_bundle()
        result["artifacts"][0]["unreviewed_extension"] = "ignored"
        (self.bundle_dir / "TASK_RESULT.json").write_text(json.dumps(result))

        with self.assertRaisesRegex(HandoffValidationError, "unexpected artifact entry fields"):
            validate_user_cpu_replay_bundle(self.bundle_dir, REPO_ROOT)

    def test_rejects_passing_claim_if_hash_only_result_changes(self) -> None:
        self.write_bundle()
        scored_path = self.bundle_dir / "SCORED_RESULT_V2.json"
        scored = json.loads(scored_path.read_text())
        scored["conditions"]["HASH_ONLY_DEDUP"]["counts"]["confirmed_shared_ancestor"] = 1
        scored_path.write_text(json.dumps(scored, indent=2) + "\n")
        result_path = self.bundle_dir / "TASK_RESULT.json"
        result = json.loads(result_path.read_text())
        for item in result["artifacts"]:
            if item["path"] == "SCORED_RESULT_V2.json":
                content = scored_path.read_bytes()
                item["bytes"] = len(content)
                item["sha256"] = sha256(content)
        result_path.write_text(json.dumps(result, indent=2) + "\n")

        with self.assertRaisesRegex(HandoffValidationError, "hash-only"):
            validate_user_cpu_replay_bundle(self.bundle_dir, REPO_ROOT)

    def test_accepts_blocked_attempt_with_reason_and_logs(self) -> None:
        self.write_bundle("BLOCKED")
        result_path = self.bundle_dir / "TASK_RESULT.json"
        result = json.loads(result_path.read_text())
        result["observed_runner_commit"] = None
        result["observed_input_pins"] = None
        result["execution"]["runner_exit_code"] = None
        result["execution"]["scorer_exit_code"] = None
        result["outcome"] = None
        result["artifacts"] = [
            item
            for item in result["artifacts"]
            if item["path"] in {"commands.txt", "environment.json", "stdout.log", "stderr.log"}
        ]
        for name in set(PASS_ARTIFACTS) - {"commands.txt", "environment.json", "stdout.log", "stderr.log"}:
            (self.bundle_dir / name).unlink()
        result_path.write_text(json.dumps(result, indent=2) + "\n")

        report = validate_user_cpu_replay_bundle(self.bundle_dir, REPO_ROOT)

        self.assertTrue(report["bundle_valid"])
        self.assertEqual(report["task_status"], "BLOCKED")
        self.assertTrue(any("task outcome did not pass" in note for note in report["notes"]))

    def test_accepts_fail_result_and_preserves_over_limit_measurements(self) -> None:
        result = self.write_bundle("FAIL")
        result["execution"]["wall_time_seconds"] = 301.25
        result["execution"]["peak_memory_mib"] = 1025.5
        result["execution"]["runner_exit_code"] = 124
        result["execution"]["scorer_exit_code"] = None
        result["failure_reasons"] = ["runner exceeded the resource ceiling"]
        (self.bundle_dir / "TASK_RESULT.json").write_text(json.dumps(result, indent=2) + "\n")

        report = validate_user_cpu_replay_bundle(self.bundle_dir, REPO_ROOT)

        self.assertTrue(report["bundle_valid"])
        self.assertEqual(report["task_status"], "FAIL")
        self.assertEqual(result["execution"]["wall_time_seconds"], 301.25)
        self.assertEqual(result["execution"]["peak_memory_mib"], 1025.5)

    def test_rejects_pass_result_with_over_limit_measurement(self) -> None:
        result = self.write_bundle("PASS")
        result["execution"]["wall_time_seconds"] = 301
        (self.bundle_dir / "TASK_RESULT.json").write_text(json.dumps(result, indent=2) + "\n")

        with self.assertRaisesRegex(HandoffValidationError, "PASS.*ceiling|ceiling.*PASS"):
            validate_user_cpu_replay_bundle(self.bundle_dir, REPO_ROOT)

    def test_accepts_fail_bundle_that_preserves_a_mismatched_input_manifest(self) -> None:
        result = self.write_bundle("FAIL")
        manifest_path = self.bundle_dir / "PRE_RUN_MANIFEST_V2.json"
        mismatch_bytes = b'{"preserved_mismatch": true}\n'
        manifest_path.write_bytes(mismatch_bytes)
        for item in result["artifacts"]:
            if item["path"] == manifest_path.name:
                item["bytes"] = len(mismatch_bytes)
                item["sha256"] = sha256(mismatch_bytes)
        result["failure_reasons"] = ["pre-run manifest differed from its frozen pin"]
        (self.bundle_dir / "TASK_RESULT.json").write_text(json.dumps(result, indent=2) + "\n")

        report = validate_user_cpu_replay_bundle(self.bundle_dir, REPO_ROOT)

        self.assertTrue(report["bundle_valid"])
        self.assertEqual(report["task_status"], "FAIL")
        self.assertEqual(manifest_path.read_bytes(), mismatch_bytes)

    def test_result_generator_blocks_wrong_runner_commit_without_running_replay(self) -> None:
        runner_root = self.bundle_dir / "wrong-runner-checkout"
        runner_root.mkdir()
        generated_bundle = self.bundle_dir / "generated-blocked-bundle"
        calls: list[list[str]] = []

        def fake_process_runner(command: list[str], **kwargs):
            calls.append(command)
            if command[:3] == ["git", "rev-parse", "HEAD"]:
                return subprocess.CompletedProcess(command, 0, stdout="a" * 40, stderr="")
            if command[:2] == ["git", "status"]:
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            raise AssertionError(f"unexpected process invocation: {command}")

        result = execute_user_cpu_replay(
            runner_root=runner_root,
            bundle_dir=generated_bundle,
            run_id="user-cpu-replay-20261012T080000Z-blocked",
            handoff_root=REPO_ROOT,
            process_runner=fake_process_runner,
        )

        self.assertEqual(result["task_status"], "BLOCKED")
        self.assertTrue(all(command[:1] == ["git"] for command in calls))
        self.assertEqual(result["observed_runner_commit"], "a" * 40)
        report = validate_user_cpu_replay_bundle(generated_bundle, REPO_ROOT)
        self.assertTrue(report["bundle_valid"])
        self.assertEqual(report["task_status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
