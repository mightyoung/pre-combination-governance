"""Offline, root-local Phase-0 research runtime materialization and verification."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from rfb.contracts.canonical_json import canonical_bytes

RUNTIME_SCHEMA_VERSION = "1.0.0"
RECEIPT_DERIVATION_CONTRACT_VERSION = "2.0.1"


def _run_process(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
    """Retry only transient Windows executable sharing violations."""
    for attempt in range(100):
        try:
            completed = subprocess.run(*args, **kwargs)
        except PermissionError as exc:
            if os.name != "nt" or getattr(exc, "winerror", None) != 32 or attempt == 99:
                raise
            time.sleep(0.05)
            continue
        windows_sharing_violation = (
            os.name == "nt" and completed.returncode & 0xFFFFFFFF == 0xC0000043
        )
        if windows_sharing_violation and attempt < 99:
            time.sleep(0.05)
            continue
        return completed
    raise AssertionError("unreachable")


ROOT_REQUIREMENTS = (
    "numpy",
    "scipy",
    "matplotlib",
    "pytest",
    "jsonschema",
    "cryptography",
    "pip",
)
RECEIPT_KINDS = (
    "pip_check",
    "unit",
    "property",
    "integration",
    "reproducibility",
    "schema",
    "artifact_hash",
)
UNIT_NODES = (
    "tests/test_conservation_contract.py::test_exact_duplicate_is_audit_only",
    "tests/test_conservation_contract.py::test_same_root_alternate_view_is_audit_only",
    "tests/test_conservation_contract.py::test_higher_version_without_transaction_ledger_freezes_atomically",
    "tests/test_conservation_contract.py::test_complete_conflict_freezes_without_committing_vacuous_state",
    "tests/test_conservation_contract.py::test_legacy_evidence_positional_interface_still_runs",
    "tests/test_conservation_contract.py::test_runtime_unique_duplicate_and_equivocation_conserve_resources_atomically",
    "tests/test_conservation_contract.py::test_runtime_unique_event_conservation_and_replay_are_deterministic",
)
PROPERTY_NODES = (
    "tests/test_g017_lifecycle_properties.py::test_frozen_corpus_schema_hash_and_actual_l01_l24_checkpoint_map",
    "tests/test_g017_lifecycle_properties.py::test_every_committed_prefix_matches_reference_replay_and_checkpoint_recovery",
    "tests/test_g017_lifecycle_properties.py::test_ordered_control_interleaving_versions_nonminimum_canonical_and_rebuilds",
    "tests/test_g017_lifecycle_properties.py::test_cap_and_budget_plus_one_fail_closed_and_hide_old_public_risk[kwargs0-ACTIVE_CONTRIBUTION_CAP]",
    "tests/test_g017_lifecycle_properties.py::test_cap_and_budget_plus_one_fail_closed_and_hide_old_public_risk[kwargs1-CONTRIBUTION_BUDGET_CAP]",
    "tests/test_g017_lifecycle_properties.py::test_explicit_safe_halt_and_invalid_controls_are_real_fail_closed_boundaries",
    "tests/test_g017_lifecycle_properties.py::test_controls_change_single_authority_binding_and_real_replay_validates_history",
    "tests/test_g017_lifecycle_properties.py::test_tampered_checkpoint_replay_reanchors_a_recoverable_fail_closed_chain[scientific-binding]",
    "tests/test_g017_lifecycle_properties.py::test_tampered_checkpoint_replay_reanchors_a_recoverable_fail_closed_chain[root-lifecycle]",
    "tests/test_g017_lifecycle_properties.py::test_tampered_checkpoint_replay_reanchors_a_recoverable_fail_closed_chain[processing-spend]",
    "tests/test_g017_lifecycle_properties.py::test_tampered_checkpoint_replay_reanchors_a_recoverable_fail_closed_chain[ledger-head]",
    "tests/test_g017_lifecycle_properties.py::test_proposed_behaviorally_calls_production_engine_and_uses_one_timeline",
    "tests/test_g017_lifecycle_properties.py::test_reference_import_isolation_is_structural",
)
INTEGRATION_NODES = (
    "tests/test_research_adapters.py::test_real_adapter_worker_scorer_chain_keeps_truth_outside_result_tree",
    "tests/test_research_adapters.py::test_scorer_alignment_failure_is_independent_of_sealed_method_result",
)
TEST_PLAN = {
    "pip_check": {"report_type": "pip_graph_json", "nodes": []},
    "unit": {"report_type": "junit", "nodes": list(UNIT_NODES)},
    "property": {"report_type": "junit", "nodes": list(PROPERTY_NODES)},
    "integration": {"report_type": "junit", "nodes": list(INTEGRATION_NODES)},
    "reproducibility": {"report_type": "fresh_process_pair_json", "nodes": []},
    "schema": {"report_type": "schema_validation_json", "nodes": []},
    "artifact_hash": {"report_type": "artifact_reopen_json", "nodes": []},
}
RECEIPT_DERIVATION_CONTRACT = {
    "version": RECEIPT_DERIVATION_CONTRACT_VERSION,
    "status_source": "RAW_REPORT_STDOUT_STDERR_AND_FIXED_TEST_PLAN",
    "junit_policy": "EXACT_NODE_SET_COUNTS_AND_ZERO_FAILURES",
    "pip_policy": "EXACT_INSTALLED_GRAPH_AND_PIP_CHECK_PARSE",
    "json_policy": "CLOSED_SEMANTIC_RECOMPUTATION",
    "repro_reopen_policy": "TWO_NEW_SEALED_PROCESSES_IN_DISTINCT_FRESH_SCRATCHES",
    "repro_argv": [
        "@ROOT/python.exe",
        "-I",
        "-S",
        "-B",
        "@ROOT/sealed_bootstrap.py",
        "module",
        "rfb.research.phase0_frozen_runtime",
        "emit-repro",
        "@FRESH_SCRATCH/result.json",
    ],
}
BLOCKER = "BLOCKED_OFFLINE_CLOSURE_NOT_MATERIALIZED"
SYSTEM_DLL_NAMES = {
    "advapi32.dll",
    "bcrypt.dll",
    "bcryptprimitives.dll",
    "cabinet.dll",
    "comctl32.dll",
    "comdlg32.dll",
    "concrt140.dll",
    "crypt32.dll",
    "gdi32.dll",
    "imm32.dll",
    "iphlpapi.dll",
    "kernel32.dll",
    "msvcp140.dll",
    "msi.dll",
    "netapi32.dll",
    "ntdll.dll",
    "ole32.dll",
    "oleaut32.dll",
    "psapi.dll",
    "rpcrt4.dll",
    "secur32.dll",
    "shell32.dll",
    "shlwapi.dll",
    "user32.dll",
    "userenv.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "version.dll",
    "winmm.dll",
    "ws2_32.dll",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def _relative_files(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": _file_sha(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def _bytecode_paths(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.name == "__pycache__" or (path.is_file() and path.suffix == ".pyc")
    )


def _purge_bytecode(root: Path) -> None:
    for path in reversed(_bytecode_paths(root)):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def _assert_zero_bytecode(root: Path) -> None:
    found = _bytecode_paths(root)
    if found:
        raise ValueError(f"BYTECODE_PRESENT:{found[0]}")


def _root_logical(path: str | Path, runtime_root: Path) -> str:
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(runtime_root.resolve())
    except ValueError as exc:
        raise ValueError(f"IDENTITY_PATH_OUTSIDE_ROOT:{resolved}") from exc
    return "@ROOT" if not relative.parts else f"@ROOT/{relative.as_posix()}"


def _requirements_for(dist: metadata.Distribution) -> list[str]:
    requirements = []
    for raw in dist.requires or ():
        requirement = Requirement(raw)
        if requirement.marker is not None and not requirement.marker.evaluate(
            {"extra": ""}
        ):
            continue
        requirements.append(str(requirement))
    return sorted(requirements)


def _record_digest(path: Path) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest())
    return f"sha256={encoded.rstrip(b'=').decode()}"


def _source_binding(workspace: Path) -> dict[str, Any]:
    from rfb.research.phase0_qualification import (
        _file_ref,
        _source_paths,
    )

    entries = [_file_ref(workspace, path) for path in _source_paths(workspace)]
    return {"files": entries, "source_set_sha256": _sha(canonical_bytes(entries))}


def _contract_binding(workspace: Path) -> dict[str, Any]:
    paths = (
        ".omx/plans/MMEPreregistration-v1.json",
        ".omx/plans/论文范围冻结决议-20260820.md",
        "risk-fusion-bench/src/rfb/contracts/phase0_qualification_manifest.schema.json",
        "risk-fusion-bench/src/rfb/contracts/phase0_frozen_runtime_manifest.schema.json",
        "risk-fusion-bench/src/rfb/contracts/phase0_frozen_runtime_qualification.schema.json",
        "risk-fusion-bench/src/rfb/contracts/phase0_frozen_runtime_receipt.schema.json",
    )
    files = [{"path": path, "sha256": _file_sha(workspace / path)} for path in paths]
    return {
        "files": files,
        "files_sha256": _sha(canonical_bytes(files)),
        "test_plan": TEST_PLAN,
        "test_plan_sha256": _sha(canonical_bytes(TEST_PLAN)),
        "receipt_derivation_contract": RECEIPT_DERIVATION_CONTRACT,
        "receipt_derivation_contract_sha256": _sha(
            canonical_bytes(RECEIPT_DERIVATION_CONTRACT)
        ),
    }


def _identity_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in manifest.items()
        if key not in {"materialization", "environment_id", "manifest_self_sha256"}
    }


def _resolve_distribution_closure() -> list[metadata.Distribution]:
    pending = list(ROOT_REQUIREMENTS)
    resolved: dict[str, metadata.Distribution] = {}
    while pending:
        requested = pending.pop(0)
        dist = metadata.distribution(requested)
        name = canonicalize_name(dist.metadata["Name"])
        if name in resolved:
            continue
        resolved[name] = dist
        for raw in dist.requires or ():
            requirement = Requirement(raw)
            if requirement.marker is not None and not requirement.marker.evaluate(
                {"extra": ""}
            ):
                continue
            dependency = metadata.distribution(requirement.name)
            if Version(dependency.version) not in requirement.specifier:
                raise ValueError(f"UNSATISFIED_REQUIREMENT:{raw}")
            pending.append(requirement.name)
    return [resolved[name] for name in sorted(resolved)]


def _copy_distribution(
    dist: metadata.Distribution, runtime_root: Path
) -> dict[str, Any]:
    copied: list[dict[str, Any]] = []
    record_path: Path | None = None
    source_record_sha256: str | None = None
    distribution_root = Path(dist.locate_file("")).resolve()
    install_root = (
        distribution_root.parents[1]
        if distribution_root.parent.name.casefold() == "lib"
        else distribution_root.parent
    )
    for item in dist.files or ():
        source = Path(dist.locate_file(item)).resolve()
        try:
            site_relative = source.relative_to(distribution_root)
            relative = Path("Lib/site-packages") / site_relative
        except ValueError:
            try:
                relative = source.relative_to(install_root)
            except ValueError as exc:
                raise ValueError(
                    f"DISTRIBUTION_FILE_OUTSIDE_INSTALL_ROOT:{source}"
                ) from exc
        if (
            not source.is_file()
            or source.suffix == ".pyc"
            or "__pycache__" in source.parts
        ):
            continue
        target = runtime_root / relative
        if source.name == "RECORD" and source.parent.name.endswith(".dist-info"):
            record_path = target
            source_record_sha256 = _file_sha(source)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if not (
            target.is_file()
            and target.stat().st_size == source.stat().st_size
            and _file_sha(target) == _file_sha(source)
        ):
            shutil.copy2(source, target)
        copied.append(
            {
                "path": relative.as_posix(),
                "size": target.stat().st_size,
                "sha256": _file_sha(target),
            }
        )
    if record_path is None or source_record_sha256 is None:
        raise ValueError(f"DISTRIBUTION_RECORD_MISSING:{dist.metadata['Name']}")
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_rows = [
        [
            entry["path"],
            _record_digest(runtime_root / entry["path"]),
            str(entry["size"]),
        ]
        for entry in sorted(copied, key=lambda item: item["path"])
    ]
    record_rows.append([record_path.relative_to(runtime_root).as_posix(), "", ""])
    with record_path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, lineterminator="\n").writerows(record_rows)
    copied.append(
        {
            "path": record_path.relative_to(runtime_root).as_posix(),
            "size": record_path.stat().st_size,
            "sha256": _file_sha(record_path),
        }
    )
    metadata_file = next(
        (entry for entry in copied if entry["path"].endswith(".dist-info/METADATA")),
        None,
    )
    if metadata_file is None:
        raise ValueError(f"DISTRIBUTION_METADATA_MISSING:{dist.metadata['Name']}")
    return {
        "name": canonicalize_name(dist.metadata["Name"]),
        "version": dist.version,
        "requirements": _requirements_for(dist),
        "metadata_sha256": metadata_file["sha256"],
        "source_record_sha256": source_record_sha256,
        "record_sha256": _file_sha(record_path),
        "record_entries": len(record_rows),
        "files": sorted(copied, key=lambda item: item["path"]),
    }


def _installed_graph(runtime_root: Path) -> list[dict[str, Any]]:
    site = runtime_root / "Lib/site-packages"
    graph = []
    for dist in metadata.distributions(path=[str(site)]):
        graph.append(
            {
                "name": canonicalize_name(dist.metadata["Name"]),
                "version": dist.version,
                "requirements": _requirements_for(dist),
            }
        )
    return sorted(graph, key=lambda item: item["name"])


def _verify_distribution_closure(
    runtime_root: Path, expected: list[dict[str, Any]]
) -> None:
    expected_graph = [
        {key: dist[key] for key in ("name", "version", "requirements")}
        for dist in expected
    ]
    if _installed_graph(runtime_root) != expected_graph:
        raise ValueError("INSTALLED_DEPENDENCY_GRAPH_MISMATCH")
    for dist in expected:
        for entry in dist["files"]:
            path = runtime_root / entry["path"]
            if (
                not path.is_file()
                or path.stat().st_size != entry["size"]
                or _file_sha(path) != entry["sha256"]
            ):
                raise ValueError("INSTALLED_DISTRIBUTION_FILE_MISMATCH")
        record_entries = [
            entry
            for entry in dist["files"]
            if entry["path"].endswith(".dist-info/RECORD")
        ]
        if len(record_entries) != 1:
            raise ValueError("INSTALLED_RECORD_CARDINALITY_INVALID")
        record_path = runtime_root / record_entries[0]["path"]
        with record_path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.reader(stream))
        if len(rows) != dist["record_entries"]:
            raise ValueError("INSTALLED_RECORD_COUNT_MISMATCH")
        seen: set[str] = set()
        for relative, digest, size in rows:
            if relative in seen:
                raise ValueError("INSTALLED_RECORD_DUPLICATE_PATH")
            seen.add(relative)
            path = runtime_root / relative
            if relative == record_entries[0]["path"]:
                if digest or size:
                    raise ValueError("INSTALLED_RECORD_SELF_ENTRY_INVALID")
                continue
            if (
                not path.is_file()
                or digest != _record_digest(path)
                or size != str(path.stat().st_size)
            ):
                raise ValueError("INSTALLED_RECORD_FILE_MISMATCH")
        if seen != {entry["path"] for entry in dist["files"]}:
            raise ValueError("INSTALLED_RECORD_CLOSURE_INCOMPLETE")


def _workspace_for_output(output: Path) -> Path:
    for candidate in (output, *output.parents):
        if (candidate / "risk-fusion-bench").is_dir() and (candidate / ".omx").is_dir():
            return candidate
    raise ValueError("WORKSPACE_ROOT_NOT_FOUND")


def _copy_clean_interpreter(clean_root: Path, runtime_root: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        current = Path(directory)
        ignored: set[str] = set()
        if current.name == "Lib" and "site-packages" in names:
            ignored.add("site-packages")
        if "__pycache__" in names:
            ignored.add("__pycache__")
        for name in names:
            source = current / name
            try:
                target = runtime_root / source.relative_to(clean_root)
            except ValueError:
                continue
            if (
                source.is_file()
                and target.is_file()
                and source.stat().st_size == target.stat().st_size
                and _file_sha(source) == _file_sha(target)
            ):
                ignored.add(name)
        return ignored

    if runtime_root.exists():
        try:
            shutil.rmtree(runtime_root)
        except PermissionError:
            prior_manifest_path = runtime_root.parent / "runtime-manifest.json"
            prior_inventory = {}
            if prior_manifest_path.is_file():
                prior_manifest = json.loads(
                    prior_manifest_path.read_text(encoding="utf-8")
                )
                prior_inventory = {
                    item["path"]: item["sha256"]
                    for item in prior_manifest.get("interpreter_files", [])
                }
            retained = {
                path.relative_to(runtime_root).as_posix(): path
                for path in runtime_root.rglob("*")
                if path.is_file()
            }
            permitted_scripts = {
                "Scripts/fonttools.exe",
                "Scripts/jsonschema.exe",
                "Scripts/pyftmerge.exe",
                "Scripts/pyftsubset.exe",
                "Scripts/ttx.exe",
            }
            invalid = []
            for relative, retained_path in retained.items():
                clean_path = clean_root / relative
                clean_match = (
                    clean_path.is_file()
                    and clean_path.stat().st_size == retained_path.stat().st_size
                    and _file_sha(clean_path) == _file_sha(retained_path)
                )
                prior_match = prior_inventory.get(relative) == _file_sha(retained_path)
                if (
                    relative not in permitted_scripts
                    and not clean_match
                    and not prior_match
                ):
                    invalid.append(relative)
            if not retained or invalid:
                raise
    shutil.copytree(clean_root, runtime_root, ignore=ignore, dirs_exist_ok=True)
    (runtime_root / "Lib/site-packages").mkdir(parents=True, exist_ok=True)


def _copy_project_snapshot(workspace: Path, runtime_root: Path) -> None:
    project = runtime_root / "project"
    shutil.copytree(
        workspace / "risk-fusion-bench/src",
        project / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(
        workspace / "risk-fusion-bench/tests",
        project / "tests",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )
    shutil.copy2(workspace / "risk-fusion-bench/pyproject.toml", project)


def _rva_to_offset(data: bytes, pe_offset: int, rva: int) -> int | None:
    section_count = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    section_offset = pe_offset + 24 + optional_size
    for index in range(section_count):
        offset = section_offset + index * 40
        virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from(
            "<IIII", data, offset + 8
        )
        if virtual_address <= rva < virtual_address + max(virtual_size, raw_size):
            return raw_pointer + rva - virtual_address
    return rva if rva < len(data) else None


def _cstring(data: bytes, offset: int) -> str:
    end = data.find(b"\0", offset)
    if end < 0:
        raise ValueError("PE_STRING_UNTERMINATED")
    return data[offset:end].decode("ascii").casefold()


def pe_imports(path: Path) -> dict[str, list[str]]:
    data = path.read_bytes()
    if len(data) < 64 or data[:2] != b"MZ":
        return {"normal": [], "delay": []}
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe : pe + 4] != b"PE\0\0":
        raise ValueError(f"PE_SIGNATURE_INVALID:{path}")
    optional = pe + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    directory = optional + (112 if magic == 0x20B else 96 if magic == 0x10B else -1)
    if directory < optional:
        raise ValueError(f"PE_OPTIONAL_HEADER_UNSUPPORTED:{path}")
    image_base = struct.unpack_from(
        "<Q" if magic == 0x20B else "<I",
        data,
        optional + (24 if magic == 0x20B else 28),
    )[0]

    def names(index: int, descriptor_size: int, name_field: int) -> list[str]:
        rva, _size = struct.unpack_from("<II", data, directory + index * 8)
        offset = _rva_to_offset(data, pe, rva) if rva else None
        found: list[str] = []
        while offset is not None and offset + descriptor_size <= len(data):
            descriptor = data[offset : offset + descriptor_size]
            if not any(descriptor):
                break
            name_rva = struct.unpack_from("<I", descriptor, name_field)[0]
            if index == 13 and not (struct.unpack_from("<I", descriptor, 0)[0] & 1):
                name_rva -= image_base
            name_offset = _rva_to_offset(data, pe, name_rva)
            if name_offset is None:
                raise ValueError(f"PE_IMPORT_NAME_OUT_OF_RANGE:{path}")
            found.append(_cstring(data, name_offset))
            offset += descriptor_size
        return sorted(set(found))

    return {"normal": names(1, 20, 12), "delay": names(13, 32, 4)}


def _native_closure(runtime_root: Path) -> dict[str, Any]:
    candidates = sorted(
        path
        for path in runtime_root.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".pyd", ".dll", ".exe"}
    )
    local_by_name: dict[str, list[Path]] = {}
    for candidate in candidates:
        local_by_name.setdefault(candidate.name.casefold(), []).append(candidate)
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    imports: list[dict[str, Any]] = []
    unresolved: set[str] = set()
    system: dict[str, dict[str, Any]] = {}
    queue = list(candidates)
    visited: set[Path] = set()
    while queue:
        binary = queue.pop(0)
        if binary in visited:
            continue
        visited.add(binary)
        parsed = pe_imports(binary)
        for import_kind, names in parsed.items():
            for name in names:
                resolution = ""
                target: Path | None = None
                same_dir = binary.parent / name
                if same_dir.is_file():
                    target, resolution = same_dir, "ROOT_LOCAL_SAME_DIRECTORY"
                elif name in local_by_name and len(local_by_name[name]) == 1:
                    target, resolution = local_by_name[name][0], "ROOT_LOCAL_UNIQUE"
                elif name.startswith(("api-ms-win-", "ext-ms-win-")):
                    resolution = "WINDOWS_API_SET"
                elif name in SYSTEM_DLL_NAMES and (system32 / name).is_file():
                    target, resolution = system32 / name, "WINDOWS_SYSTEM32_PINNED"
                    system[name] = {
                        "name": name,
                        "location": f"@SYSTEM32/{name}",
                        "sha256": _file_sha(target),
                    }
                else:
                    unresolved.add(name)
                    resolution = "UNRESOLVED"
                imports.append(
                    {
                        "binary": binary.relative_to(runtime_root).as_posix(),
                        "kind": import_kind,
                        "name": name,
                        "resolution": resolution,
                    }
                )
                if target is not None:
                    try:
                        target.relative_to(runtime_root)
                    except ValueError:
                        pass
                    else:
                        queue.append(target)
    return {
        "policy": "ROOT_LOCAL_RECURSIVE_OR_PINNED_SYSTEM32_OR_WINDOWS_API_SET",
        "normal_and_delay_imports": sorted(
            imports, key=lambda item: (item["binary"], item["kind"], item["name"])
        ),
        "system_dlls": [system[name] for name in sorted(system)],
        "unresolved": sorted(unresolved),
    }


BOOTSTRAP = r"""from __future__ import annotations
import json, os, runpy, sys
from pathlib import Path
root = Path(__file__).resolve().parent
if os.environ.get("PYTHONPATH"):
    raise SystemExit("SEALED_PYTHONPATH_PRESENT")
