from __future__ import annotations

import csv
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def build_mme_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    proposed_method: str = "Proposed",
    maximum_physical_blocks: int = 27,
    expected_methods: Sequence[str] | None = None,
) -> dict[str, Any]:
    normalized = [dict(row) for row in rows]
    for row in normalized:
        if "physical_block_id" not in row and "block_id" in row:
            row["physical_block_id"] = row["block_id"]
    required = {"physical_block_id", "method_id", "status"}
    for index, row in enumerate(normalized):
        if not required <= set(row):
            raise ValueError(
                f"row {index}: physical_block_id/method_id/status required"
            )
    blocks = sorted({str(row["physical_block_id"]) for row in normalized})
    if len(blocks) > maximum_physical_blocks:
        raise ValueError("independent physical-block count exceeds protocol maximum")
    methods = (
        list(expected_methods)
        if expected_methods is not None
        else sorted({str(row["method_id"]) for row in normalized})
    )
    if len(methods) != len(set(methods)):
        raise ValueError("expected_methods must be unique")
    unexpected = {str(row["method_id"]) for row in normalized} - set(methods)
    if unexpected:
        raise ValueError(f"unexpected methods: {sorted(unexpected)}")
    slots = [
        (str(row["physical_block_id"]), str(row["method_id"])) for row in normalized
    ]
    if len(slots) != len(set(slots)):
        raise ValueError("duplicate physical-block/method terminal row")
    present = set(slots)
    normalized.extend(
        {
            "physical_block_id": block,
            "method_id": method,
            "status": "MISSING",
            "failure_code": "METHOD_TERMINAL_ROW_MISSING",
        }
        for block in blocks
        for method in methods
        if (block, method) not in present
    )

    metric_names = sorted(
        {
            key
            for row in normalized
            for key, value in row.items()
            if key not in required and _finite_number(value)
        }
    )
    lookup = {
        (str(row["physical_block_id"]), str(row["method_id"])): row
        for row in normalized
    }
    paired_effects: list[dict[str, Any]] = []
    for comparator in methods:
        if comparator == proposed_method:
            continue
        for block in blocks:
            proposed = lookup.get((block, proposed_method))
            baseline = lookup.get((block, comparator))
            for metric in metric_names:
                left = proposed.get(metric) if proposed else None
                right = baseline.get(metric) if baseline else None
                pair_status = (
                    "PAIRED"
                    if proposed
                    and baseline
                    and proposed["status"] == "SUCCEEDED"
                    and baseline["status"] == "SUCCEEDED"
                    and _finite_number(left)
                    and _finite_number(right)
                    else "UNAVAILABLE"
                )
                difference = (
                    float(left) - float(right) if pair_status == "PAIRED" else None
                )
                paired_effects.append(
                    {
                        "physical_block_id": block,
                        "metric": metric,
                        "proposed_method": proposed_method,
                        "comparator_method": comparator,
                        "pair_status": pair_status,
                        "proposed_value": left if _finite_number(left) else None,
                        "comparator_value": right if _finite_number(right) else None,
                        "paired_difference": difference,
                        "effect_direction": "PROPOSED_HIGHER"
                        if difference is not None and difference > 0
                        else "PROPOSED_LOWER"
                        if difference is not None and difference < 0
                        else "TIE"
                        if difference == 0
                        else "UNAVAILABLE",
                    }
                )

    effect_counts: list[dict[str, Any]] = []
    groups = sorted(
        {(row["metric"], row["comparator_method"]) for row in paired_effects}
    )
    for metric, comparator in groups:
        selected = [
            row
            for row in paired_effects
            if row["metric"] == metric and row["comparator_method"] == comparator
        ]
        counts = Counter(row["effect_direction"] for row in selected)
        effect_counts.append(
            {
                "metric": metric,
                "comparator_method": comparator,
                "physical_blocks_total": len(blocks),
                "paired_blocks": sum(
                    row["pair_status"] == "PAIRED" for row in selected
                ),
                "proposed_lower": counts["PROPOSED_LOWER"],
                "ties": counts["TIE"],
                "proposed_higher": counts["PROPOSED_HIGHER"],
                "unavailable": counts["UNAVAILABLE"],
            }
        )

    curves = [
        {
            "physical_block_id": row["physical_block_id"],
            "method_id": row["method_id"],
            "prefix": row.get("prefix"),
            "curve_kind": row.get("curve_kind"),
            "value": row.get("curve_value"),
            "status": row["status"],
        }
        for row in normalized
        if "prefix" in row or "curve_kind" in row
    ]
    resources = [
        {
            "physical_block_id": row["physical_block_id"],
            "method_id": row["method_id"],
            "wall_time_seconds": row.get("wall_time_seconds"),
            "peak_memory_bytes": row.get("peak_memory_bytes"),
            "replay_time_seconds": row.get("replay_time_seconds"),
            "timing_mode": row.get("timing_mode"),
            "platform": row.get("platform"),
            "samples": row.get("resource_samples"),
            "status": row["status"],
        }
        for row in normalized
    ]
    applicability: list[dict[str, Any]] = []
    for method in methods:
        selected = [row for row in normalized if str(row["method_id"]) == method]
        for metric in metric_names:
            applicable = [
                row for row in selected if row.get(f"{metric}_applicable", True) is True
            ]
            available = [row for row in applicable if _finite_number(row.get(metric))]
            applicability.append(
                {
                    "method_id": method,
                    "metric": metric,
                    "physical_blocks_total": len(blocks),
                    "method_rows": len(selected),
                    "applicable_blocks": len(applicable),
                    "available_blocks": len(available),
                    "unavailable_blocks": len(applicable) - len(available),
                }
            )
    failures = [
        {
            "physical_block_id": row["physical_block_id"],
            "method_id": row["method_id"],
            "status": row["status"],
            "failure_code": row.get("failure_code"),
            "failure_kind": "EXPECTED_BOUNDARY"
            if str(row.get("failure_code", "")).endswith(
                ("CAP", "CAP_EXCEEDED", "MEMORY_LIMIT", "CPU_LIMIT")
            )
            or str(row["physical_block_id"]).startswith("E12")
            else "UNSUPPORTED_APPLICABILITY"
            if row["status"] in {"UNEXECUTED", "MISSING"}
            or str(row["physical_block_id"]).startswith("E08")
            else "IMPLEMENTATION_FAILURE",
        }
        for row in normalized
        if row["status"] != "SUCCEEDED"
    ]
    return {
        "schema_version": "1.0.0",
        "analysis_kind": "DESCRIPTIVE_PAIRED_PHYSICAL_BLOCK",
        "independent_unit": "physical_block",
        "independent_physical_blocks_n": len(blocks),
        "maximum_physical_blocks": maximum_physical_blocks,
        "method_rows_n": len(normalized),
        "methods": methods,
        "metric_names": metric_names,
        "significance_testing_performed": False,
        "superiority_claim_permitted": False,
        "method_rows": normalized,
        "paired_effects": paired_effects,
        "effect_direction_counts": effect_counts,
        "mechanism_curves": curves,
        "boundary_failures": failures,
        "resources": resources,
        "applicability_denominators": applicability,
    }


