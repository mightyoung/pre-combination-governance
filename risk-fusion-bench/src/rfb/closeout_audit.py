"""Independent, commitment-only G004 segment-closeout audit package."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contracts.canonical_json import canonical_bytes, sha256_hex

CLOSEOUT_FILES = (
    "regeneration_sampling_qa.json",
    "purge_authorization.json",
    "dataset_purge_ledger.json",
    "dataset_purge_tombstone.json",
    "segment_closeout_manifest.json",
)
_RESULT_FILES = ("durable_rows.jsonl", "durable_result_manifest.json")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_FORBIDDEN_KEY_TOKENS = (
    "truth",
    "raw_payload",
    "payload_path",
    "payload_bytes",
    "sidecar",
)
_ALLOWED_GOVERNANCE_KEYS = frozenset(
    {"truth_isolation_verified", "truth_isolation_status"}
)


def _persistable(value: Any) -> Any:
    """Return the JSON projection used by the strict purge contracts."""
    if isinstance(value, Mapping):
        return {
            key: _persistable(child)
            for key, child in value.items()
            if key != "canonical_bytes"
        }
    if isinstance(value, list):
        return [_persistable(child) for child in value]
    if isinstance(value, (bytes, bytearray)):
        raise ValueError("closeout evidence contains non-persistable bytes")
    return value


def _rehydrate_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Recreate the in-memory canonical-bytes field of a persisted v3 plan."""
    if (
        not isinstance(plan, Mapping)
        or plan.get("schema_version") != "regeneration-plan.v3"
    ):
        raise ValueError("strict regeneration plan v3 is required")
    body = {
        key: value
        for key, value in plan.items()
        if key not in {"canonical_bytes", "plan_hash", "freeze_event"}
    }
    encoded = canonical_bytes(body)
    if plan.get("plan_hash") != sha256_hex(encoded):
        raise ValueError("strict regeneration plan hash mismatch")
    return {
        **body,
        "canonical_bytes": encoded,
        "plan_hash": plan["plan_hash"],
        "freeze_event": plan.get("freeze_event"),
    }


