from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import socket
import stat
import time
import uuid
from copy import deepcopy
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rfb.authority.generation import (
    AuthorityGenerationBuilder,
    GenerationReader,
    ReaderBlocked,
    canonical_hash,
)
from rfb.contracts.canonical_json import canonical_bytes, sha256_hex


class BrokerBlocked(RuntimeError):
    pass


def _digest(v):
    return sha256_hex(canonical_bytes(v))


def acl_root_identity(root) -> str:
    return sha256_hex(str(Path(root).resolve(strict=True)).encode("utf-8"))


def sign_acl_attestation(
    *,
    key: bytes,
    root,
    trust_epoch: str,
    generation_id: str,
    checklist_hash: str,
    attester_id: str = "acl-attester",
    key_id: str = "acl-key-1",
    acl_entries=None,
) -> dict[str, str]:
    body = {
        "schema_id": "broker-acl-attestation.v1",
        "root_identity": acl_root_identity(root),
        "trust_epoch": str(trust_epoch),
        "generation_id": str(generation_id),
        "checklist_hash": str(checklist_hash),
        "attester_id": str(attester_id),
        "key_id": str(key_id),
        "acl_entries": acl_entries or [{"principal": "broker", "access": "write"}],
    }
    return {
        **body,
        "signature": hmac.new(key, canonical_bytes(body), hashlib.sha256).hexdigest(),
    }


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


@dataclass(frozen=True)
class BrokerEnvelope:
    source_artifact: Mapping[str, Any]
    source_snapshot: str
    source_hash: str
    projection_policy_id: str
    projection_policy_version: str
    expected_current_generation_id: str
    expected_checklist_hash: str
    patch: Mapping[str, Any]
    submitter_role: str
    submitter_signature: str
    source_signer_role: str
    source_signature: str
    source_schema_id: str
    trust_epoch: str

    @property
    def patch_digest(self):
        return _digest(self.patch)

    def body(self):
        return {
            k: getattr(self, k)
            for k in (
                "source_artifact",
                "source_snapshot",
                "source_hash",
                "projection_policy_id",
                "projection_policy_version",
                "expected_current_generation_id",
                "expected_checklist_hash",
                "patch",
                "submitter_role",
                "source_signer_role",
                "source_signature",
                "source_schema_id",
                "trust_epoch",
            )
        } | {"patch_digest": self.patch_digest}

    @classmethod
    def sign(cls, key: bytes, **kw):
        p = cls(submitter_signature="", **kw)
        return cls(
            submitter_signature=hmac.new(
                key, canonical_bytes(p.body()), hashlib.sha256
            ).hexdigest(),
            **kw,
        )

    def verify(self, key):
        return hmac.compare_digest(
            self.submitter_signature,
            hmac.new(key, canonical_bytes(self.body()), hashlib.sha256).hexdigest(),
        )


class LogicalCommitter:
    def __init__(self, key, role):
        self.key, self.role = key, role

    def envelope(self, **kw):
        return BrokerEnvelope.sign(key=self.key, submitter_role=self.role, **kw)


class RuntimeFreezeCommitter(LogicalCommitter):
    def __init__(self, key):
        super().__init__(key, "RuntimeFreezeCommitter")


class ChecklistCommitter(LogicalCommitter):
    def __init__(self, key):
        super().__init__(key, "ChecklistCommitter")


SOURCE_PAIRINGS = {
    "ChecklistCommitter": ("LiveGateVerifier", "live-gate-verdict-set.v1"),
    "RuntimeFreezeCommitter": ("RuntimeFreezeAuthority", "runtime-baseline.v1"),
}
REQUIRED_LIVE_GATES = (
    "segment_cap_gate",
    "durable_result_gate",
    "result_archive_gate",
    "regeneration_gate",
    "dataset_purge_gate",
)


