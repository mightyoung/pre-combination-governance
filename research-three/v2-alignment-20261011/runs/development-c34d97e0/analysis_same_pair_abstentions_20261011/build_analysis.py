#!/usr/bin/env python3
"""Read-only post-run analysis of three saved SAME-pair disagreements.

This script reads the frozen development inputs, sidecars, outputs, and traces.
It does not call the generator, association methods, or scorer.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

ANALYSIS_DIR = Path(__file__).resolve().parent
RUN_ROOT = ANALYSIS_DIR.parent
ATTEMPT = RUN_ROOT / "comparison_attempt_02"
CASES = [
    {
        "case_id": "C1",
        "world_group_id": "WG-49ad405b4355e37ee62ef70a",
        "pair": ["OBS-91964e41ff8667328399", "OBS-b8987acd3368ef907868"],
    },
    {
        "case_id": "C2",
        "world_group_id": "WG-a03b8a911c21fb790b2b6910",
        "pair": ["OBS-10083c5e213e53917142", "OBS-f6107c823fc32e05c1f1"],
    },
    {
        "case_id": "C3",
        "world_group_id": "WG-c6351b2c67706558c964473e",
        "pair": ["OBS-0cd8d85f9e6d947750ef", "OBS-f32de63fdc9bb280df1b"],
    },
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def field_map(record: dict[str, Any]) -> dict[str, Any]:
    return {row["name"]: row["value"] for row in record["fields"]}


def distance_m(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def elapsed_seconds(value: str, origin: datetime) -> float:
    return (datetime.fromisoformat(value.replace("Z", "+00:00")) - origin).total_seconds()


def public_record_view(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "observation_id": record["observation_id"],
        "received_at": record["received_at"],
        "id_actual_available_at": record["id_actual_available_at"],
        "id_earliest_known_at": record["id_earliest_known_at"],
        "fields": [
            {
                "name": field["name"],
                "value": field["value"],
                "actual_available_at": field["actual_available_at"],
                "earliest_known_at": field["earliest_known_at"],
            }
            for field in record["fields"]
        ],
    }


def extract_case(case: dict[str, Any]) -> dict[str, Any]:
    world = case["world_group_id"]
    left_id, right_id = case["pair"]
    source = read_json(ATTEMPT / "inputs" / f"{world}.json")
    sidecar = read_json(ATTEMPT / "scorer_sidecars" / f"{world}.json")
    trace = read_json(ATTEMPT / "outputs" / world / "trace.json")

    selected = [row for row in source["records"] if row["observation_id"] in case["pair"]]
    grouped: dict[str, list[dict[str, Any]]] = {left_id: [], right_id: []}
    for row in selected:
        grouped[row["observation_id"]].append(row)
    if any(not grouped[observation_id] for observation_id in case["pair"]):
        raise AssertionError(f"missing pair observation in {world}")

    first = {observation_id: grouped[observation_id][0] for observation_id in case["pair"]}
    values = {observation_id: field_map(first[observation_id]) for observation_id in case["pair"]}
    roots = sorted(
        {
            fields["acquisition_lineage"][0]
            for fields in values.values()
            if fields.get("acquisition_lineage")
        }
    )
    if len(roots) != 1:
        raise AssertionError(f"expected one shared acquisition root in {world}, saw {roots}")
    left, right = (values[observation_id] for observation_id in case["pair"])
    source_times = [left["source_time"], right["source_time"]]
    position_delta = distance_m(left["position_m"], right["position_m"])
    value_delta = abs(float(left["value"]) - float(right["value"]))

    truth = next(
        row
        for row in sidecar["pair_truths"]
        if {
            row["pair"]["left_observation_id"],
            row["pair"]["right_observation_id"],
        }
        == set(case["pair"])
    )
    snapshots = []
    for step in trace:
        output = read_json(ATTEMPT / step["output_path"])
        proposal = next(
            (
                row
                for row in output["proposals"]
                if {
                    row["pair"]["left_observation_id"],
                    row["pair"]["right_observation_id"],
                }
                == set(case["pair"])
            ),
            None,
        )
        snapshots.append(
            {
                "cutoff": step["cutoff"],
                "method": step["method"],
                "input_prefix_sha256": step["input_prefix_sha256"],
                "candidate_visible": proposal is not None,
                "action": proposal["action"] if proposal else "NOT_CANDIDATE",
                "reason_codes": proposal["reason_codes"] if proposal else [],
                "independent_lineage_root_count": (
                    proposal["independent_lineage_root_count"] if proposal else None
                ),
                "decided_at": proposal["decided_at"] if proposal else None,
            }
        )

    first_cutoff = min(
        (row["cutoff"] for row in snapshots if row["candidate_visible"]),
        key=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")),
    )
    if truth["label"] != "SAME" or truth["first_sufficient_evidence_at"] is not None:
        raise AssertionError(f"unexpected scorer-only truth in {world}: {truth}")
    final_cutoff = sidecar["registered_cutoffs"][-1]
    final = {
        row["method"]: row
        for row in snapshots
        if row["cutoff"] == final_cutoff
    }
    if final["TIME_ASSET_RULE"]["action"] != "LINK_CANDIDATES":
        raise AssertionError(f"baseline final action changed in {world}")
    if final["MULTI_EVIDENCE_RULE"]["action"] != "ABSTAIN":
        raise AssertionError(f"multi-evidence final action changed in {world}")
    by_method = {
        method: [row for row in snapshots if row["method"] == method and row["candidate_visible"]]
        for method in ("TIME_ASSET_RULE", "MULTI_EVIDENCE_RULE")
    }
    if any(len(rows) != 6 for rows in by_method.values()):
        raise AssertionError(f"expected six saved candidate snapshots per method in {world}")
    time_by_cutoff = {row["cutoff"]: row for row in by_method["TIME_ASSET_RULE"]}
    multi_by_cutoff = {row["cutoff"]: row for row in by_method["MULTI_EVIDENCE_RULE"]}
    if time_by_cutoff.keys() != multi_by_cutoff.keys() or any(
        time_by_cutoff[cutoff]["action"] != "LINK_CANDIDATES"
        or multi_by_cutoff[cutoff]["action"] != "ABSTAIN"
        for cutoff in time_by_cutoff
    ):
        raise AssertionError(f"saved cutoff-level action mismatch changed in {world}")
    if any(
        row["method"] == "MULTI_EVIDENCE_RULE"
        and row["candidate_visible"]
        and row["reason_codes"] != ["NO_INDEPENDENT_ACQUISITION_ROOTS"]
        for row in snapshots
    ):
        raise AssertionError(f"multi-evidence rejection reason changed in {world}")

    origin = datetime.fromisoformat(min(source_times).replace("Z", "+00:00"))
    updates = []
    for observation_id, rows in grouped.items():
        baseline_fields = first[observation_id]["fields"]
        base_values = field_map(first[observation_id])
        for row in rows[1:]:
            updated_fields = field_map(row)
            if len(row["fields"]) == 1:
                label = f"same-ID field update: {next(iter(updated_fields.items()))[0]}={next(iter(updated_fields.items()))[1]}"
            elif updated_fields == base_values:
                label = "same-ID repeated base payload (EXPOSURE)"
            else:
                label = "same-ID repeated/updated payload"
            updates.append(
                {
                    "observation_id": observation_id,
                    "received_at": row["received_at"],
                    "elapsed_seconds": elapsed_seconds(row["received_at"], origin),
                    "label": label,
                    "field_names": [field["name"] for field in row["fields"]],
                }
            )

    return {
        "case_id": case["case_id"],
        "world_group_id": world,
        "stratum": sidecar["stratum"],
        "pair": case["pair"],
        "visible_input": {
            "records": [
                public_record_view(row)
                for observation_id in case["pair"]
                for row in grouped[observation_id]
            ],
            "base_record_facts": [
                {
                    "observation_id": observation_id,
                    "received_at": first[observation_id]["received_at"],
                    "source_time": values[observation_id]["source_time"],
                    "asset_id": values[observation_id]["asset_id"],
                    "asset_binding_status": values[observation_id]["asset_binding_status"],
                    "modality": values[observation_id]["modality"],
                    "risk_flag": values[observation_id]["risk_flag"],
                    "quality_status": values[observation_id]["quality_status"],
                    "calibration_status": values[observation_id]["calibration_status"],
                    "position_m": values[observation_id]["position_m"],
                    "position_error_m": values[observation_id]["position_error_m"],
                    "value": values[observation_id]["value"],
                    "value_error": values[observation_id]["value_error"],
                    "unit": values[observation_id]["unit"],
                    "acquisition_lineage": values[observation_id]["acquisition_lineage"],
                }
                for observation_id in case["pair"]
            ],
            "distinct_acquisition_roots": roots,
            "distinct_acquisition_root_count": len(roots),
            "source_time_gap_seconds": abs(
                elapsed_seconds(source_times[0], origin) - elapsed_seconds(source_times[1], origin)
            ),
            "position_distance_m": position_delta,
            "value_difference": value_delta,
            "value_difference_allowance": (
                float(left["value_error"]) + float(right["value_error"]) + 2.5
            ),
            "same_id_updates": updates,
            "first_pair_candidate_cutoff": first_cutoff,
            "registered_cutoffs": sidecar["registered_cutoffs"],
        },
        "method_trace": snapshots,
        "analysis_only_scorer_truth": {
            "visibility": "SCORER_ONLY; NOT PROVIDED TO METHODS",
            "label": truth["label"],
            "first_sufficient_evidence_at": truth["first_sufficient_evidence_at"],
        },
    }


def extract_global_crosscheck() -> dict[str, Any]:
    """Compare saved final-cutoff actions and stored delay summaries only."""
    metrics = read_json(ATTEMPT / "metrics.json")
    delays = metrics["delay_and_censoring"]
    delays_equal = delays["TIME_ASSET_RULE"] == delays["MULTI_EVIDENCE_RULE"]
    if not delays_equal:
        raise AssertionError("saved delay summaries are no longer equal")

    disagreements = []
    scored_pair_count = 0
    for sidecar_path in sorted((ATTEMPT / "scorer_sidecars").glob("*.json")):
        sidecar = read_json(sidecar_path)
        world = sidecar["world_group_id"]
        final_cutoff = sidecar["registered_cutoffs"][-1]
        trace = read_json(ATTEMPT / "outputs" / world / "trace.json")
        actions_by_method: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
        for step in trace:
            if step["cutoff"] != final_cutoff:
                continue
            output = read_json(ATTEMPT / step["output_path"])
            actions_by_method[step["method"]] = {
                tuple(sorted((row["pair"]["left_observation_id"], row["pair"]["right_observation_id"]))): row
                for row in output["proposals"]
            }
        for truth in sidecar["pair_truths"]:
            scored_pair_count += 1
            pair = tuple(sorted((truth["pair"]["left_observation_id"], truth["pair"]["right_observation_id"])))
            time_row = actions_by_method["TIME_ASSET_RULE"].get(pair)
            multi_row = actions_by_method["MULTI_EVIDENCE_RULE"].get(pair)
            time_action = time_row["action"] if time_row else "IMPLICIT_ABSTAIN"
            multi_action = multi_row["action"] if multi_row else "IMPLICIT_ABSTAIN"
            if time_action != multi_action:
                disagreements.append(
                    {
                        "world_group_id": world,
                        "stratum": sidecar["stratum"],
                        "pair": list(pair),
                        "scorer_only_label": truth["label"],
                        "scorer_only_first_sufficient_evidence_at": truth["first_sufficient_evidence_at"],
                        "time_asset_action": time_action,
                        "time_asset_reason_codes": time_row["reason_codes"] if time_row else [],
                        "multi_evidence_action": multi_action,
                        "multi_evidence_reason_codes": multi_row["reason_codes"] if multi_row else [],
                    }
                )
    if scored_pair_count != 72 or len(disagreements) != 3:
        raise AssertionError(f"expected 72 scored rows and 3 final action disagreements; saw {scored_pair_count}/{len(disagreements)}")
    expected = {tuple(sorted(case["pair"])) for case in CASES}
    observed = {tuple(row["pair"]) for row in disagreements}
    if observed != expected:
        raise AssertionError(f"disagreement set changed: {observed}")
    return {
        "source": "saved_metrics_outputs_and_scorer_sidecars_only",
        "scored_pair_rows": scored_pair_count,
        "final_cutoff_action_disagreement_count": len(disagreements),
        "delay_summary_and_censoring_counts_equal": delays_equal,
        "delay_summaries": {
            method: {
                "valid_decision_observed_count": row["valid_decision_observed_count"],
                "observed_delay_seconds": row["observed_delay_seconds"],
                "right_censored_after_sufficient_evidence_count": row["right_censored_after_sufficient_evidence_count"],
                "right_censored_before_sufficient_evidence_count": row["right_censored_before_sufficient_evidence_count"],
                "unknown_excluded_count": row["unknown_excluded_count"],
            }
            for method, row in delays.items()
        },
        "disagreements": disagreements,
    }


def render_case(case: dict[str, Any], output_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    visible = case["visible_input"]
    records = visible["base_record_facts"]
    origin = min(
        datetime.fromisoformat(row["source_time"].replace("Z", "+00:00"))
        for row in records
    )
    fig, ax = plt.subplots(figsize=(13, 6.2), layout="constrained")
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    row_y = {"record_a": 5.1, "record_b": 4.2, "updates": 3.25, "time_asset": 2.25, "multi": 1.4}
    colors = {"record": "#276FBF", "update": "#B88700", "repeat": "#687386", "link": "#276FBF", "abstain": "#C05A16"}

    def sec(timestamp: str) -> float:
        return elapsed_seconds(timestamp, origin)

    # Each observation is shown as source-time diamond to first received-time circle.
    for idx, row in enumerate(records):
        y = row_y["record_a"] if idx == 0 else row_y["record_b"]
        source_x = sec(row["source_time"])
        received_x = sec(row["received_at"])
        ax.plot([source_x, received_x], [y, y], color=colors["record"], linewidth=2, alpha=0.65)
        ax.scatter([source_x], [y], marker="D", s=72, color="white", edgecolor=colors["record"], linewidth=1.7, zorder=3)
        ax.scatter([received_x], [y], marker="o", s=72, color=colors["record"], edgecolor="white", linewidth=0.9, zorder=3)
        full = row["observation_id"]
        label = f"{row['modality']} · {full[:14]}… · {row['risk_flag']}"
        ax.text(1.5, y + 0.14, label, ha="left", va="bottom", fontsize=9, color="#253247")

    # Mark only saved same-ID updates/repeats; do not infer an event boundary.
    for item in visible["same_id_updates"]:
        x = item["elapsed_seconds"]
        marker = "s" if "repeated base" in item["label"] else "^"
        color = colors["repeat"] if marker == "s" else colors["update"]
        ax.scatter([x], [row_y["updates"]], marker=marker, s=80, color=color, zorder=3)
        ax.annotate(
            item["label"],
            (x, row_y["updates"]),
            xytext=(0, 10 if marker == "^" else -16),
            textcoords="offset points",
            ha="center",
            va="bottom" if marker == "^" else "top",
            fontsize=8.2,
            color="#48566B",
            arrowprops={"arrowstyle": "-", "color": color, "lw": 0.8},
        )

    # Draw decisions at discrete registered snapshots, not as continuous state.
    for method, y, color, marker, label in [
        ("TIME_ASSET_RULE", row_y["time_asset"], colors["link"], "o", "LINK_CANDIDATES"),
        ("MULTI_EVIDENCE_RULE", row_y["multi"], colors["abstain"], "X", "ABSTAIN · NO_INDEPENDENT_ACQUISITION_ROOTS"),
    ]:
        rows = [row for row in case["method_trace"] if row["method"] == method and row["candidate_visible"]]
        xs = [sec(row["cutoff"]) for row in rows]
        ax.scatter(xs, [y] * len(xs), marker=marker, s=56, color=color, zorder=4)
        if xs:
            ax.text(xs[0] + 1.3, y + 0.18, f"{label} · {len(xs)} saved cutoffs", fontsize=8.4, color=color, ha="left", va="bottom")

    candidate_x = sec(visible["first_pair_candidate_cutoff"])
    ax.axvline(candidate_x, color="#64748B", linestyle=(0, (3, 3)), linewidth=1, alpha=0.8)
    ax.text(candidate_x + 1.2, 1.04, f"first candidate cutoff +{candidate_x:.0f}s", fontsize=8.2, color="#475569", va="bottom")
    for cutoff in visible["registered_cutoffs"]:
        x = sec(cutoff)
        ax.axvline(x, color="#D8DEE8", linewidth=0.65, zorder=0)

    ax.set_xlim(-3, 123)
    ax.set_ylim(0.42, 6.0)
    ax.set_yticks([row_y["record_a"], row_y["record_b"], row_y["updates"], row_y["time_asset"], row_y["multi"]])
    ax.set_yticklabels(["Visible record A", "Visible record B", "Same-ID later records", "TIME_ASSET_RULE", "MULTI_EVIDENCE_RULE"])
    ticks = list(range(0, 121, 20))
    ax.set_xticks(ticks)
    ax.set_xticklabels([(origin.replace(microsecond=0) + __import__("datetime").timedelta(seconds=x)).strftime("%H:%M:%S") for x in ticks])
    ax.set_xlabel("")
    ax.text(
        0.995,
        0.99,
        "UTC wall time · discrete saved prefixes",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=8.5,
        color="#64748B",
    )
    ax.grid(axis="x", color="#E5EAF1", linewidth=0.7)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="both", labelsize=9)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color("#AEB8C6")
    ax.spines["bottom"].set_color("#AEB8C6")

    facts = visible["base_record_facts"]
    fact_line = (
        f"Same verified asset · roots={visible['distinct_acquisition_root_count']} · "
        f"source-time gap={visible['source_time_gap_seconds']:.0f}s · "
        f"position delta={visible['position_distance_m']:.2f}m · "
        f"modalities={facts[0]['modality']} + {facts[1]['modality']}"
    )
    ax.set_title(f"{case['case_id']} · {case['world_group_id']}\n{fact_line}", loc="left", fontsize=11.5, color="#1F2937", pad=12)
    ax.text(
        61,
        0.56,
        "ANALYSIS ONLY — scorer truth: SAME; no sufficient-evidence time. Hidden from both methods.",
        ha="center",
        va="bottom",
        fontsize=8.8,
        color="#475569",
        bbox={"boxstyle": "round,pad=0.45", "facecolor": "#F1F4F8", "edgecolor": "#CBD5E1", "linestyle": "--"},
    )
    fig.savefig(output_path, dpi=170, facecolor="white")
    plt.close(fig)


def main() -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/pcg-analysis-mpl-cache")
    cases = [extract_case(case) for case in CASES]
    (ANALYSIS_DIR / "case_analysis_data.json").write_text(
        json.dumps(
            {
                "artifact_version": "same-pair-abstention-posthoc-analysis-v1",
                "run_scope": "READ_ONLY_DEVELOPMENT_ATTEMPT_02; NO_GENERATOR_METHOD_OR_SCORER_CALLS",
                "global_trace_crosscheck": extract_global_crosscheck(),
                "source_attempt_manifest_sha256": hashlib.sha256(
                    (ATTEMPT / "run_manifest.json").read_bytes()
                ).hexdigest(),
                "cases": cases,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    for case in cases:
        render_case(case, ANALYSIS_DIR / f"{case['case_id'].lower()}_timeline.png")
    print(f"wrote {len(cases)} case summaries and timelines; no run outputs modified")


if __name__ == "__main__":
    main()