def _strict_regeneration(
    evidence: Any,
    *,
    authority_root: str | os.PathLike[str] | None,
    segment_id: str,
    trust_store: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    """Rebuild the strict regeneration verdict from persisted components."""
    from .regeneration import (
        RuntimeCommitmentAuthority,
        _validated_authority_root,
        execute_regeneration_plan_v3,
        finalize_regeneration_verdict_v2,
        verify_regeneration_attestation,
    )

    if not isinstance(evidence, Mapping):
        raise ValueError("full regeneration evidence is required")
    plan_raw = evidence.get("plan", evidence.get("regeneration_plan"))
    expectations = evidence.get("expectations")
    reports = evidence.get("sample_reports", evidence.get("reports"))
    persisted = evidence.get(
        "aggregate_verdict",
        evidence.get("verdict", evidence.get("regeneration_verdict")),
    )
    if not isinstance(plan_raw, Mapping) or not isinstance(persisted, Mapping):
        raise ValueError("strict regeneration plan and verdict are required")
    if not isinstance(expectations, list) or not isinstance(reports, list):
        raise ValueError("strict regeneration expectations and reports are required")
    if (
        evidence.get("schema_version") != "regeneration-sampling-qa.v3"
        or evidence.get("status") != "REGEN_CONSISTENT_UNATTESTED"
        or evidence.get("authoritative") is not False
        or evidence.get("development_status") != "PASS"
        or evidence.get("live_status") != "PENDING"
        or evidence.get("development_only") is not True
        or evidence.get("local_live_gate_passed") is not False
        or evidence.get("regeneration_verified") is not True
        or evidence.get("purge_authorized") is not False
        or evidence.get("frozen_before_execution") is not True
        or evidence.get("segment_id") != segment_id
    ):
        raise ValueError("regeneration QA v3 metadata/latches are invalid")
    plan = _rehydrate_plan(plan_raw)
    if plan.get("segment_id") != segment_id:
        raise ValueError("regeneration segment mismatch")
    if evidence.get("selected_bundle_ids") != plan.get("selected_ids"):
        raise ValueError("regeneration selected bundle commitment mismatch")
    if evidence.get("sample_count") != len(plan.get("selected_ids", [])):
        raise ValueError("regeneration sample count mismatch")
    # authority_root is a live function argument; it is intentionally absent
    # from the persisted QA document to avoid binding an absolute local path.
    root_value = authority_root
    if (
        not isinstance(root_value, (str, os.PathLike))
        or not os.fspath(root_value).strip()
    ):
        raise ValueError("authority_root is required for strict regeneration evidence")
    root = _validated_authority_root(Path(root_value))
    authority_data = plan.get("runtime_authority")
    if not isinstance(authority_data, Mapping):
        raise ValueError("runtime authority is required by regeneration plan")
    generator = authority_data.get("generator_path")
    segment_config = authority_data.get("segment_config_path")
    if not isinstance(generator, str) or not isinstance(segment_config, str):
        raise ValueError("runtime authority generator/config bindings are required")
    loaded = RuntimeCommitmentAuthority.load(
        root, generator_path=generator, segment_config_path=segment_config
    )
    if loaded.to_dict() != dict(authority_data):
        raise ValueError("runtime authority does not match persisted regeneration plan")
    # These are strict execution inputs, not optional annotations.  Require
    # them to be persisted so a later closeout audit cannot silently fall back
    # to the frozen plan or current on-disk authority.
    persisted_authority = evidence.get("runtime_authority")
    if _persistable(persisted_authority) != _persistable(authority_data):
        raise ValueError("top-level runtime authority does not match frozen plan")
    current_authority = evidence.get("current_authority")
    freeze_event = evidence.get("freeze_event")
    ledger_rows = evidence.get("execution_ledger_rows")
    current_bundle_ids = evidence.get("current_bundle_ids")
    if (
        not isinstance(current_authority, Mapping)
        or not isinstance(freeze_event, Mapping)
        or not isinstance(ledger_rows, list)
        or not isinstance(current_bundle_ids, list)
    ):
        raise ValueError(
            "strict current authority, freeze event, execution ledger and bundle evidence are required"
        )
    execute_regeneration_plan_v3(
        plan,
        authority_root=root,
        current_authority=current_authority,
        freeze_event=freeze_event,
        execution_ledger_rows=ledger_rows,
        current_bundle_ids=current_bundle_ids,
        segment_id=segment_id,
        sample_selection_seed=plan["sample_selection_seed"],
    )
    rebuilt = finalize_regeneration_verdict_v2(plan, expectations, reports)
    if _persistable(persisted) != _persistable(rebuilt):
        raise ValueError("persisted regeneration verdict is not reconstructively equal")
    if (
        rebuilt.get("status") not in {"REGEN_VERIFIED", "REGEN_CONSISTENT_UNATTESTED"}
        or rebuilt.get("regeneration_verified") is not True
        or rebuilt.get("next_segment_allowed") is not False
        or rebuilt.get("purge_authorized") is not False
    ):
        raise ValueError("regeneration verdict latches are invalid")
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
        plan=plan,
        expectations=list(expectations),
        reports=list(reports),
        verdict=rebuilt,
        freeze_event=freeze_event,
        execution_ledger_rows=ledger_rows,
        independent_key_ids=trust_store.get(
            "independent_key_ids", {trust_store.get("key_id")}
        ),
    )
    if _persistable(evidence.get("freeze_event")) != _persistable(freeze_event):
        raise ValueError("freeze event is not persisted in regeneration evidence")
    return _persistable(plan), _persistable(evidence), rebuilt, loaded.to_dict(), root


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _merkle(files: Mapping[str, str]) -> str:
    leaves = [
        hashlib.sha256((name + "\0" + files[name]).encode("utf-8")).digest()
        for name in sorted(files)
    ]
    if not leaves:
        return hashlib.sha256(b"").hexdigest()
    while len(leaves) > 1:
        if len(leaves) % 2:
            leaves.append(leaves[-1])
        leaves = [
            hashlib.sha256(leaves[index] + leaves[index + 1]).digest()
            for index in range(0, len(leaves), 2)
        ]
    return leaves[0].hex()


