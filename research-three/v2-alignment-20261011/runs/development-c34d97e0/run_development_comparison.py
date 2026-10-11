#!/usr/bin/env python3
"""Run the one authorized, fixed-seed synthetic development comparison."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import traceback
from unittest.mock import patch


EXPECTED_COMMIT = "c34d97e0101554a362e927ed9e3ff239cedc319e"
RUN_DIR = Path(__file__).resolve().parent
REPO_ROOT = RUN_DIR.parents[3]
RUN_RELATIVE = RUN_DIR.relative_to(REPO_ROOT).as_posix()
os.environ.setdefault("MPLCONFIGDIR", "/tmp/pcg-development-mpl-cache")
sys.path.insert(0, str(REPO_ROOT / "risk-fusion-bench" / "src"))

from rfb.research import observable_association as association  # noqa: E402
from rfb.research import observable_association_evaluation as evaluation  # noqa: E402


METHODS = ("TIME_ASSET_RULE", "MULTI_EVIDENCE_RULE")
TRUTH_LABELS = ("SAME", "DIFFERENT", "UNKNOWN")
ACTIONS = ("LINK_CANDIDATES", "RETAIN_SEPARATELY", "ABSTAIN")
SOURCE_FILES = (
    "risk-fusion-bench/src/rfb/research/observable_association.py",
    "risk-fusion-bench/src/rfb/research/observable_association_evaluation.py",
    "research-three/v2-alignment-20261011/FINITE_SYNTHETIC_EVALUATION_PROTOCOL_DRAFT.md",
    "research-three/v2-alignment-20261011/AUTONOMOUS_ASSOCIATION_DEVELOPMENT_PLAN.md",
    "research-three/v2-alignment-20261011/MAC_PERSISTENCE_MANIFEST.json",
)

LOG_LINES: list[str] = []
FAILURES: list[dict[str, str]] = []
ARTIFACT_WRITE_NS = 0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def log(message: str) -> None:
    line = f"{utc_now()} {message}"
    print(line, flush=True)
    LOG_LINES.append(line)


def json_ready(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: json_ready(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_ready(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number in run artifact")
        return value
    raise TypeError(f"unsupported run-artifact type: {type(value).__name__}")


def canonical_json(value) -> bytes:
    return json.dumps(
        json_ready(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def write_bytes(path: Path, content: bytes) -> None:
    global ARTIFACT_WRITE_NS
    started = time.perf_counter_ns()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    ARTIFACT_WRITE_NS += time.perf_counter_ns() - started


def write_json(path: Path, value) -> None:
    content = json.dumps(
        json_ready(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ).encode("utf-8") + b"\n"
    write_bytes(path, content)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def pair_json(pair: association.CandidatePair) -> dict[str, str]:
    return {
        "left_observation_id": pair.left_observation_id,
        "right_observation_id": pair.right_observation_id,
    }


def sidecar_json(sidecar: evaluation.ScorerSidecar) -> dict:
    return {
        "split_name": sidecar.split_name,
        "world_group_id": sidecar.world_group_id,
        "stratum": sidecar.stratum.value,
        "evaluation_cutoff": sidecar.evaluation_cutoff,
        "registered_cutoffs": list(sidecar.registered_cutoffs),
        "pair_truths": [
            {
                "pair": pair_json(row.pair),
                "label": row.label.value,
                "first_sufficient_evidence_at": row.first_sufficient_evidence_at,
            }
            for row in sidecar.pair_truths
        ],
        "escalation_opportunities": [json_ready(row) for row in sidecar.escalation_opportunities],
    }


def field_value(record: association.ObservationRecord, name: str):
    field = next((item for item in record.fields if item.name == name), None)
    return None if field is None else field.value


def recursive_keys(value) -> set[str]:
    if isinstance(value, dict):
        keys = {str(key) for key in value}
        for item in value.values():
            keys.update(recursive_keys(item))
        return keys
    if isinstance(value, (tuple, list)):
        keys = set()
        for item in value:
            keys.update(recursive_keys(item))
        return keys
    return set()


def iso_seconds(timestamp: str) -> float:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return (parsed - evaluation._BASE_TIME).total_seconds()


def record_signature(record: association.ObservationRecord) -> str:
    return canonical_json(
        {
            "observation_id": record.observation_id,
            "id_actual_available_at": record.id_actual_available_at,
            "id_earliest_known_at": record.id_earliest_known_at,
            "fields": sorted(
                [json_ready(item) for item in record.fields], key=lambda row: row["name"]
            ),
        }
    ).decode("utf-8")


def current_git_state() -> dict:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=REPO_ROOT, text=True
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPO_ROOT,
        text=True,
    ).splitlines()
    tracked_diff = subprocess.run(
        ["git", "diff", "--quiet"], cwd=REPO_ROOT, check=False
    ).returncode
    staged_diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT, check=False
    ).returncode
    unexpected = [
        row for row in status if not row[3:].strip().startswith(RUN_RELATIVE + "/")
    ]
    return {
        "commit": commit,
        "branch": branch,
        "porcelain_status": status,
        "tracked_worktree_clean": tracked_diff == 0,
        "index_clean": staged_diff == 0,
        "only_this_run_artifact_is_untracked": not unexpected,
        "unexpected_status_rows": unexpected,
    }


def build_registered_index(plan) -> dict[str, dict]:
    rows = {}
    for stratum_index, stratum in enumerate(tuple(evaluation.SyntheticStratum)):
        for world_index in range(
            stratum_index * plan.worlds_per_stratum,
            (stratum_index + 1) * plan.worlds_per_stratum,
        ):
            world_id = evaluation._world_group_id(
                "development", plan.seed, world_index, stratum
            )
            registered_stratum, cutoffs = evaluation._registered_formal_world_schedules(
                "development"
            )[world_id]
            rows[world_id] = {
                "world_index": world_index,
                "stratum": registered_stratum,
                "registered_cutoffs": cutoffs,
            }
    return rows


def audit_worlds(worlds, plan) -> tuple[dict, list[dict]]:
    errors: list[dict] = []

    def require(condition: bool, code: str, details=None) -> None:
        if not condition:
            errors.append({"check": code, "details": json_ready(details)})

    expected = build_registered_index(plan)
    observed_ids = [world.scorer_only.world_group_id for world in worlds]
    require(len(worlds) == plan.world_budget, "development_world_budget", len(worlds))
    require(
        len(observed_ids) == len(set(observed_ids)),
        "world_ids_unique",
        observed_ids,
    )
    require(set(observed_ids) == set(expected), "world_ids_match_registered_seed", {
        "missing": sorted(set(expected) - set(observed_ids)),
        "extra": sorted(set(observed_ids) - set(expected)),
    })
    stratum_counts = Counter(world.scorer_only.stratum.value for world in worlds)
    expected_counts = {stratum.value: plan.worlds_per_stratum for stratum in evaluation.SyntheticStratum}
    require(dict(stratum_counts) == expected_counts, "balanced_development_strata", dict(stratum_counts))

    global_observation_ids: set[str] = set()
    global_root_ids: set[str] = set()
    global_asset_ids: set[str] = set()
    world_audits = []
    config = association.InferenceConfig()

    for world in worlds:
        sidecar = world.scorer_only
        trajectory = world.observable
        registration = expected.get(sidecar.world_group_id)
        observations = {record.observation_id for record in trajectory.records}
        abnormal_ids = {
            record.observation_id
            for record in trajectory.records
            if field_value(record, "risk_flag") in {"EXPOSURE", "EXPOSURE_HIGH"}
        }
        truth_pairs = {row.pair for row in sidecar.pair_truths}
        expected_pairs = {
            association.CandidatePair(left, right)
            for left, right in __import__("itertools").combinations(sorted(abnormal_ids), 2)
        }
        labels = Counter(row.label.value for row in sidecar.pair_truths)
        expected_labels = (
            {"SAME": 2, "DIFFERENT": 3, "UNKNOWN": 1}
            if sidecar.stratum is evaluation.SyntheticStratum.DEPENDENT_REPLAY_UNKNOWN
            else {"SAME": 2, "DIFFERENT": 4, "UNKNOWN": 0}
        )
        require(registration is not None, "world_id_is_registered", sidecar.world_group_id)
        if registration is not None:
            require(registration["stratum"] is sidecar.stratum, "world_stratum_matches_registration", sidecar.world_group_id)
            require(tuple(trajectory.cutoffs) == tuple(registration["registered_cutoffs"]), "world_cutoffs_match_registration", sidecar.world_group_id)
        require(sidecar.split_name == "development", "no_non_development_world", sidecar.split_name)
        require(len(abnormal_ids) == 4, "four_unique_abnormal_ids", sorted(abnormal_ids))
        require(len(sidecar.pair_truths) == 6 and truth_pairs == expected_pairs, "fixed_six_pair_universe", {
            "truth_pairs": len(sidecar.pair_truths), "expected_pairs": len(expected_pairs)
        })
        require(dict(labels) == expected_labels, "registered_label_allocation", {
            "stratum": sidecar.stratum.value, "observed": dict(labels), "expected": expected_labels
        })
        require(sidecar.registered_cutoffs == trajectory.cutoffs, "sidecar_matches_observable_cutoffs", sidecar.world_group_id)
        require(len(trajectory.cutoffs) <= 8, "cutoff_budget", len(trajectory.cutoffs))
        require(sidecar.evaluation_cutoff == evaluation._stamp(120), "common_terminal_cutoff", sidecar.evaluation_cutoff)

        root_by_observation: dict[str, set[str]] = {}
        root_ids: set[str] = set()
        asset_ids: set[str] = set()
        late_fact_count = 0
        for record in trajectory.records:
            lineage = field_value(record, "acquisition_lineage")
            if isinstance(lineage, tuple) and lineage:
                root = str(lineage[0])
                root_ids.add(root)
                root_by_observation.setdefault(record.observation_id, set()).add(root)
            asset = field_value(record, "asset_id")
            if isinstance(asset, str):
                asset_ids.add(asset)
            if record.id_earliest_known_at < record.id_actual_available_at:
                require(False, "observation_id_availability_order", record.observation_id)
            for item in record.fields:
                if item.earliest_known_at < item.actual_available_at:
                    require(False, "field_availability_order", {"observation_id": record.observation_id, "field": item.name})
                if item.earliest_known_at > item.actual_available_at:
                    late_fact_count += 1
        require(late_fact_count >= 1, "late_facts_present", late_fact_count)
        require(abnormal_ids.issubset(root_by_observation), "abnormal_observations_have_lineage", sorted(abnormal_ids - set(root_by_observation)))
        for row in sidecar.pair_truths:
            roots = root_by_observation.get(row.pair.left_observation_id, set()) | root_by_observation.get(row.pair.right_observation_id, set())
            if row.label is evaluation.PairTruthLabel.SAME:
                require(
                    (row.first_sufficient_evidence_at is not None) == (len(roots) >= 2),
                    "same_pair_sufficiency_matches_independent_roots",
                    {"pair": pair_json(row.pair), "roots": len(roots)},
                )
            elif row.label is evaluation.PairTruthLabel.DIFFERENT:
                require(row.first_sufficient_evidence_at is not None, "different_pair_has_sufficiency_time", pair_json(row.pair))
            else:
                require(row.first_sufficient_evidence_at is None, "unknown_pair_has_no_sufficiency_time", pair_json(row.pair))

        exact_signatures = Counter(record_signature(record) for record in trajectory.records)
        exact_replay_signatures = sum(count - 1 for count in exact_signatures.values() if count > 1)
        expected_replay_count = 1 if sidecar.stratum is evaluation.SyntheticStratum.DEPENDENT_REPLAY_UNKNOWN else 0
        require(exact_replay_signatures == expected_replay_count, "exact_replay_count", {
            "observed": exact_replay_signatures, "expected": expected_replay_count
        })
        recovery_count = sum(field_value(record, "risk_flag") == "RECOVERY" for record in trajectory.records)
        expected_recovery_count = 1 if sidecar.stratum is evaluation.SyntheticStratum.RECOVERY_THEN_NEW_EVENT else 0
        require(recovery_count == expected_recovery_count, "recovery_marker_count", {
            "observed": recovery_count, "expected": expected_recovery_count
        })

        overlap_observations = global_observation_ids.intersection(observations)
        overlap_roots = global_root_ids.intersection(root_ids)
        overlap_assets = global_asset_ids.intersection(asset_ids)
        require(not overlap_observations, "observation_ids_disjoint_across_worlds", sorted(overlap_observations))
        require(not overlap_roots, "lineage_roots_disjoint_across_worlds", sorted(overlap_roots))
        require(not overlap_assets, "asset_ids_disjoint_across_worlds", sorted(overlap_assets))
        global_observation_ids.update(observations)
        global_root_ids.update(root_ids)
        global_asset_ids.update(asset_ids)

        fixed_pairs = set(expected_pairs)
        candidate_trace = []
        previous_candidates: set[association.CandidatePair] = set()
        for cutoff in trajectory.cutoffs:
            prefix = association.freeze_observable_prefix(trajectory.records, as_of=cutoff)
            candidates = association.build_candidate_universe(prefix, config=config)
            candidate_set = set(candidates)
            require(candidate_set.issubset(fixed_pairs), "cutoff_candidates_subset_of_fixed_universe", {
                "world_group_id": sidecar.world_group_id, "cutoff": cutoff
            })
            require(previous_candidates.issubset(candidate_set), "candidate_set_monotonicity", {
                "world_group_id": sidecar.world_group_id, "cutoff": cutoff
            })
            candidate_trace.append({
                "cutoff": cutoff,
                "input_prefix_sha256": evaluation._prefix_sha256(prefix),
                "candidate_pairs": [pair_json(pair) for pair in candidates],
                "candidate_pair_count": len(candidates),
            })
            previous_candidates = candidate_set

        input_bytes = evaluation.serialize_observable_trajectory(trajectory)
        input_doc = json.loads(input_bytes.decode("utf-8"))
        forbidden_input_keys = {
            "world_group_id", "stratum", "split_name", "truth", "truth_label",
            "first_sufficient_evidence_at", "evaluation_cutoff", "alert_escalation_opportunities",
        }
        found_forbidden = sorted(forbidden_input_keys.intersection(recursive_keys(input_doc)))
        require(not found_forbidden, "method_input_has_no_scorer_fields", found_forbidden)
        world_slug = sidecar.world_group_id
        write_bytes(RUN_DIR / "inputs" / f"{world_slug}.json", input_bytes)
        write_json(RUN_DIR / "scorer_sidecars" / f"{world_slug}.json", sidecar_json(sidecar))
        world_audits.append({
            "world_group_id": sidecar.world_group_id,
            "world_index": None if registration is None else registration["world_index"],
            "stratum": sidecar.stratum.value,
            "unique_abnormal_observation_ids": sorted(abnormal_ids),
            "fixed_pair_count": len(sidecar.pair_truths),
            "pair_label_counts": dict(labels),
            "observation_record_count": len(trajectory.records),
            "unique_observation_id_count": len(observations),
            "unique_lineage_root_count": len(root_ids),
            "unique_asset_id_count": len(asset_ids),
            "late_fact_count": late_fact_count,
            "exact_replay_count": exact_replay_signatures,
            "recovery_marker_count": recovery_count,
            "evaluation_cutoff": sidecar.evaluation_cutoff,
            "registered_cutoffs": list(sidecar.registered_cutoffs),
            "cutoff_trace": candidate_trace,
            "observable_input_sha256": sha256_bytes(input_bytes),
            "scorer_sidecar_sha256": file_sha256(RUN_DIR / "scorer_sidecars" / f"{world_slug}.json"),
        })

    audit = {
        "split_name": "development",
        "world_count": len(worlds),
        "stratum_counts": dict(stratum_counts),
        "expected_stratum_counts": expected_counts,
        "registered_world_count": len(expected),
        "unique_observation_ids_across_worlds": len(global_observation_ids),
        "unique_lineage_roots_across_worlds": len(global_root_ids),
        "unique_assets_across_worlds": len(global_asset_ids),
        "worlds": world_audits,
        "errors": errors,
        "status": "PASS" if not errors else "INVALID_RUN",
    }
    return audit, errors


def timed_method(method_name: str, method, observations: dict[str, list[int]]):
    def wrapper(*args, **kwargs):
        started = time.perf_counter_ns()
        try:
            return method(*args, **kwargs)
        finally:
            observations[method_name].append(time.perf_counter_ns() - started)
    return wrapper


def save_step_outputs(world_id: str, steps) -> tuple[list[dict], dict]:
    trace_rows = []
    trace_by_cutoff_method = {}
    output_dir = RUN_DIR / "outputs" / world_id
    for step in steps:
        raw = step.output.canonical_json
        actual_hash = sha256_bytes(raw)
        if actual_hash != step.output.sha256:
            raise ValueError(f"frozen output hash mismatch for {world_id} {step.method} {step.cutoff}")
        cutoff_index = step.cutoff
        rel_path = Path("outputs") / world_id / f"{len(trace_rows):02d}_{step.method}.json"
        write_bytes(RUN_DIR / rel_path, raw)
        row = {
            "method": step.method,
            "cutoff": step.cutoff,
            "input_prefix_sha256": step.input_prefix_sha256,
            "candidate_pairs": [pair_json(pair) for pair in step.candidate_pairs],
            "candidate_pair_count": len(step.candidate_pairs),
            "output_path": rel_path.as_posix(),
            "output_sha256": actual_hash,
        }
        trace_rows.append(row)
        trace_by_cutoff_method[(step.cutoff, step.method)] = step
    write_json(output_dir / "trace.json", trace_rows)
    return trace_rows, trace_by_cutoff_method


def summarize_durations(values: list[int]) -> dict:
    if not values:
        return {"count": 0, "mean_seconds": None, "median_seconds": None, "min_seconds": None, "max_seconds": None}
    seconds = [float(value) for value in values]
    return {
        "count": len(seconds),
        "mean_seconds": statistics.fmean(seconds),
        "median_seconds": statistics.median(seconds),
        "min_seconds": min(seconds),
        "max_seconds": max(seconds),
        "raw_seconds": seconds,
    }


def build_metrics(worlds, scores, all_steps, aggregate, rule_call_ns, rule_call_counts) -> dict:
    score_by_id = {row["world_group_id"]: row for row in scores}
    world_by_id = {world.scorer_only.world_group_id: world for world in worlds}
    confusion = {}
    metrics_by_method = {}
    method_costs = {}
    delay_by_method = {}
    per_world_rows = []
    per_stratum = {}
    max_invocation_budget = (
        evaluation.get_split_plan("development").world_budget
        * evaluation._MAX_CUTOFFS_PER_WORLD
        * evaluation._MAX_PAIR_COUNT_PER_WORLD
    )

    for method in METHODS:
        matrix = {truth: {action: 0 for action in ACTIONS} for truth in TRUTH_LABELS}
        unknown_actions = Counter({action: 0 for action in ACTIONS})
        scorer_unknown_actions = Counter({action: 0 for action in ACTIONS})
        metric_counts = Counter()
        status_counts = Counter()
        observed_delays = []
        after_censor_delays = []
        before_censor_delays = []
        stratum_values: dict[str, list[dict]] = {}

        for world_id, world in world_by_id.items():
            score = score_by_id[world_id]
            sidecar = world.scorer_only
            final_cutoff = sidecar.evaluation_cutoff
            final_step = next(
                step for step in all_steps[world_id]
                if step.method == method and step.cutoff == final_cutoff
            )
            output_doc = json.loads(final_step.output.canonical_json.decode("utf-8"))
            actions = {
                (row["pair"]["left_observation_id"], row["pair"]["right_observation_id"]): row["action"]
                for row in output_doc["proposals"]
            }
            timing_rows = score["methods"][method]["decision_timing"]
            timing_by_pair = {
                (row["pair"]["left_observation_id"], row["pair"]["right_observation_id"]): row
                for row in timing_rows
            }
            for truth in sidecar.pair_truths:
                pair_key = (truth.pair.left_observation_id, truth.pair.right_observation_id)
                action = actions.get(pair_key, "ABSTAIN")
                matrix[truth.label.value][action] += 1
                if truth.label is evaluation.PairTruthLabel.UNKNOWN:
                    unknown_actions[action] += 1
                timing = timing_by_pair[pair_key]
                status_counts[timing["status"]] += 1
                if timing["status"] == "VALID_DECISION_OBSERVED":
                    observed_delays.append(int(timing["duration_seconds"]))
                elif timing["status"] == "RIGHT_CENSORED_AFTER_SUFFICIENT_EVIDENCE":
                    after_censor_delays.append(int(timing["duration_seconds"]))
                elif timing["status"] == "RIGHT_CENSORED_BEFORE_SUFFICIENT_EVIDENCE":
                    before_censor_delays.append(int(timing["duration_seconds"]))

            method_score = score["methods"][method]
            for key in (
                "false_merge_count", "different_pair_denominator", "false_split_count",
                "same_pair_denominator", "coverage_count", "coverage_denominator",
                "candidate_generation_recall_count", "candidate_generation_recall_denominator",
                "unknown_pair_count",
            ):
                metric_counts[key] += int(method_score[key])
            for action, count in method_score["unknown_action_counts"].items():
                scorer_unknown_actions[action] += int(count)
            per_world_rows.append({
                "world_group_id": world_id,
                "stratum": sidecar.stratum.value,
                "method": method,
                "false_merge_count": method_score["false_merge_count"],
                "different_pair_denominator": method_score["different_pair_denominator"],
                "false_split_count": method_score["false_split_count"],
                "same_pair_denominator": method_score["same_pair_denominator"],
                "coverage_count": method_score["coverage_count"],
                "coverage_denominator": method_score["coverage_denominator"],
                "candidate_generation_recall_count": method_score["candidate_generation_recall_count"],
                "candidate_generation_recall_denominator": method_score["candidate_generation_recall_denominator"],
                "unknown_pair_count": method_score["unknown_pair_count"],
                "unknown_action_counts": method_score["unknown_action_counts"],
                "timing_status_counts": method_score["timing_status_counts"],
            })
            stratum_values.setdefault(sidecar.stratum.value, []).append(method_score)

        confusion[method] = {
            "truth_labels": list(TRUTH_LABELS),
            "actions": list(ACTIONS),
            "counts": [[matrix[truth][action] for action in ACTIONS] for truth in TRUTH_LABELS],
            "row_denominators": {truth: sum(matrix[truth].values()) for truth in TRUTH_LABELS},
            "total_pair_rows": sum(sum(matrix[truth].values()) for truth in TRUTH_LABELS),
        }
        if matrix["DIFFERENT"]["LINK_CANDIDATES"] != metric_counts["false_merge_count"]:
            raise ValueError(f"confusion/false-merge mismatch for {method}")
        if matrix["SAME"]["RETAIN_SEPARATELY"] != metric_counts["false_split_count"]:
            raise ValueError(f"confusion/false-split mismatch for {method}")
        non_abstaining_count = sum(
            matrix[truth][action]
            for truth in TRUTH_LABELS
            for action in ACTIONS
            if action != "ABSTAIN"
        )
        if non_abstaining_count != metric_counts["coverage_count"]:
            raise ValueError(f"confusion/coverage mismatch for {method}")
        if sum(unknown_actions.values()) != metric_counts["unknown_pair_count"]:
            raise ValueError(f"unknown-action count mismatch for {method}")
        if dict(unknown_actions) != dict(scorer_unknown_actions):
            raise ValueError(f"unknown actions differ from scorer output for {method}")
        if sum(status_counts.values()) != metric_counts["coverage_denominator"]:
            raise ValueError(f"timing rows do not cover the fixed pair universe for {method}")
        summary = aggregate["methods"][method]
        metrics_by_method[method] = {
            "independent_world_count": len(worlds),
            "fixed_pair_denominator": metric_counts["coverage_denominator"],
            "false_merge": {
                "count": metric_counts["false_merge_count"],
                "denominator": metric_counts["different_pair_denominator"],
                "pooled_descriptive_rate": (
                    metric_counts["false_merge_count"] / metric_counts["different_pair_denominator"]
                    if metric_counts["different_pair_denominator"] else None
                ),
                "world_macro_rate": summary["false_merge_rate"]["world_macro"],
                "worlds_evaluable": summary["false_merge_rate"]["worlds_evaluable"],
            },
            "false_split": {
                "count": metric_counts["false_split_count"],
                "denominator": metric_counts["same_pair_denominator"],
                "pooled_descriptive_rate": (
                    metric_counts["false_split_count"] / metric_counts["same_pair_denominator"]
                    if metric_counts["same_pair_denominator"] else None
                ),
                "world_macro_rate": summary["false_split_rate"]["world_macro"],
                "worlds_evaluable": summary["false_split_rate"]["worlds_evaluable"],
            },
            "coverage": {
                "count": metric_counts["coverage_count"],
                "denominator": metric_counts["coverage_denominator"],
                "pooled_descriptive_rate": (
                    metric_counts["coverage_count"] / metric_counts["coverage_denominator"]
                    if metric_counts["coverage_denominator"] else None
                ),
                "world_macro_rate": summary["coverage"]["world_macro"],
                "worlds_evaluable": summary["coverage"]["worlds_evaluable"],
            },
            "candidate_generation_recall": {
                "count": metric_counts["candidate_generation_recall_count"],
                "denominator": metric_counts["candidate_generation_recall_denominator"],
                "world_macro_rate": summary["candidate_generation_recall"]["world_macro"],
                "worlds_evaluable": summary["candidate_generation_recall"]["worlds_evaluable"],
            },
            "unknown": {
                "pair_count": metric_counts["unknown_pair_count"],
                "action_counts": dict(unknown_actions),
            },
        }
        evidence_eligible = (
            status_counts["VALID_DECISION_OBSERVED"]
            + status_counts["RIGHT_CENSORED_AFTER_SUFFICIENT_EVIDENCE"]
        )
        delay_by_method[method] = {
            "timing_status_counts": dict(status_counts),
            "evidence_after_eligible_pair_count": evidence_eligible,
            "valid_decision_observed_count": status_counts["VALID_DECISION_OBSERVED"],
            "right_censored_after_sufficient_evidence_count": status_counts["RIGHT_CENSORED_AFTER_SUFFICIENT_EVIDENCE"],
            "right_censored_before_sufficient_evidence_count": status_counts["RIGHT_CENSORED_BEFORE_SUFFICIENT_EVIDENCE"],
            "unknown_excluded_count": status_counts["UNKNOWN_EXCLUDED"],
            "observed_delay_seconds": summarize_durations(observed_delays),
            "after_evidence_censor_duration_seconds": summarize_durations(after_censor_delays),
            "before_evidence_censor_duration_seconds": summarize_durations(before_censor_delays),
            "delay_interpretation": "DESCRIPTIVE_CONDITIONAL_ON_SUFFICIENT_EVIDENCE; CENSORED_ROWS_RETAINED; NO_SURVIVAL_MODEL",
        }
        stratum_metrics = {}
        for stratum, rows in stratum_values.items():
            denominators = {
                "false_merge": sum(int(row["different_pair_denominator"]) for row in rows),
                "false_split": sum(int(row["same_pair_denominator"]) for row in rows),
                "coverage": sum(int(row["coverage_denominator"]) for row in rows),
            }
            numerators = {
                "false_merge": sum(int(row["false_merge_count"]) for row in rows),
                "false_split": sum(int(row["false_split_count"]) for row in rows),
                "coverage": sum(int(row["coverage_count"]) for row in rows),
            }
            stratum_metrics[stratum] = {
                "world_count": len(rows),
                "false_merge": {"count": numerators["false_merge"], "denominator": denominators["false_merge"]},
                "false_split": {"count": numerators["false_split"], "denominator": denominators["false_split"]},
                "coverage": {"count": numerators["coverage"], "denominator": denominators["coverage"]},
            }
        per_stratum[method] = stratum_metrics
        calls = []
        unique_world_pairs = set()
        for world_id, steps in all_steps.items():
            for step in steps:
                if step.method != method:
                    continue
                for pair in step.candidate_pairs:
                    calls.append((world_id, pair.left_observation_id, pair.right_observation_id))
                    unique_world_pairs.add((world_id, pair.left_observation_id, pair.right_observation_id))
        total_calls = len(calls)
        method_costs[method] = {
            "registered_cutoff_outputs": sum(
                sum(1 for step in steps if step.method == method) for steps in all_steps.values()
            ),
            "rule_function_invocations": total_calls,
            "distinct_world_pair_candidates_ever_seen": len(unique_world_pairs),
            "repeated_prefix_invocations": total_calls - len(unique_world_pairs),
            "max_invocation_budget_per_arm": max_invocation_budget,
            "invocation_budget_used_fraction": total_calls / max_invocation_budget if max_invocation_budget else None,
            "measured_rule_function_time_ns": sum(rule_call_ns[method]),
            "measured_rule_function_time_seconds": sum(rule_call_ns[method]) / 1_000_000_000,
            "measured_rule_function_time_median_us": (
                statistics.median(rule_call_ns[method]) / 1000 if rule_call_ns[method] else None
            ),
            "measured_rule_function_call_count": rule_call_counts[method],
            "timing_note": "LOCAL_DESCRIPTIVE_WALL_TIME_INCLUDES_WRAPPER_INSTRUMENTATION; NOT_A_PERFORMANCE_BENCHMARK",
        }

    return {
        "classification_and_coverage": metrics_by_method,
        "confusion_matrices": confusion,
        "delay_and_censoring": delay_by_method,
        "compute_cost": method_costs,
        "per_world": per_world_rows,
        "per_stratum": per_stratum,
        "aggregate_world_scores_output": aggregate,
        "interpretation_scope": "SYNTHETIC_DEVELOPMENT_ONLY; POOLED_PAIR_COUNTS_ARE_DESCRIPTIVE; NO_INDEPENDENCE_ASSUMPTION_FOR_PAIRS_PREFIXES_OR_METHOD_ARMS",
    }


def make_charts(worlds, all_steps, scores, metrics) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    charts_dir = RUN_DIR / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    chart_data_dir = RUN_DIR / "chart_data"
    chart_data_dir.mkdir(parents=True, exist_ok=True)

    # Figure 1: pooled final confusion counts and the protocol's full-universe coverage.
    matrices = metrics["confusion_matrices"]
    max_cell = max(
        max(value for row in matrices[method]["counts"] for value in row)
        for method in METHODS
    )
    cmap = plt.get_cmap("Blues")
    fig, axes = plt.subplots(
        1, 3, figsize=(17, 6), gridspec_kw={"width_ratios": [1.15, 1.15, 0.9]}
    )
    for axis, method, title in zip(
        axes[:2], METHODS, ("Time + asset rule", "Multi-evidence rule")
    ):
        values = matrices[method]["counts"]
        image = axis.imshow(values, cmap=cmap, vmin=0, vmax=max(1, max_cell))
        axis.set_title(title, fontsize=12, color="#263238")
        axis.set_xticks(range(len(ACTIONS)), ["Link", "Retain", "Abstain"], rotation=0)
        row_names = [
            f"{label}\n(n={matrices[method]['row_denominators'][label]})"
            for label in TRUTH_LABELS
        ]
        axis.set_yticks(range(len(TRUTH_LABELS)), row_names)
        axis.set_xlabel("Final action")
        axis.set_ylabel("Scorer label")
        axis.set_xticks([x - 0.5 for x in range(1, len(ACTIONS))], minor=True)
        axis.set_yticks([y - 0.5 for y in range(1, len(TRUTH_LABELS))], minor=True)
        axis.grid(which="minor", color="white", linewidth=2)
        axis.tick_params(which="minor", bottom=False, left=False)
        for i, row in enumerate(values):
            for j, value in enumerate(row):
                text_color = "white" if value > max_cell * 0.55 else "#263238"
                axis.text(j, i, str(value), ha="center", va="center", color=text_color, fontsize=11)
    coverage_axis = axes[2]
    coverage_values = [
        metrics["classification_and_coverage"][method]["coverage"]["pooled_descriptive_rate"]
        for method in METHODS
    ]
    coverage_counts = [
        metrics["classification_and_coverage"][method]["coverage"]["count"]
        for method in METHODS
    ]
    coverage_denominators = [
        metrics["classification_and_coverage"][method]["coverage"]["denominator"]
        for method in METHODS
    ]
    bar_colors = ["#2C6E9B", "#53636D"]
    bars = coverage_axis.bar(["Time +\nasset", "Multi-\nevidence"], coverage_values, color=bar_colors, width=0.62)
    coverage_axis.set_ylim(0, 1.05)
    coverage_axis.set_ylabel("Pooled coverage")
    coverage_axis.set_title("Fixed six-pair universe", fontsize=12, color="#263238")
    coverage_axis.set_yticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
    coverage_axis.grid(axis="y", color="#D9DEE2", linewidth=0.8)
    coverage_axis.set_axisbelow(True)
    for bar, rate, count, denominator in zip(bars, coverage_values, coverage_counts, coverage_denominators):
        coverage_axis.text(
            bar.get_x() + bar.get_width() / 2,
            min(rate + 0.04, 1.01),
            f"{count}/{denominator}\n{rate:.1%}",
            ha="center", va="bottom", fontsize=10, color="#263238",
        )
    fig.suptitle(
        "SYNTHETIC DEVELOPMENT — final pair actions and coverage",
        fontsize=15, color="#202A30", y=0.98,
    )
    fig.text(
        0.5, 0.015,
        "Pooled descriptive counts across 12 worlds (72 fixed pair rows per rule). UNKNOWN remains in coverage; rows, cutoffs and rules are not independent samples.",
        ha="center", fontsize=9, color="#45545C",
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.93))
    confusion_path = charts_dir / "final_confusion_and_coverage.png"
    fig.savefig(confusion_path, dpi=220, facecolor="white", bbox_inches="tight")
    plt.close(fig)

    confusion_chart_data = {
        "scope": "SYNTHETIC_DEVELOPMENT",
        "independent_world_count": 12,
        "fixed_pair_rows_per_method": 72,
        "truth_labels": list(TRUTH_LABELS),
        "actions": list(ACTIONS),
        "methods": matrices,
        "coverage": {
            method: metrics["classification_and_coverage"][method]["coverage"]
            for method in METHODS
        },
    }
    write_json(chart_data_dir / "final_confusion_and_coverage.json", confusion_chart_data)

    # Figure 2: one preselected registered world, showing arrivals, evidence and actions.
    plan = evaluation.get_split_plan("development")
    world_index = 0
    stratum = evaluation.SyntheticStratum.INDEPENDENT_SAME_EVENT
    timeline_world_id = evaluation._world_group_id("development", plan.seed, world_index, stratum)
    world_by_id = {world.scorer_only.world_group_id: world for world in worlds}
    timeline_world = world_by_id[timeline_world_id]
    same_pair = next(
        row for row in timeline_world.scorer_only.pair_truths
        if row.label is evaluation.PairTruthLabel.SAME
        and row.first_sufficient_evidence_at is not None
    )
    pair_ids = (same_pair.pair.left_observation_id, same_pair.pair.right_observation_id)
    abnormal_ids = sorted({
        record.observation_id for record in timeline_world.observable.records
        if field_value(record, "risk_flag") in {"EXPOSURE", "EXPOSURE_HIGH"}
    })
    timeline_ids = list(pair_ids) + [item for item in abnormal_ids if item not in pair_ids]
    role_labels = ["selected SAME pair · left", "selected SAME pair · right"] + [
        f"other abnormal · {index + 1}" for index in range(len(timeline_ids) - 2)
    ]
    first_received = {}
    for observation_id in timeline_ids:
        receipts = [
            record.received_at for record in timeline_world.observable.records
            if record.observation_id == observation_id
        ]
        first_received[observation_id] = min(receipts, key=iso_seconds)

    timeline_steps = all_steps[timeline_world_id]
    cutoff_seconds = [iso_seconds(value) for value in timeline_world.observable.cutoffs]
    fig, (arrival_axis, action_axis) = plt.subplots(
        2, 1, figsize=(13, 8), sharex=True,
        gridspec_kw={"height_ratios": [1.0, 1.25]},
    )
    for axis in (arrival_axis, action_axis):
        for x in cutoff_seconds:
            axis.axvline(x, color="#E6EAED", linewidth=0.8, zorder=0)
    for y, observation_id in enumerate(timeline_ids[::-1]):
        x = iso_seconds(first_received[observation_id])
        arrival_axis.scatter([x], [y], s=70, color="#2C6E9B", zorder=3)
        arrival_axis.text(x + 1.2, y, f"{x:.0f}s", va="center", fontsize=9, color="#263238")
    arrival_axis.set_yticks(range(len(timeline_ids)), role_labels[::-1])
    arrival_axis.set_ylim(-0.7, len(timeline_ids) - 0.3)
    arrival_axis.set_title("First received time for the four abnormal observations", loc="left", fontsize=11)
    arrival_axis.set_ylabel("Observable arrival")
    evidence_seconds = iso_seconds(same_pair.first_sufficient_evidence_at)
    for axis in (arrival_axis, action_axis):
        axis.axvline(evidence_seconds, color="#263238", linestyle="--", linewidth=1.4, zorder=2)
    arrival_axis.text(evidence_seconds + 1, len(timeline_ids) - 0.5, "sufficient evidence", fontsize=9, color="#263238")

    marker_style = {
        "LINK_CANDIDATES": ("o", "#2C6E9B", "Link"),
        "RETAIN_SEPARATELY": ("^", "#C2811C", "Retain"),
        "ABSTAIN": ("x", "#69777F", "Abstain"),
        "NOT_CANDIDATE": ("s", "white", "Not in candidate set"),
    }
    method_y = {"TIME_ASSET_RULE": 1, "MULTI_EVIDENCE_RULE": 0}
    action_rows = []
    for method in METHODS:
        y = method_y[method]
        for cutoff in timeline_world.observable.cutoffs:
            step = next(
                row for row in timeline_steps
                if row.method == method and row.cutoff == cutoff
            )
            proposals = json.loads(step.output.canonical_json.decode("utf-8"))["proposals"]
            pair_actions = {
                (item["pair"]["left_observation_id"], item["pair"]["right_observation_id"]): item["action"]
                for item in proposals
            }
            pair_key = (same_pair.pair.left_observation_id, same_pair.pair.right_observation_id)
            action = pair_actions.get(pair_key, "NOT_CANDIDATE")
            marker, color, _ = marker_style[action]
            if action == "NOT_CANDIDATE":
                action_axis.scatter(
                    [iso_seconds(cutoff)], [y], marker=marker, s=85,
                    facecolors="white", edgecolors="#69777F", linewidths=1.5, zorder=4,
                )
            else:
                action_axis.scatter(
                    [iso_seconds(cutoff)], [y], marker=marker, s=85,
                    color=color, linewidths=1.5, zorder=4,
                )
            action_rows.append({
                "method": method,
                "cutoff": cutoff,
                "action": action,
                "candidate_at_cutoff": action != "NOT_CANDIDATE",
                "input_prefix_sha256": step.input_prefix_sha256,
            })
    action_axis.set_yticks([0, 1], ["Multi-evidence rule", "Time + asset rule"])
    action_axis.set_ylim(-0.6, 1.6)
    action_axis.set_ylabel("Proposal action")
    action_axis.set_xlabel("Seconds from synthetic world start")
    action_axis.set_xticks(cutoff_seconds, [f"{int(value)}" for value in cutoff_seconds])
    action_axis.grid(axis="y", color="#D9DEE2", linewidth=0.8)
    action_axis.set_axisbelow(True)
    handles = [
        Line2D([0], [0], marker=marker_style[action][0], color="none",
               markerfacecolor=marker_style[action][1],
               markeredgecolor=("#69777F" if action == "NOT_CANDIDATE" else marker_style[action][1]),
               markersize=8, label=marker_style[action][2])
        for action in ("LINK_CANDIDATES", "RETAIN_SEPARATELY", "ABSTAIN", "NOT_CANDIDATE")
    ]
    action_axis.legend(handles=handles, loc="lower right", ncol=2, frameon=False)
    fig.suptitle(
        f"SYNTHETIC DEVELOPMENT — registered world index 0, {same_pair.pair.left_observation_id[-6:]} ↔ {same_pair.pair.right_observation_id[-6:]}",
        fontsize=14, color="#202A30", y=0.98,
    )
    fig.text(
        0.5, 0.015,
        "Dashed line: scorer first_sufficient_evidence_at for this SAME pair. Not-in-candidate is scored as implicit ABSTAIN; action rows are shared fixed cutoffs.",
        ha="center", fontsize=9, color="#45545C",
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.93))
    timeline_path = charts_dir / "registered_world_000_same_pair_timeline.png"
    fig.savefig(timeline_path, dpi=220, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    timeline_chart_data = {
        "scope": "SYNTHETIC_DEVELOPMENT",
        "world_group_id": timeline_world_id,
        "world_index": world_index,
        "stratum": stratum.value,
        "pair": pair_json(same_pair.pair),
        "label": same_pair.label.value,
        "first_sufficient_evidence_at": same_pair.first_sufficient_evidence_at,
        "first_received_at_by_observation": first_received,
        "registered_cutoffs": list(timeline_world.observable.cutoffs),
        "actions": action_rows,
    }
    write_json(chart_data_dir / "registered_world_000_same_pair_timeline.json", timeline_chart_data)
    return {
        "final_confusion_and_coverage": (confusion_path.relative_to(RUN_DIR).as_posix(), file_sha256(confusion_path)),
        "registered_world_000_same_pair_timeline": (timeline_path.relative_to(RUN_DIR).as_posix(), file_sha256(timeline_path)),
        "timeline_world_group_id": timeline_world_id,
        "timeline_pair": pair_json(same_pair.pair),
    }


def format_rate(row: dict) -> str:
    rate = row["pooled_descriptive_rate"]
    macro = row["world_macro_rate"]
    return f"{row['count']}/{row['denominator']} ({rate:.1%}; world macro {macro:.1%})"


def make_report(run_meta, audit, metrics, runtime, charts, status) -> str:
    rows = []
    for method in METHODS:
        score = metrics["classification_and_coverage"][method]
        delay = metrics["delay_and_censoring"][method]
        cost = metrics["compute_cost"][method]
        rows.append(
            f"| {method} | {format_rate(score['false_merge'])} | {format_rate(score['false_split'])} | {format_rate(score['coverage'])} | {score['unknown']['pair_count']} ({score['unknown']['action_counts']}) | {delay['valid_decision_observed_count']}/{delay['evidence_after_eligible_pair_count']} | {cost['rule_function_invocations']} ({cost['repeated_prefix_invocations']} repeated) |"
        )
    delay_lines = []
    for method in METHODS:
        delay = metrics["delay_and_censoring"][method]
        observed = delay["observed_delay_seconds"]
        if observed["count"]:
            observed_text = f"n={observed['count']}, median {observed['median_seconds']:.1f}s, mean {observed['mean_seconds']:.1f}s, range {observed['min_seconds']:.0f}–{observed['max_seconds']:.0f}s"
        else:
            observed_text = "n=0"
        delay_lines.append(
            f"| {method} | {delay['evidence_after_eligible_pair_count']} | {delay['valid_decision_observed_count']} ({observed_text}) | {delay['right_censored_after_sufficient_evidence_count']} | {delay['right_censored_before_sufficient_evidence_count']} | {delay['unknown_excluded_count']} |"
        )
    runtime_lines = []
    for method in METHODS:
        cost = metrics["compute_cost"][method]
        runtime_lines.append(
            f"| {method} | {cost['measured_rule_function_call_count']} | {cost['measured_rule_function_time_seconds']:.6f} | {cost['measured_rule_function_time_median_us']:.2f} |"
        )
    stratum_lines = []
    for method in METHODS:
        for stratum, values in metrics["per_stratum"][method].items():
            stratum_lines.append(
                f"| {method} | {stratum} | {values['world_count']} | {values['false_merge']['count']}/{values['false_merge']['denominator']} | {values['false_split']['count']}/{values['false_split']['denominator']} | {values['coverage']['count']}/{values['coverage']['denominator']} |"
            )
    return f"""# SYNTHETIC DEVELOPMENT comparison — {status}

