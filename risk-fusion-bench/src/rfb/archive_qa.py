"""Fail-closed durable-result Archive A/B copy and readback QA."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from .archive_targets import ArchiveTarget, validate_archive_targets
from .durable_package import PACKAGE_FILES, validate_durable_package
from .durable_results import walk_forbidden

_FORBIDDEN_PATH_TOKENS = ("raw", "truth", "payload", "sidecar")
_ALLOWED_SUFFIXES = frozenset({".json", ".jsonl"})


def _symlink_components(path: Path) -> list[str]:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    found: list[str] = []
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            found.append(str(current))
    return found


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative_name(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("archive path must be a non-empty string")
    normalised = value.replace("\\", "/")
    path = PurePosixPath(normalised)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"unsafe archive path: {value}")
    if path.as_posix() != normalised:
        raise ValueError(f"non-canonical archive path: {value}")
    return normalised


def _reject(rejected: dict[str, list[str]], name: str, message: str) -> None:
    rejected.setdefault(name, []).append(message)


def _package_allowlist(
    allowlist: Iterable[str] | None,
) -> tuple[set[str], dict[str, list[str]]]:
    if allowlist is None:
        return set(PACKAGE_FILES), {}
    if isinstance(allowlist, str | bytes | bytearray):
        raise TypeError("allowlist must be an iterable of relative paths")
    allowed: set[str] = set()
    rejected: dict[str, list[str]] = {}
    for item in allowlist:
        try:
            name = _relative_name(item)
        except ValueError as exc:
            _reject(rejected, str(item), str(exc))
            continue
        if name not in PACKAGE_FILES:
            _reject(
                rejected,
                name,
                "allowlist entry is not a recognized durable package file",
            )
        else:
            allowed.add(name)
    if allowed != set(PACKAGE_FILES):
        missing = sorted(set(PACKAGE_FILES) - allowed)
        _reject(
            rejected,
            "$allowlist",
            f"strict package allowlist is incomplete: {missing}",
        )
    return allowed, rejected


def _source_rejections(
    root: Path,
    allowed: set[str],
) -> dict[str, list[str]]:
    if root.is_symlink():
        return {"$source": ["source package root cannot be a symbolic link"]}
    if not root.is_dir():
        return {"$source": ["source package must be a directory"]}
    ancestor_links = _symlink_components(root)
    if ancestor_links:
        return {
            "$source": [
                f"source path contains symbolic-link component: {item}"
                for item in ancestor_links
            ]
        }
    rejected: dict[str, list[str]] = {}
    observed: set[str] = set()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        observed.add(relative)
        if path.is_symlink():
            _reject(rejected, relative, "symbolic links are forbidden")
            continue
        if path.is_dir():
            _reject(rejected, relative, "unexpected package directory")
            continue
        if not path.is_file():
            _reject(rejected, relative, "unsupported package entry")
            continue
        if relative not in allowed:
            _reject(rejected, relative, "unexpected package file")
        if path.suffix.casefold() not in _ALLOWED_SUFFIXES:
            _reject(rejected, relative, "unsupported package file type")
        if any(token in relative.casefold() for token in _FORBIDDEN_PATH_TOKENS):
            _reject(rejected, relative, "forbidden package path")
    for name in sorted(allowed - observed):
        _reject(rejected, name, "missing package file")
    package_errors = validate_durable_package(root)
    if package_errors:
        rejected["$package"] = list(package_errors)
        for name in sorted(allowed & observed):
            _reject(rejected, name, "sealed durable package validation failed")
    return rejected


def _safe_target_root(target: ArchiveTarget) -> tuple[Path, list[str]]:
    root = Path(target.root)
    errors: list[str] = []
    links = _symlink_components(root)
    if links:
        errors.extend(
            f"target root contains symbolic-link component: {item}" for item in links
        )
    if root.is_symlink():
        errors.append("target root cannot be a symbolic link")
    elif root.exists() and not root.is_dir():
        errors.append("target root must be a directory")
    return root, errors


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError(f"destination is a symbolic link: {destination.name}")
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.partial")
    try:
        with source.open("rb") as input_stream, temporary.open("xb") as output:
            shutil.copyfileobj(input_stream, output, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _strict_expected(expected: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(expected, Mapping):
        raise TypeError("expected must be a mapping of path to SHA-256")
    normalised: dict[str, str] = {}
    for raw_name, digest in expected.items():
        name = _relative_name(raw_name)
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"expected digest for {name} must be lowercase SHA-256")
        normalised[name] = digest
    if set(normalised) != set(PACKAGE_FILES):
        raise ValueError("expected package keys must be exactly PACKAGE_FILES")
    return normalised


def _archive_files(
    root: Path,
) -> tuple[set[str], dict[str, str], dict[str, list[str]]]:
    names: set[str] = set()
    hashes: dict[str, str] = {}
    rejected: dict[str, list[str]] = {}
    if root.is_symlink():
        return names, hashes, {"$target": ["target root is a symbolic link"]}
    if not root.is_dir():
        return names, hashes, rejected
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            names.add(relative)
            _reject(rejected, relative, "symbolic link in archive")
        elif path.is_dir():
            directory_name = f"{relative}/"
            names.add(directory_name)
            _reject(
                rejected,
                directory_name,
                "unexpected archive directory",
            )
        elif path.is_file():
            names.add(relative)
            hashes[relative] = _sha256(path)
            if any(token in relative.casefold() for token in _FORBIDDEN_PATH_TOKENS):
                _reject(rejected, relative, "forbidden archive path")
        else:
            names.add(relative)
            _reject(rejected, relative, "unsupported archive entry")
    return names, hashes, rejected


def archive_qa(
    target: ArchiveTarget,
    expected: Mapping[str, str],
) -> dict[str, Any]:
    expected_hashes = _strict_expected(expected)
    names, observed_hashes, rejected = _archive_files(Path(target.root))
    missing = sorted(set(expected_hashes) - names)
    unexpected = sorted(names - set(expected_hashes))
    mismatch = sorted(
        name
        for name, digest in expected_hashes.items()
        if name in names and observed_hashes.get(name) != digest
    )
    package_errors = validate_durable_package(Path(target.root))
    if package_errors:
        rejected["$package"] = package_errors
    passed = not (missing or unexpected or mismatch or rejected)
    return {
        "target": target.name,
        "expected_count": len(expected_hashes),
        "observed_count": len(names),
        "missing": missing,
        "unexpected": unexpected,
        "mismatch": mismatch,
        "rejected": rejected,
        "observed_sha256": observed_hashes,
        "local_live_gate_passed": False,
        "pass": passed,
    }


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


def _best_effort_remove_tree(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    try:
        _remove_tree(path)
    except Exception:
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        except Exception:
            pass


def _best_effort_fsync_directory(path: Path) -> None:
    try:
        _fsync_directory(path)
    except Exception:
        pass


def _compensate_publish(
    *,
    target_root: Path,
    backup: Path,
    stage: Path,
    parent: Path,
    old_root_present: bool,
    backup_moved: bool,
    new_published: bool,
) -> None:
    if new_published:
        _best_effort_remove_tree(target_root)
    if backup_moved and backup.exists() and not target_root.exists():
        try:
            os.replace(backup, target_root)
        except Exception:
            pass
    if not old_root_present:
        _best_effort_remove_tree(target_root)
    _best_effort_remove_tree(stage)
    _best_effort_remove_tree(backup)
    _best_effort_fsync_directory(parent)


def copy_sealed_package(
    source: str | Path,
    target: ArchiveTarget,
    *,
    allowlist: Iterable[str] | None = None,
) -> dict[str, Any]:
    target_errors = target.validate()
    if target_errors:
        raise ValueError("; ".join(target_errors))
    allowed, rejected = _package_allowlist(allowlist)
    source_root = Path(source)
    for name, messages in _source_rejections(source_root, allowed).items():
        rejected.setdefault(name, []).extend(messages)
    target_root, root_errors = _safe_target_root(target)
    if root_errors:
        rejected["$target"] = root_errors
    if rejected:
        return {
            "target": target.name,
            "files": [],
            "rejected": rejected,
            "local_live_gate_passed": False,
        }

    parent = target_root.parent
    parent.mkdir(parents=True, exist_ok=True)
    import tempfile

    stage = Path(tempfile.mkdtemp(prefix=f".{target_root.name}.stage-", dir=parent))
    backup = parent / f".{target_root.name}.rollback-{uuid.uuid4().hex}"
    copied: list[str] = []
    old_root_present = target_root.exists()
    backup_moved = False
    new_published = False
    expected = {name: _sha256(source_root / name) for name in sorted(PACKAGE_FILES)}
    try:
        for name in sorted(PACKAGE_FILES):
            _atomic_copy(source_root / name, stage / name)
            copied.append(name)
        package_errors = validate_durable_package(stage)
        if package_errors:
            raise ValueError(
                "staged durable package validation failed: " + "; ".join(package_errors)
            )
        _fsync_directory(stage)
        if target_root.exists():
            if backup.exists():
                raise RuntimeError(f"rollback path already exists: {backup}")
            os.replace(target_root, backup)
            backup_moved = True
        try:
            os.replace(stage, target_root)
        except BaseException:
            raise
        new_published = True
        _fsync_directory(parent)
        readback = archive_qa(target, expected)
        if not readback["pass"]:
            raise ValueError("archive list/readback verification failed")
        if backup.exists():
            _remove_tree(backup)
        return {
            "target": target.name,
            "files": copied,
            "expected_sha256": expected,
            "readback": readback,
            "rejected": {},
            "local_live_gate_passed": False,
        }
    except (OSError, ValueError, RuntimeError) as exc:
        rejected["$copy"] = [str(exc)]
        _compensate_publish(
            target_root=target_root,
            backup=backup,
            stage=stage,
            parent=parent,
            old_root_present=old_root_present,
            backup_moved=backup_moved,
            new_published=new_published,
        )
        return {
            "target": target.name,
            "files": [],
            "rejected": rejected,
            "local_live_gate_passed": False,
        }


def _legacy_json_errors(path: Path) -> list[str]:
    if path.suffix.casefold() not in _ALLOWED_SUFFIXES:
        return ["legacy archive accepts only JSON or JSONL"]
    try:
        text = path.read_text(encoding="utf-8")
        documents = (
            [json.loads(line) for line in text.splitlines() if line.strip()]
            if path.suffix.casefold() == ".jsonl"
            else [json.loads(text)]
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"invalid UTF-8/JSON durable artifact: {exc}"]
    errors: list[str] = []
    for index, document in enumerate(documents):
        errors.extend(
            f"document[{index}]: {error}" for error in walk_forbidden(document)
        )
    return list(dict.fromkeys(errors))


def copy_durable_only(
    source: str | Path,
    target: ArchiveTarget,
    *,
    allowlist: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Strict compatibility alias; legacy arbitrary-file copying is forbidden."""

    return copy_sealed_package(source, target, allowlist=allowlist)