def _is_reparse(path: Path, metadata: os.stat_result | None = None) -> bool:
    try:
        details = metadata or path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(
        getattr(details, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _safe_path(path: Path, *, label: str, require_directory: bool) -> Path:
    absolute = Path(os.path.abspath(path))
    if absolute == Path(absolute.anchor):
        raise ValueError(f"{label} cannot be a filesystem root")
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
    if require_directory and (
        not absolute.exists() or not stat.S_ISDIR(absolute.lstat().st_mode)
    ):
        raise ValueError(f"{label} must be a real directory")
    return absolute


def _allowed_sensitive_key(key: str) -> bool:
    lowered = key.casefold()
    return (
        lowered in _ALLOWED_GOVERNANCE_KEYS
        or lowered == "contains_raw_dataset"
        or "commitment" in lowered
        or lowered.endswith("_sha256")
        or lowered.endswith("_hash")
    )


def _json_safe(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"non-string key at {path}")
            lowered = key.casefold()
            if any(
                token in lowered for token in _FORBIDDEN_KEY_TOKENS
            ) and not _allowed_sensitive_key(key):
                raise ValueError(f"forbidden raw/truth key at {path}.{key}")
            if lowered == "contains_raw_dataset" and item is not False:
                raise ValueError(f"contains_raw_dataset must be false at {path}.{key}")
            _json_safe(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _json_safe(item, f"{path}[{index}]")
    elif isinstance(value, float) and (
        value != value or value in (float("inf"), float("-inf"))
    ):
        raise ValueError(f"non-finite number at {path}")


def _load_result_package(source: Path) -> tuple[dict[str, str], list[Any]]:
    names = {path.name for path in source.iterdir() if path.is_file()}
    if names != set(_RESULT_FILES) or any(
        path.is_symlink() for path in source.iterdir()
    ):
        raise ValueError("result package must contain exactly two real durable files")
    rows: list[Any] = []
    for line_number, line in enumerate(
        (source / "durable_rows.jsonl").read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            raise ValueError(f"blank durable row at line {line_number}")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid durable row at line {line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError("durable rows must be JSON objects")
        _json_safe(row)
        rows.append(row)
    if not rows:
        raise ValueError("durable result package has no rows")
    try:
        manifest = json.loads(
            (source / "durable_result_manifest.json").read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        raise ValueError("invalid durable result manifest") from exc
    if not isinstance(manifest, dict):
        raise ValueError("durable result manifest must be an object")
    _json_safe(manifest)
    hashes = {name: _sha256(source / name) for name in _RESULT_FILES}
    return hashes, rows


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    _json_safe(value)
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
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _validate_ledger_document(document: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict) or document.get("version") != 2:
        return ["purge ledger document version/type invalid"]
    events = document.get("events")
    if not isinstance(events, list) or not events:
        return ["purge ledger events missing"]
    document_plan = document.get("plan_hash")
    document_manifest = document.get("manifest_hash")
    document_segment = document.get("segment_id")
    previous = ""
    for index, row in enumerate(events):
        if not isinstance(row, dict) or row.get("version") != 2:
            errors.append(f"purge ledger row {index} type/version invalid")
            continue
        unsigned = {key: value for key, value in row.items() if key != "entry_hash"}
        if row.get("prev_hash") != previous or row.get("entry_hash") != sha256_hex(
            canonical_bytes(unsigned)
        ):
            errors.append(f"purge ledger row {index} hash chain invalid")
        if row.get("plan_hash") != document_plan:
            errors.append(f"purge ledger row {index} plan hash mismatch")
        previous = row.get("entry_hash", "")
    intents = [row for row in events if row.get("event") == "PURGE_INTENT"]
    if len(intents) != 1 or events[0] is not intents[0]:
        errors.append("purge ledger must start with exactly one PURGE_INTENT")
    else:
        if intents[0].get("manifest_hash") != document_manifest:
            errors.append("purge ledger intent manifest hash mismatch")
    committed = events[-1]
    if events[-1].get("event") != "PURGE_COMMITTED":
        errors.append("purge ledger is not committed")
    elif committed.get("manifest_hash") != document_manifest:
        errors.append("purge ledger commit manifest hash mismatch")
    if document.get("schema_version") != "dataset-purge-ledger-document.v2":
        errors.append("purge ledger schema version mismatch")
    if not all(
        isinstance(value, str) and value
        for value in (document_segment, document_plan, document_manifest)
    ):
        errors.append("purge ledger identity fields are incomplete")
    if document.get("ledger_head") != previous:
        errors.append("purge ledger head mismatch")
    return errors


def _semantic_errors(
    regeneration: Any,
    purge_authorization: Any,
    purge_ledger: Any,
    purge_tombstone: Any,
    *,
    segment_id: str,
    authority_root: str | os.PathLike[str] | None = None,
    trust_store: Mapping[str, Any] | None = None,
    expected_commitments: Mapping[str, str] | None = None,
) -> list[str]:
    errors: list[str] = []
    normalized_evidence: dict[str, Any] | None = None
    verdict: Mapping[str, Any] | None = None
    plan: Mapping[str, Any] | None = None
    try:
        plan, normalized_evidence, verdict, _authority, root = _strict_regeneration(
            regeneration,
            authority_root=authority_root,
            segment_id=segment_id,
            trust_store=trust_store or {},
        )
    except (OSError, TypeError, ValueError, KeyError) as exc:
        errors.append(f"strict regeneration evidence invalid: {exc}")
        root = None
    if plan is not None and verdict is not None:
        if not isinstance(purge_authorization, Mapping):
            errors.append("purge authorization is required")
        elif not isinstance(purge_ledger, Mapping):
            errors.append("purge ledger is required to bind purge authorization")
        else:
            try:
                from .purge import _validated_authorization

                _validated_authorization(
                    purge_authorization,
                    {
                        "segment_id": purge_ledger.get("segment_id"),
                        "plan_hash": purge_ledger.get("plan_hash"),
                        "manifest_hash": purge_ledger.get("manifest_hash"),
                    },
                    trust_store=trust_store or {},
                )
                if purge_authorization.get("segment_id") != segment_id:
                    raise ValueError("purge authorization segment mismatch")
                if purge_authorization.get("regeneration_plan_hash") != plan.get(
                    "plan_hash"
                ):
                    raise ValueError("purge authorization regeneration plan mismatch")
                if purge_authorization.get("regeneration_verdict_hash") != verdict.get(
                    "verdict_hash"
                ):
                    raise ValueError(
                        "purge authorization regeneration verdict mismatch"
                    )
                if purge_authorization.get("authority_root") != str(root):
                    raise ValueError("purge authorization authority root mismatch")
                auth_evidence = purge_authorization.get("regeneration_evidence")
                if not isinstance(auth_evidence, Mapping):
                    raise ValueError(
                        "purge authorization regeneration evidence is missing"
                    )
                auth_plan = auth_evidence.get("plan")
                auth_expectations = auth_evidence.get("expectations")
                auth_reports = auth_evidence.get(
                    "sample_reports", auth_evidence.get("reports")
                )
                auth_verdict = auth_evidence.get(
                    "aggregate_verdict", auth_evidence.get("verdict")
                )
                qa_plan = normalized_evidence.get("plan")
                qa_expectations = normalized_evidence.get("expectations")
                qa_reports = normalized_evidence.get(
                    "sample_reports", normalized_evidence.get("reports")
                )
                qa_verdict = normalized_evidence.get(
                    "aggregate_verdict", normalized_evidence.get("verdict")
                )
                if any(
                    _persistable(left) != _persistable(right)
                    for left, right in (
                        (auth_plan, qa_plan),
                        (auth_expectations, qa_expectations),
                        (auth_reports, qa_reports),
                        (auth_verdict, qa_verdict),
                    )
                ):
                    raise ValueError(
                        "purge authorization regeneration evidence mismatch"
                    )
            except (OSError, TypeError, ValueError, KeyError, PermissionError) as exc:
                errors.append(f"purge authorization invalid: {exc}")
    if (
        expected_commitments is not None
        and normalized_evidence is not None
        and isinstance(purge_authorization, Mapping)
    ):
        att = normalized_evidence.get("regeneration_attestation")
        sealed = att.get("sealed_commitments") if isinstance(att, Mapping) else None
        if not isinstance(sealed, Mapping) or dict(sealed) != dict(
            expected_commitments
        ):
            errors.append(
                "verified attestation sealed commitments do not match actual closeout artifacts"
            )
        prereq = purge_authorization.get("prerequisites")
        if isinstance(prereq, Mapping):
            actual = {
                "result_manifest_hash": prereq.get("result_manifest_hash"),
                "archive_a_readback_root": prereq.get(
                    "archive_a_readback_root", prereq.get("archive_a_hash")
                ),
                "archive_b_readback_root": prereq.get(
                    "archive_b_readback_root", prereq.get("archive_b_hash")
                ),
                "truth_isolation_commitment": prereq.get(
                    "truth_isolation_commitment", prereq.get("truth_isolation_hash")
                ),
                "sealed_package_root": prereq.get("sealed_package_root"),
            }
            if actual != dict(expected_commitments):
                errors.append(
                    "purge prerequisites commitments do not match actual closeout artifacts"
                )
    errors.extend(_validate_ledger_document(purge_ledger))
    if isinstance(purge_ledger, dict) and isinstance(purge_authorization, Mapping):
        intent = next(
            (
                row
                for row in purge_ledger.get("events", [])
                if isinstance(row, Mapping) and row.get("event") == "PURGE_INTENT"
            ),
            None,
        )
        if not isinstance(intent, Mapping):
            errors.append("purge ledger PURGE_INTENT missing")
        else:
            if intent.get("authorization_hash") != purge_authorization.get(
                "authorization_hash"
            ):
                errors.append("purge ledger authorization hash mismatch")
            for key in ("plan_hash", "manifest_hash"):
                if purge_authorization.get(key) != purge_ledger.get(key):
                    errors.append(f"purge authorization/ledger {key} mismatch")
    if not isinstance(purge_tombstone, dict):
        errors.append("purge tombstone is not an object")
    else:
        required_zero = (
            "ephemeral_files_remaining",
            "open_deleted_bytes",
            "unexplained_delta",
        )
        if (
            purge_tombstone.get("event") != "DATASET_PURGED"
            or purge_tombstone.get("pass") is not True
        ):
            errors.append("purge tombstone is not a successful DATASET_PURGED record")
        if any(purge_tombstone.get(key) != 0 for key in required_zero):
            errors.append("purge tombstone residual/open-deleted/space checks failed")
        if purge_tombstone.get("segment_id") != segment_id:
            errors.append("purge tombstone segment mismatch")
        if isinstance(purge_ledger, dict):
            if purge_tombstone.get("purge_ledger_head") != purge_ledger.get(
                "ledger_head"
            ):
                errors.append("tombstone/ledger head mismatch")
            for key in ("plan_hash", "manifest_hash"):
                if purge_tombstone.get(key) != purge_ledger.get(key):
                    errors.append(f"tombstone/ledger {key} mismatch")
    return errors


def seal_closeout(
    result_package: str | os.PathLike[str],
    output: str | os.PathLike[str],
    *,
    segment_id: str,
    development_only: bool = True,
    live_status: str = "PENDING",
    archive_expected: Mapping[str, str] | None = None,
    regeneration: Mapping[str, Any] | None = None,
    purge_authorization: Mapping[str, Any] | None = None,
    purge_ledger: Mapping[str, Any] | None = None,
    purge_tombstone: Mapping[str, Any] | None = None,
    authority_root: str | os.PathLike[str] | None = None,
    trust_store: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Seal and validate a strict six-file closeout package atomically."""

    destination = Path(output)
    try:
        if not isinstance(segment_id, str) or not segment_id.strip():
            raise ValueError("segment_id must be a non-empty string")
        if development_only is not True or live_status != "PENDING":
            raise ValueError(
                "this local closeout helper emits development-only evidence"
            )
        source = _safe_path(
            Path(result_package), label="result package", require_directory=True
        )
        _safe_path(destination.parent, label="output parent", require_directory=True)
        result_hashes, _ = _load_result_package(source)
        expected = dict(archive_expected or {})
        if expected != result_hashes:
            raise ValueError(
                "Archive A/B recheck commitments do not match result package"
            )
        archive_root = sha256_hex(canonical_bytes(dict(sorted(expected.items()))))
        truth_value = ""
        if isinstance(purge_authorization, Mapping) and isinstance(
            purge_authorization.get("prerequisites"), Mapping
        ):
            pr = purge_authorization["prerequisites"]
            truth_value = pr.get(
                "truth_isolation_commitment", pr.get("truth_isolation_hash", "")
            )
        expected_commitments = {
            "result_manifest_hash": result_hashes.get(
                "durable_result_manifest.json", ""
            ),
            "archive_a_readback_root": archive_root,
            "archive_b_readback_root": archive_root,
            "truth_isolation_commitment": truth_value,
            "sealed_package_root": result_hashes.get(
                "durable_result_manifest.json", ""
            ),
        }
        regeneration_document = dict(regeneration or {})
        authorization_document = dict(purge_authorization or {})
        ledger_document = dict(purge_ledger or {})
        tombstone_document = dict(purge_tombstone or {})
        for value in (
            regeneration_document,
            authorization_document,
            ledger_document,
            tombstone_document,
        ):
            _json_safe(value)
        semantic_errors = _semantic_errors(
            regeneration_document,
            authorization_document,
            ledger_document,
            tombstone_document,
            segment_id=segment_id,
            authority_root=authority_root,
            trust_store=trust_store or {},
            expected_commitments=expected_commitments,
        )
        if semantic_errors:
            raise ValueError("; ".join(semantic_errors))
        stage = Path(
            tempfile.mkdtemp(
                prefix=f".{destination.name}.stage-", dir=destination.parent
            )
        )
        try:
            documents = {
                "regeneration_sampling_qa.json": regeneration_document,
                "purge_authorization.json": authorization_document,
                "dataset_purge_ledger.json": ledger_document,
                "dataset_purge_tombstone.json": tombstone_document,
            }
            for name, value in documents.items():
                _atomic_json(stage / name, value)
            evidence_hashes = {name: _sha256(stage / name) for name in documents}
            manifest: dict[str, Any] = {
                "schema_version": "segment-closeout-manifest.v2",
                "segment_id": segment_id,
                "contains_raw_dataset": False,
                "development_only": True,
                "live_status": "PENDING",
                "semantic_closeout_status": "PASS",
                "result_package_files": result_hashes,
                "result_package_sha256": sha256_hex(canonical_bytes(result_hashes)),
                "archive_ab_recheck_commitments": expected,
                "files": {
                    name: {
                        "bytes": (stage / name).stat().st_size,
                        "sha256": digest,
                    }
                    for name, digest in evidence_hashes.items()
                },
                "merkle_root": _merkle(evidence_hashes),
            }
            manifest["manifest_sha256"] = sha256_hex(canonical_bytes(manifest))
            _atomic_json(stage / "segment_closeout_manifest.json", manifest)
            if destination.exists():
                if destination.is_symlink() or not destination.is_dir():
                    raise ValueError("output exists but is not a real directory")
                if {path.name for path in destination.iterdir()} - set(CLOSEOUT_FILES):
                    raise ValueError(
                        "existing output contains files outside closeout allowlist"
                    )
                backup = destination.with_name(
                    f".{destination.name}.old-{uuid.uuid4().hex}"
                )
                os.replace(destination, backup)
                try:
                    os.replace(stage, destination)
                except BaseException:
                    os.replace(backup, destination)
                    raise
                shutil.rmtree(backup)
            else:
                os.replace(stage, destination)
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
        report = validate_closeout(
            destination,
            archive_expected=expected,
            authority_root=authority_root,
            trust_store=trust_store,
        )
        return {**report, "files": list(CLOSEOUT_FILES)}
    except Exception as exc:
        return {
            "pass": False,
            "package_integrity_pass": False,
            "semantic_closeout_pass": False,
            "errors": [str(exc)],
            "local_live_gate_passed": False,
        }


def validate_closeout(
    root: str | os.PathLike[str],
    archive_expected: Mapping[str, str] | None = None,
    *,
    authority_root: str | os.PathLike[str] | None = None,
    trust_store: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        path = _safe_path(Path(root), label="closeout root", require_directory=True)
    except ValueError as exc:
        return {
            "pass": False,
            "package_integrity_pass": False,
            "semantic_closeout_pass": False,
            "errors": [str(exc)],
            "local_live_gate_passed": False,
        }
    names = {candidate.name for candidate in path.iterdir()}
    if names != set(CLOSEOUT_FILES):
        errors.append("closeout allowlist mismatch")
    documents: dict[str, Any] = {}
    for name in CLOSEOUT_FILES:
        candidate = path / name
        if not candidate.is_file() or candidate.is_symlink():
            errors.append(f"missing or non-regular closeout file: {name}")
            continue
        try:
            document = json.loads(candidate.read_text(encoding="utf-8"))
            _json_safe(document)
            documents[name] = document
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"invalid closeout file {name}: {exc}")
    manifest = documents.get("segment_closeout_manifest.json")
    integrity_errors = list(errors)
    if isinstance(manifest, dict):
        unsigned = {
            key: value for key, value in manifest.items() if key != "manifest_sha256"
        }
        if manifest.get("manifest_sha256") != sha256_hex(canonical_bytes(unsigned)):
            integrity_errors.append("closeout manifest self-hash mismatch")
        if manifest.get("contains_raw_dataset") is not False:
            integrity_errors.append("closeout manifest raw-dataset flag is not false")
        evidence_names = set(CLOSEOUT_FILES) - {"segment_closeout_manifest.json"}
        if set(manifest.get("files", {})) != evidence_names:
            integrity_errors.append("closeout manifest file allowlist mismatch")
        observed_hashes: dict[str, str] = {}
        for name in evidence_names:
            candidate = path / name
            if not candidate.is_file():
                continue
            observed_hashes[name] = _sha256(candidate)
            metadata = manifest.get("files", {}).get(name, {})
            if (
                metadata.get("sha256") != observed_hashes[name]
                or metadata.get("bytes") != candidate.stat().st_size
            ):
                integrity_errors.append(f"closeout file hash/size mismatch: {name}")
        if manifest.get("merkle_root") != _merkle(observed_hashes):
            integrity_errors.append("closeout Merkle root mismatch")
        expected = dict(
            archive_expected or manifest.get("archive_ab_recheck_commitments", {})
        )
        if manifest.get("archive_ab_recheck_commitments") != expected:
            integrity_errors.append("Archive A/B commitment mismatch")
        if manifest.get("result_package_files") != expected:
            integrity_errors.append("result-package/archive commitment mismatch")
        if manifest.get("result_package_sha256") != sha256_hex(
            canonical_bytes(expected)
        ):
            integrity_errors.append("result package commitment mismatch")
    else:
        integrity_errors.append("closeout manifest missing or invalid")

    semantic_errors: list[str] = []
    if isinstance(manifest, dict):
        semantic_errors.extend(
            _semantic_errors(
                documents.get("regeneration_sampling_qa.json"),
                documents.get("purge_authorization.json"),
                documents.get("dataset_purge_ledger.json"),
                documents.get("dataset_purge_tombstone.json"),
                segment_id=manifest.get("segment_id"),
                authority_root=authority_root,
                trust_store=trust_store,
                expected_commitments={
                    "result_manifest_hash": expected.get(
                        "durable_result_manifest.json", ""
                    ),
                    "archive_a_readback_root": sha256_hex(
                        canonical_bytes(dict(sorted(expected.items())))
                    ),
                    "archive_b_readback_root": sha256_hex(
                        canonical_bytes(dict(sorted(expected.items())))
                    ),
                    "truth_isolation_commitment": (
                        documents.get("purge_authorization.json", {})
                        .get("prerequisites", {})
                        .get(
                            "truth_isolation_commitment",
                            documents.get("purge_authorization.json", {})
                            .get("prerequisites", {})
                            .get("truth_isolation_hash", ""),
                        )
                        if isinstance(
                            documents.get("purge_authorization.json", {}).get(
                                "prerequisites"
                            ),
                            Mapping,
                        )
                        else ""
                    ),
                    "sealed_package_root": expected.get(
                        "durable_result_manifest.json", ""
                    ),
                },
            )
        )
        if (
            manifest.get("development_only") is not True
            or manifest.get("live_status") != "PENDING"
        ):
            semantic_errors.append("closeout development/live status separation failed")
        if manifest.get("semantic_closeout_status") != "PASS":
            semantic_errors.append("closeout semantic status is not PASS")
    passed = not integrity_errors and not semantic_errors
    return {
        "pass": passed,
        "package_integrity_pass": not integrity_errors,
        "semantic_closeout_pass": not semantic_errors,
        "errors": [*integrity_errors, *semantic_errors],
        "local_live_gate_passed": False,
        "live_status": "PENDING",
    }


def copy_closeout_to_local_ab(
    source: str | os.PathLike[str],
    archive_a: str | os.PathLike[str],
    archive_b: str | os.PathLike[str],
    *,
    authority_root: str | os.PathLike[str] | None = None,
    trust_store: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source_path = Path(source)
    source_check = validate_closeout(
        source_path, authority_root=authority_root, trust_store=trust_store
    )
    if not source_check["pass"]:
        return {
            "pass": False,
            "rejected": source_check["errors"],
            "local_live_gate_passed": False,
        }
    reports: list[dict[str, Any]] = []
    source_hashes = {name: _sha256(source_path / name) for name in CLOSEOUT_FILES}
    for target_value in (archive_a, archive_b):
        target = Path(target_value)
        try:
            _safe_path(target.parent, label="archive parent", require_directory=True)
            if target.exists() and (target.is_symlink() or not target.is_dir()):
                raise ValueError("unsafe archive target")
            stage = Path(
                tempfile.mkdtemp(prefix=f".{target.name}.stage-", dir=target.parent)
            )
            try:
                for name in CLOSEOUT_FILES:
                    shutil.copyfile(source_path / name, stage / name)
                copied_hashes = {name: _sha256(stage / name) for name in CLOSEOUT_FILES}
                if copied_hashes != source_hashes:
                    raise ValueError("closeout archive copy hash mismatch")
                if target.exists():
                    if {path.name for path in target.iterdir()} - set(CLOSEOUT_FILES):
                        raise ValueError("archive target contains unexpected files")
                    backup = target.with_name(f".{target.name}.old-{uuid.uuid4().hex}")
                    os.replace(target, backup)
                    try:
                        os.replace(stage, target)
                    except BaseException:
                        os.replace(backup, target)
                        raise
                    shutil.rmtree(backup)
                else:
                    os.replace(stage, target)
            finally:
                if stage.exists():
                    shutil.rmtree(stage, ignore_errors=True)
            reports.append(
                validate_closeout(
                    target, authority_root=authority_root, trust_store=trust_store
                )
            )
        except Exception as exc:
            reports.append({"pass": False, "errors": [str(exc)]})
    return {
        "pass": all(report.get("pass") is True for report in reports),
        "targets": reports,
        "local_live_gate_passed": False,
        "live_status": "PENDING",
    }


seal = seal_closeout
validate = validate_closeout
archive_qa = copy_closeout_to_local_ab

__all__ = [
    "CLOSEOUT_FILES",
    "archive_qa",
    "copy_closeout_to_local_ab",
    "seal",
    "seal_closeout",
    "validate",
    "validate_closeout",
]
