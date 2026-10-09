from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any

import psutil
from jsonschema import Draft202012Validator

from rfb.contracts.canonical_json import canonical_bytes, sha256_hex

from .mme_events import METHOD_IDS, MMEBlock, generate_block

RUN_CLASSES = ("D_impl_unit", "D_development", "MME_v2")
TERMINAL_STATES = frozenset(
    {"SUCCEEDED", "FAILED", "TIMEOUT", "CPU_LIMIT", "MEMORY_LIMIT", "UNEXECUTED"}
)
_PREDICTION_SCHEMA_PATH = Path(__file__).with_name("contracts") / "mme_v2_prediction.schema.json"
_PREDICTION_VALIDATOR = Draft202012Validator(
    json.loads(_PREDICTION_SCHEMA_PATH.read_text(encoding="utf-8"))
)


@dataclass(frozen=True, slots=True)
class MMERunConfig:
    output_root: str
    run_class: str = "D_development"
    run_id: str | None = None
    method_ids: tuple[str, ...] = METHOD_IDS
    method_cpu_seconds: float = 30.0
    method_wall_seconds: float = 60.0
    method_memory_bytes: int = 1_000_000_000
    max_output_bytes: int = 10_000_000
    workspace_root: str | None = None
    block_specs: tuple[Mapping[str, Any], ...] = ()
    design_paths: tuple[str, ...] = ()
    source_paths: tuple[str, ...] = ()
    input_paths: tuple[str, ...] = ()
    block_limit: int | None = None
    deterministic_replay: bool = True


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"non-JSON value: {type(value).__name__}")


def _read_config(config: Mapping[str, Any] | str | Path) -> tuple[dict[str, Any], Path | None]:
    if isinstance(config, Mapping):
        return dict(config), None
    path = Path(config).resolve(strict=True)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("MME config must be a JSON object")
    return value, path


def _validated_config(config: Mapping[str, Any] | str | Path) -> tuple[MMERunConfig, Path | None]:
    raw, config_path = _read_config(config)
    allowed = set(MMERunConfig.__dataclass_fields__)
    extra = set(raw) - allowed
    if extra:
        raise ValueError(f"unknown MME config fields: {sorted(extra)}")
    for key in ("method_ids", "block_specs", "design_paths", "source_paths", "input_paths"):
        if key in raw:
            if not isinstance(raw[key], (list, tuple)) or isinstance(raw[key], (str, bytes)):
                raise ValueError(f"{key} must be an array")
            raw[key] = tuple(raw[key])
    value = MMERunConfig(**raw)
    if value.run_class == "D_test" or value.run_class not in RUN_CLASSES:
        raise ValueError("run_class must be D_impl_unit, D_development, or MME_v2")
    if tuple(value.method_ids) != METHOD_IDS:
        raise ValueError("MME panel/order must be Proposed,B0-B5,ES-Rebuild")
    if (
        isinstance(value.method_cpu_seconds, bool)
        or not isinstance(value.method_cpu_seconds, (int, float))
        or not float(value.method_cpu_seconds) > 0
        or not float(value.method_cpu_seconds) < float("inf")
        or isinstance(value.method_wall_seconds, bool)
        or not isinstance(value.method_wall_seconds, (int, float))
        or not float(value.method_wall_seconds) > 0
        or not float(value.method_wall_seconds) < float("inf")
    ):
        raise ValueError("method CPU and wall limits must be positive")
    if (
        isinstance(value.method_memory_bytes, bool)
        or not isinstance(value.method_memory_bytes, int)
        or value.method_memory_bytes <= 0
        or isinstance(value.max_output_bytes, bool)
        or not isinstance(value.max_output_bytes, int)
        or value.max_output_bytes <= 0
    ):
        raise ValueError("method memory/output limits must be positive")
    if (
        value.block_limit is not None
        and (
            isinstance(value.block_limit, bool)
            or not isinstance(value.block_limit, int)
            or value.block_limit <= 0
        )
    ):
        raise ValueError("block_limit must be positive")
    if not isinstance(value.deterministic_replay, bool):
        raise ValueError("deterministic_replay must be boolean")
    return value, config_path


