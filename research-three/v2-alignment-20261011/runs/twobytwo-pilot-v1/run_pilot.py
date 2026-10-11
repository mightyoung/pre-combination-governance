#!/usr/bin/env python3
"""Run the frozen four-call CPU pilot, then join scorer-only assignments."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SRC = REPO / "risk-fusion-bench" / "src"
sys.path.insert(0, str(SRC))

from rfb.research.observable_association import (  # noqa: E402
    InferenceConfig,
    KnownField,
    ObservationRecord,
    build_candidate_universe,
    freeze_observable_prefix,
    freeze_proposals,
    multi_evidence_rule,
    time_asset_rule,
)


PROTOCOL_PATH = HERE / "PROTOCOL.md"
PROTOCOL_FREEZE_PATH = HERE / "PROTOCOL_FREEZE_RECORD.json"
SCORER_PATH = HERE / "SCORER_ONLY_PREDECLARATION.json"
INPUT_FREEZE_PATH = HERE / "INPUT_FREEZE_RECORD.json"
PRIOR_RUN = (
    HERE.parent
    / "development-c34d97e0"
    / "comparison_attempt_02"
)
PRIOR_RUN_MANIFEST = PRIOR_RUN / "run_manifest.json"
PRIOR_RUN_CONFIG = PRIOR_RUN / "run_configuration.json"
METHOD_PATH = REPO / "risk-fusion-bench/src/rfb/research/observable_association.py"

METHODS = {
    "TIME_ASSET_RULE": time_asset_rule,
    "MULTI_EVIDENCE_RULE": multi_evidence_rule,
}
TEMPLATES = {
    "V1_ONE_ROOT": "method_inputs/V1_ONE_ROOT.json",
    "V2_TWO_ROOT_IDS": "method_inputs/V2_TWO_ROOT_IDS.json",
}
CONFIG = {
    "candidate_pair_window_seconds": 120,
    "same_asset_candidate_horizon_seconds": 600,
    "candidate_radius_m": 8.0,
    "position_margin_m": 1.0,
    "value_tolerance_c": 2.5,
    "parameter_status": "SYNTHETIC_TEST_VALUE_NOT_FOR_PRODUCTION",
}
CASE_TEMPLATE = {
    "R1-SAME": "V1_ONE_ROOT",
    "R1-DIFF": "V1_ONE_ROOT",
    "R2-SAME": "V2_TWO_ROOT_IDS",
    "R2-DIFF": "V2_TWO_ROOT_IDS",
}
CLONE_PAIRS = [("R1-SAME", "R1-DIFF"), ("R2-SAME", "R2-DIFF")]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes())


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def write_fsynced(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def fail(message: str) -> None:
    raise SystemExit(f"PILOT STOPPED: {message}")


def verify_pre_execution_contract() -> tuple[dict, dict, dict, dict, str]:
    freeze = json.loads(PROTOCOL_FREEZE_PATH.read_text(encoding="utf-8"))
    input_freeze = json.loads(INPUT_FREEZE_PATH.read_text(encoding="utf-8"))
    if freeze.get("freeze_status") != "FROZEN_BEFORE_EXECUTION":
        fail("protocol freeze status is not FROZEN_BEFORE_EXECUTION")
    if freeze.get("execution_started") or freeze.get("method_calls_made") != 0:
        fail("protocol freeze record indicates a prior method call")
    protocol_hash = file_sha256(PROTOCOL_PATH)
    if protocol_hash != freeze["protocol_sha256"]:
        fail("protocol file no longer matches the frozen digest")
    if input_freeze.get("protocol_sha256") != protocol_hash:
        fail("input freeze is bound to a different protocol")
    if file_sha256(METHOD_PATH) != freeze["method_source_sha256"]:
        fail("method source differs from the frozen source")
    if input_freeze.get("method_source_sha256") != freeze["method_source_sha256"]:
        fail("input freeze is bound to a different method source")

    # This is the original configuration object from attempt_02. Reading it
    # does not open any scorer-sidecar or expose any truth assignment.
    prior_config_doc = json.loads(PRIOR_RUN_CONFIG.read_text(encoding="utf-8"))
    prior_config = prior_config_doc["configuration"]
    prior_config_digest = sha256(
        json.dumps(
            prior_config, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
    if prior_config_digest != freeze["frozen_original_configuration_sha256"]:
        fail("original attempt_02 configuration digest changed")
    if prior_config.get("inference_config") != CONFIG:
        fail("the pilot InferenceConfig differs from original parameters")
    if input_freeze.get("original_configuration_sha256") != prior_config_digest:
        fail("input freeze is bound to a different original configuration")

    # Pin the historical run manifest without opening its scorer files yet.
    prior_manifest_bytes = PRIOR_RUN_MANIFEST.read_bytes()
    prior_manifest_digest = sha256(prior_manifest_bytes)
    if prior_manifest_digest != freeze["previous_development_attempt_02_manifest_sha256"]:
        fail("prior attempt_02 manifest digest changed")
    if not input_freeze.get("templates") or len(input_freeze["templates"]) != 2:
        fail("expected exactly two frozen input templates")
    return freeze, input_freeze, prior_config, json.loads(prior_manifest_bytes), prior_manifest_digest


def parse_method_input(payload: dict):
    records = []
    for row in payload["observations"]:
        fields = []
        for field in row["fields"]:
            value = field["value"]
            if field["name"] in {"position_m", "acquisition_lineage"} and value is not None:
                value = tuple(value)
            fields.append(
                KnownField(
                    field["name"],
                    value,
                    field["actual_available_at"],
                    field["earliest_known_at"],
                )
            )
        records.append(
            ObservationRecord(
                row["observation_id"],
                row["id_actual_available_at"],
                row["id_earliest_known_at"],
                row["received_at"],
                tuple(fields),
            )
        )
    prefix = freeze_observable_prefix(tuple(records), as_of=payload["as_of"])
    return prefix


def verify_old_run(prior_manifest: dict) -> dict:
    failures = []
    checked = 0
    for row in prior_manifest["files"]:
        path = PRIOR_RUN / row["path"]
        if not path.is_file():
            failures.append({"path": row["path"], "problem": "MISSING"})
            continue
        raw = path.read_bytes()
        checked += 1
        if len(raw) != row["bytes"] or sha256(raw) != row["sha256"]:
            failures.append({"path": row["path"], "problem": "HASH_OR_SIZE_MISMATCH"})
    return {"status": "PASS" if not failures else "FAIL", "files_checked": checked, "failures": failures}


def proposal_by_template(outputs: dict, template_name: str, method: str) -> dict:
    path = HERE / "outputs" / template_name / f"{method}.json"
    return json.loads(path.read_text(encoding="utf-8"))["proposals"][0]


def main() -> None:
    if (HERE / "OUTPUTS_FROZEN.json").exists() or (HERE / "RUN_MANIFEST.json").exists():
        fail("a pilot output freeze already exists; do not rerun this frozen protocol")
    freeze, input_freeze, prior_config, prior_manifest, prior_manifest_digest = (
        verify_pre_execution_contract()
    )
    template_records = {row["template"]: row for row in input_freeze["templates"]}
    if set(template_records) != set(TEMPLATES):
        fail("input freeze template names do not match the protocol")

    raw_inputs: dict[str, bytes] = {}
    parsed_inputs: dict[str, dict] = {}
    prefixes = {}
    for name, relative in TEMPLATES.items():
        path = HERE / relative
        raw = path.read_bytes()
        row = template_records[name]
        if sha256(raw) != row["sha256"] or len(raw) != row["bytes"]:
            fail(f"method input {name} differs from its frozen hash")
        payload = json.loads(raw)
        raw_inputs[name] = raw
        parsed_inputs[name] = payload
        prefixes[name] = parse_method_input(payload)

    config = InferenceConfig(**CONFIG)
    started_ns = time.perf_counter_ns()
    calls = 0
    outputs = {}
    candidate_counts = {}
    for template_name in TEMPLATES:
        prefix = prefixes[template_name]
        candidate_universe = build_candidate_universe(prefix, config=config)
        candidate_counts[template_name] = len(candidate_universe)
        if len(candidate_universe) != 1:
            fail(f"{template_name} candidate count was {len(candidate_universe)}, expected 1")
        pair = candidate_universe[0]
        outputs[template_name] = {}
        for method_name, method in METHODS.items():
            proposal = method(prefix, pair, config=config)
            calls += 1
            frozen = freeze_proposals([proposal])
            output_path = HERE / "outputs" / template_name / f"{method_name}.json"
            write_fsynced(output_path, frozen.canonical_json)
            outputs[template_name][method_name] = {
                "path": output_path.relative_to(HERE).as_posix(),
                "bytes": len(frozen.canonical_json),
                "sha256": frozen.sha256,
            }
    if calls != 4:
        fail(f"made {calls} rule calls; expected exactly 4")

    outputs_frozen = {
        "artifact_version": "2x2-method-outputs-frozen-v1",
        "protocol_id": freeze["protocol_id"],
        "protocol_sha256": freeze["protocol_sha256"],
        "input_freeze_record_sha256": file_sha256(INPUT_FREEZE_PATH),
        "method_source_sha256": freeze["method_source_sha256"],
        "original_configuration_sha256": freeze["frozen_original_configuration_sha256"],
        "method_input_hashes": {name: sha256(raw) for name, raw in raw_inputs.items()},
        "candidate_count_by_template": candidate_counts,
        "method_calls_made": calls,
        "outputs": outputs,
        "execution_started": True,
        "scorer_sidecar_accessed": False,
        "outputs_frozen_at_utc": utc_now(),
        "elapsed_method_execution_ns": time.perf_counter_ns() - started_ns,
    }
    frozen_bytes = canonical_json(outputs_frozen)
    frozen_path = HERE / "OUTPUTS_FROZEN.json"
    write_fsynced(frozen_path, frozen_bytes)
    outputs_frozen_hash = sha256(frozen_bytes)

    # Only now may the scorer-only assignment be opened.
    scorer_bytes = SCORER_PATH.read_bytes()
    scorer_hash = sha256(scorer_bytes)
    if scorer_hash != freeze["scorer_only_predeclaration_sha256"]:
        fail("scorer-only predeclaration differs from its frozen digest")
    scorer = json.loads(scorer_bytes)
    scorer_opened_at = utc_now()

    inputs_by_case = {
        case_id: template_records[template]["sha256"]
        for case_id, template in CASE_TEMPLATE.items()
    }
    expected_case_ids = set(CASE_TEMPLATE)
    scorer_cases = {item["case_id"]: item for item in scorer["cases"]}
    if set(scorer_cases) != expected_case_ids:
        fail("scorer-only case IDs do not match the frozen 2x2 protocol")

    pair_hash_equal = {}
    for first, second in CLONE_PAIRS:
        pair_hash_equal[f"{first}/{second}"] = inputs_by_case[first] == inputs_by_case[second]
    if not all(pair_hash_equal.values()):
        fail(
            "INVALID_IDENTIFIABILITY_CHECK: opposite-label method-input clones differ; "
            "stop before interpreting any case labels"
        )

    case_rows = []
    case_failures = []
    for case_id in sorted(expected_case_ids):
        sidecar_case = scorer_cases[case_id]
        template_name = CASE_TEMPLATE[case_id]
        event_keys = sidecar_case["observation_event_keys"]
        observation_ids = sorted(event_keys)
        if len(observation_ids) != 2:
            fail(f"{case_id} must assign exactly two observation event keys")
        generated_relation = "SAME" if event_keys[observation_ids[0]] == event_keys[observation_ids[1]] else "DIFFERENT"
        if generated_relation != sidecar_case["event_relation"]:
            fail(f"{case_id} declared event relation disagrees with registry identity")

        family_map = sidecar_case["source_family_by_observation"]
        families = {family_map[item] for item in observation_ids}
        generated_source_relation = (
            "SHARED_SOURCE_FAMILY" if len(families) == 1 else "DISJOINT_SOURCE_FAMILIES"
        )
        declared_source_relation = sidecar_case["source_dependence"]
        if generated_source_relation == "SHARED_SOURCE_FAMILY":
            if not declared_source_relation.startswith("SHARED_"):
                fail(f"{case_id} source-family graph contradicts its declared dependence")
        elif declared_source_relation != "DISJOINT_SOURCE_FAMILIES":
            fail(f"{case_id} distinct family IDs contradict its declared dependence")

        template_payload = parsed_inputs[template_name]
        root_ids = {
            next(
                field["value"][0]
                for field in observation["fields"]
                if field["name"] == "acquisition_lineage"
            )
            for observation in template_payload["observations"]
        }
        visible_root_count = len(root_ids)
        method_decisions = {}
        for method_name in METHODS:
            proposal = proposal_by_template(outputs, template_name, method_name)
            method_decisions[method_name] = {
                "action": proposal["action"],
                "reason_codes": proposal["reason_codes"],
                "independent_lineage_root_count": proposal[
                    "independent_lineage_root_count"
                ],
                "evidence_refs": proposal["evidence_refs"],
            }
            if proposal["independent_lineage_root_count"] != visible_root_count:
                case_failures.append(
                    f"{case_id}/{method_name}: output root count does not match visible root IDs"
                )

        twin = sidecar_case["counterfactual_clone"]
        clone_key = f"{case_id}/{twin}" if f"{case_id}/{twin}" in pair_hash_equal else f"{twin}/{case_id}"
        input_clone_equal = pair_hash_equal[clone_key]
        identifiability = "UNIDENTIFIABLE_FROM_METHOD_INPUTS"
        if input_clone_equal and sidecar_case["identifiability"] != identifiability:
            fail(f"{case_id} scorer identifiability label disagrees with exact input hash check")
        case_rows.append(
            {
                "case_id": case_id,
                "template": template_name,
                "method_input_sha256": inputs_by_case[case_id],
                "counterfactual_clone": twin,
                "clone_input_bytes_equal": input_clone_equal,
                "identifiability": identifiability,
                "event_relation_from_predeclared_registry": generated_relation,
                "source_family_relation_from_predeclared_graph": declared_source_relation,
                "visible_root_id_count": visible_root_count,
                "methods": method_decisions,
                "truth_scoring_status": "NOT_SCORED_UNIDENTIFIABLE",
            }
        )

    old_run_check = verify_old_run(prior_manifest)
    if old_run_check["status"] != "PASS":
        case_failures.append("prior development attempt_02 no longer matches its file manifest")
    expected_behaviors = {
        "V1_ONE_ROOT": {
            "TIME_ASSET_RULE": ("LINK_CANDIDATES", None),
            "MULTI_EVIDENCE_RULE": ("ABSTAIN", "NO_INDEPENDENT_ACQUISITION_ROOTS"),
        },
        "V2_TWO_ROOT_IDS": {
            "TIME_ASSET_RULE": ("LINK_CANDIDATES", None),
            "MULTI_EVIDENCE_RULE": ("LINK_CANDIDATES", "INDEPENDENT_ACQUISITION_ROOTS"),
        },
    }
    expectation_checks = []
    for template_name, expected in expected_behaviors.items():
        for method_name, (expected_action, expected_reason) in expected.items():
            proposal = proposal_by_template(outputs, template_name, method_name)
            action_ok = proposal["action"] == expected_action
            reason_ok = expected_reason is None or expected_reason in proposal["reason_codes"]
            expectation_checks.append(
                {
                    "template": template_name,
                    "method": method_name,
                    "action_expected": expected_action,
                    "reason_expected": expected_reason,
                    "action_observed": proposal["action"],
                    "reasons_observed": proposal["reason_codes"],
                    "status": "PASS" if action_ok and reason_ok else "DEVIATION",
                }
            )
            if not action_ok or not reason_ok:
                case_failures.append(
                    f"{template_name}/{method_name}: predeclared rule-path expectation deviated"
                )

    results = {
        "artifact_version": "2x2-cpu-pilot-case-results-v1",
        "protocol_id": freeze["protocol_id"],
        "protocol_sha256": freeze["protocol_sha256"],
        "scorer_only_predeclaration_sha256": scorer_hash,
        "outputs_frozen_sha256": outputs_frozen_hash,
        "scorer_sidecar_opened_after_outputs_frozen": True,
        "scorer_sidecar_opened_at_utc": scorer_opened_at,
        "identifiability_hash_checks": pair_hash_equal,
        "case_count": len(case_rows),
        "unique_method_input_count": len(raw_inputs),
        "rule_invocations": 4,
        "method_input_sha256_by_template": outputs_frozen["method_input_hashes"],
        "method_output_sha256_by_template_and_rule": {
            template: {method: row["sha256"] for method, row in methods.items()}
            for template, methods in outputs.items()
        },
        "case_results": case_rows,
        "protocol_expectation_checks": expectation_checks,
        "prior_attempt_02_integrity": {
            "manifest_sha256": prior_manifest_digest,
            **old_run_check,
        },
        "failure_analysis": [
            "R1-SAME and R1-DIFF have identical method-visible bytes, so the same-root input cannot distinguish event identity.",
            "With one root ID, MULTI_EVIDENCE_RULE abstains because it counts root strings; this does not establish that the two observations are the same event.",
            "R2-SAME and R2-DIFF also have identical method-visible bytes. Both rules link candidates from that input, including the scorer-only shared-upstream-family assignment.",
            "MULTI_EVIDENCE_RULE reports two independent acquisition roots for R2 based on distinct root IDs. The scorer-only graph shows that this does not authenticate independent source evidence.",
            "The hidden labels were generated from a predeclared event registry and source-family graph independent of rule code. Because opposite labels are byte-identical per root-count row, no truth-accuracy, false-merge, false-split, or superiority rate is computed.",
        ],
        "case_failures": case_failures,
        "classification": "SYNTHETIC_DEVELOPMENT_PILOT_ONLY",
        "formal_effect_evaluation": False,
        "heldout": False,
        "model_network_device_or_notification_used": False,
        "all_truth_pairs_scored": False,
    }
    result_bytes = canonical_json(results)
    write_fsynced(HERE / "case_results.json", result_bytes)

    report = render_report(results, outputs_frozen, outputs)
    write_fsynced(HERE / "REPORT.md", report.encode("utf-8"))
    log_lines = [
        "2x2 synthetic CPU pilot v1",
        f"protocol_sha256={freeze['protocol_sha256']}",
        f"outputs_frozen_sha256={outputs_frozen_hash}",
        f"scorer_only_sha256={scorer_hash}",
        f"scorer_sidecar_opened_after_outputs_frozen=true ({scorer_opened_at})",
        "method_calls=4; unique_method_inputs=2; candidate_pairs=1 per template",
        f"prior_attempt_02_manifest_sha256={prior_manifest_digest}",
        f"prior_attempt_02_integrity={old_run_check['status']} files_checked={old_run_check['files_checked']}",
        f"case_failures={len(case_failures)}",
    ]
    write_fsynced(HERE / "run.log.txt", ("\n".join(log_lines) + "\n").encode("utf-8"))

    artifact_files = []
    for path in sorted(p for p in HERE.rglob("*") if p.is_file() and p.name != "RUN_MANIFEST.json"):
        raw = path.read_bytes()
        artifact_files.append(
            {
                "path": path.relative_to(HERE).as_posix(),
                "bytes": len(raw),
                "sha256": sha256(raw),
            }
        )
    manifest = {
        "artifact_version": "2x2-cpu-pilot-run-manifest-v1",
        "classification": "SYNTHETIC_DEVELOPMENT_PILOT_ONLY",
        "branch_at_execution": os.environ.get("GIT_BRANCH", "task/research-three-v2-alignment-20261011"),
        "protocol_id": freeze["protocol_id"],
        "protocol_sha256": freeze["protocol_sha256"],
        "protocol_freeze_record_sha256": file_sha256(PROTOCOL_FREEZE_PATH),
        "input_freeze_record_sha256": file_sha256(INPUT_FREEZE_PATH),
        "scorer_only_predeclaration_sha256": scorer_hash,
        "method_source_sha256": freeze["method_source_sha256"],
        "original_configuration_sha256": freeze["frozen_original_configuration_sha256"],
        "prior_attempt_02_manifest_sha256": prior_manifest_digest,
        "outputs_frozen_sha256": outputs_frozen_hash,
        "outputs_frozen_before_scorer_open": True,
        "scorer_sidecar_opened_at_utc": scorer_opened_at,
        "method_calls_made": 4,
        "candidate_pair_count_by_template": candidate_counts,
        "unique_method_inputs": 2,
        "case_count": 4,
        "case_labels_scored": 0,
        "case_failures": case_failures,
        "prior_attempt_02_integrity": old_run_check,
        "python_version": sys.version,
        "platform": platform.platform(),
        "elapsed_process_ns_through_output_freeze": outputs_frozen["elapsed_method_execution_ns"],
        "manifest_excludes_itself": True,
        "files": artifact_files,
    }
    manifest_bytes = canonical_json(manifest)
    write_fsynced(HERE / "RUN_MANIFEST.json", manifest_bytes)
    print(f"completed 4 rule calls on 2 unique synthetic inputs; scorer labels scored: 0")
    print(f"prior attempt_02 integrity: {old_run_check['status']} ({old_run_check['files_checked']} files)")
    print(f"case failures: {len(case_failures)}")
    print(f"outputs freeze sha256: {outputs_frozen_hash}")
    print(f"run manifest sha256: {sha256(manifest_bytes)}")


def render_report(results: dict, frozen: dict, outputs: dict) -> str:
    lines = [
        "# 2×2 Counterexample CPU Pilot — Results",
        "",
        "Classification: synthetic development pilot only. This is not a held-out run, formal effect evaluation, device trial, or real notification test.",
        "",
        "## Frozen inputs, code, and execution",
        "",
        f"- Protocol: `{results['protocol_id']}`; SHA-256 `{results['protocol_sha256']}`.",
        f"- Scorer-only predeclaration: SHA-256 `{results['scorer_only_predeclaration_sha256']}`; opened after outputs were frozen.",
        f"- Method calls: {results['rule_invocations']} (two rules × two unique inputs); candidate pairs: one per input.",
        f"- Input hashes: `{json.dumps(results['method_input_sha256_by_template'], sort_keys=True)}`.",
        f"- Output hashes: `{json.dumps(results['method_output_sha256_by_template_and_rule'], sort_keys=True)}`.",
        "- Frozen parameters were inherited from the original development run; no tuning or held-out access occurred.",
        "- No model, network, device, notification, or paid service was used.",
        "",
        "## Case decisions",
        "",
        "| Case | Hidden event relation | Scorer-only source relation | Visible roots | Input clone equal | TIME_ASSET_RULE | MULTI_EVIDENCE_RULE | Truth score |",
        "|---|---|---|---:|---|---|---|---|",
    ]
    for row in results["case_results"]:
        time_decision = row["methods"]["TIME_ASSET_RULE"]
        multi_decision = row["methods"]["MULTI_EVIDENCE_RULE"]
        lines.append(
            "| {case} | {event} | {source} | {roots} | {clone} | {time_action} / {time_reason} | {multi_action} / {multi_reason} (root count {multi_roots}) | {score} |".format(
                case=row["case_id"],
                event=row["event_relation_from_predeclared_registry"],
                source=row["source_family_relation_from_predeclared_graph"],
                roots=row["visible_root_id_count"],
                clone="yes" if row["clone_input_bytes_equal"] else "no",
                time_action=time_decision["action"],
                time_reason=", ".join(time_decision["reason_codes"]),
                multi_action=multi_decision["action"],
                multi_reason=", ".join(multi_decision["reason_codes"]),
                multi_roots=multi_decision["independent_lineage_root_count"],
                score=row["truth_scoring_status"],
            )
        )
    lines.extend(
        [
            "",
            "The event labels were generated from the predeclared scorer-only event registry, not derived from the method rules or visible measurements. Source dependence was assigned separately from the scorer-only family graph.",
            "",
            "## Input-clone and identifiability check",
            "",
            f"- R1 opposite-label inputs byte-identical: `{results['identifiability_hash_checks']['R1-SAME/R1-DIFF']}`.",
            f"- R2 opposite-label inputs byte-identical: `{results['identifiability_hash_checks']['R2-SAME/R2-DIFF']}`.",
            "- All four cases are marked `NOT_SCORED_UNIDENTIFIABLE`; no accuracy, false-merge, false-split, or superiority rate is reported.",
            "",
            "## Findings and failure analysis",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in results["failure_analysis"])
    lines.extend(
        [
            "",
            "The predeclared path expectations were checked against outputs (see `case_results.json`). A `LINK_CANDIDATES` proposal is a candidate association only; it does not confirm an event identity.",
            "",
            "## Prior-run preservation and limits",
            "",
            f"- Original `comparison_attempt_02` manifest SHA-256: `{results['prior_attempt_02_integrity']['manifest_sha256']}`.",
            f"- Historical files rechecked against that manifest: {results['prior_attempt_02_integrity']['files_checked']}; integrity status: `{results['prior_attempt_02_integrity']['status']}`.",
            "- These four synthetic assignments are counterexamples to treating acquisition-root IDs as either event identity or source-independence proof. They do not estimate real-world error rates or establish general rule performance.",
            "- Real-world source provenance, event confirmation, reminder delivery and user-visible timing remain untested.",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
