import subprocess
import sys
import os
from pathlib import Path


def _run(*args):
    env = os.environ.copy()
    src = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "rfb.research", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_cli_help():
    p = _run("--help")
    assert p.returncode == 0 and "verify-remote" in p.stdout


def test_cli_invalid_command_exit_code():
    p = _run("verify-remote", "--receipt", "missing")
    assert p.returncode != 0
