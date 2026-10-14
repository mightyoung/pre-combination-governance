import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


PACKAGE = Path(__file__).resolve().parents[1]


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
            "manifest": {"resources": {"wall_seconds": 30}},
            "manifest_sha256": "b" * 64,
            "package_dir": PACKAGE,
        }
        frozen_report = {"task_status": "PASS", "exit_code": 0,
                         "wall_seconds_elapsed": 8.5,
                         "wall_seconds_scope": runner.WALL_SECONDS_SCOPE}
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(runner, "preflight_task", return_value=preflight), \
                    mock.patch.object(runner, "DockerSession", FakeSession), \
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
        spec = runner.build_container_spec(
            image="pcg-empty:sha",
            resources={"cpu_quota_millis": 1000, "memory_bytes": 268435456,
                       "pids_limit": 16},
            container_name="pcg-pair-synthetic-0001",
            cidfile="/tmp/cid",
            runtime_prefix="/host/python",
            python_relative_path="bin/python3",
            source_dir="/host/frozen-runtime",
            library_dirs=[("/host/lib", "/lib"), ("/host/usr-lib", "/usr/lib")],
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
        self.assertIn("--volume=/host/python:/runtime:ro", argv)
        self.assertIn("--volume=/host/frozen-runtime:/task/source:ro", argv)
        self.assertIn("--volume=/host/lib:/lib:ro", argv)
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