## Run identity

- Source commit: `{run_meta['source_commit']}` on `{run_meta['branch']}`.
- Existing protocol status remains `REVIEW_DRAFT`; this single development run was explicitly authorized in the task handoff. It is a fixed-seed synthetic development comparison, not a formal or blind evaluation.
- Seed: `{run_meta['configuration']['seed']}`; worlds: {audit['world_count']}; allocation: {audit['stratum_counts']}; parameter searches: 0.
- Configuration SHA-256: `{run_meta['configuration_sha256']}`.
- Integrity preflight: **{audit['status']}** with {len(audit['errors'])} failures. Failure artifact: [`failures.json`](failures.json).
- Inputs, frozen per-cutoff outputs, scorer sidecars, per-world scores, runtimes and chart data are stored alongside this report and bound by [`run_manifest.json`](run_manifest.json).

## Fixed comparison results

Pooled pair counts are descriptive across 12 worlds (72 unique pair rows per method); the protocol's primary summaries also show equal-world macro rates. A pair, cutoff, method arm or repeated rule call is not an independent world.

| Rule | False merge (DIFFERENT class) | False split (SAME class) | Coverage (all six pairs, UNKNOWN included) | UNKNOWN actions | Valid decision observed / evidence-eligible pairs | Rule calls (repeated prefix calls) |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

