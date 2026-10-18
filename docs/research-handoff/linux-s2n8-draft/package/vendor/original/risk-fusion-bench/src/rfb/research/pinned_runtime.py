"""Deterministic, fail-closed manifests for the approved pinned venv lane.

This module describes a *local* runtime closure.  It deliberately does not
claim that a remote host has materialized or verified the closure.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

RUNTIME_FORMAT = "python_pinned_venv_v1"
PROFILE_ID = "tep_nonconfirmatory_v1"
FIXTURE_RUNTIME_FORMAT = "python_zipapp_stdlib_v1"
_REQUIREMENTS_SHA256 = (
    "5d0fd2f20d1040cd314b24b11fffbdeb2dc106a8038d768f9af3a9d219f0426d"
)
_PROFILE_LOCK_SHA256 = (
    "5f37aee4dc4389000e661311aa2ff2982c07e300b7b6afcd31a072cb6dcb1fb7"
)


class PinnedRuntimeError(ValueError):
    """Raised for any unproven or drifting pinned runtime closure."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _tree_hash(root: Path) -> str:
    rows: list[dict[str, str | int]] = []
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        if path.is_symlink():
            raise PinnedRuntimeError("symlink/reparse component rejected")
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            rows.append(
                {"path": rel, "size": path.stat().st_size, "sha256": _sha256(path)}
            )
    return hashlib.sha256(_canonical(rows)).hexdigest()


def _safe_relative(value: str, *, field: str) -> str:
    posix = PurePosixPath(value.replace("\\", "/"))
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or ".." in posix.parts
        or ".." in windows.parts
    ):
        raise PinnedRuntimeError(f"{field}: path escape")
    return posix.as_posix()


def _normalize_bound_path(value: Any, root: Path) -> str:
    """Represent root-local paths independently of materialization location."""
    raw = str(value)
    if raw in {"", "builtin", "frozen", "namespace"}:
        return raw
    try:
        candidate = Path(raw).resolve()
        root_resolved = root.resolve()
        if candidate.is_relative_to(root_resolved):
            return "@ROOT/" + candidate.relative_to(root_resolved).as_posix()
    except (OSError, ValueError):
        pass
    return raw


def _resolve_bound_path(value: str, root: Path) -> Path:
    if value.startswith("@ROOT/"):
        relative = _safe_relative(value.removeprefix("@ROOT/"), field="bound_path")
        return (root.resolve() / relative).resolve()
    return Path(value).resolve()


def _approved_native_roots(manifest: Mapping[str, Any], root: Path) -> list[Path]:
    """Resolve manifest policy roots, retaining the materialized runtime itself."""
    return [
        root.resolve(),
        *[
            _resolve_bound_path(str(item["path"]), root)
            for item in manifest.get("approved_external_roots", [])
        ],
        *[
            _resolve_bound_path(str(item["path"]), root)
            for item in manifest.get("stdlib_evidence", [])
        ],
    ]


def _normalize_probe_paths(probe: Mapping[str, Any], root: Path) -> dict[str, Any]:
    normalized = dict(probe)
    normalized["sysconfig_paths"] = {
        str(key): _normalize_bound_path(value, root)
        for key, value in dict(probe.get("sysconfig_paths", {})).items()
    }
    normalized["import_origins"] = {
        str(key): _normalize_bound_path(value, root)
        for key, value in dict(probe.get("import_origins", {})).items()
    }
    return normalized


def _reject_symlink_ancestors(path: Path, root: Path) -> None:
    current = path
    root = root.resolve()
    while True:
        if current.is_symlink():
            raise PinnedRuntimeError("symlink/reparse component rejected")
        if current == root or current.parent == current:
            break
        current = current.parent


def _source_inventory(source_root: Path) -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    for path in sorted(
        source_root.rglob("*.py"), key=lambda p: p.relative_to(source_root).as_posix()
    ):
        if path.is_symlink() or any(part.is_symlink() for part in path.parents):
            raise PinnedRuntimeError("source symlink rejected")
        rel = path.relative_to(source_root).as_posix()
        rows.append({"path": rel, "sha256": _sha256(path), "size": path.stat().st_size})
    return rows, hashlib.sha256(_canonical(rows)).hexdigest()


