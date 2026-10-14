"""Create the fixed opaque A/B/C/D inputs from the pinned public JSON only."""

import argparse
import json
from pathlib import Path
import sys

PACKAGE_DIR = Path(__file__).resolve().parent
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

from pair_inputs import build_pair_cases, canonical_json_bytes


def build(input_path, bindings_path, output_path):
    source = json.loads(Path(input_path).read_text(encoding="utf-8"))
    bindings = json.loads(Path(bindings_path).read_text(encoding="utf-8"))
    case_ids = bindings.get("opaque_case_ids")
    if not isinstance(case_ids, dict):
        raise ValueError("opaque case ID mapping is missing")
    result = build_pair_cases(source, case_ids)
    output = Path(output_path)
    payload = canonical_json_bytes(result) + b"\n"
    try:
        with output.open("xb") as stream:
            stream.write(payload)
    except FileExistsError:
        if output.read_bytes() != payload:
            raise ValueError("existing pair input differs; refusing to overwrite")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-input", default=str(PACKAGE_DIR / "frozen_source/public-input.json"))
    parser.add_argument("--case-bindings", default=str(PACKAGE_DIR / "CASE_BINDINGS.json"))
    parser.add_argument("--output", default=str(PACKAGE_DIR / "PAIR_METHOD_INPUTS.json"))
    args = parser.parse_args(argv)
    result = build(args.public_input, args.case_bindings, args.output)
    print(json.dumps({"case_count": len(result["cases"]), "prefixes_per_case": 5,
                      "method_invocations_planned": 80}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