def _nonempty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Mapping, list, tuple)):
        return bool(value)
    return value is not None


def _live_evidence_complete(
    target: ArchiveTarget,
    expected: Mapping[str, str],
    observed: Mapping[str, str],
) -> bool:
    evidence = target.live_evidence
    if not isinstance(evidence, Mapping):
        return False
    if (
        not isinstance(evidence.get("verified_at"), str)
        or not evidence["verified_at"].strip()
    ):
        return False
    storage = evidence.get("storage_identity")
    if not isinstance(storage, str) or not storage.strip():
        return False
    receipt = evidence.get("readback_receipt")
    if not isinstance(receipt, Mapping):
        return False
    identity = receipt.get("target_identity")
    if identity not in {target.name, str(Path(target.root).resolve(strict=False))}:
        return False
    try:
        receipt_expected = _strict_expected(receipt.get("expected_sha256"))
        receipt_observed = _strict_expected(receipt.get("observed_sha256"))
    except (TypeError, ValueError):
        return False
    if receipt_expected != dict(expected) or receipt_observed != dict(observed):
        return False
    if receipt.get("storage_identity") != storage:
        return False
    proof = evidence.get("operational_proof")
    if not isinstance(proof, Mapping) or proof.get("verified") is not True:
        return False
    return (
        proof.get("immutable") is target.immutable
        and proof.get("append_only") is target.append_only
    )


