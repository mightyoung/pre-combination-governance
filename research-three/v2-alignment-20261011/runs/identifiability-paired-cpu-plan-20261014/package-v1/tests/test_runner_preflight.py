import errno
import io
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock


PACKAGE = Path(__file__).resolve().parents[1]


def verified_qualification(runner, resources, image_id="sha256:" + "a" * 64):
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


def load_runner():
    module_path = PACKAGE / "runner.py"
    if not module_path.is_file():
        raise AssertionError("missing feature: fail-closed task runner is not implemented")
    if str(PACKAGE) not in sys.path:
        sys.path.insert(0, str(PACKAGE))
    spec = importlib.util.spec_from_file_location("pcg_pair_runner", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunnerPreflightTests(unittest.TestCase):
    def test_terminal_progress_records_captured_bytes_from_runner_producer(self):
        runner = load_runner()
        case_id = "42474559127419126b713096e9f4d3ee"
        resources = {"cpu_quota_millis": 1000, "wall_seconds": 60,
                    "memory_bytes": 268435456, "pids_limit": 16,
                    "max_method_output_bytes": 65536}

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "run"
            run_dir.mkdir()
            manifest = {
                "resources": resources,
                "case_ids": [case_id],
                "source_commits": {},
                "schema_hashes": {},
                "public_input_sha256": "a" * 64,
                "pair_inputs_sha256": "b" * 64,
                "oracle_sha256": "c" * 64,
                "oracle_case_map_sha256": "d" * 64,
                "plan_sha256": "e" * 64,
            }
            preflight = {
                "manifest": manifest,
                "manifest_sha256": "f" * 64,
                "package_dir": PACKAGE,
                "pair_inputs": {"cases": [{
                    "case_id": case_id,
                    "rows": [{"id": "row-" + str(index), "alarm": False}
                             for index in range(5)],
                }]},
                "sandbox_image_id": "sha256:" + "9" * 64,
                "qualification_evidence": {},
            }

            class FakeSession:
                image_cleanup_attempted = True
                info = {
                    "server_version": "synthetic-docker",
                    "cgroup_version": "2",
                    "required_resource_capabilities": {
                        "memory_limit": True, "swap_limit": True,
                        "cpu_quota": True, "pids_limit": True,
                    },
                }

            def fake_slot(session, slot_dir, run_id, slot_number, slot_case_id,
                          prefix, method, payload, visible_rows, slot_resources,
                          runtime_prefix, python_relative_path, source_dir,
                          library_dirs, output_budget, deadline, event_path):
                output_budget["captured"] += 7
                output_budget["observed"] += 9
                return {
                    "status": "PASS", "started": True,
                    "start_unknown": False, "start_requested": True,
                    "container_id": "synthetic-container-" + str(slot_number),
                    "container_cleanup_status": "REMOVED",
                    "cli_exit_code": 0,
                    "state": {"ExitCode": 0, "OOMKilled": False},
                    "stdout_path": "slot-" + format(slot_number, "04d") + ".stdout.bin",
                    "stderr_path": "slot-" + format(slot_number, "04d") + ".stderr.bin",
                    "output_bytes_observed": 9,
                    "error": None,
                    "result": {"cards": {}, "risk": "EXPOSURE", "priority": "REVIEW"},
                }

            def fake_freeze(run_path, slots, attempt):
                attempt["output_sha256"] = "1" * 64
                return attempt

            with mock.patch.object(runner, "PLANNED_SLOTS", 5), \
                    mock.patch.object(runner, "METHOD_ORDER", ["M0"]), \
                    mock.patch.object(runner, "_run_slot", side_effect=fake_slot), \
                    mock.patch.object(runner, "freeze_bundle", side_effect=fake_freeze):
                runner._execute_task(
                    preflight, "synthetic-terminal", root, run_dir, FakeSession(),
                    time.monotonic(), "2026-10-14T00:00:00+00:00",
                )

            terminal = json.loads((run_dir / "progress.json").read_text())
            self.assertEqual("PASS", terminal["state"])
            self.assertEqual(5, terminal["completed_method_invocations"])
            self.assertEqual(35, terminal.get("output_bytes_captured"))

    def run_mocked_diagnostic(self, runner, *, network_errno, canary_errno,
                              network_timeout=False):
        resources = {"cpu_quota_millis": 1000, "memory_bytes": 268435456,
                     "pids_limit": 16}
        canary_path = "/tmp/synthetic-canary"
        expected = {
            **resources,
            "host_file_baseline_readable": True,
            "host_file_sha256": "e" * 64,
        }
        cgroup = {
            "/sys/fs/cgroup/cpu.max": "100000 100000",
            "/sys/fs/cgroup/memory.max": str(resources["memory_bytes"]),
            "/sys/fs/cgroup/memory.swap.max": "0",
            "/sys/fs/cgroup/pids.max": str(resources["pids_limit"]),
        }

        def fake_open(path, *unused, **kwargs):
            path_text = str(path)
            if path_text in cgroup:
                return io.StringIO(cgroup[path_text])
            if path_text == canary_path:
                if canary_errno == errno.ENOENT:
                    raise FileNotFoundError(errno.ENOENT, "synthetic path absent")
                if canary_errno == errno.EACCES:
                    raise PermissionError(errno.EACCES, "synthetic DAC denial")
                return io.BytesIO(b"synthetic canary")
            raise AssertionError("unexpected fixed-probe open path: " + path_text)

        class FakeSocket:
            def __init__(self, kind):
                self.kind = kind

            def bind(self, address):
                self.address = address

            def listen(self, backlog):
                return None

            def getsockname(self):
                return ("127.0.0.1", 23456)

            def settimeout(self, timeout):
                return None

            def connect_ex(self, address):
                if address[0] == "127.0.0.1":
                    return 0
                if network_timeout:
                    raise TimeoutError("synthetic network timeout")
                return network_errno

            def accept(self):
                return (FakeSocket("accepted"), ("127.0.0.1", 23457))

            def close(self):
                return None

        created = []

        def fake_socket(*unused, **kwargs):
            item = FakeSocket(len(created))
            created.append(item)
            return item

        output = io.StringIO()
        code = None
        with mock.patch("builtins.open", side_effect=fake_open), \
                mock.patch("socket.socket", side_effect=fake_socket), \
                mock.patch.object(sys, "argv", ["probe", json.dumps(expected), canary_path]), \
                mock.patch.object(sys, "stdout", output):
            try:
                exec(compile(runner._QUALIFICATION_DIAGNOSTIC_PROGRAM,
                             "<synthetic-fixed-probe>", "exec"), {})
            except SystemExit as error:
                code = error.code
        return code, json.loads(output.getvalue())

    def test_fixed_diagnostic_requires_reachable_control_and_network_unreachable_errno(self):
        runner = load_runner()
        code, output = self.run_mocked_diagnostic(
            runner, network_errno=errno.ENETUNREACH, canary_errno=errno.ENOENT)
        self.assertEqual(0, code)
        self.assertTrue(output["checks"]["network_positive_control"])
        self.assertTrue(output["checks"]["network_unavailable"])
        self.assertEqual("CONNECTED", output["probes"]["network"]["positive_control"]["reason"])
        self.assertEqual("NETWORK_UNREACHABLE", output["probes"]["network"]["external_control"]["reason"])

        refused_code, refused = self.run_mocked_diagnostic(
            runner, network_errno=errno.ECONNREFUSED, canary_errno=errno.ENOENT)
        self.assertNotEqual(0, refused_code)
        self.assertTrue(refused["checks"]["network_positive_control"])
        self.assertFalse(refused["checks"]["network_unavailable"])
        self.assertEqual("CONNECTION_REFUSED", refused["probes"]["network"]["external_control"]["reason"])

        timeout_code, timeout = self.run_mocked_diagnostic(
            runner, network_errno=errno.ETIMEDOUT, canary_errno=errno.ENOENT,
            network_timeout=True)
        self.assertNotEqual(0, timeout_code)
        self.assertFalse(timeout["checks"]["network_unavailable"])
        self.assertEqual("TIMEOUT", timeout["probes"]["network"]["external_control"]["reason"])

    def test_canary_dac_denial_is_distinct_from_path_isolation(self):
        runner = load_runner()
        code, output = self.run_mocked_diagnostic(
            runner, network_errno=errno.ENETUNREACH, canary_errno=errno.EACCES)
        self.assertNotEqual(0, code)
        self.assertFalse(output["checks"]["host_file_unreadable"])
        self.assertEqual("DAC_PERMISSION_DENIED", output["probes"]["host_file"]["reason"])
        self.assertEqual(errno.EACCES, output["probes"]["host_file"]["errno"])

    def test_canary_baseline_requires_same_probe_identity_without_chmod(self):
        runner = load_runner()
        with tempfile.TemporaryDirectory() as temp:
            canary = Path(temp) / "host-canary"
            canary.write_bytes(b"synthetic host canary")
            before_mode = canary.stat().st_mode
            with mock.patch.object(runner.os, "geteuid", return_value=65534), \
                    mock.patch.object(runner.os, "getegid", return_value=65534):
                baseline = runner._host_canary_baseline(canary, b"synthetic host canary")
            self.assertTrue(baseline["readable"])
            self.assertEqual(runner._sha256(b"synthetic host canary"), baseline["sha256"])
            self.assertIsNone(baseline["reason"])
            with mock.patch.object(runner.os, "geteuid", return_value=1234), \
                    mock.patch.object(runner.os, "getegid", return_value=1234):
                baseline = runner._host_canary_baseline(canary, b"synthetic host canary")
            self.assertFalse(baseline["readable"])
            self.assertEqual("HOST_IDENTITY_MISMATCH", baseline["reason"])
            self.assertEqual(before_mode, canary.stat().st_mode)

    def test_qualification_identity_mismatch_fails_before_any_container_call(self):
        runner = load_runner()
        resources = {"cpu_quota_millis": 1000,
                     "memory_bytes": 268435456, "pids_limit": 16}
        synthetic_failure = {
            "container_id": "synthetic-container-id", "config_valid": False,
            "return_code": None, "stdout": b"", "stderr": b"",
            "state": None, "removed": False, "absent_after_cleanup": False,
            "error": "synthetic failure", "cleanup_error": None,
        }

        class FakeSession:
            image_id = "sha256:" + "a" * 64
            image_tag = "synthetic-image"
            deadline = None
            info = {"memory_bytes": 512 * 1024 * 1024}

        for effective_uid, effective_gid in ((1234, 65534), (65534, 1234)):
            with self.subTest(effective_uid=effective_uid, effective_gid=effective_gid), \
                    mock.patch.object(runner.os, "geteuid", return_value=effective_uid), \
                    mock.patch.object(runner.os, "getegid", return_value=effective_gid), \
                    mock.patch.object(runner, "_qualification_container",
                                      return_value=synthetic_failure) as container_call, \
                    mock.patch.object(runner.subprocess, "run") as subprocess_run:
                report = runner.run_qualification_probe(FakeSession(), resources)

            container_call.assert_not_called()
            subprocess_run.assert_not_called()
            self.assertEqual("NOT_VERIFIED", report["status"])
            self.assertEqual("HOST_IDENTITY_MISMATCH",
                             report["observed"]["host_canary_baseline"]["reason"])
            self.assertEqual(effective_uid,
                             report["observed"]["host_canary_baseline"]["effective_uid"])
            self.assertEqual(effective_gid,
                             report["observed"]["host_canary_baseline"]["effective_gid"])
            self.assertEqual("FAIL", report["checks"]["host_file_baseline_readable"])
            self.assertTrue(all(value == "NOT_RUN" for name, value in report["checks"].items()
                                if name != "host_file_baseline_readable"))
            self.assertNotIn("diagnostic_container", report["observed"])

    def _run_qualification_container_with_cleanup_result(self, final_inspect):
        runner = load_runner()
        if isinstance(final_inspect, str):
            final_inspect = runner.SandboxError(final_inspect)

        class FakeSession:
            def call(self, argv, **kwargs):
                if argv[0] == "create":
                    return b"synthetic-container-id"
                if argv[0] == "inspect" and "--format" in argv:
                    return b'{"HostConfig": {}, "Config": {}}'
                if argv[0] == "rm":
                    return b""
                if argv[0] == "inspect":
                    if isinstance(final_inspect, Exception):
                        raise final_inspect
                    return final_inspect
                raise AssertionError("unexpected synthetic Docker command: " + repr(argv))

        spec = {
            "argv": ["create", "synthetic"],
            "resources": {"cpu_quota_millis": 1000, "memory_bytes": 268435456,
                          "pids_limit": 16},
            "expected_binds": [],
            "expected_command": ["python", "-c", "pass"],
        }
        with mock.patch.object(runner, "validate_container_config",
                               return_value=["synthetic config rejection"]):
            record = runner._qualification_container(
                FakeSession(), spec, "synthetic-name", timeout=1,
                probe_deadline=None,
            )
        return record

    def test_qualification_cleanup_inspect_permission_error_is_not_proof_of_absence(self):
        record = self._run_qualification_container_with_cleanup_result(
            "local Docker call exited 1: permission denied (EPERM)"
        )

        self.assertTrue(record["removed"])
        self.assertFalse(record["absent_after_cleanup"])
        self.assertIn("EPERM", record["cleanup_error"])

    def test_qualification_cleanup_inspection_finding_container_means_cleanup_failed(self):
        record = self._run_qualification_container_with_cleanup_result(b"{}")

        self.assertTrue(record["removed"])
        self.assertFalse(record["absent_after_cleanup"])
        self.assertIn("still exists", record["cleanup_error"])

    def test_qualification_cleanup_recognizes_only_explicit_missing_container(self):
        record = self._run_qualification_container_with_cleanup_result(
            "local Docker call exited 1: Error: No such container: synthetic-container-id"
        )

        self.assertTrue(record["removed"])
        self.assertTrue(record["absent_after_cleanup"])
        self.assertIsNone(record.get("cleanup_error"))

    def test_qualification_evidence_requires_all_checks_and_exact_limits(self):
        runner = load_runner()
        resources = {"cpu_quota_millis": 1000, "wall_seconds": 60,
                     "memory_bytes": 268435456, "pids_limit": 16,
                     "max_method_output_bytes": 65536}
        report = verified_qualification(runner, resources)
        self.assertTrue(runner.validate_qualification_evidence(report, resources))
        report["checks"]["network_unavailable"] = "NOT_RUN"
        self.assertFalse(runner.validate_qualification_evidence(report, resources))
        report = verified_qualification(runner, resources)
        report["observed"]["effective_resources"]["memory_bytes"] += 1
        self.assertFalse(runner.validate_qualification_evidence(report, resources))
        report = verified_qualification(runner, resources)
        report["observed"]["diagnostic_probes"]["network"]["external_control"] = {
            "connected": False, "errno": errno.ECONNREFUSED,
            "reason": "CONNECTION_REFUSED",
        }
        self.assertFalse(runner.validate_qualification_evidence(report, resources))
        report = verified_qualification(runner, resources)
        report["observed"]["diagnostic_probes"]["host_file"] = {
            "readable": False, "errno": errno.EACCES,
            "reason": "DAC_PERMISSION_DENIED", "sha256": None,
        }
        self.assertFalse(runner.validate_qualification_evidence(report, resources))

    def test_preflight_blocks_even_with_good_daemon_info_when_qualification_is_unverified(self):
        runner = load_runner()

        class FakeSession:
            info = {"server_version": "synthetic", "cgroup_version": "2",
                    "required_resource_capabilities": {"cpu_quota": True}}

            def __init__(self, package_dir, deadline=None):
                self.package_dir = package_dir

            def validate_resources(self, resources):
                return None

            def prepare_empty_image(self):
                return "synthetic-image", "sha256:" + "a" * 64

            def remove_empty_image(self):
                return None

            def close(self):
                return None

        preflight = {
            "task_status": "READY",
            "manifest": {"resources": {"cpu_quota_millis": 1000,
                                         "wall_seconds": 60, "memory_bytes": 268435456,
                                         "pids_limit": 16, "max_method_output_bytes": 65536}},
            "manifest_sha256": "b" * 64,
            "package_dir": PACKAGE,
        }
        not_verified = {"status": "NOT_VERIFIED", "checks": {
            "daemon_info": "PASS", "container_inspect": "PASS",
            "runtime_isolation_probe": "NOT_RUN"}}
        with mock.patch.object(runner, "preflight_task", return_value=preflight), \
                mock.patch.object(runner, "DockerSession", FakeSession), \
                mock.patch.object(runner, "run_qualification_probe", return_value=not_verified,
                                  create=True):
            report = runner.preflight_only("synthetic-manifest.json")

        self.assertEqual("BLOCKED", report["task_status"])
        self.assertEqual(0, report["method_invocations_started"])
        self.assertIn("qualification", report["stop_reason"].lower())

    def test_run_task_never_enters_slots_without_verified_qualification_evidence(self):
        runner = load_runner()

        class FakeSession:
            info = {"server_version": "synthetic", "cgroup_version": "2",
                    "required_resource_capabilities": {"cpu_quota": True}}

            def __init__(self, package_dir, deadline=None):
                self.deadline = deadline

            def validate_resources(self, resources):
                return None

            def prepare_empty_image(self):
                return "synthetic-image", "sha256:" + "a" * 64

            def remove_empty_image(self):
                return None

            def close(self):
                return None

        preflight = {
            "task_status": "READY",
            "manifest": {"resources": {"cpu_quota_millis": 1000,
                                         "wall_seconds": 60, "memory_bytes": 268435456,
                                         "pids_limit": 16, "max_method_output_bytes": 65536}},
            "manifest_sha256": "b" * 64,
            "package_dir": PACKAGE,
        }
        not_verified = {"status": "NOT_VERIFIED", "checks": {"network": "NOT_RUN"}}
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(runner, "preflight_task", return_value=preflight), \
                    mock.patch.object(runner, "DockerSession", FakeSession), \
                    mock.patch.object(runner, "run_qualification_probe", return_value=not_verified,
                                      create=True), \
                    mock.patch.object(runner, "_execute_task", return_value={"task_status": "PASS"}) as execute:
                report = runner.run_task("synthetic-manifest.json", "qualification-blocked", temp)

            self.assertEqual("BLOCKED", report["task_status"])
            self.assertEqual(0, report["method_start_requests"])
            self.assertEqual(0, report["method_invocations_started"])
            self.assertEqual(0, report["completed_method_invocations"])
            self.assertFalse((Path(temp) / "qualification-blocked").exists())
            execute.assert_not_called()

    def test_runtime_mount_rejects_ancestor_tree_that_contains_oracle_files(self):
        runner = load_runner()
        resources = {"cpu_quota_millis": 1000, "memory_bytes": 268435456,
                     "pids_limit": 16}
        runtime_dir = PACKAGE / "frozen_source" / "runtime"
        with self.assertRaisesRegex(runner.SandboxError, "overlaps protected package paths"):
            runner.build_container_spec(
                "synthetic-image", resources, "synthetic", "/tmp/synthetic.cid",
                str(PACKAGE.parent), "bin/python3", str(runtime_dir), [],
            )

    def test_image_cleanup_is_attempted_once_and_timed_before_bundle_finalization(self):
        runner = load_runner()

        class FakeSession:
            def __init__(self):
                self.image_cleanup_attempted = False
                self.calls = 0

            def remove_empty_image(self):
                self.calls += 1
                return "synthetic cleanup failure"

        session = FakeSession()
        self.assertEqual("synthetic cleanup failure",
                         runner._remove_sandbox_image_once(session))
        self.assertIsNone(runner._remove_sandbox_image_once(session))
        self.assertEqual(1, session.calls)

    def test_run_task_reports_full_attempt_duration_after_bundle_freeze(self):
        runner = load_runner()

        class FakeSession:
            def __init__(self, package_dir, deadline):
                self.deadline = deadline
                self.removed = 0
                self.closed = False

            def validate_resources(self, resources):
                return None

            def prepare_empty_image(self):
                return "synthetic-image-tag", "sha256:" + "a" * 64

            def remove_empty_image(self):
                self.removed += 1
                return None

            def close(self):
                self.closed = True

        preflight = {
            "task_status": "READY",
            "manifest": {"resources": {"cpu_quota_millis": 1000,
                                         "wall_seconds": 30, "memory_bytes": 268435456,
                                         "pids_limit": 16, "max_method_output_bytes": 65536}},
            "manifest_sha256": "b" * 64,
            "package_dir": PACKAGE,
        }
        frozen_report = {"task_status": "PASS", "exit_code": 0,
                         "wall_seconds_elapsed": 8.5,
                         "wall_seconds_scope": runner.WALL_SECONDS_SCOPE}
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(runner, "preflight_task", return_value=preflight), \
                    mock.patch.object(runner, "DockerSession", FakeSession), \
                    mock.patch.object(runner, "run_qualification_probe",
                                      return_value=verified_qualification(
                                          runner, preflight["manifest"]["resources"])), \
                    mock.patch.object(runner, "_execute_task", return_value=frozen_report), \
                    mock.patch.object(runner.time, "monotonic", side_effect=[100.0, 106.25]):
                report = runner.run_task("synthetic-manifest.json", "scope-test", temp)

        self.assertEqual(8.5, report["wall_seconds_elapsed"])
        self.assertEqual(6.25, report["attempt_wall_seconds_elapsed"])
        self.assertEqual("sandbox_lifecycle_through_image_cleanup",
                         report["wall_seconds_scope"])
        self.assertIn("attempt_finished_at_utc", report)

    def test_live_runner_pair_check_detects_output_mismatch(self):
        runner = load_runner()
        references = {}
        case_a = "38e02496822f1a85849b6a39f698e50d"
        case_b = "33fadeeedeed902bd0ab9dfae5420213"
        self.assertIsNone(runner._record_ab_pair_result(
            references, case_a, 1, "M0", "a" * 64, "b" * 64))
        self.assertEqual("AB_PROTOCOL_FAILURE: paired A/B input or output mismatch",
                         runner._record_ab_pair_result(
                             references, case_b, 1, "M0", "a" * 64, "c" * 64))

    def test_finished_event_write_failure_keeps_measured_start_and_result(self):
        runner = load_runner()
        result = {"cards": {"a": "card-a"}}
        outcome = {"status": "PASS", "started": True, "start_requested": True,
                   "result": result}
        preserved = runner._mark_persistence_failure(
            outcome, "METHOD_FINISH_EVENT_PERSIST_FAILED", OSError("synthetic fsync failure"))
        self.assertIs(outcome, preserved)
        self.assertTrue(preserved["started"])
        self.assertTrue(preserved["start_requested"])
        self.assertIs(result, preserved["result"])
        self.assertEqual("FAIL", preserved["status"])
        self.assertIn("METHOD_FINISH_EVENT_PERSIST_FAILED", preserved["error"])

    def test_docker_call_timeout_is_clamped_to_remaining_task_wall(self):
        runner = load_runner()
        session = object.__new__(runner.DockerSession)
        session.binary = "/usr/bin/docker"
        session.config_dir = Path("/tmp/docker-config")
        session.endpoint = "unix:///var/run/docker.sock"
        session.home_dir = Path("/tmp/docker-home")
        session.deadline = 15.0
        completed = mock.Mock(returncode=0, stdout=b"ok", stderr=b"")
        with mock.patch.object(runner.time, "monotonic", return_value=10.0), \
                mock.patch.object(runner.subprocess, "run", return_value=completed) as run:
            self.assertEqual(b"ok", session.call(["info"], timeout=20))
        self.assertEqual(5.0, run.call_args.kwargs["timeout"])

    def test_docker_call_obeys_earlier_method_deadline_inside_task_wall(self):
        runner = load_runner()
        session = object.__new__(runner.DockerSession)
        session.binary = "/usr/bin/docker"
        session.config_dir = Path("/tmp/docker-config")
        session.endpoint = "unix:///var/run/docker.sock"
        session.home_dir = Path("/tmp/docker-home")
        session.deadline = 30.0
        completed = mock.Mock(returncode=0, stdout=b"ok", stderr=b"")
        with mock.patch.object(runner.time, "monotonic", return_value=10.0), \
                mock.patch.object(runner.subprocess, "run", return_value=completed) as run:
            self.assertEqual(b"ok", session.call(["create"], timeout=20, deadline=15.0))
        self.assertEqual(5.0, run.call_args.kwargs["timeout"])

    def test_docker_call_fails_after_task_wall_deadline(self):
        runner = load_runner()
        session = object.__new__(runner.DockerSession)
        session.binary = "/usr/bin/docker"
        session.config_dir = Path("/tmp/docker-config")
        session.endpoint = "unix:///var/run/docker.sock"
        session.home_dir = Path("/tmp/docker-home")
        session.deadline = 1.0
        with mock.patch.object(runner.time, "monotonic", return_value=2.0), \
                mock.patch.object(runner.subprocess, "run") as run:
            with self.assertRaisesRegex(runner.SandboxError, "wall deadline expired"):
                session.call(["info"], timeout=20)
        run.assert_not_called()

    def test_emergency_timeout_cleanup_is_bounded_and_keeps_slot_failed(self):
        runner = load_runner()

        class FakeSession:
            def __init__(self):
                self.calls = []

            def call(self, args, timeout=20):
                self.calls.append((args, timeout))
                return b""

        class FakeStartClient:
            def __init__(self):
                self.killed = False
                self.wait_timeout = None

            def poll(self):
                return -9 if self.killed else None

            def kill(self):
                self.killed = True

            def wait(self, timeout):
                self.wait_timeout = timeout
                return -9

        session = FakeSession()
        process = FakeStartClient()
        result = runner._fail_timed_out_container(
            session, "synthetic-container", process,
            {"status": "PASS", "error": "WALL_LIMIT_EXCEEDED"})
        self.assertEqual("FAIL", result["status"])
        self.assertEqual("WALL_LIMIT_EXCEEDED", result["error"])
        self.assertTrue(result["start_unknown"])
        self.assertEqual("REMOVED", result["container_cleanup_status"])
        self.assertTrue(process.killed)
        self.assertEqual(1, process.wait_timeout)
        self.assertEqual([
            (["kill", "synthetic-container"], 2),
            (["rm", "--force", "synthetic-container"], 3),
        ], session.calls)

    def test_missing_limits_block_before_run_directory_or_method_invocation(self):
        runner = load_runner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "task_id": "PCG-IDENTIFIABILITY-PAIRED-CPU-001",
                "resources": {"cpu_quota_millis": 1000, "wall_seconds": None,
                              "memory_bytes": None, "pids_limit": None,
                              "max_method_output_bytes": None},
            }))
            output_root = root / "returns"
            report = runner.run_task(manifest, "synthetic-blocked-run", output_root)
            self.assertEqual("BLOCKED", report["task_status"])
            self.assertEqual(0, report["method_invocations_started"])
            self.assertFalse((output_root / "synthetic-blocked-run").exists())

    def test_runner_manifest_pins_opaque_case_order_and_arm_ids(self):
        runner = load_runner()
        manifest = json.loads((PACKAGE / "TASK_MANIFEST.json").read_text())
        manifest["opaque_case_ids"]["A"] = manifest["opaque_case_ids"]["B"]
        manifest["case_ids"][0] = manifest["case_ids"][1]
        issues = runner._valid_manifest(manifest)
        self.assertIn("case IDs do not match the four cases pinned to the reviewed plan", issues)
        self.assertIn("opaque case IDs must bind exactly the four planned arms", issues)

    def test_existing_run_id_is_never_overwritten(self):
        runner = load_runner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "manifest.json"
            manifest.write_text("not consulted if run ID is already reserved")
            output_root = root / "returns"
            run_dir = output_root / "same-run"
            run_dir.mkdir(parents=True)
            marker = run_dir / "marker.txt"
            marker.write_text("keep")
            report = runner.run_task(manifest, "same-run", output_root)
            self.assertEqual("BLOCKED", report["task_status"])
            self.assertIn("already exists", report["stop_reason"])
            self.assertEqual("keep", marker.read_text())

    def test_docker_config_must_match_requested_isolation_and_limits_exactly(self):
        runner = load_runner()
        requested = {"cpu_quota_millis": 1000, "memory_bytes": 268435456,
                     "pids_limit": 16}
        host_config = {
            "NanoCpus": 1000000000,
            "Memory": 268435456,
            "MemorySwap": 268435456,
            "PidsLimit": 16,
            "ReadonlyRootfs": True,
            "Privileged": False,
            "NetworkMode": "none",
            "PidMode": "",
            "IpcMode": "private",
            "CgroupnsMode": "private",
            "UTSMode": "",
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "LogConfig": {"Type": "none"},
            "Binds": ["/tmp/visible-source:/task/source:ro"],
        }
        self.assertEqual([], runner.validate_container_config(host_config, requested,
                                                               ["/tmp/visible-source:/task/source:ro"]))
        host_config["NetworkMode"] = "bridge"
        self.assertIn("network mode is not none",
                      runner.validate_container_config(host_config, requested,
                                                       ["/tmp/visible-source:/task/source:ro"]))

    def test_custom_seccomp_and_shared_namespace_modes_are_rejected(self):
        runner = load_runner()
        requested = {"cpu_quota_millis": 1000, "memory_bytes": 268435456,
                     "pids_limit": 16}
        base = {
            "NanoCpus": 1000000000, "Memory": 268435456,
            "MemorySwap": 268435456, "PidsLimit": 16,
            "ReadonlyRootfs": True, "Privileged": False, "NetworkMode": "none",
            "PidMode": "", "IpcMode": "private", "UsernsMode": "private",
            "CgroupnsMode": "private", "UTSMode": "",
            "CapDrop": ["ALL"], "CapAdd": [], "SecurityOpt": ["no-new-privileges:true"],
            "Binds": [], "Devices": [], "DeviceRequests": [], "Mounts": [],
            "VolumesFrom": [], "Tmpfs": {}, "LogConfig": {"Type": "none"},
        }
        custom_seccomp = dict(base, SecurityOpt=["no-new-privileges:true", "seccomp=/tmp/custom.json"])
        self.assertIn("custom container security profiles are forbidden",
                      runner.validate_container_config(custom_seccomp, requested, []))
        shared_pid = dict(base, PidMode="container:other-container")
        self.assertIn("shared or host PID namespaces are forbidden",
                      runner.validate_container_config(shared_pid, requested, []))
        shared_ipc = dict(base, IpcMode="container:other-container")
        self.assertIn("shared or host IPC namespaces are forbidden",
                      runner.validate_container_config(shared_ipc, requested, []))
        shared_cgroup = dict(base, CgroupnsMode="host")
        self.assertIn("cgroup namespace is not private",
                      runner.validate_container_config(shared_cgroup, requested, []))
        shared_uts = dict(base, UTSMode="host")
        self.assertIn("shared or host UTS namespaces are forbidden",
                      runner.validate_container_config(shared_uts, requested, []))

    def test_inspected_container_command_environment_and_mounts_are_pinned(self):
        runner = load_runner()
        requested = {"cpu_quota_millis": 1000, "memory_bytes": 268435456,
                     "pids_limit": 16}
        binds = ["/host/python:/runtime:ro", "/host/source:/task/source:ro"]
        host_config = {
            "NanoCpus": 1000000000, "Memory": 268435456,
            "MemorySwap": 268435456, "PidsLimit": 16,
            "ReadonlyRootfs": True, "Privileged": False, "NetworkMode": "none",
            "PidMode": "", "IpcMode": "private", "CgroupnsMode": "private",
            "UTSMode": "", "CapDrop": ["ALL"],
            "CapAdd": [], "SecurityOpt": ["no-new-privileges:true"],
            "Binds": binds, "Devices": [], "DeviceRequests": [],
            "Mounts": [], "VolumesFrom": [], "Tmpfs": {},
            "LogConfig": {"Type": "none"},
        }
        command = ["/runtime/bin/python3", "-I", "-S", "-B", "/task/source/slot_worker.py"]
        config = {
            "User": "65534:65534", "WorkingDir": "/task/source", "Env": [],
            "Entrypoint": None, "Cmd": command, "Tty": False,
            "AttachStdin": True, "OpenStdin": True,
            "AttachStdout": True, "AttachStderr": True,
        }
        self.assertEqual([], runner.validate_container_config(
            host_config, requested, binds, config, command))
        config["Env"] = ["ORACLE_PATH=/private/oracle"]
        self.assertIn("method container environment must be empty",
                      runner.validate_container_config(host_config, requested,
                                                       binds, config, command))

    def test_method_container_binds_only_runtime_and_method_code(self):
        runner = load_runner()
        self.assertTrue(callable(getattr(runner, "build_container_spec", None)),
                        "missing feature: secure Docker spec builder")
        runtime_prefix, python_relative_path, library_dirs = runner._runtime_layout()
        source_dir = PACKAGE / "frozen_source" / "runtime"
        spec = runner.build_container_spec(
            image="pcg-empty:sha",
            resources={"cpu_quota_millis": 1000, "memory_bytes": 268435456,
                       "pids_limit": 16},
            container_name="pcg-pair-synthetic-0001",
            cidfile="/tmp/cid",
            runtime_prefix=runtime_prefix,
            python_relative_path=python_relative_path,
            source_dir=str(source_dir),
            library_dirs=library_dirs,
        )
        argv = spec["argv"]
        self.assertIn("--network=none", argv)
        self.assertIn("--read-only", argv)
        self.assertIn("--cgroupns=private", argv)
        self.assertIn("--cap-drop=ALL", argv)
        self.assertIn("--log-driver=none", argv)
        self.assertIn("--cpus=1.000", argv)
        self.assertIn("--interactive", argv)
        self.assertIn("--attach=stdin", argv)
        self.assertIn("--attach=stdout", argv)
        self.assertIn("--attach=stderr", argv)
        self.assertIn("--volume=" + runtime_prefix + ":/runtime:ro", argv)
        self.assertIn("--volume=" + str(source_dir.resolve()) + ":/task/source:ro", argv)
        self.assertIn("--volume=" + library_dirs[0][0] + ":" + library_dirs[0][1] + ":ro", argv)
        self.assertNotIn("oracle", " ".join(argv).lower())
        self.assertNotIn("truth", " ".join(argv).lower())

    def test_fractional_resource_limits_are_not_accepted_as_preregistration(self):
        module = load_runner()
        profile = module.validate_resource_profile({"resources": {
            "cpu_quota_millis": 1000, "wall_seconds": 5.5,
            "memory_bytes": 1024, "pids_limit": 16,
            "max_method_output_bytes": 4096,
        }})
        self.assertEqual("BLOCKED", profile.status)
        self.assertIn("wall_seconds", profile.invalid_fields)

    def test_wall_budget_must_leave_the_pinned_cleanup_reserve(self):
        module = load_runner()
        profile = module.validate_resource_profile({"resources": {
            "cpu_quota_millis": 1000, "wall_seconds": 9,
            "memory_bytes": 1024, "pids_limit": 16,
            "max_method_output_bytes": 4096,
        }})
        self.assertEqual("BLOCKED", profile.status)
        self.assertIn("wall_seconds", profile.invalid_fields)

    def test_daemon_without_each_cgroup_limit_is_blocked(self):
        runner = load_runner()
        daemon = {
            "ServerVersion": "synthetic", "CgroupVersion": "2", "NCPU": 2,
            "MemTotal": 1073741824, "SecurityOptions": ["name=seccomp,profile=builtin"],
            "MemoryLimit": True, "SwapLimit": True, "CpuCfsQuota": True,
            "PidsLimit": True,
        }
        session = object.__new__(runner.DockerSession)
        session.call = lambda args, timeout=15: json.dumps(daemon).encode()
        info = session._read_daemon_info()
        self.assertEqual(2, info["cpus"])
        daemon["PidsLimit"] = False
        with self.assertRaisesRegex(runner.SandboxError, "pids_limit"):
            session._read_daemon_info()
        daemon["PidsLimit"] = True
        daemon["SecurityOptions"] = ["name=seccomp,profile=unconfined"]
        with self.assertRaisesRegex(runner.SandboxError, "seccomp"):
            session._read_daemon_info()
        daemon["SecurityOptions"] = ["name=seccomp,profile=custom:/tmp/profile.json"]
        with self.assertRaisesRegex(runner.SandboxError, "seccomp"):
            session._read_daemon_info()
        daemon["SecurityOptions"] = ["name=seccomp,profile=default"]
        self.assertEqual(2, session._read_daemon_info()["cpus"])

    def test_unconfined_container_seccomp_option_is_rejected(self):
        runner = load_runner()
        requested = {"cpu_quota_millis": 1000, "memory_bytes": 268435456,
                     "pids_limit": 16}
        host_config = {
            "NanoCpus": 1000000000, "Memory": 268435456,
            "MemorySwap": 268435456, "PidsLimit": 16,
            "ReadonlyRootfs": True, "Privileged": False, "NetworkMode": "none",
            "PidMode": "", "IpcMode": "private", "CgroupnsMode": "private",
            "UTSMode": "", "CapDrop": ["ALL"],
            "CapAdd": [], "SecurityOpt": ["no-new-privileges:true", "seccomp=unconfined"],
            "Binds": [], "Devices": [], "DeviceRequests": [], "Mounts": [],
            "VolumesFrom": [], "Tmpfs": {}, "LogConfig": {"Type": "none"},
        }
        issues = runner.validate_container_config(host_config, requested, [])
        self.assertIn("an unconfined seccomp profile is forbidden", issues)


if __name__ == "__main__":
    unittest.main()