def _confined(path: str | Path, root: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=True)
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"binding path escapes workspace: {path}")
    if not resolved.is_file():
        raise ValueError(f"binding path is not a file: {path}")
    return resolved


def _reject_reparse_ancestors(path: Path, stop: Path) -> None:
    current = path
    while True:
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError(f"reparse path is forbidden: {current}")
        if current == stop or current.parent == current:
            return
        current = current.parent


def _file_bindings(cfg: MMERunConfig, config_path: Path | None) -> tuple[dict[str, Any], ...]:
    workspace = Path(cfg.workspace_root or Path.cwd()).resolve(strict=True)
    source_paths: Sequence[str | Path] = cfg.source_paths
    if not source_paths:
        source_paths = tuple(
            path
            for path in (
                Path(__file__),
                Path(__file__).with_name("mme_process.py"),
                Path(__file__).with_name("mme_events.py"),
                Path(__file__).with_name("mme_methods.py"),
                Path(__file__).with_name("mme_baselines.py"),
                Path(__file__).with_name("mme_oracle.py"),
                Path(__file__).with_name("mme_metrics.py"),
                _PREDICTION_SCHEMA_PATH,
            )
            if path.is_file()
        )
    design_paths: Sequence[str | Path] = cfg.design_paths
    if not design_paths:
        candidates = (
            workspace / ".omx" / "plans" / "MMEPreregistration-v2.json",
            workspace / ".omx" / "plans" / "下一步开发计划-MME科学闭环-20260907.md",
        )
        design_paths = tuple(path for path in candidates if path.is_file())
    groups: list[tuple[str, Sequence[str | Path]]] = [
        ("design", design_paths),
        ("source", source_paths),
        ("input", cfg.input_paths),
    ]
    if config_path is not None:
        groups.append(("config", (config_path,)))
    rows: list[dict[str, Any]] = []
    for kind, paths in groups:
        for raw in paths:
            path = _confined(raw, workspace)
            rows.append(
                {
                    "kind": kind,
                    "path": path.relative_to(workspace).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    return tuple(sorted(rows, key=lambda row: (row["kind"], row["path"])))


def _revalidate_bindings(cfg: MMERunConfig, expected: Sequence[Mapping[str, Any]]) -> None:
    workspace = Path(cfg.workspace_root or Path.cwd()).resolve(strict=True)
    for row in expected:
        path = _confined(str(row["path"]), workspace)
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise RuntimeError(f"MME_INTEGRITY_CHANGED:{row['kind']}:{row['path']}")


def _sync_directory(path: Path) -> bool:
    if os.name == "nt":
        return False
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return True


def _publish_new_json(path: Path, value: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_bytes(_json_value(value)) + b"\n"
    digest = hashlib.sha256(data).hexdigest()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    directory_synced = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
            raise OSError("MME_PARTIAL_READBACK_MISMATCH")
        if path.exists():
            raise FileExistsError(f"MME_IMMUTABLE_OUTPUT_EXISTS:{path}")
        if os.name == "nt":
            os.rename(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError:
                raise
            temporary.unlink()
            directory_synced = _sync_directory(path.parent)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise OSError("MME_PUBLISHED_READBACK_MISMATCH")
        return {
            "sha256": digest,
            "durability": "FILE_FSYNC_ATOMIC_CREATE_READBACK",
            "directory_fsync": directory_synced,
        }
    finally:
        if temporary.exists():
            temporary.unlink()


def _process_usage(process: psutil.Process) -> tuple[float, int]:
    cpu = 0.0
    rss = 0
    members = [process]
    try:
        members.extend(process.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    for member in members:
        try:
            times = member.cpu_times()
            cpu += float(times.user + times.system)
            rss += int(member.memory_info().rss)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return cpu, rss


def _terminate_tree(process: subprocess.Popen[str]) -> None:
    try:
        root = psutil.Process(process.pid)
        children = root.children(recursive=True)
        for child in reversed(children):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        try:
            root.kill()
        except psutil.NoSuchProcess:
            pass
        psutil.wait_procs([*children, root], timeout=2.0)
    except psutil.NoSuchProcess:
        pass


def _scientific_output(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _scientific_output(item)
            for key, item in value.items()
            if key not in {"cost", "measurements", "elapsed_ns", "wall_seconds", "cpu_seconds", "peak_rss_bytes"}
        }
    if isinstance(value, list):
        return [_scientific_output(item) for item in value]
    return value


def _validate_method_output(value: Mapping[str, Any]) -> None:
    errors = sorted(_PREDICTION_VALIDATOR.iter_errors(value), key=lambda row: list(row.path))
    if errors:
        raise ValueError(f"MME_METHOD_OUTPUT_SCHEMA_INVALID:{errors[0].message}")
    interval = value.get("risk_interval")
    if interval is not None and float(interval[0]) > float(interval[1]):
        raise ValueError("MME_METHOD_OUTPUT_INTERVAL_REVERSED")
    bpa = value.get("bpa")
    if isinstance(bpa, Mapping):
        focal_sets = bpa["focal_sets"]
        masses = bpa["masses"]
        if len(focal_sets) != len(masses) or abs(sum(float(row) for row in masses) - 1.0) > 1e-9:
            raise ValueError("MME_METHOD_OUTPUT_BPA_INVALID")


def _run_method_prefixes(method_id: str, prefixes: Sequence[Any], cfg: MMERunConfig) -> list[dict[str, Any]]:
    available_memory = int(psutil.virtual_memory().available)
    required_memory = max(cfg.method_memory_bytes + 256 * 1024 * 1024, 512 * 1024 * 1024)
    if available_memory < required_memory:
        raise RuntimeError(
            f"MME_LOCAL_MEMORY_PREFLIGHT_FAILED:available={available_memory}:required={required_memory}"
        )
    process_entry = Path(__file__).with_name("mme_process.py").resolve(strict=True)
    env = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    for key in ("SYSTEMROOT", "WINDIR"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="rfb-mme-method-") as child_cwd:
        process = subprocess.Popen(
            [sys.executable, "-I", "-X", "utf8", str(process_entry), method_id, "--stream"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=child_cwd,
            env=env,
            creationflags=creationflags,
            bufsize=1,
        )
        assert process.stdin is not None and process.stdout is not None
        ps_process = psutil.Process(process.pid)

        def request(payload: Mapping[str, Any]) -> dict[str, Any]:
            before_cpu, _ = _process_usage(ps_process)
            started = time.perf_counter()
            process.stdin.write(canonical_bytes(dict(payload)).decode("utf-8") + "\n")
            process.stdin.flush()
            responses: queue.Queue[str] = queue.Queue(maxsize=1)

            def receive() -> None:
                responses.put(process.stdout.readline())

            reader = threading.Thread(target=receive, daemon=True)
            reader.start()
            peak_rss = 0
            peak_cpu = 0.0
            limit_state: str | None = None
            while reader.is_alive():
                current_cpu, rss = _process_usage(ps_process)
                peak_cpu = max(peak_cpu, max(0.0, current_cpu - before_cpu))
                peak_rss = max(peak_rss, rss)
                elapsed = time.perf_counter() - started
                if rss > cfg.method_memory_bytes:
                    limit_state = "MEMORY_LIMIT"
                elif peak_cpu > cfg.method_cpu_seconds:
                    limit_state = "CPU_LIMIT"
                elif elapsed > cfg.method_wall_seconds:
                    limit_state = "TIMEOUT"
                if limit_state or process.poll() is not None:
                    _terminate_tree(process)
                    break
                time.sleep(0.005)
            reader.join(timeout=2.0)
            elapsed = time.perf_counter() - started
            measurements = {
                "wall_seconds": elapsed,
                "cpu_seconds": peak_cpu,
                "peak_rss_bytes": peak_rss,
                "sampling_interval_seconds": 0.005,
                "platform": sys.platform,
            }
            if limit_state:
                return {"status": limit_state, "failure_code": f"METHOD_{limit_state}", "measurements": measurements}
            try:
                line = responses.get_nowait()
            except queue.Empty:
                return {"status": "FAILED", "failure_code": "METHOD_PROCESS_FAILED", "measurements": measurements}
            if len(line.encode("utf-8")) > cfg.max_output_bytes:
                return {"status": "FAILED", "failure_code": "METHOD_OUTPUT_LIMIT", "measurements": measurements}
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                return {"status": "FAILED", "failure_code": "METHOD_OUTPUT_INVALID_JSON", "error": str(exc), "measurements": measurements}
            if not response.get("ok"):
                return {
                    "status": "FAILED",
                    "failure_code": "METHOD_TRUTH_ACCESS_DENIED" if response.get("truth_access_denied") else "METHOD_PROCESS_FAILED",
                    "error": f"{response.get('error_type')}:{response.get('error')}",
                    "measurements": measurements,
                }
            output = response.get("output")
            if not isinstance(output, dict):
                return {"status": "FAILED", "failure_code": "METHOD_OUTPUT_INVALID_JSON", "measurements": measurements}
            try:
                _validate_method_output(output)
                canonical_bytes(output)
            except (TypeError, ValueError) as exc:
                return {
                    "status": "FAILED",
                    "failure_code": "METHOD_OUTPUT_SCHEMA_INVALID",
                    "error": str(exc),
                    "measurements": measurements,
                }
            method_status = str(output.get("status", "SUCCEEDED"))
            status = "SUCCEEDED" if method_status == "SUCCEEDED" else "FAILED"
            return {
                "status": status,
                "failure_code": output.get("failure_code") if status == "FAILED" else None,
                "output": output,
                "measurements": measurements,
            }

        for prefix in prefixes:
            identity = {"prefix_id": prefix.prefix_id}
            first = request(prefix.method_payload())
            if first["status"] == "SUCCEEDED" and cfg.deterministic_replay:
                replay = request(prefix.method_payload())
                if replay["status"] != "SUCCEEDED" or canonical_bytes(
                    _scientific_output(first["output"])
                ) != canonical_bytes(_scientific_output(replay.get("output", {}))):
                    first = {
                        **first,
                        "status": "FAILED",
                        "failure_code": "METHOD_NONDETERMINISTIC_REPLAY",
                    }
                first["replay_verified"] = first["status"] == "SUCCEEDED"
            rows.append({**identity, **first})
            if first["status"] in {"MEMORY_LIMIT", "CPU_LIMIT", "TIMEOUT"} or first.get(
                "failure_code"
            ) == "METHOD_TRUTH_ACCESS_DENIED":
                break
        if process.poll() is None:
            process.stdin.close()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                _terminate_tree(process)
    return rows


def _blocks(cfg: MMERunConfig, supplied: Sequence[MMEBlock] | None) -> tuple[MMEBlock, ...]:
    if supplied is not None:
        rows = tuple(supplied)
    elif cfg.block_specs:
        rows = tuple(generate_block(spec, run_class=cfg.run_class) for spec in cfg.block_specs)
    else:
        try:
            from .mme_events import generate_experiment
        except ImportError as exc:
            raise ValueError("block_specs or blocks are required") from exc
        rows = tuple(generate_experiment(run_class=cfg.run_class))
    if cfg.block_limit is not None:
        rows = rows[: cfg.block_limit]
    if not rows or len({row.block_id for row in rows}) != len(rows):
        raise ValueError("MME blocks must be non-empty with unique block_id values")
    if any(row.run_class != cfg.run_class for row in rows):
        raise ValueError("MME block run_class differs from config")
    if cfg.run_class in {"D_development", "MME_v2"}:
        expected = tuple(prefix.prefix_id for prefix in generate_experiment(cfg.run_class)[0].prefixes)
        if any(tuple(prefix.prefix_id for prefix in row.prefixes) != expected for row in rows):
            raise ValueError("development and MME_v2 blocks require the complete prefix protocol")
    return rows


def _new_run_id(run_class: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"{run_class}-{stamp}-{uuid.uuid4().hex[:12]}"


def _run_location(cfg: MMERunConfig) -> tuple[Path, str, Path]:
    workspace = Path(cfg.workspace_root or Path.cwd()).resolve(strict=True)
    output_root = Path(cfg.output_root)
    if not output_root.is_absolute():
        output_root = workspace / output_root
    _reject_reparse_ancestors(output_root, workspace)
    output_root = output_root.resolve(strict=False)
    if output_root != workspace and workspace not in output_root.parents:
        raise ValueError("output_root escapes workspace")
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = cfg.run_id or _new_run_id(cfg.run_class)
    if not run_id or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id) is None:
        raise ValueError("run_id must be one safe path component")
    run_root = output_root / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    return workspace, run_id, run_root


@contextmanager
def _exclusive_run(run_root: Path):
    lock_path = run_root / ".mme-run.lock"
    token = uuid.uuid4().hex
    body = {"pid": os.getpid(), "token": token, "created_at_utc": datetime.now(UTC).isoformat()}
    while True:
        try:
            descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            try:
                owner = json.loads(lock_path.read_text(encoding="utf-8"))
                active = psutil.pid_exists(int(owner["pid"]))
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                active = False
            if active:
                raise RuntimeError("MME_RUN_ALREADY_ACTIVE")
            stale = run_root / f".mme-run.lock.stale.{uuid.uuid4().hex}"
            try:
                os.rename(lock_path, stale)
            except FileNotFoundError:
                continue
        else:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(canonical_bytes(body))
                stream.flush()
                os.fsync(stream.fileno())
            break
    try:
        yield
    finally:
        try:
            current = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = None
        if isinstance(current, Mapping) and current.get("token") == token:
            lock_path.unlink()
            _sync_directory(run_root)


def _locked(function):
    @wraps(function)
    def wrapper(config, *args, **kwargs):
        cfg, config_path = _validated_config(config)
        workspace, run_id, run_root = _run_location(cfg)
        normalized = asdict(cfg)
        normalized["run_id"] = run_id
        normalized["workspace_root"] = str(workspace)
        if config_path is not None:
            normalized["input_paths"] = tuple(cfg.input_paths) + (str(config_path),)
        with _exclusive_run(run_root):
            return function(normalized, *args, **kwargs)

    return wrapper


def _next_attempt(run_root: Path) -> tuple[str, Path]:
    attempts = run_root / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    numbers = []
    for path in attempts.glob("attempt-*"):
        try:
            numbers.append(int(path.name.removeprefix("attempt-")))
        except ValueError:
            continue
    number = max(numbers, default=0) + 1
    while True:
        attempt_id = f"attempt-{number:04d}"
        path = attempts / attempt_id
        try:
            path.mkdir(exist_ok=False)
        except FileExistsError:
            number += 1
            continue
        return attempt_id, path


def _completed_attempt(run_root: Path, protocol_sha256: str) -> dict[str, Any] | None:
    for path in sorted((run_root / "attempts").glob("attempt-*/run_result.json"), reverse=True):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if value.get("terminal_state") != "SUCCEEDED" or value.get("protocol_sha256") != protocol_sha256:
            continue
        for block in value.get("blocks", []):
            block_root = path.parent / "blocks" / str(block.get("block_id", ""))
            methods_path = block_root / "method_outputs.json"
            block_path = block_root / "block_result.json"
            try:
                methods_hash = hashlib.sha256(methods_path.read_bytes()).hexdigest()
                persisted = json.loads(block_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raise RuntimeError("MME_SEALED_ATTEMPT_INTEGRITY_FAILURE") from None
            if methods_hash != block.get("method_outputs_sha256") or persisted != block:
                raise RuntimeError("MME_SEALED_ATTEMPT_INTEGRITY_FAILURE")
        for name, expected_hash in value.get("report_files_sha256", {}).items():
            report_path = path.parent / "report" / str(name)
            try:
                actual_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
            except OSError:
                raise RuntimeError("MME_SEALED_ATTEMPT_INTEGRITY_FAILURE") from None
            if actual_hash != expected_hash:
                raise RuntimeError("MME_SEALED_ATTEMPT_INTEGRITY_FAILURE")
        return value
    return None


def _default_score(sidecar: Any, rows: Mapping[str, Any]) -> Mapping[str, Any]:
    from .mme_metrics import make_runner_scorer

    first = next(iter(rows.values()))
    return make_runner_scorer(first["_method_prefixes"])(sidecar, rows)


def _publish_report(attempt_root: Path, result: Mapping[str, Any]) -> dict[str, str]:
    from .mme_report import build_report_from_run_result, write_mme_report

    staging = Path(tempfile.mkdtemp(prefix=".report.", dir=attempt_root))
    destination = attempt_root / "report"
    try:
        paths = write_mme_report(build_report_from_run_result(result), staging)
        hashes: dict[str, str] = {}
        for path in paths.values():
            with path.open("r+b") as stream:
                os.fsync(stream.fileno())
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        _publish_new_json(
            staging / "report_manifest.json",
            {"files_sha256": hashes, "directory_fsync": os.name != "nt"},
        )
        if destination.exists():
            raise FileExistsError(f"MME_IMMUTABLE_OUTPUT_EXISTS:{destination}")
        os.rename(staging, destination)
        _sync_directory(attempt_root)
        for name, expected in hashes.items():
            if hashlib.sha256((destination / name).read_bytes()).hexdigest() != expected:
                raise OSError("MME_REPORT_READBACK_MISMATCH")
        return hashes
    finally:
        if staging.exists():
            shutil.rmtree(staging)


@_locked
def run_mme(
    config: Mapping[str, Any] | str | Path,
    *,
    blocks: Sequence[MMEBlock] | None = None,
    scorer: Callable[[Any, Mapping[str, Any]], Mapping[str, Any]] | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    cfg, config_path = _validated_config(config)
    selected_blocks = _blocks(cfg, blocks)
    bindings = _file_bindings(cfg, config_path)
    workspace, run_id, run_root = _run_location(cfg)
    protocol = {
        "schema_version": "MME_LOCAL_RUN_V2",
        "run_id": run_id,
        "run_class": cfg.run_class,
        "method_order": list(cfg.method_ids),
        "prefix_order": [prefix.prefix_id for prefix in selected_blocks[0].prefixes],
        "block_ids": [block.block_id for block in selected_blocks],
        "limits": {
            "cpu_seconds": cfg.method_cpu_seconds,
            "wall_seconds": cfg.method_wall_seconds,
            "memory_bytes": cfg.method_memory_bytes,
            "max_output_bytes": cfg.max_output_bytes,
        },
        "method_isolation": "TRUSTED_PYTHON_AUDIT_HOOK_NOT_OS_SECURITY_SANDBOX",
        "integrity_bindings": list(bindings),
        "public_input_sha256": sha256_hex(
            canonical_bytes(
                [
                    {
                        "block_id": block.block_id,
                        "prefixes": [prefix.method_payload() for prefix in block.prefixes],
                    }
                    for block in selected_blocks
                ]
            )
        ),
    }
    protocol["protocol_sha256"] = sha256_hex(canonical_bytes(protocol))
    protocol_path = run_root / "run_protocol.json"
    if protocol_path.exists():
        current = json.loads(protocol_path.read_text(encoding="utf-8"))
        if current != protocol:
            raise ValueError("MME_RUN_ID_PROTOCOL_COLLISION")
    else:
        _publish_new_json(protocol_path, protocol)
    if resume:
        completed = _completed_attempt(run_root, protocol["protocol_sha256"])
        if completed is not None:
            return {**completed, "deduplicated_resume": True}
    attempt_id, attempt_root = _next_attempt(run_root)
    started = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    block_results: list[dict[str, Any]] = []
    hard_stop: str | None = None
    for block in selected_blocks:
        method_rows: dict[str, Any] = {}
        for method_id in cfg.method_ids:
            if hard_stop or block.generation_status != "SUPPORTED":
                reason = hard_stop or block.generation_status
                prefix_rows = [
                    {"prefix_id": prefix.prefix_id, "status": "UNEXECUTED", "failure_code": reason}
                    for prefix in block.prefixes
                ]
            else:
                prefix_rows = _run_method_prefixes(method_id, block.prefixes, cfg)
                if len(prefix_rows) < len(block.prefixes):
                    reason = str(prefix_rows[-1].get("failure_code", "METHOD_HARD_STOP"))
                    prefix_rows.extend(
                        {
                            "prefix_id": prefix.prefix_id,
                            "status": "UNEXECUTED",
                            "failure_code": reason,
                        }
                        for prefix in block.prefixes[len(prefix_rows) :]
                    )
                for result in prefix_rows:
                    if result["status"] in {"MEMORY_LIMIT", "CPU_LIMIT", "TIMEOUT"} or result.get(
                        "failure_code"
                    ) == "METHOD_TRUTH_ACCESS_DENIED":
                        hard_stop = str(result["failure_code"])
                        break
            statuses = {row["status"] for row in prefix_rows}
            terminal = (
                "SUCCEEDED"
                if statuses == {"SUCCEEDED"}
                else next(
                    (state for state in ("MEMORY_LIMIT", "CPU_LIMIT", "TIMEOUT", "FAILED") if state in statuses),
                    "UNEXECUTED",
                )
            )
            method_rows[method_id] = {
                "method_id": method_id,
                "terminal_state": terminal,
                "prefixes": prefix_rows,
                "_method_prefixes": list(block.prefixes),
            }
        durable_methods = {
            method_id: {key: value for key, value in row.items() if not key.startswith("_")}
            for method_id, row in method_rows.items()
        }
        block_root = attempt_root / "blocks" / block.block_id
        methods_receipt = _publish_new_json(block_root / "method_outputs.json", durable_methods)
        scoring = dict((scorer or _default_score)(block.truth_sidecar, method_rows))
        block_document = {
            "block_id": block.block_id,
            "method_outputs_sha256": methods_receipt["sha256"],
            "scoring": _json_value(scoring),
            "truth_used_after_methods_sealed": True,
        }
        _publish_new_json(block_root / "block_result.json", block_document)
        block_results.append(block_document)
    _revalidate_bindings(cfg, bindings)
    terminals = [
        row["terminal_state"]
        for block in selected_blocks
        for row in json.loads(
            (attempt_root / "blocks" / block.block_id / "method_outputs.json").read_text(encoding="utf-8")
        ).values()
    ]
    terminal_state = "SUCCEEDED" if all(row == "SUCCEEDED" for row in terminals) else "COMPLETED_WITH_FAILURES"
    result = {
        "schema_version": "MME_LOCAL_RESULT_V2",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "run_class": cfg.run_class,
        "terminal_state": terminal_state,
        "status": terminal_state,
        "hard_stop_code": hard_stop,
        "protocol_sha256": protocol["protocol_sha256"],
        "started_at_utc": started,
        "finished_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "attempt_path": str(attempt_root),
        "block_count": len(selected_blocks),
        "method_slot_count": len(selected_blocks) * len(cfg.method_ids),
        "method_terminal_counts": {state: terminals.count(state) for state in sorted(set(terminals))},
        "blocks": block_results,
        "measurements_excluded_from_replay_identity": True,
        "deduplicated_resume": False,
    }
    result["report_files_sha256"] = _publish_report(attempt_root, result)
    _publish_new_json(attempt_root / "run_result.json", result)
    return result


__all__ = ["MMERunConfig", "RUN_CLASSES", "run_mme"]
