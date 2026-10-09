"""Capability-bound purge authorization and durable anti-replay."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Sequence
from contextlib import contextmanager
import socket

from rfb.contracts.canonical_json import canonical_bytes


class PurgeBlocked(ValueError):
    pass


_HASH = re.compile(r"^[0-9a-f]{64}$")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def freeze_allowlist(paths: Sequence[str]) -> dict[str, Any]:
    if isinstance(paths, (str, bytes)):
        raise PurgeBlocked("allowlist paths must be an array")
    normalized = []
    for raw in paths:
        if not isinstance(raw, str):
            raise PurgeBlocked("allowlist path must be a string")
        posix = PurePosixPath(str(raw).replace("\\", "/"))
        windows = PureWindowsPath(str(raw))
        if (
            not raw
            or posix.is_absolute()
            or windows.is_absolute()
            or windows.drive
            or ".." in posix.parts
            or posix.as_posix() in {".", ""}
        ):
            raise PurgeBlocked("allowlist path is not root-confined")
        value = posix.as_posix()
        if value in normalized:
            raise PurgeBlocked("duplicate allowlist path")
        normalized.append(value)
    normalized.sort()
    return {"paths": normalized, "allowlist_hash": canonical_hash(normalized)}


def _target_metadata(path: Path) -> dict[str, Any]:
    try:
        st = path.lstat()
    except OSError as exc:
        raise PurgeBlocked("allowlist target missing") from exc
    if path.is_symlink() or not stat.S_ISREG(st.st_mode):
        raise PurgeBlocked("symlink target forbidden")
    return {
        "st_dev": int(st.st_dev),
        "st_ino": int(st.st_ino),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _freeze_target_bindings(root: Path, paths: Sequence[str]) -> dict[str, Any]:
    return {
        relative: _target_metadata(root.joinpath(*PurePosixPath(relative).parts))
        for relative in paths
    }


def _assert_root_stable(root: Path, expected: dict[str, Any]) -> None:
    try:
        observed = root.stat()
    except OSError as exc:
        raise PurgeBlocked("root identity unavailable") from exc
    if not expected.get("identity_verified"):
        return
    for key, value in (("st_dev", observed.st_dev), ("st_ino", observed.st_ino)):
        if key in expected and int(expected[key]) != int(value):
            raise PurgeBlocked("root identity drift")


def issue_no_writer_attestation(
    *,
    attester,
    root,
    root_identity,
    operation_id,
    allowlist_hash,
    target_bindings,
    now=None,
    ttl_seconds=120,
    facts=None,
):
    if attester.get("role") != "PurgeNoWriterAttester":
        raise PurgeBlocked("attester role mismatch")
    if (
        not 0 < ttl_seconds <= 300
        or not isinstance(facts, dict)
        or facts.get("exclusive_writer") is not True
    ):
        raise PurgeBlocked("exclusive writer attestation facts invalid")
    stamp = _now(now)
    body = {
        "schema_id": "purge-no-writer-attestation.v1",
        "status": "ATTESTED",
        "role": attester["role"],
        "attester_id": attester["identity"],
        "key_id": attester["key_id"],
        "trust_epoch": attester["trust_epoch"],
        "root": str(Path(root).resolve()),
        "root_identity": dict(root_identity),
        "operation_id": operation_id,
        "allowlist_hash": allowlist_hash,
        "target_bindings": dict(target_bindings),
        "facts": dict(facts),
        "issued_at": stamp.isoformat(),
        "expires_at": (stamp + timedelta(seconds=ttl_seconds)).isoformat(),
    }
    return body | {"signature": _signature(body, attester["key"])}


def verify_no_writer_attestation(attestation, trust, *, capability, now=None):
    if not isinstance(attestation, dict):
        raise PurgeBlocked("no-writer attestation required")
    body = dict(attestation)
    sig = body.pop("signature", None)
    if set(body) != {
        "schema_id",
        "status",
        "role",
        "attester_id",
        "key_id",
        "trust_epoch",
        "root",
        "root_identity",
        "operation_id",
        "allowlist_hash",
        "target_bindings",
        "facts",
        "issued_at",
        "expires_at",
    }:
        raise PurgeBlocked("no-writer attestation schema invalid")
    if (
        body["schema_id"] != "purge-no-writer-attestation.v1"
        or body["status"] != "ATTESTED"
        or body["role"] != "PurgeNoWriterAttester"
    ):
        raise PurgeBlocked("no-writer attestation invalid")
    if (
        body["attester_id"] != trust.get("identity")
        or body["key_id"] != trust.get("key_id")
        or body["trust_epoch"] != trust.get("trust_epoch")
        or not isinstance(sig, str)
        or not hmac.compare_digest(sig, _signature(body, trust["key"]))
    ):
        raise PurgeBlocked("no-writer attestation signature invalid")
    for k in (
        "root",
        "root_identity",
        "operation_id",
        "allowlist_hash",
        "target_bindings",
    ):
        if body[k] != capability[k]:
            raise PurgeBlocked("no-writer attestation binding mismatch")
    if body["facts"].get("exclusive_writer") is not True:
        raise PurgeBlocked("exclusive writer attestation missing")
    if _now(now) >= _time(body["expires_at"], "attestation expiry"):
        raise PurgeBlocked("no-writer attestation expired")
    return body


def _now(value=None):
    return (value or datetime.now(UTC)).astimezone(UTC)


def _time(value, field):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as exc:
        raise PurgeBlocked(f"invalid {field}") from exc


def _signature(body, key):
    return hmac.new(key, canonical_bytes(body), hashlib.sha256).hexdigest()


def _verify(artifact, trust, role):
    body = dict(artifact)
    signature = body.pop("signature", None)
    allowed = {
        "PurgeCapabilityIssuer": {
            "schema_id",
            "status",
            "role",
            "identity",
            "key_id",
            "trust_epoch",
            "segment_id",
            "root",
            "root_identity",
            "manifest_hash",
            "allowlist_hash",
            "allowlist_paths",
            "target_bindings",
            "nonce",
            "operation_id",
            "issued_at",
            "expires_at",
        },
        "DestructiveApprover": {
            "schema_id",
            "status",
            "role",
            "identity",
            "key_id",
            "trust_epoch",
            "capability_hash",
            "segment_id",
            "root",
            "root_identity",
            "manifest_hash",
            "allowlist_hash",
            "target_bindings",
            "nonce",
            "operation_id",
            "issued_at",
            "expires_at",
        },
    }[role]
    if set(body) != allowed:
        raise PurgeBlocked(f"{role} schema fields invalid")
    expected_schema = (
        "purge-capability.v1"
        if role == "PurgeCapabilityIssuer"
        else "purge-execution-approval.v1"
    )
    if body.get("schema_id") != expected_schema or body.get("status") != "ISSUED":
        raise PurgeBlocked(f"{role} schema/status invalid")
    if body.get("role") != role:
        raise PurgeBlocked(f"{role} role mismatch")
    for field in ("identity", "key_id", "trust_epoch"):
        if body.get(field) != trust.get(field):
            raise PurgeBlocked(f"{role} {field} mismatch")
    if (
        not isinstance(signature, str)
        or not _HASH.fullmatch(signature)
        or not hmac.compare_digest(signature, _signature(body, trust["key"]))
    ):
        raise PurgeBlocked(f"{role} signature invalid")
    return body


def issue_capability(
    *,
    issuer,
    segment_id,
    root,
    root_identity,
    manifest_hash,
    allowlist,
    nonce,
    operation_id,
    prerequisites,
    now=None,
    ttl_seconds=300,
):
    required = {
        "result_sealed_local": "PASS",
        "result_archive_a": "PASS",
        "result_archive_b": "PASS",
        "regen_verified": "PASS",
        "contains_raw_dataset": False,
        "truth_isolation": "PASS",
    }
    if any(prerequisites.get(k) != v for k, v in required.items()):
        raise PurgeBlocked("purge prerequisites are incomplete")
    if issuer.get("role") != "PurgeCapabilityIssuer":
        raise PurgeBlocked("issuer role mismatch")
    if not all(
        isinstance(value, str) and value.strip()
        for value in (segment_id, nonce, operation_id)
    ):
        raise PurgeBlocked("capability identifiers are required")
    if (
        not isinstance(root_identity, dict)
        or not root_identity
        or root_identity.get("identity_verified") is not True
        or not {"st_dev", "st_ino", "mount"}.issubset(root_identity)
    ):
        raise PurgeBlocked("verified root identity metadata is required")
    if not isinstance(manifest_hash, str) or not _HASH.fullmatch(manifest_hash):
        raise PurgeBlocked("manifest hash is invalid")
    if not isinstance(allowlist, dict):
        raise PurgeBlocked("allowlist must be an object")
    if not 0 < ttl_seconds <= 900:
        raise PurgeBlocked("capability ttl exceeds policy")
    frozen = freeze_allowlist(allowlist.get("paths", []))
    if frozen != dict(allowlist):
        raise PurgeBlocked("allowlist hash mismatch")
    stamp = _now(now)
    root_path = Path(root).resolve(strict=True)
    target_bindings = _freeze_target_bindings(root_path, frozen["paths"])
    body = {
        "schema_id": "purge-capability.v1",
        "status": "ISSUED",
        "role": "PurgeCapabilityIssuer",
        "identity": issuer["identity"],
        "key_id": issuer["key_id"],
        "trust_epoch": issuer["trust_epoch"],
        "segment_id": segment_id,
        "root": str(root_path),
        "root_identity": dict(root_identity),
        "manifest_hash": manifest_hash,
        "allowlist_hash": frozen["allowlist_hash"],
        "allowlist_paths": frozen["paths"],
        "target_bindings": target_bindings,
        "nonce": nonce,
        "operation_id": operation_id,
        "issued_at": stamp.isoformat(),
        "expires_at": (stamp + timedelta(seconds=ttl_seconds)).isoformat(),
    }
    return body | {"signature": _signature(body, issuer["key"])}


def issue_execution_approval(
    *, approver, capability, issuer_trust, now=None, ttl_seconds=120
):
    cap = _verify(capability, issuer_trust, "PurgeCapabilityIssuer")
    if approver.get("role") != "DestructiveApprover":
        raise PurgeBlocked("approver role mismatch")
    if (
        approver.get("identity") == cap["identity"]
        or approver.get("key_id") == cap["key_id"]
        or approver.get("key") == issuer_trust.get("key")
    ):
        raise PurgeBlocked("issuer and approver must be distinct")
    stamp = _now(now)
    if stamp >= _time(cap["expires_at"], "capability expiry"):
        raise PurgeBlocked("capability expired")
    if not 0 < ttl_seconds <= 300:
        raise PurgeBlocked("approval ttl exceeds policy")
    body = {
        "schema_id": "purge-execution-approval.v1",
        "status": "ISSUED",
        "role": "DestructiveApprover",
        "identity": approver["identity"],
        "key_id": approver["key_id"],
        "trust_epoch": approver["trust_epoch"],
        "capability_hash": canonical_hash(capability),
        **{
            k: cap[k]
            for k in (
                "segment_id",
                "root",
                "root_identity",
                "manifest_hash",
                "allowlist_hash",
                "target_bindings",
                "nonce",
                "operation_id",
            )
        },
        "issued_at": stamp.isoformat(),
        "expires_at": min(
            stamp + timedelta(seconds=ttl_seconds),
            _time(cap["expires_at"], "capability expiry"),
        ).isoformat(),
    }
    return body | {"signature": _signature(body, approver["key"])}


class PurgeLedger:
    states = {
        "APPROVAL_RECORDED",
        "CLAIMED",
        "PURGE_INTENT",
        "UNLINK_PREPARED",
        "UNLINK_QUARANTINED",
        "UNLINK_COMMITTED",
        "COMMITTED",
        "ABORTED",
    }

    def __init__(self, path):
        self.path = Path(path)

    @classmethod
    def _validate_transition(cls, previous_state, state):
        """Validate one operation state transition before any ledger write."""
        legal = {
            None: {"APPROVAL_RECORDED"},
            "APPROVAL_RECORDED": {"CLAIMED"},
            "CLAIMED": {"PURGE_INTENT", "ABORTED"},
            "PURGE_INTENT": {"UNLINK_PREPARED", "ABORTED"},
            "UNLINK_PREPARED": {"UNLINK_QUARANTINED", "ABORTED"},
            "UNLINK_QUARANTINED": {"UNLINK_COMMITTED", "ABORTED"},
            "UNLINK_COMMITTED": {"UNLINK_PREPARED", "COMMITTED", "ABORTED"},
            "COMMITTED": set(),
            "ABORTED": set(),
        }
        if state not in legal.get(previous_state, set()):
            raise PurgeBlocked("illegal ledger state transition")

    def rows(self):
        if not self.path.exists():
            return []
        if self.path.is_symlink() or not self.path.is_file():
            raise PurgeBlocked("ledger must be a regular file")
        rows, previous, last_by_op = [], "", {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line:
                raise PurgeBlocked("blank ledger row")
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PurgeBlocked("invalid ledger JSON") from exc
            if not isinstance(row, dict) or row.get("state") not in self.states:
                raise PurgeBlocked("invalid ledger state")
            prev = row.get("prev_hash", "")
            unsigned = {
                k: v for k, v in row.items() if k not in {"entry_hash", "prev_hash"}
            }
            if prev != previous or row.get("entry_hash") != canonical_hash(
                unsigned | {"prev_hash": prev}
            ):
                raise PurgeBlocked("ledger hash chain invalid")
            operation = row.get("operation_id")
            required = {
                "operation_id",
                "segment_id",
                "root",
                "manifest_hash",
                "allowlist_hash",
                "nonce",
                "capability_hash",
                "approval_hash",
            }
            if not required.issubset(row) or any(
                not isinstance(row.get(key), str) or not row.get(key)
                for key in required
            ):
                raise PurgeBlocked("ledger binding metadata incomplete")
            for key in (
                "manifest_hash",
                "allowlist_hash",
                "capability_hash",
                "approval_hash",
            ):
                if not _HASH.fullmatch(row[key]):
                    raise PurgeBlocked("ledger binding hash invalid")
            previous_state = last_by_op.get(operation)
            if not isinstance(operation, str) or not operation:
                raise PurgeBlocked("illegal ledger state transition")
            self._validate_transition(previous_state, row["state"])
            last_by_op[operation], previous = row["state"], row["entry_hash"]
            rows.append(row)
        return rows

    def state(self, operation_id):
        rows = [r for r in self.rows() if r["operation_id"] == operation_id]
        return rows[-1]["state"] if rows else None

    def assert_binding(self, binding):
        for row in self.rows():
            if (
                row["nonce"] == binding["nonce"]
                and row["operation_id"] != binding["operation_id"]
            ):
                raise PurgeBlocked("nonce replay detected")
            if row["operation_id"] == binding["operation_id"]:
                for field, value in binding.items():
                    if row[field] != value:
                        raise PurgeBlocked(f"operation binding changed: {field}")

    def append(self, state, binding):
        if state not in self.states:
            raise ValueError(state)
        rows = self.rows()
        operation = binding.get("operation_id") if isinstance(binding, dict) else None
        previous_state = next(
            (
                row["state"]
                for row in reversed(rows)
                if row.get("operation_id") == operation
            ),
            None,
        )
        self._validate_transition(previous_state, state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = binding | {
            "state": state,
            "prev_hash": rows[-1]["entry_hash"] if rows else "",
        }
        row["entry_hash"] = canonical_hash(row)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


@contextmanager
def _operation_lock(
    root: Path, operation_id: str, nonce: str, root_identity: dict[str, Any]
):
    """Acquire a durable O_EXCL operation lock; quarantine only proven-dead owners."""
    lock = root / ".rfb-purge-operation.lock"
    payload = {
        "operation_id": operation_id,
        "nonce": nonce,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "root_identity": root_identity,
    }
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(fd, canonical_bytes(payload))
                os.fsync(fd)
            finally:
                os.close(fd)
            break
        except FileExistsError as exc:
            try:
                owner = json.loads(lock.read_text(encoding="utf-8"))
                owner_pid = int(owner.get("pid", -1))
            except (
                OSError,
                ValueError,
                TypeError,
                json.JSONDecodeError,
            ) as parse_error:
                raise PurgeBlocked(
                    "purge operation lock is unreadable"
                ) from parse_error
            if (
                owner.get("root_identity") != root_identity
                or owner.get("operation_id") != operation_id
                or owner.get("nonce") != nonce
            ):
                raise PurgeBlocked("purge operation lock is owned by another operation")
            # A PID is only meaningful on the host that created the lock.  In
            # particular, never reclaim a lock from a foreign NFS host merely
            # because its PID is not present in this host's process table.
            if owner.get("host") != socket.gethostname():
                raise PurgeBlocked("purge operation lock owner host is unverifiable")
            if not _pid_alive(owner_pid):
                stale = lock.with_name(
                    f"{lock.name}.stale.{owner_pid}.{owner.get('nonce', 'unknown')}"
                )
                try:
                    os.replace(lock, stale)
                except OSError as race:
                    raise PurgeBlocked("stale purge lock recovery raced") from race
                continue
            raise PurgeBlocked("purge operation is already active") from exc
    try:
        yield
    finally:
        try:
            current = json.loads(lock.read_text(encoding="utf-8"))
            if current.get("pid") == os.getpid() and current.get("nonce") == nonce:
                lock.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass


def execute_purge(
    *,
    root,
    capability,
    approval,
    issuer_trust,
    approver_trust,
    current_root_identity,
    ledger,
    now=None,
    crash_at=None,
    no_writer_attestation=None,
    attester_trust=None,
):
    stamp = _now(now)
    cap = _verify(capability, issuer_trust, "PurgeCapabilityIssuer")
    app = _verify(approval, approver_trust, "DestructiveApprover")
    if (
        attester_trust is None
        or attester_trust.get("identity")
        in {issuer_trust.get("identity"), approver_trust.get("identity")}
        or attester_trust.get("key_id")
        in {issuer_trust.get("key_id"), approver_trust.get("key_id")}
        or attester_trust.get("key")
        in {issuer_trust.get("key"), approver_trust.get("key")}
    ):
        raise PurgeBlocked("independent no-writer attester required")
    verify_no_writer_attestation(
        no_writer_attestation, attester_trust, capability=cap, now=stamp
    )
    if (
        issuer_trust.get("identity") == approver_trust.get("identity")
        or issuer_trust.get("key_id") == approver_trust.get("key_id")
        or issuer_trust.get("key") == approver_trust.get("key")
    ):
        raise PurgeBlocked("issuer and approver must be distinct")
    if app.get("capability_hash") != canonical_hash(capability):
        raise PurgeBlocked("approval not bound to capability")
    bound = (
        "segment_id",
        "root",
        "root_identity",
        "manifest_hash",
        "allowlist_hash",
        "target_bindings",
        "nonce",
        "operation_id",
    )
    if any(app.get(k) != cap.get(k) for k in bound):
        raise PurgeBlocked("approval binding mismatch")
    root_path = Path(root)
    resolved_root = root_path.resolve(strict=True)
    if root_path.is_symlink() or str(resolved_root) != cap["root"]:
        raise PurgeBlocked("root path mismatch")
    if dict(current_root_identity) != cap["root_identity"]:
        raise PurgeBlocked("root identity drift")
    binding = {
        "operation_id": cap["operation_id"],
        "segment_id": cap["segment_id"],
        "root": cap["root"],
        "manifest_hash": cap["manifest_hash"],
        "allowlist_hash": cap["allowlist_hash"],
        "target_bindings": cap["target_bindings"],
        "nonce": cap["nonce"],
        "capability_hash": canonical_hash(capability),
        "approval_hash": canonical_hash(approval),
    }
    with _operation_lock(
        resolved_root, cap["operation_id"], cap["nonce"], cap["root_identity"]
    ):
        _assert_root_stable(resolved_root, cap["root_identity"])
        verify_no_writer_attestation(
            no_writer_attestation, attester_trust, capability=cap, now=stamp
        )
        ledger.assert_binding(binding)
        state = ledger.state(cap["operation_id"])
        # Expiry blocks new operations, but an operation that already recorded
        # CLAIMED/PURGE_INTENT may finish its exact-bound recovery.  The
        # binding check above prevents extending an expired authorization to a
        # different root, manifest, allowlist, or nonce.
        if state not in {"CLAIMED", "PURGE_INTENT", "ABORTED"} and (
            stamp >= _time(cap["expires_at"], "capability expiry")
            or stamp >= _time(app["expires_at"], "approval expiry")
        ):
            raise PurgeBlocked("authorization expired")
        if state == "COMMITTED":
            residual = [
                relative
                for relative in cap["allowlist_paths"]
                if (resolved_root.joinpath(*PurePosixPath(relative).parts)).exists()
                or (resolved_root.joinpath(*PurePosixPath(relative).parts)).is_symlink()
            ]
            if residual:
                raise PurgeBlocked("committed purge residuals require reconciliation")
            return {"status": "COMMITTED", "deleted": []}
        if state == "ABORTED":
            raise PurgeBlocked("ABORTED purge requires manual reconciliation")
        if state is None:
            ledger.append("APPROVAL_RECORDED", binding)
            state = "APPROVAL_RECORDED"
        if state == "APPROVAL_RECORDED":
            ledger.append("CLAIMED", binding)
            state = "CLAIMED"
            if crash_at == "claimed":
                raise RuntimeError("simulated crash after CLAIMED")
        if state == "CLAIMED":
            ledger.append("PURGE_INTENT", binding)
            state = "PURGE_INTENT"
            if crash_at == "intent":
                raise RuntimeError("simulated crash after PURGE_INTENT")
        if state != "PURGE_INTENT":
            raise PurgeBlocked(f"unexpected state {state}")
        # Destructive phase uses a private in-root quarantine.  A verified leaf
        # is never unlinked by pathname: rename and unlink are both descriptor-
        # relative and each boundary is durably recorded in the hash ledger.
        if os.name == "nt":
            raise PurgeBlocked("handle-relative purge unavailable on Windows")
        root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            root_fd = os.open(resolved_root, root_flags)
        except OSError as exc:
            raise PurgeBlocked("unable to retain root handle") from exc
        quarantine_name = ".rfb-purge-quarantine-" + cap["operation_id"]
        quarantine_path = resolved_root / quarantine_name
        qfd = -1
        try:
            created = False
            try:
                if os.mkdir in getattr(os, "supports_dir_fd", ()):
                    os.mkdir(quarantine_name, 0o700, dir_fd=root_fd)
                else:
                    os.mkdir(quarantine_path, 0o700)
                created = True
            except FileExistsError:
                visible_q = os.lstat(quarantine_name, dir_fd=root_fd)
                if not stat.S_ISDIR(visible_q.st_mode) or stat.S_ISLNK(
                    visible_q.st_mode
                ):
                    raise PurgeBlocked("quarantine path is not private")
            except OSError as exc:
                raise PurgeBlocked("quarantine setup failed") from exc
            if created:
                os.fsync(root_fd)
            qfd_flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            qfd = os.open(quarantine_name, qfd_flags, dir_fd=root_fd)
            qmeta = os.fstat(qfd)
            visible_q = os.lstat(quarantine_name, dir_fd=root_fd)
            if (
                not stat.S_ISDIR(qmeta.st_mode)
                or not stat.S_ISDIR(visible_q.st_mode)
                or stat.S_ISLNK(visible_q.st_mode)
                or int(qmeta.st_dev) != int(visible_q.st_dev)
                or int(qmeta.st_ino) != int(visible_q.st_ino)
            ):
                raise PurgeBlocked("quarantine identity changed")
        except (OSError, PurgeBlocked) as exc:
            if qfd >= 0:
                os.close(qfd)
            os.close(root_fd)
            if isinstance(exc, PurgeBlocked):
                raise
            raise PurgeBlocked("quarantine setup failed") from exc
        deleted = []
        try:
            for relative in cap["allowlist_paths"]:
                prior_rows = [
                    r
                    for r in ledger.rows()
                    if r.get("operation_id") == cap["operation_id"]
                    and r.get("relative") == relative
                ]
                if prior_rows and prior_rows[-1].get("state") == "UNLINK_COMMITTED":
                    deleted.append(relative)
                    continue
                if prior_rows and prior_rows[-1].get("state") == "UNLINK_QUARANTINED":
                    row_binding = prior_rows[-1]
                    qleaf = row_binding.get("quarantine")
                    expected = row_binding.get("expected")
                    if not isinstance(qleaf, str) or not isinstance(expected, dict):
                        raise PurgeBlocked("quarantine recovery binding invalid")
                    qtarget = -1
                    try:
                        if (
                            not (
                                resolved_root.joinpath(
                                    *PurePosixPath(relative).parts
                                ).exists()
                            )
                            and not (
                                resolved_root.joinpath(
                                    *PurePosixPath(relative).parts
                                ).is_symlink()
                            )
                            and not (
                                resolved_root
                                / (".rfb-purge-quarantine-" + cap["operation_id"])
                                / qleaf
                            ).exists()
                        ):
                            ledger.append("UNLINK_COMMITTED", row_binding)
                            deleted.append(relative)
                            continue
                        qtarget = os.open(
                            qleaf,
                            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                            dir_fd=qfd,
                        )
                        qmeta = os.fstat(qtarget)
                        qdigest = hashlib.sha256()
                        with os.fdopen(os.dup(qtarget), "rb") as handle:
                            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                                qdigest.update(chunk)
                        visible_q = os.stat(qleaf, dir_fd=qfd, follow_symlinks=False)
                        if (
                            not stat.S_ISREG(qmeta.st_mode)
                            or int(qmeta.st_dev) != expected.get("st_dev")
                            or int(qmeta.st_ino) != expected.get("st_ino")
                            or int(visible_q.st_dev) != expected.get("st_dev")
                            or int(visible_q.st_ino) != expected.get("st_ino")
                            or qdigest.hexdigest() != expected.get("sha256")
                        ):
                            raise PurgeBlocked("quarantine binding mismatch")
                        os.unlink(qleaf, dir_fd=qfd)
                        os.fsync(qfd)
                        if crash_at == "unlinked":
                            raise RuntimeError("simulated crash after unlink")
                        ledger.append("UNLINK_COMMITTED", row_binding)
                        if crash_at == "committed":
                            raise RuntimeError("simulated crash after UNLINK_COMMITTED")
                        deleted.append(relative)
                        continue
                    except PurgeBlocked:
                        raise
                    except (FileNotFoundError, OSError) as exc:
                        raise PurgeBlocked("quarantine recovery failed") from exc
                    finally:
                        if qtarget >= 0:
                            os.close(qtarget)
                parts = PurePosixPath(relative).parts
                expected = cap["target_bindings"].get(relative)
                qleaf = canonical_hash(relative)[:32] + ".quarantine"
                row_binding = binding | {
                    "relative": relative,
                    "expected": expected,
                    "quarantine": qleaf,
                }
                prior_state = prior_rows[-1]["state"] if prior_rows else "PURGE_INTENT"
                # A crash after rename but before UNLINK_QUARANTINED leaves
                # the source absent while the deterministic quarantine leaf
                # remains. Recover only that exact bound leaf.
                source_path = resolved_root.joinpath(*parts)
                if (
                    prior_state == "UNLINK_PREPARED"
                    and not source_path.exists()
                    and not source_path.is_symlink()
                ):
                    qtarget = -1
                    try:
                        if not isinstance(expected, dict):
                            raise PurgeBlocked("target binding missing")
                        qtarget = os.open(
                            qleaf,
                            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                            dir_fd=qfd,
                        )
                        qmeta = os.fstat(qtarget)
                        qdigest = hashlib.sha256()
                        with os.fdopen(os.dup(qtarget), "rb") as handle:
                            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                                qdigest.update(chunk)
                        visible_q = os.stat(qleaf, dir_fd=qfd, follow_symlinks=False)
                        if (
                            not stat.S_ISREG(qmeta.st_mode)
                            or int(qmeta.st_dev) != expected.get("st_dev")
                            or int(qmeta.st_ino) != expected.get("st_ino")
                            or int(visible_q.st_dev) != expected.get("st_dev")
                            or int(visible_q.st_ino) != expected.get("st_ino")
                            or qdigest.hexdigest() != expected.get("sha256")
                        ):
                            raise PurgeBlocked("quarantine binding mismatch")
                        ledger.append("UNLINK_QUARANTINED", row_binding)
                        os.unlink(qleaf, dir_fd=qfd)
                        os.fsync(qfd)
                        if crash_at == "unlinked":
                            raise RuntimeError("simulated crash after unlink")
                        ledger.append("UNLINK_COMMITTED", row_binding)
                        deleted.append(relative)
                        continue
                    except PurgeBlocked:
                        try:
                            ledger.append("ABORTED", row_binding)
                        except PurgeBlocked:
                            pass
                        raise
                    except (FileNotFoundError, OSError) as exc:
                        try:
                            ledger.append("ABORTED", row_binding)
                        except PurgeBlocked:
                            pass
                        raise PurgeBlocked("quarantine recovery failed") from exc
                    finally:
                        if qtarget >= 0:
                            os.close(qtarget)
                parent_fd = os.dup(root_fd)
                target_fd = -1
                try:
                    for component in parts[:-1]:
                        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                        if hasattr(os, "O_NOFOLLOW"):
                            flags |= os.O_NOFOLLOW
                        next_fd = os.open(component, flags, dir_fd=parent_fd)
                        os.close(parent_fd)
                        parent_fd = next_fd
                    leaf = parts[-1]
                    flags = os.O_RDONLY | (getattr(os, "O_NOFOLLOW", 0))
                    target_fd = os.open(leaf, flags, dir_fd=parent_fd)
                    expected = cap["target_bindings"].get(relative)
                    current = os.fstat(target_fd)
                    if (
                        expected is None
                        or not stat.S_ISREG(current.st_mode)
                        or int(current.st_dev) != expected["st_dev"]
                        or int(current.st_ino) != expected["st_ino"]
                    ):
                        raise PurgeBlocked("target identity changed")
                    digest = hashlib.sha256()
                    with os.fdopen(os.dup(target_fd), "rb") as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != expected["sha256"]:
                        raise PurgeBlocked("target hash changed")
                    qleaf = canonical_hash(relative)[:32] + ".quarantine"
                    row_binding = binding | {
                        "relative": relative,
                        "expected": expected,
                        "quarantine": qleaf,
                    }
                    prior = [
                        r
                        for r in ledger.rows()
                        if r.get("operation_id") == cap["operation_id"]
                        and r.get("relative") == relative
                    ]
                    prior_state = prior[-1]["state"] if prior else "PURGE_INTENT"
                    if prior_state == "PURGE_INTENT":
                        ledger.append("UNLINK_PREPARED", row_binding)
                        if crash_at == "prepared":
                            raise RuntimeError("simulated crash after UNLINK_PREPARED")
                    elif prior_state not in {
                        "UNLINK_PREPARED",
                        "UNLINK_QUARANTINED",
                        "UNLINK_COMMITTED",
                    }:
                        raise PurgeBlocked("unexpected unlink state")
                    if prior_state in {"PURGE_INTENT", "UNLINK_PREPARED"}:
                        # Re-check immediately before rename; replacement inode
                        # therefore cannot be moved into quarantine.
                        latest = os.fstat(target_fd)
                        visible = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                        if (
                            int(latest.st_dev) != expected["st_dev"]
                            or int(latest.st_ino) != expected["st_ino"]
                            or int(visible.st_dev) != expected["st_dev"]
                            or int(visible.st_ino) != expected["st_ino"]
                        ):
                            raise PurgeBlocked(
                                "target identity changed before quarantine"
                            )
                        os.rename(leaf, qleaf, src_dir_fd=parent_fd, dst_dir_fd=qfd)
                        os.fsync(parent_fd)
                        os.fsync(qfd)
                        if crash_at == "renamed":
                            raise RuntimeError("simulated crash after rename")
                        prior_state = "UNLINK_PREPARED"
                    qtarget = os.open(
                        qleaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=qfd
                    )
                    try:
                        qmeta = os.fstat(qtarget)
                        qdigest = hashlib.sha256()
                        with os.fdopen(os.dup(qtarget), "rb") as handle:
                            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                                qdigest.update(chunk)
                        if (
                            int(qmeta.st_dev) != expected["st_dev"]
                            or int(qmeta.st_ino) != expected["st_ino"]
                            or qdigest.hexdigest() != expected["sha256"]
                        ):
                            raise PurgeBlocked("quarantine binding mismatch")
                        if prior_state == "UNLINK_PREPARED":
                            ledger.append("UNLINK_QUARANTINED", row_binding)
                            if crash_at == "quarantined":
                                raise RuntimeError(
                                    "simulated crash after UNLINK_QUARANTINED"
                                )
                        if prior_state in {"UNLINK_PREPARED", "UNLINK_QUARANTINED"}:
                            visible_q = os.stat(
                                qleaf, dir_fd=qfd, follow_symlinks=False
                            )
                            if (
                                int(visible_q.st_dev) != expected["st_dev"]
                                or int(visible_q.st_ino) != expected["st_ino"]
                            ):
                                raise PurgeBlocked("quarantine identity changed")
                            os.unlink(qleaf, dir_fd=qfd)
                            os.fsync(qfd)
                            if crash_at == "unlinked":
                                raise RuntimeError("simulated crash after unlink")
                            ledger.append("UNLINK_COMMITTED", row_binding)
                            if crash_at == "committed":
                                raise RuntimeError(
                                    "simulated crash after UNLINK_COMMITTED"
                                )
                        deleted.append(relative)
                    finally:
                        os.close(qtarget)
                except PurgeBlocked:
                    try:
                        ledger.append("ABORTED", row_binding)
                    except PurgeBlocked:
                        pass
                    raise
                except (FileNotFoundError, OSError) as exc:
                    try:
                        ledger.append("ABORTED", row_binding)
                    except PurgeBlocked:
                        pass
                    raise PurgeBlocked("quarantine operation failed") from exc
                finally:
                    if target_fd >= 0:
                        os.close(target_fd)
                    os.close(parent_fd)
        finally:
            try:
                if qfd >= 0:
                    os.rmdir(quarantine_name, dir_fd=root_fd)
                    os.fsync(root_fd)
            except OSError:
                pass
            finally:
                if qfd >= 0:
                    os.close(qfd)
                os.close(root_fd)
        _assert_root_stable(resolved_root, cap["root_identity"])
        ledger.append("COMMITTED", binding)
        return {"status": "COMMITTED", "deleted": deleted}
