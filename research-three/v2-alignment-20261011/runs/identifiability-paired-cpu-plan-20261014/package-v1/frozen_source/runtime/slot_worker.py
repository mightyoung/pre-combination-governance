"""One-slot adapter; receives only the current prefix and prior public output."""

import json
from pathlib import Path
import sys


METHODS = {"M0", "M1", "M2", "M3"}
PAYLOAD_KEYS = {"method", "prefix", "old"}
OLD_STATE_KEYS = {"cards", "risk", "priority"}


def handle(payload: dict, step_function=None) -> dict:
    if not isinstance(payload, dict) or set(payload) != PAYLOAD_KEYS:
        raise ValueError("slot payload must contain exactly method, prefix, and old")
    method = payload["method"]
    prefix = payload["prefix"]
    old = payload["old"]
    if method not in METHODS:
        raise ValueError("unknown frozen method")
    if not isinstance(prefix, list) or not 1 <= len(prefix) <= 5:
        raise ValueError("slot must contain one current prefix of length 1 through 5")
    if any(not isinstance(row, dict) for row in prefix):
        raise ValueError("prefix rows must be objects")
    if not isinstance(old, dict) or not set(old).issubset(OLD_STATE_KEYS):
        raise ValueError("prior state may contain only prior public cards, risk, and priority")
    if step_function is None:
        source_dir = str(Path(__file__).resolve().parent)
        if source_dir not in sys.path:
            sys.path.insert(0, source_dir)
        import worker
        step_function = worker.step
    return step_function(prefix, method, old)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read())
        result = handle(payload)
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False))
        sys.stdout.write("\n")
        return 0
    except Exception as error:
        sys.stderr.write(type(error).__name__ + ": " + str(error) + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