def _mean(values: Sequence[Any]) -> float | None:
    finite = [float(value) for value in values if _finite_number(value)]
    return sum(finite) / len(finite) if finite else None


def build_report_from_run_result(run_result: Mapping[str, Any]) -> dict[str, Any]:
    aggregate_rows: list[dict[str, Any]] = []
    curve_rows: list[dict[str, Any]] = []
    resource_rows: list[dict[str, Any]] = []
    for block in run_result.get("blocks", []):
        block_id = str(block["block_id"])
        scoring = block.get("scoring", {})
        for method_id, method in scoring.get("methods", {}).items():
            prefix_scores = list(method.get("prefix_scores", []))
            response_pairs = list(method.get("response_pairs", []))
            resources = list(method.get("resource_measurements", []))
            expected_prefixes = len(prefix_scores)
            scored_prefixes = sum(item.get("scored") is True for item in prefix_scores)
            terminal_state = method.get("terminal_state") or "UNAVAILABLE"
            report_status = (
                terminal_state
                if terminal_state != "SUCCEEDED" or scored_prefixes == expected_prefixes
                else "INVALID_SCORING"
            )
            recovery = method.get("recovery", {})
            row: dict[str, Any] = {
                "physical_block_id": block_id,
                "method_id": str(method_id),
                "status": report_status,
                "failure_code": next(
                    (
                        item.get("failure_code")
                        for item in prefix_scores
                        if item.get("failure_code")
                    ),
                    None,
                ),
                "expected_prefixes": expected_prefixes,
                "scored_prefixes": scored_prefixes,
                "partial_prefixes": scored_prefixes != expected_prefixes,
                "endpoint_l1": _mean(
                    [item.get("endpoint_l1") for item in prefix_scores]
                ),
                "belief_l1": _mean([item.get("belief_l1") for item in prefix_scores]),
                "jousselme": _mean([item.get("jousselme") for item in prefix_scores]),
                "false_block_rate": _mean(
                    [
                        float(item["false_block"])
                        for item in prefix_scores
                        if isinstance(item.get("false_block"), bool)
                    ]
                ),
                "availability_rate": _mean(
                    [
                        float(item["available"])
                        for item in prefix_scores
                        if isinstance(item.get("available"), bool)
                    ]
                ),
                "action_disagreement_rate": _mean(
                    [
                        float(item["action_set_disagreement"])
                        for item in prefix_scores
                        if isinstance(item.get("action_set_disagreement"), bool)
                    ]
                ),
                "dri_response_error": _mean(
                    [
                        item.get("response_vector_error_l1")
                        for item in response_pairs
                        if item.get("metric_family") == "DRI"
                    ]
                ),
                "sri_response_error": _mean(
                    [
                        item.get("response_vector_error_l1")
                        for item in response_pairs
                        if item.get("metric_family") == "SRI"
                    ]
                ),
                "sri_direction_match_rate": _mean(
                    [
                        float(item["response_direction_matches_oracle"])
                        for item in response_pairs
                        if item.get("metric_family") == "SRI"
                        and isinstance(
                            item.get("response_direction_matches_oracle"), bool
                        )
                    ]
                ),
                "recovery_endpoint_l1": recovery.get("mean_endpoint_l1")
                if recovery.get("applicable") is True
                else None,
                "recovery_endpoint_l1_applicable": recovery.get("applicable") is True,
                "wall_time_seconds": sum(
                    float(item["wall_seconds"])
                    for item in resources
                    if _finite_number(item.get("wall_seconds"))
                )
                if resources
                else None,
                "peak_memory_bytes": max(
                    (
                        int(item["peak_rss_bytes"])
                        for item in resources
                        if _finite_number(item.get("peak_rss_bytes"))
                    ),
                    default=None,
                ),
                "platform": next(
                    (
                        item.get("platform")
                        for item in resources
                        if item.get("platform")
                    ),
                    None,
                ),
                "resource_samples": len(resources),
                "resource_measurement_applicable": bool(resources),
            }
            aggregate_rows.append(row)
            for item in prefix_scores:
                curve_rows.append(
                    {
                        "physical_block_id": block_id,
                        "method_id": method_id,
                        "prefix": item.get("prefix_id"),
                        "curve_kind": "oracle_endpoint_l1",
                        "value": item.get("endpoint_l1"),
                        "status": item.get("status"),
                    }
                )
            for item in resources:
                resource_rows.append(
                    {
                        "physical_block_id": block_id,
                        "method_id": method_id,
                        **dict(item),
                    }
                )
    from .mme_events import METHOD_IDS

    report = build_mme_report(aggregate_rows, expected_methods=METHOD_IDS)
    report["run_id"] = run_result.get("run_id")
    report["attempt_id"] = run_result.get("attempt_id")
    report["run_class"] = run_result.get("run_class")
    report["mechanism_curves"] = curve_rows
    report["resources"] = resource_rows
    return report


def write_mme_report(
    report: Mapping[str, Any], output_directory: str | Path
) -> dict[str, Path]:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    table_names = (
        "method_rows",
        "paired_effects",
        "effect_direction_counts",
        "mechanism_curves",
        "boundary_failures",
        "resources",
        "applicability_denominators",
    )
    json_path = output / "mme_report.json"
    targets = [json_path, *(output / f"{key}.csv" for key in table_names)]
    existing = [path for path in targets if path.exists()]
    if existing:
        raise FileExistsError(f"MME report output already exists: {existing[0]}")
    with json_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
    paths["report"] = json_path
    for key in table_names:
        rows = list(report.get(key, []))
        path = output / f"{key}.csv"
        fields = sorted({field for row in rows for field in row})
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            if fields:
                writer.writeheader()
                writer.writerows(rows)
        paths[key] = path
    return paths


__all__ = ["build_mme_report", "build_report_from_run_result", "write_mme_report"]
