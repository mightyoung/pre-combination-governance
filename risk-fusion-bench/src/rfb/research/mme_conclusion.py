from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def evaluate_conclusion(
    report: Mapping[str, Any], preregistration: Mapping[str, Any]
) -> dict[str, Any]:
    policy = preregistration["analysis_policy"]
    eligible = tuple(policy["eligible_primary_block_ids"])
    comparators = tuple(policy["primary_comparators"])
    metrics = tuple(policy["primary_metric_keys"])
    panel = tuple(preregistration["method_order"])
    threshold = policy["minimum_improved_blocks"]
    tolerance = policy["equality_tolerance"]
    if (
        not eligible
        or len(set(eligible)) != len(eligible)
        or not 1 <= threshold <= len(eligible)
    ):
        raise ValueError("MME_CONCLUSION_PROTOCOL_INVALID")
    if not _finite(tolerance) or tolerance < 0:
        raise ValueError("MME_CONCLUSION_TOLERANCE_INVALID")
    lookup: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in report["method_rows"]:
        key = (str(row["physical_block_id"]), str(row["method_id"]))
        if key in lookup:
            raise ValueError("MME_CONCLUSION_DUPLICATE_SLOT")
        lookup[key] = row
    gaps: list[dict[str, str]] = []
    for block_id in eligible:
        for method_id in panel:
            row = lookup.get((block_id, method_id))
            if row is None or row.get("status") != "SUCCEEDED":
                gaps.append(
                    {
                        "block_id": block_id,
                        "method_id": method_id,
                        "reason": "MISSING_OR_FAILED_SLOT",
                    }
                )
                continue
            if method_id in ("Proposed", "ES-Rebuild", *comparators):
                for metric in metrics:
                    if not _finite(row.get(metric)):
                        gaps.append(
                            {
                                "block_id": block_id,
                                "method_id": method_id,
                                "reason": "METRIC_UNAVAILABLE",
                                "metric": metric,
                            }
                        )
    counts = []
    for comparator in comparators:
        for metric in metrics:
            lower = ties = higher = unavailable = 0
            for block_id in eligible:
                left_row = lookup.get((block_id, "Proposed"), {})
                right_row = lookup.get((block_id, comparator), {})
                left, right = left_row.get(metric), right_row.get(metric)
                if (
                    left_row.get("status") != "SUCCEEDED"
                    or right_row.get("status") != "SUCCEEDED"
                    or not _finite(left)
                    or not _finite(right)
                ):
                    unavailable += 1
                elif left < right - tolerance:
                    lower += 1
                elif left > right + tolerance:
                    higher += 1
                else:
                    ties += 1
            counts.append(
                {
                    "comparator": comparator,
                    "metric": metric,
                    "preference": "LOWER_IS_BETTER",
                    "eligible_blocks": len(eligible),
                    "proposed_lower": lower,
                    "ties": ties,
                    "proposed_higher": higher,
                    "unavailable": unavailable,
                }
            )
    supported = all(row["proposed_lower"] >= threshold for row in counts)
    status = (
        "EVIDENCE_INSUFFICIENT"
        if gaps
        else "MECHANISM_SUPPORTED"
        if supported
        else "MECHANISM_UNSUPPORTED"
    )
    es_tie: bool | None = None
    if not gaps:
        es_tie = all(
            abs(
                lookup[(block, "Proposed")][metric]
                - lookup[(block, "ES-Rebuild")][metric]
            )
            <= tolerance
            for block in eligible
            for metric in metrics
        )
    return {
        "schema_version": "MME_V2_DESCRIPTIVE_CONCLUSION",
        "status": status,
        "eligible_block_ids": list(eligible),
        "eligible_physical_blocks_n": len(eligible),
        "minimum_improved_blocks_per_comparator_and_metric": threshold,
        "primary_effect_counts": counts,
        "evidence_gaps": gaps,
        "es_rebuild_tie_on_all_primary_values": es_tie,
        "unique_increment_over_es_rebuild": "NOT_ESTABLISHED_TIE"
        if es_tie
        else "EVIDENCE_INSUFFICIENT"
        if es_tie is None
        else "DIFFERENT_VALUES_NOT_A_SUPERIORITY_PROOF",
        "no_harm_role": "DESCRIPTIVE_REFERENCE_ONLY_NOT_A_SUPPORT_OVERRIDE",
        "confirmatory": False,
        "statistical_significance_claim": False,
    }
