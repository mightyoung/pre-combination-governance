"""Score a complete, hash-frozen 80-slot bundle; never score partial outputs."""

import hashlib
import json
from pathlib import Path
import sys

PACKAGE_DIR = Path(__file__).resolve().parent
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

from bundle import BundleError, canonical_bytes, verify_frozen_bundle
from result_contract import ResultContractError, validate_result
from task_contract import CASE_ID_ORDER, CASE_IDS_BY_ARM, EXPECTED_TRACE_BY_CASE_ID


EXPECTED_METHOD_ORDER = ("M0", "M1", "M2", "M3")


def _validate_ab_consistency(case_rows, by_key, case_ids):
    case_a, case_b = CASE_IDS_BY_ARM["A"], CASE_IDS_BY_ARM["B"]
    if list(case_ids) != list(CASE_ID_ORDER):
        raise BundleError("case order differs from the reviewed A/B/C/D bindings")
    if canonical_bytes(case_rows[case_a]) != canonical_bytes(case_rows[case_b]):
        raise BundleError("A/B method-visible input rows differ")
    for prefix in range(1, 6):
        for method in EXPECTED_METHOD_ORDER:
            left = by_key[(case_a, prefix, method)]
            right = by_key[(case_b, prefix, method)]
            if (left.get("input_sha256") != right.get("input_sha256")
                    or canonical_bytes(left.get("result")) != canonical_bytes(right.get("result"))):
                raise BundleError("A/B protocol failure: paired inputs or outputs differ")


def _validate_case_map(case_map, case_ids, oracle):
    if list(case_ids) != list(CASE_ID_ORDER):
        raise BundleError("case order differs from the reviewed A/B/C/D bindings")
    truth_map = case_map.get("oracle_trace_for_case")
    if truth_map != EXPECTED_TRACE_BY_CASE_ID:
        raise BundleError("oracle case mapping differs from the reviewed plan")
    traces = oracle.get("traces")
    if not isinstance(traces, dict) or any(name not in traces for name in truth_map.values()):
        raise BundleError("oracle mapping refers to an unknown source trace")
    return truth_map


def _read_json(path: Path, label: str) -> tuple[bytes, dict]:
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise BundleError(label + " is unreadable JSON") from error
    if not isinstance(data, dict):
        raise BundleError(label + " must be a JSON object")
    return raw, data


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _old_state(result: dict) -> dict:
    return {key: result[key] for key in ("cards", "risk", "priority")}


def _validate_result(result: dict, expected_alarm_ids: set[str]) -> None:
    try:
        validate_result(result, expected_alarm_ids)
    except ResultContractError as error:
        raise BundleError("method result violates its frozen contract: " + str(error)) from error


def _event_errors(cards: dict, possible: list, physical_episodes: dict) -> dict:
    """Preserve the pinned reference's pairwise false-merge/split semantics."""
    ids = sorted(set(cards) & set(physical_episodes))
    uncertain = set(possible)
    merged = split = decided = rejected = total = 0
    for index, left in enumerate(ids):
        for right in ids[index + 1:]:
            total += 1
            if left in uncertain or right in uncertain:
                rejected += 1
                continue
            decided += 1
            same_truth = physical_episodes[left] == physical_episodes[right]
            same_card = cards[left] == cards[right]
            merged += int(same_card and not same_truth)
            split += int(same_truth and not same_card)
    return {
        "false_merge": merged,
        "false_split": split,
        "decided_pairs": decided,
        "rejected_pairs": rejected,
        "total_pairs": total,
    }


def _first_alert_checks(case_ids, methods, by_key, oracle, truth_map):
    checks = []
    for case_id in case_ids:
        truth = oracle["traces"][truth_map[case_id]]
        required = truth["must_first_alert"]
        for method in methods:
            actual = [
                prefix for prefix in range(1, 6)
                if "new_event_first_alert" in by_key[(case_id, prefix, method)]["result"]["notification_reasons"]
            ]
            missed = [prefix for prefix in required if prefix not in actual]
            extra = [prefix for prefix in actual if prefix not in required]
            delays = []
            for index, start in enumerate(required):
                end = required[index + 1] if index + 1 < len(required) else 6
                hits = [prefix for prefix in actual if start <= prefix < end]
                delays.append(None if not hits else min(hits) - start)
            checks.append({
                "case_id": case_id,
                "method": method,
                "required_prefixes": list(required),
                "actual_prefixes": actual,
                "missed_prefixes": missed,
                "extra_prefixes": extra,
                "logical_delays": delays,
                "missed": bool(missed),
            })
    return checks


