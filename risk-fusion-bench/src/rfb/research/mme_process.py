from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


_DENIED_KEY_PARTS = ("truth", "oracle", "sidecar", "future")
_DENIED_MODULE_STEMS = {
    "mme_events",
    "mme_metrics",
    "mme_oracle",
    "mme_runner",
    "scorer_owner",
}
_RUN_METHOD: Any = None


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    return any(resolved == root or root in resolved.parents for root in roots)


def _install_read_boundary(source_root: Path) -> None:
    roots = tuple(
        dict.fromkeys(
            Path(value).resolve(strict=False)
            for value in (source_root, sys.base_prefix, sys.prefix)
        )
    )

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event in {
            "subprocess.Popen",
            "os.system",
            "socket.__new__",
            "socket.connect",
            "ctypes.dlopen",
        }:
            raise PermissionError("MME_METHOD_CAPABILITY_DENIED")
        if event not in {"open", "os.open"} or not args:
            return
        target = args[0]
        if isinstance(target, int):
            return
        try:
            path = Path(os.fsdecode(target))
        except (TypeError, ValueError):
            raise PermissionError("MME_METHOD_FILESYSTEM_READ_DENIED") from None
        if not path.is_absolute():
            path = Path.cwd() / path
        mode = args[1] if len(args) > 1 else "r"
        flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
        if (
            isinstance(mode, str) and any(character in mode for character in "wax+")
        ) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise PermissionError("MME_METHOD_FILESYSTEM_WRITE_DENIED")
        if path.stem.split(".")[0] in _DENIED_MODULE_STEMS:
            raise PermissionError("MME_METHOD_SCORER_SOURCE_READ_DENIED")
        if not _inside(path, roots):
            raise PermissionError("MME_METHOD_FILESYSTEM_READ_DENIED")

    sys.addaudithook(audit)


def _validate_public(value: Any, *, location: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{location}: JSON object keys must be strings")
            lowered = key.lower()
            if any(part in lowered for part in _DENIED_KEY_PARTS) or lowered.endswith(
                ("_path", "_file", "_directory")
            ):
                raise PermissionError("MME_METHOD_FORBIDDEN_PUBLIC_FIELD")
            _validate_public(item, location=f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_public(item, location=f"{location}[{index}]")
    elif value is None or isinstance(value, (str, int, float, bool)):
        return
    else:
        raise TypeError(f"{location}: value is not JSON")


def _execute(method_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    cap = payload.get("method_cap", 1_000_000)
    return dict(_RUN_METHOD(method_id, payload, cap=cap))


def _response(method_id: str, payload: Any) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict):
            raise TypeError("MME method payload must be a JSON object")
        _validate_public(payload)
        output = _execute(method_id, payload)
        _validate_public(output, location="output")
        return {"ok": True, "output": output}
    except BaseException as exc:
        denied = isinstance(exc, PermissionError)
        return {
            "ok": False,
            "truth_access_denied": denied,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def main(argv: list[str] | None = None) -> int:
    global _RUN_METHOD
    parser = argparse.ArgumentParser()
    parser.add_argument("method_id")
    parser.add_argument("--stream", action="store_true")
    args = parser.parse_args(argv)
    source_root = Path(__file__).resolve().parents[2]
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from rfb.research.mme_methods import run_mme_method

    _RUN_METHOD = run_mme_method
    _install_read_boundary(source_root)
    if args.stream:
        for line in sys.stdin:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                response = {
                    "ok": False,
                    "truth_access_denied": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            else:
                response = _response(args.method_id, payload)
            json.dump(response, sys.stdout, ensure_ascii=True, sort_keys=True)
            sys.stdout.write("\n")
            sys.stdout.flush()
        return 0
    response = _response(args.method_id, json.load(sys.stdin))
    if response["ok"]:
        json.dump(response["output"], sys.stdout, ensure_ascii=True, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    marker = (
        "MME_METHOD_TRUTH_ACCESS_DENIED"
        if response["truth_access_denied"]
        else "MME_METHOD_EXECUTION_FAILED"
    )
    sys.stderr.write(f"{marker}:{response['error_type']}:{response['error']}\n")
    return 73 if response["truth_access_denied"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
