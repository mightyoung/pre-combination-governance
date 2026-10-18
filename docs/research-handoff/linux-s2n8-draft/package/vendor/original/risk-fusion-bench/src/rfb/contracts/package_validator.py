"""Pure package validation and atomic non-formal receipt commits."""

from __future__ import annotations

import errno
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from uuid import uuid4

from .canonical_json import CanonicalJsonError, canonical_bytes, sha256_hex
from .failure_codes import FailureCode, primary_failure_code
from .schema_versions import (
    CompatibilityRegistry,
    EXACT_COMPATIBILITY,
    parse_semantic_version,
)
from .schemas import (
    EXPECTED_SCHEMA_VERSIONS,
    PENDING_HASH,
    collect_pending_hash_paths,
    manifest_hash_fields,
    validate_schema,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PackageFailure:
    code: FailureCode
    path: str
    message: str


@dataclass(frozen=True)
class PackageValidationResult:
    success: bool
    confirmation_eligible: bool
    primary_code: FailureCode | None
    failures: tuple[PackageFailure, ...]
    receipt_path: str | None = None


BINDING_VERSION_COMPANIONS = {
    "main_sha256": "main_version",
    "S1_sha256": "S1_version",
    "S2_sha256": "S2_version",
    "experiment_sha256": "experiment_version",
    "SafetyArtifactIR_schema_sha256": "SafetyArtifactIR_schema_version",
    "compiler_sha256": "compiler_version",
    "Eventifier_sha256": "Eventifier_version",
    "SetwiseEligibilityGenerator_sha256": "SetwiseEligibilityGenerator_version",
}

REQUIRED_BINDINGS = tuple(manifest_hash_fields())


def _raw_components(path_text: str) -> list[str]:
    return [part for part in re.split(r"[\\/]+", path_text) if part not in ("", ".")]


def _contains_dtest_text(path_text: str) -> bool:
    return any(part.casefold() == "d_test" for part in _raw_components(path_text))


def _diagnostic_key_bytes(key: Any) -> bytes:
    return str(key).encode("utf-8", errors="backslashreplace")


def _diagnostic_key_text(key: Any) -> str:
    return _diagnostic_key_bytes(key).decode("utf-8")


def _path_has_dtest(path: Path) -> bool:
    """Return True when a raw/native/resolved path contains a D_test component."""

    if _contains_dtest_text(str(path)) or any(
        part.casefold() == "d_test" for part in path.parts
    ):
        return True
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return False
    return _contains_dtest_text(str(resolved)) or any(
        part.casefold() == "d_test" for part in resolved.parts
    )


def _is_clean_string(value: Any, *, allow_pending: bool = False) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        return False
    if value == "PENDING_HASH":
        return False
    if value == PENDING_HASH and not allow_pending:
        return False
    return True


def _is_descriptor_hash(value: Any) -> bool:
    return isinstance(value, str) and (
        value == PENDING_HASH or bool(_SHA256_RE.fullmatch(value))
    )


def _path_safety_failure(path_text: str, label: str) -> PackageFailure | None:
    if not isinstance(path_text, str) or not path_text:
        return PackageFailure(
            FailureCode.MANIFEST_SCHEMA_INVALID,
            label,
            "path must be a non-empty relative string",
        )
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in path_text):
        return PackageFailure(
            FailureCode.MANIFEST_SCHEMA_INVALID, label, "path contains lone surrogate"
        )
    if _contains_dtest_text(path_text):
        return PackageFailure(
            FailureCode.D_TEST_FORBIDDEN, label, "path contains D_test component"
        )
    if (
        path_text.startswith(("/", "\\"))
        or PurePosixPath(path_text).is_absolute()
        or PureWindowsPath(path_text).is_absolute()
    ):
        return PackageFailure(
            FailureCode.MANIFEST_SCHEMA_INVALID, label, "absolute paths are forbidden"
        )
    if re.match(r"^[A-Za-z]:", path_text) or path_text.startswith(("\\\\", "//")):
        return PackageFailure(
            FailureCode.MANIFEST_SCHEMA_INVALID,
            label,
            "Windows absolute/UNC paths are forbidden",
        )
    for part in _raw_components(path_text):
        if part == "..":
            return PackageFailure(
                FailureCode.MANIFEST_SCHEMA_INVALID,
                label,
                "path traversal is forbidden",
            )
    return None


