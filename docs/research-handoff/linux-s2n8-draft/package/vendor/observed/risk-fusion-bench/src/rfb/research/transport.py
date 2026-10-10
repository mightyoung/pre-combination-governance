"""Injectable transports; OpenSSH is argv-only and strict-host-key by default."""

from __future__ import annotations

import hashlib
import json
import locale
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from rfb.contracts.canonical_json import canonical_bytes

from .files import _fsync_dir
from .runtime_binding import runtime_binding_args
from .runtime_bundle import (
    PinnedRuntimeBundle,
    RuntimeBundle,
    RuntimeBundleError,
    _publish_new_bytes,
    materialize_pinned_runtime_bundle,
)
from .worker import durable_tree_sync

_BOOTSTRAP_PREFLIGHT_SCRIPT = r"""import json, os, sys, time
from pathlib import Path
parent = Path(sys.argv[1])
if not parent.is_absolute() or ".." in parent.parts:
    raise SystemExit("RUN_ROOT_PARENT_INVALID")
current = parent
while True:
    if current.is_symlink():
        raise SystemExit("BOOTSTRAP_PARENT_INVALID")
    if current == current.parent:
        break
    current = current.parent
if not parent.is_dir():
    raise SystemExit("BOOTSTRAP_PARENT_INVALID")
usage = os.statvfs(parent)
print(json.dumps({
    "approved_remote_parent": str(parent),
    "parent": str(parent),
    "parent_device": os.stat(parent).st_dev,
    "parent_inode": os.stat(parent).st_ino,
    "mount_identity": f"device={os.stat(parent).st_dev}:anchor={parent.anchor}",
    "observed_at_ns": time.time_ns(),
    "filesystem_total_bytes": usage.f_frsize * usage.f_blocks,
    "filesystem_used_bytes": usage.f_frsize * usage.f_blocks - usage.f_frsize * usage.f_bfree,
    "filesystem_free_bytes": usage.f_frsize * usage.f_bavail,
    "capacity_available": usage.f_frsize * usage.f_bavail >= 265853007872,
    "remote_reserve_available": usage.f_frsize * usage.f_bavail >= 235853007872,
}, sort_keys=True))
"""

_CREATE_RUN_ROOT_SCRIPT = r"""import json, os, re, sys, time
from pathlib import Path
parent = Path(sys.argv[1])
run_id = sys.argv[2]
if not parent.is_absolute() or ".." in parent.parts:
    raise SystemExit("RUN_ROOT_PARENT_INVALID")
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id) or run_id in {".", ".."}:
    raise SystemExit("RUN_ID_INVALID")
root = parent / run_id
current = parent
while True:
    if current.is_symlink():
        raise SystemExit("RUN_ROOT_PARENT_INVALID")
    if current == current.parent:
        break
    current = current.parent
if not parent.is_dir():
    raise SystemExit("RUN_ROOT_PARENT_INVALID")
if root.exists() or root.is_symlink():
    raise SystemExit("RUN_ROOT_COLLISION")
try:
    root.mkdir()
except FileExistsError:
    raise SystemExit("RUN_ROOT_COLLISION")
runtime = root / ".runtime"
runtime.mkdir()
def sync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
sync(runtime)
sync(root)
sync(parent)
parent_stat = os.stat(parent)
root_stat = os.stat(root)
print(json.dumps({
    "remote_run_root": str(root),
    "approved_remote_parent": str(parent),
    "run_id": run_id,
    "parent_device": parent_stat.st_dev,
    "parent_inode": parent_stat.st_ino,
    "run_root_device": root_stat.st_dev,
    "run_root_inode": root_stat.st_ino,
    "mount_identity": f"device={root_stat.st_dev}:anchor={root.anchor}",
    "created_at_ns": time.time_ns(),
}, sort_keys=True))
"""

_SEAL_RUNTIME_SCRIPT = r"""import hashlib, json, os, stat, sys
from pathlib import Path
pairs = [
    (Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]),
    (Path(sys.argv[4]), Path(sys.argv[5]), sys.argv[6]),
]
def digest_nofollow(path):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        mode = os.fstat(fd).st_mode
        if not stat.S_ISREG(mode):
            raise SystemExit("RUNTIME_STAGE_VERIFY_FAILED")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)
    finally:
        os.close(fd)
def sync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
for partial, final, expected in pairs:
    if (not partial.is_absolute() or not final.is_absolute()
            or ".." in partial.parts or ".." in final.parts
            or partial.parent != final.parent):
        raise SystemExit("RUNTIME_STAGE_VERIFY_FAILED")
    try:
        partial_stat = os.lstat(partial)
    except OSError:
        raise SystemExit("RUNTIME_STAGE_VERIFY_FAILED")
    if not stat.S_ISREG(partial_stat.st_mode) or digest_nofollow(partial) != expected:
        raise SystemExit("RUNTIME_STAGE_VERIFY_FAILED")
    try:
        final_stat = os.lstat(final)
    except FileNotFoundError:
        final_stat = None
    if final_stat is not None:
        if not stat.S_ISREG(final_stat.st_mode) or digest_nofollow(final) != expected:
            raise SystemExit("RUNTIME_COLLISION")
    else:
        os.link(partial, final, follow_symlinks=False)
        sync(final.parent)
        sync(final.parent.parent)
    os.unlink(partial)
    sync(final.parent)
    sync(final.parent.parent)
print(json.dumps({"runtime_sealed": True}, sort_keys=True))
"""