UNKNOWN counts are not part of false-merge, false-split or evidence-after delay denominators. The UNKNOWN labels are synthetic masks over known relations, not an ambiguity-detection task.

### Delay and censoring

| Rule | Evidence-after eligible | Correct decision observed and delay | Right-censored after sufficient evidence | Right-censored before sufficient evidence | UNKNOWN excluded |
|---|---:|---|---:|---:|---:|
{chr(10).join(delay_lines)}

Observed delay is conditional on a registered sufficient-evidence time and a correct decision at or after that time. Censored rows remain reported; no survival model or SLO was applied. Shared-root SAME pairs are right-censored before sufficient evidence and are excluded from the evidence-after denominator.

### Calls and local runtime

| Rule | Function calls | Sum of instrumented rule-call time (seconds) | Median measured rule-call time (µs) |
|---|---:|---:|---:|
{chr(10).join(runtime_lines)}

Maximum rule-call budget was {metrics['compute_cost'][METHODS[0]]['max_invocation_budget_per_arm']} per arm. Runtime is local descriptive wall time with a lightweight timing wrapper; it is not a benchmark or performance claim. Repeated prefix calls are distinct computation, while the fixed unique-pair denominator remains 72 per method.

### Per-stratum descriptive counts

| Rule | Stratum | Worlds | False merges / DIFFERENT | False splits / SAME | Non-abstaining / fixed pairs |
|---|---|---:|---:|---:|---:|
{chr(10).join(stratum_lines)}

