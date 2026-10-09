from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
REPO = WORKSPACE / "risk-fusion-bench"
EXCLUSIONS = {
    "tests/test_g018_phase0_qualification.py": "Historical phase-0 qualification packaging, not the local MME v2 execution contract.",
    "tests/test_g019_phase0_frozen_runtime.py": "Historical frozen-runtime rebuild/qualification, not the local MME v2 runtime.",
    "tests/test_g020_mme_authorization.py": "Retired authorization chain; current CLI protocol tests run separately.",
}
KNOWN_FAILURES = {
    "tests/test_g018_phase0_receipt_adversarial.py::test_resigned_review_locator_prefix_collision_is_rejected": "Historical qualification receipt cannot be regenerated against its prior frozen environment.",
    "tests/test_research_fake_e2e.py::test_installed_worker_rejects_legacy_phase_less_manifest": "Reproduced with pre-change controller/CLI copy; legacy worker returns rejection instead of raising expected ValueError.",
    "tests/test_research_fake_e2e.py::test_installed_worker_rejects_legacy_stale_preflight_manifest": "Reproduced with pre-change controller/CLI copy; legacy worker exception expectation differs.",
    "tests/test_research_fake_e2e.py::test_installed_worker_rejects_legacy_post_drift_manifest": "Reproduced with pre-change controller/CLI copy; legacy worker exception expectation differs.",
}


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = WORKSPACE / ".omx/mme-v2" / ("validation-" + stamp)
    output.mkdir(parents=True, exist_ok=False)
    sources = sorted(
        path
        for tree in (REPO / "src", REPO / "tests")
        for path in tree.rglob("*")
        if path.suffix in {".py", ".json"} and "__pycache__" not in path.parts
    )
    sources += [
        WORKSPACE / relative
        for relative in (
            "docs/MME-v2-design.md",
            ".omx/plans/MMEPreregistration-v2.json",
            "tools/validate_mme_v2.py",
        )
    ]
    source_records = [
        {
            "path": path.relative_to(WORKSPACE).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
        for path in sources
    ]
    env = os.environ.copy()
    env.update(
        PYTHONPATH=os.pathsep.join((str(REPO / "src"), str(REPO / "tests"))),
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    new_sources = sorted(
        path.relative_to(REPO).as_posix()
        for path in (REPO / "src/rfb/research").glob("mme_*.py")
        if path.name != "mme_authorization.py"
    )
    new_tests = sorted(
        path.relative_to(REPO).as_posix()
        for path in (REPO / "tests").glob("test_mme_*.py")
    )
    changed = (
        new_sources
        + new_tests
        + [
            "src/rfb/research/__main__.py",
            "src/rfb/research/controller.py",
            "tests/test_g020_mme_authorization.py",
        ]
    )
    commands = [
        ("mme_targeted", [sys.executable, "-B", "-m", "pytest", "-q", *new_tests]),
        (
            "current_cli",
            [
                sys.executable,
                "-B",
                "-m",
                "pytest",
                "-q",
                "tests/test_g020_mme_authorization.py",
                "-k",
                "legacy_authorization_flags or scope_guard",
            ],
        ),
        (
            "applicable_regression",
            [
                sys.executable,
                "-B",
                "-m",
                "pytest",
                "-q",
                *["--ignore=" + path for path in EXCLUSIONS],
                *["--deselect=" + path for path in KNOWN_FAILURES],
            ],
        ),
        ("ruff", ["ruff", "check", *changed]),
        ("ruff_format", ["ruff", "format", "--check", *changed]),
        ("compileall", [sys.executable, "-m", "compileall", "-q", "src", "tests"]),
        (
            "mypy_mme_scope",
            ["mypy", "--follow-imports=skip", "--ignore-missing-imports", *new_sources],
        ),
    ]
    checks = []
    for name, argv in commands:
        print("CHECK " + name, flush=True)
        started = datetime.now(UTC).isoformat()
        try:
            process = subprocess.run(
                argv,
                cwd=REPO,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1200,
                check=False,
            )
            code, log = process.returncode, process.stdout + process.stderr
        except (OSError, subprocess.TimeoutExpired) as error:
            code, log = -1, str(error)
        (output / (name + ".log")).write_text(log, encoding="utf-8")
        checks.append(
            {
                "name": name,
                "argv": argv,
                "returncode": code,
                "started_at": started,
                "finished_at": datetime.now(UTC).isoformat(),
                "log": name + ".log",
            }
        )
        print(
            name + ": " + str(code) + " " + log.strip().splitlines()[-1]
            if log.strip()
            else name + ": " + str(code),
            flush=True,
        )
    drift = [
        row["path"]
        for row in source_records
        if hashlib.sha256((WORKSPACE / row["path"]).read_bytes()).hexdigest()
        != row["sha256"]
    ]
    environment = {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "scipy", "jsonschema", "psutil", "pytest")
        },
    }
    with zipfile.ZipFile(
        output / "source_snapshot.zip", "x", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for row in source_records:
            archive.write(WORKSPACE / row["path"], row["path"])
    result = {
        "status": "PASS"
        if not drift and all(row["returncode"] == 0 for row in checks)
        else "FAILED",
        "checks": checks,
        "environment": environment,
        "source_drift": drift,
        "source_manifest": source_records,
        "known_exclusions": EXCLUSIONS,
        "known_baseline_failures": KNOWN_FAILURES,
        "mypy_limit": "MME sources checked; transitive imported modules skipped and missing third-party stubs ignored; no whole-repository typecheck claim.",
        "formal_admission": False,
        "mme_execution_performed_by_this_validator": False,
    }
    (output / "validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(str(output), flush=True)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
