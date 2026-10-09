"""Closed durable-result rows and manifest helpers."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .contracts.canonical_json import canonical_bytes, sha256_hex

REQUIRED_ROW_FIELDS = frozenset(
    {
        "bundle_id",
        "method_id",
        "algorithm_seed",
        "prediction_or_decision",
        "scorer_metrics",
        "validity_status",
        "failure_or_timeout_code",
        "stratum_template_batch_superblock_keys",
        "resource_telemetry",
        "input_commitment",
        "generator_candidate_method_scorer_schema_container_allocation_prereg_hashes",
        "transaction_id",
        "contains_raw_dataset",
        "result_sha256",
    }
)
ALLOWED_ROW_FIELDS = REQUIRED_ROW_FIELDS | frozenset(
    {"schema_version", "manifest_refs"}
)
FORBIDDEN_TOKENS = ("truth", "raw", "payload", "sidecar")
VALIDITY_STATUSES = frozenset(
    {"VALID", "INVALID_RESULT", "FAILED", "TIMEOUT", "SKIPPED_POLICY"}
)
ROWS_NAME = "durable_rows.jsonl"
MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "contains_raw_dataset",
        "row_count",
        "expected",
        "observed",
        "missing",
        "unexpected",
        "mismatch",
        "duplicate",
        "rows_sha256",
        "files",
        "merkle_root_sha256",
        "manifest_sha256",
    }
)
LEGACY_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "contains_raw_dataset",
        "row_count",
        "expected",
        "observed",
        "missing",
        "unexpected",
        "mismatch",
        "rows_sha256",
    }
)


def walk_forbidden(value: Any, path: str = "$") -> list[str]:
    def forbidden(text: str) -> bool:
        folded = text.casefold()
        compact = "".join(char for char in folded if char.isalnum())
        return any(token in folded or token in compact for token in FORBIDDEN_TOKENS)

    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if key_text.casefold() != "contains_raw_dataset" and forbidden(key_text):
                errors.append(f"{path}.{key_text}: forbidden durable field")
            errors.extend(walk_forbidden(child, f"{path}.{key_text}"))
    elif isinstance(value, list | tuple):
        for index, child in enumerate(value):
            errors.extend(walk_forbidden(child, f"{path}[{index}]"))
    elif isinstance(value, bytes | bytearray | memoryview):
        errors.append(f"{path}: raw bytes are forbidden")
    elif isinstance(value, str) and forbidden(value):
        errors.append(f"{path}: forbidden durable string")
    return errors


def row_key(row: Mapping[str, Any] | Sequence[Any]) -> tuple[str, str, str]:
    if not isinstance(row, Mapping):
        raise TypeError("row must be an object")
    return tuple(
        str(row.get(key, "")) for key in ("bundle_id", "method_id", "algorithm_seed")
    )


def _require_mapping(row: Mapping[str, Any], key: str, errors: list[str]) -> None:
    if key in row and not isinstance(row[key], Mapping):
        errors.append(f"{key} must be object")


def _require_string(row: Mapping[str, Any], key: str, errors: list[str]) -> None:
    if key in row and (not isinstance(row[key], str) or row[key] == ""):
        errors.append(f"{key} must be non-empty string")


def _require_sha(row: Mapping[str, Any], key: str, errors: list[str]) -> None:
    if key in row and (
        not isinstance(row[key], str)
        or len(row[key]) != 64
        or any(char not in "0123456789abcdef" for char in row[key])
    ):
        errors.append(f"{key} must be a 64-character hex digest")


def row_result_sha256(row: Mapping[str, Any]) -> str:
    """Return the deterministic digest of a row excluding its digest field."""
    if not isinstance(row, Mapping):
        raise TypeError("row must be an object")
    payload = {key: value for key, value in row.items() if key != "result_sha256"}
    return sha256_hex(canonical_bytes(payload))


def validate_durable_row(row: Any) -> list[str]:
    if not isinstance(row, Mapping):
        return ["row must be object"]
    errors = [
        f"missing required field: {key}"
        for key in sorted(REQUIRED_ROW_FIELDS - set(row))
    ]
    errors.extend(
        f"unexpected field: {key}" for key in sorted(set(row) - ALLOWED_ROW_FIELDS)
    )
    for key in ("bundle_id", "method_id", "transaction_id"):
        _require_string(row, key, errors)
    if "algorithm_seed" in row and (
        not isinstance(row["algorithm_seed"], int)
        or isinstance(row["algorithm_seed"], bool)
    ):
        errors.append("algorithm_seed must be integer")
    if row.get("contains_raw_dataset") is not False:
        errors.append("contains_raw_dataset must be false")
    if "validity_status" in row and row["validity_status"] not in VALIDITY_STATUSES:
        errors.append("validity_status is not allowed")
    for key in (
        "prediction_or_decision",
        "scorer_metrics",
        "stratum_template_batch_superblock_keys",
        "resource_telemetry",
        "generator_candidate_method_scorer_schema_container_allocation_prereg_hashes",
    ):
        _require_mapping(row, key, errors)
    for key in ("input_commitment", "result_sha256"):
        _require_sha(row, key, errors)
    errors.extend(walk_forbidden(row))
    try:
        canonical_bytes(row)
    except Exception as exc:  # pragma: no cover - defensive reporting
        errors.append(f"row is not canonical JSON: {exc}")
    else:
        if isinstance(row.get("result_sha256"), str) and row.get(
            "result_sha256"
        ) != row_result_sha256(row):
            errors.append("result_sha256 does not match canonical row content")
    return list(dict.fromkeys(errors))


def _sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _triples(values: Iterable[Sequence[Any]], label: str) -> list[tuple[str, str, str]]:
    keys: list[tuple[str, str, str]] = []
    for index, value in enumerate(values):
        if (
            not isinstance(value, Sequence)
            or isinstance(value, str | bytes | bytearray)
            or len(value) != 3
        ):
            raise ValueError(f"{label}[{index}] must be a three-item key")
        key = tuple(str(item) for item in value)
        if any(not item for item in key):
            raise ValueError(f"{label}[{index}] items must be non-empty")
        keys.append(key)
    duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate {label} keys: {duplicates}")
    return sorted(keys)


def _row_bytes(rows: list[Mapping[str, Any]], strict: bool) -> bytes:
    return (
        b"".join(canonical_bytes(row) + b"\n" for row in rows)
        if strict
        else canonical_bytes(rows)
    )


def _merkle(files: list[Mapping[str, Any]]) -> str:
    level = [
        hashlib.sha256(
            str(item["path"]).encode() + b"\0" + bytes.fromhex(str(item["sha256"]))
        ).digest()
        for item in sorted(files, key=lambda item: str(item["path"]))
    ]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256(level[index] + level[index + 1]).digest()
            for index in range(0, len(level), 2)
        ]
    return level[0].hex() if level else sha256_hex(b"")


def build_durable_manifest(
    rows: Iterable[Mapping[str, Any]],
    *,
    expected_keys: Iterable[Sequence[Any]] | None = None,
    schema_version: str = "1.0.0",
    strict: bool = False,
) -> dict[str, Any]:
    selected = list(rows)
    errors = [
        f"row[{index}]: {error}"
        for index, row in enumerate(selected)
        for error in validate_durable_row(row)
    ]
    if errors:
        raise ValueError("invalid durable rows: " + "; ".join(errors))
    keys = [row_key(row) for row in selected]
    observed = sorted(set(keys))
    duplicate = sorted(key for key, count in Counter(keys).items() if count > 1)
    expected = (
        observed if expected_keys is None else _triples(expected_keys, "expected")
    )
    missing = sorted(set(expected) - set(observed))
    unexpected = sorted(set(observed) - set(expected))
    if strict and (missing or unexpected or duplicate):
        raise ValueError(
            f"durable key closure failed: missing={missing}, "
            f"unexpected={unexpected}, duplicate={duplicate}"
        )
    data = _row_bytes(selected, strict)
    digest = sha256_hex(data)
    files = [{"path": ROWS_NAME, "bytes": len(data), "sha256": digest}]
    base = {
        "schema_version": schema_version,
        "contains_raw_dataset": False,
        "row_count": len(selected),
        "expected": [list(key) for key in expected],
        "observed": [list(key) for key in observed],
        "missing": [list(key) for key in missing],
        "unexpected": [list(key) for key in unexpected],
        "mismatch": [],
        "duplicate": [list(key) for key in duplicate],
        "rows_sha256": digest,
        "files": files,
        "merkle_root_sha256": _merkle(files),
    }
    return {**base, "manifest_sha256": sha256_hex(canonical_bytes(base))}


def _declared(manifest: Mapping[str, Any], name: str, errors: list[str]):
    value = manifest.get(name)
    if not isinstance(value, list):
        errors.append(f"{name} must be array")
        return []
    keys: list[tuple[str, str, str]] = []
    for index, item in enumerate(value):
        if (
            not isinstance(item, list)
            or len(item) != 3
            or not all(isinstance(part, str) and part for part in item)
        ):
            errors.append(f"{name}[{index}] must contain exactly three strings")
        else:
            keys.append(tuple(item))
    if keys != sorted(keys):
        errors.append(f"{name} must be sorted")
    if len(keys) != len(set(keys)):
        errors.append(f"{name} contains duplicate keys")
    return keys


def validate_durable_manifest(
    manifest: Any,
    rows: Iterable[Mapping[str, Any]] | None = None,
    *,
    strict: bool = False,
    expected_keys: Iterable[Sequence[Any]] | None = None,
) -> list[str]:
    if not isinstance(manifest, Mapping):
        return ["manifest must be object"]
    errors: list[str] = []
    required = MANIFEST_FIELDS if strict else LEGACY_REQUIRED_FIELDS
    errors += [
        f"missing manifest field: {key}" for key in sorted(required - set(manifest))
    ]
    errors += [
        f"unexpected manifest field: {key}"
        for key in sorted(set(manifest) - MANIFEST_FIELDS)
    ]
    if manifest.get("contains_raw_dataset") is not False:
        errors.append("contains_raw_dataset must be false")
    count = manifest.get("row_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        errors.append("row_count must be non-negative integer")
    errors.extend(walk_forbidden(manifest))
    expected = _declared(manifest, "expected", errors)
    if expected_keys is not None:
        try:
            frozen_expected = _triples(expected_keys, "expected_keys")
        except ValueError as exc:
            errors.append(str(exc))
            frozen_expected = []
        if expected != frozen_expected:
            errors.append("manifest expected keys mismatch supplied expected_keys")
    observed = _declared(manifest, "observed", errors)
    missing = _declared(manifest, "missing", errors)
    unexpected = _declared(manifest, "unexpected", errors)
    mismatch = _declared(manifest, "mismatch", errors)
    duplicate = (
        _declared(manifest, "duplicate", errors) if "duplicate" in manifest else []
    )
    if missing != sorted(set(expected) - set(observed)):
        errors.append("manifest missing keys mismatch expected/observed closure")
    if unexpected != sorted(set(observed) - set(expected)):
        errors.append("manifest unexpected keys mismatch expected/observed closure")
    if missing or unexpected or mismatch or duplicate:
        errors.append("durable key closure is not exact")
    data = None
    if rows is not None:
        selected = list(rows)
        errors.extend(
            f"row[{index}]: {error}"
            for index, row in enumerate(selected)
            for error in validate_durable_row(row)
        )
        keys = [row_key(row) for row in selected]
        actual_duplicate = sorted(key for key, n in Counter(keys).items() if n > 1)
        if observed != sorted(set(keys)):
            errors.append("observed keys mismatch rows")
        if duplicate != actual_duplicate:
            errors.append("duplicate keys mismatch rows")
        if count != len(selected):
            errors.append("row_count mismatch")
        data = _row_bytes(selected, strict)
        if manifest.get("rows_sha256") != sha256_hex(data):
            errors.append("rows_sha256 mismatch")
    elif not _sha(manifest.get("rows_sha256")):
        errors.append("rows_sha256 must be lowercase SHA-256")
    files = manifest.get("files", [])
    valid_files = isinstance(files, list)
    for index, item in enumerate(files if valid_files else []):
        if not isinstance(item, Mapping) or set(item) != {"path", "bytes", "sha256"}:
            errors.append(f"files[{index}] fields are not closed")
            valid_files = False
            continue
        path = item["path"]
        posix = PurePosixPath(path) if isinstance(path, str) else None
        if (
            posix is None
            or not path
            or posix.is_absolute()
            or path != posix.as_posix()
            or ".." in posix.parts
            or "\\" in path
        ):
            errors.append(f"files[{index}].path is unsafe")
        if (
            not isinstance(item["bytes"], int)
            or isinstance(item["bytes"], bool)
            or item["bytes"] < 0
        ):
            errors.append(f"files[{index}].bytes is invalid")
        if not _sha(item["sha256"]):
            errors.append(f"files[{index}].sha256 is invalid")
    if strict and not isinstance(files, list):
        errors.append("files must be array")
    if data is not None and files != [
        {"path": ROWS_NAME, "bytes": len(data), "sha256": sha256_hex(data)}
    ]:
        errors.append("per-file metadata mismatch")
    if "merkle_root_sha256" in manifest and (
        not _sha(manifest["merkle_root_sha256"])
        or (valid_files and manifest["merkle_root_sha256"] != _merkle(files))
    ):
        errors.append("merkle_root_sha256 mismatch")
    if "manifest_sha256" in manifest:
        base = dict(manifest)
        base.pop("manifest_sha256", None)
        if not _sha(manifest["manifest_sha256"]) or manifest[
            "manifest_sha256"
        ] != sha256_hex(canonical_bytes(base)):
            errors.append("manifest_sha256 mismatch")
    return list(dict.fromkeys(errors))


def write_durable_manifest(
    path: str | Path,
    rows: Iterable[Mapping[str, Any]],
    *,
    expected_keys=None,
    strict: bool = False,
) -> dict[str, Any]:
    manifest = build_durable_manifest(
        list(rows), expected_keys=expected_keys, strict=strict
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(manifest) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return manifest


build_manifest = build_durable_manifest
validate_manifest = validate_durable_manifest
write_manifest = write_durable_manifest
