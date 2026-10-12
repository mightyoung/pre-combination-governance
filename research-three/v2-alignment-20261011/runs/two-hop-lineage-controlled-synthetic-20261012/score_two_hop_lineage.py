"""Score the frozen method output against a separate synthetic truth fixture."""

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
    scorer_manifest = read_json(RUN_DIR / "SCORER_TRUTH_MANIFEST.json")
    for entry in scorer_manifest["files"]:
        raw = (REPO_ROOT / entry["path"]).read_bytes()
        if len(raw) != entry["bytes"] or sha256(raw) != entry["sha256"]:
            raise ValueError(f"frozen scorer-side file changed: {entry['path']}")

    truth = read_json(RUN_DIR / "SYNTHETIC_TRUTH_LOG.json")
    outputs_path = RUN_DIR / "METHOD_OUTPUTS.json"
    freeze = read_json(RUN_DIR / "METHOD_OUTPUT_FREEZE.json")
    outputs_raw = outputs_path.read_bytes()
    if len(outputs_raw) != freeze["bytes"] or sha256(outputs_raw) != freeze["sha256"]:
        raise ValueError("method output no longer matches its pre-scoring freeze")
    checks = read_json(RUN_DIR / "RUNNER_CHECKS.json")
    outputs = read_json(outputs_path)
    if checks["method_runner_read_truth_log"] is not False:
        raise ValueError("method-runner truth isolation record is not PASS")
    if checks["checks"].get("all_frozen_expectation_checks_passed") is not True:
        raise ValueError("method runner did not pass frozen expectations")

    truth_by_pair = {row["pair_id"]: row["relation"] for row in truth["truth_relations"]}
    if len(truth_by_pair) != len(truth["truth_relations"]):
        raise ValueError("duplicate pair in synthetic truth fixture")
    result_conditions: dict[str, Any] = {}
    expected_pair_ids = set(truth_by_pair)
    for condition_id, condition in outputs["conditions"].items():
        rows = condition["pair_results"]
        pair_ids = [row["pair_id"] for row in rows]
        if len(pair_ids) != len(set(pair_ids)) or set(pair_ids) != expected_pair_ids:
            raise ValueError(f"pair coverage mismatch in {condition_id}")
        scored_rows = []
        counts = {"correct_source_attribution": 0, "wrong_separate_attribution": 0, "unknown": 0}
        for row in rows:
            true_relation = truth_by_pair[row["pair_id"]]
            if "lineage_status" in row:
                if row["lineage_status"] == "SHARED_KNOWN_ANCESTOR":
                    outcome = "CORRECT_SOURCE_ATTRIBUTION"
                elif row["lineage_status"] == "UNKNOWN":
                    outcome = "UNKNOWN"
                else:
                    outcome = "WRONG_SEPARATE_ATTRIBUTION"
            elif row.get("dedup_outcome") == "DISTINCT_HASH_BUCKETS":
                outcome = "WRONG_SEPARATE_ATTRIBUTION"
            elif row.get("dedup_outcome") == "SAME_HASH_BUCKET":
                outcome = "CORRECT_SOURCE_ATTRIBUTION"
            else:
                outcome = "UNKNOWN"
            if true_relation != "SAME_SYNTHETIC_PARENT":
                raise ValueError("unsupported synthetic truth relation for this fixed scorer")
            count_key = {
                "CORRECT_SOURCE_ATTRIBUTION": "correct_source_attribution",
                "WRONG_SEPARATE_ATTRIBUTION": "wrong_separate_attribution",
                "UNKNOWN": "unknown",
            }[outcome]
            counts[count_key] += 1
            scored_rows.append({
                "pair_id": row["pair_id"],
                "synthetic_truth": true_relation,
                "method_outcome": outcome,
            })
        result_conditions[condition_id] = {
            "pair_rows": len(rows),
            "counts": counts,
            "scored_pairs": scored_rows,
        }

    scored = {
        "run_id": outputs["run_id"],
        "world_id": truth["world_id"],
        "status": "COMPLETED_CONTROLLED_SYNTHETIC_REPLAY_NOT_PRODUCTION_EVIDENCE",
        "classification": truth["classification"],
        "method_outputs_sha256_at_freeze": freeze["sha256"],
        "method_runner_read_truth_log": False,
        "scorer_read_truth_after_method_output_freeze": True,
        "production_replay_log_denominator": 0,
        "production_accuracy": "NOT_COMPUTABLE",
        "synthetic_worlds": 1,
        "pair_rows_within_world": len(expected_pair_ids),
        "pair_rows_are_independent_samples": False,
        "conditions": result_conditions,
        "interpretation": "Counts describe only three pairwise rows within one predeclared synthetic chain. Hash-distinct buckets are scored as wrong separation for this source-attribution task; this does not imply or measure statistical independence.",
        "network_or_model_or_notification_called": False,
        "delivery_status": "NOT_DELIVERED",
    }
    (RUN_DIR / "SCORED_RESULT.json").write_text(
        json.dumps(scored, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(scored["conditions"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
