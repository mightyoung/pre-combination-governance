"""Execute the pinned PCG CPU replay on a disposable user checkout and bundle evidence.

This command is for the user's server. Cloud development should run only its
isolated unit tests, never this replay command.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable
import uuid

try:
    import resource
except ImportError:  # pragma: no cover - platform-specific fallback
    resource = None

from .user_cpu_replay_handoff import (
    BASE_RUNNER_COMMIT,
    EXPECTED_COMMANDS,
    FAILURE_ARTIFACTS,
    HandoffValidationError,
    PASS_ARTIFACTS,
    PRE_RUN_MANIFEST_SHA256,
    RESULT_SCHEMA_SHA256,
    SCHEMA_VERSION,
    SCORER_TRUTH_MANIFEST_SHA256,
    SOURCE_SAMPLE_BYTES,
    SOURCE_SAMPLE_SHA256,
    TASK_ID,
    validate_user_cpu_replay_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
RUN_RELATIVE = Path(
    "research-three/v2-alignment-20261011/runs/"
    "two-hop-lineage-controlled-synthetic-20261012-v2"
)
SOURCE_SAMPLE_RELATIVE = Path(
    "research-three/v2-alignment-20261011/source-audit/usgs-summary-20261011/"
    "REAL_PUBLIC_FEED_SAMPLE.json"
)
GENERATED_RUN_FILES = (
    "METHOD_OUTPUTS_V2.json",
    "METHOD_OUTPUT_FREEZE_V2.json",
    "RUNNER_CHECKS_V2.json",
    "SCORED_RESULT_V2.json",
    "ALIAS_HOP1_V2.json",
    "ALIAS_HOP2_V2.json",
    "SIDEINPUT_NEGATIVE_HOP2_V2.json",
)
RUN_ARTIFACTS = tuple(sorted(PASS_ARTIFACTS - set(FAILURE_ARTIFACTS)))
LOG_ARTIFACTS = ("commands.txt", "environment.json", "stdout.log", "stderr.log")
MAX_WALL_SECONDS = 300
MAX_PEAK_MEMORY_MIB = 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _run_process(
    command: list[str],
    *,
    cwd: Path,
    process_runner: Callable[..., Any],
    timeout: float | None = None,
    env: dict[str, str] | None = None,
) -> Any:
    kwargs: dict[str, Any] = {
        "cwd": cwd,
        "check": False,
        "capture_output": True,
        "text": True,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    if env is not None:
        kwargs["env"] = env
    return process_runner(command, **kwargs)


def _git_value(root: Path, args: list[str], process_runner: Callable[..., Any]) -> str | None:
    try:
        completed = _run_process(["git", *args], cwd=root, process_runner=process_runner)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return _as_text(completed.stdout).strip()


def _peak_memory_mib() -> float | None:
    if resource is None:
        return None
    try:
        peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    except (AttributeError, OSError, ValueError):
        return None
    # Darwin reports bytes; Linux and the other supported Unix runners report KiB.
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(float(peak) / divisor, 6)


def _environment_snapshot() -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count() or 1,
        "gpu_used": False,
        "network_calls_after_checkout": False,
        "model_called": False,
        "notification_called": False,
        "packages_installed_for_task": [],
    }


def _expected_pins() -> dict[str, Any]:
    return {
        "pre_run_manifest_sha256": PRE_RUN_MANIFEST_SHA256,
        "scorer_truth_manifest_sha256": SCORER_TRUTH_MANIFEST_SHA256,
        "source_sample_sha256": SOURCE_SAMPLE_SHA256,
        "source_sample_bytes": SOURCE_SAMPLE_BYTES,
    }


def _observed_pins(runner_root: Path) -> dict[str, Any] | None:
    run_dir = runner_root / RUN_RELATIVE
    paths = {
        "pre_run_manifest_sha256": run_dir / "PRE_RUN_MANIFEST_V2.json",
        "scorer_truth_manifest_sha256": run_dir / "SCORER_TRUTH_MANIFEST_V2.json",
        "source_sample_sha256": runner_root / SOURCE_SAMPLE_RELATIVE,
    }
    if not all(path.is_file() and not path.is_symlink() for path in paths.values()):
        return None
    sample_path = paths["source_sample_sha256"]
    sample_raw = sample_path.read_bytes()
    return {
        "pre_run_manifest_sha256": _sha256(paths["pre_run_manifest_sha256"].read_bytes()),
        "scorer_truth_manifest_sha256": _sha256(paths["scorer_truth_manifest_sha256"].read_bytes()),
        "source_sample_sha256": _sha256(sample_raw),
        "source_sample_bytes": len(sample_raw),
    }


def _outcome_from_bundle(bundle_dir: Path) -> dict[str, Any] | None:
    runner_path = bundle_dir / "RUNNER_CHECKS_V2.json"
    scorer_path = bundle_dir / "SCORED_RESULT_V2.json"
    try:
        runner = json.loads(runner_path.read_text(encoding="utf-8"))
        scorer = json.loads(scorer_path.read_text(encoding="utf-8"))
        method_hash = runner["method_outputs_sha256_at_freeze"]
        checks = runner["checks"]
        conditions = scorer["conditions"]
        def counts(key: str) -> dict[str, int]:
            values = conditions[key]["counts"]
            return {
                "confirmed": values["confirmed_shared_ancestor"],
                "unknown": values["unknown"],
            }
        side_input = scorer["side_input_negative_control"]
        return {
            "method_outputs_sha256": method_hash,
            "runner_checks_total": len(checks),
            "runner_checks_passed": sum(value is True for value in checks.values()),
            "full_receipt_chain": counts("FULL_RECEIPT_CHAIN"),
            "missing_hop2_receipt": counts("MISSING_INTERMEDIATE_RECEIPT"),
            "hash_only": counts("HASH_ONLY_DEDUP"),
            "side_input_receipt_status": side_input["receipt_validation_status"],
            "side_input_lineage_status": side_input["lineage_status"],
            "production_truth_denominator": scorer["production_truth_denominator"],
            "production_accuracy": scorer["production_accuracy"],
            "wrong_confirmed_attribution_status": scorer["wrong_confirmed_attribution_status"],
            "pair_rows_independent": scorer["pair_rows_are_independent_samples"],
        }
    except (KeyError, OSError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _artifact_manifest(bundle_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(bundle_dir.iterdir(), key=lambda item: item.name):
        if path.name == "TASK_RESULT.json" or not path.is_file() or path.is_symlink():
            continue
        raw = path.read_bytes()
        rows.append({"path": path.name, "bytes": len(raw), "sha256": _sha256(raw)})
    return rows


def _copy_run_artifacts(runner_root: Path, bundle_dir: Path, reasons: list[str]) -> set[str]:
    source_dir = runner_root / RUN_RELATIVE
    copied: set[str] = set()
    for name in RUN_ARTIFACTS:
        source = source_dir / name
        if not source.exists():
            continue
        if source.is_symlink() or not source.is_file():
            reasons.append(f"refused non-regular run artifact: {name}")
            continue
        try:
            shutil.copyfile(source, bundle_dir / name)
        except OSError as exc:
            reasons.append(f"could not copy {name}: {exc}")
            continue
        copied.add(name)
    return copied


def _write_logs(bundle_dir: Path, stdout_parts: list[str], stderr_parts: list[str]) -> None:
    (bundle_dir / "commands.txt").write_text("\n".join(EXPECTED_COMMANDS) + "\n", encoding="utf-8")
    (bundle_dir / "stdout.log").write_text("".join(stdout_parts), encoding="utf-8")
    (bundle_dir / "stderr.log").write_text("".join(stderr_parts), encoding="utf-8")


def execute_user_cpu_replay(
    *,
    runner_root: Path,
    bundle_dir: Path,
    run_id: str | None = None,
    handoff_root: Path = REPO_ROOT,
    process_runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run only the pinned V2 runner/scorer and write TASK_RESULT.json.

    ``process_runner`` exists for isolated contract tests. Production use must
    leave it unset so the two checked-in Python entry points run normally.
    """
    process_runner = process_runner or subprocess.run
    runner_root = Path(runner_root).resolve()
    handoff_root = Path(handoff_root).resolve()
    bundle_dir = Path(bundle_dir).resolve()
    if bundle_dir.exists():
        raise FileExistsError(f"bundle directory already exists: {bundle_dir}")
    if bundle_dir.is_relative_to(runner_root):
        raise ValueError("bundle directory must be outside the disposable runner checkout")
    if run_id is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"user-cpu-replay-{stamp}-{uuid.uuid4().hex[:8]}"
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,100}", run_id) is None:
        raise ValueError("run_id must be a unique path-safe identifier")

    handoff_commit = _git_value(handoff_root, ["rev-parse", "HEAD"], subprocess.run)
    if handoff_commit is None or re.fullmatch(r"[0-9a-f]{40}", handoff_commit) is None:
        raise RuntimeError("handoff checkout must have a readable full Git commit")

    bundle_dir.mkdir(parents=True)
    started_at = _utc_now()
    environment = _environment_snapshot()
    reasons: list[str] = []
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    observed_runner_commit = _git_value(runner_root, ["rev-parse", "HEAD"], process_runner)
    status_text = _git_value(runner_root, ["status", "--porcelain", "--untracked-files=all"], process_runner)
    task_status = "BLOCKED"
    runner_exit_code: int | None = None
    scorer_exit_code: int | None = None
    wall_time_seconds: float | None = None
    peak_memory_mib: float | None = None
    execution_started = time.monotonic()
    execution_attempted = False

    if observed_runner_commit != BASE_RUNNER_COMMIT:
        reasons.append("runner checkout does not match the pinned base commit")
    elif status_text is None:
        reasons.append("cannot verify runner checkout status")
    elif status_text:
        reasons.append("runner checkout is not clean before the replay")
    elif _parse_version(platform.python_version()) < (3, 11):
        reasons.append("Python >=3.11 is required")
    elif resource is None or _peak_memory_mib() is None:
        reasons.append("platform does not provide a measurable child-process peak memory value")
    else:
        unresolved_run_dir = runner_root / RUN_RELATIVE
        run_dir = unresolved_run_dir.resolve()
        if unresolved_run_dir.is_symlink() or not run_dir.is_relative_to(runner_root) or not run_dir.is_dir():
            reasons.append("pinned V2 run directory is missing or outside runner checkout")
        elif any((run_dir / name).is_symlink() for name in GENERATED_RUN_FILES):
            reasons.append("generated V2 output path is a symlink; refusing to remove it")
        else:
            for name in GENERATED_RUN_FILES:
                output_path = run_dir / name
                if output_path.exists():
                    output_path.unlink()
            task_status = "FAIL"
            execution_attempted = True
            execution_started = time.monotonic()
            python_command = shutil.which("python") or sys.executable
            env = os.environ.copy()
            env["PYTHONPATH"] = "risk-fusion-bench/src"
            script_paths = (
                "research-three/v2-alignment-20261011/runs/"
                "two-hop-lineage-controlled-synthetic-20261012-v2/run_two_hop_lineage_v2.py",
                "research-three/v2-alignment-20261011/runs/"
                "two-hop-lineage-controlled-synthetic-20261012-v2/score_two_hop_lineage_v2.py",
            )
            stage_names = ("runner", "scorer")
            exits: list[int | None] = []
            for stage_name, script_path in zip(stage_names, script_paths):
                elapsed = time.monotonic() - execution_started
                remaining = MAX_WALL_SECONDS - elapsed
                if remaining <= 0:
                    reasons.append("combined runner/scorer execution exceeded 300 seconds")
                    exits.append(None)
                    break
                command = [python_command, script_path]
                try:
                    completed = _run_process(
                        command, cwd=runner_root, process_runner=process_runner,
                        timeout=remaining, env=env,
                    )
                    stage_exit = int(completed.returncode)
                    stdout_parts.append(f"=== {stage_name} ===\n{_as_text(completed.stdout)}")
                    stderr_parts.append(f"=== {stage_name} ===\n{_as_text(completed.stderr)}")
                except subprocess.TimeoutExpired as exc:
                    stage_exit = 124
                    stdout_parts.append(f"=== {stage_name} (timeout) ===\n{_as_text(exc.stdout)}")
                    stderr_parts.append(f"=== {stage_name} (timeout) ===\n{_as_text(exc.stderr)}")
                    reasons.append(f"{stage_name} exceeded the remaining five-minute execution budget")
                except OSError as exc:
                    stage_exit = 127
                    stderr_parts.append(f"=== {stage_name} (launch error) ===\n{exc}\n")
                    reasons.append(f"could not launch {stage_name}: {exc}")
                exits.append(stage_exit)
                current_peak = _peak_memory_mib()
                if current_peak is not None:
                    peak_memory_mib = max(peak_memory_mib or 0.0, current_peak)
                if stage_exit != 0:
                    reasons.append(f"{stage_name} exited with status {stage_exit}")
                    break
                if peak_memory_mib is None:
                    reasons.append("peak memory measurement became unavailable during execution")
                    break
                if peak_memory_mib > MAX_PEAK_MEMORY_MIB:
                    reasons.append("execution exceeded the 1024 MiB peak memory ceiling")
                    break
            runner_exit_code = exits[0] if exits else None
            scorer_exit_code = exits[1] if len(exits) > 1 else None
            wall_time_seconds = round(time.monotonic() - execution_started, 6)
            if wall_time_seconds > MAX_WALL_SECONDS:
                reasons.append("execution exceeded the 300-second wall-time ceiling")
            if runner_exit_code == 0 and scorer_exit_code == 0 and not reasons:
                task_status = "PASS"
            elif peak_memory_mib is None and not any("exited with status" in item for item in reasons):
                task_status = "BLOCKED"

    if not execution_attempted and not reasons:
        reasons.append("runner preconditions were not met")
    observed_pins = _observed_pins(runner_root)
    if observed_pins is not None and observed_pins != _expected_pins():
        reasons.append("observed input pins differ from the frozen V2 task inputs")
        if task_status == "PASS":
            task_status = "FAIL"
    copied = _copy_run_artifacts(runner_root, bundle_dir, reasons) if execution_attempted else set()
    _write_logs(bundle_dir, stdout_parts, stderr_parts)
    _write_json(bundle_dir / "environment.json", environment)

    if task_status == "PASS":
        missing = sorted(set(PASS_ARTIFACTS) - (copied | set(LOG_ARTIFACTS)))
        if missing:
            task_status = "FAIL"
            reasons.append(f"successful command exits did not produce required artifacts: {missing}")

    outcome = _outcome_from_bundle(bundle_dir)
    if task_status == "PASS" and outcome is None:
        task_status = "FAIL"
        reasons.append("runner/scorer outputs do not contain a complete outcome summary")

    finished_at = _utc_now()
    result = {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "run_id": run_id,
        "task_status": task_status,
        "target_runner_commit": BASE_RUNNER_COMMIT,
        "handoff_code_commit": handoff_commit,
        "result_schema_sha256": RESULT_SCHEMA_SHA256,
        "observed_runner_commit": observed_runner_commit,
        "execution": {
            "started_at_utc": started_at,
            "finished_at_utc": finished_at,
            **environment,
            "commands": list(EXPECTED_COMMANDS),
            "wall_time_seconds": wall_time_seconds,
            "peak_memory_mib": peak_memory_mib,
            "runner_exit_code": runner_exit_code,
            "scorer_exit_code": scorer_exit_code,
        },
        "expected_input_pins": _expected_pins(),
        "observed_input_pins": observed_pins,
        "outcome": outcome,
        "failure_reasons": [] if task_status == "PASS" else (reasons or ["replay did not pass"]),
        "artifacts": _artifact_manifest(bundle_dir),
    }
    _write_json(bundle_dir / "TASK_RESULT.json", result)
    if task_status == "PASS":
        try:
            validate_user_cpu_replay_bundle(bundle_dir, handoff_root)
        except HandoffValidationError as exc:
            result["task_status"] = "FAIL"
            result["outcome"] = None
            result["failure_reasons"] = [f"frozen mechanics validation failed: {exc}"]
            _write_json(bundle_dir / "TASK_RESULT.json", result)
    return result


def _parse_version(value: str) -> tuple[int, int]:
    match = re.match(r"^(\d+)\.(\d+)", value)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-root", required=True, type=Path,
                        help="clean detached Git worktree at the pinned V2 runner commit")
    parser.add_argument("--bundle-dir", required=True, type=Path,
                        help="new output folder outside the disposable runner worktree")
    parser.add_argument("--run-id", help="optional unique path-safe result ID")
    args = parser.parse_args()
    try:
        result = execute_user_cpu_replay(
            runner_root=args.runner_root,
            bundle_dir=args.bundle_dir,
            run_id=args.run_id,
        )
    except (FileExistsError, OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"bundle_written": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({
        "bundle_written": True,
        "task_status": result["task_status"],
        "run_id": result["run_id"],
        "bundle_dir": str(args.bundle_dir),
    }, ensure_ascii=False, sort_keys=True))
    # A structurally written FAIL/BLOCKED bundle is still a successful
    # generation step; the recorded task_status carries the replay outcome.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