class CASPolicyBroker:
    def __init__(
        self,
        root,
        *,
        submitter_keys=None,
        policy_id="frozen-default",
        policy_version="1",
        signing_key,
        durability_provider=None,
        acl_attestation=None,
        acl_attestation_key=None,
        acl_trust_epoch=None,
        acl_attester_id=None,
        acl_attester_key_id=None,
    ):
        if not signing_key:
            raise ValueError("signing_key is required")
        self.root = Path(root)
        self.durability_provider = durability_provider
        self.keys = dict(submitter_keys or {})
        self.policy_id = policy_id
        self.policy_version = policy_version
        self.signing_key = signing_key
        self.acl_attestation = (
            deepcopy(dict(acl_attestation))
            if isinstance(acl_attestation, Mapping)
            else acl_attestation
        )
        self.acl_attestation_key = bytes(acl_attestation_key or b"")
        self.acl_trust_epoch = str(acl_trust_epoch or "")
        self.acl_attester_id = str(acl_attester_id or "")
        self.acl_attester_key_id = str(acl_attester_key_id or "")
        self.builder = AuthorityGenerationBuilder(
            self.root, signing_key=signing_key, durability_provider=durability_provider
        )

    def _key_record(self, role):
        r = self.keys.get(role)
        if isinstance(r, bytes):
            return r, "", False
        if not isinstance(r, Mapping) or not isinstance(
            r.get("key"), (bytes, bytearray)
        ):
            raise BrokerBlocked("unknown signer role")
        return (
            bytes(r["key"]),
            str(r.get("trust_epoch", "")),
            bool(r.get("revoked", False)),
        )

    @contextlib.contextmanager
    def _lock(self):
        p = self.root / ".broker.lock"
        nonce = uuid.uuid4().hex
        pid = os.getpid()
        lease = 300.0
        while True:
            now = time.time()
            payload = {
                "pid": pid,
                "nonce": nonce,
                "host": socket.gethostname(),
                "acquired_at": now,
                "expires_at": now + lease,
            }
            try:
                fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, separators=(",", ":"))
                    f.flush()
                    os.fsync(f.fileno())
                try:
                    yield p
                finally:
                    try:
                        cur = json.loads(p.read_text())
                        if cur.get("pid") == pid and cur.get("nonce") == nonce:
                            p.unlink(missing_ok=True)
                    except (OSError, ValueError):
                        pass
                return
            except FileExistsError:
                try:
                    cur = json.loads(p.read_text())
                    owner = int(cur.get("pid", -1))
                    float(cur.get("expires_at", 0))
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    raise BrokerBlocked("broker lock is malformed") from exc
                if (
                    owner < 1
                    or "expires_at" not in cur
                    or cur.get("host") != socket.gethostname()
                    or not cur.get("nonce")
                ):
                    raise BrokerBlocked("broker lock belongs to another host")
                if _pid_alive(owner):
                    raise BrokerBlocked("broker lock is held by a live owner")
                # Reclaim only a dead owner. Atomic rename prevents an old cleaner from
                # unlinking a newer owner that won the lock path.
                tomb = p.with_name(p.name + ".reclaim." + uuid.uuid4().hex)
                try:
                    os.rename(p, tomb)
                except FileNotFoundError:
                    continue
                except OSError:
                    time.sleep(0.01)
                    continue
                try:
                    try:
                        moved = json.loads(tomb.read_text(encoding="utf-8"))
                    except (OSError, ValueError, TypeError):
                        moved = {}
                    if (
                        moved.get("nonce") == cur.get("nonce")
                        and int(moved.get("pid", -1)) == owner
                    ):
                        tomb.unlink(missing_ok=True)
                    elif not p.exists():
                        try:
                            os.link(tomb, p)
                        except OSError:
                            pass
                finally:
                    tomb.unlink(missing_ok=True)

    def _atomic_current(self, value: str, name: str):
        tmp = self.root / name
        fd = os.open(
            tmp,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise BrokerBlocked("CURRENT temp is not regular")
            with os.fdopen(fd, "wb") as f:
                fd = -1
                f.write(value.encode("ascii"))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.root / "CURRENT")
            if self.durability_provider:
                self.durability_provider.fsync_dir(self.root)
            else:
                dfd = os.open(self.root, os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
        finally:
            if fd != -1:
                try:
                    os.close(fd)
                except OSError:
                    pass
            tmp.unlink(missing_ok=True)

    def _audit(self, status, **b):
        row = self.builder.append_audit(status, **b)
        try:
            from jsonschema import Draft202012Validator

            schema = json.loads(
                (
                    Path(__file__).parents[1] / "contracts" / "broker_audit.schema.json"
                ).read_text()
            )
            Draft202012Validator(schema).validate(row)
        except Exception as exc:
            raise BrokerBlocked("audit schema invalid") from exc
        return row

    def _check(self, c):
        p = self.root / "generations" / c["generation_id"] / "checklist_authority.json"
        try:
            authority = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BrokerBlocked(
                "canonical checklist authority missing or unreadable"
            ) from exc
        if not isinstance(authority, Mapping) or not isinstance(
            authority.get("checklist"), Mapping
        ):
            raise BrokerBlocked("canonical checklist authority invalid")
        observed = _digest(authority["checklist"])
        if authority.get("checklist_hash") != observed:
            raise BrokerBlocked("canonical checklist authority hash mismatch")
        manifest_hash = c.get("manifest", {}).get("checklist_hash")
        if manifest_hash and manifest_hash != observed:
            raise BrokerBlocked("manifest checklist authority mismatch")
        return observed

    def current_authority(self):
        c = GenerationReader(
            self.root, signing_key=self.signing_key, authoritative=True
        ).read(runtime=False)
        c["checklist_hash"] = self._check(c)
        return c

    def projection(self, e):
        if (e.projection_policy_id, e.projection_policy_version) != (
            self.policy_id,
            self.policy_version,
        ):
            raise BrokerBlocked("projection policy mismatch")
        a = e.source_artifact
        if SOURCE_PAIRINGS.get(e.submitter_role) != (
            e.source_signer_role,
            e.source_schema_id,
        ):
            raise BrokerBlocked("submitter/source role pairing mismatch")
        if e.submitter_role == "ChecklistCommitter":
            self._validate_live_verdict(a)
            snapshot = deepcopy(dict(a["source_snapshot"]))
            for gate in REQUIRED_LIVE_GATES:
                snapshot[gate] = deepcopy(a["verdicts"][gate])
            return {"checklist": snapshot}
        if not isinstance(a, Mapping) or a.get("schema_id") != "runtime-baseline.v1":
            raise BrokerBlocked("runtime-freeze source schema mismatch")
        # A runtime freeze may only publish its explicitly declared runtime
        # partition.  Metadata (and any future non-runtime partitions) must
        # never leak into the checklist authority.
        runtime = a.get("runtime")
        if not isinstance(runtime, Mapping):
            raise BrokerBlocked("runtime-freeze runtime partition missing")
        return {"checklist": deepcopy(dict(runtime))}

    def _validate_live_verdict(self, artifact):
        try:
            from jsonschema import Draft202012Validator

            schema = json.loads(
                (
                    Path(__file__).parents[1]
                    / "contracts"
                    / "live_gate_verdict_set.schema.json"
                ).read_text()
            )
            Draft202012Validator(schema).validate(artifact)
        except Exception as exc:
            raise BrokerBlocked("invalid live-gate verdict envelope") from exc
        if artifact.get("signer_role") != "LiveGateVerifier":
            raise BrokerBlocked("live verdict signer role mismatch")
        if artifact.get("source_snapshot_hash") != _digest(artifact["source_snapshot"]):
            raise BrokerBlocked("live verdict source snapshot mismatch")
        if any(
            artifact["verdicts"][g].get("status") != "PASS" for g in REQUIRED_LIVE_GATES
        ):
            raise BrokerBlocked("live verdict gates are not all PASS")

    def _verify_acl(self, generation_id, checklist_hash):
        att = self.acl_attestation
        if not self.acl_attestation_key or not isinstance(att, Mapping):
            raise BrokerBlocked("independent ACL attestation required")
        body = {
            k: att.get(k)
            for k in (
                "schema_id",
                "root_identity",
                "trust_epoch",
                "generation_id",
                "checklist_hash",
                "attester_id",
                "key_id",
                "acl_entries",
            )
        }
        if body["schema_id"] != "broker-acl-attestation.v1":
            raise BrokerBlocked("ACL attestation schema mismatch")
        if body["root_identity"] != acl_root_identity(self.root):
            raise BrokerBlocked("ACL attestation root mismatch")
        if body["trust_epoch"] != self.acl_trust_epoch:
            raise BrokerBlocked("ACL attestation trust epoch mismatch")
        if body["generation_id"] != generation_id:
            raise BrokerBlocked("ACL attestation generation mismatch")
        if body["checklist_hash"] != checklist_hash:
            raise BrokerBlocked("ACL attestation checklist mismatch")
        if (
            body["attester_id"] != self.acl_attester_id
            or body["key_id"] != self.acl_attester_key_id
        ):
            raise BrokerBlocked("ACL attestation attester identity mismatch")
        if body["acl_entries"] != [{"principal": "broker", "access": "write"}]:
            raise BrokerBlocked("ACL evidence is not exclusive")
        if body["attester_id"] in self.keys:
            raise BrokerBlocked("ACL attestation attester overlaps signer role")
        trusted_keys = [self.signing_key] + [
            r if isinstance(r, (bytes, bytearray)) else r.get("key")
            for r in self.keys.values()
        ]
        if any(
            isinstance(k, (bytes, bytearray)) and bytes(k) == self.acl_attestation_key
            for k in trusted_keys
        ):
            raise BrokerBlocked("ACL attester key must be independent")
        expected = hmac.new(
            self.acl_attestation_key, canonical_bytes(body), hashlib.sha256
        ).hexdigest()
        if not isinstance(att.get("signature"), str) or not hmac.compare_digest(
            att["signature"], expected
        ):
            raise BrokerBlocked("ACL attestation signature invalid")
        """Verify root ownership and mode from the operating system."""
        try:
            st = self.root.lstat()
            if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
                raise BrokerBlocked(
                    "OS ACL attestation failed: root is not a directory"
                )
            if hasattr(os, "geteuid") and st.st_uid != os.geteuid():
                raise BrokerBlocked("OS ACL attestation failed: root owner mismatch")
            # Permission bits are supplemental telemetry; signed attestation is authoritative.
        except BrokerBlocked:
            raise
        except (AttributeError, OSError) as exc:
            raise BrokerBlocked("OS ACL attestation failed") from exc

        return _digest(self.acl_attestation)

    def _validate_prerequisites(
        self, e, *, expected_generation_id=None, expected_checklist_hash=None
    ):
        expected_generation_id = (
            expected_generation_id or e.expected_current_generation_id
        )
        expected_checklist_hash = expected_checklist_hash or e.expected_checklist_hash
        if not expected_generation_id or not expected_checklist_hash:
            raise BrokerBlocked("expected pair required")
        k, _ep, revoked = self._key_record(e.submitter_role)
        if revoked or not e.verify(k):
            raise BrokerBlocked("invalid submitter signature")
        if e.source_hash != _digest(e.source_artifact):
            raise BrokerBlocked("source hash mismatch")
        if SOURCE_PAIRINGS.get(e.submitter_role) != (
            e.source_signer_role,
            e.source_schema_id,
        ):
            raise BrokerBlocked("submitter/source role pairing mismatch")
        acl_digest = self._verify_acl(expected_generation_id, expected_checklist_hash)
        sk, source_epoch, source_revoked = self._key_record(e.source_signer_role)
        proof = {
            "source_artifact": e.source_artifact,
            "source_snapshot": e.source_snapshot,
            "source_hash": e.source_hash,
            "source_schema_id": e.source_schema_id,
            "trust_epoch": e.trust_epoch,
        }
        artifact_sig_ok = True
        if e.submitter_role == "ChecklistCommitter":
            body = dict(e.source_artifact)
            artifact_sig = body.pop("signature", None)
            artifact_sig_ok = isinstance(artifact_sig, str) and hmac.compare_digest(
                artifact_sig,
                hmac.new(sk, canonical_bytes(body), hashlib.sha256).hexdigest(),
            )
        if (
            source_revoked
            or (e.trust_epoch and source_epoch and e.trust_epoch != source_epoch)
            or not e.source_signature
            or not hmac.compare_digest(
                e.source_signature,
                hmac.new(sk, canonical_bytes(proof), hashlib.sha256).hexdigest(),
            )
            or not artifact_sig_ok
        ):
            raise BrokerBlocked("invalid source proof")
        if dict(e.patch) != self.projection(e):
            raise BrokerBlocked("patch differs from deterministic projection")
        if e.submitter_role == "ChecklistCommitter":
            snapshot = e.source_artifact.get("source_snapshot")
            if (
                not isinstance(snapshot, Mapping)
                or _digest(snapshot) != expected_checklist_hash
            ):
                raise BrokerBlocked("verdict predecessor checklist mismatch")
        return acl_digest

    def _envelope_from_binding(self, b):
        fields = {
            "source_artifact": b.get("source_artifact"),
            "source_snapshot": b.get("source_snapshot"),
            "source_hash": b.get("source_hash"),
            "projection_policy_id": b.get("projection_policy_id"),
            "projection_policy_version": b.get("projection_policy_version"),
            "expected_current_generation_id": b.get("expected_generation_id"),
            "expected_checklist_hash": b.get("expected_checklist_hash"),
            "patch": b.get("patch"),
            "submitter_role": b.get("submitter_role"),
            "submitter_signature": b.get("submitter_signature"),
            "source_signer_role": b.get("source_signer_role"),
            "source_signature": b.get("source_signature"),
            "source_schema_id": b.get("source_schema_id"),
            "trust_epoch": b.get("trust_epoch"),
        }
        if not all(v is not None for v in fields.values()):
            raise BrokerBlocked("prepared binding is incomplete")
        try:
            return BrokerEnvelope(**fields)
        except (TypeError, ValueError) as exc:
            raise BrokerBlocked("prepared binding envelope invalid") from exc

    def _validate_envelope(self, e):
        try:
            from jsonschema import Draft202012Validator

            schema = json.loads(
                (
                    Path(__file__).parents[1]
                    / "contracts"
                    / "broker_envelope.schema.json"
                ).read_text()
            )
            Draft202012Validator(schema).validate(
                e.body()
                | {
                    "patch_digest": e.patch_digest,
                    "submitter_signature": e.submitter_signature,
                }
            )
        except Exception as exc:
            raise BrokerBlocked("envelope schema invalid") from exc

    def submit(self, e, *, crash_at=None):
        self._validate_envelope(e)
        k, _ep, rv = self._key_record(e.submitter_role)
        if rv or not e.verify(k):
            raise BrokerBlocked("invalid submitter signature")
        if not e.expected_current_generation_id or not e.expected_checklist_hash:
            raise BrokerBlocked("expected pair required")
        if e.source_hash != _digest(e.source_artifact):
            raise BrokerBlocked("source hash mismatch")
        if SOURCE_PAIRINGS.get(e.submitter_role) != (
            e.source_signer_role,
            e.source_schema_id,
        ):
            raise BrokerBlocked("submitter/source role pairing mismatch")
        # Publication of either authority is an external side effect and must
        # be protected by an independently verified ACL.  A caller-provided
        # claim is intentionally ignored (self-attestation is not evidence).
        self._verify_acl(e.expected_current_generation_id, e.expected_checklist_hash)
        if e.source_signer_role:
            sk, se, sr = self._key_record(e.source_signer_role)
            proof = {
                "source_artifact": e.source_artifact,
                "source_snapshot": e.source_snapshot,
                "source_hash": e.source_hash,
                "source_schema_id": e.source_schema_id,
                "trust_epoch": e.trust_epoch,
            }
            artifact_sig_ok = True
            if e.submitter_role == "ChecklistCommitter":
                body = dict(e.source_artifact)
                artifact_sig = body.pop("signature", None)
                artifact_sig_ok = isinstance(artifact_sig, str) and hmac.compare_digest(
                    artifact_sig,
                    hmac.new(sk, canonical_bytes(body), hashlib.sha256).hexdigest(),
                )
            if (
                sr
                or (e.trust_epoch and se and e.trust_epoch != se)
                or not e.source_signature
                or not hmac.compare_digest(
                    e.source_signature,
                    hmac.new(sk, canonical_bytes(proof), hashlib.sha256).hexdigest(),
                )
                or not artifact_sig_ok
            ):
                raise BrokerBlocked("invalid source proof")
        if dict(e.patch) != self.projection(e):
            raise BrokerBlocked("patch differs from deterministic projection")
        with self._lock():
            c = GenerationReader(
                self.root, signing_key=self.signing_key, authoritative=True
            ).read(runtime=False)
            actual = self._check(c)
            if (
                c["generation_id"] != e.expected_current_generation_id
                or actual != e.expected_checklist_hash
            ):
                self._audit(
                    "BROKER_ABORTED",
                    request_id=uuid.uuid4().hex,
                    operation_id="abort",
                    generation_id=c["generation_id"],
                    predecessor_generation_id=c["generation_id"],
                    reason="CAS_LOSER",
                    expected_generation_id=e.expected_current_generation_id,
                    expected_checklist_hash=e.expected_checklist_hash,
                    source_artifact=e.source_artifact,
                    source_snapshot=e.source_snapshot,
                    source_hash=e.source_hash,
                    source_schema_id=e.source_schema_id,
                    trust_epoch=e.trust_epoch,
                    projection_policy_id=e.projection_policy_id,
                    projection_policy_version=e.projection_policy_version,
                    submitter_role=e.submitter_role,
                    source_signer_role=e.source_signer_role,
                    submitter_signature=e.submitter_signature,
                    source_signature=e.source_signature,
                    patch_digest=e.patch_digest,
                    receipt_hash="0" * 64,
                    manifest_hash="0" * 64,
                    business_state_delta=1,
                )
                raise BrokerBlocked("stale expected pair")
            # Revalidate every submit prerequisite while holding the lock,
            # immediately before constructing the durable PREPARED binding.
            acl_digest = self._validate_prerequisites(
                e,
                expected_generation_id=c["generation_id"],
                expected_checklist_hash=actual,
            )
            # The live verdict must be based on the exact checklist that won
            # the CAS, not merely on a caller-supplied expected hash.
            if e.submitter_role == "ChecklistCommitter":
                source_snapshot = e.source_artifact.get("source_snapshot")
                if (
                    not isinstance(source_snapshot, Mapping)
                    or _digest(source_snapshot) != actual
                ):
                    raise BrokerBlocked("verdict predecessor checklist mismatch")
                if dict(e.patch) != self.projection(e):
                    raise BrokerBlocked("patch differs from locked projection")
            rid = uuid.uuid4().hex
            s = self.builder.build_successor(
                c["generation_id"],
                checklist_replacement=dict(e.patch["checklist"]),
                operation_id=rid,
                schema_ids={
                    "result": "v2",
                    "runtime_authority": "runtime-authority.v2",
                    "checklist_authority": "checklist-authority.v2",
                },
                policy_ids={"projection": self.policy_id},
                business_state_delta=1,
            )
            gid = s["generation_id"]
            if (
                s.get("receipt", {}).get("parent_generation") != c["generation_id"]
                or s.get("manifest", {}).get("parent_generation") != c["generation_id"]
                or s.get("receipt", {}).get("generation_id") != gid
                or s.get("manifest", {}).get("generation_id") != gid
            ):
                raise BrokerBlocked("successor parent binding mismatch")
            b = {
                "request_id": rid,
                "operation_id": rid,
                "generation_id": gid,
                "predecessor_generation_id": c["generation_id"],
                "predecessor_checklist_hash": actual,
                "successor_checklist_hash": _digest(e.patch["checklist"]),
                "expected_generation_id": e.expected_current_generation_id,
                "expected_checklist_hash": e.expected_checklist_hash,
                "source_hash": e.source_hash,
                "source_snapshot": e.source_snapshot,
                "patch": deepcopy(dict(e.patch)),
                "acl_attestation_digest": acl_digest,
                "acl_attestation": deepcopy(dict(self.acl_attestation)),
                "source_schema_id": e.source_schema_id,
                "trust_epoch": e.trust_epoch,
                "patch_digest": e.patch_digest,
                "business_state_delta": 1,
                "receipt_hash": canonical_hash(s["receipt"]),
                "manifest_hash": s["manifest"]["manifest_sha256"],
                "source_artifact": e.source_artifact,
                "projection_policy_id": e.projection_policy_id,
                "projection_policy_version": e.projection_policy_version,
                "submitter_role": e.submitter_role,
                "source_signer_role": e.source_signer_role,
                "submitter_signature": e.submitter_signature,
                "source_signature": e.source_signature,
            }
            self._audit("BROKER_PREPARED", **b)
            if crash_at == "prepared":
                raise RuntimeError("simulated crash")
            self._atomic_current(gid, "CURRENT." + rid + ".tmp")
            if crash_at == "cas":
                raise RuntimeError("simulated crash after CAS")
            self._audit("BROKER_COMMITTED", **b)
            self._audit("COMMITTED", **b)
            return GenerationReader(
                self.root, signing_key=self.signing_key, authoritative=True
            ).read(runtime=False)

    def recover_commit(self, request_id, generation_id):
        with self._lock():
            ap = self.root / "authority_audit.jsonl"
            rows = (
                [json.loads(x) for x in ap.read_text().splitlines() if x]
                if ap.exists()
                else []
            )
            prev = ""
            for r in rows:
                if r.get("previous_hash", "") != prev or r.get(
                    "entry_hash"
                ) != canonical_hash({k: v for k, v in r.items() if k != "entry_hash"}):
                    raise BrokerBlocked("audit hash chain tampered")
                prev = r["entry_hash"]
            p = next(
                (
                    r
                    for r in reversed(rows)
                    if r.get("status") == "BROKER_PREPARED"
                    and r.get("binding", {}).get("request_id") == request_id
                    and r.get("binding", {}).get("generation_id") == generation_id
                ),
                None,
            )
            if not p:
                raise BrokerBlocked("no audited prepared operation")
            b = p["binding"]
            if b.get("acl_attestation_digest") != _digest(b.get("acl_attestation")):
                raise BrokerBlocked("prepared ACL proof digest mismatch")
            if b.get("acl_attestation") != self.acl_attestation:
                raise BrokerBlocked("prepared ACL proof changed")
            envelope = self._envelope_from_binding(b)
            # Recovery is allowed only after the same trust, signature, ACL,
            # projection, and predecessor checks required for a fresh submit.
            self._validate_envelope(envelope)
            self._validate_prerequisites(
                envelope,
                expected_generation_id=b.get("expected_generation_id"),
                expected_checklist_hash=b.get("expected_checklist_hash"),
            )
            pred = b.get("predecessor_generation_id")
            if b.get("expected_generation_id") != pred:
                raise BrokerBlocked("requested generation predecessor mismatch")
            if not isinstance(pred, str) or not pred:
                raise BrokerBlocked("requested generation predecessor missing")
            terminals = [
                r
                for r in rows
                if r.get("status") in ("BROKER_COMMITTED", "COMMITTED")
                and r.get("binding", {}).get("request_id") == request_id
            ]
            if terminals:
                if any(
                    r.get("binding", {}).get("generation_id") != generation_id
                    for r in terminals
                ):
                    raise BrokerBlocked("mixed request terminal")
                return GenerationReader(
                    self.root, signing_key=self.signing_key, authoritative=True
                ).read(runtime=False)
            cur = (self.root / "CURRENT").read_text().strip()
            try:
                d = self.root / "generations" / generation_id
                rec = json.loads((d / "receipt.json").read_text())
                man = json.loads((d / "manifest.json").read_text())
                if canonical_hash(rec) != b.get("receipt_hash") or man.get(
                    "manifest_sha256"
                ) != b.get("manifest_hash"):
                    raise ValueError
                GenerationReader(
                    self.root, signing_key=self.signing_key
                ).verify_generation(generation_id, require_audit=False)
                if b.get("successor_checklist_hash"):
                    successor_checklist = json.loads(
                        (d / "checklist_authority.json").read_text(encoding="utf-8")
                    )
                    if (
                        successor_checklist.get("checklist_hash")
                        != b["successor_checklist_hash"]
                    ):
                        raise BrokerBlocked("successor checklist binding mismatch")
                if cur == pred:
                    self._atomic_current(
                        generation_id, "CURRENT.recover." + request_id + ".tmp"
                    )
                    cur = generation_id
                if cur != generation_id:
                    raise BrokerBlocked("CURRENT does not name successor")
                self._audit("BROKER_COMMITTED", **b, recovery=True)
                self._audit("COMMITTED", **b, recovery=True)
                return GenerationReader(
                    self.root, signing_key=self.signing_key, authoritative=True
                ).read(runtime=False)
            except BrokerBlocked:
                raise
            except (KeyError, OSError, ReaderBlocked, TypeError, ValueError):
                if cur != generation_id:
                    raise BrokerBlocked("successor invalid and CURRENT changed")
                try:
                    GenerationReader(
                        self.root, signing_key=self.signing_key
                    ).verify_generation(pred, require_audit=True)
                except (KeyError, OSError, ReaderBlocked, TypeError, ValueError) as exc:
                    raise BrokerBlocked("predecessor not terminal") from exc
                if (self.root / "CURRENT").read_text().strip() != generation_id:
                    raise BrokerBlocked("rollback CAS loser")
                self._atomic_current(pred, "CURRENT.rollback." + request_id + ".tmp")
                self._audit("BROKER_ROLLED_BACK", **b, rollback_to=pred, recovery=True)
                return GenerationReader(
                    self.root, signing_key=self.signing_key, authoritative=True
                ).read(runtime=False)
