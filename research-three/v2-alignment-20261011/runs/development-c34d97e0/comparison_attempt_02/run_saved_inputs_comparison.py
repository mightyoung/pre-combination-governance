#!/usr/bin/env python3
"""Score the exact development inputs preserved by the preflight-only attempt."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback
from unittest.mock import patch


RUN_DIR = Path(__file__).resolve().parent
INPUT_RUN_DIR = RUN_DIR.parent
REPO_ROOT = RUN_DIR.parents[4]
EXPECTED_COMMIT = "c34d97e0101554a362e927ed9e3ff239cedc319e"
BASE_SCRIPT = INPUT_RUN_DIR / "run_development_comparison.py"
sys.dont_write_bytecode = True


def load_base_runner():
    spec = importlib.util.spec_from_file_location("frozen_development_runner", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the immutable preflight runner helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.RUN_DIR = RUN_DIR
    module.LOG_LINES = []
    module.FAILURES = []
    module.ARTIFACT_WRITE_NS = 0
    return module


base = load_base_runner()
evaluation = base.evaluation
association = base.association
METHODS = base.METHODS


def status_snapshot() -> dict:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO_ROOT, text=True).strip()
    rows = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=REPO_ROOT, text=True
    ).splitlines()
    allowed_prefix = INPUT_RUN_DIR.relative_to(REPO_ROOT).as_posix() + "/"
    unexpected = [row for row in rows if not row[3:].strip().startswith(allowed_prefix)]
    return {
        "commit": commit,
        "branch": branch,
        "tracked_clean": subprocess.run(["git", "diff", "--quiet"], cwd=REPO_ROOT, check=False).returncode == 0,
        "index_clean": subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT, check=False).returncode == 0,
        "all_untracked_files_under_run_artifacts": not unexpected,
        "unexpected_status_rows": unexpected,
    }


def list_to_tuple(value):
    if isinstance(value, list):
        return tuple(list_to_tuple(item) for item in value)
    return value


def load_worlds_from_preserved_files() -> tuple[list, dict, dict]:
    input_files = sorted((INPUT_RUN_DIR / "inputs").glob("WG-*.json"))
    sidecar_files = sorted((INPUT_RUN_DIR / "scorer_sidecars").glob("WG-*.json"))
    if len(input_files) != 12 or len(sidecar_files) != 12:
        raise ValueError(f"expected 12 preserved inputs and sidecars; found {len(input_files)} and {len(sidecar_files)}")
    sidecars_by_id = {path.stem: path for path in sidecar_files}
    worlds = []
    original_hashes = {}
    for input_path in input_files:
        world_id = input_path.stem
        if world_id not in sidecars_by_id:
            raise ValueError(f"missing preserved scorer sidecar for {world_id}")
        input_bytes = input_path.read_bytes()
        sidecar_path = sidecars_by_id[world_id]
        sidecar_bytes = sidecar_path.read_bytes()
        input_doc = json.loads(input_bytes.decode("utf-8"))
        sidecar_doc = json.loads(sidecar_bytes.decode("utf-8"))
        records = tuple(
            association.ObservationRecord(
                observation_id=row["observation_id"],
                id_actual_available_at=row["id_actual_available_at"],
                id_earliest_known_at=row["id_earliest_known_at"],
                received_at=row["received_at"],
                fields=tuple(
                    association.KnownField(
                        name=item["name"],
                        value=list_to_tuple(item["value"]),
                        actual_available_at=item["actual_available_at"],
                        earliest_known_at=item["earliest_known_at"],
                    )
                    for item in row["fields"]
                ),
            )
            for row in input_doc["records"]
        )
        observable = evaluation.ObservableTrajectory(
            records=records,
            cutoffs=tuple(input_doc["cutoffs"]),
        )
        pair_truths = tuple(
            evaluation.PairTruth(
                pair=association.CandidatePair(
                    row["pair"]["left_observation_id"],
                    row["pair"]["right_observation_id"],
                ),
                label=row["label"],
                first_sufficient_evidence_at=row["first_sufficient_evidence_at"],
            )
            for row in sidecar_doc["pair_truths"]
        )
        opportunities = tuple(
            evaluation.AlertEscalationOpportunity(**row)
            for row in sidecar_doc["escalation_opportunities"]
        )
        sidecar = evaluation.ScorerSidecar(
            world_group_id=sidecar_doc["world_group_id"],
            stratum=sidecar_doc["stratum"],
            pair_truths=pair_truths,
            evaluation_cutoff=sidecar_doc["evaluation_cutoff"],
            registered_cutoffs=tuple(sidecar_doc["registered_cutoffs"]),
            escalation_opportunities=opportunities,
            split_name=sidecar_doc["split_name"],
        )
        world = evaluation.GeneratedWorld(observable=observable, scorer_only=sidecar)
        if sidecar.world_group_id != world_id:
            raise ValueError(f"file stem and sidecar world ID disagree for {world_id}")
        if evaluation.serialize_observable_trajectory(observable) != input_bytes:
            raise ValueError(f"rehydrated input serialization changed for {world_id}")
        if base.json_ready(base.sidecar_json(sidecar)) != sidecar_doc:
            raise ValueError(f"rehydrated scorer sidecar changed for {world_id}")
        original_hashes[world_id] = {
            "input_sha256": base.sha256_bytes(input_bytes),
            "input_bytes": len(input_bytes),
            "sidecar_sha256": base.sha256_bytes(sidecar_bytes),
            "sidecar_bytes": len(sidecar_bytes),
        }
        worlds.append(world)
    return worlds, original_hashes, sidecars_by_id


def audit_preserved_worlds(worlds, previous_audit, expected_registration, plan):
    errors = []

    def require(condition, check, details=None):
        if not condition:
            errors.append({"check": check, "details": base.json_ready(details)})

    expected_counts = {stratum.value: plan.worlds_per_stratum for stratum in evaluation.SyntheticStratum}
    observed_counts = Counter(world.scorer_only.stratum.value for world in worlds)
    require(len(worlds) == 12, "development_world_budget", len(worlds))
    require({key: observed_counts.get(key, 0) for key in expected_counts} == expected_counts, "balanced_registered_strata", dict(observed_counts))
    observed_ids = {world.scorer_only.world_group_id for world in worlds}
    require(observed_ids == set(expected_registration), "exact_registered_world_id_set", {
        "missing": sorted(set(expected_registration) - observed_ids),
        "extra": sorted(observed_ids - set(expected_registration)),
    })

    previous_worlds = {row["world_group_id"]: row for row in previous_audit["worlds"]}
    global_obs: set[str] = set()
    global_roots: set[str] = set()
    global_assets: set[str] = set()
    audits = []
    config = association.InferenceConfig()
    for world in worlds:
        sidecar = world.scorer_only
        trajectory = world.observable
        prior = previous_worlds.get(sidecar.world_group_id)
        registered = expected_registration.get(sidecar.world_group_id)
        require(prior is not None, "world_was_saved_by_first_attempt", sidecar.world_group_id)
        require(registered is not None, "world_is_registered", sidecar.world_group_id)
        if registered is not None:
            require(sidecar.stratum is registered["stratum"], "registered_world_stratum", sidecar.world_group_id)
            require(trajectory.cutoffs == registered["cutoffs"], "registered_expected_schedule", sidecar.world_group_id)
        require(sidecar.split_name == "development", "development_only", sidecar.split_name)
        require(sidecar.registered_cutoffs == trajectory.cutoffs, "sidecar_matches_saved_input_schedule", sidecar.world_group_id)
        require(sidecar.evaluation_cutoff == evaluation._stamp(120), "registered_terminal_cutoff", sidecar.evaluation_cutoff)
        require(len(trajectory.cutoffs) <= evaluation._MAX_CUTOFFS_PER_WORLD, "cutoff_budget", len(trajectory.cutoffs))

        observations = {record.observation_id for record in trajectory.records}
        abnormal_ids = {
            record.observation_id for record in trajectory.records
            if base.field_value(record, "risk_flag") in {"EXPOSURE", "EXPOSURE_HIGH"}
        }
        expected_pairs = {
            association.CandidatePair(left, right)
            for left, right in __import__("itertools").combinations(sorted(abnormal_ids), 2)
        }
        pairs = {row.pair for row in sidecar.pair_truths}
        label_counts = Counter(row.label.value for row in sidecar.pair_truths)
        normalized_label_counts = {
            label.value: label_counts.get(label.value, 0)
            for label in evaluation.PairTruthLabel
        }
        expected_label_counts = (
            {"SAME": 2, "DIFFERENT": 3, "UNKNOWN": 1}
            if sidecar.stratum is evaluation.SyntheticStratum.DEPENDENT_REPLAY_UNKNOWN
            else {"SAME": 2, "DIFFERENT": 4, "UNKNOWN": 0}
        )
        require(len(abnormal_ids) == 4, "four_abnormal_observation_ids", sorted(abnormal_ids))
        require(len(sidecar.pair_truths) == 6 and pairs == expected_pairs, "six_pair_fixed_universe", len(pairs))
        require(normalized_label_counts == expected_label_counts, "registered_label_allocation", {
            "observed": normalized_label_counts, "expected": expected_label_counts,
        })

        root_by_observation: dict[str, set[str]] = {}
        root_ids: set[str] = set()
        asset_ids: set[str] = set()
        late_fact_count = 0
        for record in trajectory.records:
            lineage = base.field_value(record, "acquisition_lineage")
            if isinstance(lineage, tuple) and lineage:
                root = str(lineage[0])
                root_ids.add(root)
                root_by_observation.setdefault(record.observation_id, set()).add(root)
            asset = base.field_value(record, "asset_id")
            if isinstance(asset, str):
                asset_ids.add(asset)
            for fact in record.fields:
                if fact.earliest_known_at > fact.actual_available_at:
                    late_fact_count += 1
                require(fact.earliest_known_at >= fact.actual_available_at, "field_availability_order", {
                    "observation_id": record.observation_id, "field": fact.name,
                })
        require(late_fact_count >= 1, "late_fact_present", late_fact_count)
        expected_root_count = {
            evaluation.SyntheticStratum.INDEPENDENT_SAME_EVENT: 4,
            evaluation.SyntheticStratum.ADJACENT_DISTINCT_ASSETS: 4,
            evaluation.SyntheticStratum.RECOVERY_THEN_NEW_EVENT: 5,
            evaluation.SyntheticStratum.DEPENDENT_REPLAY_UNKNOWN: 3,
        }[sidecar.stratum]
        require(len(root_ids) == expected_root_count, "registered_acquisition_root_count", {
            "stratum": sidecar.stratum.value,
            "observed": len(root_ids),
            "expected": expected_root_count,
        })
        require(abnormal_ids.issubset(root_by_observation), "all_abnormal_observations_have_lineage", sorted(abnormal_ids - set(root_by_observation)))
        for truth in sidecar.pair_truths:
            roots = root_by_observation.get(truth.pair.left_observation_id, set()) | root_by_observation.get(truth.pair.right_observation_id, set())
            if truth.label is evaluation.PairTruthLabel.SAME:
                require((truth.first_sufficient_evidence_at is not None) == (len(roots) >= 2), "same_sufficiency_matches_lineage", {
                    "pair": base.pair_json(truth.pair), "root_count": len(roots),
                })
            elif truth.label is evaluation.PairTruthLabel.DIFFERENT:
                require(truth.first_sufficient_evidence_at is not None, "different_pair_has_sufficiency_time", base.pair_json(truth.pair))
            else:
                require(truth.first_sufficient_evidence_at is None, "unknown_pair_has_no_sufficiency_time", base.pair_json(truth.pair))

        signature_counts = Counter(base.record_signature(record) for record in trajectory.records)
        replay_count = sum(count - 1 for count in signature_counts.values() if count > 1)
        expected_replay_count = 1 if sidecar.stratum is evaluation.SyntheticStratum.DEPENDENT_REPLAY_UNKNOWN else 0
        require(replay_count == expected_replay_count, "exact_replay_count", replay_count)
        recovery_count = sum(base.field_value(record, "risk_flag") == "RECOVERY" for record in trajectory.records)
        expected_recovery_count = 1 if sidecar.stratum is evaluation.SyntheticStratum.RECOVERY_THEN_NEW_EVENT else 0
        require(recovery_count == expected_recovery_count, "recovery_marker_count", recovery_count)

        require(not global_obs.intersection(observations), "world_observation_ids_disjoint", sorted(global_obs.intersection(observations)))
        require(not global_roots.intersection(root_ids), "world_lineage_roots_disjoint", sorted(global_roots.intersection(root_ids)))
        require(not global_assets.intersection(asset_ids), "world_assets_disjoint", sorted(global_assets.intersection(asset_ids)))
        global_obs.update(observations)
        global_roots.update(root_ids)
        global_assets.update(asset_ids)

        candidate_trace = []
        previous_candidates = set()
        for cutoff in trajectory.cutoffs:
            prefix = association.freeze_observable_prefix(trajectory.records, as_of=cutoff)
            candidates = association.build_candidate_universe(prefix, config=config)
            candidate_set = set(candidates)
            require(candidate_set.issubset(expected_pairs), "cutoff_candidates_in_fixed_universe", cutoff)
            require(previous_candidates.issubset(candidate_set), "candidate_set_monotonic", cutoff)
            candidate_trace.append({
                "cutoff": cutoff,
                "input_prefix_sha256": evaluation._prefix_sha256(prefix),
                "candidate_pairs": [base.pair_json(pair) for pair in candidates],
                "candidate_pair_count": len(candidates),
            })
            previous_candidates = candidate_set
        if prior is not None:
            require(candidate_trace == prior["cutoff_trace"], "candidate_trace_reuses_first_attempt", sidecar.world_group_id)

        input_path = INPUT_RUN_DIR / "inputs" / f"{sidecar.world_group_id}.json"
        sidecar_path = INPUT_RUN_DIR / "scorer_sidecars" / f"{sidecar.world_group_id}.json"
        input_bytes = evaluation.serialize_observable_trajectory(trajectory)
        sidecar_bytes = json.dumps(
            base.json_ready(base.sidecar_json(sidecar)), ensure_ascii=False,
            sort_keys=True, indent=2, allow_nan=False,
        ).encode("utf-8") + b"\n"
        input_doc = json.loads(input_bytes.decode("utf-8"))
        forbidden = {
            "world_group_id", "stratum", "split_name", "truth", "truth_label",
            "first_sufficient_evidence_at", "evaluation_cutoff", "alert_escalation_opportunities",
        }
        leaked = sorted(forbidden.intersection(base.recursive_keys(input_doc)))
        require(not leaked, "saved_method_input_excludes_scorer_fields", leaked)
        require(input_bytes == input_path.read_bytes(), "input_bytes_unchanged_after_rehydration", sidecar.world_group_id)
        require(sidecar_bytes == sidecar_path.read_bytes(), "sidecar_bytes_unchanged_after_rehydration", sidecar.world_group_id)

        # Copy the original bytes exactly into the self-contained comparison package.
        base.write_bytes(RUN_DIR / "inputs" / input_path.name, input_path.read_bytes())
        base.write_bytes(RUN_DIR / "scorer_sidecars" / sidecar_path.name, sidecar_path.read_bytes())
        audits.append({
            "world_group_id": sidecar.world_group_id,
            "world_index": None if registered is None else registered["world_index"],
            "stratum": sidecar.stratum.value,
            "unique_abnormal_observation_ids": sorted(abnormal_ids),
            "fixed_pair_count": len(sidecar.pair_truths),
            "pair_label_counts": normalized_label_counts,
            "observation_record_count": len(trajectory.records),
            "unique_observation_id_count": len(observations),
            "unique_lineage_root_count": len(root_ids),
            "unique_asset_id_count": len(asset_ids),
            "late_fact_count": late_fact_count,
            "exact_replay_count": replay_count,
            "recovery_marker_count": recovery_count,
            "evaluation_cutoff": sidecar.evaluation_cutoff,
            "registered_cutoffs": list(sidecar.registered_cutoffs),
            "cutoff_trace": candidate_trace,
            "input_sha256": base.file_sha256(RUN_DIR / "inputs" / input_path.name),
            "sidecar_sha256": base.file_sha256(RUN_DIR / "scorer_sidecars" / sidecar_path.name),
        })

    audit = {
        "status": "PASS" if not errors else "INVALID_RUN",
        "split_name": "development",
        "world_count": len(worlds),
        "stratum_counts": {key: observed_counts.get(key, 0) for key in expected_counts},
        "expected_stratum_counts": expected_counts,
        "registered_world_count": len(expected_registration),
        "unique_observation_ids_across_worlds": len(global_obs),
        "unique_lineage_roots_across_worlds": len(global_roots),
        "unique_assets_across_worlds": len(global_assets),
        "reused_saved_inputs_from_attempt": "../run_manifest.json",
        "generator_invoked_in_this_comparison_attempt": False,
        "worlds": audits,
        "errors": errors,
    }
    return audit, errors


def main() -> int:
    if (RUN_DIR / "run_manifest.json").exists():
        print("refusing to overwrite comparison attempt 2", flush=True)
        return 1
    started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    started_ns = time.perf_counter_ns()
    stage = "freeze_check"
    status = "RUNNING"
    failures = []
    worlds = []
    all_steps = {}
    scores = []
    aggregate = None
    metrics = None
    runtime = {}
    charts = {}
    run_meta = None
    try:
        source_state = status_snapshot()
        if source_state["commit"] != EXPECTED_COMMIT or source_state["branch"] != "task/research-three-v2-alignment-20261011":
            raise RuntimeError(f"frozen source mismatch: {source_state}")
        if not source_state["tracked_clean"] or not source_state["index_clean"] or not source_state["all_untracked_files_under_run_artifacts"]:
            raise RuntimeError(f"tracked source changed or unrelated files exist: {source_state}")

        prior_manifest_path = INPUT_RUN_DIR / "run_manifest.json"
        prior_manifest_bytes = prior_manifest_path.read_bytes()
        prior_manifest = json.loads(prior_manifest_bytes.decode("utf-8"))
        if prior_manifest["status"] != "INVALID_RUN" or prior_manifest["source_commit"] != EXPECTED_COMMIT:
            raise RuntimeError("first attempt is not the preserved preflight-only c34d97e attempt")
        prior_manifest_errors = []
        for row in prior_manifest["files"]:
            path = INPUT_RUN_DIR / row["path"]
            raw = path.read_bytes()
            if len(raw) != row["bytes"] or base.sha256_bytes(raw) != row["sha256"]:
                prior_manifest_errors.append(row["path"])
        if prior_manifest_errors:
            raise RuntimeError(f"preserved attempt-1 files fail hash verification: {prior_manifest_errors}")
        prior_failures = json.loads((INPUT_RUN_DIR / "failures.json").read_text())
        prior_audit = json.loads((INPUT_RUN_DIR / "preflight_audit.json").read_text())
        prior_summary = json.loads((INPUT_RUN_DIR / "run_summary.json").read_text())
        prior_configuration = json.loads((INPUT_RUN_DIR / "run_configuration.json").read_text())
        prior_errors = prior_audit["errors"]
        allowed_initial_error = "registered_label_allocation"
        if not prior_errors or any(row["check"] != allowed_initial_error for row in prior_errors):
            raise RuntimeError(f"attempt-1 had non-normalization preflight failures: {prior_errors}")

        for path, expected_hash in prior_configuration["source_file_sha256"].items():
            actual_hash = base.file_sha256(REPO_ROOT / path)
            if actual_hash != expected_hash:
                raise RuntimeError(f"frozen source file changed since attempt 1: {path}")
        if prior_configuration["configuration_sha256"] != prior_manifest["configuration_sha256"]:
            raise RuntimeError("attempt-1 configuration hash does not match its manifest")
        config_bytes = base.canonical_json(prior_configuration["configuration"])
        if base.sha256_bytes(config_bytes) != prior_configuration["configuration_sha256"]:
            raise RuntimeError("attempt-1 fixed configuration hash failed verification")

        plan = evaluation.get_split_plan("development")
        if (plan.seed, plan.world_budget, plan.worlds_per_stratum, plan.search_configs_per_method) != (2026101101, 12, 3, 0):
            raise RuntimeError(f"registered development plan changed: {plan}")
        expected_registration = {}
        for stratum_index, stratum in enumerate(tuple(evaluation.SyntheticStratum)):
            for world_index in range(stratum_index * plan.worlds_per_stratum, (stratum_index + 1) * plan.worlds_per_stratum):
                world_id = evaluation._world_group_id("development", plan.seed, world_index, stratum)
                registered_stratum, cutoffs = evaluation._registered_formal_world_schedules("development")[world_id]
                expected_registration[world_id] = {
                    "world_index": world_index,
                    "stratum": registered_stratum,
                    "cutoffs": cutoffs,
                }
        if len(expected_registration) != plan.world_budget:
            raise RuntimeError("fixed development world registry size mismatch")

        stage = "load_saved_inputs"
        load_started = time.perf_counter_ns()
        worlds, original_hashes, _ = load_worlds_from_preserved_files()
        runtime["saved_input_reload_wall_seconds"] = (time.perf_counter_ns() - load_started) / 1_000_000_000
        world_index_by_id = {world.scorer_only.world_group_id: index for index, world in enumerate(worlds)}
        if set(world_index_by_id) != set(expected_registration):
            raise RuntimeError("preserved input world IDs do not equal the fixed development registry")

        stage = "corrected_preflight"
        preflight_started = time.perf_counter_ns()
        audit, audit_errors = audit_preserved_worlds(
            worlds, prior_audit, expected_registration, plan
        )
        runtime["preflight_wall_seconds"] = (time.perf_counter_ns() - preflight_started) / 1_000_000_000
        base.write_json(RUN_DIR / "preflight_audit.json", audit)
        if audit_errors:
            raise RuntimeError(f"corrected preflight failed: {audit_errors}")

        config = association.InferenceConfig()
        configuration = prior_configuration["configuration"]
        run_meta = {
            "source_commit": EXPECTED_COMMIT,
            "branch": source_state["branch"],
            "source_file_sha256": prior_configuration["source_file_sha256"],
            "configuration": configuration,
            "configuration_sha256": prior_configuration["configuration_sha256"],
            "protocol_status": "REVIEW_DRAFT",
            "started_at_utc": started_at,
            "python_version": sys.version,
            "platform": base.platform.platform(),
            "timer": "time.perf_counter_ns; local process wall time",
            "generator_invoked": False,
            "saved_inputs_reused_from_attempt_01": True,
            "previous_attempt_status": "INVALID_RUN_PRE_METHOD_PREFLIGHT_ONLY",
            "previous_attempt_manifest_sha256": base.sha256_bytes(prior_manifest_bytes),
        }
        base.write_json(RUN_DIR / "run_configuration.json", run_meta)
        base.write_json(RUN_DIR / "run_configuration.json", run_meta)
        runtime["generation_wall_seconds"] = float(prior_summary["runtime"]["generation_wall_seconds"])
        runtime["first_attempt_preflight_wall_seconds"] = float(prior_summary["runtime"]["preflight_wall_seconds"])
        base.log(f"SAVED_INPUTS_REUSED worlds={len(worlds)} generator_invoked=false prior_manifest_sha={run_meta['previous_attempt_manifest_sha256']}")
        base.log(f"CORRECTED_PREFLIGHT_PASS strata={audit['stratum_counts']} candidate_traces_match_attempt_01=true")

        # Freeze both method outputs exactly once for each of the saved inputs.
        stage = "method_execution"
        rule_call_ns = {method: [] for method in METHODS}
        rule_call_counts = {method: 0 for method in METHODS}
        per_world_method_times = []
        combined_method_ns = 0
        prior_world_audits = {row["world_group_id"]: row for row in audit["worlds"]}
        for world in worlds:
            world_id = world.scorer_only.world_group_id
            expected_world = prior_world_audits[world_id]
            expected_trace = {row["cutoff"]: row for row in expected_world["cutoff_trace"]}
            before_counts = {method: len(rule_call_ns[method]) for method in METHODS}
            method_started = time.perf_counter_ns()
            with patch.object(
                association, "time_asset_rule",
                base.timed_method("TIME_ASSET_RULE", association.time_asset_rule, rule_call_ns),
            ), patch.object(
                association, "multi_evidence_rule",
                base.timed_method("MULTI_EVIDENCE_RULE", association.multi_evidence_rule, rule_call_ns),
            ):
                steps = evaluation.run_two_methods(world.observable)
            method_elapsed = time.perf_counter_ns() - method_started
            combined_method_ns += method_elapsed
            by_cutoff = {}
            for step in steps:
                by_cutoff.setdefault(step.cutoff, []).append(step)
            if tuple(by_cutoff) != world.observable.cutoffs:
                raise ValueError(f"method cutoff order differs from saved registration for {world_id}")
            for cutoff, cutoff_steps in by_cutoff.items():
                if len(cutoff_steps) != 2 or {step.method for step in cutoff_steps} != set(METHODS):
                    raise ValueError(f"two-method output count mismatch for {world_id} {cutoff}")
                if cutoff_steps[0].input_prefix_sha256 != cutoff_steps[1].input_prefix_sha256:
                    raise ValueError(f"method prefix hashes differ for {world_id} {cutoff}")
                if cutoff_steps[0].candidate_pairs != cutoff_steps[1].candidate_pairs:
                    raise ValueError(f"method candidate sets differ for {world_id} {cutoff}")
                expected_cutoff = expected_trace[cutoff]
                if cutoff_steps[0].input_prefix_sha256 != expected_cutoff["input_prefix_sha256"]:
                    raise ValueError(f"method prefix differs from preflight for {world_id} {cutoff}")
                if [base.pair_json(pair) for pair in cutoff_steps[0].candidate_pairs] != expected_cutoff["candidate_pairs"]:
                    raise ValueError(f"method candidates differ from preflight for {world_id} {cutoff}")
            base.save_step_outputs(world_id, steps)
            all_steps[world_id] = tuple(steps)
            expected_calls = {
                method: sum(len(step.candidate_pairs) for step in steps if step.method == method)
                for method in METHODS
            }
            actual_calls = {
                method: len(rule_call_ns[method]) - before_counts[method]
                for method in METHODS
            }
            if expected_calls != actual_calls:
                raise ValueError(f"instrumented call count mismatch for {world_id}: {actual_calls} != {expected_calls}")
            for method in METHODS:
                rule_call_counts[method] += actual_calls[method]
            per_world_method_times.append({
                "world_group_id": world_id,
                "stratum": world.scorer_only.stratum.value,
                "registered_cutoff_count": len(world.observable.cutoffs),
                "combined_method_wall_ns": method_elapsed,
                "method_function_call_counts": actual_calls,
                "output_step_count": len(steps),
                "saved_output_trace_path": f"outputs/{world_id}/trace.json",
            })
        runtime["combined_method_wall_seconds"] = combined_method_ns / 1_000_000_000
        runtime["per_world_method_execution"] = per_world_method_times
        runtime["rule_function_wall_ns"] = {method: sum(rule_call_ns[method]) for method in METHODS}
        runtime["rule_function_calls"] = rule_call_counts
        base.log(f"METHODS_FROZEN_AND_SAVED outputs={sum(len(steps) for steps in all_steps.values())}")

        # Only now pass frozen outputs and separate scorer sidecars to the scorer.
        stage = "scoring"
        scoring_started = time.perf_counter_ns()
        for world in worlds:
            world_id = world.scorer_only.world_group_id
            score = evaluation.score_world(all_steps[world_id], world.scorer_only)
            if tuple(score["registered_cutoffs"]) != world.observable.cutoffs or tuple(score["scored_cutoffs"]) != world.observable.cutoffs:
                raise ValueError(f"score cutoff trace differs from registered input for {world_id}")
            scores.append(score)
            base.write_json(RUN_DIR / "scores" / f"{world_id}.json", score)
        runtime["scoring_wall_seconds"] = (time.perf_counter_ns() - scoring_started) / 1_000_000_000
        base.log(f"SCORING_PASS worlds={len(scores)} seconds={runtime['scoring_wall_seconds']:.6f}")

        stage = "aggregation"
        aggregate_started = time.perf_counter_ns()
        aggregate = evaluation.aggregate_world_scores(scores)
        runtime["aggregation_wall_seconds"] = (time.perf_counter_ns() - aggregate_started) / 1_000_000_000
        base.write_json(RUN_DIR / "aggregate_world_scores.json", aggregate)
        metrics = base.build_metrics(worlds, scores, all_steps, aggregate, rule_call_ns, rule_call_counts)
        base.write_json(RUN_DIR / "metrics.json", metrics)

        stage = "charts"
        chart_started = time.perf_counter_ns()
        charts = base.make_charts(worlds, all_steps, scores, metrics)
        runtime["chart_wall_seconds"] = (time.perf_counter_ns() - chart_started) / 1_000_000_000
        runtime["end_to_end_compute_seconds"] = sum(
            runtime[key] for key in (
                "generation_wall_seconds", "first_attempt_preflight_wall_seconds",
                "saved_input_reload_wall_seconds", "preflight_wall_seconds",
                "combined_method_wall_seconds", "scoring_wall_seconds",
                "aggregation_wall_seconds", "chart_wall_seconds",
            )
        )
        runtime["artifact_write_seconds"] = base.ARTIFACT_WRITE_NS / 1_000_000_000
        status = "PASS_SYNTHETIC_DEVELOPMENT_ONLY"
        run_meta["finished_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        run_meta["status"] = status
        run_meta["runtime"] = runtime
        run_meta["charts"] = charts
        run_meta["failure_count_for_comparison_attempt_02"] = 0
        report = base.make_report(run_meta, audit, metrics, runtime, charts, status)
        report += f"""

