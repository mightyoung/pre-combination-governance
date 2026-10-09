"""Fail-closed, manifest-bound purge helpers for v6.13 segment closeout.

The destructive path unlinks only explicitly frozen regular files. It never
performs recursive deletion and defaults to a dry run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .capacity_probe import ProbeUnavailable, filesystem_used_bytes, open_deleted_bytes
from .contracts.canonical_json import canonical_bytes, sha256_hex

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_KINDS = {"EPHEMERAL_DATASET", "TRANSIENT_RUNTIME"}
_RESERVED = re.compile(r"(?:durable|ledger|tombstone|archive|result)", re.I)
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_PLAN_VERSION = "dataset-purge-plan.v3"
_MANIFEST_VERSION = "dataset-purge-manifest.v2"
_AUTH_VERSION = "dataset-purge-authorization.v4"
_LEDGER_VERSION = 2


def _persistable_projection(value: Any) -> Any:
    """Return the JSON-safe representation used by persisted purge records.

    Strict regeneration constructors retain ``canonical_bytes`` in memory so
    their validators can reconstruct and verify the corresponding hashes.  It
    is deliberately not a persisted field.  Only that explicitly non-persisted
    field is removed here; any other bytes value is rejected rather than being
    silently coerced or dropped.
    """

    if isinstance(value, Mapping):
        projected: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("persisted purge record mapping keys must be strings")
            if key == "canonical_bytes":
                if not isinstance(child, bytes):
                    raise ValueError("canonical_bytes must be an in-memory bytes value")
                continue
            projected[key] = _persistable_projection(child)
        return projected
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_persistable_projection(child) for child in value]
    if isinstance(value, (bytes, bytearray)):
        raise ValueError(
            "only canonical_bytes may be omitted from persisted purge records"
        )
    return value


def _rehydrate_strict_regeneration_plan(
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Restore the non-persisted canonical bytes of a strict plan safely.

    Persisted purge evidence retains the complete plan body and its original
    ``plan_hash`` but deliberately omits the in-memory ``canonical_bytes``
    helper.  Rebuild those bytes only after verifying that the persisted body
    still hashes to the already frozen commitment.
    """

    if not isinstance(plan, Mapping):
        raise ValueError("strict regeneration plan must be an object")
    if "canonical_bytes" in plan:
        raw = plan.get("canonical_bytes")
        if not isinstance(raw, bytes):
            raise ValueError("strict regeneration canonical bytes are invalid")
        return dict(plan)
    body = {key: plan[key] for key in plan if key not in {"plan_hash", "freeze_event"}}
    raw = canonical_bytes(body)
    if not _HEX64.fullmatch(str(plan.get("plan_hash", ""))) or sha256_hex(
        raw
    ) != plan.get("plan_hash"):
        raise ValueError("persisted strict regeneration plan hash mismatch")
    return {**dict(plan), "canonical_bytes": raw}


def _is_reparse(path: Path, metadata: os.stat_result | None = None) -> bool:
    try:
        details = metadata or path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(
        getattr(details, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _assert_no_reparse_components(path: Path, *, label: str) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path)))
    if not absolute.is_absolute() or absolute == Path(absolute.anchor):
        raise ValueError(f"{label} must be a non-root absolute path")
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        if _is_reparse(current, metadata):
            raise ValueError(
                f"{label} contains symlink/junction/reparse point: {current}"
            )
    return absolute