def _physical_alert_checks(case_ids, methods, by_key, oracle, truth_map):
    checks = []
    for case_id in case_ids:
        truth = oracle["traces"][truth_map[case_id]]
        required = truth["must_notify"]
        for method in methods:
            available = [
                prefix for prefix in range(1, 6)
                if any(reason != "handling_follow_up_only" for reason in
                       by_key[(case_id, prefix, method)]["result"]["notification_reasons"])
            ]
            matched = set()
            for index, start in enumerate(required):
                end = required[index + 1] if index + 1 < len(required) else 6
                hits = [prefix for prefix in available if start <= prefix < end]
                if hits:
                    matched.add(min(hits))
            missed = [start for index, start in enumerate(required)
                      if not any(start <= prefix < (required[index + 1] if index + 1 < len(required) else 6)
                                 for prefix in available)]
            unmatched = [prefix for prefix in available if prefix not in matched]
            checks.append({
                "case_id": case_id,
                "method": method,
                "required_prefixes": list(required),
                "actual_alert_prefixes": available,
                "missed_required_prefixes": missed,
                "unmatched_alert_prefixes": unmatched,
            })
    return checks


def score_bundle(bundle_dir, manifest_path, oracle_path, oracle_case_map_path, score_path):
    """Verify all non-oracle artifacts before opening the oracle sidecar."""
    verified = verify_frozen_bundle(bundle_dir, require_complete=True)
    attempt = verified.attempt
    manifest_bytes, manifest = _read_json(Path(manifest_path), "task manifest")
    expected_manifest_sha = attempt.get("task_manifest_sha256")
    if not isinstance(expected_manifest_sha, str) or _sha256(manifest_bytes) != expected_manifest_sha:
        raise BundleError("task manifest hash does not match the frozen attempt")
    if manifest.get("task_id") != "PCG-IDENTIFIABILITY-PAIRED-CPU-001":
        raise BundleError("unexpected task manifest ID")
    if manifest.get("planned_method_invocations") != 80:
        raise BundleError("task manifest must retain the 80-slot plan")
    if manifest.get("pair_inputs_path") != "PAIR_METHOD_INPUTS.json":
        raise BundleError("task manifest paired input path differs from the frozen package")

    case_ids = manifest.get("case_ids")
    methods = manifest.get("method_order")
    if (case_ids != attempt.get("case_ids") or methods != list(EXPECTED_METHOD_ORDER)
            or methods != attempt.get("method_order")):
        raise BundleError("task manifest case/method binding does not match the attempt")
    pair_path = Path(manifest_path).resolve().parent / manifest.get("pair_inputs_path", "")
    pair_bytes, pair_inputs = _read_json(pair_path, "paired method inputs")
    if _sha256(pair_bytes) != manifest.get("pair_inputs_sha256"):
        raise BundleError("paired method input hash mismatch")
    cases = pair_inputs.get("cases")
    if not isinstance(cases, list) or [case.get("case_id") for case in cases] != case_ids:
        raise BundleError("paired method inputs do not match opaque case IDs")
    if any(len(case.get("rows", [])) != 5 for case in cases):
        raise BundleError("each paired case must contain five frozen rows")

    by_key = {}
    for slot in verified.slots:
        key = (slot.get("case_id"), slot.get("prefix"), slot.get("method"))
        if key in by_key:
            raise BundleError("duplicate frozen output slot")
        by_key[key] = slot
    if len(by_key) != 80:
        raise BundleError("scorer requires exactly 80 completed slots")

    case_rows = {case["case_id"]: case["rows"] for case in cases}
    if set(case_rows) != set(CASE_ID_ORDER):
        raise BundleError("paired method inputs do not use the four reviewed opaque cases")
    _validate_ab_consistency(case_rows, by_key, case_ids)
    for case_id in case_ids:
        for method in methods:
            previous = {}
            for prefix in range(1, 6):
                slot = by_key[(case_id, prefix, method)]
                visible_rows = case_rows[case_id][:prefix]
                expected_ids = {row["id"] for row in visible_rows if row.get("alarm") is True}
                _validate_result(slot.get("result"), expected_ids)
                payload = {"method": method, "prefix": visible_rows, "old": previous}
                if _sha256(canonical_bytes(payload)) != slot.get("input_sha256"):
                    raise BundleError("method-visible input hash mismatch")
                if _sha256(canonical_bytes(slot["result"])) != slot.get("output_sha256"):
                    raise BundleError("method output hash mismatch")
                previous = _old_state(slot["result"])

    # Oracle bytes are read only after output freeze, manifest/input pins, all
    # 80 slot keys, and per-slot input/output hashes have passed validation.
    oracle_bytes, oracle = _read_json(Path(oracle_path), "physical oracle")
    if _sha256(oracle_bytes) != manifest.get("oracle_sha256"):
        raise BundleError("physical oracle SHA-256 mismatch")
    # Keep case labels out of the task manifest and all execution-side files.
    # The map is a separate scorer-only sidecar, read only after outputs freeze.
    map_bytes, case_map = _read_json(Path(oracle_case_map_path), "oracle case map")
    if _sha256(map_bytes) != manifest.get("oracle_case_map_sha256"):
        raise BundleError("oracle case map SHA-256 mismatch")
    if case_map.get("schema_version") != 1:
        raise BundleError("oracle case map schema version must be 1")
    truth_map = _validate_case_map(case_map, case_ids, oracle)

    first_alert = _first_alert_checks(case_ids, methods, by_key, oracle, truth_map)
    physical_alert = _physical_alert_checks(case_ids, methods, by_key, oracle, truth_map)
    event_metrics = []
    for case_id in case_ids:
        truth = oracle["traces"][truth_map[case_id]]
        for prefix in range(1, 6):
            for method in methods:
                result = by_key[(case_id, prefix, method)]["result"]
                event_metrics.append({
                    "case_id": case_id,
                    "prefix": prefix,
                    "method": method,
                    **_event_errors(result["cards"], result["possible"], truth["alarm_episodes"]),
                })
    first_acceptance = all(
        not check["missed_prefixes"] and not check["extra_prefixes"]
        and all(delay == 0 for delay in check["logical_delays"])
        for check in first_alert
    )
    physical_acceptance = all(
        not check["missed_required_prefixes"] and not check["unmatched_alert_prefixes"]
        for check in physical_alert
    )
    acceptance = "TRUE" if first_acceptance and physical_acceptance else "FALSE"
    result = {
        "schema_version": 1,
        "task_id": manifest["task_id"],
        "run_id": attempt["run_id"],
        "task_status": "PASS",
        "research_acceptance": acceptance,
        "planned_method_invocations": 80,
        "method_invocations_started": attempt["method_invocations_started"],
        "completed_method_invocations": attempt["completed_method_invocations"],
        "method_start_requests": attempt["method_start_requests"],
        "terminal_exit_code": 0,
        "output_sha256": attempt["output_sha256"],
        "task_manifest_sha256": attempt["task_manifest_sha256"],
        "oracle_sha256": manifest["oracle_sha256"],
        "oracle_case_map_sha256": manifest["oracle_case_map_sha256"],
        "plan_sha256": manifest["plan_sha256"],
        "source_commits": manifest.get("source_commits", {}),
        "schema_hashes": manifest.get("schema_hashes", {}),
        "partial": False,
        "first_alert_acceptance": first_acceptance,
        "physical_notification_acceptance": physical_acceptance,
        "first_alert_checks": first_alert,
        "physical_alert_checks": physical_alert,
        "event_pair_metrics": event_metrics,
        "rejection_denominator": sum(metric["rejected_pairs"] for metric in event_metrics),
        "production_truth_denominator": 0,
        "production_accuracy": "NOT_COMPUTABLE",
        "delivery_status": "NOT_DELIVERED",
        "scope_note": "Synthetic paired mechanism diagnostic; execution PASS does not imply research acceptance or production safety.",
    }
    destination = Path(score_path)
    with destination.open("xb") as stream:
        stream.write(canonical_bytes(result) + b"\n")
        stream.flush()
    return result


def main(argv=None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--task-manifest", required=True)
    parser.add_argument("--oracle", required=True)
    parser.add_argument("--oracle-case-map", required=True)
    parser.add_argument("--score-output", required=True)
    args = parser.parse_args(argv)
    result = score_bundle(args.bundle, args.task_manifest, args.oracle,
                          args.oracle_case_map, args.score_output)
    print(json.dumps({key: result[key] for key in (
        "run_id", "task_status", "research_acceptance",
        "first_alert_acceptance", "physical_notification_acceptance",
        "production_truth_denominator", "production_accuracy",
    )}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
