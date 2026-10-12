"""Report V2 coverage counts after method-output freeze; no accuracy scoring."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
RUN_DIR = Path(__file__).resolve().parent


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def main() -> None:
    outputs_path = RUN_DIR / "METHOD_OUTPUTS_V2.json"
    freeze = read_json(RUN_DIR / "METHOD_OUTPUT_FREEZE_V2.json")
    outputs_raw = outputs_path.read_bytes()
    if len(outputs_raw) != freeze["bytes"] or sha256(outputs_raw) != freeze["sha256"]:
        raise ValueError("method output does not match its pre-scoring freeze")
    runner_checks = read_json(RUN_DIR / "RUNNER_CHECKS_V2.json")
    if runner_checks["method_runner_read_truth_log"] is not False:
        raise ValueError("method runner truth-isolation record is not PASS")
    if runner_checks["checks"].get("all_frozen_expectations_passed") is not True:
        raise ValueError("method runner failed frozen expectations")
    outputs = json.loads(outputs_raw.decode("utf-8"))

    # Only after the method output hash is verified do we open scorer-only files.
    scorer_manifest = read_json(RUN_DIR / "SCORER_TRUTH_MANIFEST_V2.json")
    for entry in scorer_manifest["files"]:
        data = (REPO_ROOT / entry["path"]).read_bytes()
        if len(data) != entry["bytes"] or sha256(data) != entry["sha256"]:
            raise ValueError(f"scorer-side frozen file changed: {entry['path']}")
    truth = read_json(RUN_DIR / "SYNTHETIC_TRUTH_LOG_V2.json")
    truth_pairs = {row["pair_id"] for row in truth["truth_relations"]}
    if len(truth_pairs) != 3 or truth["world_id"] != outputs["world_id"]:
        raise ValueError("synthetic fixture audit mismatch")

    conditions: dict[str, Any] = {}
    for condition_id in ("FULL_RECEIPT_CHAIN", "MISSING_INTERMEDIATE_RECEIPT", "HASH_ONLY_DEDUP"):
        rows = outputs["conditions"][condition_id]["pair_results"]
        pair_ids = [row["pair_id"] for row in rows]
        if len(pair_ids) != 3 or len(set(pair_ids)) != 3 or set(pair_ids) != truth_pairs:
            raise ValueError(f"fixed pair coverage changed in {condition_id}")
        counts = {"confirmed_shared_ancestor": 0, "unknown": 0, "other_bounded_graph_state": 0}
        for row in rows:
            status = row["lineage_status"]
            if status == "SHARED_KNOWN_ANCESTOR":
                counts["confirmed_shared_ancestor"] += 1
            elif status == "UNKNOWN":
                counts["unknown"] += 1
            else:
                counts["other_bounded_graph_state"] += 1
        conditions[condition_id] = {
            "eligible_pair_rows": 3,
            "counts": counts,
            "coverage_is_count_only": True,
            "wrong_confirmed_attribution_count": None,
            "wrong_confirmed_attribution_status": "NOT_EVALUATED_NO_INDEPENDENT_PRODUCTION_TRUTH",
        }

    expected_counts = {
        "FULL_RECEIPT_CHAIN": {"confirmed_shared_ancestor": 3, "unknown": 0},
        "MISSING_INTERMEDIATE_RECEIPT": {"confirmed_shared_ancestor": 1, "unknown": 2},
        "HASH_ONLY_DEDUP": {"confirmed_shared_ancestor": 0, "unknown": 3},
    }
    for condition_id, expected in expected_counts.items():
        actual = conditions[condition_id]["counts"]
        if any(actual[key] != value for key, value in expected.items()):
            raise ValueError(f"coverage counts differ from frozen policy in {condition_id}")

    negative = outputs["side_input_negative_control"]
    if negative["receipt_validation_status"] != "UNDECLARED_SIDE_INPUT" or negative["lineage_status"] != "UNKNOWN":
        raise ValueError("undeclared-side-input negative did not fail closed")
    scored = {
        "run_id": outputs["run_id"],
        "status": "COMPLETED_V2_SYNTHETIC_MECHANICS_ONLY",
        "classification": outputs["classification"],
        "method_outputs_sha256_at_freeze": freeze["sha256"],
        "method_runner_read_truth_log": False,
        "scorer_read_synthetic_fixture_after_output_freeze": True,
        "synthetic_truth_fixture_used_for_accuracy": False,
        "synthetic_fixture_audit": {
            "world_id": truth["world_id"],
            "pair_rows": len(truth_pairs),
            "single_shared_synthetic_parent": all(row["relation"] == "SAME_SYNTHETIC_PARENT" for row in truth["truth_relations"]),
            "production_truth": False,
        },
        "production_truth_denominator": 0,
        "production_accuracy": "NOT_COMPUTABLE",
        "wrong_confirmed_attribution_count": None,
        "wrong_confirmed_attribution_status": "NOT_EVALUATED_NO_INDEPENDENT_PRODUCTION_TRUTH",
        "pair_rows_are_independent_samples": False,
        "conditions": conditions,
        "side_input_negative_control": {
            "receipt_validation_status": negative["receipt_validation_status"],
            "lineage_status": negative["lineage_status"],
            "included_in_pair_denominator": False,
        },
        "interpretation": "Counts are coverage/UNKNOWN states within one fixed synthetic chain. Hash equality and inequality are byte observations only. Missing lineage capability is not counted as a wrong attribution.",
        "delivery_status": "NOT_DELIVERED",
        "event_identity_status": "NOT_EVALUATED",
        "network_or_model_or_notification_called": False,
    }
    (RUN_DIR / "SCORED_RESULT_V2.json").write_text(
        json.dumps(scored, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"conditions": conditions, "side_input_negative_control": scored["side_input_negative_control"], "production_accuracy": scored["production_accuracy"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
