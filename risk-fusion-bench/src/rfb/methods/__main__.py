"""Subprocess entry point for one registered method."""

from __future__ import annotations

import argparse
import json
import sys

from .api import METHOD_IDS, run_method


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("method_id", choices=METHOD_IDS)
    args = parser.parse_args()
    json.dump(
        run_method(args.method_id, json.load(sys.stdin)), sys.stdout, sort_keys=True
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