## Figures

![Final confusion counts and coverage](charts/final_confusion_and_coverage.png)

![Registered world 0 SAME-pair timeline](charts/registered_world_000_same_pair_timeline.png)

The timeline uses registered world index 0 selected before outcome inspection; its vertical line marks that pair's scorer-provided sufficient-evidence time.

## Integrity and interpretation limits

- Two rules used the same fixed `InferenceConfig`, one frozen prefix per registered cutoff, and the same shared candidate set and prefix hash at each cutoff. The six-pair scoring universe was fixed from four abnormal observation IDs before method outputs; non-candidates score as implicit `ABSTAIN`.
- The preflight checked the exact development world ID/stratum/schedule registry, 12-world budget, three worlds per stratum, pair labels and six-pair universe, available times, lineage roots, cross-world ID/root/asset disjointness, exact replay behavior, and recovery markers. The run manifest hashes the frozen code, protocol and all saved artifacts.
- Both rules are deterministic synthetic functions over observable records. Current visible asset and recovery cues often explain the synthetic truth; boundary-adjacent difficulty is not systematically covered. Results describe these scripted worlds only.
- No heldout worlds, tuning, threshold changes, sample expansion, real field data, Mac repair, external notification, or old 1,464-check trial was run. Alert escalation remains `NOT_EVALUATED` because neither rule emits alert actions.
- No statistical test or method-superiority claim is made. Identical outputs, errors and censored observations are reported as generated.

