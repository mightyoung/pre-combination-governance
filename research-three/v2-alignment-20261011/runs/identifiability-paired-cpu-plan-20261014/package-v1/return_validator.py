"""Validate a returned execution bundle and optional separate score receipt."""

import json
from pathlib import Path
import sys
import tempfile

PACKAGE_DIR = Path(__file__).resolve().parent
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

from bundle import BundleError, verify_frozen_bundle
from bundle import canonical_bytes
from scorer import score_bundle


class ReturnValidationError(ValueError):
    pass


def validate_return(bundle_dir, score_path=None, task_manifest_path=None,
                    oracle_path=None, oracle_case_map_path=None):
    try:
        verified = verify_frozen_bundle(bundle_dir, require_complete=False)
    except BundleError as error:
        raise ReturnValidationError(str(error)) from error
    attempt = verified.attempt
    status = attempt["task_status"]
    score = None
    score_bytes = None
    if score_path is not None:
        try:
            score_bytes = Path(score_path).read_bytes()
            score = json.loads(score_bytes)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ReturnValidationError("score receipt is unreadable JSON") from error
        if not isinstance(score, dict):
            raise ReturnValidationError("score receipt must be a JSON object")
        if score.get("run_id") != attempt.get("run_id"):
            raise ReturnValidationError("score run ID does not match execution receipt")
        if score.get("task_id") != attempt.get("task_id"):
            raise ReturnValidationError("score task ID does not match execution receipt")

    if status == "PASS":
        if score is None:
            validation_status = "VALID_EXECUTION_SCORE_PENDING"
            acceptance = attempt["research_acceptance"]
        else:
            manifest = Path(task_manifest_path or PACKAGE_DIR / "TASK_MANIFEST.json")
            oracle = Path(oracle_path or PACKAGE_DIR / "scorer_source" / "oracle.physical.json")
            case_map = Path(oracle_case_map_path or PACKAGE_DIR / "scorer_source" / "ORACLE_CASE_MAP.json")
            try:
                with tempfile.TemporaryDirectory(prefix="pcg-score-recompute-") as temp_dir:
                    expected_score = score_bundle(
                        bundle_dir, manifest, oracle, case_map,
                        Path(temp_dir) / "recomputed-score.json",
                    )
            except (BundleError, OSError, ValueError, TypeError, KeyError) as error:
                raise ReturnValidationError(
                    "complete score could not be recomputed from the frozen bundle: " + str(error)
                ) from error
            if score_bytes != canonical_bytes(expected_score) + b"\n":
                raise ReturnValidationError(
                    "score receipt bytes differ from the deterministic scorer output"
                )
            validation_status = "VALID_COMPLETE_RETURN"
            acceptance = score["research_acceptance"]
    else:
        if score is not None:
            raise ReturnValidationError("partial execution must not receive research scoring")
        if attempt.get("research_acceptance") != "NOT_EVALUATED":
            raise ReturnValidationError("partial execution acceptance must be NOT_EVALUATED")
        validation_status = "VALID_PARTIAL_EXECUTION"
        acceptance = "NOT_EVALUATED"

    return {
        "validation_status": validation_status,
        "run_id": attempt["run_id"],
        "task_status": status,
        "research_acceptance": acceptance,
        "planned_method_invocations": attempt["planned_method_invocations"],
        "method_start_requests": attempt["method_start_requests"],
        "method_invocations_started": attempt["method_invocations_started"],
        "completed_method_invocations": attempt["completed_method_invocations"],
        "partial": attempt["partial"],
        "stop_reason": attempt["stop_reason"],
        "output_sha256": attempt["output_sha256"],
    }


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--score")
    parser.add_argument("--task-manifest", default=str(PACKAGE_DIR / "TASK_MANIFEST.json"))
    parser.add_argument("--oracle", default=str(PACKAGE_DIR / "scorer_source" / "oracle.physical.json"))
    parser.add_argument("--oracle-case-map", default=str(PACKAGE_DIR / "scorer_source" / "ORACLE_CASE_MAP.json"))
    args = parser.parse_args(argv)
    report = validate_return(args.bundle, args.score, args.task_manifest,
                             args.oracle, args.oracle_case_map)
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
