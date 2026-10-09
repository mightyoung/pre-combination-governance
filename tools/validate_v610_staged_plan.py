from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MD = ROOT / "实验设计与执行计划v6.10-100GB分阶段执行版.md"
DOCX = MD.with_suffix(".docx")
CONTRACT = ROOT / "ExperimentExecutionPlan-v6.10.json"
TEMPLATES = ROOT / "MMETemplateMatrix-v6.10.csv"
ALLOCATION = ROOT / "MMEAllocation-v6.10-100GBStaged.csv"
STAGES = ROOT / "StorageStagePlan-v6.10.csv"
SCHEMA = ROOT / "StorageStageManifest-v6.10.schema.json"
DOCX_REPORT = ROOT / "v6.10-100GB分阶段计划交付与结构核验.json"
V69_ACCEPTANCE = ROOT / "v6.9-指定实验计划最终验收.json"
OUT = ROOT / "v6.10-100GB分阶段实验计划最终验收.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    failures: list[str] = []
    required_files = [MD, CONTRACT, TEMPLATES, ALLOCATION, STAGES, SCHEMA, V69_ACCEPTANCE]
    for path in required_files:
        if not path.exists():
            failures.append(f"missing file: {path.name}")

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    allocation = read_csv(ALLOCATION)
    stages = read_csv(STAGES)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    docx_report = json.loads(DOCX_REPORT.read_text(encoding="utf-8")) if DOCX_REPORT.exists() else None
    v69 = json.loads(V69_ACCEPTANCE.read_text(encoding="utf-8"))
    md_text = MD.read_text(encoding="utf-8")

    if contract.get("authoritative_artifact") != MD.name:
        failures.append("Markdown is not the declared authoritative artifact")
    format_policy = contract.get("delivery_format_policy", {})
    if format_policy.get("experiment_plan") != "MARKDOWN_AUTHORITATIVE":
        failures.append("experiment plan format policy is not Markdown-authoritative")
    if format_policy.get("docx_derivative_required") is not False or format_policy.get("docx_layout_gate_required") is not False:
        failures.append("DOCX is still configured as a required experiment-plan gate")

    storage = contract["storage_execution"]
    sub = storage["subbudgets_bytes"]
    if storage["stage_cap_bytes"] != 100_000_000_000:
        failures.append("stage cap is not decimal 100GB")
    if sum(sub.values()) != storage["stage_cap_bytes"]:
        failures.append("storage subbudgets do not sum to stage cap")
    expected_sub = {"committed": 80_000_000_000, "scratch_partial_retry": 10_000_000_000, "recovery_quarantine": 5_000_000_000, "manifests_checksums_reserve": 5_000_000_000}
    if sub != expected_sub:
        failures.append("storage subbudget contract changed")
    if storage["effect_look_allowed_between_stages"] is not False:
        failures.append("effect look is incorrectly allowed")
    if storage["archive_uri_a"] != "PENDING_ARCHIVE_URI_A" or storage["archive_uri_b"] != "PENDING_ARCHIVE_URI_B":
        failures.append("archive placeholders changed without signoff")

    gates = contract["resource_gates"]
    formula_checks = {
        "reserve25": gates["reserve_25pct_bytes"] == 235_853_007_872,
        "below_reserve": gates["current_below_reserve_bytes"] == 18_670_873_600,
        "target80_launch": gates["target80_same_volume_start_free_bytes"] == 315_853_007_872,
        "target80_shortfall": gates["target80_additional_free_bytes"] == 98_670_873_600,
        "hard100_launch": gates["hard100_same_volume_start_free_bytes"] == 335_853_007_872,
        "hard100_shortfall": gates["hard100_additional_free_bytes"] == 118_670_873_600,
        "archive_capacity": storage["legacy_planning_point_only"]["two_archive_capacity_with_5pct_each_bytes"] == 936_307_008_000,
    }
    if not all(formula_checks.values()):
        failures.append(f"capacity formula failure: {formula_checks}")
    if gates["current_G0_RESOURCE"] != "FAIL" or gates["current_G0_STAGED"] != "FAIL":
        failures.append("G0 status was incorrectly promoted")
    if gates["pilot_authorized"] or gates["d_test_authorized"]:
        failures.append("pilot or D_test incorrectly authorized")

    if len(allocation) != 2352:
        failures.append(f"allocation rows wrong: {len(allocation)}")
    if any(row["contains_executable_seed"].lower() == "true" for row in allocation):
        failures.append("allocation contains executable seeds")
    if any(row["effect_look_allowed"].lower() == "true" for row in allocation):
        failures.append("allocation permits effect look")
    r_alg_values = Counter(row["r_alg"] for row in allocation)
    if r_alg_values != Counter({"PENDING_G3A_PREREGISTRATION": 2352}):
        failures.append(f"r_alg preregistration placeholder wrong: {dict(r_alg_values)}")

    superblocks: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in allocation:
        superblocks.setdefault((row["phase"], row["balance_superblock_id"]), []).append(row)
    sb_phase = Counter(phase for phase, _ in superblocks)
    if sb_phase != Counter({"SCREEN": 4, "VERIFY": 10}):
        failures.append(f"MME superblock counts wrong: {dict(sb_phase)}")
    sb_checks: dict[str, object] = {}
    for (phase, sb_id), members in superblocks.items():
        strata = Counter(row["stratum"] for row in members)
        sequences = Counter(row["method_sequence_id"] for row in members)
        templates = Counter(row["template_id"] for row in members)
        if len(members) != 168:
            failures.append(f"{sb_id}: not 168 bundles")
        if len(strata) != 24 or set(strata.values()) != {7}:
            failures.append(f"{sb_id}: stratum imbalance")
        if len(sequences) != 14 or set(sequences.values()) != {12}:
            failures.append(f"{sb_id}: Williams imbalance")
        expected_template = {2} if phase == "SCREEN" else {6}
        if set(templates.values()) != expected_template:
            failures.append(f"{sb_id}: template imbalance")
    sb_checks = {"counts": dict(sb_phase), "bundles_per_superblock": 168, "strata_each": 7, "williams_each": 12, "screen_template_each": 2, "verify_template_each": 6}

    stage_phase = Counter(row["phase"] for row in stages)
    expected_stage_phase = Counter({
        "PHASE0": 28,
        "MME_SCREEN": 4,
        "MME_VERIFY": 10,
        "D_SELECT": 4,
        "PILOT_W1": 6,
        "PILOT_W2": 6,
        "PILOT_W3": 4,
        "PILOT_HELDOUT": 4,
        "CONFIRMATORY": 1,
        "EXTERNAL": 1,
    })
    if len(stages) != 68 or stage_phase != expected_stage_phase:
        failures.append(f"storage stage plan counts wrong: rows={len(stages)}, phases={dict(stage_phase)}")
    if any(int(row["stage_cap_bytes"]) != 100_000_000_000 for row in stages):
        failures.append("one or more stage rows have wrong cap")
    if any(row["effect_look_allowed"].lower() == "true" for row in stages):
        failures.append("stage plan permits effect look")

    expected_execution_units = {"mme": 28, "d_select": 24, "pilot_confirm": 24}
    if storage["units"]["execution_batch"] != expected_execution_units:
        failures.append(f"execution-batch unit contract wrong: {storage['units']['execution_batch']}")
    d_select_rows = [row for row in stages if row["phase"] == "D_SELECT"]
    d_select_checks = {
        "rows": len(d_select_rows),
        "design_units": sum(int(row["design_units"]) for row in d_select_rows),
        "execution_batches": sum(int(row["execution_batches"]) for row in d_select_rows),
        "all_superblocks_168": all(row["design_units"] == "168" for row in d_select_rows),
        "all_batches_7": all(row["execution_batches"] == "7" for row in d_select_rows),
    }
    if d_select_checks != {
        "rows": 4,
        "design_units": 672,
        "execution_batches": 28,
        "all_superblocks_168": True,
        "all_batches_7": True,
    }:
        failures.append(f"D_SELECT storage mapping wrong: {d_select_checks}")
    if contract["selection"]["independent_bundles"] != d_select_checks["design_units"] or contract["selection"]["batches"] != d_select_checks["execution_batches"]:
        failures.append("D_SELECT CSV disagrees with JSON selection contract")

    confirmatory_rows = [row for row in stages if row["phase"] == "CONFIRMATORY"]
    confirmatory_placeholder_ok = len(confirmatory_rows) == 1 and all([
        confirmatory_rows[0]["balance_superblock_id"] == "CONFIRM-AGGREGATE-PENDING",
        confirmatory_rows[0]["unit_kind"] == "CONFIRMATORY_AGGREGATE_PLACEHOLDER",
        confirmatory_rows[0]["design_units"] == "FINAL_N",
        confirmatory_rows[0]["execution_batches"] == "FINAL_N/24",
        confirmatory_rows[0]["method_evaluations"] == "FINAL_N*5",
        "FINAL_N/120" in confirmatory_rows[0]["note"],
    ])
    if not confirmatory_placeholder_ok:
        failures.append("confirmatory aggregate placeholder semantics wrong")

    state_enum = schema["properties"]["state"]["enum"]
    required_states = ["PLANNED", "RUNNING", "SEALED_LOCAL", "ARCHIVED_A", "ARCHIVED_B", "RESTORE_VERIFIED", "PURGE_AUTHORIZED", "PURGED", "RECONCILED"]
    if any(state not in state_enum for state in required_states):
        failures.append("manifest schema misses required state")
    for key, value in [("stage_cap_bytes", 100_000_000_000), ("committed_budget_bytes", 80_000_000_000), ("scratch_budget_bytes", 10_000_000_000), ("recovery_budget_bytes", 5_000_000_000), ("manifest_reserve_bytes", 5_000_000_000)]:
        if schema["properties"][key]["const"] != value:
            failures.append(f"schema constant wrong: {key}")
    if schema["properties"]["effect_look_performed"]["const"] is not False:
        failures.append("schema permits effect peeking")

    for key, path in [("markdown", MD), ("template_matrix", TEMPLATES), ("allocation", ALLOCATION), ("storage_stage_plan", STAGES), ("storage_manifest_schema", SCHEMA)]:
        if contract["files"][key]["sha256"] != sha256(path):
            failures.append(f"hash mismatch: {key}")
    docx_derivative_status = "OPTIONAL_NOT_PRESENT"
    if DOCX.exists():
        docx_derivative_status = "OPTIONAL_PRESENT"
        if docx_report and docx_report.get("status") == "PASS" and docx_report.get("structure", {}).get("source_sha256") == sha256(MD):
            docx_derivative_status = "OPTIONAL_STRUCTURALLY_CURRENT"
        elif docx_report:
            docx_derivative_status = "OPTIONAL_PRESENT_NOT_CURRENT"

    v69_paths = {
        "markdown": ROOT / "实验设计与执行计划v6.9-指定执行版-机制验证到确认性试验.md",
        "docx": ROOT / "实验设计与执行计划v6.9-指定执行版-机制验证到确认性试验.docx",
        "json": ROOT / "ExperimentExecutionPlan-v6.9.json",
        "templates": ROOT / "MMETemplateMatrix-v6.9.csv",
        "allocation": ROOT / "MMEAllocation-v6.9.csv",
    }
    for key, path in v69_paths.items():
        if v69["sha256"][key] != sha256(path):
            failures.append(f"v6.9 original changed: {key}")

    required_tokens = [
        "100,000,000,000",
        "balance_superblock",
        "168 bundles",
        "120 bundles",
        "PENDING_ARCHIVE_URI_A/B",
        "335,853,007,872",
        "118,670,873,600",
        "936.307008GB",
        "storage_stage不是统计中期分析",
        "MD/JSON/CSV为权威执行包",
        "DOCX仅为可选阅读副本",
        "D_select固定为28个24-bundle batches",
    ]
    for token in required_tokens:
        if token not in md_text:
            failures.append(f"Markdown missing token: {token}")

    report = {
        "status": "PASS" if not failures else "FAIL",
        "checks": {
            "capacity_formulas": formula_checks,
            "MME_superblocks": sb_checks,
            "stage_plan_phase_counts": dict(stage_phase),
            "D_SELECT_storage_mapping": d_select_checks,
            "confirmatory_placeholder_ok": confirmatory_placeholder_ok,
            "r_alg_values": dict(r_alg_values),
            "manifest_state_machine": required_states,
            "v69_preserved": not any(item.startswith("v6.9 original changed") for item in failures),
            "docx_derivative_status": docx_derivative_status,
        },
        "failures": failures,
        "sha256": {
            "markdown": sha256(MD),
            "docx": sha256(DOCX) if DOCX.exists() else None,
            "json": sha256(CONTRACT),
            "templates": sha256(TEMPLATES),
            "allocation": sha256(ALLOCATION),
            "storage_stage_plan": sha256(STAGES),
            "manifest_schema": sha256(SCHEMA),
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(OUT), "status": report["status"], "failures": failures}, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