def _resolved_path(
    package_root: Path, rel_path: str, label: str
) -> tuple[Path | None, PackageFailure | None]:
    raw_failure = _path_safety_failure(rel_path, label)
    if raw_failure is not None:
        return None, raw_failure
    try:
        root = package_root.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return None, PackageFailure(
            FailureCode.MANIFEST_SCHEMA_INVALID,
            label,
            f"cannot resolve package root: {exc}",
        )
    candidate = root.joinpath(*_raw_components(rel_path))
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return None, PackageFailure(
            FailureCode.MANIFEST_SCHEMA_INVALID, label, f"cannot resolve path: {exc}"
        )
    if any(part.casefold() == "d_test" for part in resolved.parts):
        return None, PackageFailure(
            FailureCode.D_TEST_FORBIDDEN,
            label,
            "resolved path contains D_test component",
        )
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, PackageFailure(
            FailureCode.MANIFEST_SCHEMA_INVALID,
            label,
            "resolved path escapes package root",
        )
    return resolved, None


def _reject_output_path(output: Path, failures: list[PackageFailure]) -> None:
    if _path_has_dtest(output):
        failures.append(
            PackageFailure(
                FailureCode.D_TEST_FORBIDDEN,
                "output_dir",
                "output path contains D_test component",
            )
        )


def _hash_file(path: Path) -> str:
    digest = __import__("hashlib").sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_index(index: Any) -> tuple[list[dict[str, Any]], list[PackageFailure]]:
    failures: list[PackageFailure] = []
    if not isinstance(index, dict):
        return [], [
            PackageFailure(
                FailureCode.MANIFEST_SCHEMA_INVALID, "index", "index must be an object"
            )
        ]
    required = ("schema_version", "release_id", "artifacts")
    allowed = set(required)
    for key in sorted(index, key=_diagnostic_key_bytes):
        if key not in allowed:
            failures.append(
                PackageFailure(
                    FailureCode.MANIFEST_SCHEMA_INVALID,
                    f"index.{_diagnostic_key_text(key)}",
                    "unknown index field",
                )
            )
    for key in required:
        if key not in index:
            failures.append(
                PackageFailure(
                    FailureCode.MANIFEST_SCHEMA_INVALID,
                    f"index.{key}",
                    "missing index field",
                )
            )
    if not _is_clean_string(index.get("schema_version")):
        failures.append(
            PackageFailure(
                FailureCode.MANIFEST_SCHEMA_INVALID,
                "index.schema_version",
                "invalid schema version",
            )
        )
    if not _is_clean_string(index.get("release_id")):
        failures.append(
            PackageFailure(
                FailureCode.MANIFEST_SCHEMA_INVALID,
                "index.release_id",
                "invalid release id",
            )
        )
    artifacts = index.get("artifacts")
    if not isinstance(artifacts, list) or not all(
        isinstance(item, dict) for item in artifacts
    ):
        failures.append(
            PackageFailure(
                FailureCode.MANIFEST_SCHEMA_INVALID,
                "index.artifacts",
                "invalid artifacts index",
            )
        )
        return [], failures
    descriptor_allowed = {
        "artifact_id",
        "binding_key",
        "path",
        "sha256",
        "artifact_version",
        "schema_name",
        "schema_version",
    }
    for idx, artifact in enumerate(artifacts):
        base = f"index.artifacts[{idx}]"
        for key in sorted(artifact, key=_diagnostic_key_bytes):
            if key not in descriptor_allowed:
                failures.append(
                    PackageFailure(
                        FailureCode.MANIFEST_SCHEMA_INVALID,
                        f"{base}.{_diagnostic_key_text(key)}",
                        "unknown descriptor field",
                    )
                )
        for key in ("artifact_id", "binding_key", "path", "sha256"):
            if key == "sha256":
                if not _is_descriptor_hash(artifact.get(key)):
                    failures.append(
                        PackageFailure(
                            FailureCode.MANIFEST_SCHEMA_INVALID,
                            f"{base}.{key}",
                            "invalid descriptor sha256",
                        )
                    )
                continue
            if not _is_clean_string(artifact.get(key)):
                failures.append(
                    PackageFailure(
                        FailureCode.MANIFEST_SCHEMA_INVALID,
                        f"{base}.{key}",
                        "missing/invalid descriptor field",
                    )
                )
        has_schema_name = "schema_name" in artifact
        has_schema_version = "schema_version" in artifact
        if has_schema_name != has_schema_version:
            failures.append(
                PackageFailure(
                    FailureCode.MANIFEST_SCHEMA_INVALID,
                    base,
                    "schema_name/schema_version must appear as a pair",
                )
            )
        if "artifact_version" in artifact and not _is_clean_string(
            artifact.get("artifact_version")
        ):
            failures.append(
                PackageFailure(
                    FailureCode.MANIFEST_SCHEMA_INVALID,
                    f"{base}.artifact_version",
                    "invalid artifact version",
                )
            )
        if "schema_name" in artifact and not _is_clean_string(
            artifact.get("schema_name")
        ):
            failures.append(
                PackageFailure(
                    FailureCode.MANIFEST_SCHEMA_INVALID,
                    f"{base}.schema_name",
                    "invalid schema name",
                )
            )
        if "schema_version" in artifact and not _is_clean_string(
            artifact.get("schema_version")
        ):
            failures.append(
                PackageFailure(
                    FailureCode.MANIFEST_SCHEMA_INVALID,
                    f"{base}.schema_version",
                    "invalid schema version",
                )
            )
    return artifacts, failures