def _distributions(site_root: Path | None, runtime_root: Path) -> list[dict[str, Any]]:
    if site_root is None:
        return []
    result: list[dict[str, Any]] = []
    for dist in sorted(
        importlib.metadata.distributions(path=[str(site_root)]),
        key=lambda d: (d.metadata.get("Name", "").lower(), d.version),
    ):
        if not dist.files or not any(
            str(item).endswith("RECORD") for item in dist.files
        ):
            raise PinnedRuntimeError("distribution RECORD missing")
        files = []
        if dist.files and site_root:
            for item in sorted(dist.files, key=lambda x: str(x)):
                candidate = (site_root / item).resolve()
                try:
                    relative = candidate.relative_to(runtime_root.resolve())
                except ValueError:
                    raise PinnedRuntimeError("distribution path escapes runtime root")
                if candidate.is_symlink():
                    raise PinnedRuntimeError("distribution symlink rejected")
                if candidate.is_file():
                    files.append(
                        {
                            "path": relative.as_posix(),
                            "sha256": _sha256(candidate),
                            "size": candidate.stat().st_size,
                        }
                    )
        result.append(
            {
                "name": dist.metadata.get("Name", ""),
                "version": dist.version,
                "files": files,
                "tree_sha256": hashlib.sha256(_canonical(files)).hexdigest(),
            }
        )
    # A lock is an exact site-packages closure, not merely a list of metadata
    # files.  Any file which is not owned by an installed distribution is an
    # unreviewed extra and therefore makes the pinned lane fail closed.
    owned = {
        str(item["path"]).replace("\\", "/")
        for dist in result
        for item in dist["files"]
    }
    actual = {
        path.relative_to(runtime_root).as_posix()
        for path in site_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if any(path.is_symlink() for path in site_root.rglob("*")):
        raise PinnedRuntimeError("distribution symlink rejected")
    site_prefix = site_root.relative_to(runtime_root).as_posix() + "/"
    owned_site = {path for path in owned if path.startswith(site_prefix)}
    if actual != owned_site:
        extras = sorted(actual - owned_site)
        missing = sorted(owned_site - actual)
        raise PinnedRuntimeError(
            f"site-packages closure mismatch (extras={extras[:3]}, missing={missing[:3]})"
        )
    return result


def _probe_interpreter(
    path: Path, root: Path, site_root: Path | None = None
) -> dict[str, Any]:
    """Ask the selected interpreter for identity; never use controller identity."""
    probe = (
        "import importlib.util,json,platform,sys,sysconfig; "
        "sys.path.insert(0,sys.argv[1]) if len(sys.argv)>1 else None; "
        "print(json.dumps({'version':platform.python_version(),"
        "'implementation':platform.python_implementation(),"
        "'abi':sysconfig.get_config_var('SOABI') or 'none',"
        "'build':platform.python_build()[0],"
        "'sysconfig':{k:str(sysconfig.get_config_var(k) or '') for k in ('SOABI','MULTIARCH','CONFIG_ARGS')},"
        "'target_platform':f'{sys.platform}-{platform.machine().lower()}',"
        "'sys_path':[p for p in sys.path if p],"
        "'sysconfig_paths':{k:str(v) for k,v in sysconfig.get_paths().items()},"
        "'stdlib_paths':[sysconfig.get_path('stdlib')],"
        "'import_origins':{m:(getattr(importlib.util.find_spec(m),'origin',None) or 'builtin') for m in ('numpy','scipy','rfb') if importlib.util.find_spec(m) is not None}}, sort_keys=True))"
    )
    executable = os.access(path, os.X_OK) and not (
        os.name == "nt" and path.suffix.lower() not in {".exe", ".cmd", ".bat"}
    )
    if not executable:
        # Opaque fixture interpreters are retained for contract tests; a
        # materialized executable always takes the fixed-argv probe below.
        return {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "abi": sysconfig.get_config_var("SOABI") or "none",
            "build": platform.python_build()[0],
            "sysconfig": {
                k: str(sysconfig.get_config_var(k) or "")
                for k in ("SOABI", "MULTIARCH", "CONFIG_ARGS")
            },
            "target_platform": f"{sys.platform}-{platform.machine().lower()}",
            "sys_path": [],
            "sysconfig_paths": {},
            "stdlib_paths": [],
            "import_origins": {},
        }
    try:
        completed = subprocess.run(
            # Do not execute mutable ``.pth`` startup hooks while enumerating
            # the closure.  Inject only the already-selected distribution root.
            [
                str(path),
                "-X",
                "utf8",
                "-B",
                "-I",
                "-S",
                "-c",
                probe,
                str(site_root or ""),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
            env={
                **{
                    key: value
                    for key, value in os.environ.items()
                    if key
                    not in {
                        "DISPLAY",
                        "RFB_EPHEMERAL_PASSWORD",
                        "SSH_ASKPASS",
                        "SSH_ASKPASS_REQUIRE",
                    }
                },
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        info = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise PinnedRuntimeError("selected interpreter probe failed") from exc
    if not isinstance(info, dict) or not isinstance(info.get("sys_path"), list):
        raise PinnedRuntimeError("selected interpreter probe malformed")
    return info


def _native_closure(
    site: Path,
    target_platform: str,
    seed_paths: list[Path] | None = None,
    approved_roots: list[Path] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    native = [
        path
        for path in sorted(site.rglob("*"))
        if path.is_file()
        and (path.suffix.lower() in {".pyd", ".dll", ".dylib"} or ".so" in path.name)
    ]
    seeds = []
    for seed in seed_paths or []:
        if seed.is_file() and (
            seed.suffix.lower() in {".pyd", ".dll", ".dylib"} or ".so" in seed.name
        ):
            seeds.append(seed)
    native = sorted(set(native))
    seeds = sorted(set(seeds))
    if not native and not seeds:
        return [], []
    # Native dependency closure requires a target-platform-specific verifier.
    # Linux ELF is handled with the system ldd resolver; other formats remain
    # explicitly non-launchable rather than silently hashing only extensions.
    verifier = {"linux-x86_64", "linux-aarch64"}
    ldd = shutil.which("ldd")
    if target_platform not in verifier or ldd is None:
        raise PinnedRuntimeError(
            f"native closure verifier unavailable for target platform {target_platform}"
        )
    ldd_path = Path(ldd).resolve()
    if not ldd_path.is_file() or ldd_path.is_symlink():
        raise PinnedRuntimeError("native closure verifier unavailable")
    native_rows = [
        {
            "path": path.relative_to(site).as_posix(),
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
        for path in native
    ]
    runtime_library_index: dict[str, list[Path]] = {}
    if approved_roots:
        runtime_root = approved_roots[0].resolve()
        for candidate in runtime_root.rglob("*"):
            if candidate.is_file() and not candidate.is_symlink():
                runtime_library_index.setdefault(candidate.name, []).append(
                    candidate.resolve()
                )
    pending = [path.resolve() for path in [*native, *seeds]]
    seen: set[Path] = set()
    libraries: dict[Path, dict[str, Any]] = {}
    while pending:
        subject = pending.pop(0)
        if subject in seen:
            continue
        seen.add(subject)
        try:
            completed = subprocess.run(
                [str(ldd_path), str(subject)],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PinnedRuntimeError("native linked-library probe failed") from exc
        if completed.returncode != 0:
            raise PinnedRuntimeError("native linked-library probe failed")
        for raw_line in completed.stdout.splitlines():
            line = raw_line.strip()
            if not line or line == "statically linked" or line.startswith("linux-vdso"):
                continue
            if "not found" in line:
                library_name = line.split("=>", 1)[0].strip()
                matches = runtime_library_index.get(library_name, [])
                if len(matches) != 1:
                    raise PinnedRuntimeError("native linked-library unresolved")
                candidate = matches[0]
                if candidate not in libraries:
                    libraries[candidate] = {
                        "path": candidate.as_posix(),
                        "sha256": _sha256(candidate),
                        "size": candidate.stat().st_size,
                    }
                    pending.append(candidate)
                continue
            candidate_text = None
            if "=>" in line:
                candidate_text = line.split("=>", 1)[1].strip().split(None, 1)[0]
            elif line.startswith("/"):
                candidate_text = line.split(None, 1)[0]
            if not candidate_text:
                raise PinnedRuntimeError("native linked-library output unrecognized")
            candidate = Path(candidate_text).resolve()
            if not candidate.is_file():
                raise PinnedRuntimeError("native linked-library missing")
            if approved_roots and not any(
                candidate.is_relative_to(root.resolve()) for root in approved_roots
            ):
                raise PinnedRuntimeError("native linked-library outside approved roots")
            if candidate not in libraries:
                libraries[candidate] = {
                    "path": candidate.as_posix(),
                    "sha256": _sha256(candidate),
                    "size": candidate.stat().st_size,
                }
                pending.append(candidate)
    return native_rows, [libraries[path] for path in sorted(libraries)]


def _linker_identity() -> dict[str, Any]:
    path = shutil.which("ldd")
    if not path:
        return {}
    raw = Path(path)
    if raw.is_symlink():
        raise PinnedRuntimeError("native closure verifier symlink rejected")
    resolved = raw.resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise PinnedRuntimeError("native closure verifier unavailable")
    return {
        "path": resolved.as_posix(),
        "sha256": _sha256(resolved),
        "size": resolved.stat().st_size,
    }


def _stdlib_evidence(probe: Mapping[str, Any], root: Path) -> list[dict[str, Any]]:
    rows = []
    for raw in probe.get("stdlib_paths", []):
        path = Path(str(raw)).resolve()
        if not path.is_dir() or path.is_symlink():
            raise PinnedRuntimeError("stdlib root missing or symlinked")
        rows.append(
            {
                "path": _normalize_bound_path(path, root),
                "tree_sha256": _tree_hash(path),
            }
        )
    return rows


def _native_seed_paths(interpreter: Path, probe: Mapping[str, Any]) -> list[Path]:
    seeds = [interpreter]
    for raw in probe.get("stdlib_paths", []):
        root = Path(str(raw)).resolve()
        if root.is_dir():
            seeds.extend(
                path
                for path in root.rglob("*")
                if path.is_file()
                and (
                    path.suffix.lower() in {".pyd", ".dll", ".dylib"}
                    or ".so" in path.name
                )
            )
    return seeds


def _native_inventory(site: Path | None) -> list[dict[str, Any]]:
    if site is None or not site.is_dir():
        return []
    if any(path.is_symlink() for path in site.rglob("*")):
        raise PinnedRuntimeError("dependency symlink rejected")
    return [
        {
            "path": p.relative_to(site).as_posix(),
            "sha256": _sha256(p),
            "size": p.stat().st_size,
        }
        for p in sorted(site.rglob("*"))
        if p.is_file()
        and not p.is_symlink()
        and (p.suffix.lower() in {".pyd", ".dll", ".dylib"} or ".so" in p.name)
    ]


def _is_executable(path: Path) -> bool:
    return os.access(path, os.X_OK) and not (
        os.name == "nt" and path.suffix.lower() not in {".exe", ".cmd", ".bat"}
    )


def _profile_artifacts(root: Path) -> dict[str, str]:
    values = {
        "requirements_relative": "requirements.txt",
        "runtime_profile_relative": "runtime_profiles/tep_nonconfirmatory_v1.lock.json",
    }
    for key, rel in list(values.items()):
        path = root / _safe_relative(rel, field=key)
        current = path
        while current != root:
            if current.is_symlink():
                raise PinnedRuntimeError(f"{key} contains symlink")
            current = current.parent
        if not path.is_file() or path.is_symlink():
            raise PinnedRuntimeError(f"{key} missing or symlinked")
        values[key.removesuffix("_relative") + "_sha256"] = _sha256(path)
    return values


def _validate_probe(
    manifest: Mapping[str, Any], probe: Mapping[str, Any], root: Path
) -> None:
    interp = manifest.get("interpreter")
    expected = {
        "version": interp.get("version"),
        "implementation": interp.get("implementation"),
        "abi": interp.get("abi"),
        "build": interp.get("build"),
        "sysconfig": interp.get("sysconfig", {}),
    }
    if any(probe.get(key) != value for key, value in expected.items()):
        raise PinnedRuntimeError("selected interpreter metadata drift")
    if probe.get("target_platform") != manifest.get("target_platform"):
        raise PinnedRuntimeError("selected interpreter target platform drift")
    probe = _normalize_probe_paths(probe, root)
    expected_paths = manifest.get("ordered_sys_path_policy", [])
    actual_paths = []
    for item in probe.get("sys_path", []):
        candidate = Path(item).resolve()
        if not candidate.is_relative_to(root.resolve()):
            raise PinnedRuntimeError(
                "selected interpreter sys.path external and unbound"
            )
        actual_paths.append(
            _safe_relative(str(candidate.relative_to(root.resolve())), field="sys_path")
            if candidate.is_relative_to(root.resolve())
            else candidate.as_posix()
        )
    if actual_paths != expected_paths:
        raise PinnedRuntimeError("selected interpreter sys.path policy drift")


def _controller_target_platform() -> str:
    """Return the platform identity of the process doing controller staging."""
    return f"{sys.platform}-{platform.machine().lower()}"


def _verify_static_manifest_files(manifest: Mapping[str, Any], root: Path) -> None:
    """Verify a foreign runtime without executing its interpreter.

    Cross-target controllers (notably Windows staging a Linux closure) can
    prove confinement, manifest closure, and every static file hash. Dynamic
    interpreter/sysconfig/import/linker probing is deliberately deferred to
    the sealed target runtime in the transport layer.
    """
    root = root.resolve()

    def file_for(value: str, field: str) -> Path:
        rel = value.removeprefix("@ROOT/") if value.startswith("@ROOT/") else value
        path = (root / _safe_relative(rel, field=field)).resolve()
        _reject_symlink_ancestors(path, root)
        if not path.is_file() or path.is_symlink():
            raise PinnedRuntimeError(f"{field} missing or symlinked")
        return path

    interpreter = manifest.get("interpreter", {})
    path = file_for(str(interpreter.get("relative_path", "")), "interpreter")
    if _sha256(path) != interpreter.get("sha256"):
        raise PinnedRuntimeError("interpreter missing/unhashed/drifted")

    site_rel = manifest.get("site_packages_relative")
    site_root = None
    if site_rel is not None:
        site_root = root / _safe_relative(str(site_rel), field="site_packages_relative")
        _reject_symlink_ancestors(site_root, root)
        if not site_root.is_dir() or site_root.is_symlink():
            raise PinnedRuntimeError("dependency site-packages missing")
        actual = {
            p.relative_to(root).as_posix()
            for p in site_root.rglob("*")
            if p.is_file() and not p.is_symlink()
        }
        if any(p.is_symlink() for p in site_root.rglob("*")):
            raise PinnedRuntimeError("dependency symlink rejected")
        prefix = site_root.relative_to(root).as_posix() + "/"
        locked_paths = {
            str(item.get("path"))
            for dist in manifest.get("locked_distributions", [])
            for item in dist.get("files", [])
        }
        if actual != {p for p in locked_paths if p.startswith(prefix)}:
            raise PinnedRuntimeError("dependency tree contains extras or missing files")

    for distribution in manifest.get("locked_distributions", []):
        for item in distribution.get("files", []):
            candidate = file_for(str(item.get("path", "")), "distribution.path")
            if _sha256(candidate) != item.get(
                "sha256"
            ) or candidate.stat().st_size != item.get("size"):
                raise PinnedRuntimeError("dependency missing/unhashed/drifted")

    def verify_file_item(item: Mapping[str, Any], candidate: Path, field: str) -> None:
        _reject_symlink_ancestors(candidate, root)
        if (
            not candidate.is_file()
            or candidate.is_symlink()
            or _sha256(candidate) != item.get("sha256")
            or candidate.stat().st_size != item.get("size")
        ):
            raise PinnedRuntimeError(f"{field} drift")

    def validate_deferred_external(item: Mapping[str, Any], field: str) -> None:
        raw = str(item.get("path", ""))
        path = PurePosixPath(raw)
        if not path.is_absolute() or ".." in path.parts or str(path) != raw:
            raise PinnedRuntimeError(f"{field} external path invalid")
        digest = item.get("sha256")
        size = item.get("size")
        if (
            not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise PinnedRuntimeError(f"{field} external fingerprint invalid")

    native_items = manifest.get("native_extensions", [])
    native_paths = [str(item.get("path", "")) for item in native_items]
    if len(native_paths) != len(set(native_paths)):
        raise PinnedRuntimeError("native_extensions duplicate path")
    if native_items and site_root is None:
        raise PinnedRuntimeError("native extension site root missing")
    for item in native_items:
        candidate = (
            site_root
            / _safe_relative(str(item.get("path", "")), field="native_extensions")
        ).resolve()
        verify_file_item(item, candidate, "native_extensions")

    for field in ("native_seed_inventory", "linked_libraries"):
        items = manifest.get(field, [])
        paths = [str(item.get("path", "")) for item in items]
        if len(paths) != len(set(paths)):
            raise PinnedRuntimeError(f"{field} duplicate path")
        for item in items:
            raw = str(item.get("path", ""))
            if raw.startswith("@ROOT/"):
                verify_file_item(item, file_for(raw, field), field)
                continue
            validate_deferred_external(item, field)
            approved = [
                PurePosixPath(str(entry.get("path", "")))
                for entry in manifest.get("approved_external_roots", [])
            ]
            path = PurePosixPath(raw)
            if field == "linked_libraries" and not any(
                path == root_path or root_path in path.parents for root_path in approved
            ):
                raise PinnedRuntimeError("linked_libraries outside approved roots")
    linker = manifest.get("native_linker", {})
    if linker:
        raw = str(linker.get("path", ""))
        if raw.startswith("@ROOT/"):
            verify_file_item(linker, file_for(raw, "native_linker"), "native linker")
        else:
            validate_deferred_external(linker, "native_linker")

    for item in manifest.get("stdlib_evidence", []):
        raw = str(item.get("path", ""))
        if raw.startswith("@ROOT/"):
            stdlib = (
                root / _safe_relative(raw.removeprefix("@ROOT/"), field="stdlib.path")
            ).resolve()
        else:
            stdlib = Path(raw).resolve()
        _reject_symlink_ancestors(stdlib, root)
        if (
            not stdlib.is_dir()
            or stdlib.is_symlink()
            or _tree_hash(stdlib) != item.get("tree_sha256")
        ):
            raise PinnedRuntimeError("stdlib closure drift")

    # Fixture-only opaque interpreters may omit both profile artifacts.  A
    # foreign executable cannot be identified with the controller OS access
    # bits, so presence in the manifest (not local executability) controls
    # whether the artifacts must be verified.
    profile_artifacts = tuple(
        root / _safe_relative(str(value), field="runtime profile artifact")
        for value in (
            manifest.get("requirements_relative"),
            manifest.get("runtime_profile_relative"),
        )
    )
    profile_presence = tuple(path.is_file() for path in profile_artifacts)
    if any(profile_presence):
        if not all(profile_presence):
            raise PinnedRuntimeError("runtime profile artifact binding incomplete")
        for rel, key in (
            (manifest.get("requirements_relative"), "requirements_sha256"),
            (manifest.get("runtime_profile_relative"), "runtime_profile_sha256"),
        ):
            candidate = file_for(str(rel), "runtime profile artifact")
            if _sha256(candidate) != manifest.get(key):
                raise PinnedRuntimeError("runtime profile artifact drift")

    source = root / _safe_relative(
        str(manifest.get("source_root_relative", "")), field="source_root_relative"
    )
    _reject_symlink_ancestors(source, root)
    if not source.is_dir() or source.is_symlink():
        raise PinnedRuntimeError("rfb source inventory root missing")
    rows, source_hash = _source_inventory(source)
    if rows != manifest.get("rfb_source_inventory") or source_hash != manifest.get(
        "rfb_source_inventory_sha256"
    ):
        raise PinnedRuntimeError("rfb source closure drift")
    locked = manifest.get("locked_distributions", [])
    if hashlib.sha256(_canonical(locked)).hexdigest() != manifest.get(
        "dependency_lock_sha256"
    ):
        raise PinnedRuntimeError("dependency lock drift")


def build_pinned_manifest(
    root: str | Path,
    *,
    profile: str = PROFILE_ID,
    source_root: str | Path | None = None,
    interpreter: str | Path | None = None,
    site_packages: str | Path | None = None,
    target_platform: str | None = None,
    fixture_only: bool = False,
) -> dict[str, Any]:
    """Build a deterministic manifest; no files are written or launched."""
    if profile != PROFILE_ID:
        raise PinnedRuntimeError("mutable/unapproved runtime profile")
    root_path = Path(root).resolve()
    if root_path.is_symlink():
        raise PinnedRuntimeError("runtime root symlink rejected")
    source = Path(source_root).resolve() if source_root else root_path / "src" / "rfb"
    if not source.is_dir():
        raise PinnedRuntimeError("source inventory root missing")
    source_rows, source_hash = _source_inventory(source)
    try:
        source_relative = source.relative_to(root_path).as_posix()
    except ValueError as exc:
        raise PinnedRuntimeError("source inventory must be under runtime root") from exc
    interpreter_path = (
        Path(interpreter).resolve() if interpreter else Path(sys.executable).resolve()
    )
    _reject_symlink_ancestors(
        Path(interpreter) if interpreter else interpreter_path, root_path
    )
    try:
        interpreter_rel = interpreter_path.relative_to(root_path).as_posix()
    except ValueError:
        raise PinnedRuntimeError("interpreter must be materialized under runtime root")
    site = Path(site_packages).resolve() if site_packages else None
    probed = _probe_interpreter(interpreter_path, root_path, site)
    executable = _is_executable(interpreter_path)
    if not executable and not fixture_only:
        raise PinnedRuntimeError("selected interpreter is not executable")
    artifacts = (
        _profile_artifacts(root_path)
        if executable
        else {
            "requirements_relative": "requirements.txt",
            "runtime_profile_relative": "runtime_profiles/tep_nonconfirmatory_v1.lock.json",
            "requirements_sha256": _REQUIREMENTS_SHA256,
            "runtime_profile_sha256": _PROFILE_LOCK_SHA256,
        }
    )
    interpreter_info = {
        "relative_path": _safe_relative(
            interpreter_rel, field="interpreter.relative_path"
        ),
        "sha256": _sha256(interpreter_path),
        "version": probed["version"],
        "implementation": probed["implementation"],
        "abi": probed["abi"],
        "build": probed["build"],
        "sysconfig": probed.get("sysconfig", {}),
    }
    native_extensions = []
    native_seed_inventory = []
    linked_libraries = []
    approved_external_roots: list[Path] = []
    if target_platform in {"linux-x86_64", "linux-aarch64"}:
        approved_external_roots = sorted(
            {
                path.resolve()
                for path in map(
                    Path,
                    ("/lib", "/lib64", "/usr/lib", "/usr/lib64", "/usr/local/lib"),
                )
                if path.is_dir()
            }
        )
    if site is not None:
        for candidate in sorted(site.rglob("*")):
            if candidate.is_symlink():
                raise PinnedRuntimeError("dependency symlink rejected")
            if candidate.is_file() and (
                candidate.suffix.lower() in {".pyd", ".dll", ".dylib"}
                or ".so" in candidate.name
            ):
                native_extensions.append(
                    {
                        "path": candidate.relative_to(site).as_posix(),
                        "sha256": _sha256(candidate),
                        "size": candidate.stat().st_size,
                    }
                )
        native_extensions, linked_libraries = _native_closure(
            site,
            target_platform or "",
            seed_paths=_native_seed_paths(interpreter_path, probed),
            approved_roots=[root_path, *approved_external_roots],
        )
        linked_libraries = [
            {**item, "path": _normalize_bound_path(item["path"], root_path)}
            for item in linked_libraries
        ]
        native_seed_inventory = [
            {
                "path": _normalize_bound_path(seed.resolve(), root_path),
                "sha256": _sha256(seed),
                "size": seed.stat().st_size,
            }
            for seed in _native_seed_paths(interpreter_path, probed)
            if seed.is_file()
            and (
                seed.suffix.lower() in {".pyd", ".dll", ".dylib"} or ".so" in seed.name
            )
        ]
    sys_paths = []
    for item in probed.get("sys_path", []):
        if not item:
            continue
        candidate = Path(item).resolve()
        sys_paths.append(
            _safe_relative(str(candidate.relative_to(root_path)), field="sys_path")
            if candidate.is_relative_to(root_path)
            else candidate.as_posix()
        )
        if not candidate.is_relative_to(root_path) and not fixture_only:
            raise PinnedRuntimeError(
                "external sys.path requires approved materialized root"
            )
    locked_distributions = _distributions(site, root_path)
    dependency_lock_sha256 = hashlib.sha256(
        _canonical(locked_distributions)
    ).hexdigest()
    manifest: dict[str, Any] = {
        "schema_version": "pinned-runtime-manifest.v1",
        "runtime_format": RUNTIME_FORMAT,
        "runtime_dependency_profile": profile,
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "target_platform": target_platform or probed["target_platform"],
        "interpreter": interpreter_info,
        "source_root_relative": source_relative,
        "ordered_sys_path_policy": sys_paths,
        "sysconfig_paths": _normalize_probe_paths(probed, root_path).get(
            "sysconfig_paths", {}
        ),
        "stdlib_evidence": _stdlib_evidence(probed, root_path),
        "approved_external_roots": [
            {"path": path.as_posix()} for path in approved_external_roots
        ],
        "distribution_roots": [],
        "import_origins": _normalize_probe_paths(probed, root_path).get(
            "import_origins", {}
        ),
        "site_packages_relative": (
            _safe_relative(
                str(site.relative_to(root_path)), field="site_packages_relative"
            )
            if site is not None and site.is_relative_to(root_path)
            else None
        ),
        "locked_distributions": locked_distributions,
        "dependency_lock_sha256": dependency_lock_sha256,
        "requirements_sha256": _REQUIREMENTS_SHA256,
        "runtime_lock_sha256": _PROFILE_LOCK_SHA256,
        **artifacts,
        "native_extensions": native_extensions,
        "native_seed_inventory": native_seed_inventory,
        "linked_libraries": linked_libraries,
        "native_linker": _linker_identity() if native_extensions else {},
        "rfb_source_inventory": source_rows,
        "rfb_source_inventory_sha256": source_hash,
        "remote_materialization_verified": False,
    }
    manifest["closure_fingerprint"] = (
        "sha256:" + hashlib.sha256(_canonical(manifest)).hexdigest()
    )
    return manifest


def verify_pinned_manifest(
    manifest: Mapping[str, Any], root: str | Path, *, phase: str = "before_launch"
) -> dict[str, Any]:
    try:
        from jsonschema import Draft202012Validator

        schema_path = (
            Path(__file__).with_name("contracts")
            / "pinned_runtime_manifest.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = sorted(
            Draft202012Validator(schema).iter_errors(manifest),
            key=lambda e: list(e.path),
        )
        if errors:
            raise PinnedRuntimeError(f"manifest schema invalid: {errors[0].message}")
    except ImportError as exc:
        raise PinnedRuntimeError("manifest schema validator unavailable") from exc
    if (
        manifest.get("runtime_format") != RUNTIME_FORMAT
        or manifest.get("runtime_dependency_profile") != PROFILE_ID
    ):
        raise PinnedRuntimeError("runtime format/profile mismatch")
    if manifest.get("classification") != "DEVELOPMENT_NONCONFIRMATORY":
        raise PinnedRuntimeError("classification is not development-only")
    if manifest.get("remote_materialization_verified") is not False:
        raise PinnedRuntimeError("remote materialization may only be set by verifier")
    if manifest.get("requirements_sha256") != _REQUIREMENTS_SHA256:
        raise PinnedRuntimeError("requirements lock mismatch")
    if manifest.get("runtime_lock_sha256") != _PROFILE_LOCK_SHA256:
        raise PinnedRuntimeError("runtime profile lock mismatch")
    expected = manifest.get("closure_fingerprint")
    if not isinstance(expected, str) or not expected.startswith("sha256:"):
        raise PinnedRuntimeError("missing closure fingerprint")
    unsigned = dict(manifest)
    unsigned.pop("closure_fingerprint", None)
    actual = "sha256:" + hashlib.sha256(_canonical(unsigned)).hexdigest()
    if actual != expected:
        raise PinnedRuntimeError("closure drift")
    interpreter = manifest.get("interpreter")
    if not isinstance(interpreter, Mapping):
        raise PinnedRuntimeError("interpreter binding missing")
    rel = _safe_relative(
        str(interpreter.get("relative_path", "")), field="interpreter.relative_path"
    )
    raw_path = Path(root).resolve() / rel
    _reject_symlink_ancestors(raw_path, Path(root).resolve())
    if raw_path.is_symlink():
        raise PinnedRuntimeError("interpreter symlink rejected")
    path = raw_path.resolve()
    if (
        not path.is_file()
        or path.is_symlink()
        or _sha256(path) != interpreter.get("sha256")
    ):
        raise PinnedRuntimeError("interpreter missing/unhashed/drifted")
    # Cross-target staging is an explicit controller-only phase.  Ordinary
    # before/after verification never auto-downgrades based on host platform;
    # the sealed target transport must execute the full dynamic path.
    if phase == "controller_staging":
        _verify_static_manifest_files(manifest, Path(root).resolve())
        return dict(manifest)
    site_rel = manifest.get("site_packages_relative")
    site = None
    if site_rel is not None:
        site = (
            Path(root).resolve()
            / _safe_relative(str(site_rel), field="site_packages_relative")
        ).resolve()
        if not site.is_dir() or site.is_symlink():
            raise PinnedRuntimeError("dependency site-packages missing")
    probe = _probe_interpreter(path, Path(root).resolve(), site)
    _validate_probe(manifest, probe, Path(root).resolve())
    actual_native = _native_inventory(site)
    if actual_native != manifest.get("native_extensions", []):
        raise PinnedRuntimeError("native extension closure drift")
    actual_seeds = [
        {
            "path": _normalize_bound_path(seed.resolve(), Path(root).resolve()),
            "sha256": _sha256(seed),
            "size": seed.stat().st_size,
        }
        for seed in _native_seed_paths(path, probe)
        if seed.is_file()
        and (seed.suffix.lower() in {".pyd", ".dll", ".dylib"} or ".so" in seed.name)
    ]
    if actual_seeds != manifest.get("native_seed_inventory", []):
        raise PinnedRuntimeError("native seed closure drift")
    if actual_native and not manifest.get("linked_libraries"):
        raise PinnedRuntimeError("native linked-library closure missing")
    if not actual_native and manifest.get("linked_libraries"):
        raise PinnedRuntimeError("linked-library closure without native extension")
    if actual_native:
        linker = manifest.get("native_linker")
        current_linker = _linker_identity()
        if linker != current_linker:
            raise PinnedRuntimeError("native linker identity drift")
        _, actual_libraries = _native_closure(
            site,
            str(manifest.get("target_platform")),
            seed_paths=_native_seed_paths(path, probe),
            approved_roots=_approved_native_roots(manifest, Path(root).resolve()),
        )
        actual_libraries = [
            {**item, "path": _normalize_bound_path(item["path"], Path(root).resolve())}
            for item in actual_libraries
        ]
        if actual_libraries != manifest.get("linked_libraries"):
            raise PinnedRuntimeError("native linked-library closure drift")
    if _is_executable(path):
        artifacts = _profile_artifacts(Path(root).resolve())
        if manifest.get("requirements_relative") != artifacts["requirements_relative"]:
            raise PinnedRuntimeError("requirements artifact path drift")
        if (
            manifest.get("runtime_profile_relative")
            != artifacts["runtime_profile_relative"]
        ):
            raise PinnedRuntimeError("runtime profile artifact path drift")
        if manifest.get("requirements_sha256") != artifacts["requirements_sha256"]:
            raise PinnedRuntimeError("requirements artifact drift")
        if (
            manifest.get("runtime_profile_sha256")
            != artifacts["runtime_profile_sha256"]
        ):
            raise PinnedRuntimeError("runtime profile artifact drift")
    source_rel = _safe_relative(
        str(manifest.get("source_root_relative", "")), field="source_root_relative"
    )
    source = Path(root).resolve() / source_rel
    if source.is_dir():
        rows, source_hash = _source_inventory(source)
        if source_hash != manifest.get(
            "rfb_source_inventory_sha256"
        ) or rows != manifest.get("rfb_source_inventory"):
            raise PinnedRuntimeError("rfb source closure drift")
    else:
        raise PinnedRuntimeError("rfb source inventory root missing")
    locked = manifest.get("locked_distributions", [])
    lock_hash = hashlib.sha256(_canonical(locked)).hexdigest()
    if manifest.get("dependency_lock_sha256") != lock_hash:
        raise PinnedRuntimeError("dependency lock drift")
    # Every locked file must still exist with the exact hash.  An absent file
    # list is not treated as a wildcard: it is an intentionally empty lock.
    if site_rel is not None:
        site_root = (
            Path(root).resolve()
            / _safe_relative(site_rel, field="site_packages_relative")
        ).resolve()
        if not site_root.is_dir() or site_root.is_symlink():
            raise PinnedRuntimeError("dependency site-packages missing")
        actual = {
            p.relative_to(Path(root).resolve()).as_posix()
            for p in site_root.rglob("*")
            if p.is_file() and not p.is_symlink()
        }
        locked_paths = {
            str(item.get("path")) for dist in locked for item in dist.get("files", [])
        }
        site_prefix = site_root.relative_to(Path(root).resolve()).as_posix() + "/"
        locked_site_paths = {
            path for path in locked_paths if path.startswith(site_prefix)
        }
        if actual != locked_site_paths:
            raise PinnedRuntimeError("dependency tree contains extras or missing files")
    for distribution in manifest.get("locked_distributions", []):
        for item in distribution.get("files", []):
            rel = _safe_relative(str(item.get("path", "")), field="distribution.path")
            candidate = (Path(root).resolve() / rel).resolve()
            if (
                not candidate.is_file()
                or candidate.is_symlink()
                or _sha256(candidate) != item.get("sha256")
            ):
                raise PinnedRuntimeError("dependency missing/unhashed/drifted")
    if _stdlib_evidence(probe, Path(root).resolve()) != manifest.get(
        "stdlib_evidence", []
    ):
        raise PinnedRuntimeError("stdlib closure drift")
    normalized_probe = _normalize_probe_paths(probe, Path(root).resolve())
    if normalized_probe.get("sysconfig_paths", {}) != manifest.get(
        "sysconfig_paths", {}
    ):
        raise PinnedRuntimeError("sysconfig path drift")
    if normalized_probe.get("import_origins", {}) != manifest.get("import_origins", {}):
        raise PinnedRuntimeError("import origin drift")
    if phase not in {"before_launch", "after_run"}:
        raise PinnedRuntimeError("unknown verification phase")
    return dict(manifest)


verify_before_launch = verify_pinned_manifest
verify_after_run = verify_pinned_manifest


def verify_controller_staging(
    manifest: Mapping[str, Any], root: str | Path
) -> dict[str, Any]:
    """Verify static closure, plus the full probe when controller and target match."""
    verified = verify_pinned_manifest(manifest, root, phase="controller_staging")
    if str(manifest.get("target_platform")) == _controller_target_platform():
        return verify_pinned_manifest(manifest, root, phase="before_launch")
    return verified