if os.environ.get("PYTHONNOUSERSITE") != "1":
    raise SystemExit("SEALED_USER_SITE_NOT_DISABLED")
for base in (root / "Lib/site-packages", root / "project/src", root / "project"):
    if not base.resolve().is_relative_to(root):
        raise SystemExit("SEALED_PATH_OUTSIDE_ROOT")
for forbidden in ("sitecustomize.py", "usercustomize.py"):
    if any(root.rglob(forbidden)):
        raise SystemExit("SEALED_CUSTOMIZATION_PRESENT")
if any((root / "Lib/site-packages").rglob("*.pth")):
    raise SystemExit("SEALED_PTH_PRESENT")
sys.path[:0] = [str(root / "Lib/site-packages"), str(root / "project/src"), str(root / "project")]
if sys.flags.isolated != 1 or sys.flags.no_site != 1 or sys.dont_write_bytecode is not True:
    raise SystemExit("SEALED_FLAGS_MISSING")
if sys.argv[1] == "module":
    module = sys.argv[2]; sys.argv = [module, *sys.argv[3:]]; runpy.run_module(module, run_name="__main__")
elif sys.argv[1] == "probe":
    print(json.dumps({"executable": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix, "sys_path": sys.path, "isolated": sys.flags.isolated, "no_site": sys.flags.no_site, "dont_write_bytecode": sys.dont_write_bytecode}, sort_keys=True))
