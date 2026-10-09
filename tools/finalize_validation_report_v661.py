#!/usr/bin/env python3
"""Attach a fresh legacy smoke-test result to the v6.6.1 validation report."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "实验启动包v6.6.1-核验报告.json"
BENCH = ROOT / "risk-fusion-bench"


def main() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=BENCH,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + "\n" + result.stderr)
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    data["validated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    data["checks"]["legacy_code_smoke_tests"] = {
        "command": "python -m pytest -q",
        "result": result.stdout.strip(),
        "interpretation": "legacy v5 components remain healthy but are not v20-conformant experiment evidence",
    }
    REPORT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(REPORT)


if __name__ == "__main__":
    main()