_MATERIALIZE_PINNED_SCRIPT = r"""import hashlib, os, shutil, sys, zipfile
from pathlib import Path, PurePosixPath
archive = Path(sys.argv[1]); target = Path(sys.argv[2]); expected = sys.argv[3]
interpreter_rel = PurePosixPath(sys.argv[4])
if (not archive.is_absolute() or not target.is_absolute() or ".." in archive.parts
        or ".." in target.parts or interpreter_rel.is_absolute() or ".." in interpreter_rel.parts):
    raise SystemExit("PINNED_RUNTIME_MATERIALIZATION_FAILED")
if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
    raise SystemExit("PINNED_RUNTIME_MATERIALIZATION_FAILED")
partial = target.with_name("." + target.name + ".partial")
if target.exists() or target.is_symlink() or partial.exists() or partial.is_symlink():
    raise SystemExit("PINNED_RUNTIME_MATERIALIZATION_COLLISION")
partial.mkdir(parents=True)
try:
    seen = set()
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            rel = PurePosixPath(info.filename)
            if not info.filename or rel.is_absolute() or ".." in rel.parts or rel.as_posix() in seen:
                raise SystemExit("PINNED_ARCHIVE_PATH_ESCAPE")
            seen.add(rel.as_posix())
            out = (partial / Path(*rel.parts)).resolve()
            if partial not in out.parents:
                raise SystemExit("PINNED_ARCHIVE_PATH_ESCAPE")
            if info.is_dir():
                out.mkdir(parents=True, exist_ok=False); continue
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.exists() or out.is_symlink():
                raise SystemExit("PINNED_ARCHIVE_DUPLICATE")
            out.write_bytes(zf.read(info))
            mode = (info.external_attr >> 16) & 0o7777
            if mode: out.chmod(mode)
    interpreter = (partial / Path(*interpreter_rel.parts)).resolve()
    if partial not in interpreter.parents or not interpreter.is_file() or interpreter.is_symlink():
        raise SystemExit("PINNED_INTERPRETER_MISSING")
    partial.rename(target)
    print(str(target / Path(*interpreter_rel.parts)))
except BaseException:
    shutil.rmtree(partial, ignore_errors=True)
    raise
"""

_VERIFY_PINNED_SCRIPT = r"""import hashlib, json, sys
from pathlib import Path
from rfb.contracts.canonical_json import canonical_bytes
from rfb.research.pinned_runtime import verify_before_launch

manifest = json.loads(__MANIFEST_JSON__)
verified = verify_before_launch(manifest, Path(sys.argv[1]))
print(json.dumps({
    "manifest": verified,
    "manifest_sha256": hashlib.sha256(canonical_bytes(verified)).hexdigest(),
}, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
"""


class TransportError(RuntimeError):
    pass


def _rename_dir_new(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise TransportError("DOWNLOAD_TARGET_EXISTS")
    if os.name == "nt":
        source.rename(destination)
        return
    if sys.platform.startswith("linux"):
        import ctypes
        import errno

        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise TransportError("IMMUTABLE_DIRECTORY_PUBLICATION_UNSUPPORTED")
        result = renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
        if result != 0:
            error = ctypes.get_errno()
            if error == errno.EEXIST:
                raise TransportError("DOWNLOAD_TARGET_EXISTS")
            raise OSError(error, os.strerror(error))
        return
    raise TransportError("IMMUTABLE_DIRECTORY_PUBLICATION_UNSUPPORTED")


@dataclass(frozen=True)
class RunRootCreationEvidence:
    """Durability and identity evidence for an atomically-created run root."""

    remote_run_root: str
    approved_remote_parent: str
    run_id: str
    parent_device: int
    parent_inode: int
    run_root_device: int
    run_root_inode: int
    mount_identity: str
    created_at_ns: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "remote_run_root": self.remote_run_root,
            "approved_remote_parent": self.approved_remote_parent,
            "run_id": self.run_id,
            "parent_device": self.parent_device,
            "parent_inode": self.parent_inode,
            "run_root_device": self.run_root_device,
            "run_root_inode": self.run_root_inode,
            "mount_identity": self.mount_identity,
            "created_at_ns": self.created_at_ns,
        }

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]


class ResearchTransport(Protocol):
    def run(self, remote_argv: Sequence[str]) -> Mapping[str, Any]: ...


