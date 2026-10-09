from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import uuid
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from jsonschema import Draft202012Validator

from rfb.contracts.canonical_json import canonical_bytes, sha256_hex

ABSENT = "ABSENT"
TERMINAL = {"GENESIS_COMMITTED", "COMMITTED"}


class ReaderBlocked(RuntimeError):
    pass


def _validate_generation_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 32
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ReaderBlocked("invalid generation_id")
    return value


def canonical_hash(value: Any) -> str:
    return sha256_hex(canonical_bytes(value))


def sign_receipt(body: Mapping[str, Any], key: bytes) -> str:
    return hmac.new(key, canonical_bytes(body), hashlib.sha256).hexdigest()


def verify_receipt(receipt: Mapping[str, Any], key: bytes) -> bool:
    sig = receipt.get("signature")
    body = {k: v for k, v in receipt.items() if k != "signature"}
    return isinstance(sig, str) and hmac.compare_digest(sig, sign_receipt(body, key))


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical_bytes(value))
    _fsync(path)


def _fsync(path: Path) -> None:
    with path.open("r+b") as fh:
        os.fsync(fh.fileno())


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise RuntimeError("directory fsync unavailable") from exc


def _relative_name(name: str) -> str:
    rel = str(name).replace(chr(92), "/")
    p = PurePosixPath(rel)
    w = PureWindowsPath(rel)
    if not rel or p.is_absolute() or w.is_absolute() or w.drive or ".." in p.parts:
        raise ValueError("authority path must be relative and root-confined")
    return "/".join(p.parts)


def _validate(schema_name: str, value: Any) -> None:
    schema = json.loads(
        (
            Path(__file__).parents[1] / "contracts" / f"{schema_name}.schema.json"
        ).read_text(encoding="utf-8")
    )
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        raise ValueError(f"{schema_name} schema invalid: {errors[0].message}")


def _safe_tree(root: Path, *, writable=False) -> None:
    root = Path(root)
    if not root.is_absolute():
        raise ReaderBlocked("generation root must be absolute")
    cur, ancestors = root, []
    while True:
        ancestors.append(cur)
        if cur.parent == cur:
            break
        cur = cur.parent
    for item in reversed(ancestors):
        try:
            st = item.lstat()
        except OSError as exc:
            raise ReaderBlocked("generation path missing") from exc
        if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & 0x400:
            raise ReaderBlocked("symlink/reparse in generation path")
    real = root.resolve(strict=True)
    for item in [root, *root.rglob("*")]:
        st = item.lstat()
        if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & 0x400:
            raise ReaderBlocked("symlink/reparse in generation")
        try:
            if not item.resolve(strict=True).is_relative_to(real):
                raise ReaderBlocked("generation path escape")
        except (OSError, RuntimeError) as exc:
            raise ReaderBlocked("generation path escape") from exc
        if writable:
            # Windows read-only is carried in FILE_ATTRIBUTE_READONLY rather
            # than POSIX mode bits (which remain writable on mounted drives).
            if os.name == "nt":
                if item.is_file() and not (getattr(st, "st_file_attributes", 0) & 0x01):
                    raise ReaderBlocked("generation writable")
            elif st.st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
                raise ReaderBlocked("generation writable")


def _validate_root_for_write(root: Path) -> None:
    if not root.is_absolute():
        raise ReaderBlocked("generation root must be absolute")
    cur = root
    while not cur.exists() and cur.parent != cur:
        cur = cur.parent
    _safe_tree(cur)
    if root.exists():
        _safe_tree(root)


