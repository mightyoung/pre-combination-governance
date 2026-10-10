"""Root-wide fail-closed research lock with explicit verified tombstoning."""

from __future__ import annotations
import json
import os
import secrets
import time
import threading
import ctypes
import errno
from pathlib import Path, PureWindowsPath
from dataclasses import dataclass
from .files import _fsync_dir, publish_json


class LockBusy(RuntimeError):
    pass


class LockTombstoneError(RuntimeError):
    pass


def _reject_symlink_chain(path: Path) -> None:
    current = path
    while True:
        if current.exists() and (
            current.is_symlink()
            or bool(getattr(current.stat(), "st_file_attributes", 0) & 0x400)
        ):
            raise LockTombstoneError("root symlink/reparse rejected")
        if current == current.parent:
            return
        current = current.parent


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically rename *source* without ever replacing *destination*."""
    source = Path(source)
    destination = Path(destination)
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move = kernel32.MoveFileExW
        move.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        move.restype = ctypes.c_int
        # MOVEFILE_WRITE_THROUGH; omitting REPLACE_EXISTING gives create-new semantics.
        if not move(str(source), str(destination), 0x00000008):
            error = ctypes.get_last_error()
            raise OSError(error, os.strerror(error), str(destination))
        return
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        error = errno.ENOTSUP
    else:
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1) == 0:
            return
        error = ctypes.get_errno()
    unsupported = {errno.ENOTSUP, errno.EOPNOTSUPP, errno.EINVAL, errno.ENOSYS}
    if error not in unsupported:
        raise OSError(error, os.strerror(error), str(destination))
    source_stat = source.stat()
    try:
        os.lstat(destination)
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError(errno.EEXIST, "destination exists", destination)
    os.rename(source, destination)
    destination_stat = destination.stat()
    if source.exists() or (
        source_stat.st_dev,
        source_stat.st_ino,
    ) != (destination_stat.st_dev, destination_stat.st_ino):
        raise OSError(errno.EIO, "rename identity mismatch", str(destination))


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "unknown"


def _start_ticks(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[21]
    except (OSError, IndexError):
        return "unknown"


def _identity_matches(rec: dict) -> bool:
    if rec.get("boot_id") != _boot_id():
        return False
    pid = int(rec.get("pid", -1))
    return _start_ticks(pid) == str(rec.get("start_ticks"))


def _process_group_alive(rec: dict) -> bool:
    try:
        pgid = int(rec.get("process_group", -1))
        if hasattr(os, "killpg"):
            os.killpg(pgid, 0)
            return True
    except (OSError, ValueError):
        return False
    return False


@dataclass
class ResearchLock:
    root: Path
    manifest_hash: str
    run_id: str = "unknown"
    remote_run_root: Path | None = None
    heartbeat_seconds: float = 10.0
    stale_seconds: float = 60.0
    nonce: str | None = None
    controller_nonce: str | None = None
    path: Path | None = None
    record: dict | None = None
    _heartbeat_thread: threading.Thread | None = None
    _stop_heartbeat: threading.Event | None = None

    def acquire(self) -> "ResearchLock":
        raw_root = Path(self.root).absolute()
        _reject_symlink_chain(raw_root)
        root = raw_root.resolve()
        if not root.is_absolute() or ".." in root.parts:
            raise LockTombstoneError("absolute confined lock root required")
        remote_root = Path(self.remote_run_root or root).absolute()
        if PureWindowsPath(str(self.remote_run_root or root)).is_absolute() and os.name != "nt":
            raise LockTombstoneError("cross-platform remote run root rejected")
        _reject_symlink_chain(remote_root)
        remote_root = remote_root.resolve()
        if remote_root != root and root not in remote_root.parents:
            raise LockTombstoneError("remote run root outside approved parent")
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / ".rfb-research-run.lock"
        self.nonce = secrets.token_hex(16)
        now = time.time()
        rec = {
            "run_id": self.run_id,
            "root_identity": str(root),
            "remote_run_root": str(remote_root),
            "host": os.uname().nodename
            if hasattr(os, "uname")
            else os.environ.get("COMPUTERNAME", "unknown"),
            "boot_id": _boot_id(),
            "pid": os.getpid(),
            "start_ticks": _start_ticks(os.getpid()),
            "process_group": os.getpgrp() if hasattr(os, "getpgrp") else os.getpid(),
            "nonce": self.nonce,
            "controller_nonce": self.controller_nonce,
            "manifest_hash": self.manifest_hash,
            "heartbeat_at": now,
            "created_at": now,
        }
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(rec, f, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
        except FileExistsError as exc:
            raise LockBusy(
                "research root lock exists; stale locks require verified tombstone"
            ) from exc
        try:
            _fsync_dir(root)
        except RuntimeError as exc:
            raise LockTombstoneError("lock acquisition durability unproven") from exc
        self.record = rec
        return self

    def _owns(self) -> bool:
        if not self.path or not self.path.exists():
            return False
        try:
            return json.loads(self.path.read_text()).get("nonce") == self.nonce
        except (OSError, ValueError):
            return False

    def heartbeat(self) -> None:
        if not self._owns():
            raise LockBusy("lock is not owned")
        self.record["heartbeat_at"] = time.time()
        publish_json(self.path, self.record)

    def release(self) -> None:
        raise LockTombstoneError("locks never auto-unlock; use verified_tombstone")

    def release_owned(self) -> Path:
        """Release the lock after this worker has durably sealed its receipt."""
        self.stop_heartbeat()
        if not self._owns():
            raise LockTombstoneError("lock is not owned")
        current = json.loads(self.path.read_text(encoding="utf-8"))
        if current.get("nonce") != self.nonce:
            raise LockTombstoneError("lock changed during release")
        tomb = self.path.with_name(self.path.name + f".{self.nonce}.tombstone")
        if tomb.exists():
            raise LockTombstoneError("tombstone already exists")
        try:
            _rename_noreplace(self.path, tomb)
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                raise LockTombstoneError("tombstone already exists") from exc
            raise LockTombstoneError("atomic tombstone rename failed") from exc
        try:
            _fsync_dir(self.path.parent)
        except RuntimeError as exc:
            raise LockTombstoneError(
                "lock release directory durability unproven"
            ) from exc
        persisted = json.loads(tomb.read_text(encoding="utf-8"))
        if persisted.get("nonce") != self.nonce:
            raise LockTombstoneError("tombstone readback mismatch")
        return tomb

    def start_heartbeat(self) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._stop_heartbeat = threading.Event()

        def loop():
            while not self._stop_heartbeat.wait(self.heartbeat_seconds):
                try:
                    self.heartbeat()
                except LockBusy:
                    break

        self._heartbeat_thread = threading.Thread(target=loop, daemon=True)
        self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        if self._stop_heartbeat:
            self._stop_heartbeat.set()
        if (
            self._heartbeat_thread
            and self._heartbeat_thread.is_alive()
            and self._heartbeat_thread is not threading.current_thread()
        ):
            self._heartbeat_thread.join(timeout=max(1.0, self.heartbeat_seconds + 1.0))
            if self._heartbeat_thread.is_alive():
                raise LockTombstoneError("heartbeat thread did not stop")

    @staticmethod
    def verified_tombstone(
        root: str | Path,
        *,
        expected_manifest_hash: str,
        run_id: str | None = None,
        reason: str = "verified-stale",
    ) -> Path:
        raw_root = Path(root).absolute()
        if raw_root.is_symlink():
            raise LockTombstoneError("root symlink/reparse rejected")
        root_path = raw_root.resolve()
        path = root_path / ".rfb-research-run.lock"
        if not path.is_file():
            raise LockTombstoneError("lock missing")
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec.get("manifest_hash") != expected_manifest_hash:
            raise LockTombstoneError("manifest binding mismatch")
        if run_id is not None and rec.get("run_id") != run_id:
            raise LockTombstoneError("run binding mismatch")
        if rec.get("root_identity") != str(root_path):
            raise LockTombstoneError("root binding mismatch")
        if time.time() - float(rec.get("heartbeat_at", 0)) < 60:
            raise LockTombstoneError("lock is not stale")
        if _identity_matches(rec):
            raise LockTombstoneError("owner identity still matches")
        if _process_group_alive(rec):
            raise LockTombstoneError("bound process group still alive")
        try:
            os.kill(int(rec.get("pid", -1)), 0)
        except OSError:
            pass
        else:
            raise LockTombstoneError("owner process still exists")
        tomb = path.with_name(path.name + f".{rec.get('nonce')}.tombstone")
        if tomb.exists():
            raise LockTombstoneError("tombstone already exists")
        # Compare-and-tombstone: rename only if the lock still has the same nonce.
        current = json.loads(path.read_text(encoding="utf-8"))
        if current.get("nonce") != rec.get("nonce"):
            raise LockTombstoneError("lock changed during tombstone")
        try:
            _rename_noreplace(path, tomb)
            _fsync_dir(root_path)
        except OSError as exc:
            raise LockTombstoneError("atomic tombstone rename failed") from exc
        except RuntimeError as exc:
            raise LockTombstoneError("tombstone durability unproven") from exc
        return tomb