@dataclass
class OpenSSHTransport:
    host: str
    known_hosts: Path
    fingerprint: str | None = None
    port: int = 22
    timeout: float = 120.0
    ssh: str = "ssh"
    auth_mode: str = "batch"
    control_path: Path | None = None

    def __post_init__(self) -> None:
        if self.auth_mode not in {"batch", "password_askpass"}:
            raise ValueError("unsupported SSH auth_mode")

    def _auth_options(self) -> list[str]:
        batch = "no" if self.auth_mode == "password_askpass" else "yes"
        options = ["-o", f"BatchMode={batch}"]
        if self.auth_mode == "password_askpass":
            options.extend(["-o", "NumberOfPasswordPrompts=1"])
        return options

    def _strict_options(self) -> list[str]:
        options = [
            *self._auth_options(),
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={self.known_hosts}",
        ]
        if self.control_path is not None:
            options.extend(
                [
                    "-o",
                    "ControlMaster=auto",
                    "-o",
                    "ControlPersist=300",
                    "-o",
                    f"ControlPath={self.control_path}",
                ]
            )
        return options

    def _scp_options(self) -> list[str]:
        return ["-P", str(self.port), *self._strict_options()]

    def validate_fingerprint(self, observed: str) -> None:
        if self.fingerprint and observed != self.fingerprint:
            raise TransportError("HOST_KEY_MISMATCH: fingerprint mismatch")

    def command(self, remote_argv: Sequence[str]) -> list[str]:
        if (
            not isinstance(self.port, int)
            or isinstance(self.port, bool)
            or not 1 <= self.port <= 65535
        ):
            raise ValueError("invalid SSH port")
        forbidden = re.compile(r"[\x00-\x1f;&|$`<>\r\n]")
        if (
            not self.host
            or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:@[A-Za-z0-9_.-]+)?", self.host)
            or any(
                forbidden.search(str(x)) or str(x).startswith(("-o", "--config"))
                for x in remote_argv
            )
        ):
            raise ValueError("invalid SSH target")
        return [
            self.ssh,
            *self._strict_options(),
            "-p",
            str(self.port),
            self.host,
            *map(str, remote_argv),
        ]

    def run(
        self, remote_argv: Sequence[str], *, env: Mapping[str, str] | None = None
    ) -> Mapping[str, Any]:
        if self.auth_mode == "password_askpass" and env is not None:
            raise ValueError("password_askpass requires inherited process environment")
        if not self.known_hosts.is_file():
            raise TransportError("HOST_KEY_MISMATCH: known-hosts file missing")
        proc = subprocess.run(
            self.command(remote_argv),
            shell=False,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
            env=dict(env) if env else None,
            start_new_session=True,
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

    def _run_script(self, script: str, argv: Sequence[str]) -> Mapping[str, Any]:
        if not self.known_hosts.is_file():
            raise TransportError("HOST_KEY_MISMATCH: known-hosts file missing")
        proc = subprocess.run(
            self.command(["python3", "-I", "-S", "-", *map(str, argv)]),
            shell=False,
            input=script,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
            start_new_session=True,
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

    def _run_pinned_verify(
        self,
        *,
        interpreter: PurePosixPath,
        root: PurePosixPath,
        manifest: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Verify a materialized closure with the materialized interpreter itself."""
        if not interpreter.is_absolute() or ".." in interpreter.parts:
            raise TransportError("PINNED_RUNTIME_PATH_BINDING_MISMATCH")
        if not root.is_absolute() or ".." in root.parts:
            raise TransportError("PINNED_RUNTIME_PATH_BINDING_MISMATCH")
        manifest_json = json.dumps(
            dict(manifest), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        script = _VERIFY_PINNED_SCRIPT.replace(
            "__MANIFEST_JSON__", repr(manifest_json), 1
        )
        if not self.known_hosts.is_file():
            raise TransportError("HOST_KEY_MISMATCH: known-hosts file missing")
        proc = subprocess.run(
            self.command([str(interpreter), "-B", "-I", "-", str(root)]),
            shell=False,
            input=script,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
            start_new_session=True,
        )
        if proc.returncode != 0:
            raise TransportError("PINNED_RUNTIME_VERIFY_FAILED")
        try:
            payload = json.loads(proc.stdout)
            verified = payload["manifest"]
            verifier_hash = payload["manifest_sha256"]
        except (TypeError, KeyError, json.JSONDecodeError) as exc:
            raise TransportError("PINNED_RUNTIME_VERIFY_FAILED") from exc
        if not isinstance(verified, Mapping) or not isinstance(verifier_hash, str):
            raise TransportError("PINNED_RUNTIME_VERIFY_FAILED")
        verified_hash = hashlib.sha256(canonical_bytes(dict(verified))).hexdigest()
        expected_hash = hashlib.sha256(canonical_bytes(dict(manifest))).hexdigest()
        if verifier_hash != expected_hash or verified_hash != verifier_hash:
            raise TransportError("PINNED_RUNTIME_VERIFY_BINDING_MISMATCH")
        return {"manifest": dict(verified), "manifest_sha256": verifier_hash}

    def _verify_known_host(self) -> None:
        if not self.fingerprint:
            raise TransportError("HOST_KEY_MISMATCH: expected fingerprint required")
        host_name = self.host.rsplit("@", 1)[-1]
        lookup_name = f"[{host_name}]:{self.port}" if self.port != 22 else host_name
        host_entry = subprocess.run(
            ["ssh-keygen", "-F", lookup_name, "-f", str(self.known_hosts)],
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
        if host_entry.returncode != 0 or not host_entry.stdout.strip():
            raise TransportError("HOST_KEY_MISMATCH: host missing from known-hosts")
        probe = subprocess.run(
            ["ssh-keygen", "-lf", "-", "-E", "sha256"],
            shell=False,
            input=host_entry.stdout,
            capture_output=True,
            text=True,
            check=False,
        )
        observed = {
            token
            for line in probe.stdout.splitlines()
            for token in line.split()
            if token.startswith("SHA256:")
        }
        if probe.returncode != 0 or self.fingerprint not in observed:
            raise TransportError("HOST_KEY_MISMATCH: known-host fingerprint mismatch")

    def bootstrap_parent_preflight(
        self, *, approved_remote_parent: Path | PurePosixPath
    ) -> Mapping[str, Any]:
        self._verify_known_host()
        result = self._run_script(
            _BOOTSTRAP_PREFLIGHT_SCRIPT, [str(approved_remote_parent)]
        )
        if result.get("returncode") != 0:
            raise TransportError("BOOTSTRAP_PREFLIGHT_BLOCKED")
        try:
            evidence = json.loads(result.get("stdout", ""))
        except (TypeError, json.JSONDecodeError) as exc:
            raise TransportError("BOOTSTRAP_PREFLIGHT_BLOCKED") from exc
        self._capacity_filesystem_baseline_bytes = evidence.get("filesystem_used_bytes")
        self._capacity_owned_external_layers_bytes = 0
        return {
            **evidence,
            "fingerprint_verified": True,
            "owned_external_layers_bytes": 0,
        }

    def bootstrap_preflight(self, *, root: Path | PurePosixPath) -> Mapping[str, Any]:
        """Compatibility alias; ``root`` is interpreted as the approved parent."""
        return self.bootstrap_parent_preflight(approved_remote_parent=root)

    def create_run_root(
        self, *, approved_remote_parent: Path | PurePosixPath, run_id: str
    ) -> RunRootCreationEvidence:
        result = self._run_script(
            _CREATE_RUN_ROOT_SCRIPT,
            [str(approved_remote_parent), run_id],
        )
        if result.get("returncode") != 0:
            stderr = str(result.get("stderr", "")).strip()
            code = next(
                (
                    token
                    for token in (
                        "RUN_ID_INVALID",
                        "RUN_ROOT_COLLISION",
                        "RUN_ROOT_PARENT_INVALID",
                    )
                    if token in stderr
                ),
                "RUN_ROOT_CREATE_FAILED",
            )
            raise TransportError(code)
        try:
            payload = json.loads(result.get("stdout", ""))
            return RunRootCreationEvidence(**payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TransportError("RUN_ROOT_CREATE_FAILED") from exc

    def _runtime_args(self) -> list[str]:
        try:
            binding = self._runtime_binding
        except AttributeError as exc:
            raise TransportError("RUNTIME_NOT_STAGED") from exc
        return runtime_binding_args(binding)

    def _runtime_command(self, subcommand: str) -> list[str]:
        binding = self._runtime_binding
        if binding["runtime_format"] == "python_pinned_venv_v1":
            return [
                binding["runtime_path"],
                "-X",
                "utf8",
                "-B",
                "-I",
                "-m",
                "rfb.research",
                subcommand,
            ]
        return ["python3", "-I", "-S", binding["runtime_path"], subcommand]

    def stage_runtime(
        self,
        *,
        bundle: RuntimeBundle | PinnedRuntimeBundle,
        remote_run_root: Path | PurePosixPath | None = None,
        remote_root: Path | PurePosixPath | None = None,
    ) -> PurePosixPath:
        bundle.verify()
        if remote_run_root is None:
            remote_run_root = remote_root
        if remote_run_root is None:
            raise ValueError("remote_run_root is required")
        remote_run_root = PurePosixPath(remote_run_root)
        if not remote_run_root.is_absolute() or ".." in remote_run_root.parts:
            raise TransportError("RUN_ROOT_PATH_INVALID")
        remote_root = remote_run_root
        runtime_root = PurePosixPath(remote_root) / ".runtime"
        final = runtime_root / bundle.remote_name
        manifest_final = runtime_root / f"{bundle.file_sha256}.manifest.json"
        partial = runtime_root / f".{bundle.remote_name}.partial"
        manifest_partial = runtime_root / f".{bundle.file_sha256}.manifest.json.partial"
        for local, remote in (
            (bundle.path, partial),
            (bundle.manifest_path, manifest_partial),
        ):
            subprocess.run(
                [
                    "scp",
                    *self._scp_options(),
                    str(local),
                    f"{self.host}:{remote}",
                ],
                shell=False,
                check=True,
                capture_output=True,
            )
        result = self._run_script(
            _SEAL_RUNTIME_SCRIPT,
            [
                str(partial),
                str(final),
                bundle.file_sha256,
                str(manifest_partial),
                str(manifest_final),
                hashlib.sha256(bundle.manifest_path.read_bytes()).hexdigest(),
            ],
        )
        if result.get("returncode") != 0:
            raise TransportError("RUNTIME_STAGE_VERIFY_FAILED")
        if isinstance(bundle, PinnedRuntimeBundle):
            materialized = (
                PurePosixPath(remote_root) / ".runtime" / f"{bundle.file_sha256}.pinned"
            )
            extracted = self._run_script(
                _MATERIALIZE_PINNED_SCRIPT,
                [
                    str(final),
                    str(materialized),
                    bundle.file_sha256,
                    bundle.interpreter_relative_path,
                ],
            )
            if extracted.get("returncode") != 0:
                raise TransportError("PINNED_RUNTIME_MATERIALIZATION_FAILED")
            interpreter = PurePosixPath(str(extracted.get("stdout", "")).strip())
            expected = materialized / PurePosixPath(bundle.interpreter_relative_path)
            if interpreter != expected:
                raise TransportError("PINNED_RUNTIME_PATH_BINDING_MISMATCH")
            verifier = self._run_pinned_verify(
                interpreter=interpreter,
                root=materialized,
                manifest=bundle.pinned_manifest,
            )
            if (
                verifier["manifest"].get("closure_fingerprint")
                != bundle.closure_fingerprint
            ):
                raise TransportError("PINNED_RUNTIME_VERIFY_BINDING_MISMATCH")
            self._runtime_binding = {
                "runtime_format": bundle.format,
                "runtime_path": str(interpreter),
                "runtime_file_sha256": bundle.file_sha256,
                "runtime_source_sha256": bundle.source_sha256,
                "runtime_manifest_sha256": bundle.manifest_sha256,
                "runtime_dependency_profile": "tep_nonconfirmatory_v1",
                "pinned_runtime_manifest_sha256": verifier["manifest_sha256"],
                "pinned_runtime_closure_fingerprint": bundle.closure_fingerprint,
            }
            return interpreter
        self._runtime_binding = {
            "runtime_format": bundle.format,
            "runtime_path": str(final),
            "runtime_file_sha256": bundle.file_sha256,
            "runtime_source_sha256": bundle.source_sha256,
            "runtime_manifest_sha256": bundle.manifest_sha256,
            "runtime_dependency_profile": "stdlib_only",
        }
        return final


def _ssh_preflight(
    self,
    *,
    root: Path,
    manifest_sha256: str,
    controller_nonce: str,
    formal_snapshot_sha256: str,
    dataset_root: str | Path | None = None,
    fixture_only: bool = False,
    filesystem_baseline_bytes: int | None = None,
    owned_external_layers_bytes: int | None = None,
    trusted_open_deleted_bytes: int | None = None,
):
    argv = [
        *self._runtime_command("preflight"),
        "--root",
        str(root),
        "--manifest-sha256",
        manifest_sha256,
        "--controller-nonce",
        controller_nonce,
        "--formal-snapshot-sha256",
        formal_snapshot_sha256,
        *self._runtime_args(),
    ]
    if dataset_root is not None:
        argv.extend(["--dataset-root", str(dataset_root)])
    if fixture_only:
        argv.append("--fixture-only")
    if filesystem_baseline_bytes is None:
        filesystem_baseline_bytes = getattr(
            self, "_capacity_filesystem_baseline_bytes", None
        )
    if owned_external_layers_bytes is None:
        owned_external_layers_bytes = getattr(
            self, "_capacity_owned_external_layers_bytes", None
        )
    for flag, value in (
        ("--filesystem-baseline-bytes", filesystem_baseline_bytes),
        ("--owned-external-layers-bytes", owned_external_layers_bytes),
        ("--trusted-open-deleted-bytes", trusted_open_deleted_bytes),
    ):
        if value is not None:
            argv.extend([flag, str(value)])
    result = self.run(argv)
    if result.get("returncode") != 0:
        raise TransportError("PREFLIGHT_BLOCKED")
    try:
        evidence = json.loads(result.get("stdout", ""))
    except (TypeError, json.JSONDecodeError) as exc:
        raise TransportError("PREFLIGHT_BLOCKED: invalid evidence") from exc
    if not evidence.get("capacity_available"):
        raise TransportError("PREFLIGHT_BLOCKED: insufficient capacity")
    return {**evidence, "fingerprint_verified": True}


def _ssh_stage(self, *, manifest: Path, remote_root: Path):
    if manifest.name != Path(manifest.name).name:
        raise ValueError("unsafe staged basename")
    remote_final = remote_root / manifest.name
    remote_partial = remote_root / f".{manifest.name}.partial"
    cmd = [
        "scp",
        *self._scp_options(),
        str(manifest),
        f"{self.host}:{remote_partial}",
    ]
    subprocess.run(cmd, shell=False, check=True, capture_output=True)
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    sealed = self.run(
        [
            *self._runtime_command("stage-seal"),
            "--partial",
            str(remote_partial),
            "--final",
            str(remote_final),
            "--sha256",
            digest,
        ]
    )
    if sealed.get("returncode") != 0:
        raise TransportError("STAGE_VERIFY_FAILED")
    return remote_final


def _ssh_download(self, *, remote_path: Path, local_path: Path):
    if local_path.exists():
        raise TransportError("DOWNLOAD_TARGET_EXISTS")
    local_partial = local_path.with_name(f".{local_path.name}.download.partial")
    if local_partial.exists():
        raise TransportError("DOWNLOAD_PARTIAL_EXISTS")
    cmd = [
        "scp",
        "-r",
        *self._scp_options(),
        f"{self.host}:{remote_path}",
        str(local_partial),
    ]
    subprocess.run(cmd, shell=False, check=True, capture_output=True)
    if not local_partial.is_dir() or any(
        path.is_symlink() for path in local_partial.rglob("*")
    ):
        raise TransportError("DOWNLOAD_VERIFY_FAILED")
    try:
        durable_tree_sync(local_partial)
    except RuntimeError as exc:
        raise TransportError("DOWNLOAD_DURABILITY_UNPROVEN") from exc
    _rename_dir_new(local_partial, local_path)
    _fsync_dir(local_path.parent)
    return local_path


def _ssh_download_file(self, *, remote_path: Path, local_path: Path):
    if local_path.exists() or local_path.is_symlink():
        raise TransportError("DOWNLOAD_TARGET_EXISTS")
    verified = self.run(
        [
            *self._runtime_command("verify-remote"),
            "--receipt",
            str(remote_path),
            *self._runtime_args(),
        ]
    )
    if verified.get("returncode") != 0:
        raise TransportError("REMOTE_RECEIPT_INVALID")
    partial = local_path.with_name(f".{local_path.name}.download.partial")
    cmd = [
        "scp",
        *self._scp_options(),
        f"{self.host}:{remote_path}",
        str(partial),
    ]
    subprocess.run(cmd, shell=False, check=True, capture_output=True)
    if not partial.is_file() or partial.is_symlink():
        raise TransportError("REMOTE_RECEIPT_INVALID")
    try:
        _publish_new_bytes(local_path, partial.read_bytes())
    except RuntimeBundleError as exc:
        raise TransportError("DOWNLOAD_TARGET_EXISTS") from exc
    partial.unlink()
    _fsync_dir(local_path.parent)
    return local_path


OpenSSHTransport.preflight = _ssh_preflight
OpenSSHTransport.stage = _ssh_stage
OpenSSHTransport.download = _ssh_download
OpenSSHTransport.download_file = _ssh_download_file


def _ssh_download_evidence_file(self, *, remote_path: Path, local_path: Path):
    """Copy a non-receipt evidence file; the controller validates its hash/schema."""
    if local_path.exists() or local_path.is_symlink():
        raise TransportError("DOWNLOAD_TARGET_EXISTS")
    partial = local_path.with_name(f".{local_path.name}.download.partial")
    cmd = [
        "scp",
        *self._scp_options(),
        f"{self.host}:{remote_path}",
        str(partial),
    ]
    subprocess.run(cmd, shell=False, check=True, capture_output=True)
    if not partial.is_file() or partial.is_symlink():
        raise TransportError("REMOTE_EVIDENCE_INVALID")
    try:
        _publish_new_bytes(local_path, partial.read_bytes())
    except RuntimeBundleError as exc:
        raise TransportError("DOWNLOAD_TARGET_EXISTS") from exc
    partial.unlink()
    _fsync_dir(local_path.parent)
    return local_path


OpenSSHTransport.download_evidence_file = _ssh_download_evidence_file


class FakeTransport:
    """Filesystem/local transport used by tests; never contacts SSH."""

    def __init__(self, worker, *, observed_available_bytes: int = 300_000_000_000):
        self.worker = worker
        self.observed_available_bytes = observed_available_bytes
        self.calls: list[list[str]] = []
        self.lifecycle: list[str] = []

    def _runtime_args(self) -> list[str]:
        binding = self._runtime_binding
        return runtime_binding_args(binding)

    def _invoke_runtime(self, argv: Sequence[str]) -> Mapping[str, Any]:
        command = list(map(str, argv))
        if command and command[0] == "python3":
            command[0] = sys.executable
        proc = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            check=False,
            env={
                "PATH": os.environ.get("PATH", ""),
                # FakeTransport mirrors the sealed remote launch contract;
                # keep fixture workers explicitly CPU-only as OpenSSH does.
                "CUDA_VISIBLE_DEVICES": "-1",
                "PYTHONUTF8": "1",
                "PYTHONUNBUFFERED": "1",
                "RFB_RESEARCH_ROOT": str(
                    Path(self._runtime_binding["runtime_path"]).parent.parent
                ),
                "RFB_RESEARCH_FAKE_AVAILABLE_BYTES": str(self.observed_available_bytes),
            },
        )

        def decode_output(payload: bytes | str) -> str:
            if isinstance(payload, str):
                return payload
            try:
                return payload.decode("utf-8")
            except UnicodeDecodeError:
                fallback = locale.getencoding()
                if fallback.lower().replace("-", "") == "utf8":
                    raise
                return payload.decode(fallback)

        return {
            "returncode": proc.returncode,
            "stdout": decode_output(proc.stdout),
            "stderr": decode_output(proc.stderr),
        }

    def _runtime_command(self, subcommand: str) -> list[str]:
        binding = self._runtime_binding
        if binding["runtime_format"] == "python_pinned_venv_v1":
            return [
                binding["runtime_path"],
                "-X",
                "utf8",
                "-B",
                "-I",
                "-m",
                "rfb.research",
                subcommand,
            ]
        return [
            sys.executable,
            "-X",
            "utf8",
            "-I",
            "-S",
            binding["runtime_path"],
            subcommand,
        ]

    def bootstrap_parent_preflight(
        self, *, approved_remote_parent: Path
    ) -> Mapping[str, Any]:
        self.lifecycle.append("bootstrap_preflight")
        parent = Path(approved_remote_parent)
        if not parent.is_absolute() or ".." in parent.parts:
            raise TransportError("RUN_ROOT_PARENT_INVALID")
        current = parent
        while True:
            if current.is_symlink():
                raise TransportError("BOOTSTRAP_PREFLIGHT_BLOCKED")
            if current == current.parent:
                break
            current = current.parent
        if not parent.is_dir():
            raise TransportError("BOOTSTRAP_PREFLIGHT_BLOCKED")
        usage = shutil.disk_usage(parent)
        self._capacity_filesystem_baseline_bytes = usage.used
        # Staging is confined to the approved parent; no container/external
        # layers are created by this transport.
        self._capacity_owned_external_layers_bytes = 0
        return {
            "approved_remote_parent": str(parent),
            "parent": str(parent),
            "parent_device": parent.stat().st_dev,
            "parent_inode": parent.stat().st_ino,
            "mount_identity": f"device={parent.stat().st_dev}:anchor={parent.anchor}",
            "observed_at_ns": time.time_ns(),
            "filesystem_total_bytes": usage.total,
            "filesystem_free_bytes": self.observed_available_bytes,
            "capacity_available": self.observed_available_bytes >= 265_853_007_872,
            "remote_reserve_available": self.observed_available_bytes
            >= 235_853_007_872,
            "fingerprint_verified": True,
        }

    def bootstrap_preflight(self, *, root: Path) -> Mapping[str, Any]:
        return self.bootstrap_parent_preflight(approved_remote_parent=root)

    def create_run_root(
        self, *, approved_remote_parent: Path, run_id: str
    ) -> RunRootCreationEvidence:
        self.lifecycle.append("create_run_root")
        parent = Path(approved_remote_parent)
        if not parent.is_absolute() or ".." in parent.parts:
            raise TransportError("RUN_ROOT_PARENT_INVALID")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id):
            raise TransportError("RUN_ID_INVALID")
        current = parent
        while True:
            if current.is_symlink():
                raise TransportError("RUN_ROOT_PARENT_INVALID")
            if current == current.parent:
                break
            current = current.parent
        if not parent.is_dir():
            raise TransportError("RUN_ROOT_PARENT_INVALID")
        root = parent / run_id
        try:
            root.mkdir()
        except FileExistsError as exc:
            raise TransportError("RUN_ROOT_COLLISION") from exc
        try:
            (root / ".runtime").mkdir()
            _fsync_dir(root / ".runtime")
            _fsync_dir(root)
            _fsync_dir(parent)
        except OSError as exc:
            raise TransportError("RUN_ROOT_DURABILITY_FAILED") from exc
        parent_stat = parent.stat()
        root_stat = root.stat()
        return RunRootCreationEvidence(
            remote_run_root=str(root),
            approved_remote_parent=str(parent),
            run_id=run_id,
            parent_device=parent_stat.st_dev,
            parent_inode=parent_stat.st_ino,
            run_root_device=root_stat.st_dev,
            run_root_inode=root_stat.st_ino,
            mount_identity=f"device={root_stat.st_dev}:anchor={root.anchor}",
            created_at_ns=time.time_ns(),
        )

    def stage_runtime(
        self,
        *,
        bundle: RuntimeBundle | PinnedRuntimeBundle,
        remote_run_root: Path | None = None,
        remote_root: Path | None = None,
    ) -> Path:
        self.lifecycle.append("stage_runtime")
        try:
            bundle.verify()
        except RuntimeBundleError as exc:
            raise TransportError("RUNTIME_STAGE_VERIFY_FAILED") from exc
        if remote_run_root is None:
            remote_run_root = remote_root
        if remote_run_root is None:
            raise ValueError("remote_run_root is required")
        remote_root = Path(remote_run_root)
        if not remote_root.is_absolute() or ".." in remote_root.parts:
            raise TransportError("RUN_ROOT_PATH_INVALID")
        runtime_root = remote_root / ".runtime"
        if (
            not remote_root.is_dir()
            or remote_root.is_symlink()
            or not runtime_root.is_dir()
            or runtime_root.is_symlink()
        ):
            raise TransportError("RUN_ROOT_NOT_CREATED")
        final = runtime_root / bundle.remote_name
        manifest_final = runtime_root / f"{bundle.file_sha256}.manifest.json"
        for source, destination, expected in (
            (bundle.path, final, bundle.file_sha256),
            (
                bundle.manifest_path,
                manifest_final,
                hashlib.sha256(bundle.manifest_path.read_bytes()).hexdigest(),
            ),
        ):
            if destination.exists():
                if (
                    destination.is_symlink()
                    or not destination.is_file()
                    or hashlib.sha256(destination.read_bytes()).hexdigest() != expected
                ):
                    raise TransportError("RUNTIME_COLLISION")
            else:
                try:
                    _publish_new_bytes(destination, source.read_bytes())
                except RuntimeBundleError as exc:
                    raise TransportError("RUNTIME_STAGE_VERIFY_FAILED") from exc
        if isinstance(bundle, PinnedRuntimeBundle):
            materialized_root = runtime_root / f"{bundle.file_sha256}.pinned"
            staged_bundle = PinnedRuntimeBundle(
                final,
                manifest_final,
                bundle.file_sha256,
                bundle.manifest_sha256,
                bundle.closure_fingerprint,
                bundle.interpreter_relative_path,
                bundle.pinned_manifest,
            )
            try:
                materialize_pinned_runtime_bundle(staged_bundle, materialized_root)
                from .pinned_runtime import verify_before_launch

                verify_before_launch(bundle.pinned_manifest, materialized_root)
            except (RuntimeBundleError, ValueError) as exc:
                raise TransportError("PINNED_RUNTIME_MATERIALIZATION_FAILED") from exc
            interpreter = (
                materialized_root
                / Path(*PurePosixPath(bundle.interpreter_relative_path).parts)
            ).resolve()
            self._runtime_binding = {
                "runtime_format": bundle.format,
                "runtime_path": str(interpreter),
                "runtime_file_sha256": bundle.file_sha256,
                "runtime_source_sha256": bundle.source_sha256,
                "runtime_manifest_sha256": bundle.manifest_sha256,
                "runtime_dependency_profile": "tep_nonconfirmatory_v1",
                "pinned_runtime_manifest_sha256": hashlib.sha256(
                    canonical_bytes(bundle.pinned_manifest)
                ).hexdigest(),
                "pinned_runtime_closure_fingerprint": bundle.closure_fingerprint,
            }
            return interpreter
        self._runtime_binding = {
            "runtime_format": bundle.format,
            "runtime_path": str(final),
            "runtime_file_sha256": bundle.file_sha256,
            "runtime_source_sha256": bundle.source_sha256,
            "runtime_manifest_sha256": bundle.manifest_sha256,
            "runtime_dependency_profile": "stdlib_only",
        }
        return final

    def preflight(
        self,
        *,
        root: Path,
        manifest_sha256: str,
        controller_nonce: str,
        formal_snapshot_sha256: str,
        dataset_root: str | Path | None = None,
        fixture_only: bool = False,
        filesystem_baseline_bytes: int | None = None,
        owned_external_layers_bytes: int | None = None,
        trusted_open_deleted_bytes: int | None = None,
    ) -> Mapping[str, Any]:
        self.lifecycle.append("preflight")
        if filesystem_baseline_bytes is None:
            filesystem_baseline_bytes = getattr(
                self, "_capacity_filesystem_baseline_bytes", None
            )
        if owned_external_layers_bytes is None:
            owned_external_layers_bytes = getattr(
                self, "_capacity_owned_external_layers_bytes", None
            )
        argv = [
            *self._runtime_command("preflight"),
            "--root",
            str(root),
            "--manifest-sha256",
            manifest_sha256,
            "--controller-nonce",
            controller_nonce,
            "--formal-snapshot-sha256",
            formal_snapshot_sha256,
            *self._runtime_args(),
        ]
        if dataset_root is not None:
            argv.extend(["--dataset-root", str(dataset_root)])
        if fixture_only:
            argv.append("--fixture-only")
        for flag, value in (
            ("--filesystem-baseline-bytes", filesystem_baseline_bytes),
            ("--owned-external-layers-bytes", owned_external_layers_bytes),
            ("--trusted-open-deleted-bytes", trusted_open_deleted_bytes),
        ):
            if value is not None:
                argv.extend([flag, str(value)])
        result = self._invoke_runtime(argv)
        if result["returncode"] != 0:
            raise TransportError(f"PREFLIGHT_BLOCKED:{result['stderr'].strip()}")
        return json.loads(result["stdout"])

    def stage(self, *, manifest: Path, remote_root: Path) -> Path:
        self.lifecycle.append("stage")
        remote_final = Path(remote_root).resolve() / manifest.name
        remote_partial = remote_final.with_name(f".{remote_final.name}.partial")
        if remote_partial.exists() or remote_partial.is_symlink():
            raise TransportError("STAGE_VERIFY_FAILED")
        _publish_new_bytes(remote_partial, manifest.read_bytes())
        result = self._invoke_runtime(
            [
                *self._runtime_command("stage-seal"),
                "--partial",
                str(remote_partial),
                "--final",
                str(remote_final),
                "--sha256",
                hashlib.sha256(manifest.read_bytes()).hexdigest(),
            ]
        )
        if result["returncode"] != 0:
            raise TransportError("STAGE_VERIFY_FAILED")
        return remote_final

    def run(self, remote_argv: Sequence[str]) -> Mapping[str, Any]:
        self.lifecycle.append("run")
        self.calls.append(list(map(str, remote_argv)))
        return self._invoke_runtime(remote_argv)

    def download(self, *, remote_path: Path, local_path: Path) -> Path:
        self.lifecycle.append("download")
        return remote_path

    def download_file(self, *, remote_path: Path, local_path: Path) -> Path:
        self.lifecycle.append("download_receipt")
        if local_path.exists() or local_path.is_symlink():
            raise TransportError("DOWNLOAD_TARGET_EXISTS")
        verified = self._invoke_runtime(
            [
                *self._runtime_command("verify-remote"),
                "--receipt",
                str(remote_path),
                *self._runtime_args(),
            ]
        )
        if verified["returncode"] != 0:
            raise TransportError("REMOTE_RECEIPT_INVALID")
        shutil.copyfile(remote_path, local_path)
        _fsync_dir(local_path.parent)
        return local_path

    def download_evidence_file(self, *, remote_path: Path, local_path: Path) -> Path:
        self.lifecycle.append("download_evidence")
        if local_path.exists() or local_path.is_symlink():
            raise TransportError("DOWNLOAD_TARGET_EXISTS")
        shutil.copyfile(remote_path, local_path)
        _fsync_dir(local_path.parent)
        return local_path