def _schema_version_failures(
    artifacts: list[dict[str, Any]], registry: CompatibilityRegistry
) -> list[PackageFailure]:
    failures: list[PackageFailure] = []
    for idx, artifact in enumerate(artifacts):
        if "schema_name" not in artifact:
            continue
        schema_name = artifact.get("schema_name")
        schema_version = artifact.get("schema_version")
        path = f"index.artifacts[{idx}].schema_version"
        if (
            not isinstance(schema_name, str)
            or schema_name not in EXPECTED_SCHEMA_VERSIONS
        ):
            failures.append(
                PackageFailure(
                    FailureCode.SCHEMA_INCOMPATIBLE, path, "unknown artifact schema"
                )
            )
            continue
        try:
            parse_semantic_version(schema_version)
            expected = EXPECTED_SCHEMA_VERSIONS[schema_name]
            if not registry.is_compatible(schema_name, expected, schema_version):
                failures.append(
                    PackageFailure(
                        FailureCode.STALE_VERSION_REFERENCE,
                        path,
                        "unregistered schema version reference",
                    )
                )
        except (TypeError, ValueError):
            failures.append(
                PackageFailure(
                    FailureCode.SCHEMA_INCOMPATIBLE,
                    path,
                    "invalid schema version syntax",
                )
            )
    return failures


def _dependency_failures(
    manifest: dict[str, Any], endpoints: set[str]
) -> list[PackageFailure]:
    failures: list[PackageFailure] = []
    edges = manifest.get("dependency_edges", [])
    if not isinstance(edges, list):
        return [
            PackageFailure(
                FailureCode.MANIFEST_SCHEMA_INVALID,
                "manifest.dependency_edges",
                "dependency_edges must be a list",
            )
        ]
    graph = {endpoint: set() for endpoint in endpoints}
    for idx, edge in enumerate(edges):
        edge_path = f"manifest.dependency_edges[{idx}]"
        if not isinstance(edge, dict):
            failures.append(
                PackageFailure(
                    FailureCode.MANIFEST_SCHEMA_INVALID,
                    edge_path,
                    "dependency edge must be object",
                )
            )
            continue
        src, dst = edge.get("from"), edge.get("to")
        if not isinstance(src, str) or not isinstance(dst, str):
            failures.append(
                PackageFailure(
                    FailureCode.MANIFEST_SCHEMA_INVALID,
                    edge_path,
                    "dependency endpoints must be strings",
                )
            )
            continue
        if src not in endpoints or dst not in endpoints:
            failures.append(
                PackageFailure(
                    FailureCode.MISSING_DEPENDENCY_ENDPOINT,
                    edge_path,
                    "dependency endpoint is absent",
                )
            )
            continue
        graph.setdefault(src, set()).add(dst)

    visited: set[str] = set()
    active: set[str] = set()

    def visit(node: str) -> bool:
        if node in active:
            return True
        if node in visited:
            return False
        active.add(node)
        for child in graph.get(node, ()):
            if visit(child):
                return True
        active.remove(node)
        visited.add(node)
        return False

    for endpoint in sorted(graph):
        active.clear()
        if visit(endpoint):
            failures.append(
                PackageFailure(
                    FailureCode.DEPENDENCY_CYCLE,
                    "manifest.dependency_edges",
                    "cycle detected",
                )
            )
            break
    return failures