else:
    raise SystemExit("SEALED_BOOTSTRAP_COMMAND_INVALID")
"""


def _sealed_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PIP_NO_INDEX"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def _sealed_argv(runtime_root: Path, *args: str) -> list[str]:
    return [
        str(runtime_root / "python.exe"),
        "-I",
        "-S",
        "-B",
        str(runtime_root / "sealed_bootstrap.py"),
        *args,
    ]


def _parse_junit_report(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if len(suites) != 1:
        raise ValueError("FROZEN_JUNIT_SUITE_CARDINALITY")
    outcomes: dict[str, str] = {}
    for case in suites[0].findall("testcase"):
        node = f"{case.attrib['classname'].replace('.', '/')}.py::{case.attrib['name']}"
        if node in outcomes:
            raise ValueError("FROZEN_JUNIT_DUPLICATE_NODE")
        outcomes[node] = (
            "FAIL"
            if case.find("failure") is not None or case.find("error") is not None
            else "SKIP"
            if case.find("skipped") is not None
            else "PASS"
        )
    result = {
        "nodes": outcomes,
        "passed": sum(value == "PASS" for value in outcomes.values()),
        "failed": sum(value == "FAIL" for value in outcomes.values()),
        "skipped": sum(value == "SKIP" for value in outcomes.values()),
    }
    suite = suites[0]
    claimed = {
        "tests": int(suite.attrib.get("tests", len(outcomes))),
        "failed": int(suite.attrib.get("failures", 0))
        + int(suite.attrib.get("errors", 0)),
        "skipped": int(suite.attrib.get("skipped", 0)),
    }
    if claimed != {
        "tests": len(outcomes),
        "failed": result["failed"],
        "skipped": result["skipped"],
    }:
        raise ValueError("FROZEN_JUNIT_CLAIMED_COUNTS_MISMATCH")
    return result


def _schema_semantics(runtime_root: Path) -> dict[str, Any]:
    from jsonschema.validators import validator_for

    contracts = runtime_root / "project/src/rfb/contracts"
    names = (
        "phase0_qualification_manifest.schema.json",
        "phase0_frozen_runtime_manifest.schema.json",
        "phase0_frozen_runtime_qualification.schema.json",
        "phase0_frozen_runtime_receipt.schema.json",
    )
    schemas = []
    for name in names:
        path = contracts / name
        document = json.loads(path.read_text(encoding="utf-8"))
        validator_for(document).check_schema(document)
        schemas.append(
            {"path": f"project/src/rfb/contracts/{name}", "sha256": _file_sha(path)}
        )
    return {"kind": "schema", "schemas": schemas, "status": "PASS"}


def _pip_semantics(runtime_root: Path) -> dict[str, Any]:
    bootstrap = runtime_root / "sealed_bootstrap.py"
    completed = _run_process(
        _sealed_argv(runtime_root, "module", "pip", "check"),
        cwd=runtime_root / "project",
        env=_sealed_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "kind": "pip_check",
        "installed_graph": _installed_graph(runtime_root),
        "pip_check_returncode": completed.returncode,
        "pip_check_stdout": completed.stdout,
        "pip_check_stderr": completed.stderr,
        "bootstrap_sha256": _file_sha(bootstrap),
        "status": "PASS"
        if completed.returncode == 0
        and completed.stdout.strip() == "No broken requirements found."
        and not completed.stderr
        else "FAIL",
    }


def _reproducible_payload() -> dict[str, Any]:
    from rfb.research.lifecycle_qualification import execute_l01_l24

    return execute_l01_l24()


def _emit_repro(path: Path) -> dict[str, Any]:
    payload = _reproducible_payload()
    raw = canonical_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"pid": os.getpid(), "output_sha256": _sha(raw), "size": len(raw)}


def _repro_semantics(runtime_root: Path, output: Path) -> dict[str, Any]:
    scratch = output / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    runs = []
    for index in range(2):
        with tempfile.TemporaryDirectory(
            prefix=f"repro-{index}-", dir=scratch
        ) as directory:
            target = Path(directory) / "result.json"
            completed = _run_process(
                _sealed_argv(
                    runtime_root,
                    "module",
                    "rfb.research.phase0_frozen_runtime",
                    "emit-repro",
                    str(target),
                ),
                cwd=runtime_root / "project",
                env=_sealed_env(),
                capture_output=True,
                text=True,
                check=False,
            )
            result = json.loads(completed.stdout) if completed.returncode == 0 else {}
            result["scratch_token"] = Path(directory).name
            result["returncode"] = completed.returncode
            result["stderr_sha256"] = _sha(completed.stderr.encode())
            result["materialized_sha256"] = (
                _file_sha(target) if target.is_file() else None
            )
            runs.append(result)
    expected = _sha(canonical_bytes(_reproducible_payload()))
    passed = (
        all(isinstance(run.get("pid"), int) and run["pid"] > 0 for run in runs)
        and len({run["pid"] for run in runs}) == 2
        and len({run.get("scratch_token") for run in runs}) == 2
        and all(run.get("returncode") == 0 for run in runs)
        and all(run.get("stderr_sha256") == _sha(b"") for run in runs)
        and all(run.get("output_sha256") == expected for run in runs)
        and all(run.get("materialized_sha256") == expected for run in runs)
    )
    return {
        "kind": "reproducibility",
        "fresh_processes": 2,
        "expected_output_sha256": expected,
        "runs": runs,
        "status": "PASS" if passed else "FAIL",
    }


def _repro_document_passes(document: dict[str, Any], expected: str) -> bool:
    runs = document.get("runs", [])
    return (
        set(document)
        == {"kind", "fresh_processes", "expected_output_sha256", "runs", "status"}
        and document["kind"] == "reproducibility"
        and document["fresh_processes"] == 2
        and document["expected_output_sha256"] == expected
        and len(runs) == 2
        and all(
            set(run)
            == {
                "pid",
                "output_sha256",
                "size",
                "scratch_token",
                "returncode",
                "stderr_sha256",
                "materialized_sha256",
            }
            for run in runs
        )
        and all(isinstance(run["pid"], int) and run["pid"] > 0 for run in runs)
        and len({run["pid"] for run in runs}) == 2
        and len({run["scratch_token"] for run in runs}) == 2
        and all(run["returncode"] == 0 for run in runs)
        and all(run["stderr_sha256"] == _sha(b"") for run in runs)
        and all(run["output_sha256"] == expected for run in runs)
        and all(run["materialized_sha256"] == expected for run in runs)
    )


def _json_report_semantics(
    kind: str, runtime_root: Path, output: Path
) -> dict[str, Any]:
    if kind == "pip_check":
        return _pip_semantics(runtime_root)
    if kind == "schema":
        return _schema_semantics(runtime_root)
    if kind == "reproducibility":
        return _repro_semantics(runtime_root, output)
    if kind == "artifact_hash":
        return {"kind": kind, **validate_runtime_artifacts(output)}
    raise ValueError(f"UNKNOWN_JSON_REPORT_KIND:{kind}")


def _derive_report_semantics(
    kind: str, runtime_root: Path, output: Path, report_path: Path
) -> tuple[dict[str, Any], str]:
    if TEST_PLAN[kind]["report_type"] == "junit":
        parsed = _parse_junit_report(report_path)
        expected_nodes = TEST_PLAN[kind]["nodes"]
        passed = (
            list(parsed["nodes"]) == expected_nodes
            and parsed["passed"] == len(expected_nodes)
            and parsed["failed"] == 0
            and parsed["skipped"] == 0
            and set(parsed["nodes"].values()) == {"PASS"}
        )
        return parsed, "PASS" if passed else "FAIL"
    raw = report_path.read_bytes()
    document = json.loads(raw)
    if raw != canonical_bytes(document) + b"\n":
        raise ValueError("JSON_MACHINE_REPORT_NOT_CANONICAL_LINE")
    if kind == "reproducibility":
        expected = _sha(canonical_bytes(_reproducible_payload()))
        passed = _repro_document_passes(document, expected)
    else:
        expected_document = _json_report_semantics(kind, runtime_root, output)
        passed = document == expected_document
    derived = "PASS" if passed else "FAIL"
    if document.get("status") != derived:
        raise ValueError("JSON_MACHINE_REPORT_STATUS_NOT_DERIVED")
    return document, derived


def _run_receipt(
    runtime_root: Path,
    output: Path,
    environment_id: str,
    kind: str,
    arguments: list[str],
    report_name: str,
) -> dict[str, Any]:
    _assert_zero_bytecode(runtime_root)
    report_path = output / "reports" / report_name
    raw_dir = output / "raw"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    report_path.unlink(missing_ok=True)
    stdout_path = raw_dir / f"{kind}.stdout"
    stderr_path = raw_dir / f"{kind}.stderr"
    argv = _sealed_argv(runtime_root, *arguments)
    started = _now()
    completed = _run_process(
        argv,
        cwd=runtime_root / "project",
        env=_sealed_env(),
        capture_output=True,
        text=False,
        check=False,
    )
    ended = _now()
    stdout_path.write_bytes(completed.stdout)
    stderr_path.write_bytes(completed.stderr)
    if not report_path.exists():
        report_path.write_bytes(completed.stdout)
    _assert_zero_bytecode(runtime_root)
    try:
        derived_summary, derived_status = _derive_report_semantics(
            kind, runtime_root, output, report_path
        )
    except (ValueError, KeyError, json.JSONDecodeError, ET.ParseError) as exc:
        derived_summary = {"error": f"{type(exc).__name__}:{exc}"}
        derived_status = "FAIL"
    if completed.returncode != 0 or completed.stderr:
        derived_status = "FAIL"
    body = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "kind": kind,
        "environment_id": environment_id,
        "test_plan_sha256": _sha(canonical_bytes(TEST_PLAN)),
        "receipt_derivation_contract_sha256": _sha(
            canonical_bytes(RECEIPT_DERIVATION_CONTRACT)
        ),
        "argv": argv,
        "cwd": str(runtime_root / "project"),
        "started_at_utc": started,
        "ended_at_utc": ended,
        "exit_code": completed.returncode,
        "status": derived_status,
        "stdout_path": stdout_path.relative_to(output).as_posix(),
        "stdout_sha256": _sha(completed.stdout),
        "stderr_path": stderr_path.relative_to(output).as_posix(),
        "stderr_sha256": _sha(completed.stderr),
        "report_path": report_path.relative_to(output).as_posix(),
        "report_sha256": _file_sha(report_path),
        "derived_summary_sha256": _sha(canonical_bytes(derived_summary)),
    }
    receipt = {**body, "receipt_self_sha256": _sha(canonical_bytes(body))}
    _write_json(output / "receipts" / f"{kind}.json", receipt)
    return receipt


def _pytest_arguments(report: Path, nodes: Iterable[str]) -> list[str]:
    return [
        "module",
        "pytest",
        "-q",
        "--junitxml",
        str(report),
        *nodes,
    ]


def _receipt_specs(output: Path) -> dict[str, tuple[list[str], str]]:
    return {
        "pip_check": (
            [
                "module",
                "rfb.research.phase0_frozen_runtime",
                "report",
                "pip_check",
                str(output),
            ],
            "pip-check.json",
        ),
        "unit": (
            _pytest_arguments(output / "reports/unit.xml", UNIT_NODES),
            "unit.xml",
        ),
        "property": (
            _pytest_arguments(
                output / "reports/property.xml",
                PROPERTY_NODES,
            ),
            "property.xml",
        ),
        "integration": (
            _pytest_arguments(
                output / "reports/integration.xml",
                INTEGRATION_NODES,
            ),
            "integration.xml",
        ),
        "reproducibility": (
            [
                "module",
                "rfb.research.phase0_frozen_runtime",
                "report",
                "reproducibility",
                str(output),
            ],
            "reproducibility.json",
        ),
        "schema": (
            [
                "module",
                "rfb.research.phase0_frozen_runtime",
                "report",
                "schema",
                str(output),
            ],
            "schema.json",
        ),
        "artifact_hash": (
            [
                "module",
                "rfb.research.phase0_frozen_runtime",
                "report",
                "artifact_hash",
                str(output),
            ],
            "artifact-hash.json",
        ),
    }


def materialize_frozen_runtime(
    workspace_root: str | Path,
    output_root: str | Path,
    clean_python_root: str | Path,
) -> dict[str, Any]:
    workspace = Path(workspace_root).resolve()
    output = Path(output_root).resolve()
    runtime_root = output / "runtime"
    clean_root = Path(clean_python_root).resolve()
    version_probe = _run_process(
        [
            str(clean_root / "python.exe"),
            "-I",
            "-S",
            "-B",
            "-c",
            "import platform; print(platform.python_version())",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if version_probe.returncode != 0 or version_probe.stdout.strip() != "3.11.14":
        raise ValueError("CLEAN_UV_PYTHON_VERSION_MISMATCH")
    output.mkdir(parents=True, exist_ok=True)
    _copy_clean_interpreter(clean_root, runtime_root)
    distributions = [
        _copy_distribution(dist, runtime_root)
        for dist in _resolve_distribution_closure()
    ]
    _copy_project_snapshot(workspace, runtime_root)
    (runtime_root / "sealed_bootstrap.py").write_text(BOOTSTRAP, encoding="utf-8")
    forbidden = sorted(
        path.relative_to(runtime_root).as_posix()
        for pattern in ("*.pth", "sitecustomize.py", "usercustomize.py")
        for path in runtime_root.rglob(pattern)
    )
    # The copied clean interpreter contains a setuptools .pth; sealed policy removes it.
    for relative in forbidden:
        (runtime_root / relative).unlink()
    _purge_bytecode(runtime_root)
    _assert_zero_bytecode(runtime_root)
    _verify_distribution_closure(runtime_root, distributions)
    native = _native_closure(runtime_root)
    probe = _run_process(
        _sealed_argv(runtime_root, "probe"),
        env=_sealed_env(),
        capture_output=True,
        check=False,
        text=True,
    )
    if probe.returncode != 0:
        raise ValueError(f"SEALED_PROBE_FAILED:{probe.stderr}")
    probe_result = json.loads(probe.stdout)
    if native["unresolved"]:
        raise ValueError(f"NATIVE_CLOSURE_UNRESOLVED:{native['unresolved']}")
    source = _source_binding(workspace)
    contracts = _contract_binding(workspace)
    interpreter_files = _relative_files(runtime_root)
    unsigned = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "python": {
            "implementation": "CPython",
            "version": "3.11.14",
            "executable": "@ROOT/python.exe",
            "sha256": _file_sha(runtime_root / "python.exe"),
        },
        "sealed_flags": ["-I", "-S", "-B"],
        "user_site_enabled": False,
        "pythonpath_accepted": False,
        "root_local": True,
        "probe": {
            **{
                key: probe_result[key]
                for key in ("isolated", "no_site", "dont_write_bytecode")
            },
            "executable": _root_logical(probe_result["executable"], runtime_root),
            "prefix": _root_logical(probe_result["prefix"], runtime_root),
            "base_prefix": _root_logical(probe_result["base_prefix"], runtime_root),
            "sys_path": [
                _root_logical(value, runtime_root) for value in probe_result["sys_path"]
            ],
        },
        "source_binding": source,
        "contracts": contracts,
        "distributions": distributions,
        "native_closure": native,
        "runtime_tree_sha256": _sha(canonical_bytes(interpreter_files)),
        "runtime_files": interpreter_files,
        "bytecode_files": 0,
    }
    materialization = {
        "workspace_root": str(workspace),
        "runtime_root": str(runtime_root),
        "clean_python_root": str(clean_root),
        "probe": probe_result,
        "system_dll_paths": [
            {
                "name": item["name"],
                "path": str(
                    Path(os.environ.get("SystemRoot", r"C:\Windows"))
                    / "System32"
                    / item["name"]
                ),
                "sha256": item["sha256"],
            }
            for item in native["system_dlls"]
        ],
    }
    environment_id = _sha(canonical_bytes(unsigned))
    manifest = {
        **unsigned,
        "materialization": materialization,
        "environment_id": environment_id,
        "manifest_self_sha256": _sha(
            canonical_bytes(
                {
                    **unsigned,
                    "materialization": materialization,
                    "environment_id": environment_id,
                }
            )
        ),
    }
    _write_json(output / "runtime-manifest.json", manifest)
    lock = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "environment_id": environment_id,
        "distributions": [
            {
                key: dist[key]
                for key in (
                    "name",
                    "version",
                    "requirements",
                    "metadata_sha256",
                    "source_record_sha256",
                    "record_sha256",
                )
            }
            for dist in distributions
        ],
    }
    _write_json(output / "runtime-lock.json", lock)
    return manifest


def run_qualification(output_root: str | Path) -> dict[str, Any]:
    output = Path(output_root).resolve()
    runtime = output / "runtime"
    manifest = json.loads(
        (output / "runtime-manifest.json").read_text(encoding="utf-8")
    )
    environment_id = manifest["environment_id"]
    specs = _receipt_specs(output)
    receipts = [
        _run_receipt(runtime, output, environment_id, kind, *specs[kind])
        for kind in RECEIPT_KINDS
    ]
    body = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "environment_id": environment_id,
        "runtime_manifest_path": "runtime-manifest.json",
        "runtime_manifest_sha256": _file_sha(output / "runtime-manifest.json"),
        "runtime_lock_path": "runtime-lock.json",
        "runtime_lock_sha256": _file_sha(output / "runtime-lock.json"),
        "receipt_refs": [
            {
                "kind": receipt["kind"],
                "path": f"receipts/{receipt['kind']}.json",
                "sha256": _file_sha(output / "receipts" / f"{receipt['kind']}.json"),
            }
            for receipt in receipts
        ],
        "status": "PASS" if all(r["status"] == "PASS" for r in receipts) else "FAIL",
        "blocker_code": None
        if all(r["status"] == "PASS" for r in receipts)
        else BLOCKER,
    }
    qualification = {**body, "qualification_self_sha256": _sha(canonical_bytes(body))}
    _write_json(output / "qualification.json", qualification)
    return qualification


def validate_runtime_artifacts(output_root: str | Path) -> dict[str, Any]:
    output = Path(output_root).resolve()
    runtime = output / "runtime"
    manifest = json.loads(
        (output / "runtime-manifest.json").read_text(encoding="utf-8")
    )
    body = {
        key: value for key, value in manifest.items() if key != "manifest_self_sha256"
    }
    if _sha(canonical_bytes(body)) != manifest["manifest_self_sha256"]:
        raise ValueError("RUNTIME_MANIFEST_SELF_HASH_MISMATCH")
    if _sha(canonical_bytes(_identity_payload(manifest))) != manifest["environment_id"]:
        raise ValueError("ENVIRONMENT_ID_MISMATCH")
    workspace = _workspace_for_output(output)
    if manifest["source_binding"] != _source_binding(workspace):
        raise ValueError("LIVE_SOURCE_BINDING_MISMATCH")
    if manifest["contracts"] != _contract_binding(workspace):
        raise ValueError("LIVE_CONTRACT_BINDING_MISMATCH")
    materialization = manifest["materialization"]
    if (
        not Path(materialization["workspace_root"]).is_absolute()
        or not Path(materialization["runtime_root"]).is_absolute()
        or not Path(materialization["clean_python_root"]).is_absolute()
    ):
        raise ValueError("MATERIALIZATION_PATH_NOT_ABSOLUTE")
    _assert_zero_bytecode(runtime)
    actual = _relative_files(runtime)
    if actual != manifest["runtime_files"]:
        raise ValueError("RUNTIME_FILE_INVENTORY_MISMATCH")
    if _sha(canonical_bytes(actual)) != manifest["runtime_tree_sha256"]:
        raise ValueError("RUNTIME_TREE_HASH_MISMATCH")
    logical_paths = (
        manifest["python"]["executable"],
        manifest["probe"]["executable"],
        manifest["probe"]["prefix"],
        manifest["probe"]["base_prefix"],
        *manifest["probe"]["sys_path"],
    )
    if any(not value.startswith("@ROOT") for value in logical_paths):
        raise ValueError("RUNTIME_IDENTITY_PATH_NOT_LOGICAL")
    _verify_distribution_closure(runtime, manifest["distributions"])
    for dist in manifest["distributions"]:
        record = [
            entry
            for entry in dist["files"]
            if entry["path"].endswith(".dist-info/RECORD")
        ]
        metadata_files = [
            entry
            for entry in dist["files"]
            if entry["path"].endswith(".dist-info/METADATA")
        ]
        if (
            len(record) != 1
            or len(metadata_files) != 1
            or record[0]["sha256"] != dist["record_sha256"]
            or metadata_files[0]["sha256"] != dist["metadata_sha256"]
        ):
            raise ValueError("DISTRIBUTION_METADATA_RECORD_BINDING_MISMATCH")
    if _native_closure(runtime) != manifest["native_closure"]:
        raise ValueError("NATIVE_CLOSURE_RECOMPUTE_MISMATCH")
    for system in manifest["native_closure"]["system_dlls"]:
        expected_location = f"@SYSTEM32/{system['name']}"
        system_path = (
            Path(os.environ.get("SystemRoot", r"C:\Windows"))
            / "System32"
            / system["name"]
        )
        if (
            system["location"] != expected_location
            or _file_sha(system_path) != system["sha256"]
        ):
            raise ValueError("SYSTEM_DLL_HASH_MISMATCH")
    return {
        "environment_id": manifest["environment_id"],
        "runtime_tree_sha256": manifest["runtime_tree_sha256"],
        "status": "PASS",
    }


def _validate_receipt_evidence(
    receipt: dict[str, Any], runtime: Path, output: Path
) -> str:
    kind = receipt["kind"]
    expected_arguments, expected_report = _receipt_specs(output)[kind]
    if (
        receipt["argv"] != _sealed_argv(runtime, *expected_arguments)
        or receipt["cwd"] != str(runtime / "project")
        or receipt["report_path"] != f"reports/{expected_report}"
        or receipt["stdout_path"] != f"raw/{kind}.stdout"
        or receipt["stderr_path"] != f"raw/{kind}.stderr"
    ):
        raise ValueError("RECEIPT_EXECUTION_CONTRACT_MISMATCH")
    expected_test_plan = _sha(canonical_bytes(TEST_PLAN))
    expected_derivation = _sha(canonical_bytes(RECEIPT_DERIVATION_CONTRACT))
    if (
        receipt["test_plan_sha256"] != expected_test_plan
        or receipt["receipt_derivation_contract_sha256"] != expected_derivation
    ):
        raise ValueError("RECEIPT_DERIVATION_CONTRACT_MISMATCH")
    stdout = output / receipt["stdout_path"]
    stderr = output / receipt["stderr_path"]
    report = output / receipt["report_path"]
    if _file_sha(stdout) != receipt["stdout_sha256"]:
        raise ValueError("RECEIPT_STDOUT_HASH_MISMATCH")
    if _file_sha(stderr) != receipt["stderr_sha256"]:
        raise ValueError("RECEIPT_STDERR_HASH_MISMATCH")
    if _file_sha(report) != receipt["report_sha256"]:
        raise ValueError("RECEIPT_REPORT_HASH_MISMATCH")
    if (
        TEST_PLAN[kind]["report_type"] != "junit"
        and stdout.read_bytes() != report.read_bytes()
    ):
        raise ValueError("JSON_REPORT_STDOUT_BINDING_MISMATCH")
    summary, semantic_status = _derive_report_semantics(kind, runtime, output, report)
    if receipt["derived_summary_sha256"] != _sha(canonical_bytes(summary)):
        raise ValueError("RECEIPT_DERIVED_SUMMARY_MISMATCH")
    derived_status = (
        "PASS" if semantic_status == "PASS" and stderr.read_bytes() == b"" else "FAIL"
    )
    if receipt["status"] != derived_status:
        raise ValueError("RECEIPT_STATUS_NOT_DERIVED")
    if derived_status == "PASS" and receipt["exit_code"] != 0:
        raise ValueError("RECEIPT_EXIT_CODE_INCONSISTENT")
    return derived_status


def _validate_active_reproducibility(
    persisted: dict[str, Any],
    runtime: Path,
    output: Path,
    runtime_files: list[dict[str, Any]],
) -> None:
    expected = _sha(canonical_bytes(_reproducible_payload()))
    if not _repro_document_passes(persisted, expected):
        raise ValueError("PERSISTED_REPRO_REPORT_INVALID")
    before = _relative_files(runtime)
    if before != runtime_files:
        raise ValueError("REPRO_RUNTIME_PRE_CLOSURE_DRIFT")
    with tempfile.TemporaryDirectory(prefix="strict-reopen-", dir=output) as directory:
        active = _repro_semantics(runtime, Path(directory))
    after = _relative_files(runtime)
    if after != before:
        raise ValueError("REPRO_RUNTIME_POST_CLOSURE_DRIFT")
    if not _repro_document_passes(active, expected) or active["status"] != "PASS":
        raise ValueError("ACTIVE_REPRO_VALIDATION_FAILED")
    persisted_signature = {
        "expected_output_sha256": persisted["expected_output_sha256"],
        "outputs": sorted(
            (run["output_sha256"], run["materialized_sha256"], run["size"])
            for run in persisted["runs"]
        ),
    }
    active_signature = {
        "expected_output_sha256": active["expected_output_sha256"],
        "outputs": sorted(
            (run["output_sha256"], run["materialized_sha256"], run["size"])
            for run in active["runs"]
        ),
    }
    if active_signature != persisted_signature:
        raise ValueError("ACTIVE_REPRO_REPORT_MISMATCH")


def validate_frozen_runtime(output_root: str | Path) -> dict[str, Any]:
    from jsonschema import validate

    output = Path(output_root).resolve()
    runtime = output / "runtime"
    manifest_path = output / "runtime-manifest.json"
    qualification_path = output / "qualification.json"
    manifest_raw = manifest_path.read_bytes()
    qualification_raw = qualification_path.read_bytes()
    manifest = json.loads(manifest_raw)
    qualification = json.loads(qualification_raw)
    contracts = runtime / "project/src/rfb/contracts"
    validate(
        manifest,
        json.loads(
            (contracts / "phase0_frozen_runtime_manifest.schema.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    validate(
        qualification,
        json.loads(
            (contracts / "phase0_frozen_runtime_qualification.schema.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    if manifest_raw != canonical_bytes(
        manifest
    ) or qualification_raw != canonical_bytes(qualification):
        raise ValueError("FROZEN_RUNTIME_ARTIFACT_NOT_CANONICAL")
    validate_runtime_artifacts(output)
    manifest_body = {
        key: value for key, value in manifest.items() if key != "manifest_self_sha256"
    }
    if _sha(canonical_bytes(manifest_body)) != manifest["manifest_self_sha256"]:
        raise ValueError("RUNTIME_MANIFEST_SELF_HASH_MISMATCH")
    if _sha(canonical_bytes(_identity_payload(manifest))) != manifest["environment_id"]:
        raise ValueError("ENVIRONMENT_ID_MISMATCH")
    if qualification["environment_id"] != manifest["environment_id"]:
        raise ValueError("QUALIFICATION_ENVIRONMENT_MISMATCH")
    if qualification["runtime_manifest_sha256"] != _file_sha(manifest_path):
        raise ValueError("QUALIFICATION_RUNTIME_MANIFEST_HASH_MISMATCH")
    lock_path = output / qualification["runtime_lock_path"]
    if _file_sha(lock_path) != qualification["runtime_lock_sha256"]:
        raise ValueError("QUALIFICATION_RUNTIME_LOCK_HASH_MISMATCH")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock["environment_id"] != manifest["environment_id"] or lock[
        "distributions"
    ] != [
        {
            key: dist[key]
            for key in (
                "name",
                "version",
                "requirements",
                "metadata_sha256",
                "source_record_sha256",
                "record_sha256",
            )
        }
        for dist in manifest["distributions"]
    ]:
        raise ValueError("RUNTIME_LOCK_CONTENT_MISMATCH")
    q_body = {
        key: value
        for key, value in qualification.items()
        if key != "qualification_self_sha256"
    }
    if _sha(canonical_bytes(q_body)) != qualification["qualification_self_sha256"]:
        raise ValueError("QUALIFICATION_SELF_HASH_MISMATCH")
    refs = qualification["receipt_refs"]
    if [ref["kind"] for ref in refs] != list(RECEIPT_KINDS):
        raise ValueError("RECEIPT_KIND_SET_MISMATCH")
    derived_statuses = []
    for ref in refs:
        receipt_path = output / ref["path"]
        if _file_sha(receipt_path) != ref["sha256"]:
            raise ValueError("RECEIPT_RAW_HASH_MISMATCH")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        validate(
            receipt,
            json.loads(
                (contracts / "phase0_frozen_runtime_receipt.schema.json").read_text(
                    encoding="utf-8"
                )
            ),
        )
        body = {
            key: value for key, value in receipt.items() if key != "receipt_self_sha256"
        }
        if _sha(canonical_bytes(body)) != receipt["receipt_self_sha256"]:
            raise ValueError("RECEIPT_SELF_HASH_MISMATCH")
        if receipt["environment_id"] != manifest["environment_id"]:
            raise ValueError("RECEIPT_ENVIRONMENT_MISMATCH")
        derived_statuses.append(_validate_receipt_evidence(receipt, runtime, output))
        if receipt["kind"] == "reproducibility":
            persisted_repro = json.loads(
                (output / receipt["report_path"]).read_text(encoding="utf-8")
            )
            _validate_active_reproducibility(
                persisted_repro, runtime, output, manifest["runtime_files"]
            )
    expected_status = (
        "PASS" if all(status == "PASS" for status in derived_statuses) else "FAIL"
    )
    if qualification["status"] != expected_status:
        raise ValueError("QUALIFICATION_STATUS_NOT_DERIVED")
    expected_blocker = None if expected_status == "PASS" else BLOCKER
    if qualification["blocker_code"] != expected_blocker:
        raise ValueError("QUALIFICATION_BLOCKER_NOT_DERIVED")
    _assert_zero_bytecode(runtime)
    return qualification


def _main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("output")
    verify_artifacts = sub.add_parser("verify-artifacts")
    verify_artifacts.add_argument("output")
    report = sub.add_parser("report")
    report.add_argument(
        "kind", choices=("pip_check", "reproducibility", "schema", "artifact_hash")
    )
    report.add_argument("output")
    emit_repro = sub.add_parser("emit-repro")
    emit_repro.add_argument("path")
    args = parser.parse_args()
    if args.command == "verify":
        result = validate_frozen_runtime(args.output)
        print(
            json.dumps(
                {
                    "environment_id": result["environment_id"],
                    "status": result["status"],
                },
                sort_keys=True,
            )
        )
    elif args.command == "verify-artifacts":
        print(json.dumps(validate_runtime_artifacts(args.output), sort_keys=True))
    elif args.command == "report":
        runtime = Path(__file__).resolve().parents[4]
        document = _json_report_semantics(
            args.kind, runtime, Path(args.output).resolve()
        )
        sys.stdout.buffer.write(canonical_bytes(document) + b"\n")
    elif args.command == "emit-repro":
        sys.stdout.buffer.write(canonical_bytes(_emit_repro(Path(args.path))) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
