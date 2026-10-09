from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rfb.contracts.canonical_json import canonical_bytes

from .generation import (
    ABSENT,
    AuthorityGenerationBuilder,
    GenerationReader,
    ReaderBlocked,
    canonical_hash,
    verify_receipt,
)

if os.name == "posix":
    import fcntl
else:
    import msvcrt

_THREAD_LOCK_GUARD = threading.Lock()
_THREAD_LOCKS = {}


@dataclass(frozen=True)
class FreezeProof:
    identity: str
    lock_id: str
    planned_hashes: Mapping[str, str]
    valid: bool = True
    issued: str = ""
    expires: str = ""
    held_token: str = ""
    identities: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    lock_provider: str = ""
    lock_owner: str = ""
    lock_held: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "lock_id": self.lock_id,
            "planned_hashes": dict(self.planned_hashes),
            "identities": {k: dict(v) for k, v in self.identities.items()},
            "valid": self.valid,
            "issued": self.issued,
            "expires": self.expires,
            "held_token": self.held_token,
            "lock_provider": self.lock_provider,
            "lock_owner": self.lock_owner,
            "lock_held": self.lock_held,
        }


@dataclass(frozen=True)
class NoWriterAttestation:
    """Independently signed statement that no writer changed legacy inputs."""

    signer_id: str
    trust_epoch: str
    root: str
    planned_hashes: Mapping[str, str]
    identities: Mapping[str, Mapping[str, Any]]
    issued: str
    expires: str
    signature: str

    def body(self) -> dict[str, Any]:
        return {
            "schema_id": "authority-no-writer-attestation.v1",
            "signer_id": self.signer_id,
            "trust_epoch": self.trust_epoch,
            "root": self.root,
            "planned_hashes": dict(self.planned_hashes),
            "identities": {k: dict(v) for k, v in self.identities.items()},
            "issued": self.issued,
            "expires": self.expires,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(), "signature": self.signature}


class NoWriterTrustStore:
    """Explicit trust store for independently signed no-writer attestations."""

    def __init__(self, keys: Mapping[str, bytes], *, trust_epoch: str):
        self.keys = {str(k): bytes(v) for k, v in keys.items()}
        self.trust_epoch = str(trust_epoch)

    def verify(self, attestation: NoWriterAttestation | Mapping[str, Any]) -> bool:
        value = (
            attestation.to_dict()
            if isinstance(attestation, NoWriterAttestation)
            else dict(attestation)
        )
        signer = value.get("signer_id")
        if not isinstance(signer, str) or signer not in self.keys:
            raise ReaderBlocked("no-writer signer is not trusted")
        if value.get("trust_epoch") != self.trust_epoch:
            raise ReaderBlocked("no-writer trust epoch mismatch")
        signature = value.get("signature")
        body = {k: v for k, v in value.items() if k != "signature"}
        expected = hmac.new(
            self.keys[signer], canonical_bytes(body), hashlib.sha256
        ).hexdigest()
        if not isinstance(signature, str) or not hmac.compare_digest(
            signature, expected
        ):
            raise ReaderBlocked("no-writer attestation signature invalid")
        return True


def sign_no_writer_attestation(
    body: Mapping[str, Any], *, signer_id: str, key: bytes
) -> dict[str, Any]:
    payload = {
        **dict(body),
        "schema_id": "authority-no-writer-attestation.v1",
        "signer_id": signer_id,
    }
    payload["signature"] = hmac.new(
        key, canonical_bytes(payload), hashlib.sha256
    ).hexdigest()
    return payload