def _cleanup_empty_new_parents(parent: Path, stop_at: Path) -> None:
    current = parent
    try:
        stop = stop_at.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return
    while True:
        try:
            current_resolved = current.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            return
        try:
            if current_resolved == stop:
                return
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _write_receipt_staging(staging: Path, receipt: dict[str, Any]) -> None:
    staging.mkdir()
    (staging / "validation_receipt.json").write_bytes(canonical_bytes(receipt))


def _cleanup_owned_staging(staging: Path | None) -> None:
    if staging is not None and staging.exists():
        shutil.rmtree(staging, ignore_errors=True)


def _commit_receipt(output_dir: Path, receipt: dict[str, Any]) -> str | PackageFailure:
    if output_dir.exists():
        return PackageFailure(
            FailureCode.OUTPUT_ALREADY_EXISTS,
            str(output_dir),
            "target output already exists",
        )
    parent = output_dir.parent
    existing_ancestor = parent
    while not existing_ancestor.exists():
        existing_ancestor = existing_ancestor.parent
    staging: Path | None = None
    claimed_output = False
    try:
        parent.mkdir(parents=True, exist_ok=True)
        staging = parent / f".{output_dir.name}.staging-{os.getpid()}-{uuid4().hex}"
        _write_receipt_staging(staging, receipt)
        try:
            output_dir.mkdir()
            claimed_output = True
        except OSError as exc:
            _cleanup_owned_staging(staging)
            _cleanup_empty_new_parents(parent, existing_ancestor)
            if exc.errno in (errno.EEXIST, errno.ENOTEMPTY) or output_dir.exists():
                return PackageFailure(
                    FailureCode.OUTPUT_ALREADY_EXISTS,
                    str(output_dir),
                    "target created concurrently",
                )
            return PackageFailure(
                FailureCode.PACKAGE_CONSISTENCY_INVALID,
                str(output_dir),
                f"receipt commit failed: {exc}",
            )
        (staging / "validation_receipt.json").replace(
            output_dir / "validation_receipt.json"
        )
        try:
            staging.rmdir()
        except OSError:
            _cleanup_owned_staging(staging)
        return str(output_dir / "validation_receipt.json")
    except OSError as exc:
        failure = PackageFailure(
            FailureCode.PACKAGE_CONSISTENCY_INVALID,
            str(output_dir),
            f"receipt commit failed: {exc}",
        )
        _cleanup_owned_staging(staging)
        if claimed_output:
            try:
                output_dir.rmdir()
            except OSError:
                pass
        _cleanup_empty_new_parents(parent, existing_ancestor)
        return failure
    except Exception as exc:  # pragma: no cover - exercised by injected tests
        _cleanup_owned_staging(staging)
        if claimed_output:
            try:
                output_dir.rmdir()
            except OSError:
                pass
        _cleanup_empty_new_parents(parent, existing_ancestor)
        return PackageFailure(
            FailureCode.PACKAGE_CONSISTENCY_INVALID,
            str(output_dir),
            f"receipt commit failed: {exc}",
        )