class AuthorityGenerationBuilder:
    def __init__(
        self, root: str | Path, *, signing_key: bytes, durability_provider=None
    ):
        if not signing_key:
            raise ValueError("signing_key is required")
        self.root = Path(root)
        _validate_root_for_write(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        _validate_root_for_write(self.root)
        self.key = signing_key
        self.durability_provider = durability_provider
        self.generations = self.root / "generations"
        _validate_root_for_write(self.generations)
        self.generations.mkdir(exist_ok=True)
        _validate_root_for_write(self.generations)
        self.audit_path = self.root / "authority_audit.jsonl"

    def _durable_file(self, p):
        (
            self.durability_provider.fsync_file(p)
            if self.durability_provider
            else _fsync(p)
        )

    def _durable_dir(self, p):
        (
            self.durability_provider.fsync_dir(p)
            if self.durability_provider
            else _fsync_dir(p)
        )

    def _audit(self, status, **binding):
        prev = ""
        if self.audit_path.exists():
            lines = self.audit_path.read_text(encoding="utf-8").splitlines()
            prev = json.loads(lines[-1]).get("entry_hash", "") if lines else ""
        row = {
            "status": status,
            "event_id": uuid.uuid4().hex,
            "binding": binding,
            "previous_hash": prev,
        }
        row["entry_hash"] = canonical_hash(row)
        with self.audit_path.open("ab") as fh:
            fh.write(canonical_bytes(row) + b"\n")
            fh.flush()
            os.fsync(fh.fileno())
        return row

    def build(
        self,
        authorities: Mapping[str, Any],
        *,
        schema_ids=None,
        policy_ids=None,
        parent_generation=ABSENT,
        operation_id=None,
        business_state_delta=None,
        checklist_hash=None,
    ):
        _validate_root_for_write(self.root)
        if parent_generation != ABSENT and not parent_generation:
            raise ValueError("invalid parent generation")
        if parent_generation == ABSENT:
            if business_state_delta not in (None, 0):
                raise ValueError("genesis business_state_delta must be zero")
            business_state_delta = 0
        elif business_state_delta is None:
            raise ValueError("runtime business_state_delta must be explicit")
        elif (
            not isinstance(business_state_delta, int)
            or isinstance(business_state_delta, bool)
            or business_state_delta < 0
        ):
            raise ValueError("invalid business_state_delta")
        if checklist_hash is None:
            checklist_value = authorities.get("checklist", authorities.get("gate"))
            if checklist_value is None and isinstance(
                authorities.get("checklist_authority.json"), Mapping
            ):
                checklist_value = authorities["checklist_authority.json"].get(
                    "checklist", {}
                )
            checklist_hash = canonical_hash(checklist_value or {})
        if not isinstance(checklist_hash, str) or len(checklist_hash) != 64:
            raise ValueError("checklist_hash is required")
        gid = uuid.uuid4().hex
        d = self.generations / gid
        d.mkdir()
        files = {}
        for name, content in authorities.items():
            rel = _relative_name(name)
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            _safe_tree(d)
            _write_json(p, content)
            files[rel] = {
                "sha256": sha256_hex(p.read_bytes()),
                "bytes": p.stat().st_size,
            }
        manifest = {
            "generation_id": gid,
            "parent_generation": parent_generation,
            "files": files,
            "schema_ids": dict(schema_ids or {}),
            "policy_ids": dict(policy_ids or {}),
        }
        manifest["manifest_sha256"] = canonical_hash(manifest)
        _write_json(d / "manifest.json", manifest)
        files_with_manifest = {
            **files,
            "manifest.json": {
                "sha256": sha256_hex((d / "manifest.json").read_bytes()),
                "bytes": (d / "manifest.json").stat().st_size,
            },
        }
        body = {
            "generation_id": gid,
            "parent_generation": parent_generation,
            "manifest_sha256": manifest["manifest_sha256"],
            "files": files_with_manifest,
            "checklist_hash": checklist_hash,
            "schema_ids": dict(schema_ids or {}),
            "policy_ids": dict(policy_ids or {}),
            "status": "COMMITTED",
            "business_state_delta": business_state_delta,
        }
        receipt = {**body, "signature": sign_receipt(body, self.key)}
        _validate("authority_generation", manifest)
        _validate("authority_receipt", receipt)
        _write_json(d / "receipt.json", receipt)
        for p in d.rglob("*"):
            if p.is_file():
                self._durable_file(p)
        self._durable_dir(d)
        # Seal the generation root itself as well as every descendant before
        # self-verification; leaving the root writable permits replacement files.
        d.chmod(
            stat.S_IRUSR
            | stat.S_IRGRP
            | stat.S_IROTH
            | stat.S_IXUSR
            | stat.S_IXGRP
            | stat.S_IXOTH
        )
        for p in d.rglob("*"):
            p.chmod(
                (stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
                if p.is_file()
                else (
                    stat.S_IRUSR
                    | stat.S_IRGRP
                    | stat.S_IROTH
                    | stat.S_IXUSR
                    | stat.S_IXGRP
                    | stat.S_IXOTH
                )
            )
        GenerationReader(
            self.root, signing_key=self.key, authoritative=False
        ).verify_generation(gid, require_audit=False)
        return {
            "generation_id": gid,
            "directory": str(d),
            "manifest": manifest,
            "receipt": receipt,
        }

    def build_successor(
        self,
        predecessor_generation: str,
        authorities: Mapping[str, Any] | None = None,
        *,
        checklist_replacement: Any = None,
        operation_id=None,
        schema_ids=None,
        policy_ids=None,
        business_state_delta=None,
    ):
        """Build a complete successor by hash-verifying and copying predecessor authority objects."""
        predecessor_generation = _validate_generation_id(predecessor_generation)
        reader = GenerationReader(self.root, signing_key=self.key)
        prior = reader.verify_generation(predecessor_generation, require_audit=True)
        pd = self.generations / predecessor_generation
        merged = {}
        inherited_schema_ids = dict(prior["manifest"].get("schema_ids", {}))
        inherited_policy_ids = dict(prior["manifest"].get("policy_ids", {}))
        for name, info in prior["manifest"]["files"].items():
            if name in ("manifest.json", "receipt.json") or name == "checklist.json":
                continue
            raw = (pd / name).read_bytes()
            if sha256_hex(raw) != info["sha256"]:
                raise ReaderBlocked("predecessor authority hash mismatch")
            merged[name] = json.loads(raw.decode("utf-8"))
        if authorities:
            if (
                "authority.json" in authorities
                and authorities["authority.json"] == prior["manifest"]
            ):
                raise ValueError("manifest cannot masquerade as authority.json")
            merged.update(authorities)
        if checklist_replacement is not None:
            merged["checklist.json"] = checklist_replacement
            authority = merged.get("checklist_authority.json")
            if not isinstance(authority, Mapping):
                raise ReaderBlocked("checklist authority missing")
            authority = dict(authority)
            authority["checklist"] = checklist_replacement
            authority["checklist_hash"] = canonical_hash(checklist_replacement)
            merged["checklist_authority.json"] = authority
        if "checklist.json" not in merged:
            raise ValueError("successor checklist is required")
        if schema_ids is None:
            schema_ids = inherited_schema_ids
        if policy_ids is None:
            policy_ids = inherited_policy_ids
        if (
            business_state_delta is None
            or isinstance(business_state_delta, bool)
            or not isinstance(business_state_delta, int)
            or business_state_delta < 0
        ):
            raise ValueError("successor business_state_delta must be explicit")
        return self.build(
            merged,
            parent_generation=predecessor_generation,
            operation_id=operation_id,
            schema_ids=schema_ids,
            policy_ids=policy_ids,
            business_state_delta=business_state_delta,
            checklist_hash=canonical_hash(merged["checklist.json"]),
        )

    def create_current_absent(self, gid):
        try:
            fd = os.open(self.root / "CURRENT", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "wb") as fh:
                fh.write(gid.encode())
                fh.flush()
                os.fsync(fh.fileno())
            self._durable_dir(self.root)
            return True
        except FileExistsError:
            return False

    def append_audit(self, status, **binding):
        return self._audit(status, **binding)


class GenerationReader:
    def __init__(
        self, root: str | Path, *, signing_key: bytes, authoritative: bool = True
    ):
        self.root = Path(root)
        self.key = signing_key
        self.authoritative = authoritative

    def current_id(self):
        p = self.root / "CURRENT"
        if not p.is_file() or p.is_symlink():
            raise ReaderBlocked("CURRENT absent")
        v = p.read_text().strip()
        if len(v) != 32 or any(c not in "0123456789abcdef" for c in v):
            raise ReaderBlocked("invalid CURRENT")
        return v

    def verify_generation(self, gid, runtime=False, require_audit=True):
        gid = _validate_generation_id(gid)
        d = self.root / "generations" / gid
        if not d.is_dir():
            raise ReaderBlocked("generation missing")
        _safe_tree(d, writable=True)
        try:
            rec = json.loads((d / "receipt.json").read_text())
            man = json.loads((d / "manifest.json").read_text())
        except Exception as exc:
            raise ReaderBlocked("generation metadata invalid") from exc
        try:
            _validate("authority_generation", man)
            _validate("authority_receipt", rec)
        except ValueError as exc:
            raise ReaderBlocked(str(exc)) from exc
        if rec.get("generation_id") != gid or not verify_receipt(rec, self.key):
            raise ReaderBlocked("receipt invalid")
        if rec.get("status") not in ({"COMMITTED"} if runtime else TERMINAL):
            raise ReaderBlocked("receipt not terminal")
        if man.get("manifest_sha256") != canonical_hash(
            {k: v for k, v in man.items() if k != "manifest_sha256"}
        ):
            raise ReaderBlocked("manifest hash mismatch")
        expected = set(man.get("files", {})) | {"manifest.json", "receipt.json"}
        actual = {p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()}
        if actual != expected or set(rec.get("files", {})) != (
            set(man.get("files", {})) | {"manifest.json"}
        ):
            raise ReaderBlocked("file set mismatch")
        if rec.get("manifest_sha256") != man.get("manifest_sha256"):
            raise ReaderBlocked("manifest binding mismatch")
        if self.authoritative:
            required = {
                "runtime_authority.json",
                "checklist_authority.json",
                "genesis_metadata.json",
            }
            if not required.issubset(set(man.get("files", {}))):
                raise ReaderBlocked("authoritative authority objects missing")
            schemas = man.get("schema_ids", {})
            if (
                schemas.get("runtime_authority") != "runtime-authority.v2"
                or schemas.get("checklist_authority") != "checklist-authority.v2"
            ):
                raise ReaderBlocked("authoritative schema bindings missing")
        for rel, info in rec["files"].items():
            p = d / rel
            if sha256_hex(p.read_bytes()) != info.get(
                "sha256"
            ) or p.stat().st_size != info.get("bytes"):
                raise ReaderBlocked("file hash mismatch")
        if self.authoritative:
            try:
                authority = json.loads(
                    (d / "checklist_authority.json").read_text(encoding="utf-8")
                )
                checklist_path = d / "checklist.json"
                checklist = (
                    json.loads(checklist_path.read_text(encoding="utf-8"))
                    if checklist_path.exists()
                    else authority.get("checklist")
                )
            except (OSError, ValueError) as exc:
                raise ReaderBlocked("checklist authority invalid") from exc
            if authority.get("checklist") != checklist or authority.get(
                "checklist_hash"
            ) != canonical_hash(checklist):
                raise ReaderBlocked("checklist authority binding mismatch")
            if rec.get("checklist_hash") != canonical_hash(checklist):
                raise ReaderBlocked("receipt checklist binding mismatch")
        rows = []
        ap = self.root / "authority_audit.jsonl"
        if ap.exists():
            prev = ""
            for line in ap.read_text(encoding="utf-8").splitlines():
                if not line:
                    continue
                row = json.loads(line)
                if row.get("previous_hash", "") != prev or row.get(
                    "entry_hash"
                ) != canonical_hash(
                    {k: v for k, v in row.items() if k != "entry_hash"}
                ):
                    raise ReaderBlocked("audit hash chain tampered")
                rows.append(row)
                prev = row["entry_hash"]
        prepared = [
            r
            for r in rows
            if r.get("status") in ("GENESIS_PREPARED", "BROKER_PREPARED")
            and r.get("binding", {}).get("generation_id") == gid
        ]
        terminals = [
            r
            for r in rows
            if r.get("status") in ("GENESIS_COMMITTED", "BROKER_COMMITTED")
            and r.get("binding", {}).get("generation_id") == gid
        ]
        if require_audit:
            if not prepared or not terminals:
                raise ReaderBlocked("prepared/terminal audit missing")
            prep = prepared[-1]
            terminal = terminals[-1]
            pb, tb = prep.get("binding", {}), terminal.get("binding", {})
            if (
                prep.get("status") == "GENESIS_PREPARED"
                and terminal.get("status") != "GENESIS_COMMITTED"
            ):
                raise ReaderBlocked("audit operation mismatch")
            if (
                prep.get("status") == "BROKER_PREPARED"
                and terminal.get("status") != "BROKER_COMMITTED"
            ):
                raise ReaderBlocked("audit operation mismatch")
            if not pb.get("operation_id") or tb.get("operation_id") != pb.get(
                "operation_id"
            ):
                raise ReaderBlocked("audit operation mismatch")
            for k in (
                "request_id",
                "generation_id",
                "receipt_hash",
                "manifest_hash",
                "business_state_delta",
            ):
                if k in pb and tb.get(k) != pb.get(k):
                    raise ReaderBlocked("audit binding mismatch")
            if pb.get("receipt_hash") not in (
                canonical_hash(rec),
                sha256_hex((d / "receipt.json").read_bytes()),
            ):
                raise ReaderBlocked("prepared receipt binding mismatch")
            if tb.get("receipt_hash") != pb.get("receipt_hash"):
                raise ReaderBlocked("terminal receipt binding mismatch")
            if tb.get("manifest_hash") and tb.get("manifest_hash") != man.get(
                "manifest_sha256"
            ):
                raise ReaderBlocked("terminal manifest binding mismatch")
        else:
            terminal = {"status": "COMMITTED"}
        return {
            "generation_id": gid,
            "manifest": man,
            "receipt": rec,
            "audit_status": terminal["status"],
        }

    def read(self, *, runtime=False):
        return self.verify_generation(self.current_id(), runtime=runtime)
