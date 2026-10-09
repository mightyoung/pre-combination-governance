#!/usr/bin/env python3
"""Print a dependency-free JSON profile for the v6.6 experiment server."""

from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def run(args: list[str]) -> dict[str, object]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=15, check=False)
        return {
            "available": True,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "error": type(exc).__name__}


def memory_bytes() -> tuple[int | None, int | None]:
    if os.name == "nt":
        fields = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]
        status_type = type("MEMORYSTATUSEX", (ctypes.Structure,), {"_fields_": fields})
        status = status_type()
        status.dwLength = ctypes.sizeof(status_type)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys), int(status.ullAvailPhys)
        return None, None

    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        values: dict[str, int] = {}
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0]) * 1024
        return values.get("MemTotal"), values.get("MemAvailable")
    return None, None


def gb(value: int | None) -> float | None:
    return None if value is None else round(value / (1024**3), 2)


def main() -> None:
    total_mem, available_mem = memory_bytes()
    disk = shutil.disk_usage(Path.cwd())
    nvidia = run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version,power.limit",
            "--format=csv,noheader,nounits",
        ]
    )
    profile = {
        "schema_version": "v6.6-server-profile-1.0",
        "status": "MEASURED",
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
        },
        "cpu": {
            "logical_processors": os.cpu_count(),
            "processor": platform.processor() or None,
        },
        "memory": {
            "total_gb": gb(total_mem),
            "available_gb": gb(available_mem),
        },
        "working_disk": {
            "path": str(Path.cwd().resolve()),
            "total_gb": gb(disk.total),
            "free_gb": gb(disk.free),
        },
        "gpu": nvidia,
        "container_runtime": {
            "docker": run(["docker", "--version"]),
            "podman": run(["podman", "--version"]),
        },
        "required_thresholds": {
            "minimum": {"logical_processors": 16, "memory_gb": 64, "free_nvme_gb": 1000},
            "recommended": {"logical_processors": 32, "memory_gb": 128, "free_nvme_gb": 2000},
        },
        "notes": [
            "GPU is optional for the v20 primary CSTR confirmation and is reserved for neural baselines or inference.",
            "CPU, RAM, disk throughput and reproducible containers dominate primary-run capacity.",
        ],
    }
    print(json.dumps(profile, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