def _safe_relative(value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError(f"unsafe purge path: {value!r}")
    relative = Path(value)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError(f"unsafe purge path: {value!r}")
    if any(_RESERVED.search(part) for part in relative.parts):
        raise ValueError(f"reserved purge path: {value!r}")
    return relative


def _file_snapshot(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"purge path missing: {path}") from exc
    if _is_reparse(path, metadata) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"purge target is not a real regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "dev": int(metadata.st_dev),
        "ino": int(metadata.st_ino),
        "size": int(metadata.st_size),
        "allocated_bytes": int(
            getattr(metadata, "st_blocks", (metadata.st_size + 511) // 512)
        )
        * 512,
        "sha256": digest.hexdigest(),
    }


def _validated_root(root: str | os.PathLike[str]) -> tuple[Path, os.stat_result]:
    root_path = _assert_no_reparse_components(Path(root), label="purge root")
    try:
        metadata = root_path.lstat()
    except FileNotFoundError as exc:
        raise ValueError("purge root is missing") from exc
    if _is_reparse(root_path, metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("purge root must be a real directory")
    return root_path, metadata


def _target(root: Path, relative: Path) -> Path:
    target = root.joinpath(relative)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("purge target escapes root") from exc
    current = root
    for component in relative.parts[:-1]:
        current /= component
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise ValueError(f"purge ancestor missing: {current}") from exc
        if _is_reparse(current, metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"purge ancestor is not a real directory: {current}")
    return target


def freeze_purge_manifest(
    root: str | os.PathLike[str],
    entries: Sequence[Mapping[str, Any]],
    *,
    segment_id: str,
) -> dict[str, Any]:
    """Freeze the exact allowlist and observed identities before authorization."""

    if not isinstance(segment_id, str) or not segment_id.strip():
        raise ValueError("segment_id must be a non-empty string")
    root_path, root_metadata = _validated_root(root)
    if not isinstance(entries, Sequence) or isinstance(
        entries, (str, bytes, bytearray)
    ):
        raise ValueError("manifest entries must be a sequence")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, Mapping) or set(item) - {"path", "kind", "sha256"}:
            raise ValueError("manifest entry has unknown fields")
        kind = item.get("kind")
        if kind not in _ALLOWED_KINDS:
            raise ValueError("manifest contains non-ephemeral object")
        relative = _safe_relative(item.get("path"))
        collision_key = relative.as_posix().casefold()
        if collision_key in seen:
            raise ValueError("duplicate or case-colliding purge path")
        seen.add(collision_key)
        snapshot = _file_snapshot(_target(root_path, relative))
        declared_hash = item.get("sha256")
        if declared_hash is not None and declared_hash != snapshot["sha256"]:
            raise ValueError(f"manifest hash mismatch for {relative.as_posix()}")
        normalized.append(
            {
                "path": relative.as_posix(),
                "kind": kind,
                "lstat": snapshot,
            }
        )
    if not normalized:
        raise ValueError("purge manifest cannot be empty")
    normalized.sort(key=lambda item: item["path"].casefold())
    body: dict[str, Any] = {
        "schema_version": _MANIFEST_VERSION,
        "segment_id": segment_id,
        "root": str(root_path),
        "root_lstat": {
            "dev": int(root_metadata.st_dev),
            "ino": int(root_metadata.st_ino),
        },
        "filesystem_used_bytes_before": filesystem_used_bytes(root_path),
        "entries": normalized,
    }
    return {**body, "manifest_hash": sha256_hex(canonical_bytes(body))}


def _validated_manifest(
    root: Path, manifest: Mapping[str, Any], manifest_hash: str | None
) -> dict[str, Any]:
    if not isinstance(manifest, Mapping):
        raise ValueError("purge manifest must be a frozen manifest object")
    supplied = manifest.get("manifest_hash")
    if not isinstance(supplied, str) or not _HEX64.fullmatch(supplied):
        raise ValueError("manifest_hash must be a lowercase SHA-256 digest")
    if manifest_hash is not None and manifest_hash != supplied:
        raise ValueError("requested manifest hash differs from frozen manifest")
    body = {key: manifest[key] for key in manifest if key != "manifest_hash"}
    if sha256_hex(canonical_bytes(body)) != supplied:
        raise ValueError("frozen manifest hash is invalid")
    if body.get("schema_version") != _MANIFEST_VERSION or body.get("root") != str(root):
        raise ValueError("frozen manifest root/version mismatch")
    return dict(manifest)


def build_purge_plan(
    root: str | os.PathLike[str],
    manifest: Mapping[str, Any],
    manifest_hash: str | None = None,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Build a manifest-bound dry-run purge plan."""

    root_path, root_metadata = _validated_root(root)
    frozen = _validated_manifest(root_path, manifest, manifest_hash)
    expected_root = frozen["root_lstat"]
    if (int(root_metadata.st_dev), int(root_metadata.st_ino)) != (
        expected_root["dev"],
        expected_root["ino"],
    ):
        raise ValueError("purge root identity changed after manifest freeze")
    entries: list[dict[str, Any]] = []
    for item in frozen["entries"]:
        relative = _safe_relative(item["path"])
        if item.get("kind") not in _ALLOWED_KINDS:
            raise ValueError("frozen manifest kind is not purgeable")
        current = _file_snapshot(_target(root_path, relative))
        if current != item.get("lstat"):
            raise ValueError(f"purge target changed after manifest freeze: {relative}")
        entries.append(dict(item))
    body: dict[str, Any] = {
        "schema_version": _PLAN_VERSION,
        "segment_id": frozen["segment_id"],
        "root": str(root_path),
        "root_lstat": dict(frozen["root_lstat"]),
        "dry_run": bool(dry_run),
        "manifest_hash": frozen["manifest_hash"],
        "filesystem_used_bytes_before": frozen["filesystem_used_bytes_before"],
        "entries": entries,
    }
    return {**body, "plan_hash": sha256_hex(canonical_bytes(body))}


def _validated_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, Mapping):
        raise ValueError("purge plan must be an object")
    body = {key: plan[key] for key in plan if key != "plan_hash"}
    if plan.get("plan_hash") != sha256_hex(canonical_bytes(body)):
        raise ValueError("purge plan hash mismatch")
    if body.get("schema_version") != _PLAN_VERSION:
        raise ValueError("unsupported purge plan version")
    if not _HEX64.fullmatch(str(body.get("manifest_hash", ""))):
        raise ValueError("purge plan manifest hash is invalid")
    root, metadata = _validated_root(body.get("root"))
    expected_root = body.get("root_lstat", {})
    if (int(metadata.st_dev), int(metadata.st_ino)) != (
        expected_root.get("dev"),
        expected_root.get("ino"),
    ):
        raise ValueError("purge root identity changed")
    validated = dict(body)
    validated["root_path"] = root
    return validated


def _strict_regeneration_evidence(
    prerequisites: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    authority_root: str | os.PathLike[str],
    trust_store: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Validate and reconstruct the complete strict regeneration closeout.

    The persisted verdict is deliberately treated as an assertion only: the
    canonical verdict is rebuilt from the frozen plan, expectations, and
    individually hashed sample reports and must compare byte-for-byte.
    """
    from .regeneration import (
        RuntimeCommitmentAuthority,
        execute_regeneration_plan_v3,
        finalize_regeneration_verdict_v2,
        verify_regeneration_attestation,
    )

    if not isinstance(evidence, Mapping):
        raise ValueError("full regeneration evidence is required")
    prerequisite_plan = prerequisites.get("regeneration_plan")
    evidence_plan = evidence.get("plan", evidence.get("regeneration_plan"))
    if prerequisite_plan is not None and evidence_plan is not None:
        if _persistable_projection(prerequisite_plan) != _persistable_projection(
            evidence_plan
        ):
            raise ValueError("regeneration plan evidence is not reconstructively equal")
    regeneration_plan = prerequisite_plan or evidence_plan
    expectations = evidence.get("expectations")
    reports = evidence.get("reports")
    persisted = prerequisites.get("regeneration_verdict") or evidence.get(
        "verdict", evidence.get("regeneration_verdict")
    )
    if (
        not all(isinstance(value, Mapping) for value in (regeneration_plan, persisted))
        or not isinstance(expectations, Sequence)
        or isinstance(expectations, (str, bytes, bytearray))
        or not isinstance(reports, Sequence)
        or isinstance(reports, (str, bytes, bytearray))
    ):
        raise ValueError(
            "strict regeneration plan, expectations, reports and verdict are required"
        )
    if regeneration_plan.get("schema_version") != "regeneration-plan.v3":
        raise ValueError("compatibility regeneration plan cannot authorize purge")
    runtime_plan = _rehydrate_strict_regeneration_plan(regeneration_plan)
    authority_data = regeneration_plan.get("runtime_authority")
    if not isinstance(authority_data, Mapping):
        raise ValueError("runtime authority is required by regeneration plan")
    generator_path = authority_data.get("generator_path")
    segment_config_path = authority_data.get("segment_config_path")
    if not isinstance(generator_path, str) or not isinstance(segment_config_path, str):
        raise ValueError("generator and segment-config commitments are required")
    loaded = RuntimeCommitmentAuthority.load(
        authority_root,
        generator_path=generator_path,
        segment_config_path=segment_config_path,
    )
    if loaded.to_dict() != dict(authority_data):
        raise ValueError("runtime authority does not match frozen regeneration plan")
    persisted_authority = evidence.get("runtime_authority")
    if not isinstance(persisted_authority, Mapping) or _persistable_projection(
        persisted_authority
    ) != _persistable_projection(authority_data):
        raise ValueError("persisted runtime authority does not match frozen plan")
    current_authority = evidence.get("current_authority")
    freeze_event = evidence.get("freeze_event")
    ledger_rows = evidence.get("execution_ledger_rows")
    current_bundle_ids = evidence.get("current_bundle_ids")
    if (
        not isinstance(current_authority, (Mapping, RuntimeCommitmentAuthority))
        or not isinstance(freeze_event, Mapping)
        or not isinstance(ledger_rows, Sequence)
        or isinstance(ledger_rows, (str, bytes, bytearray))
        or not isinstance(current_bundle_ids, Sequence)
        or isinstance(current_bundle_ids, (str, bytes, bytearray))
    ):
        raise ValueError(
            "strict current authority, freeze event, execution ledger and bundle evidence are required"
        )
    execute_regeneration_plan_v3(
        runtime_plan,
        authority_root=authority_root,
        current_authority=current_authority,
        freeze_event=freeze_event,
        execution_ledger_rows=ledger_rows,
        current_bundle_ids=current_bundle_ids,
        segment_id=regeneration_plan["segment_id"],
        sample_selection_seed=regeneration_plan["sample_selection_seed"],
    )
    rebuilt = finalize_regeneration_verdict_v2(
        runtime_plan, list(expectations), list(reports)
    )
    attestation = evidence.get("regeneration_attestation")
    if "regeneration_attestation_trust" in evidence:
        raise ValueError("attestation trust must not be embedded in evidence")
    attestation_trust = trust_store
    if not isinstance(attestation, Mapping) or not isinstance(
        attestation_trust, Mapping
    ):
        raise ValueError("independent regeneration attestation trust store is required")
    verify_regeneration_attestation(
        attestation,
        trust=attestation_trust,
        plan=runtime_plan,
        expectations=list(expectations),
        reports=list(reports),
        verdict=rebuilt,
        freeze_event=freeze_event,
        execution_ledger_rows=ledger_rows,
        independent_key_ids=trust_store.get(
            "independent_key_ids", {trust_store.get("key_id")}
        ),
    )
    if _persistable_projection(persisted) != _persistable_projection(rebuilt):
        raise ValueError("persisted regeneration verdict is not reconstructively equal")
    if (
        rebuilt.get("status") != "REGEN_CONSISTENT_UNATTESTED"
        or rebuilt.get("authoritative") is not False
        or rebuilt.get("regeneration_verified") is not True
    ):
        raise ValueError("regeneration verdict is not successful")
    if (
        rebuilt.get("next_segment_allowed") is not False
        or rebuilt.get("purge_authorized") is not False
    ):
        raise ValueError("successful regeneration verdict latch is invalid")
    # Persist every independently reconstructible input used by the strict
    # execution check.  Omitting these fields makes a create -> execute (or
    # closeout) round-trip impossible because later validation cannot rebuild
    # the same strict evidence from the authorization record alone.
    if isinstance(current_authority, RuntimeCommitmentAuthority):
        current_authority_data = current_authority.to_dict()
    elif isinstance(current_authority, Mapping):
        current_authority_data = dict(current_authority)
    else:
        raise ValueError("current runtime authority is not persistable")
    evidence_body = _persistable_projection(
        {
            "plan": regeneration_plan,
            "expectations": list(expectations),
            "reports": list(reports),
            "verdict": rebuilt,
            "runtime_authority": dict(authority_data),
            "current_authority": current_authority_data,
            "freeze_event": dict(freeze_event),
            "execution_ledger_rows": list(ledger_rows),
            "current_bundle_ids": list(current_bundle_ids),
            "regeneration_attestation": dict(attestation),
        }
    )
    return dict(regeneration_plan), evidence_body, rebuilt, loaded.to_dict()


def _authorization_body(
    prerequisites: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    authority_root: str | os.PathLike[str],
    regeneration_evidence: Mapping[str, Any],
    trust_store: Mapping[str, Any],
    development_capability: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(prerequisites, Mapping):
        raise ValueError("purge authorization prerequisites are required")
    required_true = (
        "result_sealed",
        "archive_a_verified",
        "archive_b_verified",
        "truth_isolation_verified",
    )
    if any(prerequisites.get(key) is not True for key in required_true):
        raise ValueError("purge authorization prerequisites are incomplete")
    if prerequisites.get("contains_raw_dataset") is not False:
        raise ValueError("durable result package raw-dataset flag is not false")
    if prerequisites.get("segment_state") != "REGEN_VERIFIED":
        raise ValueError("segment state is not REGEN_VERIFIED")
    digest_keys = (
        "state_signature",
        "result_manifest_hash",
        "archive_a_hash",
        "archive_b_hash",
        "dataset_approval_commitment",
        "stat_approval_commitment",
    )
    for key in digest_keys:
        if not _HEX64.fullmatch(str(prerequisites.get(key, ""))):
            raise ValueError(f"{key} is required")
    if prerequisites.get("manifest_hash") != plan.get("manifest_hash"):
        raise ValueError("authorization manifest does not match purge plan")
    truth_hash = prerequisites.get(
        "truth_isolation_hash", prerequisites.get("truth_isolation_qa_hash")
    )
    if not _HEX64.fullmatch(str(truth_hash or "")):
        raise ValueError("truth isolation commitment is required")
    if prerequisites.get("development_only") is not True:
        raise ValueError("purge authorization is development-only")
    if prerequisites.get("live_destructive_use_allowed", False) is not False:
        raise ValueError("live destructive purge is structurally prohibited")
    regen_plan, evidence_body, verdict, authority = _strict_regeneration_evidence(
        prerequisites,
        regeneration_evidence,
        authority_root=authority_root,
        trust_store=trust_store,
    )
    att = evidence_body.get("regeneration_attestation", {})
    sealed = att.get("sealed_commitments") if isinstance(att, Mapping) else None
    required_sealed = {
        "result_manifest_hash",
        "archive_a_readback_root",
        "archive_b_readback_root",
        "truth_isolation_commitment",
        "sealed_package_root",
    }
    if not isinstance(sealed, Mapping) or set(sealed) != required_sealed:
        raise ValueError("exact sealed commitments are required for purge")
    expected_sealed = {
        "result_manifest_hash": prerequisites.get("result_manifest_hash"),
        "archive_a_readback_root": prerequisites.get(
            "archive_a_readback_root", prerequisites.get("archive_a_hash")
        ),
        "archive_b_readback_root": prerequisites.get(
            "archive_b_readback_root", prerequisites.get("archive_b_hash")
        ),
        "truth_isolation_commitment": prerequisites.get(
            "truth_isolation_commitment", truth_hash
        ),
        "sealed_package_root": prerequisites.get("sealed_package_root"),
    }
    if dict(sealed) != expected_sealed:
        raise ValueError(
            "sealed commitments do not match independently supplied purge prerequisites"
        )
    if not isinstance(development_capability, Mapping):
        raise PermissionError("explicit development purge capability is required")
    capability = _persistable_projection(development_capability)
    if (
        capability.get("development_only") is not True
        or capability.get("live_destructive_use_allowed") is not False
        or capability.get("quiescence") is not True
    ):
        raise PermissionError("development purge capability is missing or unsafe")
    cap_hash = capability.get("capability_hash", capability.get("marker_hash"))
    if not _HEX64.fullmatch(str(cap_hash or "")):
        raise PermissionError("development capability commitment is required")
    body = {
        "schema_version": _AUTH_VERSION,
        "state": "DATASET_PURGE_AUTHORIZED",
        "development_only": True,
        "live_destructive_use_allowed": False,
        "development_scope": "SYSTEM_TEMP_FIXTURE_ONLY_EXPLICIT_QUIESCENCE",
        "segment_id": plan.get("segment_id"),
        "segment_hash": sha256_hex(canonical_bytes(plan.get("segment_id"))),
        "plan_hash": plan.get("plan_hash"),
        "manifest_hash": plan.get("manifest_hash"),
        "authority_hash": authority["authority_hash"],
        "state_signature": prerequisites["state_signature"],
        "result_manifest_hash": prerequisites["result_manifest_hash"],
        "archive_a_hash": prerequisites["archive_a_hash"],
        "archive_b_hash": prerequisites["archive_b_hash"],
        "truth_isolation_hash": truth_hash,
        "regeneration_plan_hash": regen_plan["plan_hash"],
        "regeneration_evidence_hash": sha256_hex(canonical_bytes(evidence_body)),
        "regeneration_verdict_hash": verdict["verdict_hash"],
        "dataset_approval_commitment": prerequisites["dataset_approval_commitment"],
        "stat_approval_commitment": prerequisites["stat_approval_commitment"],
        "approval_commitment_scope": "DEVELOPMENT_COMMITMENTS_NOT_AUTHENTIC_LIVE_SIGNATURES",
        "authority_root": str(Path(authority_root).resolve()),
        "development_capability": capability,
        "prerequisites": _persistable_projection(prerequisites),
        "regeneration_evidence": evidence_body,
    }
    return body, evidence_body


def authorize_purge(
    prerequisites: Mapping[str, Any], plan: Mapping[str, Any] | None = None
) -> bool:
    """This boolean surface can never authorize a purge; fail loudly instead.

    Historically this helper always returned ``False`` while still looking
    like an authorization API. Authorization is only expressible through
    :func:`create_purge_authorization`, which produces the hash-bound record
    that :func:`execute_purge` re-validates reconstructively.
    """

    raise NotImplementedError(
        "authorize_purge cannot authorize anything; use create_purge_authorization"
    )


def create_purge_authorization(
    prerequisites: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    authority_root: str | os.PathLike[str],
    regeneration_evidence: Mapping[str, Any],
    development_capability: Mapping[str, Any] | None = None,
    trust_store: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _validated_plan(plan)
    if not isinstance(development_capability, Mapping):
        raise PermissionError("explicit development purge capability is required")
    body, _ = _authorization_body(
        prerequisites,
        plan,
        authority_root=authority_root,
        regeneration_evidence=regeneration_evidence,
        development_capability=development_capability,
        trust_store=trust_store,
    )
    return {**body, "authorization_hash": sha256_hex(canonical_bytes(body))}


def _validated_authorization(
    authorization: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    trust_store: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(authorization, Mapping):
        raise PermissionError("destructive purge requires an authorization record")
    raw_body = {
        key: authorization[key] for key in authorization if key != "authorization_hash"
    }
    try:
        body = _persistable_projection(raw_body)
    except ValueError as exc:
        raise PermissionError(
            "purge authorization contains non-persistable values"
        ) from exc
    if body != raw_body:
        raise PermissionError("purge authorization contains non-persisted fields")
    if authorization.get("authorization_hash") != sha256_hex(canonical_bytes(body)):
        raise PermissionError("purge authorization hash mismatch")
    if (
        body.get("schema_version") != _AUTH_VERSION
        or body.get("state") != "DATASET_PURGE_AUTHORIZED"
    ):
        raise PermissionError("purge authorization state/version mismatch")
    for key in ("segment_id", "plan_hash", "manifest_hash"):
        if body.get(key) != plan.get(key):
            raise PermissionError(f"purge authorization {key} mismatch")
    if (
        body.get("development_only") is not True
        or body.get("live_destructive_use_allowed") is not False
    ):
        raise PermissionError("live destructive purge is structurally prohibited")
    prerequisites = body.get("prerequisites")
    evidence = body.get("regeneration_evidence")
    if not isinstance(prerequisites, Mapping) or not isinstance(evidence, Mapping):
        raise PermissionError("purge authorization strict evidence is incomplete")
    try:
        reconstructed, _ = _authorization_body(
            prerequisites,
            plan,
            authority_root=body.get("authority_root"),
            regeneration_evidence=evidence,
            development_capability=body.get("development_capability"),
            trust_store=trust_store,
        )
    except (OSError, TypeError, ValueError, KeyError, PermissionError) as exc:
        raise PermissionError(
            f"purge authorization prerequisites are not reconstructively valid: {exc}"
        ) from exc
    if _persistable_projection(reconstructed) != body:
        raise PermissionError(
            "purge authorization prerequisite body is not reconstructively equal"
        )
    for key in (
        "state_signature",
        "result_manifest_hash",
        "archive_a_hash",
        "archive_b_hash",
        "dataset_approval_commitment",
        "stat_approval_commitment",
    ):
        if body.get(key) != prerequisites.get(key):
            raise PermissionError(f"purge authorization prerequisite {key} mismatch")
    truth_hash = prerequisites.get(
        "truth_isolation_hash", prerequisites.get("truth_isolation_qa_hash")
    )
    if body.get("truth_isolation_hash") != truth_hash:
        raise PermissionError("purge authorization truth-isolation commitment mismatch")

    persisted_plan = prerequisites.get("regeneration_plan")
    evidence_plan = evidence.get("plan")
    persisted_verdict = prerequisites.get("regeneration_verdict")
    evidence_verdict = evidence.get("verdict")
    if not all(
        isinstance(value, Mapping)
        for value in (
            persisted_plan,
            evidence_plan,
            persisted_verdict,
            evidence_verdict,
        )
    ):
        raise PermissionError(
            "purge authorization strict plan/verdict references are incomplete"
        )
    if _persistable_projection(persisted_plan) != _persistable_projection(
        evidence_plan
    ):
        raise PermissionError(
            "purge authorization regeneration plan reference mismatch"
        )
    if _persistable_projection(persisted_verdict) != _persistable_projection(
        evidence_verdict
    ):
        raise PermissionError(
            "purge authorization regeneration verdict reference mismatch"
        )

    def _checked_hash(
        record: Mapping[str, Any],
        field: str,
        label: str,
        *,
        excluded: frozenset[str] = frozenset(),
    ) -> None:
        supplied = record.get(field)
        unsigned = {
            key: value
            for key, value in record.items()
            if key != field and key not in excluded
        }
        if not isinstance(supplied, str) or supplied != sha256_hex(
            canonical_bytes(unsigned)
        ):
            raise PermissionError(f"purge authorization {label} hash mismatch")

    _checked_hash(
        persisted_plan,
        "plan_hash",
        "regeneration plan",
        excluded=frozenset({"freeze_event"}),
    )
    _checked_hash(persisted_verdict, "verdict_hash", "regeneration verdict")
    expectations = evidence.get("expectations")
    reports = evidence.get("reports")
    if not isinstance(expectations, Sequence) or isinstance(
        expectations, (str, bytes, bytearray)
    ):
        raise PermissionError(
            "purge authorization regeneration expectations are incomplete"
        )
    if not isinstance(reports, Sequence) or isinstance(
        reports, (str, bytes, bytearray)
    ):
        raise PermissionError("purge authorization regeneration reports are incomplete")
    for expectation in expectations:
        if not isinstance(expectation, Mapping):
            raise PermissionError(
                "purge authorization regeneration expectation is invalid"
            )
        _checked_hash(expectation, "expectation_hash", "regeneration expectation")
    for report in reports:
        if not isinstance(report, Mapping):
            raise PermissionError("purge authorization regeneration report is invalid")
        _checked_hash(report, "report_hash", "regeneration report")
    if body.get("regeneration_plan_hash") != persisted_plan.get("plan_hash"):
        raise PermissionError(
            "purge authorization regeneration plan commitment mismatch"
        )
    if body.get("regeneration_verdict_hash") != persisted_verdict.get("verdict_hash"):
        raise PermissionError(
            "purge authorization regeneration verdict commitment mismatch"
        )
    if body.get("regeneration_evidence_hash") != sha256_hex(canonical_bytes(evidence)):
        raise PermissionError("purge authorization regeneration evidence hash mismatch")
    runtime_authority = persisted_plan.get("runtime_authority")
    if not isinstance(runtime_authority, Mapping) or body.get(
        "authority_hash"
    ) != runtime_authority.get("authority_hash"):
        raise PermissionError(
            "purge authorization runtime authority commitment mismatch"
        )
    return body


def _capability_marker(root: Path) -> Path:
    return root / ".rfb-purge-development-capability.json"


def create_development_purge_capability(
    root: str | os.PathLike[str], *, quiescence_confirmed: bool = False
) -> dict[str, Any]:
    """Create an explicitly quiescent capability for temp-root fixture rehearsal."""

    if quiescence_confirmed is not True:
        raise PermissionError("fixture purge capability requires explicit quiescence")
    root = Path(root)
    root, metadata = _validated_root(root)
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        root.relative_to(temp_root)
    except ValueError as exc:
        raise PermissionError(
            "development purge root must be under OS temp directory"
        ) from exc
    body = {
        "schema_version": "purge-capability.v1",
        "root": str(root),
        "root_lstat": {"dev": int(metadata.st_dev), "ino": int(metadata.st_ino)},
        "development_only": True,
        "live_destructive_use_allowed": False,
        "quiescence": True,
    }
    body["marker_hash"] = sha256_hex(canonical_bytes(body))
    _atomic_json(_capability_marker(root), body)
    return {
        # Persist only the root-relative marker identity. The absolute temp
        # path is reconstructed from the already validated purge root during
        # controlled fixture execution and never enters durable evidence.
        "marker": _capability_marker(root).name,
        "marker_hash": body["marker_hash"],
        **{
            k: body[k]
            for k in ("development_only", "live_destructive_use_allowed", "quiescence")
        },
    }


def _ledger_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise ValueError("purge ledger must be a real regular file")
    rows: list[dict[str, Any]] = []
    previous = ""
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            raise ValueError(f"blank purge ledger row at line {line_number}")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid purge ledger row at line {line_number}") from exc
        if not isinstance(row, dict) or row.get("version") != _LEDGER_VERSION:
            raise ValueError("purge ledger row version/type invalid")
        unsigned = {key: value for key, value in row.items() if key != "entry_hash"}
        if row.get("prev_hash", "") != previous or row.get("entry_hash") != sha256_hex(
            canonical_bytes(unsigned)
        ):
            raise ValueError("purge ledger hash chain invalid")
        previous = row["entry_hash"]
        rows.append(row)
    return rows


@contextmanager
def _ledger_lock(path: Path) -> Iterator[None]:
    lock = path.with_name(f".{path.name}.lock")
    descriptor: int | None = None
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        os.fsync(descriptor)
        yield
    except FileExistsError as exc:
        raise RuntimeError("purge ledger is locked by another writer") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
            lock.unlink(missing_ok=True)


def append_purge_ledger(
    path: str | os.PathLike[str], event: Mapping[str, Any]
) -> dict[str, Any]:
    ledger = Path(path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    if ledger.exists() and ledger.is_symlink():
        raise ValueError("purge ledger cannot be a symbolic link")
    with _ledger_lock(ledger):
        rows = _ledger_rows(ledger)
        row = {
            "version": _LEDGER_VERSION,
            **dict(event),
            "prev_hash": rows[-1]["entry_hash"] if rows else "",
        }
        row["entry_hash"] = sha256_hex(canonical_bytes(row))
        with ledger.open("ab") as stream:
            stream.write(canonical_bytes(row) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    return row


def _operation_rows(
    rows: Sequence[Mapping[str, Any]], operation_id: str, plan_hash: str
) -> list[Mapping[str, Any]]:
    selected = [row for row in rows if row.get("operation_id") == operation_id]
    if any(row.get("plan_hash") != plan_hash for row in selected):
        raise RuntimeError("purge ledger operation is bound to another plan")
    if selected and selected[0].get("event") != "PURGE_INTENT":
        raise RuntimeError("purge ledger operation does not start with intent")
    allowed = {"PURGE_INTENT", "UNLINK_INTENT", "UNLINK", "PURGE_COMMITTED"}
    if any(row.get("event") not in allowed for row in selected):
        raise RuntimeError("purge ledger contains an unknown operation event")
    return selected


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def execute_purge(
    plan: Mapping[str, Any],
    authorization: Mapping[str, Any] | None = None,
    *,
    dry_run: bool | None = None,
    ledger_path: str | os.PathLike[str] | None = None,
    trust_store: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute or resume a manifest-bound purge with fsynced intent records."""

    validated = _validated_plan(plan)
    effective_dry_run = validated["dry_run"] if dry_run is None else bool(dry_run)
    if effective_dry_run:
        return {
            "dry_run": True,
            "plan_hash": plan["plan_hash"],
            "manifest_hash": validated["manifest_hash"],
            "would_delete": [entry["path"] for entry in validated["entries"]],
            "deleted": [],
        }
    if not isinstance(trust_store, Mapping):
        raise PermissionError("out-of-band regeneration trust store required")
    auth = _validated_authorization(authorization, plan, trust_store=trust_store)
    root: Path = validated["root_path"]
    if auth.get("development_only") is not True:
        raise PermissionError("live destructive purge is structurally prohibited")
    capability = auth.get("development_capability")
    if (
        not isinstance(capability, Mapping)
        or capability.get("development_only") is not True
        or capability.get("live_destructive_use_allowed") is not False
        or capability.get("quiescence") is not True
    ):
        raise PermissionError("development purge capability is missing or unsafe")
    marker_reference = str(capability.get("marker", ""))
    try:
        marker = root / _safe_relative(marker_reference)
    except ValueError as exc:
        raise PermissionError(
            "development purge capability marker reference is unsafe"
        ) from exc
    if (
        marker != _capability_marker(root)
        or not marker.is_file()
        or marker.is_symlink()
    ):
        raise PermissionError(
            "development purge capability marker is missing or tampered"
        )
    marker_body = json.loads(marker.read_text(encoding="utf-8"))
    if marker_body.get("marker_hash") != capability.get("marker_hash"):
        raise PermissionError("development purge capability marker hash mismatch")
    _, marker_metadata = _validated_root(root)
    if marker_body.get("root_lstat") != {
        "dev": int(marker_metadata.st_dev),
        "ino": int(marker_metadata.st_ino),
    } or marker_body.get("root") != str(root):
        raise PermissionError("development purge capability root identity changed")
    try:
        Path(root).resolve().relative_to(Path(tempfile.gettempdir()).resolve())
    except ValueError as exc:
        raise PermissionError(
            "development purge root must be under OS temp directory"
        ) from exc
    ledger = (
        Path(ledger_path)
        if ledger_path is not None
        else root.parent / "dataset_purge_ledger.jsonl"
    )
    ledger_absolute = Path(os.path.abspath(ledger))
    targets = {
        _target(root, _safe_relative(entry["path"])) for entry in validated["entries"]
    }
    if ledger_absolute in targets or ledger_absolute.is_symlink():
        raise PermissionError("purge ledger overlaps the deletion allowlist")
    operation_id = sha256_hex(
        canonical_bytes(
            {
                "authorization_hash": authorization["authorization_hash"],
                "plan_hash": plan["plan_hash"],
            }
        )
    )
    execution_lock = root / ".rfb-purge-execution.lock"
    try:
        lock_fd = os.open(execution_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("purge execution is locked by another writer") from exc
    try:
        os.write(lock_fd, str(os.getpid()).encode("ascii"))
        os.fsync(lock_fd)
        # Revalidate root and every allowlisted target while the exclusive guard is held.
        _validated_plan(plan)
        marker_body = json.loads(marker.read_text(encoding="utf-8"))
        marker_unsigned = {
            key: marker_body[key] for key in marker_body if key != "marker_hash"
        }
        if marker_body.get("marker_hash") != sha256_hex(
            canonical_bytes(marker_unsigned)
        ):
            raise PermissionError("development purge capability marker changed")
        _, locked_root_metadata = _validated_root(root)
        if marker_body.get("root_lstat") != {
            "dev": int(locked_root_metadata.st_dev),
            "ino": int(locked_root_metadata.st_ino),
        }:
            raise PermissionError("purge root identity changed while locked")
        rows = _ledger_rows(ledger_absolute)
        operation = _operation_rows(rows, operation_id, plan["plan_hash"])
        if operation and operation[-1].get("event") == "PURGE_COMMITTED":
            recreated = [
                entry["path"]
                for entry in validated["entries"]
                if _target(root, _safe_relative(entry["path"])).exists()
            ]
            if recreated:
                raise RuntimeError(f"committed purge targets reappeared: {recreated}")
            return {
                "dry_run": False,
                "deleted": [],
                "remaining": 0,
                "resumed": True,
                "operation_id": operation_id,
                "ledger_head": operation[-1]["entry_hash"],
            }
        if not operation:
            append_purge_ledger(
                ledger_absolute,
                {
                    "event": "PURGE_INTENT",
                    "operation_id": operation_id,
                    "plan_hash": plan["plan_hash"],
                    "manifest_hash": validated["manifest_hash"],
                    "authorization_hash": authorization["authorization_hash"],
                    "development_only": auth["development_only"],
                },
            )
            operation = _operation_rows(
                _ledger_rows(ledger_absolute), operation_id, plan["plan_hash"]
            )

        deleted: list[str] = []
        for entry in validated["entries"]:
            relative = _safe_relative(entry["path"])
            target = _target(root, relative)
            intent = next(
                (
                    row
                    for row in operation
                    if row.get("event") == "UNLINK_INTENT"
                    and row.get("path") == entry["path"]
                ),
                None,
            )
            done = next(
                (
                    row
                    for row in operation
                    if row.get("event") == "UNLINK" and row.get("path") == entry["path"]
                ),
                None,
            )
            if done is not None:
                if target.exists():
                    raise RuntimeError(f"purged target was recreated: {entry['path']}")
                continue
            if intent is None:
                current = _file_snapshot(target)
                if current != entry["lstat"]:
                    raise RuntimeError(f"purge target changed: {entry['path']}")
                intent = append_purge_ledger(
                    ledger_absolute,
                    {
                        "event": "UNLINK_INTENT",
                        "operation_id": operation_id,
                        "path": entry["path"],
                        "expected_lstat": entry["lstat"],
                        "plan_hash": plan["plan_hash"],
                    },
                )
                operation = _operation_rows(
                    _ledger_rows(ledger_absolute), operation_id, plan["plan_hash"]
                )
            if target.exists():
                current = _file_snapshot(target)
                if (
                    current != entry["lstat"]
                    or intent.get("expected_lstat") != entry["lstat"]
                ):
                    raise RuntimeError(
                        f"purge target changed after intent: {entry['path']}"
                    )
                target.unlink()
                _fsync_directory(target.parent)
                deleted.append(entry["path"])
                recovered_missing = False
            else:
                recovered_missing = True
            append_purge_ledger(
                ledger_absolute,
                {
                    "event": "UNLINK",
                    "operation_id": operation_id,
                    "path": entry["path"],
                    "plan_hash": plan["plan_hash"],
                    "recovered_missing_after_intent": recovered_missing,
                },
            )
            operation = _operation_rows(
                _ledger_rows(ledger_absolute), operation_id, plan["plan_hash"]
            )

        remaining = [
            entry["path"]
            for entry in validated["entries"]
            if _target(root, _safe_relative(entry["path"])).exists()
        ]
        if remaining:
            raise RuntimeError(f"purge allowlist residuals remain: {remaining}")
        committed = append_purge_ledger(
            ledger_absolute,
            {
                "event": "PURGE_COMMITTED",
                "operation_id": operation_id,
                "plan_hash": plan["plan_hash"],
                "manifest_hash": validated["manifest_hash"],
                "deleted_count": len(validated["entries"]),
            },
        )
        return {
            "dry_run": False,
            "deleted": deleted,
            "remaining": 0,
            "resumed": bool(operation),
            "operation_id": operation_id,
            "ledger_head": committed["entry_hash"],
        }
    finally:
        os.close(lock_fd)
        execution_lock.unlink(missing_ok=True)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(dict(value)) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def reconcile_purge(
    plan: Mapping[str, Any],
    ledger_path: str | os.PathLike[str],
    tombstone_path: str | os.PathLike[str],
    *,
    archive_targets: Sequence[Any],
    archive_expected: Mapping[str, str],
    trusted_open_deleted_bytes: int | None = None,
    development_only: bool = False,
    space_tolerance_bytes: int = 0,
) -> dict[str, Any]:
    """Collect reconciliation evidence and emit a tombstone only on full closure."""

    validated = _validated_plan(plan)
    root: Path = validated["root_path"]
    rows = _ledger_rows(Path(ledger_path))
    committed = [
        row
        for row in rows
        if row.get("event") == "PURGE_COMMITTED"
        and row.get("plan_hash") == plan.get("plan_hash")
    ]
    residuals = [
        entry["path"]
        for entry in validated["entries"]
        if _target(root, _safe_relative(entry["path"])).exists()
    ]
    try:
        if trusted_open_deleted_bytes is not None and not development_only:
            raise ValueError("trusted open-deleted value is development-only")
        open_deleted = open_deleted_bytes(
            trusted_open_deleted_bytes=trusted_open_deleted_bytes
        )
        open_deleted_probe_error = None
    except (ProbeUnavailable, ValueError) as exc:
        open_deleted = None
        open_deleted_probe_error = str(exc)
    filesystem_after = filesystem_used_bytes(root)
    expected_reclaimed = sum(
        entry["lstat"]["allocated_bytes"] for entry in validated["entries"]
    )
    observed_reclaimed = max(
        0, validated["filesystem_used_bytes_before"] - filesystem_after
    )
    if (
        isinstance(space_tolerance_bytes, bool)
        or not isinstance(space_tolerance_bytes, int)
        or space_tolerance_bytes < 0
        or (space_tolerance_bytes and not development_only)
    ):
        raise ValueError(
            "space tolerance must be a non-negative development-only value"
        )
    unexplained_delta = max(
        0, expected_reclaimed - observed_reclaimed - space_tolerance_bytes
    )

    from .archive_qa import qa_archives

    archive_report = qa_archives(list(archive_targets), dict(archive_expected))
    archive_ok = archive_report.get("pass") is True
    ledger_head = rows[-1]["entry_hash"] if rows else ""
    checks = {
        "purge_ledger_committed": bool(committed),
        "ephemeral_files_remaining": len(residuals),
        "open_deleted_bytes": open_deleted,
        "unexplained_delta": unexplained_delta,
        "archive_a_rechecked": archive_ok,
        "archive_b_rechecked": archive_ok,
    }
    passed = (
        checks["purge_ledger_committed"]
        and checks["ephemeral_files_remaining"] == 0
        and checks["open_deleted_bytes"] == 0
        and checks["unexplained_delta"] == 0
        and archive_ok
    )
    if not passed:
        return {
            "pass": False,
            "checks": checks,
            "residual_paths": residuals,
            "open_deleted_probe_error": open_deleted_probe_error,
            "archive_recheck": archive_report,
            "local_live_gate_passed": False,
        }
    archive_commitment = sha256_hex(
        canonical_bytes(dict(sorted(archive_expected.items())))
    )
    body: dict[str, Any] = {
        "schema_version": "dataset-purge-tombstone.v2",
        "event": "DATASET_PURGED",
        "pass": True,
        "development_only": bool(development_only),
        "local_live_gate_passed": False,
        "live_status": "PENDING" if development_only else "PASS",
        "segment_id": validated["segment_id"],
        "plan_hash": plan["plan_hash"],
        "manifest_hash": validated["manifest_hash"],
        "purge_ledger_head": ledger_head,
        "ephemeral_files_remaining": 0,
        "residual_paths": [],
        "open_deleted_bytes": 0,
        "open_deleted_measurement": (
            "TRUSTED_DEVELOPMENT_FIXTURE_VALUE"
            if trusted_open_deleted_bytes is not None
            else "OS_BACKED_COMPLETE_PROBE"
        ),
        "filesystem_used_bytes_before": validated["filesystem_used_bytes_before"],
        "filesystem_used_bytes_after": filesystem_after,
        "expected_reclaimed_bytes": expected_reclaimed,
        "observed_reclaimed_bytes": observed_reclaimed,
        "space_tolerance_bytes": space_tolerance_bytes,
        "unexplained_delta": 0,
        "archive_a_rechecked": True,
        "archive_b_rechecked": True,
        "archive_expected_commitment_sha256": archive_commitment,
    }
    body["tombstone_hash"] = sha256_hex(canonical_bytes(body))
    _atomic_json(Path(tombstone_path), body)
    return body


__all__ = [
    "append_purge_ledger",
    "authorize_purge",
    "build_purge_plan",
    "create_development_purge_capability",
    "create_purge_authorization",
    "execute_purge",
    "freeze_purge_manifest",
    "reconcile_purge",
]