## Execution totals

- Generation batch: {runtime['generation_wall_seconds']:.6f}s.
- Candidate/lineage preflight: {runtime['preflight_wall_seconds']:.6f}s.
- Combined rule execution across 12 worlds: {runtime['combined_method_wall_seconds']:.6f}s.
- Scoring: {runtime['scoring_wall_seconds']:.6f}s; aggregation: {runtime['aggregation_wall_seconds']:.6f}s.
- Plot generation: {runtime['chart_wall_seconds']:.6f}s.
- Status: `{status}`; failure count: {len(FAILURES)}.

No subsequent run was started. Any next step requires a separate decision.
"""


def list_artifact_hashes() -> list[dict]:
    rows = []
    for path in sorted(RUN_DIR.rglob("*")):
        if not path.is_file() or path.name == "run_manifest.json":
            continue
        rel = path.relative_to(RUN_DIR).as_posix()
        raw = path.read_bytes()
        rows.append({"path": rel, "bytes": len(raw), "sha256": sha256_bytes(raw)})
    return rows


def main() -> int:
    started_ns = time.perf_counter_ns()
    started_at = utc_now()
    stage = "freeze_check"
    status = "RUNNING"
    plan = None
    worlds = []
    all_steps: dict[str, tuple] = {}
    scores: list[dict] = []
    aggregate = None
    metrics = None
    audit = {"status": "NOT_RUN", "errors": [], "worlds": []}
    charts = {}
    runtime: dict[str, float] = {}
    rule_call_ns = {method: [] for method in METHODS}
    rule_call_counts = {method: 0 for method in METHODS}

    try:
        if (RUN_DIR / "run_manifest.json").exists():
            raise RuntimeError("this fixed-seed run has already been attempted; refusing to overwrite it")
        git_state = current_git_state()
        if git_state["commit"] != EXPECTED_COMMIT:
            raise RuntimeError(f"source commit mismatch: {git_state['commit']}")
        if git_state["tracked_worktree_clean"] is not True or git_state["index_clean"] is not True:
            raise RuntimeError("tracked source worktree/index must be clean before the run")
        if git_state["only_this_run_artifact_is_untracked"] is not True:
            raise RuntimeError(f"unexpected repository changes before the run: {git_state['unexpected_status_rows']}")
        if git_state["branch"] != "task/research-three-v2-alignment-20261011":
            raise RuntimeError(f"unexpected branch: {git_state['branch']}")

        plan = evaluation.get_split_plan("development")
        if (plan.seed, plan.world_budget, plan.worlds_per_stratum, plan.search_configs_per_method) != (2026101101, 12, 3, 0):
            raise RuntimeError(f"registered development plan changed: {plan}")
        config = association.InferenceConfig()
        protocol_text = (REPO_ROOT / SOURCE_FILES[2]).read_text()
        if "状态：** `REVIEW_DRAFT`" not in protocol_text:
            raise RuntimeError("protocol status changed from REVIEW_DRAFT")
        source_hashes = {
            path: file_sha256(REPO_ROOT / path) for path in SOURCE_FILES
        }
        configuration = {
            "split_name": "development",
            "seed": plan.seed,
            "world_budget": plan.world_budget,
            "worlds_per_stratum": plan.worlds_per_stratum,
            "search_configs_per_method": plan.search_configs_per_method,
            "methods": list(METHODS),
            "inference_config": asdict(config),
            "evaluation_cutoff_seconds": evaluation._EVALUATION_CUTOFF_SECONDS,
            "max_cutoffs_per_world": evaluation._MAX_CUTOFFS_PER_WORLD,
            "max_unique_pairs_per_world": evaluation._MAX_PAIR_COUNT_PER_WORLD,
            "candidate_universe": "ALL_SIX_UNORDERED_PAIRS_AMONG_FOUR_ABNORMAL_OBSERVATION_IDS",
            "run_scope": "ONE_USER_AUTHORIZED_SYNTHETIC_DEVELOPMENT_COMPARISON",
            "heldout_run": False,
            "tuning": False,
        }
        configuration_sha256 = sha256_bytes(canonical_json(configuration))
        run_meta = {
            "source_commit": git_state["commit"],
            "branch": git_state["branch"],
            "git_state_before_run": git_state,
            "source_file_sha256": source_hashes,
            "protocol_status": "REVIEW_DRAFT",
            "user_authorization": "ONE_FINITE_DEVELOPMENT_SYNTHETIC_COMPARISON; NO_HELDOUT_OR_TUNING",
            "configuration": configuration,
            "configuration_sha256": configuration_sha256,
            "started_at_utc": started_at,
            "python_version": sys.version,
            "platform": platform.platform(),
            "timer": "time.perf_counter_ns; local process wall time",
        }
        write_json(RUN_DIR / "run_configuration.json", run_meta)
        log(f"FROZEN_SOURCE_OK commit={git_state['commit']} branch={git_state['branch']}")
        log(f"REGISTERED_PLAN_OK seed={plan.seed} worlds={plan.world_budget} strata_each={plan.worlds_per_stratum} search=0")

        stage = "generate_development"
        generation_started = time.perf_counter_ns()
        worlds = evaluation.generate_protocol_split("development")
        runtime["generation_wall_seconds"] = (time.perf_counter_ns() - generation_started) / 1_000_000_000
        log(f"GENERATED_DEVELOPMENT worlds={len(worlds)} seconds={runtime['generation_wall_seconds']:.6f}")

        stage = "preflight"
        preflight_started = time.perf_counter_ns()
        audit, audit_errors = audit_worlds(worlds, plan)
        runtime["preflight_wall_seconds"] = (time.perf_counter_ns() - preflight_started) / 1_000_000_000
        write_json(RUN_DIR / "preflight_audit.json", audit)
        if audit_errors:
            FAILURES.append({"stage": "preflight", "type": "IntegrityError", "message": f"{len(audit_errors)} preflight checks failed", "traceback": ""})
            raise RuntimeError(f"development integrity preflight failed: {audit_errors}")
        log(f"PREFLIGHT_PASS worlds={audit['world_count']} strata={audit['stratum_counts']} cutoff_max={max(len(row['registered_cutoffs']) for row in audit['worlds'])}")

        stage = "method_execution"
        combined_method_ns = 0
        method_world_times = []
        for world in worlds:
            world_id = world.scorer_only.world_group_id
            before_counts = {method: len(rule_call_ns[method]) for method in METHODS}
            method_started = time.perf_counter_ns()
            with patch.object(
                association,
                "time_asset_rule",
                timed_method("TIME_ASSET_RULE", association.time_asset_rule, rule_call_ns),
            ), patch.object(
                association,
                "multi_evidence_rule",
                timed_method("MULTI_EVIDENCE_RULE", association.multi_evidence_rule, rule_call_ns),
            ):
                steps = evaluation.run_two_methods(world.observable)
            method_elapsed = time.perf_counter_ns() - method_started
            combined_method_ns += method_elapsed
            expected_world = next(row for row in audit["worlds"] if row["world_group_id"] == world_id)
            expected_trace = {row["cutoff"]: row for row in expected_world["cutoff_trace"]}
            by_cutoff = {}
            for step in steps:
                by_cutoff.setdefault(step.cutoff, []).append(step)
            if tuple(by_cutoff) != tuple(world.scorer_only.registered_cutoffs):
                raise ValueError(f"cutoff order changed in actual method run for {world_id}")
            for cutoff, cutoff_steps in by_cutoff.items():
                if len(cutoff_steps) != 2 or {step.method for step in cutoff_steps} != set(METHODS):
                    raise ValueError(f"method arm count mismatch at {world_id} {cutoff}")
                if cutoff_steps[0].input_prefix_sha256 != cutoff_steps[1].input_prefix_sha256:
                    raise ValueError(f"input prefix mismatch between arms at {world_id} {cutoff}")
                if cutoff_steps[0].candidate_pairs != cutoff_steps[1].candidate_pairs:
                    raise ValueError(f"candidate set mismatch between arms at {world_id} {cutoff}")
                expected_cutoff = expected_trace[cutoff]
                if cutoff_steps[0].input_prefix_sha256 != expected_cutoff["input_prefix_sha256"]:
                    raise ValueError(f"prefix differs from preflight input at {world_id} {cutoff}")
                actual_candidates = [pair_json(pair) for pair in cutoff_steps[0].candidate_pairs]
                if actual_candidates != expected_cutoff["candidate_pairs"]:
                    raise ValueError(f"candidate set differs from preflight at {world_id} {cutoff}")
            trace_rows, _ = save_step_outputs(world_id, steps)
            all_steps[world_id] = tuple(steps)
            expected_call_count = {
                method: sum(len(step.candidate_pairs) for step in steps if step.method == method)
                for method in METHODS
            }
            world_call_counts = {
                method: len(rule_call_ns[method]) - before_counts[method]
                for method in METHODS
            }
            if world_call_counts != expected_call_count:
                raise ValueError(f"instrumented rule call count mismatch for {world_id}: {world_call_counts} != {expected_call_count}")
            for method in METHODS:
                rule_call_counts[method] += world_call_counts[method]
            method_world_times.append({
                "world_group_id": world_id,
                "stratum": world.scorer_only.stratum.value,
                "registered_cutoff_count": len(world.observable.cutoffs),
                "combined_method_wall_ns": method_elapsed,
                "method_function_call_counts": world_call_counts,
                "output_step_count": len(steps),
                "saved_output_trace_path": f"outputs/{world_id}/trace.json",
            })

        runtime["combined_method_wall_seconds"] = combined_method_ns / 1_000_000_000
        runtime["per_world_method_execution"] = method_world_times
        runtime["rule_function_wall_ns"] = {
            method: sum(rule_call_ns[method]) for method in METHODS
        }
        runtime["rule_function_calls"] = dict(rule_call_counts)
        log(f"METHODS_FROZEN_AND_SAVED outputs={sum(len(steps) for steps in all_steps.values())} seconds={runtime['combined_method_wall_seconds']:.6f}")

        stage = "scoring"
        scoring_started = time.perf_counter_ns()
        for world in worlds:
            world_id = world.scorer_only.world_group_id
            # Frozen canonical output files and their hashes exist before this scorer call.
            score = evaluation.score_world(all_steps[world_id], world.scorer_only)
            if tuple(score["registered_cutoffs"]) != world.observable.cutoffs:
                raise ValueError(f"score registered trace mismatch for {world_id}")
            if tuple(score["scored_cutoffs"]) != world.observable.cutoffs:
                raise ValueError(f"score executed trace mismatch for {world_id}")
            scores.append(score)
            write_json(RUN_DIR / "scores" / f"{world_id}.json", score)
        runtime["scoring_wall_seconds"] = (time.perf_counter_ns() - scoring_started) / 1_000_000_000
        log(f"SCORING_PASS worlds={len(scores)} seconds={runtime['scoring_wall_seconds']:.6f}")

        stage = "aggregation"
        aggregation_started = time.perf_counter_ns()
        aggregate = evaluation.aggregate_world_scores(scores)
        runtime["aggregation_wall_seconds"] = (time.perf_counter_ns() - aggregation_started) / 1_000_000_000
        write_json(RUN_DIR / "aggregate_world_scores.json", aggregate)
        metrics = build_metrics(worlds, scores, all_steps, aggregate, rule_call_ns, rule_call_counts)
        write_json(RUN_DIR / "metrics.json", metrics)
        log(f"AGGREGATION_PASS independent_world_count={aggregate['independent_world_count']} seconds={runtime['aggregation_wall_seconds']:.6f}")

        stage = "charts"
        chart_started = time.perf_counter_ns()
        charts = make_charts(worlds, all_steps, scores, metrics)
        runtime["chart_wall_seconds"] = (time.perf_counter_ns() - chart_started) / 1_000_000_000
        log(f"CHARTS_WRITTEN count=2 seconds={runtime['chart_wall_seconds']:.6f}")

        runtime["end_to_end_compute_seconds"] = sum(
            runtime[key] for key in (
                "generation_wall_seconds", "preflight_wall_seconds",
                "combined_method_wall_seconds", "scoring_wall_seconds",
                "aggregation_wall_seconds", "chart_wall_seconds",
            )
        )
        runtime["artifact_write_seconds"] = ARTIFACT_WRITE_NS / 1_000_000_000
        status = "PASS_SYNTHETIC_DEVELOPMENT_ONLY"
        run_meta["finished_at_utc"] = utc_now()
        run_meta["status"] = status
        run_meta["runtime"] = runtime
        run_meta["charts"] = charts
        run_meta["failure_count"] = 0
        write_json(RUN_DIR / "runtime.json", runtime)
        write_json(RUN_DIR / "run_summary.json", {
            "status": status,
            "run_meta": run_meta,
            "preflight_status": audit["status"],
            "world_count": len(worlds),
            "aggregate_independent_world_count": aggregate["independent_world_count"],
            "metrics": metrics,
            "charts": charts,
            "failure_count": len(FAILURES),
        })
        report = make_report(run_meta, audit, metrics, runtime, charts, status)
        write_bytes(RUN_DIR / "REPORT.md", report.encode("utf-8"))
        log("RUN_COMPLETE status=PASS_SYNTHETIC_DEVELOPMENT_ONLY")
    except Exception as exc:
        if not any(row.get("message") == str(exc) for row in FAILURES):
            FAILURES.append({
                "stage": stage,
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            })
        status = "INVALID_RUN" if stage in {"preflight", "method_execution", "scoring", "aggregation"} else "RUNNER_ERROR"
        log(f"RUN_FAILED stage={stage} type={type(exc).__name__} message={exc}")
    finally:
        finished_ns = time.perf_counter_ns()
        runtime["script_elapsed_seconds_before_final_manifest"] = (finished_ns - started_ns) / 1_000_000_000
        runtime["artifact_write_seconds_before_final_manifest"] = ARTIFACT_WRITE_NS / 1_000_000_000
        write_json(RUN_DIR / "failures.json", FAILURES)
        write_json(RUN_DIR / "runtime.json", runtime)
        write_bytes(RUN_DIR / "run.log.txt", ("\n".join(LOG_LINES) + "\n").encode("utf-8"))
        if status != "PASS_SYNTHETIC_DEVELOPMENT_ONLY":
            write_json(RUN_DIR / "run_summary.json", {
                "status": status,
                "stage": stage,
                "preflight_status": audit.get("status"),
                "world_count_generated": len(worlds),
                "world_scores_written": len(scores),
                "failure_count": len(FAILURES),
                "runtime": runtime,
            })
        manifest = {
            "artifact_version": "finite-synthetic-development-comparison-v1",
            "classification": "SYNTHETIC_DEVELOPMENT_ONLY",
            "status": status,
            "source_commit": EXPECTED_COMMIT,
            "branch_at_run": "task/research-three-v2-alignment-20261011",
            "protocol_status": "REVIEW_DRAFT",
            "configuration_sha256": (
                run_meta["configuration_sha256"] if "run_meta" in locals() else None
            ),
            "files": list_artifact_hashes(),
            "manifest_excludes_itself_from_file_hashes": True,
            "mac_persistence": "PREPARED_IN_REPOSITORY; NOT_STORED_ON_MAC; MAC_OFFLINE",
            "failure_count": len(FAILURES),
        }
        write_json(RUN_DIR / "run_manifest.json", manifest)
        log(f"MANIFEST_WRITTEN files={len(manifest['files'])} status={status}")
        # Refresh log and manifest once after recording final status.
        write_bytes(RUN_DIR / "run.log.txt", ("\n".join(LOG_LINES) + "\n").encode("utf-8"))
        manifest["files"] = list_artifact_hashes()
        write_json(RUN_DIR / "run_manifest.json", manifest)

    return 0 if status == "PASS_SYNTHETIC_DEVELOPMENT_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
