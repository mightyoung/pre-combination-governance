"""Run the paired CPU diagnostic through a local, inspected Docker sandbox."""

import argparse
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import socket
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time

PACKAGE_DIR = Path(__file__).resolve().parent
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

from bundle import canonical_bytes, freeze_bundle
from pair_inputs import build_pair_cases, canonical_json_bytes
from preflight import CLEANUP_RESERVE_SECONDS, validate_resource_profile
from result_contract import ResultContractError, validate_result
from task_contract import CASE_ID_ORDER, CASE_IDS_BY_ARM


TASK_ID = "PCG-IDENTIFIABILITY-PAIRED-CPU-001"
METHOD_ORDER = ["M0", "M1", "M2", "M3"]
PLANNED_SLOTS = 80
WALL_SECONDS_SCOPE = "sandbox_lifecycle_through_image_cleanup"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DOCKER_CANDIDATES = ("/usr/bin/docker", "/usr/local/bin/docker", "/bin/docker")
LOCAL_DOCKER_SOCKETS = ("/var/run/docker.sock", "/run/docker.sock")
QUALIFICATION_PROBE_ID = "fixed-network-cgroup-oom-v1"
QUALIFICATION_MEMORY_BYTES = 64 * 1024 * 1024
QUALIFICATION_CHECKS = (
    "container_config", "host_file_baseline_readable", "host_file_unreadable",
    "network_positive_control", "network_unavailable",
    "effective_cpu_quota", "effective_memory_limit",
    "effective_memory_swap_limit", "effective_pid_limit",
    "memory_overlimit_killed", "probe_container_cleanup",
)

_QUALIFICATION_DIAGNOSTIC_PROGRAM = r'''import errno, hashlib, json, os, socket, sys
expected = json.loads(sys.argv[1])
canary = sys.argv[2]
def read(path):
    with open(path, "r", encoding="ascii") as stream:
        return stream.read().strip()
cpu_fields = read("/sys/fs/cgroup/cpu.max").split()
cpu_quota = None if cpu_fields[0] == "max" else int(cpu_fields[0])
cpu_period = int(cpu_fields[1])
actual = {
    "cpu_quota_millis": int(cpu_quota * 1000 / cpu_period) if cpu_quota is not None else None,
    "memory_bytes": int(read("/sys/fs/cgroup/memory.max")),
    "memory_swap_bytes": int(read("/sys/fs/cgroup/memory.swap.max")),
    "pids_limit": int(read("/sys/fs/cgroup/pids.max")),
}
try:
    with open(canary, "rb") as stream:
        canary_bytes = stream.read()
    canary_hash = hashlib.sha256(canary_bytes).hexdigest()
    hash_matches = canary_hash == expected.get("host_file_sha256")
    host_file = {"readable": True, "errno": None,
                 "reason": "HOST_FILE_VISIBLE" if hash_matches else "HOST_FILE_CONTENT_MISMATCH",
                 "sha256": canary_hash}
except OSError as error:
    code = error.errno
    reason = "DAC_PERMISSION_DENIED" if code == errno.EACCES else (
        "PATH_NOT_VISIBLE" if code == errno.ENOENT else "FILE_PROBE_ERROR")
    host_file = {"readable": False, "errno": code,
                 "reason": reason, "sha256": None}

listener = None
positive = None
positive_control = {"connected": False, "errno": None,
                    "reason": "CONTROL_SETUP_FAILED"}
try:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    positive = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    positive.settimeout(1.0)
    code = positive.connect_ex(listener.getsockname())
    positive_control = {"connected": code == 0, "errno": code,
                        "reason": "CONNECTED" if code == 0 else "CONTROL_CONNECT_FAILED"}
except (OSError, AttributeError) as error:
    code = error.errno if isinstance(error, OSError) else None
    positive_control = {"connected": False, "errno": code,
                        "reason": "CONTROL_SETUP_FAILED"}
finally:
    if positive is not None:
        positive.close()
    if listener is not None:
        listener.close()

external = None
external_control = {"connected": False, "errno": None, "reason": "PROBE_FAILED"}
try:
    external = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    external.settimeout(1.0)
    code = external.connect_ex(("192.0.2.1", 9))
    if code == 0:
        reason = "CONNECTED"
    elif code == errno.ECONNREFUSED:
        reason = "CONNECTION_REFUSED"
    elif code in (errno.ENETUNREACH, errno.EHOSTUNREACH):
        reason = "NETWORK_UNREACHABLE"
    elif code == errno.ETIMEDOUT:
        reason = "TIMEOUT"
    else:
        reason = "OTHER_ERRNO"
    external_control = {"connected": code == 0, "errno": code, "reason": reason}
except (OSError, TimeoutError) as error:
    code = error.errno if isinstance(error, OSError) and error.errno is not None else errno.ETIMEDOUT
    reason = "TIMEOUT" if code == errno.ETIMEDOUT else "OTHER_ERRNO"
    external_control = {"connected": False, "errno": code, "reason": reason}
finally:
    if external is not None:
        external.close()

host_baseline = expected.get("host_file_baseline_readable") is True
host_file_unreadable = (host_baseline and not host_file["readable"]
                        and host_file["errno"] == errno.ENOENT
                        and host_file["reason"] == "PATH_NOT_VISIBLE")
network_positive_control = (positive_control["connected"] is True
                           and positive_control["errno"] == 0)
network_unavailable = (network_positive_control
                       and external_control["connected"] is False
                       and external_control["errno"] in (errno.ENETUNREACH,
                                                          errno.EHOSTUNREACH)
                       and external_control["reason"] == "NETWORK_UNREACHABLE")
checks = {
    "host_file_baseline_readable": host_baseline,
    "host_file_unreadable": host_file_unreadable,
    "network_positive_control": network_positive_control,
    "network_unavailable": network_unavailable,
    "effective_cpu_quota": actual["cpu_quota_millis"] == expected["cpu_quota_millis"],
    "effective_memory_limit": actual["memory_bytes"] == expected["memory_bytes"],
    "effective_memory_swap_limit": actual["memory_swap_bytes"] == 0,
    "effective_pid_limit": actual["pids_limit"] == expected["pids_limit"],
}
print(json.dumps({"actual": actual, "checks": checks,
                  "probes": {"host_file": host_file,
                             "network": {"positive_control": positive_control,
                                         "external_control": external_control}}},
                 sort_keys=True))
sys.exit(0 if all(checks.values()) else 41)
'''

_QUALIFICATION_OOM_PROGRAM = r'''import os, sys
os.write(1, b"PCG_OOM_PROBE_READY\n")
target = int(sys.argv[1]) + 16 * 1024 * 1024
chunk = 1024 * 1024
blocks = []
while True:
    block = bytearray(min(chunk, target - len(blocks) * chunk))
    for offset in range(0, len(block), 4096):
        block[offset] = 1
    blocks.append(block)
    if len(blocks) * chunk >= target:
        os._exit(42)
'''


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _host_canary_baseline(path: Path, expected_bytes: bytes) -> dict:
    """Prove the exact sandbox identity can read the untouched host canary."""
    effective_uid = os.geteuid()
    effective_gid = os.getegid()
    report = {
        "effective_uid": effective_uid,
        "effective_gid": effective_gid,
        "readable": False,
        "sha256": None,
        "errno": None,
        "reason": None,
    }
    if effective_uid != 65534 or effective_gid != 65534:
        report["reason"] = "HOST_IDENTITY_MISMATCH"
        return report
    try:
        actual = path.read_bytes()
    except OSError as error:
        report["errno"] = error.errno
        report["reason"] = "HOST_CANARY_READ_FAILED"
        return report
    report["sha256"] = _sha256(actual)
    if actual != expected_bytes:
        report["reason"] = "HOST_CANARY_CONTENT_MISMATCH"
        return report
    report["readable"] = True
    return report


def _remove_sandbox_image_once(session) -> str | None:
    """Run one bounded image-cleanup attempt; keep receipt timing consistent."""
    if getattr(session, "image_cleanup_attempted", False):
        return None
    session.image_cleanup_attempted = True
    return session.remove_empty_image()


def _blocked(reason: str, missing=(), run_id=None) -> dict:
    return {
        "task_status": "BLOCKED",
        "research_acceptance": "NOT_EVALUATED",
        "run_id": run_id,
        "planned_method_invocations": PLANNED_SLOTS,
        "method_start_requests": 0,
        "method_invocations_started": 0,
        "completed_method_invocations": 0,
        "partial": False,
        "stop_reason": reason,
        "missing_resource_fields": list(missing),
        "exit_code": 20,
    }


def _read_json(path: Path, label: str) -> tuple[bytes, dict]:
    try:
        data = path.read_bytes()
        value = json.loads(data)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(label + " is unreadable JSON") from error
    if not isinstance(value, dict):
        raise ValueError(label + " must be a JSON object")
    return data, value