class LegacyAuthorityFreeze:
    """Real cross-platform advisory locks and identity snapshot for legacy files."""

    def __init__(self, paths):
        self.paths = {k: Path(v) for k, v in paths.items()}
        self.handles = {}
        self._lock_lengths = {}
        self.token = None

    def __enter__(self):
        try:
            for name, p in self.paths.items():
                if not p.is_file():
                    raise FileNotFoundError(p)
                fh = p.open("r+b")
                self.handles[name] = fh
                if os.name == "posix":
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                else:
                    fh.seek(0)
                    n = max(1, p.stat().st_size)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, n)
                    self._lock_lengths[name] = n
            self.token = uuid.uuid4().hex
            return self
        except BaseException:
            for fh in self.handles.values():
                try:
                    fh.close()
                except OSError:
                    pass
            self.handles.clear()
            self._lock_lengths.clear()
            self.token = None
            raise

    def __exit__(self, *exc):
        for name, fh in self.handles.items():
            try:
                if os.name == "posix":
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                else:
                    fh.seek(0)
                    msvcrt.locking(
                        fh.fileno(), msvcrt.LK_UNLCK, self._lock_lengths.get(name, 1)
                    )
            finally:
                fh.close()
        self.handles.clear()
        self._lock_lengths.clear()
        self.token = None

    def _read_bytes(self, name):
        fh = self.handles.get(name)
        if fh is None:
            return self.paths[name].read_bytes()
        fh.seek(0)
        return fh.read()

    def proof(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        hashes = {
            k: hashlib.sha256(self._read_bytes(k)).hexdigest()
            for k, p in self.paths.items()
        }
        ids = {}
        for k, p in self.paths.items():
            st = p.stat()
            ids[k] = {
                "path": str(p.resolve()),
                "dev": st.st_dev,
                "ino": st.st_ino,
                "size": st.st_size,
                "mtime_ns": st.st_mtime_ns,
                "sha256": hashes[k],
            }
        return FreezeProof(
            "legacy-authority-freeze",
            self.token or "",
            hashes,
            True,
            now.isoformat(),
            (now + timedelta(hours=1)).isoformat(),
            self.token or "",
            ids,
            "LegacyAuthorityFreeze",
            "runtime",
            bool(self.handles),
        )

    def verify(self, proof):
        if not self.handles or not self.token or proof.held_token != self.token:
            raise ReaderBlocked("legacy freeze lock not held")
        measured = {
            k: hashlib.sha256(self._read_bytes(k)).hexdigest()
            for k, p in self.paths.items()
        }
        if measured != proof.planned_hashes:
            raise ReaderBlocked("legacy freeze drift")
        return True


class GenesisMigrator:
    """ABSENT-sentinel bootstrap with append-only recovery audit."""

    def __init__(self, root: str | Path, *, signing_key: bytes, freeze_verifier=None):
        if not signing_key:
            raise ValueError("signing_key is required")
        self.root = Path(root)
        self.builder = AuthorityGenerationBuilder(self.root, signing_key=signing_key)
        self.key = signing_key
        self.freeze_verifier = freeze_verifier

    def _hash_legacy(self, legacy: Mapping[str, str]) -> dict[str, str]:
        out = {}
        for name, value in legacy.items():
            p = Path(value)
            if not p.is_file():
                raise FileNotFoundError(value)
            if (
                isinstance(self.freeze_verifier, LegacyAuthorityFreeze)
                and name in self.freeze_verifier.handles
            ):
                out[name] = hashlib.sha256(
                    self.freeze_verifier._read_bytes(name)
                ).hexdigest()
            else:
                out[name] = hashlib.sha256(p.read_bytes()).hexdigest()
        return out

    def _read_json(self, name, value):
        if (
            isinstance(self.freeze_verifier, LegacyAuthorityFreeze)
            and name in self.freeze_verifier.handles
        ):
            return json.loads(self.freeze_verifier._read_bytes(name).decode())
        return json.loads(Path(value).read_text())

    def _identities(self, legacy, hashes):
        out = {}
        for name, value in legacy.items():
            p = Path(value)
            st = p.stat()
            out[name] = {
                "path": str(p.resolve()),
                "dev": st.st_dev,
                "ino": st.st_ino,
                "size": st.st_size,
                "mtime_ns": st.st_mtime_ns,
                "sha256": hashes[name],
            }
        return out

    def _verify_no_writer(self, attestation, trust_store, legacy, measured):
        if attestation is None or trust_store is None:
            raise ReaderBlocked("independent no-writer attestation required")
        if any(
            hmac.compare_digest(bytes(key), self.key)
            for key in trust_store.keys.values()
        ):
            raise ReaderBlocked("no-writer attester key must be independent")
        trust_store.verify(attestation)
        value = (
            attestation.to_dict()
            if isinstance(attestation, NoWriterAttestation)
            else dict(attestation)
        )
        if value.get("root") != str(self.root.resolve()):
            raise ReaderBlocked("no-writer root mismatch")
        if value.get("planned_hashes") != dict(measured):
            raise ReaderBlocked("no-writer hashes mismatch")
        if value.get("identities") != self._identities(legacy, measured):
            raise ReaderBlocked("no-writer identities mismatch")
        try:
            issued = datetime.fromisoformat(str(value["issued"]).replace("Z", "+00:00"))
            expires = datetime.fromisoformat(
                str(value["expires"]).replace("Z", "+00:00")
            )
        except Exception as exc:
            raise ReaderBlocked("invalid no-writer timestamp") from exc
        now = datetime.now(timezone.utc)
        if issued > now or expires <= now:
            raise ReaderBlocked("no-writer attestation expired")

    def _verify_freeze(self, freeze, legacy, measured):
        if (
            self.freeze_verifier is None
            or type(self.freeze_verifier) is not LegacyAuthorityFreeze
        ):
            raise ReaderBlocked("trusted freeze verifier required")
        if (
            not freeze.valid
            or not freeze.identity
            or not freeze.lock_id
            or not freeze.issued
            or not freeze.expires
        ):
            raise ReaderBlocked("freeze proof invalid")
        if (
            not freeze.held_token
            or not freeze.lock_provider
            or not freeze.lock_owner
            or not freeze.lock_held
        ):
            raise ReaderBlocked("lock is not held")
        try:
            self.freeze_verifier.verify(freeze)
            issued = datetime.fromisoformat(freeze.issued.replace("Z", "+00:00"))
            expires = datetime.fromisoformat(freeze.expires.replace("Z", "+00:00"))
        except Exception as exc:
            raise ReaderBlocked("invalid freeze timestamp") from exc
        if expires <= datetime.now(timezone.utc) or issued > datetime.now(timezone.utc):
            raise ReaderBlocked("freeze proof expired")
        if dict(freeze.planned_hashes) != dict(measured):
            raise ReaderBlocked("freeze hashes mismatch")
        expected_ids = self._identities(legacy, measured)
        if dict(freeze.identities) != expected_ids:
            raise ReaderBlocked("legacy identity drift")
        for name, fh in self.freeze_verifier.handles.items():
            st = os.fstat(fh.fileno())
            ident = freeze.identities.get(name, {})
            if not ident:
                raise ReaderBlocked("opened handle identity missing")
            if (
                st.st_dev != ident.get("dev")
                or st.st_ino != ident.get("ino")
                or st.st_size != ident.get("size")
                or st.st_mtime_ns != ident.get("mtime_ns")
            ):
                raise ReaderBlocked("opened handle identity drift")

    def _audit_rows(self):
        p = self.root / "authority_audit.jsonl"
        if not p.exists():
            return []
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x]
        prev = ""
        for row in rows:
            if row.get("previous_hash", "") != prev or row.get(
                "entry_hash"
            ) != canonical_hash({k: v for k, v in row.items() if k != "entry_hash"}):
                raise ReaderBlocked("audit hash chain tampered")
            prev = row["entry_hash"]
        return rows

    def _validate_prepared(self, binding, legacy):
        req = (
            "planned_old_hashes",
            "remeasured_old_hashes",
            "legacy_identities",
            "freeze_proof",
            "receipt_hash",
            "manifest_hash",
            "schema_ids",
            "policy_ids",
        )
        if (
            binding.get("expected_current_generation_id") != ABSENT
            or binding.get("business_state_delta") != 0
            or any(k not in binding for k in req)
        ):
            raise ReaderBlocked("incomplete prepared binding")
        measured = self._hash_legacy(legacy)
        if (
            measured != binding["remeasured_old_hashes"]
            or self._identities(legacy, measured) != binding["legacy_identities"]
        ):
            raise ReaderBlocked("legacy drift after prepared")
        self._verify_freeze(FreezeProof(**binding["freeze_proof"]), legacy, measured)
        gid = binding.get("generation_id")
        d = self.root / "generations" / str(gid)
        try:
            receipt = json.loads((d / "receipt.json").read_text())
            manifest = json.loads((d / "manifest.json").read_text())
        except Exception as exc:
            raise ReaderBlocked("generation proof missing") from exc
        if (
            not verify_receipt(receipt, self.key)
            or canonical_hash(receipt) != binding["receipt_hash"]
        ):
            raise ReaderBlocked("receipt proof invalid")
        if manifest.get("manifest_sha256") != binding[
            "manifest_hash"
        ] or canonical_hash(
            {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        ) != manifest.get("manifest_sha256"):
            raise ReaderBlocked("manifest proof invalid")

    @contextlib.contextmanager
    def _creator_lock(self):
        key = str(self.root.resolve())
        with _THREAD_LOCK_GUARD:
            thread_lock = _THREAD_LOCKS.setdefault(key, threading.Lock())
        thread_lock.acquire()
        try:
            path = self.root / ".genesis.creator.lock"
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            fh = os.fdopen(fd, "r+b", closefd=True)
        except BaseException:
            thread_lock.release()
            raise
        try:
            if os.name == "posix":
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            else:
                fh.seek(0)
                fh.write(b"0")
                fh.flush()
                fh.seek(0)
                while True:
                    try:
                        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.01)
                        fh.seek(0)
            yield
        finally:
            try:
                if os.name == "posix":
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                else:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                fh.close()
                thread_lock.release()

    def bootstrap(
        self,
        legacy: Mapping[str, str],
        *,
        expected_hashes: Mapping[str, str] | None = None,
        freeze: FreezeProof | None = None,
        schema_ids: Mapping[str, str] | None = None,
        policy_ids: Mapping[str, str] | None = None,
        crash_at: str | None = None,
        no_writer_attestation=None,
        trust_store: NoWriterTrustStore | None = None,
        authoritative: bool = True,
    ) -> dict[str, Any]:
        with self._creator_lock():
            if expected_hashes is None or freeze is None:
                raise ValueError("expected_hashes and verified freeze are required")
            if (self.root / "CURRENT").exists():
                self.builder.append_audit(
                    "GENESIS_ABORTED",
                    reason="CURRENT_EXISTS",
                    expected_current_generation_id=ABSENT,
                )
                raise ReaderBlocked("CURRENT must be absent")
            measured = self._hash_legacy(legacy)
            if dict(expected_hashes) != measured:
                raise ReaderBlocked("legacy drift")
            self._verify_freeze(freeze, legacy, measured)
            if (
                authoritative
                or no_writer_attestation is not None
                or trust_store is not None
            ):
                self._verify_no_writer(
                    no_writer_attestation, trust_store, legacy, measured
                )
            rows = self._audit_rows()
            prepared_row = next(
                (r for r in reversed(rows) if r.get("status") == "GENESIS_PREPARED"),
                None,
            )
            if prepared_row:
                self._validate_prepared(prepared_row["binding"], legacy)
                gid = prepared_row["binding"]["generation_id"]
                if not self.builder.create_current_absent(gid):
                    self.builder.append_audit(
                        "GENESIS_ABORTED", generation_id=gid, reason="CAS_LOSER"
                    )
                    raise ReaderBlocked("CURRENT create lost")
                self.builder.append_audit(
                    "GENESIS_COMMITTED",
                    operation_id=gid,
                    generation_id=gid,
                    receipt_hash=prepared_row["binding"]["receipt_hash"],
                    manifest_hash=prepared_row["binding"]["manifest_hash"],
                    business_state_delta=0,
                    recovery=True,
                )
                return GenerationReader(
                    self.root, signing_key=self.key, authoritative=authoritative
                ).read()
            legacy_payload = {k: self._read_json(k, v) for k, v in legacy.items()}
            checklist = legacy_payload.get("checklist", legacy_payload.get("gate", {}))
            runtime_authority = {
                "schema_id": "runtime-authority.v2",
                "genesis": True,
                "legacy_hashes": dict(measured),
                "legacy_identities": self._identities(legacy, measured),
                "business_state_delta": 0,
            }
            checklist_authority = {
                "schema_id": "checklist-authority.v2",
                "genesis": True,
                "checklist": checklist,
                "checklist_hash": canonical_hash(checklist),
                "business_state_delta": 0,
            }
            payload = {
                "runtime_authority.json": runtime_authority,
                "checklist_authority.json": checklist_authority,
                "genesis_metadata.json": {
                    "legacy": legacy_payload,
                    "freeze_proof": freeze.to_dict(),
                    "no_writer_attestation": (
                        no_writer_attestation.to_dict()
                        if isinstance(no_writer_attestation, NoWriterAttestation)
                        else no_writer_attestation
                    ),
                    "transformation": "zero-business-change",
                },
            }
            # Genesis publishes two explicit v2 authority partitions.  The
            # externally verified legacy freeze remains mandatory above; these
            # identifiers make the resulting authority chain unambiguous.
            schema_ids = dict(schema_ids or {})
            schema_ids.setdefault("runtime_authority", "runtime-authority.v2")
            schema_ids.setdefault("checklist_authority", "checklist-authority.v2")
            staged = self.builder.build(
                payload, schema_ids=schema_ids, policy_ids=policy_ids
            )
            gid = staged["generation_id"]
            self.builder.append_audit(
                "GENESIS_PREPARED",
                operation_id=gid,
                generation_id=gid,
                expected_current_generation_id=ABSENT,
                planned_old_hashes=dict(freeze.planned_hashes),
                remeasured_old_hashes=measured,
                legacy_identities=self._identities(legacy, measured),
                freeze_proof=freeze.to_dict(),
                receipt_hash=canonical_hash(staged["receipt"]),
                manifest_hash=staged["manifest"]["manifest_sha256"],
                schema_ids=dict(schema_ids or {}),
                policy_ids=dict(policy_ids or {}),
                business_state_delta=0,
            )
            if crash_at == "prepared":
                raise RuntimeError("simulated crash after GENESIS_PREPARED")
            if self._hash_legacy(legacy) != measured:
                self.builder.append_audit(
                    "GENESIS_ABORTED", generation_id=gid, reason="LEGACY_DRIFT"
                )
                raise ReaderBlocked("legacy drift after prepared")
            if crash_at == "before_create":
                raise RuntimeError("simulated crash before CURRENT create")
            final_hashes = self._hash_legacy(legacy)
            final_ids = self._identities(legacy, final_hashes)
            if final_hashes != measured or final_ids != freeze.identities:
                self.builder.append_audit(
                    "GENESIS_ABORTED",
                    generation_id=gid,
                    reason="LEGACY_IDENTITY_DRIFT_FINAL",
                )
                raise ReaderBlocked("legacy identity drift before create")
            if not self.builder.create_current_absent(gid):
                self.builder.append_audit(
                    "GENESIS_ABORTED", generation_id=gid, reason="CAS_LOSER"
                )
                raise ReaderBlocked("CURRENT create lost")
            if crash_at == "after_create":
                raise RuntimeError("simulated crash before GENESIS_COMMITTED")
            self.builder.append_audit(
                "GENESIS_COMMITTED",
                operation_id=gid,
                generation_id=gid,
                receipt_hash=canonical_hash(staged["receipt"]),
                manifest_hash=staged["manifest"]["manifest_sha256"],
                business_state_delta=0,
            )
            return GenerationReader(
                self.root, signing_key=self.key, authoritative=authoritative
            ).read()

    def bootstrap_legacy(self, legacy: Mapping[str, str], **kwargs) -> dict[str, Any]:
        """Development-only compatibility path; never authoritative evidence."""
        kwargs["authoritative"] = False
        return self.bootstrap(legacy, **kwargs)

    def recover_commit(
        self,
        generation_id: str,
        legacy: Mapping[str, str] | None = None,
        *,
        no_writer_attestation=None,
        trust_store: NoWriterTrustStore | None = None,
        authoritative: bool = False,
    ) -> dict[str, Any]:
        if legacy is None:
            raise ReaderBlocked(
                "blind recovery forbidden; provide audited prepared operation"
            )
        rows = self._audit_rows()
        prepared = next(
            (
                r
                for r in reversed(rows)
                if r.get("status") == "GENESIS_PREPARED"
                and r.get("binding", {}).get("generation_id") == generation_id
            ),
            None,
        )
        if prepared is None:
            raise ReaderBlocked("no audited prepared operation")
        self._validate_prepared(prepared["binding"], legacy)
        generation_dir = self.root / "generations" / str(generation_id)
        required = {
            "runtime_authority.json",
            "checklist_authority.json",
            "genesis_metadata.json",
        }
        try:
            manifest = json.loads((generation_dir / "manifest.json").read_text())
        except (OSError, ValueError) as exc:
            raise ReaderBlocked("generation proof missing") from exc
        recorded_attestation = None
        if required.issubset(set(manifest.get("files", {}))):
            try:
                metadata = json.loads(
                    (generation_dir / "genesis_metadata.json").read_text(
                        encoding="utf-8"
                    )
                )
                recorded_attestation = metadata.get("no_writer_attestation")
            except (OSError, TypeError, ValueError) as exc:
                raise ReaderBlocked("generation metadata invalid") from exc
        # Legacy metadata records ``None`` for the attestation. Such
        # generations remain development-only even when v2 files are present.
        is_authoritative = authoritative or recorded_attestation is not None
        if is_authoritative:
            if recorded_attestation is None:
                raise ReaderBlocked("authoritative no-writer proof missing")
            if no_writer_attestation is None:
                no_writer_attestation = recorded_attestation
            elif dict(no_writer_attestation) != dict(recorded_attestation):
                raise ReaderBlocked("no-writer attestation binding mismatch")
            measured = self._hash_legacy(legacy)
            self._verify_no_writer(no_writer_attestation, trust_store, legacy, measured)
        current = self.root / "CURRENT"
        if current.exists() and current.read_text().strip() != generation_id:
            self.builder.append_audit(
                "GENESIS_ABORTED",
                generation_id=generation_id,
                reason="CURRENT_MISMATCH",
            )
            raise ReaderBlocked("CURRENT mismatch")
        terminal = next(
            (
                r
                for r in reversed(rows)
                if r.get("status") == "GENESIS_COMMITTED"
                and r.get("binding", {}).get("generation_id") == generation_id
            ),
            None,
        )
        if terminal is not None:
            if not current.exists():
                raise ReaderBlocked("terminal audit missing CURRENT")
            return GenerationReader(
                self.root, signing_key=self.key, authoritative=is_authoritative
            ).read()
        if not current.exists() and not self.builder.create_current_absent(
            generation_id
        ):
            raise ReaderBlocked("CURRENT create lost")
        self.builder.append_audit(
            "GENESIS_COMMITTED",
            operation_id=generation_id,
            generation_id=generation_id,
            receipt_hash=prepared["binding"]["receipt_hash"],
            manifest_hash=prepared["binding"]["manifest_hash"],
            business_state_delta=0,
            recovery=True,
        )
        return GenerationReader(
            self.root, signing_key=self.key, authoritative=is_authoritative
        ).read()