## Preserved first preflight attempt

The first invocation is retained at [`../run_manifest.json`](../run_manifest.json) with status `INVALID_RUN`. It generated and saved the same 12 development worlds but stopped before either rule ran. Its audit compared sparse `Counter` output to an expected mapping containing explicit zero counts, so it falsely flagged nine non-UNKNOWN strata. The raw generated inputs, scorer sidecars, candidate traces, failures and runtimes from that invocation remain hash-verified; this comparison reused those exact files and did not call the generator again.

The first attempt's manifest SHA-256 is `{run_meta['previous_attempt_manifest_sha256']}`. No rule output from that attempt exists.
"""
        base.write_bytes(RUN_DIR / "REPORT.md", report.encode("utf-8"))
        base.write_json(RUN_DIR / "runtime.json", runtime)
        base.write_json(RUN_DIR / "failures.json", {
            "comparison_attempt_02_failures": [],
            "preserved_attempt_01": {
                "status": prior_manifest["status"],
                "failure_artifact": "../failures.json",
                "preflight_audit": "../preflight_audit.json",
                "failure_count": len(prior_failures),
                "manifest_sha256": run_meta["previous_attempt_manifest_sha256"],
            },
        })
        base.write_json(RUN_DIR / "run_summary.json", {
            "status": status,
            "run_meta": run_meta,
            "reused_input_world_count": len(worlds),
            "generator_invoked_in_comparison_attempt_02": False,
            "preflight_status": audit["status"],
            "aggregate_independent_world_count": aggregate["independent_world_count"],
            "metrics": metrics,
            "charts": charts,
            "prior_preflight_attempt_status": prior_manifest["status"],
            "prior_preflight_attempt_failures": len(prior_failures),
        })
        base.log("RUN_COMPLETE status=PASS_SYNTHETIC_DEVELOPMENT_ONLY generator_invoked=false")
    except Exception as exc:
        failures.append({
            "stage": stage,
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        })
        status = "INVALID_RUN" if stage in {"corrected_preflight", "method_execution", "scoring", "aggregation"} else "RUNNER_ERROR"
        base.log(f"RUN_FAILED stage={stage} type={type(exc).__name__} message={exc}")
    finally:
        runtime["comparison_attempt_02_script_elapsed_seconds"] = (time.perf_counter_ns() - started_ns) / 1_000_000_000
        if failures:
            base.write_json(RUN_DIR / "failures.json", {
                "comparison_attempt_02_failures": failures,
                "preserved_attempt_01": "../failures.json",
            })
            base.write_json(RUN_DIR / "run_summary.json", {
                "status": status,
                "stage": stage,
                "world_scores_written": len(scores),
                "failure_count": len(failures),
                "runtime": runtime,
            })
        base.write_json(RUN_DIR / "runtime.json", runtime)
        base.write_bytes(RUN_DIR / "run.log.txt", ("\n".join(base.LOG_LINES) + "\n").encode("utf-8"))
        previous_manifest_sha = base.file_sha256(INPUT_RUN_DIR / "run_manifest.json")
        manifest = {
            "artifact_version": "finite-synthetic-development-comparison-v1",
            "classification": "SYNTHETIC_DEVELOPMENT_ONLY",
            "status": status,
            "source_commit": EXPECTED_COMMIT,
            "branch_at_run": "task/research-three-v2-alignment-20261011",
            "protocol_status": "REVIEW_DRAFT",
            "generator_invoked_in_this_comparison_attempt": False,
            "reused_saved_input_artifacts": "../inputs AND ../scorer_sidecars; exact bytes copied and verified",
            "previous_preflight_attempt": {
                "path": "../run_manifest.json",
                "status": "INVALID_RUN_PRE_METHOD_PREFLIGHT_ONLY",
                "manifest_sha256": previous_manifest_sha,
                "failure_artifact": "../failures.json",
            },
            "configuration_sha256": run_meta["configuration_sha256"] if run_meta else None,
            "files": base.list_artifact_hashes(),
            "manifest_excludes_itself_from_file_hashes": True,
            "mac_persistence": "PREPARED_IN_REPOSITORY; NOT_STORED_ON_MAC; MAC_OFFLINE",
            "failure_count": len(failures),
        }
        base.write_json(RUN_DIR / "run_manifest.json", manifest)
        base.LOG_LINES.append(f"{datetime.now(timezone.utc).isoformat()} MANIFEST_WRITTEN files={len(manifest['files'])} status={status}")
        base.write_bytes(RUN_DIR / "run.log.txt", ("\n".join(base.LOG_LINES) + "\n").encode("utf-8"))
        manifest["files"] = base.list_artifact_hashes()
        base.write_json(RUN_DIR / "run_manifest.json", manifest)

    return 0 if status == "PASS_SYNTHETIC_DEVELOPMENT_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