def _independence_marker(evidence: Mapping[str, Any], key: str) -> bool:
    if evidence.get(key) is True or evidence.get(f"{key}_verified") is True:
        return True
    independent = evidence.get("independent_failure_domain")
    return isinstance(independent, Mapping) and independent.get(key) is True


def _live_archive_pair(
    targets: list[ArchiveTarget],
    expected: Mapping[str, str],
    observed_by_target: Mapping[str, Mapping[str, str]],
) -> bool:
    if not all(
        _live_evidence_complete(
            target, expected, observed_by_target.get(target.name, {})
        )
        for target in targets
    ):
        return False
    identities = {
        str(target.live_evidence["storage_identity"])
        for target in targets
        if target.live_evidence is not None
    }
    if len(identities) != 2:
        return False
    target_b = next(target for target in targets if target.name == "B")
    evidence = target_b.live_evidence
    assert evidence is not None
    return (target_b.off_host and _independence_marker(evidence, "off_host")) or (
        target_b.off_volume and _independence_marker(evidence, "off_volume")
    )


def qa_archives(
    targets: Iterable[ArchiveTarget],
    expected: Mapping[str, str],
) -> dict[str, Any]:
    selected = list(targets)
    target_errors = validate_archive_targets(selected)
    target_results = [archive_qa(target, expected) for target in selected]
    passed = not target_errors and all(result["pass"] for result in target_results)
    live_passed = passed and _live_archive_pair(
        selected,
        expected,
        {result["target"]: result["observed_sha256"] for result in target_results},
    )
    return {
        "targets": target_results,
        "target_errors": target_errors,
        "local_live_gate_passed": live_passed,
        "pass": passed,
    }


validate_targets = validate_archive_targets
write_archive = copy_sealed_package
run_archive_qa = qa_archives

__all__ = [
    "ArchiveTarget",
    "archive_qa",
    "copy_durable_only",
    "copy_sealed_package",
    "qa_archives",
    "run_archive_qa",
    "validate_archive_targets",
    "validate_targets",
    "write_archive",
]