def validate_container_config(host_config: dict, requested: dict,
                              expected_binds: list[str], config: dict | None = None,
                              expected_command: list[str] | None = None,
                              expected_working_dir: str = "/task/source") -> list[str]:
    """Return exact mismatches from Docker's inspected, stopped container config."""
    issues = []
    expected_nano_cpus = requested["cpu_quota_millis"] * 1_000_000
    if host_config.get("NanoCpus") != expected_nano_cpus:
        issues.append("CPU quota does not match preregistered limit")
    if host_config.get("Memory") != requested["memory_bytes"]:
        issues.append("memory limit does not match preregistered limit")
    if host_config.get("MemorySwap") != requested["memory_bytes"]:
        issues.append("memory plus swap limit does not match memory limit")
    if host_config.get("PidsLimit") != requested["pids_limit"]:
        issues.append("process limit does not match preregistered limit")
    if host_config.get("ReadonlyRootfs") is not True:
        issues.append("container root filesystem is not read-only")
    if host_config.get("NetworkMode") != "none":
        issues.append("network mode is not none")
    if host_config.get("Privileged") is not False:
        issues.append("container must not be privileged")
    if host_config.get("PidMode") not in (None, "", "private"):
        issues.append("shared or host PID namespaces are forbidden")
    if host_config.get("IpcMode") not in (None, "", "private"):
        issues.append("shared or host IPC namespaces are forbidden")
    if host_config.get("UsernsMode") not in (None, "", "private"):
        issues.append("shared or host user namespaces are forbidden")
    if host_config.get("CgroupnsMode") != "private":
        issues.append("cgroup namespace is not private")
    if "UTSMode" not in host_config:
        issues.append("UTS namespace mode could not be verified")
    elif host_config.get("UTSMode") not in ("", "private"):
        issues.append("shared or host UTS namespaces are forbidden")
    if "ALL" not in host_config.get("CapDrop", []):
        issues.append("all Linux capabilities must be dropped")
    if host_config.get("CapAdd", []):
        issues.append("Linux capabilities must not be added")
    security_options = host_config.get("SecurityOpt") or []
    if "no-new-privileges:true" not in security_options:
        issues.append("no-new-privileges is not enabled")
    if any("seccomp=unconfined" in str(value).lower() for value in security_options):
        issues.append("an unconfined seccomp profile is forbidden")
    if security_options != ["no-new-privileges:true"]:
        issues.append("custom container security profiles are forbidden")
    if host_config.get("Binds", []) != expected_binds:
        issues.append("container bind mounts do not match the read-only allowlist")
    if host_config.get("Devices", []):
        issues.append("device mounts are forbidden")
    if host_config.get("DeviceRequests", []):
        issues.append("device requests are forbidden")
    if host_config.get("Mounts", []):
        issues.append("additional mounts are forbidden")
    if host_config.get("VolumesFrom", []):
        issues.append("inherited volumes are forbidden")
    if host_config.get("Tmpfs", {}):
        issues.append("writable tmpfs mounts are forbidden")
    for key in ("Links", "ExtraHosts", "PortBindings", "Dns", "DnsSearch"):
        if host_config.get(key):
            issues.append(key + " host configuration is forbidden")
    if host_config.get("LogConfig", {}).get("Type") != "none":
        issues.append("container log persistence is not disabled")
    if config is not None:
        if config.get("User") != "65534:65534":
            issues.append("container user is not the unprivileged task user")
        if config.get("WorkingDir") != expected_working_dir:
            issues.append("container working directory differs from the reviewed command")
        if config.get("Env") not in (None, []):
            issues.append("method container environment must be empty")
        if config.get("Entrypoint") not in (None, []):
            issues.append("container entrypoint differs from the reviewed command")
        if config.get("Cmd") != expected_command:
            issues.append("container command differs from the reviewed slot adapter")
        for key, expected in (("Tty", False), ("AttachStdin", True),
                              ("OpenStdin", True), ("AttachStdout", True),
                              ("AttachStderr", True)):
            if config.get(key) is not expected:
                issues.append("container " + key + " setting is not the reviewed value")
    return issues


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _validated_mounts(runtime_prefix: str, source_dir: str | None,
                      library_dirs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Resolve binds and reject any path that can expose protected package data."""
    protected_package = PACKAGE_DIR.resolve()
    allowed_method_source = (protected_package / "frozen_source" / "runtime").resolve()
    expected_prefix = Path(sys.prefix).resolve()
    normalized_runtime = Path(runtime_prefix).resolve()
    if _paths_overlap(normalized_runtime, protected_package):
        raise SandboxError("bind mount overlaps protected package paths")
    if normalized_runtime != expected_prefix:
        raise SandboxError("runtime bind source differs from the active Python prefix")
    mounts = [(str(normalized_runtime), "/runtime")]
    if source_dir is not None:
        normalized_source = Path(source_dir).resolve()
        if normalized_source != allowed_method_source:
            raise SandboxError("method source must use the exact frozen runtime directory")
        mounts.append((str(normalized_source), "/task/source"))
    expected_libraries = []
    for host_path, destination in (("/lib", "/lib"), ("/lib64", "/lib64"),
                                  ("/usr/lib", "/usr/lib")):
        candidate = Path(host_path)
        if candidate.exists():
            expected_libraries.append((str(candidate.resolve()), destination))
    normalized_libraries = [(str(Path(source).resolve()), destination)
                            for source, destination in library_dirs]
    if normalized_libraries != expected_libraries:
        raise SandboxError("library binds differ from the exact host runtime allowlist")
    if any(_paths_overlap(Path(source), protected_package)
           for source, _destination in normalized_libraries):
        raise SandboxError("bind mount overlaps protected package paths")
    mounts.extend(normalized_libraries)
    allowed_destinations = {"/runtime", "/task/source", "/lib", "/lib64", "/usr/lib"}
    seen_destinations = set()
    for source_text, destination in mounts:
        source = Path(source_text)
        if destination not in allowed_destinations or destination in seen_destinations:
            raise SandboxError("bind mount destination is outside the reviewed allowlist")
        seen_destinations.add(destination)
        if (destination == "/task/source" and source == allowed_method_source):
            if any(path.is_symlink() for path in source.rglob("*")):
                raise SandboxError("method runtime mount contains a symlink")
            continue
        if _paths_overlap(source, protected_package):
            raise SandboxError("bind mount overlaps protected package paths")
    if "/runtime" not in seen_destinations:
        raise SandboxError("runtime bind mount is missing")
    if source_dir is not None and "/task/source" not in seen_destinations:
        raise SandboxError("method source bind mount is missing")
    return mounts


def build_container_spec(image: str, resources: dict, container_name: str,
                         cidfile: str, runtime_prefix: str,
                         python_relative_path: str, source_dir: str,
                         library_dirs: list[tuple[str, str]]) -> dict:
    """Build one isolated container command with no oracle or case mount."""
    mounts = _validated_mounts(runtime_prefix, source_dir, library_dirs)
    expected_python = Path(sys.executable).resolve().relative_to(Path(sys.prefix).resolve()).as_posix()
    if Path(python_relative_path).as_posix() != expected_python:
        raise SandboxError("container Python executable differs from the active interpreter")
    binds = []
    for source, destination in mounts:
        if ":" in source or ":" in destination:
            raise ValueError("colon in bind path is unsupported")
        binds.append(source + ":" + destination + ":ro")

    cpu_value = resources["cpu_quota_millis"] / 1000
    if cpu_value != 1.0:
        raise ValueError("the reviewed plan fixes execution to one CPU")
    executable = "/runtime/" + str(Path(python_relative_path))
    argv = [
        "create", "--cidfile", cidfile, "--name", container_name,
        "--network=none", "--read-only", "--cgroupns=private", "--cpus=1.000",
        "--memory=" + str(resources["memory_bytes"]),
        "--memory-swap=" + str(resources["memory_bytes"]),
        "--pids-limit=" + str(resources["pids_limit"]),
        "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
        "--log-driver=none", "--user=65534:65534", "--workdir=/task/source",
        "--interactive", "--attach=stdin", "--attach=stdout", "--attach=stderr",
    ]
    argv.extend("--volume=" + bind for bind in binds)
    argv.extend((image, executable, "-I", "-S", "-B", "/task/source/slot_worker.py"))
    return {"argv": argv, "expected_binds": binds, "mounts": mounts,
            "expected_command": [executable, "-I", "-S", "-B", "/task/source/slot_worker.py"]}


def build_qualification_container_spec(image: str, resources: dict,
                                       container_name: str, cidfile: str,
                                       runtime_prefix: str, python_relative_path: str,
                                       library_dirs: list[tuple[str, str]],
                                       program: str, arguments: list[str]) -> dict:
    """Build the fixed qualification command with runtime binds only."""
    mounts = _validated_mounts(runtime_prefix, None, library_dirs)
    expected_python = Path(sys.executable).resolve().relative_to(Path(sys.prefix).resolve()).as_posix()
    if Path(python_relative_path).as_posix() != expected_python:
        raise SandboxError("qualification Python executable differs from the active interpreter")
    binds = []
    for source, destination in mounts:
        if ":" in source or ":" in destination:
            raise SandboxError("colon in bind path is unsupported")
        binds.append(source + ":" + destination + ":ro")
    cpu_value = resources["cpu_quota_millis"] / 1000
    if cpu_value != 1.0:
        raise SandboxError("the reviewed plan fixes execution to one CPU")
    executable = "/runtime/" + str(Path(python_relative_path))
    expected_command = [executable, "-I", "-S", "-B", "-c", program, *arguments]
    argv = [
        "create", "--cidfile", cidfile, "--name", container_name,
        "--network=none", "--read-only", "--cgroupns=private", "--cpus=1.000",
        "--memory=" + str(resources["memory_bytes"]),
        "--memory-swap=" + str(resources["memory_bytes"]),
        "--pids-limit=" + str(resources["pids_limit"]),
        "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
        "--log-driver=none", "--user=65534:65534", "--workdir=/",
        "--interactive", "--attach=stdin", "--attach=stdout", "--attach=stderr",
    ]
    argv.extend("--volume=" + bind for bind in binds)
    argv.extend((image, *expected_command))
    return {"argv": argv, "expected_binds": binds, "mounts": mounts,
            "expected_command": expected_command}


def _locate_docker() -> str | None:
    for candidate in DOCKER_CANDIDATES:
        path = Path(candidate)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
    return None


def _locate_local_socket() -> str | None:
    for candidate in LOCAL_DOCKER_SOCKETS:
        try:
            info = Path(candidate).stat()
        except OSError:
            continue
        if stat.S_ISSOCK(info.st_mode):
            return "unix://" + str(Path(candidate).resolve())
    return None


class SandboxError(RuntimeError):
    pass


class DockerSession:
    """Use only a detected local Unix Docker socket with isolated CLI config."""

    def __init__(self, package_dir: Path, deadline: float | None = None):
        if not sys.platform.startswith("linux"):
            raise SandboxError("Linux Docker isolation is required")
        self.binary = _locate_docker()
        self.endpoint = _locate_local_socket()
        if not self.binary:
            raise SandboxError("no preinstalled Docker CLI found")
        if not self.endpoint:
            raise SandboxError("no local Unix Docker socket found")
        self.config_dir = Path(tempfile.mkdtemp(prefix="pcg-docker-config-", dir="/tmp"))
        self.home_dir = Path(tempfile.mkdtemp(prefix="pcg-docker-home-", dir="/tmp"))
        self.package_dir = package_dir
        self.deadline = deadline
        self.image_tag = None
        self.image_id = None
        self.image_cleanup_attempted = False
        try:
            self.info = self._read_daemon_info()
        except Exception:
            self.close()
            raise

    def close(self):
        shutil.rmtree(self.config_dir, ignore_errors=True)
        shutil.rmtree(self.home_dir, ignore_errors=True)

    def _command(self, args):
        return [self.binary, "--config", str(self.config_dir), "--host",
                self.endpoint, *args]

    def popen(self, args):
        environment = {
            "HOME": str(self.home_dir),
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "LC_ALL": "C",
        }
        return subprocess.Popen(
            self._command(args), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0, env=environment,
        )

    def call_completed(self, args, timeout=20, input_data=None, deadline=None):
        environment = {
            "HOME": str(self.home_dir),
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "LC_ALL": "C",
        }
        effective_deadline = self.deadline
        if deadline is not None:
            effective_deadline = (deadline if effective_deadline is None
                                  else min(effective_deadline, deadline))
        if effective_deadline is not None:
            remaining = effective_deadline - time.monotonic()
            if remaining <= 0:
                raise SandboxError("task wall deadline expired before Docker call")
            timeout = min(timeout, remaining)
        try:
            result = subprocess.run(
                self._command(args), input=input_data, capture_output=True,
                timeout=timeout, check=False, env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SandboxError("local Docker call failed: " + type(error).__name__) from error
        return result

    def call(self, args, timeout=20, input_data=None, deadline=None):
        result = self.call_completed(args, timeout=timeout, input_data=input_data,
                                     deadline=deadline)
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", "replace")[-1000:]
            raise SandboxError("local Docker call exited " + str(result.returncode) + ": " + message)
        return result.stdout

    def _read_daemon_info(self):
        raw = self.call(["info", "--format", "{{json .}}"], timeout=15).decode().strip()
        try:
            daemon = json.loads(raw)
        except (ValueError, json.JSONDecodeError) as error:
            raise SandboxError("Docker daemon capability record is invalid") from error
        required_capabilities = {
            "memory_limit": daemon.get("MemoryLimit"),
            "swap_limit": daemon.get("SwapLimit"),
            "cpu_quota": daemon.get("CpuCfsQuota"),
            "pids_limit": daemon.get("PidsLimit"),
        }
        info = {
            "server_version": daemon.get("ServerVersion"),
            "cgroup_version": daemon.get("CgroupVersion"),
            "cpus": daemon.get("NCPU"),
            "memory_bytes": daemon.get("MemTotal"),
            "security_options": daemon.get("SecurityOptions", []),
            "required_resource_capabilities": required_capabilities,
        }
        if info["cgroup_version"] != "2":
            raise SandboxError("Docker daemon must use cgroup v2")
        seccomp_options = [str(option).lower() for option in info["security_options"]
                           if "seccomp" in str(option).lower()]
        profiles = []
        for option in seccomp_options:
            match = re.search(r"(?:^|[, ])profile=([^,\s]+)", option)
            profiles.append(match.group(1) if match else None)
        if not profiles or any(profile not in {"builtin", "default"} for profile in profiles):
            raise SandboxError("Docker daemon seccomp profile is missing, custom, or unconfined")
        missing = [name for name, supported in required_capabilities.items() if supported is not True]
        if missing:
            raise SandboxError("Docker daemon lacks required cgroup controls: " + ", ".join(missing))
        if not isinstance(info["cpus"], int) or not isinstance(info["memory_bytes"], int):
            raise SandboxError("Docker daemon CPU/memory capacity is unavailable")
        return info

    def validate_resources(self, resources):
        if resources["cpu_quota_millis"] != 1000:
            raise SandboxError("reviewed task requires one CPU quota")
        if resources["memory_bytes"] > self.info["memory_bytes"]:
            raise SandboxError("preregistered memory limit exceeds Docker host memory")
        if self.info["cpus"] < 1:
            raise SandboxError("Docker host reports fewer than one CPU")

    def prepare_empty_image(self):
        sandbox_dir = self.package_dir / "sandbox"
        dockerfile = sandbox_dir / "Dockerfile"
        if not dockerfile.is_file() or not (sandbox_dir / "rootfs").is_dir():
            raise SandboxError("offline scratch sandbox definition is missing")
        files = [dockerfile, *sorted((sandbox_dir / "rootfs").rglob("*"))]
        digest_input = b"".join(
            str(path.relative_to(sandbox_dir)).encode() + b"\0" + path.read_bytes()
            for path in files if path.is_file()
        )
        image_tag = "pcg-identifiability-runtime:v1-" + _sha256(digest_input)[:16]
        existing = self.call(["image", "ls", "--quiet", image_tag], timeout=15).decode().splitlines()
        if existing:
            raise SandboxError("deterministic sandbox image tag already exists; refusing to replace it")
        self.image_tag = image_tag
        self.call([
            "buildx", "build", "--network=none", "--pull=false", "--no-cache",
            "--load", "--file", str(dockerfile), "--tag", self.image_tag,
            str(sandbox_dir),
        ], timeout=60)
        raw = self.call(["image", "inspect", "--format", "{{json .}}", self.image_tag])
        try:
            image = json.loads(raw)
            config = image["Config"]
            layers = image["RootFS"]["Layers"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise SandboxError("scratch image inspection failed") from error
        if config.get("Entrypoint") or config.get("Cmd") or config.get("Env"):
            raise SandboxError("scratch image contains an entrypoint, command, or environment")
        if not isinstance(layers, list) or len(layers) != 1:
            raise SandboxError("scratch image must contain exactly the local empty-rootfs layer")
        self.image_id = image.get("Id")
        if not isinstance(self.image_id, str) or not self.image_id.startswith("sha256:"):
            raise SandboxError("scratch image ID is missing")
        return self.image_tag, self.image_id

    def remove_empty_image(self):
        if self.image_tag:
            try:
                self.call(["image", "rm", self.image_tag], timeout=15)
                self.image_tag = None
                self.image_id = None
                return None
            except SandboxError as error:
                return str(error)
        return None


def _qualification_container(session: DockerSession, spec: dict,
                             name: str, timeout: int,
                             probe_deadline: float | None) -> dict:
    """Create, inspect, start, and confirm removal of one fixed probe container."""
    record = {"container_id": None, "config_valid": False,
              "return_code": None, "stdout": b"", "stderr": b"",
              "state": None, "removed": False, "absent_after_cleanup": False}
    container_id = None
    try:
        created = session.call(spec["argv"], timeout=15, deadline=probe_deadline)
        container_id = created.decode("ascii", "replace").strip()
        if not container_id:
            raise SandboxError("qualification container create returned no ID")
        record["container_id"] = container_id
        raw = session.call(["inspect", "--format", "{{json .}}", container_id],
                           timeout=10, deadline=probe_deadline)
        try:
            inspected = json.loads(raw)
            host_config = inspected["HostConfig"]
            container_config = inspected["Config"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise SandboxError("qualification container inspection is malformed") from error
        issues = validate_container_config(
            host_config, spec["resources"], spec["expected_binds"],
            container_config, spec["expected_command"], expected_working_dir="/",
        )
        if issues:
            raise SandboxError("qualification container configuration rejected: "
                               + "; ".join(issues))
        record["config_valid"] = True
        result = session.call_completed(
            ["start", "--attach", "--interactive", container_id],
            timeout=timeout, input_data=b"", deadline=probe_deadline,
        )
        record["return_code"] = result.returncode
        record["stdout"] = result.stdout
        record["stderr"] = result.stderr
        state_raw = session.call(["inspect", "--format", "{{json .State}}", container_id],
                                 timeout=10, deadline=session.deadline)
        try:
            record["state"] = json.loads(state_raw)
        except json.JSONDecodeError as error:
            raise SandboxError("qualification container state is invalid JSON") from error
    except (SandboxError, OSError, TypeError, KeyError, AttributeError) as error:
        record["error"] = type(error).__name__ + ": " + str(error)
    finally:
        if container_id:
            try:
                session.call(["rm", "--force", container_id], timeout=5)
                record["removed"] = True
            except SandboxError as error:
                record["cleanup_error"] = str(error)
            try:
                session.call(["inspect", container_id], timeout=5)
            except SandboxError as error:
                message = str(error).lower()
                if "no such container" in message or "no such object" in message:
                    record["absent_after_cleanup"] = True
                else:
                    prior = record.get("cleanup_error")
                    record["cleanup_error"] = "; ".join(
                        value for value in (prior, str(error)) if value
                    )
            else:
                record["cleanup_error"] = "; ".join(
                    value for value in (
                        record.get("cleanup_error"),
                        "qualification container still exists after cleanup",
                    ) if value
                )
    return record


def _probe_check_set() -> dict:
    return {name: "NOT_RUN" for name in QUALIFICATION_CHECKS}


def run_qualification_probe(session: DockerSession, resources: dict) -> dict:
    """Run a fixed, non-research capability probe before any method slot starts."""
    checks = _probe_check_set()
    report = {
        "schema_version": 1,
        "probe_id": QUALIFICATION_PROBE_ID,
        "status": "NOT_VERIFIED",
        "script_sha256": _sha256((_QUALIFICATION_DIAGNOSTIC_PROGRAM
                                   + _QUALIFICATION_OOM_PROGRAM).encode("utf-8")),
        "image_id": getattr(session, "image_id", None),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "observed": {"resources": dict(resources)},
    }
    diagnostic = None
    oom = None
    try:
        probe_deadline = (session.deadline - CLEANUP_RESERVE_SECONDS
                          if session.deadline is not None else None)
        if not isinstance(report["image_id"], str) or not report["image_id"].startswith("sha256:"):
            raise SandboxError("qualification probe has no inspected scratch image ID")
        host_memory = session.info.get("memory_bytes")
        if isinstance(host_memory, bool) or not isinstance(host_memory, int):
            raise SandboxError("qualification host memory capacity is unavailable")
        if host_memory < 256 * 1024 * 1024:
            raise SandboxError("host memory is below the fixed qualification probe minimum")
        if resources.get("memory_bytes", 0) < QUALIFICATION_MEMORY_BYTES:
            raise SandboxError("task memory limit is below the fixed probe's Python runtime minimum")

        runtime_prefix, python_relative_path, library_dirs = _runtime_layout()
        nonce = format(time.monotonic_ns(), "x")
        with tempfile.TemporaryDirectory(prefix="pcg-qualification-", dir="/tmp") as temp:
            temp_dir = Path(temp)
            canary = temp_dir / "host-only-canary.bin"
            canary_bytes = os.urandom(32)
            canary.write_bytes(canary_bytes)
            baseline = _host_canary_baseline(canary, canary_bytes)
            report["observed"]["host_canary_baseline"] = baseline
            expected = {key: resources[key] for key in (
                "cpu_quota_millis", "memory_bytes", "pids_limit")}
            expected["host_file_baseline_readable"] = baseline["readable"] is True
            expected["host_file_sha256"] = baseline["sha256"]
            diagnostic_program = _QUALIFICATION_DIAGNOSTIC_PROGRAM
            diag_spec = build_qualification_container_spec(
                session.image_tag, resources, "pcg-qual-diag-" + nonce,
                str(temp_dir / "diag.cid"), runtime_prefix, python_relative_path,
                library_dirs, diagnostic_program,
                [json.dumps(expected, sort_keys=True), str(canary)],
            )
            diag_spec["resources"] = resources
            diagnostic = _qualification_container(
                session, diag_spec, "pcg-qual-diag-" + nonce, timeout=15,
                probe_deadline=probe_deadline)
            report["observed"]["diagnostic_container"] = {
                key: diagnostic.get(key) for key in (
                    "container_id", "config_valid", "return_code", "state",
                    "removed", "absent_after_cleanup", "error", "cleanup_error")
            }
            if (diagnostic["config_valid"] and diagnostic["return_code"] == 0
                    and isinstance(diagnostic.get("state"), dict)
                    and diagnostic["state"].get("ExitCode") == 0
                    and diagnostic["state"].get("OOMKilled") is False):
                try:
                    output = json.loads(diagnostic["stdout"].decode("utf-8"))
                    observed_checks = output["checks"]
                    actual = output["actual"]
                except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
                    observed_checks, actual = {}, {}
                mapping = {
                    "host_file_baseline_readable": "host_file_baseline_readable",
                    "host_file_unreadable": "host_file_unreadable",
                    "network_positive_control": "network_positive_control",
                    "network_unavailable": "network_unavailable",
                    "effective_cpu_quota": "effective_cpu_quota",
                    "effective_memory_limit": "effective_memory_limit",
                    "effective_memory_swap_limit": "effective_memory_swap_limit",
                    "effective_pid_limit": "effective_pid_limit",
                }
                for output_key, report_key in mapping.items():
                    checks[report_key] = "PASS" if observed_checks.get(output_key) is True else "FAIL"
                report["observed"]["effective_resources"] = actual
                report["observed"]["diagnostic_probes"] = output["probes"]
                checks["container_config"] = "PASS"
            else:
                checks["container_config"] = "PASS" if diagnostic["config_valid"] else "FAIL"
                for key in ("host_file_baseline_readable", "host_file_unreadable",
                            "network_positive_control", "network_unavailable",
                            "effective_cpu_quota", "effective_memory_limit",
                            "effective_memory_swap_limit", "effective_pid_limit"):
                    checks[key] = "FAIL"

            diag_clean = diagnostic["removed"] and diagnostic["absent_after_cleanup"]
            checks["probe_container_cleanup"] = "PASS" if diag_clean else "FAIL"
            if all(checks[key] == "PASS" for key in (
                    "container_config", "host_file_baseline_readable",
                    "host_file_unreadable", "network_positive_control", "network_unavailable",
                    "effective_cpu_quota", "effective_memory_limit",
                    "effective_memory_swap_limit", "effective_pid_limit",
                    "probe_container_cleanup")):
                oom_resources = dict(resources)
                oom_resources["memory_bytes"] = QUALIFICATION_MEMORY_BYTES
                oom_resources["pids_limit"] = min(resources["pids_limit"], 16)
                oom_spec = build_qualification_container_spec(
                    session.image_tag, oom_resources, "pcg-qual-oom-" + nonce,
                    str(temp_dir / "oom.cid"), runtime_prefix, python_relative_path,
                    library_dirs, _QUALIFICATION_OOM_PROGRAM,
                    [str(QUALIFICATION_MEMORY_BYTES)],
                )
                oom_spec["resources"] = oom_resources
                oom = _qualification_container(
                    session, oom_spec, "pcg-qual-oom-" + nonce, timeout=15,
                    probe_deadline=probe_deadline)
                state = oom.get("state") or {}
                marker_seen = oom.get("stdout", b"").startswith(b"PCG_OOM_PROBE_READY\n")
                checks["memory_overlimit_killed"] = (
                    "PASS" if oom["config_valid"] and state.get("OOMKilled") is True
                    and state.get("ExitCode") == 137 and oom.get("return_code") in (137, 1)
                    and marker_seen
                    else "FAIL")
                report["observed"]["oom_container"] = {
                    key: oom.get(key) for key in (
                        "container_id", "config_valid", "return_code", "state",
                        "removed", "absent_after_cleanup", "error", "cleanup_error")
                }
                report["observed"]["oom_container"]["overlimit_marker_seen"] = marker_seen
                checks["probe_container_cleanup"] = (
                    "PASS" if diag_clean and oom["removed"] and oom["absent_after_cleanup"]
                    else "FAIL")
            else:
                checks["memory_overlimit_killed"] = "NOT_RUN"

        report["status"] = ("VERIFIED" if all(checks[name] == "PASS"
                                              for name in QUALIFICATION_CHECKS)
                            else "NOT_VERIFIED")
    except (SandboxError, OSError, TypeError, KeyError, ValueError, AttributeError) as error:
        report["error"] = type(error).__name__ + ": " + str(error)
    report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    return report


def validate_qualification_evidence(report: dict, resources: dict,
                                    image_id: str | None = None) -> bool:
    """Accept only a complete report from this fixed probe and exact profile."""
    if (not isinstance(report, dict) or isinstance(report.get("schema_version"), bool)
            or report.get("schema_version") != 1):
        return False
    if report.get("probe_id") != QUALIFICATION_PROBE_ID or report.get("status") != "VERIFIED":
        return False
    if (not isinstance(report.get("script_sha256"), str)
            or report["script_sha256"] != _sha256((_QUALIFICATION_DIAGNOSTIC_PROGRAM
                                                   + _QUALIFICATION_OOM_PROGRAM).encode("utf-8"))):
        return False
    expected_image = image_id or report.get("image_id")
    if (not isinstance(expected_image, str) or not expected_image.startswith("sha256:")
            or report.get("image_id") != expected_image):
        return False
    try:
        completed_at = datetime.fromisoformat(str(report.get("completed_at_utc")).replace("Z", "+00:00"))
    except ValueError:
        return False
    if completed_at.tzinfo is None:
        return False
    checks = report.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(QUALIFICATION_CHECKS):
        return False
    if any(checks.get(name) != "PASS" for name in QUALIFICATION_CHECKS):
        return False
    observed = report.get("observed")
    observed_resources = observed.get("resources") if isinstance(observed, dict) else None
    if (not isinstance(observed_resources, dict)
            or set(observed_resources) != set(resources)
            or any(type(observed_resources.get(key)) is not int
                   or type(value) is not int or observed_resources[key] != value
                   for key, value in resources.items())):
        return False
    host_baseline = observed.get("host_canary_baseline")
    if (not isinstance(host_baseline, dict)
            or set(host_baseline) != {"effective_uid", "effective_gid", "readable",
                                      "sha256", "errno", "reason"}
            or type(host_baseline.get("effective_uid")) is not int
            or host_baseline.get("effective_uid") != 65534
            or type(host_baseline.get("effective_gid")) is not int
            or host_baseline.get("effective_gid") != 65534
            or host_baseline.get("readable") is not True
            or not isinstance(host_baseline.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", host_baseline["sha256"])
            or host_baseline.get("errno") is not None
            or host_baseline.get("reason") is not None):
        return False
    probes = observed.get("diagnostic_probes")
    if (not isinstance(probes, dict) or set(probes) != {"host_file", "network"}
            or not isinstance(probes.get("host_file"), dict)
            or set(probes["host_file"]) != {"readable", "errno", "reason", "sha256"}
            or probes["host_file"].get("readable") is not False
            or type(probes["host_file"].get("errno")) is not int
            or probes["host_file"].get("errno") != errno.ENOENT
            or probes["host_file"].get("reason") != "PATH_NOT_VISIBLE"
            or probes["host_file"].get("sha256") is not None):
        return False
    network = probes.get("network") if isinstance(probes, dict) else None
    if (not isinstance(network, dict)
            or set(network) != {"positive_control", "external_control"}):
        return False
    positive = network.get("positive_control")
    external = network.get("external_control")
    if (not isinstance(positive, dict)
            or set(positive) != {"connected", "errno", "reason"}
            or positive.get("connected") is not True
            or type(positive.get("errno")) is not int
            or positive.get("errno") != 0
            or positive.get("reason") != "CONNECTED"
            or not isinstance(external, dict)
            or set(external) != {"connected", "errno", "reason"}
            or external.get("connected") is not False
            or type(external.get("errno")) is not int
            or external.get("errno") not in (errno.ENETUNREACH, errno.EHOSTUNREACH)
            or external.get("reason") != "NETWORK_UNREACHABLE"):
        return False
    actual = observed.get("effective_resources")
    diagnostic = observed.get("diagnostic_container")
    oom = observed.get("oom_container")
    resource_pairs = (
        ("cpu_quota_millis", resources.get("cpu_quota_millis")),
        ("memory_bytes", resources.get("memory_bytes")),
        ("memory_swap_bytes", 0),
        ("pids_limit", resources.get("pids_limit")),
    )
    if not (isinstance(actual, dict)
            and all(type(actual.get(name)) is int and type(expected) is int
                    and actual[name] == expected for name, expected in resource_pairs)
            and isinstance(diagnostic, dict) and isinstance(oom, dict)):
        return False
    diag_state = diagnostic.get("state")
    oom_state = oom.get("state")
    return (diagnostic.get("config_valid") is True
            and type(diagnostic.get("return_code")) is int
            and diagnostic.get("return_code") == 0
            and isinstance(diag_state, dict)
            and type(diag_state.get("ExitCode")) is int and diag_state.get("ExitCode") == 0
            and diag_state.get("OOMKilled") is False
            and diag_state.get("Running") is False and diag_state.get("Status") == "exited"
            and diagnostic.get("removed") is True
            and diagnostic.get("absent_after_cleanup") is True
            and diagnostic.get("error") is None
            and diagnostic.get("cleanup_error") is None
            and oom.get("config_valid") is True
            and type(oom.get("return_code")) is int and oom.get("return_code") in (1, 137)
            and isinstance(oom_state, dict)
            and type(oom_state.get("ExitCode")) is int and oom_state.get("ExitCode") == 137
            and oom_state.get("OOMKilled") is True
            and oom_state.get("Running") is False and oom_state.get("Status") == "exited"
            and oom.get("removed") is True
            and oom.get("absent_after_cleanup") is True
            and oom.get("error") is None
            and oom.get("cleanup_error") is None
            and oom.get("overlimit_marker_seen") is True)


def _valid_manifest(manifest: dict) -> list[str]:
    issues = []
    if manifest.get("task_id") != TASK_ID:
        issues.append("task_id does not match the reviewed plan")
    if manifest.get("planned_method_invocations") != PLANNED_SLOTS:
        issues.append("planned_method_invocations must remain 80")
    if manifest.get("method_order") != METHOD_ORDER:
        issues.append("method order must remain M0-M3")
    case_ids = manifest.get("case_ids")
    if (not isinstance(case_ids, list) or len(case_ids) != 4
            or any(not isinstance(value, str) for value in case_ids)
            or len(set(case_ids)) != 4):
        issues.append("manifest must bind four unique opaque case IDs")
    elif any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value)
             for value in case_ids):
        issues.append("case IDs must remain opaque 128-bit lowercase hexadecimal values")
    if case_ids != list(CASE_ID_ORDER):
        issues.append("case IDs do not match the four cases pinned to the reviewed plan")
    if manifest.get("cpu_quota_basis") != "one_cpu_serial_slots":
        issues.append("CPU execution basis must remain one serial CPU")
    if manifest.get("resource_profile_status") not in (
            "PRE_REGISTERED", "BLOCKED_MISSING_VALUES"):
        issues.append("resource_profile_status must be PRE_REGISTERED or BLOCKED_MISSING_VALUES")
    opaque_ids = manifest.get("opaque_case_ids")
    if (not isinstance(opaque_ids, dict)
            or set(opaque_ids) != {"A", "B", "C", "D"}
            or any(not isinstance(value, str) for value in opaque_ids.values())
            or len(set(opaque_ids.values())) != 4
            or list(opaque_ids.values()) != case_ids):
        issues.append("opaque case IDs must bind exactly the four planned arms")
    if opaque_ids != CASE_IDS_BY_ARM:
        issues.append("opaque case-to-arm binding differs from the reviewed plan")
    if manifest.get("pair_inputs_path") != "PAIR_METHOD_INPUTS.json":
        issues.append("paired method input path differs from the pinned package file")
    if not isinstance(manifest.get("pair_inputs_sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", manifest["pair_inputs_sha256"]):
        issues.append("paired method input SHA-256 is missing or invalid")
    if manifest.get("public_input_sha256") != "905d0670f9693217ef4713f39378c29a07e5213f1c43abf2f527d55f31cd1de9":
        issues.append("pinned public input SHA-256 differs from the reviewed plan")
    if not isinstance(manifest.get("execution_file_hashes"), dict):
        issues.append("execution source hash pins are missing")
    elif (not manifest["execution_file_hashes"]
          or any(not isinstance(relative, str) or relative.startswith("/")
                 for relative in manifest["execution_file_hashes"])
          or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                 for value in manifest["execution_file_hashes"].values())):
        issues.append("execution source pins must be lowercase SHA-256 values")
    expected_source_pins = {
        "frozen_source/runtime/methods.py": "9e1a7f6da7b03c2f4832916fd49130f89feac9f2648e8ee2b3bed8ffcdaf6343",
        "frozen_source/runtime/shared_context.py": "fb46e5040fe91f7337fdd5cb585673e8fc9ee3cbb3fb5dc2e0e1604fab90029e",
        "frozen_source/runtime/worker.py": "5a904a8a877c3f7b2673fc2464cfaf57f80af4176780eb556acc35ca01fcaff7",
    }
    if isinstance(manifest.get("execution_file_hashes"), dict):
        for relative, expected in expected_source_pins.items():
            if manifest["execution_file_hashes"].get(relative) != expected:
                issues.append("pinned method/gate source differs from reviewed commit: " + relative)
    if manifest.get("source_commits") != {
        "public_input": "910302bac55487a542c656288d8202bd950e1b56",
        "methods_and_gate": "ed463fa208d3fcadf5c8cb1e0c4505f64d4e7ca2",
    }:
        issues.append("pinned source commits differ from the reviewed plan")
    schema_hashes = manifest.get("schema_hashes")
    expected_schemas = {
        "pair-inputs.schema.json", "method-result.schema.json", "attempt.schema.json", "score.schema.json",
        "return-validation.schema.json", "task-manifest.schema.json",
        "oracle-case-map.schema.json",
    }
    if not isinstance(schema_hashes, dict) or set(schema_hashes) != expected_schemas:
        issues.append("all five schema file pins are required")
    elif any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
             for value in schema_hashes.values()):
        issues.append("schema hashes must be lowercase SHA-256 values")
    if manifest.get("oracle_sha256") != "f41cddf14c1905b5358280445efbd542685fa1e2cfb61d6dc78274ec42fda902":
        issues.append("physical oracle pin differs from the reviewed plan")
    if not isinstance(manifest.get("oracle_case_map_sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", manifest["oracle_case_map_sha256"]):
        issues.append("scorer-only oracle case-map SHA-256 is missing")
    if not isinstance(manifest.get("plan_sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", manifest["plan_sha256"]):
        issues.append("reviewed plan SHA-256 is missing")
    return issues


def preflight_task(manifest_path, package_dir=None) -> dict:
    manifest_path = Path(manifest_path).resolve()
    try:
        manifest_bytes, manifest = _read_json(manifest_path, "task manifest")
    except ValueError as error:
        return _blocked(str(error))
    profile = validate_resource_profile(manifest)
    issues = _valid_manifest(manifest)
    if profile.status == "READY" and manifest.get("resource_profile_status") != "PRE_REGISTERED":
        issues.append("complete resource values require PRE_REGISTERED status")
    if profile.status != "READY" and manifest.get("resource_profile_status") != "BLOCKED_MISSING_VALUES":
        issues.append("incomplete resource values require BLOCKED_MISSING_VALUES status")
    if profile.status != "READY":
        reason = "resource limits are missing or invalid"
        if issues:
            reason += "; " + "; ".join(issues)
        return _blocked(reason,
                        (*profile.missing_fields, *profile.invalid_fields))
    if issues:
        return _blocked("; ".join(issues))
    package_dir = Path(package_dir or PACKAGE_DIR).resolve()
    source_path = package_dir / "frozen_source" / "public-input.json"
    pair_path = (package_dir / manifest["pair_inputs_path"]).resolve()
    try:
        public_bytes, public_input = _read_json(source_path, "pinned public input")
        pair_bytes, pair_inputs = _read_json(pair_path, "paired method input")
    except ValueError as error:
        return _blocked(str(error))
    if _sha256(public_bytes) != manifest["public_input_sha256"]:
        return _blocked("pinned public input SHA-256 mismatch")
    if _sha256(pair_bytes) != manifest["pair_inputs_sha256"]:
        return _blocked("paired method input SHA-256 mismatch")
    try:
        expected_pairs = build_pair_cases(public_input, manifest["opaque_case_ids"])
    except (TypeError, ValueError) as error:
        return _blocked("paired input reconstruction failed: " + str(error))
    if pair_bytes != canonical_json_bytes(expected_pairs) + b"\n":
        return _blocked("paired method input differs from the frozen A/B/C/D specification")
    if [case.get("case_id") for case in pair_inputs.get("cases", [])] != manifest["case_ids"]:
        return _blocked("paired method input case IDs do not match the manifest")
    for relative, expected in manifest["execution_file_hashes"].items():
        path = (package_dir / relative).resolve()
        if not path.is_relative_to(package_dir) or not path.is_file():
            return _blocked("execution source pin is missing or outside the package: " + relative)
        if _sha256(path.read_bytes()) != expected:
            return _blocked("execution source SHA-256 mismatch: " + relative)
    for filename, expected in manifest["schema_hashes"].items():
        path = package_dir / "schemas" / filename
        if not path.is_file() or _sha256(path.read_bytes()) != expected:
            return _blocked("schema SHA-256 mismatch: " + filename)
    plan_path = package_dir.parent / "PLAN.md"
    if not plan_path.is_file() or _sha256(plan_path.read_bytes()) != manifest["plan_sha256"]:
        return _blocked("reviewed task plan SHA-256 mismatch")
    runtime_dir = package_dir / "frozen_source" / "runtime"
    runtime_paths = list(runtime_dir.rglob("*"))
    runtime_files = {path.name for path in runtime_paths if path.is_file()}
    if (runtime_files != {"methods.py", "shared_context.py", "worker.py", "slot_worker.py"}
            or any(not path.is_file() for path in runtime_paths)):
        return _blocked("method runtime mount contains an unexpected file set")
    return {
        "task_status": "READY",
        "manifest_sha256": _sha256(manifest_bytes),
        "manifest": manifest,
        "manifest_path": manifest_path,
        "package_dir": package_dir,
        "pair_inputs": pair_inputs,
        "issues": [],
    }


def run_task(manifest_path, run_id: str, output_root) -> dict:
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id) or ".." in run_id:
        return _blocked("run ID is invalid", run_id=run_id)
    output_root = Path(output_root)
    run_dir = output_root / run_id
    if run_dir.exists():
        return _blocked("run ID already exists; attempts cannot be retried or overwritten", run_id)
    preflight = preflight_task(manifest_path)
    if preflight["task_status"] != "READY":
        preflight["run_id"] = run_id
        return preflight
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        if not output_root.is_dir():
            return _blocked("output root is not a directory", run_id=run_id)
    except (OSError, TypeError):
        return _blocked("output root cannot be prepared", run_id=run_id)
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".pcg-write-check-",
                                         dir=output_root, delete=True) as probe:
            probe.write(b"write check")
            probe.flush()
            os.fsync(probe.fileno())
    except OSError:
        return _blocked("output root is not writable", run_id=run_id)

    task_started = time.monotonic()
    task_started_at_utc = datetime.now(timezone.utc).isoformat()
    session = None
    try:
        session = DockerSession(
            preflight["package_dir"],
            deadline=task_started + preflight["manifest"]["resources"]["wall_seconds"],
        )
        session.validate_resources(preflight["manifest"]["resources"])
        image_tag, image_id = session.prepare_empty_image()
        preflight["sandbox_image_tag"] = image_tag
        preflight["sandbox_image_id"] = image_id
        qualification = run_qualification_probe(session, preflight["manifest"]["resources"])
        if not validate_qualification_evidence(
                qualification, preflight["manifest"]["resources"], image_id):
            failed_checks = [name for name in QUALIFICATION_CHECKS
                             if qualification.get("checks", {}).get(name) != "PASS"]
            cleanup_error = _remove_sandbox_image_once(session)
            session.close()
            reason = "sandbox qualification was not verified"
            if failed_checks:
                reason += ": " + ", ".join(failed_checks)
            if qualification.get("error"):
                reason += "; " + qualification["error"]
            if cleanup_error:
                reason += "; sandbox image cleanup failed: " + cleanup_error
                qualification["sandbox_image_cleanup"] = "FAILED"
            else:
                qualification["sandbox_image_cleanup"] = "REMOVED"
            blocked = _blocked(reason, run_id=run_id)
            blocked["qualification_evidence"] = qualification
            return blocked
        preflight["qualification_evidence"] = qualification
    except (SandboxError, OSError) as error:
        if session is not None:
            cleanup_error = session.remove_empty_image()
            session.close()
            if cleanup_error:
                error = SandboxError(str(error) + "; sandbox image cleanup failed: " + cleanup_error)
        return _blocked("sandbox preflight blocked: " + str(error), run_id=run_id)

    try:
        run_dir.mkdir(exist_ok=False)
    except OSError:
        session.remove_empty_image()
        session.close()
        return _blocked("run ID already exists or cannot be exclusively reserved", run_id=run_id)
    intent = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "attempt_count": 1,
        "state": "IN_PROGRESS",
        "manifest_sha256": preflight["manifest_sha256"],
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "sandbox_image_id": image_id,
        "qualification_evidence": preflight["qualification_evidence"],
    }
    try:
        (run_dir / "intent.json").write_bytes(canonical_bytes(intent) + b"\n")
    except OSError as error:
        session.remove_empty_image()
        session.close()
        return _blocked("could not persist single-attempt intent: " + str(error), run_id=run_id)
    try:
        report = _execute_task(preflight, run_id, output_root, run_dir, session,
                               task_started, task_started_at_utc)
    finally:
        _remove_sandbox_image_once(session)
        session.close()
    report["attempt_wall_seconds_elapsed"] = max(0.0, time.monotonic() - task_started)
    report["attempt_finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["wall_seconds_scope"] = WALL_SECONDS_SCOPE
    return report


def preflight_only(manifest_path) -> dict:
    """Check pins, daemon controls, and fixed sandbox qualification without a run."""
    result = preflight_task(manifest_path)
    if result["task_status"] != "READY":
        result["method_invocations_started"] = 0
        result["completed_method_invocations"] = 0
        result["planned_method_invocations"] = PLANNED_SLOTS
        result["research_acceptance"] = "NOT_EVALUATED"
        result["exit_code"] = 20
        return result
    session = None
    try:
        wall_limit = result["manifest"]["resources"]["wall_seconds"]
        session = DockerSession(result["package_dir"], deadline=time.monotonic() + wall_limit)
        session.validate_resources(result["manifest"]["resources"])
        image_tag, image_id = session.prepare_empty_image()
        qualification = run_qualification_probe(session, result["manifest"]["resources"])
        if not validate_qualification_evidence(
                qualification, result["manifest"]["resources"], image_id):
            failed_checks = [name for name in QUALIFICATION_CHECKS
                             if qualification.get("checks", {}).get(name) != "PASS"]
            raise SandboxError("sandbox qualification was not verified: "
                               + ", ".join(failed_checks))
        cleanup_error = _remove_sandbox_image_once(session)
        if cleanup_error:
            qualification["status"] = "NOT_VERIFIED"
            qualification["error"] = "sandbox image cleanup failed: " + cleanup_error
            raise SandboxError(qualification["error"])
        return {
            "task_status": "READY",
            "research_acceptance": "NOT_EVALUATED",
            "planned_method_invocations": PLANNED_SLOTS,
            "method_start_requests": 0,
            "method_invocations_started": 0,
            "completed_method_invocations": 0,
            "partial": False,
            "stop_reason": None,
            "sandbox_preflight": "LOCAL_DOCKER_CGROUP_V2_SECCOMP_QUALIFICATION_CHECKED",
            "qualification_evidence": qualification,
            "sandbox_image_cleanup": "REMOVED",
            "docker_server_version": session.info["server_version"],
            "docker_cgroup_version": session.info["cgroup_version"],
            "docker_required_resource_capabilities": session.info["required_resource_capabilities"],
            "exit_code": 0,
        }
    except (SandboxError, OSError) as error:
        cleanup_error = _remove_sandbox_image_once(session) if session is not None else None
        blocked = _blocked("sandbox preflight blocked: " + str(error))
        if "qualification" in locals():
            if cleanup_error:
                qualification["sandbox_image_cleanup"] = "FAILED"
                qualification["error"] = (qualification.get("error", "")
                                           + "; sandbox image cleanup failed: " + cleanup_error).strip("; ")
            elif session is not None:
                qualification["sandbox_image_cleanup"] = "REMOVED"
            blocked["qualification_evidence"] = qualification
        if cleanup_error:
            blocked["stop_reason"] += "; sandbox image cleanup failed: " + cleanup_error
        return blocked
    finally:
        if session is not None:
            _remove_sandbox_image_once(session)
            session.close()


class _StopRun(RuntimeError):
    def __init__(self, reason: str, status: str):
        super().__init__(reason)
        self.status = status


def _runtime_layout():
    prefix = Path(sys.prefix).resolve()
    executable = Path(sys.executable).resolve()
    try:
        relative_executable = executable.relative_to(prefix).as_posix()
        Path(sysconfig.get_path("stdlib")).resolve().relative_to(prefix)
    except ValueError as error:
        raise SandboxError("Python executable and standard library must share a bindable prefix") from error
    library_dirs = []
    for host_path, destination in (("/lib", "/lib"), ("/lib64", "/lib64"),
                                   ("/usr/lib", "/usr/lib")):
        path = Path(host_path)
        if path.exists():
            library_dirs.append((str(path.resolve()), destination))
    return str(prefix), relative_executable, library_dirs


def _append_event(event_path: Path, event: dict) -> None:
    event = dict(event)
    event.setdefault("event_at_utc", datetime.now(timezone.utc).isoformat())
    with event_path.open("ab") as stream:
        stream.write(canonical_bytes(event) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def _mark_persistence_failure(outcome, label, error):
    if error is None:
        return outcome
    outcome["status"] = "FAIL"
    suffix = label + ": " + str(error)
    outcome["error"] = (outcome.get("error") + "; " + suffix
                        if outcome.get("error") else suffix)
    return outcome


def _record_ab_pair_result(reference_by_slot, case_id, prefix, method,
                           input_sha256, output_sha256):
    key = (prefix, method)
    if case_id == CASE_IDS_BY_ARM["A"]:
        reference_by_slot[key] = (input_sha256, output_sha256)
        return None
    if case_id != CASE_IDS_BY_ARM["B"]:
        return None
    expected = reference_by_slot.get(key)
    if expected is None:
        return "AB_PROTOCOL_FAILURE: matching A output is missing"
    if expected != (input_sha256, output_sha256):
        return "AB_PROTOCOL_FAILURE: paired A/B input or output mismatch"
    return None


def _write_progress(run_dir: Path, value: dict) -> None:
    value = dict(value)
    value["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    target = run_dir / "progress.json"
    temporary = run_dir / ".progress.json.tmp"
    with temporary.open("wb") as stream:
        stream.write(canonical_bytes(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)


def _validate_method_result(result: dict, visible_rows: list[dict]) -> None:
    expected_ids = {row["id"] for row in visible_rows if row.get("alarm") is True}
    try:
        validate_result(result, expected_ids)
        canonical_bytes(result)
    except (ResultContractError, ValueError, TypeError) as error:
        raise SandboxError(str(error)) from error


def _inspect_container_state(session: DockerSession, container_id: str,
                             deadline: float | None = None) -> dict:
    raw = session.call(["inspect", "--format", "{{json .State}}", container_id],
                       timeout=10, deadline=deadline)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise SandboxError("Docker container state is invalid JSON") from error


def _fail_timed_out_container(session, container_id: str, process,
                              outcome: dict) -> dict:
    """Fail the slot and use only the preregistered post-method cleanup reserve."""
    outcome["status"] = "FAIL"
    outcome["start_unknown"] = True
    outcome.setdefault("error", "WALL_LIMIT_EXCEEDED")
    cleanup_errors = []
    try:
        session.call(["kill", container_id], timeout=2)
    except SandboxError as error:
        cleanup_errors.append("container kill failed: " + str(error))
    if process is not None and process.poll() is None:
        try:
            process.kill()
            process.wait(timeout=1)
        except (OSError, subprocess.SubprocessError) as error:
            cleanup_errors.append("Docker start client termination failed: " + str(error))
    try:
        session.call(["rm", "--force", container_id], timeout=3)
        outcome["container_cleanup_status"] = "REMOVED"
    except SandboxError as error:
        outcome["container_cleanup_status"] = "FAILED"
        cleanup_errors.append("container removal failed: " + str(error))
    if cleanup_errors:
        outcome["error"] += "; timeout cleanup: " + "; ".join(cleanup_errors)
    return outcome


def _run_slot(session: DockerSession, run_dir: Path, run_id: str,
              slot_number: int, case_id: str, prefix_number: int, method: str,
              payload: dict, visible_rows: list[dict], resources: dict,
              runtime_prefix: str, python_relative_path: str,
              source_dir: str, library_dirs: list[tuple[str, str]],
              output_budget: dict, deadline: float, event_path: Path) -> dict:
    if time.monotonic() >= deadline:
        return {"status": "FAIL", "started": False, "start_unknown": False,
                "start_requested": False,
                "error": "WALL_LIMIT_BEFORE_SLOT", "result": None}
    name = "pcg-" + run_id[:20] + "-s" + format(slot_number, "04d")
    cidfile = run_dir / ("container-" + format(slot_number, "04d") + ".cid")
    create_spec = build_container_spec(
        session.image_tag, resources, name, str(cidfile), runtime_prefix,
        python_relative_path, source_dir, library_dirs,
    )
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return {"status": "FAIL", "started": False, "start_unknown": False,
                "start_requested": False,
                "error": "WALL_LIMIT_BEFORE_CONTAINER_CREATE", "result": None}
    try:
        create_output = session.call(create_spec["argv"], timeout=min(15, remaining),
                                     deadline=deadline)
    except SandboxError as error:
        return {"status": "BLOCKED", "started": False, "start_unknown": False,
                "start_requested": False,
                "error": "CONTAINER_CREATE_FAILED: " + str(error), "result": None}
    container_id = create_output.decode("ascii", "replace").strip()
    if not container_id:
        return {"status": "BLOCKED", "started": False, "start_unknown": False,
                "start_requested": False,
                "error": "CONTAINER_CREATE_RETURNED_NO_ID", "result": None}

    def cleaned(outcome):
        try:
            session.call(["rm", "--force", container_id], timeout=5)
            outcome["container_cleanup_status"] = "REMOVED"
        except SandboxError as error:
            outcome["container_cleanup_status"] = "FAILED"
            outcome["status"] = "FAIL"
            suffix = "CONTAINER_CLEANUP_FAILED: " + str(error)
            outcome["error"] = (outcome.get("error") + "; " + suffix
                                if outcome.get("error") else suffix)
        return outcome

    try:
        _append_event(event_path, {
            "event": "CONTAINER_CREATED", "slot": slot_number, "case_id": case_id,
            "prefix": prefix_number, "method": method, "container_id": container_id,
            "create_argv": create_spec["argv"],
        })
    except OSError as error:
        return cleaned({"status": "BLOCKED", "started": False, "start_unknown": False,
                        "start_requested": False,
                        "container_id": container_id,
                        "error": "CONTAINER_EVENT_PERSIST_FAILED: " + str(error), "result": None})
    try:
        raw_config = session.call(["inspect", "--format", "{{json .}}", container_id],
                                  timeout=10, deadline=deadline)
        inspected = json.loads(raw_config)
        host_config = inspected["HostConfig"]
        container_config = inspected["Config"]
    except (SandboxError, json.JSONDecodeError) as error:
        return cleaned({"status": "BLOCKED", "started": False, "start_unknown": False,
                        "start_requested": False,
                        "container_id": container_id,
                        "error": "CONTAINER_CONFIG_INSPECT_FAILED: " + str(error),
                        "result": None})
    except (KeyError, TypeError) as error:
        return cleaned({"status": "BLOCKED", "started": False, "start_unknown": False,
                        "start_requested": False,
                        "container_id": container_id,
                        "error": "CONTAINER_CONFIG_INSPECT_MALFORMED: " + str(error),
                        "result": None})
    config_issues = validate_container_config(
        host_config, resources, create_spec["expected_binds"], container_config,
        create_spec["expected_command"],
    )
    inspected_summary = {
        "host_config": {
            key: host_config.get(key) for key in (
                "NanoCpus", "Memory", "MemorySwap", "PidsLimit", "ReadonlyRootfs",
                "NetworkMode", "Privileged", "PidMode", "IpcMode", "UsernsMode",
                "CgroupnsMode", "UTSMode",
                "CapDrop", "CapAdd", "SecurityOpt", "Binds", "Devices",
                "DeviceRequests", "Mounts", "VolumesFrom", "Tmpfs", "LogConfig",
            )
        },
        "container_config": {
            key: container_config.get(key) for key in (
                "User", "WorkingDir", "Env", "Entrypoint", "Cmd", "Tty",
                "AttachStdin", "OpenStdin", "AttachStdout", "AttachStderr",
            )
        },
    }
    try:
        _append_event(event_path, {
            "event": "CONTAINER_CONFIG_INSPECTED", "slot": slot_number,
            "case_id": case_id, "prefix": prefix_number, "method": method,
            "container_id": container_id, "validated": not config_issues,
            "issues": config_issues, "configuration": inspected_summary,
            "configuration_sha256": _sha256(canonical_bytes(inspected_summary)),
        })
    except OSError as error:
        return cleaned({"status": "BLOCKED", "started": False, "start_unknown": False,
                        "start_requested": False, "container_id": container_id,
                        "error": "CONTAINER_CONFIG_EVENT_PERSIST_FAILED: " + str(error),
                        "result": None})
    if config_issues:
        return cleaned({"status": "BLOCKED", "started": False, "start_unknown": False,
                        "start_requested": False,
                        "container_id": container_id,
                        "error": "CONTAINER_CONFIG_REJECTED: " + "; ".join(config_issues),
                        "result": None})
    if time.monotonic() >= deadline:
        return cleaned({"status": "FAIL", "started": False, "start_unknown": False,
                        "start_requested": False, "container_id": container_id,
                        "error": "WALL_LIMIT_BEFORE_SLOT_START", "result": None})
    stdout_path = run_dir / ("slot-" + format(slot_number, "04d") + ".stdout.bin")
    stderr_path = run_dir / ("slot-" + format(slot_number, "04d") + ".stderr.bin")
    slot_observed_start = output_budget["observed"]
    stdout_chunks, stderr_chunks = bytearray(), bytearray()
    stream_paths = {"stdout": stdout_path, "stderr": stderr_path}
    try:
        files = {name: stream_paths[name].open("xb") for name in stream_paths}
    except OSError as error:
        for path in stream_paths.values():
            if path.exists():
                path.unlink()
        return cleaned({"status": "FAIL", "started": False, "start_unknown": False,
                        "start_requested": False,
                        "container_id": container_id,
                        "error": "METHOD_OUTPUT_FILE_OPEN_FAILED: " + str(error),
                        "result": None})
    process = None
    stop_reason = None
    capture_persist_error = None
    cli_exit = None
    start_requested = False
    kill_requested = False
    try:
        _append_event(event_path, {
            "event": "METHOD_START_REQUESTED", "slot": slot_number,
            "case_id": case_id, "prefix": prefix_number, "method": method,
            "container_id": container_id,
        })
        process = session.popen(["start", "--attach", "--interactive", container_id])
        start_requested = True
        try:
            process.stdin.write(canonical_bytes(payload))
            process.stdin.close()
        except (BrokenPipeError, OSError):
            try:
                process.stdin.close()
            except OSError:
                pass

        selector = selectors.DefaultSelector()
        for stream, name_key in ((process.stdout, "stdout"), (process.stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name_key)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0 and not kill_requested:
                stop_reason = "WALL_LIMIT_EXCEEDED"
            if stop_reason is not None:
                if not kill_requested:
                    if stop_reason != "WALL_LIMIT_EXCEEDED":
                        try:
                            session.call(["kill", container_id], timeout=2,
                                         deadline=deadline)
                        except SandboxError:
                            pass
                    kill_requested = True
                    if process.poll() is None:
                        try:
                            process.kill()
                        except OSError:
                            pass
                stop_reason_killed = True
            else:
                stop_reason_killed = False
            if stop_reason_killed:
                wait_seconds = 0.05
            else:
                wait_seconds = min(0.1, remaining)
            ready = selector.select(wait_seconds)
            if not ready and process.poll() is not None:
                for stream in (process.stdout, process.stderr):
                    key = next((item for item in selector.get_map().values()
                                if item.fileobj is stream), None)
                    if key is not None:
                        try:
                            selector.unregister(stream)
                        except KeyError:
                            pass
                continue
            for key, _ in ready:
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output_budget["observed"] += len(chunk)
                room = max(0, output_budget["limit"] - output_budget["captured"])
                kept = chunk[:room]
                if kept:
                    files[key.data].write(kept)
                    files[key.data].flush()
                    output_budget["captured"] += len(kept)
                    if key.data == "stdout":
                        stdout_chunks.extend(kept)
                    else:
                        stderr_chunks.extend(kept)
                if len(kept) != len(chunk) and stop_reason is None:
                    stop_reason = "METHOD_OUTPUT_LIMIT_EXCEEDED"
        selector.close()
        try:
            cli_exit = process.wait(timeout=1 if stop_reason == "WALL_LIMIT_EXCEEDED" else 5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                cli_exit = process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                cli_exit = None
    except (OSError, SandboxError, subprocess.SubprocessError) as error:
        if process is not None and process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        return cleaned({"status": "FAIL", "started": False,
                        "start_unknown": process is not None,
                        "start_requested": start_requested,
                        "container_id": container_id,
                        "output_bytes_observed": output_budget["observed"] - slot_observed_start,
                        "error": "METHOD_ATTACH_OR_CAPTURE_FAILED: " + str(error),
                        "result": None})
    finally:
        for stream in files.values():
            try:
                stream.flush()
                os.fsync(stream.fileno())
            except OSError as error:
                if capture_persist_error is None:
                    capture_persist_error = error
            finally:
                try:
                    stream.close()
                except OSError as error:
                    if capture_persist_error is None:
                        capture_persist_error = error
    if time.monotonic() >= deadline and stop_reason is None:
        stop_reason = "WALL_LIMIT_EXCEEDED"
    if stop_reason == "WALL_LIMIT_EXCEEDED":
        timed_out = {
            "status": "FAIL", "started": False, "start_unknown": True,
            "start_requested": start_requested, "container_id": container_id,
            "cli_exit_code": cli_exit, "stdout_path": str(stdout_path.name),
            "stderr_path": str(stderr_path.name),
            "output_bytes_observed": output_budget["observed"] - slot_observed_start,
            "result": None,
        }
        try:
            _append_event(event_path, {
                "event": "METHOD_WALL_TIMEOUT", "slot": slot_number,
                "case_id": case_id, "prefix": prefix_number, "method": method,
                "container_id": container_id, "start_requested": start_requested,
            })
        except OSError as error:
            timed_out = _mark_persistence_failure(
                timed_out, "METHOD_TIMEOUT_EVENT_PERSIST_FAILED", error)
        timed_out = _mark_persistence_failure(
            timed_out, "METHOD_CAPTURE_PERSIST_FAILED", capture_persist_error)
        return _fail_timed_out_container(session, container_id, process, timed_out)
    try:
        state = _inspect_container_state(session, container_id, deadline=deadline)
    except SandboxError as error:
        return cleaned({"status": "FAIL", "started": False, "start_unknown": True,
                        "start_requested": start_requested,
                        "container_id": container_id, "cli_exit_code": cli_exit,
                        "stdout_path": str(stdout_path.name), "stderr_path": str(stderr_path.name),
                        "error": "CONTAINER_START_STATE_UNKNOWN: " + str(error), "result": None})
    started_at = state.get("StartedAt")
    started = isinstance(started_at, str) and not started_at.startswith("0001-01-01")
    base = {
        "status": "FAIL", "started": started, "start_unknown": False,
        "start_requested": start_requested,
        "container_id": container_id, "state": state, "cli_exit_code": cli_exit,
        "stdout_path": str(stdout_path.name), "stderr_path": str(stderr_path.name),
        "output_bytes_observed": output_budget["observed"] - slot_observed_start,
    }
    finish_event_error = None
    try:
        _append_event(event_path, {
            "event": "METHOD_PROCESS_FINISHED", "slot": slot_number,
            "case_id": case_id, "prefix": prefix_number, "method": method,
            "container_id": container_id, "started": started,
            "started_at": started_at, "container_exit_code": state.get("ExitCode"),
            "cli_exit_code": cli_exit, "oom_killed": state.get("OOMKilled", False),
            "stop_reason": stop_reason,
        })
    except OSError as error:
        finish_event_error = error
    if stop_reason is not None:
        base["status"] = "FAIL"
        base["error"] = stop_reason
        base = _mark_persistence_failure(
            base, "METHOD_FINISH_EVENT_PERSIST_FAILED", finish_event_error)
        return cleaned(_mark_persistence_failure(
            base, "METHOD_CAPTURE_PERSIST_FAILED", capture_persist_error))
    if not started:
        base["status"] = "FAIL" if finish_event_error is not None else "BLOCKED"
        base["error"] = "METHOD_START_NOT_CONFIRMED"
        base = _mark_persistence_failure(
            base, "METHOD_FINISH_EVENT_PERSIST_FAILED", finish_event_error)
        return cleaned(_mark_persistence_failure(
            base, "METHOD_CAPTURE_PERSIST_FAILED", capture_persist_error))
    if state.get("OOMKilled") is True:
        base["error"] = "MEMORY_LIMIT_EXCEEDED"
        base = _mark_persistence_failure(
            base, "METHOD_FINISH_EVENT_PERSIST_FAILED", finish_event_error)
        return cleaned(_mark_persistence_failure(
            base, "METHOD_CAPTURE_PERSIST_FAILED", capture_persist_error))
    if state.get("ExitCode") != 0 or cli_exit != 0:
        base["error"] = "METHOD_OR_CONTAINER_NONZERO_EXIT"
        base = _mark_persistence_failure(
            base, "METHOD_FINISH_EVENT_PERSIST_FAILED", finish_event_error)
        return cleaned(_mark_persistence_failure(
            base, "METHOD_CAPTURE_PERSIST_FAILED", capture_persist_error))
    try:
        result = json.loads(bytes(stdout_chunks))
        _validate_method_result(result, visible_rows)
    except (json.JSONDecodeError, SandboxError, UnicodeDecodeError) as error:
        base["error"] = "METHOD_OUTPUT_INVALID: " + str(error)
        base = _mark_persistence_failure(
            base, "METHOD_FINISH_EVENT_PERSIST_FAILED", finish_event_error)
        return cleaned(_mark_persistence_failure(
            base, "METHOD_CAPTURE_PERSIST_FAILED", capture_persist_error))
    base["status"] = "PASS"
    base["result"] = result
    base = _mark_persistence_failure(
        base, "METHOD_FINISH_EVENT_PERSIST_FAILED", finish_event_error)
    return cleaned(_mark_persistence_failure(
        base, "METHOD_CAPTURE_PERSIST_FAILED", capture_persist_error))


def _artifact_hashes(run_dir: Path, excluded: set[str]) -> list[dict]:
    records = []
    for path in sorted(run_dir.iterdir()):
        if not path.is_file() or path.name in excluded:
            continue
        raw = path.read_bytes()
        records.append({"path": path.name, "bytes": len(raw), "sha256": _sha256(raw)})
    return records


def _execute_task(preflight: dict, run_id: str, output_root: Path,
                  run_dir: Path, session: DockerSession,
                  task_started: float, task_started_at_utc: str) -> dict:
    manifest = preflight["manifest"]
    resources = manifest["resources"]
    run_started = task_started
    deadline = run_started + resources["wall_seconds"]
    method_deadline = deadline - CLEANUP_RESERVE_SECONDS
    started_at = task_started_at_utc
    case_ids = manifest["case_ids"]
    slots = []
    started_count = 0
    start_requests = 0
    completed_count = 0
    output_budget = {"captured": 0, "observed": 0,
                     "limit": resources["max_method_output_bytes"]}
    event_path = run_dir / "slot-events.jsonl"
    event_path.open("xb").close()
    progress_path = run_dir / "slots.progress.jsonl"
    progress_stream = progress_path.open("xb")
    stop_reason = None
    task_status = "PASS"
    start_unknown_slots = []
    child_records = []
    try:
        runtime_prefix, python_relative_path, library_dirs = _runtime_layout()
        source_dir = str((preflight["package_dir"] / "frozen_source" / "runtime").resolve())
        cases = {case["case_id"]: case["rows"] for case in preflight["pair_inputs"]["cases"]}
        previous = {(case_id, method): {} for case_id in case_ids for method in METHOD_ORDER}
        ab_reference_by_slot = {}
        slot_number = 0
        for case_id in case_ids:
            for prefix_number in range(1, 6):
                for method in METHOD_ORDER:
                    slot_number += 1
                    if time.monotonic() >= method_deadline:
                        raise _StopRun("WALL_LIMIT_BEFORE_SLOT", "FAIL")
                    if output_budget["captured"] >= output_budget["limit"]:
                        raise _StopRun("METHOD_OUTPUT_LIMIT_EXHAUSTED", "FAIL")
                    visible_rows = cases[case_id][:prefix_number]
                    payload = {"method": method, "prefix": visible_rows,
                               "old": previous[(case_id, method)]}
                    input_hash = _sha256(canonical_bytes(payload))
                    outcome = _run_slot(
                        session, run_dir, run_id, slot_number, case_id,
                        prefix_number, method, payload, visible_rows, resources,
                        runtime_prefix, python_relative_path, source_dir,
                        library_dirs, output_budget, method_deadline, event_path,
                    )
                    if outcome.get("start_requested") is True:
                        start_requests += 1
                    if outcome.get("started") is True:
                        started_count += 1
                    elif outcome.get("start_unknown") is True:
                        start_unknown_slots.append({"slot": slot_number, "case_id": case_id,
                                                    "prefix": prefix_number, "method": method})
                    record = {
                        "slot": slot_number, "case_id": case_id, "prefix": prefix_number,
                        "method": method, "status": outcome["status"],
                        "started": outcome.get("started", False),
                        "start_requested": outcome.get("start_requested", False),
                        "start_unknown": outcome.get("start_unknown", False),
                        "container_id": outcome.get("container_id"),
                        "container_cleanup_status": outcome.get("container_cleanup_status"),
                        "cli_exit_code": outcome.get("cli_exit_code"),
                        "container_exit_code": outcome.get("state", {}).get("ExitCode"),
                        "oom_killed": outcome.get("state", {}).get("OOMKilled", False),
                        "stdout_path": outcome.get("stdout_path"),
                        "stderr_path": outcome.get("stderr_path"),
                        "output_bytes_observed": outcome.get("output_bytes_observed", 0),
                        "error": outcome.get("error"),
                    }
                    child_records.append(record)
                    ab_protocol_failure = None
                    if outcome.get("result") is not None:
                        result = outcome["result"]
                        output_hash = _sha256(canonical_bytes(result))
                        ab_protocol_failure = _record_ab_pair_result(
                            ab_reference_by_slot, case_id, prefix_number, method,
                            input_hash, output_hash,
                        )
                        slot = {
                            "case_id": case_id,
                            "prefix": prefix_number,
                            "method": method,
                            "input_sha256": input_hash,
                            "output_sha256": output_hash,
                            "result": result,
                        }
                        line = canonical_bytes(slot) + b"\n"
                        progress_stream.write(line)
                        progress_stream.flush()
                        os.fsync(progress_stream.fileno())
                        slots.append(slot)
                        completed_count += 1
                        previous[(case_id, method)] = {
                            key: result[key] for key in ("cards", "risk", "priority")
                        }
                    _write_progress(run_dir, {
                        "run_id": run_id,
                        "state": "IN_PROGRESS",
                        "method_start_requests": start_requests,
                        "method_invocations_started": started_count,
                        "completed_method_invocations": completed_count,
                        "planned_method_invocations": PLANNED_SLOTS,
                        "output_bytes_captured": output_budget["captured"],
                    })
                    if outcome["status"] != "PASS":
                        task_status = outcome["status"]
                        stop_reason = outcome.get("error") or "METHOD_SLOT_FAILED"
                        raise _StopRun(stop_reason, task_status)
                    if ab_protocol_failure is not None:
                        raise _StopRun(ab_protocol_failure, "FAIL")
        if completed_count != PLANNED_SLOTS or started_count != PLANNED_SLOTS:
            raise _StopRun("INCOMPLETE_80_SLOT_PLAN", "FAIL")
    except _StopRun as error:
        task_status = error.status
        stop_reason = str(error)
    except (OSError, SandboxError, ValueError, KeyError, TypeError) as error:
        task_status = "FAIL" if started_count else "BLOCKED"
        stop_reason = "RUNNER_OR_SANDBOX_ERROR: " + type(error).__name__ + ": " + str(error)
    finally:
        progress_stream.flush()
        os.fsync(progress_stream.fileno())
        progress_stream.close()

    image_cleanup_error = _remove_sandbox_image_once(session)
    if image_cleanup_error:
        task_status = "FAIL" if task_status == "PASS" else task_status
        cleanup_reason = "SANDBOX_IMAGE_CLEANUP_FAILED: " + image_cleanup_error
        stop_reason = (stop_reason + "; " + cleanup_reason) if stop_reason else cleanup_reason
    elapsed = time.monotonic() - run_started
    sandbox_finished_at_utc = datetime.now(timezone.utc).isoformat()
    if task_status == "PASS" and elapsed > resources["wall_seconds"]:
        task_status = "FAIL"
        stop_reason = "WALL_LIMIT_EXCEEDED_DURING_SANDBOX_LIFECYCLE"
    partial = task_status != "PASS"
    final_slots_name = "slots.jsonl" if not partial else "slots.partial.jsonl"
    progress_path.rename(run_dir / final_slots_name)
    _write_progress(run_dir, {
        "run_id": run_id,
        "state": task_status,
        "method_start_requests": start_requests,
        "method_invocations_started": started_count,
        "completed_method_invocations": completed_count,
        "planned_method_invocations": PLANNED_SLOTS,
        "output_bytes_captured": output_budget["captured"],
        "stop_reason": stop_reason,
        "sandbox_image_cleanup": "REMOVED" if image_cleanup_error is None else "FAILED",
    })
    excluded = {"attempt.json", "OUTPUT_FREEZE.json", "slots.jsonl", "slots.partial.jsonl"}
    attempt = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "attempt_count": 1,
        "task_status": task_status,
        "terminal_exit_code": 0 if task_status == "PASS" else 20 if task_status == "BLOCKED" else 30,
        "research_acceptance": "NOT_EVALUATED",
        "planned_method_invocations": PLANNED_SLOTS,
        "method_start_requests": start_requests,
        "method_invocations_started": started_count,
        "completed_method_invocations": completed_count,
        "partial": partial,
        "stop_reason": stop_reason,
        "case_ids": case_ids,
        "method_order": METHOD_ORDER,
        "task_manifest_sha256": preflight["manifest_sha256"],
        "source_commits": manifest["source_commits"],
        "schema_hashes": manifest["schema_hashes"],
        "public_input_sha256": manifest["public_input_sha256"],
        "pair_inputs_sha256": manifest["pair_inputs_sha256"],
        "oracle_sha256": manifest["oracle_sha256"],
        "oracle_case_map_sha256": manifest["oracle_case_map_sha256"],
        "plan_sha256": manifest["plan_sha256"],
        "started_at_utc": started_at,
        "finished_at_utc": sandbox_finished_at_utc,
        "wall_seconds_elapsed": elapsed,
        "wall_seconds_scope": WALL_SECONDS_SCOPE,
        "cpu_quota_millis": resources["cpu_quota_millis"],
        "wall_seconds_limit": resources["wall_seconds"],
        "container_cleanup_reserve_seconds": CLEANUP_RESERVE_SECONDS,
        "memory_limit_bytes": resources["memory_bytes"],
        "pids_limit": resources["pids_limit"],
        "max_method_output_bytes": resources["max_method_output_bytes"],
        "method_output_bytes_captured": output_budget["captured"],
        "method_output_bytes_observed": output_budget["observed"],
        "peak_rss_bytes": "UNKNOWN",
        "cpu_usage_seconds": "UNKNOWN",
        "method_start_unknown_slots": start_unknown_slots,
        "slot_exit_records": child_records,
        "qualification_evidence": preflight["qualification_evidence"],
        "sandbox_image_cleanup": "REMOVED" if image_cleanup_error is None else "FAILED",
        "execution_environment": {
            "python_executable": str(Path(sys.executable).resolve()),
            "python_binary_sha256": _sha256(Path(sys.executable).resolve().read_bytes()),
            "python_version": sys.version,
            "platform": sys.platform,
            "docker_server_version": session.info["server_version"],
            "docker_cgroup_version": session.info["cgroup_version"],
            "docker_required_resource_capabilities": session.info["required_resource_capabilities"],
            "sandbox_image_id": preflight["sandbox_image_id"],
            "sandbox_endpoint_type": "local_unix_socket",
        },
        "command": list(sys.argv),
        "artifacts": _artifact_hashes(run_dir, excluded),
    }
    try:
        receipt = freeze_bundle(run_dir, slots, attempt)
    except (OSError, ValueError) as error:
        try:
            (run_dir / "RUNNER_FINALIZATION_ERROR.json").write_bytes(
                canonical_bytes({"error": type(error).__name__, "message": str(error)}) + b"\n"
            )
        except OSError:
            pass
        return {
            "task_status": "FAIL",
            "research_acceptance": "NOT_EVALUATED",
            "run_id": run_id,
            "planned_method_invocations": PLANNED_SLOTS,
            "method_invocations_started": started_count,
            "completed_method_invocations": completed_count,
            "partial": True,
            "stop_reason": "RUNNER_FINALIZATION_FAILED: " + str(error),
            "exit_code": 30,
        }
    exit_code = 0 if task_status == "PASS" else 20 if task_status == "BLOCKED" else 30
    return {
        "task_status": receipt["task_status"],
        "research_acceptance": receipt["research_acceptance"],
        "run_id": run_id,
        "planned_method_invocations": receipt["planned_method_invocations"],
        "method_start_requests": receipt["method_start_requests"],
        "method_invocations_started": receipt["method_invocations_started"],
        "completed_method_invocations": receipt["completed_method_invocations"],
        "partial": receipt["partial"],
        "stop_reason": receipt["stop_reason"],
        "output_sha256": receipt["output_sha256"],
        "qualification_evidence": receipt["qualification_evidence"],
        "wall_seconds_elapsed": receipt["wall_seconds_elapsed"],
        "wall_seconds_scope": WALL_SECONDS_SCOPE,
        "exit_code": exit_code,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-manifest", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--output-root")
    args = parser.parse_args(argv)
    if args.preflight_only:
        report = preflight_only(args.task_manifest)
    elif args.run_id and args.output_root:
        report = run_task(args.task_manifest, args.run_id, args.output_root)
    else:
        parser.error("--run-id and --output-root are required unless --preflight-only is used")
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