def validate_and_commit_package(
    *,
    package_root: Path | str,
    manifest: dict[str, Any],
    index: dict[str, Any],
    output_dir: Path | str | None = None,
    mode: str = "design",
    compatibility_registry: CompatibilityRegistry = EXACT_COMPATIBILITY,
) -> PackageValidationResult:
    """Validate a package and optionally commit a non-formal receipt."""

    package_root = Path(package_root)
    output = Path(output_dir) if output_dir is not None else None
    failures: list[PackageFailure] = []
    if _path_has_dtest(package_root):
        failures.append(
            PackageFailure(
                FailureCode.D_TEST_FORBIDDEN,
                "package_root",
                "package root contains D_test component",
            )
        )
    if output is not None:
        _reject_output_path(output, failures)
    if failures:
        return _result(False, False, failures)

    if mode not in {"design", "confirmation", "test"}:
        return _result(
            False,
            False,
            [
                PackageFailure(
                    FailureCode.MANIFEST_SCHEMA_INVALID,
                    "mode",
                    "mode must be design, confirmation, or test",
                )
            ],
        )
    if not isinstance(manifest, dict):
        return _result(
            False,
            False,
            [
                PackageFailure(
                    FailureCode.MANIFEST_SCHEMA_INVALID,
                    "manifest",
                    "manifest must be an object",
                )
            ],
        )
    if not isinstance(index, dict):
        return _result(
            False,
            False,
            [
                PackageFailure(
                    FailureCode.MANIFEST_SCHEMA_INVALID,
                    "index",
                    "index must be an object",
                )
            ],
        )

    schema_result = validate_schema("NormativeReleaseManifest", manifest)
    if not schema_result.valid:
        failures.extend(
            PackageFailure(error.code, error.path, error.message)
            for error in schema_result.errors
        )

    artifacts, index_failures = _check_index(index)
    failures.extend(index_failures)
    try:
        canonical_bytes(manifest)
        canonical_bytes(index)
    except CanonicalJsonError as exc:
        failures.append(
            PackageFailure(
                FailureCode.MANIFEST_SCHEMA_INVALID, "canonical_json", str(exc)
            )
        )
    try:
        if not compatibility_registry.is_compatible(
            "PackageIndex", "1.0.0", index.get("schema_version")
        ):
            failures.append(
                PackageFailure(
                    FailureCode.SCHEMA_INCOMPATIBLE,
                    "index.schema_version",
                    "index schema incompatible",
                )
            )
        if not compatibility_registry.is_compatible(
            "NormativeReleaseManifest",
            EXPECTED_SCHEMA_VERSIONS["NormativeReleaseManifest"],
            manifest.get("schema_version"),
        ):
            failures.append(
                PackageFailure(
                    FailureCode.SCHEMA_INCOMPATIBLE,
                    "manifest.schema_version",
                    "manifest schema incompatible",
                )
            )
    except (TypeError, ValueError):
        failures.append(
            PackageFailure(
                FailureCode.SCHEMA_INCOMPATIBLE,
                "index.schema_version",
                "invalid manifest/index schema version",
            )
        )

    if isinstance(index, dict) and index.get("release_id") != manifest.get(
        "release_id"
    ):
        failures.append(
            PackageFailure(
                FailureCode.PACKAGE_CONSISTENCY_INVALID,
                "index.release_id",
                "release_id mismatch",
            )
        )

    binding_to_descriptors: dict[str, list[tuple[int, dict[str, Any]]]] = {
        key: [] for key in REQUIRED_BINDINGS
    }
    artifact_ids: set[str] = set()
    endpoints: set[str] = set()
    safe_descriptor_paths: list[tuple[int, dict[str, Any], Path]] = []
    release_id = manifest.get("release_id")

    for idx, artifact in enumerate(artifacts):
        base = f"index.artifacts[{idx}]"
        artifact_id = artifact.get("artifact_id")
        binding_key = artifact.get("binding_key")
        if isinstance(artifact_id, str):
            if artifact_id == release_id:
                failures.append(
                    PackageFailure(
                        FailureCode.PACKAGE_CONSISTENCY_INVALID,
                        f"{base}.artifact_id",
                        "artifact_id collides with release_id",
                    )
                )
            if artifact_id in artifact_ids:
                failures.append(
                    PackageFailure(
                        FailureCode.PACKAGE_CONSISTENCY_INVALID,
                        f"{base}.artifact_id",
                        "duplicate artifact id",
                    )
                )
            artifact_ids.add(artifact_id)
        if isinstance(binding_key, str):
            if binding_key not in REQUIRED_BINDINGS:
                failures.append(
                    PackageFailure(
                        FailureCode.PACKAGE_CONSISTENCY_INVALID,
                        f"{base}.binding_key",
                        "unbound normative binding",
                    )
                )
            else:
                binding_to_descriptors[binding_key].append((idx, artifact))
        rel_path = artifact.get("path")
        if isinstance(rel_path, str):
            resolved, path_failure = _resolved_path(
                package_root, rel_path, f"{base}.path"
            )
            if path_failure is not None:
                failures.append(path_failure)
            elif resolved is not None:
                safe_descriptor_paths.append((idx, artifact, resolved))

    if isinstance(release_id, str):
        endpoints.add(release_id)
    endpoints.update(artifact_ids)

    for binding_key, matches in binding_to_descriptors.items():
        if len(matches) != 1:
            failures.append(
                PackageFailure(
                    FailureCode.PACKAGE_CONSISTENCY_INVALID,
                    f"index.bindings.{binding_key}",
                    "binding must have exactly one descriptor",
                )
            )
            continue
        idx, artifact = matches[0]
        manifest_value = manifest.get(binding_key)
        if artifact.get("sha256") != manifest_value:
            failures.append(
                PackageFailure(
                    FailureCode.PACKAGE_CONSISTENCY_INVALID,
                    f"index.artifacts[{idx}].sha256",
                    "descriptor hash mismatches manifest binding",
                )
            )
        companion = BINDING_VERSION_COMPANIONS.get(binding_key)
        if companion is not None:
            if artifact.get("artifact_version") != manifest.get(companion):
                failures.append(
                    PackageFailure(
                        FailureCode.STALE_VERSION_REFERENCE,
                        f"index.artifacts[{idx}].artifact_version",
                        "artifact version mismatches manifest label",
                    )
                )
        elif "artifact_version" in artifact:
            failures.append(
                PackageFailure(
                    FailureCode.MANIFEST_SCHEMA_INVALID,
                    f"index.artifacts[{idx}].artifact_version",
                    "artifact version not allowed for this binding",
                )
            )

    failures.extend(_schema_version_failures(artifacts, compatibility_registry))
    if schema_result.valid and not any(
        f.code == FailureCode.PACKAGE_CONSISTENCY_INVALID for f in failures
    ):
        failures.extend(_dependency_failures(manifest, endpoints))

    if failures:
        return _result(False, False, failures)

    pending_paths = set(schema_result.pending_hash_paths)
    pending_paths.update(collect_pending_hash_paths(index, "$.index"))

    if failures:
        return _result(
            False, False if mode != "design" else not pending_paths, failures
        )

    path_by_idx = {idx: path for idx, _, path in safe_descriptor_paths}
    for idx, artifact in enumerate(artifacts):
        if idx not in path_by_idx:
            continue
        file_path = path_by_idx[idx]
        expected_hash = artifact.get("sha256")
        if not file_path.is_file():
            failures.append(
                PackageFailure(
                    FailureCode.FILE_MISSING, str(file_path), "artifact file is missing"
                )
            )
            continue
        if expected_hash != PENDING_HASH:
            actual_hash = _hash_file(file_path)
            if actual_hash != expected_hash:
                failures.append(
                    PackageFailure(
                        FailureCode.HASH_MISMATCH,
                        str(file_path),
                        "artifact hash mismatch",
                    )
                )
        if (
            "schema_name" in artifact
            and "schema_version" in artifact
            and artifact.get("schema_name") in EXPECTED_SCHEMA_VERSIONS
        ):
            try:
                content = json.loads(file_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                failures.append(
                    PackageFailure(
                        FailureCode.MANIFEST_SCHEMA_INVALID,
                        str(file_path),
                        f"schema artifact is not parseable JSON: {exc}",
                    )
                )
                continue
            if (
                isinstance(content, dict)
                and content.get("schema_version") != artifact["schema_version"]
            ):
                failures.append(
                    PackageFailure(
                        FailureCode.MANIFEST_SCHEMA_INVALID,
                        str(file_path),
                        "schema artifact content schema_version does not match descriptor",
                    )
                )
            schema_validation = validate_schema(artifact["schema_name"], content)
            pending_paths.update(
                f"index.artifacts[{idx}].content{path[1:] if path.startswith('$') else path}"
                for path in schema_validation.pending_hash_paths
            )
            if not schema_validation.valid:
                failures.append(
                    PackageFailure(
                        FailureCode.MANIFEST_SCHEMA_INVALID,
                        str(file_path),
                        "schema artifact content failed closed schema validation",
                    )
                )

    confirmation_eligible = not pending_paths
    if pending_paths and mode != "design":
        failures.append(
            PackageFailure(
                FailureCode.CONFIRMATION_PENDING_HASH,
                ",".join(sorted(pending_paths)),
                "PENDING-HASH blocks confirmation/test unlock",
            )
        )
    if failures:
        return _result(
            False, False if mode != "design" else confirmation_eligible, failures
        )

    receipt_path: str | None = None
    if output is not None:
        receipt = {
            "receipt_type": "rfb.stage1.non_formal_validation",
            "formal_experiment_artifact": False,
            "confirmation_eligible": confirmation_eligible,
            "manifest_sha256": sha256_hex(canonical_bytes(manifest)),
            "index_sha256": sha256_hex(canonical_bytes(index)),
        }
        committed = _commit_receipt(output, receipt)
        if isinstance(committed, PackageFailure):
            return _result(False, False, [committed])
        receipt_path = committed
    return PackageValidationResult(True, confirmation_eligible, None, (), receipt_path)


def _result(
    success: bool, confirmation_eligible: bool, failures: list[PackageFailure]
) -> PackageValidationResult:
    return PackageValidationResult(
        success=success,
        confirmation_eligible=confirmation_eligible,
        primary_code=primary_failure_code(failure.code for failure in failures),
        failures=tuple(failures),
    )
