"""Seal and validate closed, durable-result-only packages."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .contracts.canonical_json import canonical_bytes, sha256_hex
from .durable_results import row_key, validate_durable_row, walk_forbidden

ROWS_NAME = "durable_rows.jsonl"
MANIFEST_NAME = "durable_result_manifest.json"
PACKAGE_FILES = frozenset({ROWS_NAME, MANIFEST_NAME})
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
FORBIDDEN_TOKENS = ("raw", "truth", "payload", "sidecar")
ALLOWED_SOURCE_SUFFIXES = frozenset({".json", ".jsonl"})


class _DuplicateJsonKey(ValueError):
    """Raised for duplicate keys in a JSON object."""


def _object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _parse_json(text: str) -> Any:
    return json.loads(
        text,
        object_pairs_hook=_object_from_pairs,
        parse_constant=_reject_constant,
    )


def _sensitive_errors(value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                errors.append(f"{path}: non-string object key")
                continue
            folded = key.casefold()
            compact = "".join(char for char in folded if char.isalnum())
            if folded != "contains_raw_dataset" and any(
                token in folded or token in compact for token in FORBIDDEN_TOKENS
            ):
                errors.append(f"{path}.{key}: forbidden durable field")
            errors.extend(_sensitive_errors(child, f"{path}.{key}"))
    elif isinstance(value, list | tuple):
        for index, child in enumerate(value):
            errors.extend(_sensitive_errors(child, f"{path}[{index}]"))
    elif isinstance(value, bytes | bytearray | memoryview):
        errors.append(f"{path}: bytes are forbidden")
    elif isinstance(value, str):
        folded = value.casefold()
        compact = "".join(char for char in folded if char.isalnum())
        if not any(token in folded or token in compact for token in FORBIDDEN_TOKENS):
            return errors

        errors.append(f"{path}: forbidden durable string")
    return errors


def _row_errors(row: Any) -> list[str]:
    errors = list(validate_durable_row(row))
    errors.extend(walk_forbidden(row))
    errors.extend(_sensitive_errors(row))
    return list(dict.fromkeys(errors))


def _normalise_key(value: Any, label: str) -> tuple[str, str, str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, str | bytes | bytearray)
        or len(value) != 3
    ):
        raise ValueError(f"{label} must be a three-item key")
    key = tuple(str(item) for item in value)
    if any(not item for item in key):
        raise ValueError(f"{label} items must be non-empty")
    return key


def _normalise_expected(
    expected_keys: Iterable[Sequence[Any]],
) -> list[tuple[str, str, str]]:
    keys = [
        _normalise_key(value, f"expected[{index}]")
        for index, value in enumerate(expected_keys)
    ]
    duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate expected keys: {duplicates}")
    return sorted(keys)


def _validate_rows(rows: Iterable[Any]) -> list[Mapping[str, Any]]:
    selected = list(rows)
    errors = [
        f"row[{index}]: {error}"
        for index, row in enumerate(selected)
        for error in _row_errors(row)
    ]
    if errors:
        raise ValueError("invalid durable rows: " + "; ".join(errors))
    return [row for row in selected if isinstance(row, Mapping)]


def _canonical_rows(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_bytes(row) + b"\n" for row in rows)


def _sha256_bytes(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _merkle_root(files: Iterable[Mapping[str, Any]]) -> str:
    ordered = sorted(files, key=lambda item: str(item["path"]))
    level = [
        _sha256_bytes(
            str(item["path"]).encode("utf-8")
            + b"\0"
            + bytes.fromhex(str(item["sha256"]))
        )
        for item in ordered
    ]
    if not level:
        return sha256_hex(b"")
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            _sha256_bytes(level[index] + level[index + 1])
            for index in range(0, len(level), 2)
        ]
    return level[0].hex()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def _safe_text(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if b"\0" in data:
        raise ValueError(f"{path}: NUL/binary content is forbidden")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path}: content is not UTF-8") from exc


def _documents_from_source(path: Path) -> list[Any]:
    text = _safe_text(path)
    if path.suffix.casefold() == ".json":
        try:
            return [_parse_json(text)]
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    documents: list[Any] = []
    if not text:
        raise ValueError(f"{path}: empty JSONL is not allowed")
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            raise ValueError(f"{path}:{line_number}: blank JSONL row")
        try:
            documents.append(_parse_json(line))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return documents


def _assert_no_symlink_components(
    path: Path, role: str, *, allow_missing_leaf: bool = True
) -> Path:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    parts = absolute.parts[1:]
    for index, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{role} path contains symbolic-link component: {current}")
        if current.exists() and not current.is_dir() and index < len(parts) - 1:
            raise ValueError(f"{role} ancestor is not a directory: {current}")
    resolved = absolute.resolve(strict=False)
    root = Path(os.path.abspath(absolute.parent if not absolute.exists() else absolute))
    try:
        resolved.relative_to(root.resolve(strict=False))
    except ValueError:
        raise ValueError(f"{role} resolved path escapes intended root") from None
    return absolute


def _load_source_rows(source: Path) -> list[Mapping[str, Any]]:
    _assert_no_symlink_components(source, "source")
    if not source.is_dir():
        raise ValueError(f"source is not a directory: {source}")
    rows: list[Any] = []
    for path in sorted(source.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(source).as_posix()
        try:
            path.resolve(strict=True).relative_to(source.resolve(strict=True))
        except ValueError:
            raise ValueError(f"{relative}: resolved path escapes source root") from None
        if path.is_symlink():
            raise ValueError(f"{relative}: symbolic links are forbidden")
        if any(token in relative.casefold() for token in FORBIDDEN_TOKENS):
            raise ValueError(f"{relative}: forbidden package filename")
        if path.suffix.casefold() not in ALLOWED_SOURCE_SUFFIXES:
            raise ValueError(f"{relative}: unsupported package file type")
        rows.extend(_documents_from_source(path))
    if not rows:
        raise ValueError("source contains no durable rows")
    return _validate_rows(rows)


def _resolve_seal_input(
    source: Any,
    destination: Any,
    explicit_rows: Iterable[Any] | None,
) -> tuple[Path, list[Mapping[str, Any]]]:
    if explicit_rows is not None:
        if destination is not None:
            raise TypeError("destination and rows cannot both be supplied")
        return Path(source), _validate_rows(explicit_rows)
    if destination is None:
        raise TypeError("destination or rows is required")
    source_is_path = isinstance(source, str | os.PathLike)
    destination_is_path = isinstance(destination, str | os.PathLike)
    if source_is_path and destination_is_path:
        return Path(destination), _load_source_rows(Path(source))
    if source_is_path:
        return Path(source), _validate_rows(destination)
    if destination_is_path:
        return Path(destination), _validate_rows(source)
    raise TypeError("one positional argument must identify the package directory")


def _ensure_writable_package_root(root: Path) -> None:
    if root.exists() and not root.is_dir():
        raise ValueError(f"package path is not a directory: {root}")
    if not root.exists():
        root.mkdir(parents=True)
        return
    unexpected = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.relative_to(root).as_posix() not in PACKAGE_FILES
    ]
    if unexpected:
        raise ValueError(f"package directory is not closed: {sorted(unexpected)}")


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_tree(path: Path) -> None:
    for child in sorted(
        path.rglob("*"), key=lambda item: len(item.parts), reverse=True
    ):
        if child.is_dir() and not child.is_symlink():
            child.rmdir()
        else:
            child.unlink(missing_ok=True)
    path.rmdir()


def seal_durable_package(
    source: Any,
    destination: Any = None,
    *,
    rows: Iterable[Any] | None = None,
    expected_keys: Iterable[Sequence[Any]] | None = None,
    schema_version: str = "1.0.0",
) -> dict[str, Any]:
    """Seal validated rows into a deterministic two-file durable package.

    ``source`` and ``destination`` may be source/destination directories.  For
    direct use, pass ``(package_directory, rows)`` or ``rows=...``.
    """

    root, selected = _resolve_seal_input(source, destination, rows)
    _assert_no_symlink_components(root, "destination")
    selected.sort(key=row_key)
    observed_keys = [row_key(row) for row in selected]
    duplicate_keys = sorted(
        key for key, count in Counter(observed_keys).items() if count > 1
    )
    if duplicate_keys:
        raise ValueError(f"duplicate durable row keys: {duplicate_keys}")
    observed = sorted(observed_keys)
    if expected_keys is None:
        raise ValueError("expected_keys is required for durable package sealing")
    expected = _normalise_expected(expected_keys)
    missing = sorted(set(expected) - set(observed))
    unexpected = sorted(set(observed) - set(expected))
    if missing or unexpected:
        raise ValueError(
            f"durable key closure failed: missing={missing}, unexpected={unexpected}"
        )
    if not isinstance(schema_version, str) or not schema_version:
        raise ValueError("schema_version must be a non-empty string")

    rows_bytes = _canonical_rows(selected)
    rows_hash = sha256_hex(rows_bytes)
    files = [{"path": ROWS_NAME, "bytes": len(rows_bytes), "sha256": rows_hash}]
    manifest_base: dict[str, Any] = {
        "schema_version": schema_version,
        "contains_raw_dataset": False,
        "row_count": len(selected),
        "expected": [list(key) for key in expected],
        "observed": [list(key) for key in observed],
        "missing": [],
        "unexpected": [],
        "mismatch": [],
        "duplicate": [],
        "rows_sha256": rows_hash,
        "files": files,
        "merkle_root_sha256": _merkle_root(files),
    }
    manifest = {
        **manifest_base,
        "manifest_sha256": sha256_hex(canonical_bytes(manifest_base)),
    }
    manifest_errors = _sensitive_errors(manifest)
    if manifest_errors:
        raise ValueError("unsafe durable manifest: " + "; ".join(manifest_errors))

    _ensure_writable_package_root(root)
    parent = root.parent
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{root.name}.stage-", dir=parent))
    backup = parent / f".{root.name}.rollback-{os.getpid()}"
    backup_created = False
    try:
        _atomic_write(stage / ROWS_NAME, rows_bytes)
        _atomic_write(stage / MANIFEST_NAME, canonical_bytes(manifest) + b"\n")
        errors = validate_durable_package(stage, expected_keys=expected)
        if errors:
            raise RuntimeError("staged package failed readback: " + "; ".join(errors))
        _fsync_directory(stage)
        if root.exists():
            if backup.exists():
                raise RuntimeError(f"rollback path already exists: {backup}")
            os.replace(root, backup)
            backup_created = True
        try:
            os.replace(stage, root)
        except BaseException:
            if backup_created and backup.exists() and not root.exists():
                os.replace(backup, root)
                backup_created = False
            raise
        try:
            _fsync_directory(parent)
        except BaseException:
            # The directory entry is not durable, so restore the old package
            # before exposing the publication failure to the caller.
            if root.exists():
                _remove_tree(root)
            if backup_created and backup.exists():
                os.replace(backup, root)
                backup_created = False
            raise
        if backup_created and backup.exists():
            _remove_tree(backup)
            backup_created = False
        return manifest
    except BaseException:
        if stage.exists():
            _remove_tree(stage)
        if backup_created and backup.exists() and not root.exists():
            os.replace(backup, root)
        raise


def _package_shape_errors(root: Path) -> list[str]:
    try:
        _assert_no_symlink_components(root, "package")
    except ValueError as exc:
        return [str(exc)]
    if not root.is_dir():
        return [f"package is not a directory: {root}"]
    errors: list[str] = []
    observed: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        observed.add(relative)
        if path.is_symlink():
            errors.append(f"{relative}: symbolic links are forbidden")
        if any(token in relative.casefold() for token in FORBIDDEN_TOKENS):
            errors.append(f"{relative}: forbidden package filename")
        if path.is_file() and path.suffix.casefold() not in ALLOWED_SOURCE_SUFFIXES:
            errors.append(f"{relative}: unsupported package file type")
    missing = sorted(PACKAGE_FILES - observed)
    unexpected = sorted(observed - PACKAGE_FILES)
    errors.extend(f"missing package file: {name}" for name in missing)
    errors.extend(f"unexpected package entry: {name}" for name in unexpected)
    return errors


def _read_rows(path: Path) -> tuple[list[Any], bytes, list[str]]:
    errors: list[str] = []
    try:
        data = path.read_bytes()
    except OSError as exc:
        return [], b"", [f"{ROWS_NAME}: cannot read: {exc}"]
    if b"\0" in data:
        return [], data, [f"{ROWS_NAME}: NUL/binary content is forbidden"]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [], data, [f"{ROWS_NAME}: content is not UTF-8"]
    rows: list[Any] = []
    if not text:
        return rows, data, errors
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            errors.append(f"{ROWS_NAME}:{line_number}: blank JSONL row")
            continue
        try:
            row = _parse_json(line)
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{ROWS_NAME}:{line_number}: invalid JSON: {exc}")
            continue
        row_errors = _row_errors(row)
        errors.extend(f"{ROWS_NAME}:{line_number}: {error}" for error in row_errors)
        rows.append(row)
    if not errors:
        canonical = _canonical_rows(rows)
        if canonical != data:
            errors.append(f"{ROWS_NAME}: file is not canonical JSONL")
    return rows, data, errors


def _read_manifest(path: Path) -> tuple[Any, bytes, list[str]]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return None, b"", [f"{MANIFEST_NAME}: cannot read: {exc}"]
    if b"\0" in data:
        return None, data, [f"{MANIFEST_NAME}: NUL/binary content is forbidden"]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, data, [f"{MANIFEST_NAME}: content is not UTF-8"]
    try:
        manifest = _parse_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        return None, data, [f"{MANIFEST_NAME}: invalid JSON: {exc}"]
    errors: list[str] = []
    if not isinstance(manifest, Mapping):
        return manifest, data, [f"{MANIFEST_NAME}: manifest must be an object"]
    try:
        if canonical_bytes(manifest) + b"\n" != data:
            errors.append(f"{MANIFEST_NAME}: file is not canonical JSON")
    except ValueError as exc:
        errors.append(f"{MANIFEST_NAME}: not canonical JSON: {exc}")
    return manifest, data, errors


def _manifest_key_list(
    value: Any,
    label: str,
    errors: list[str],
) -> list[tuple[str, str, str]]:
    if not isinstance(value, list):
        errors.append(f"{label} must be an array")
        return []
    keys: list[tuple[str, str, str]] = []
    for index, item in enumerate(value):
        try:
            key = _normalise_key(item, f"{label}[{index}]")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not all(isinstance(part, str) for part in item):
            errors.append(f"{label}[{index}] items must be strings")
        keys.append(key)
    if keys != sorted(keys):
        errors.append(f"{label} must be sorted")
    if len(keys) != len(set(keys)):
        errors.append(f"{label} contains duplicate keys")
    return keys


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def validate_durable_package(
    path: str | os.PathLike[str],
    *,
    expected_keys: Iterable[Sequence[Any]] | None = None,
) -> list[str]:
    """Return all detected package-integrity and durable-content errors."""

    root = Path(path)
    errors = _package_shape_errors(root)
    rows_path = root / ROWS_NAME
    manifest_path = root / MANIFEST_NAME
    rows: list[Any] = []
    rows_bytes = b""
    manifest: Any = None
    if rows_path.is_file() and not rows_path.is_symlink():
        rows, rows_bytes, row_errors = _read_rows(rows_path)
        errors.extend(row_errors)
    if manifest_path.is_file() and not manifest_path.is_symlink():
        manifest, _, manifest_errors = _read_manifest(manifest_path)
        errors.extend(manifest_errors)
    if not isinstance(manifest, Mapping):
        return list(dict.fromkeys(errors))

    missing_fields = sorted(MANIFEST_FIELDS - set(manifest))
    unexpected_fields = sorted(set(manifest) - MANIFEST_FIELDS)
    errors.extend(f"missing manifest field: {key}" for key in missing_fields)
    errors.extend(f"unexpected manifest field: {key}" for key in unexpected_fields)
    errors.extend(_sensitive_errors(manifest))
    if manifest.get("contains_raw_dataset") is not False:
        errors.append("contains_raw_dataset must be false")
    if not isinstance(manifest.get("schema_version"), str) or not manifest.get(
        "schema_version"
    ):
        errors.append("schema_version must be a non-empty string")

    observed_rows = [row for row in rows if isinstance(row, Mapping)]
    observed_keys = sorted(row_key(row) for row in observed_rows)
    duplicate_keys = sorted(
        key for key, count in Counter(observed_keys).items() if count > 1
    )
    manifest_expected = _manifest_key_list(manifest.get("expected"), "expected", errors)
    manifest_observed = _manifest_key_list(manifest.get("observed"), "observed", errors)
    expected = manifest_expected
    if expected_keys is not None:
        try:
            expected = _normalise_expected(expected_keys)
        except ValueError as exc:
            errors.append(str(exc))
            expected = []
        if manifest_expected != expected:
            errors.append("manifest expected keys mismatch requested closure")
    missing = sorted(set(expected) - set(observed_keys))
    unexpected = sorted(set(observed_keys) - set(expected))
    if manifest_observed != observed_keys:
        errors.append("manifest observed keys mismatch durable rows")
    for field, computed in (
        ("missing", missing),
        ("unexpected", unexpected),
        ("duplicate", duplicate_keys),
    ):
        declared = _manifest_key_list(manifest.get(field), field, errors)
        if declared != computed:
            errors.append(f"manifest {field} mismatch durable rows")
    if missing or unexpected:
        errors.append("durable key closure is not exact")
    if duplicate_keys:
        errors.append("duplicate durable row keys")
    if manifest.get("mismatch") != []:
        errors.append("manifest mismatch must be empty")
    if manifest.get("row_count") != len(rows):
        errors.append("row_count mismatch")

    rows_hash = sha256_hex(rows_bytes)
    if manifest.get("rows_sha256") != rows_hash:
        errors.append("rows_sha256 mismatch")
    files = [{"path": ROWS_NAME, "bytes": len(rows_bytes), "sha256": rows_hash}]
    if manifest.get("files") != files:
        errors.append("per-file metadata mismatch")
    if manifest.get("merkle_root_sha256") != _merkle_root(files):
        errors.append("merkle_root_sha256 mismatch")
    if not _is_sha256(manifest.get("manifest_sha256")):
        errors.append("manifest_sha256 must be a lowercase SHA-256 digest")
    manifest_base = dict(manifest)
    manifest_base.pop("manifest_sha256", None)
    try:
        manifest_hash = sha256_hex(canonical_bytes(manifest_base))
    except ValueError as exc:
        errors.append(f"manifest cannot be hashed canonically: {exc}")
    else:
        if manifest.get("manifest_sha256") != manifest_hash:
            errors.append("manifest_sha256 mismatch")
    return list(dict.fromkeys(errors))


seal_package = seal_durable_package
validate_package = validate_durable_package
