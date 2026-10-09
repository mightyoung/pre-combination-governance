from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import build_v610_staged_experiment_plan as draft


ROOT = draft.ROOT
SECTION = ROOT / "tools" / "v610_storage_section_final.md"
MD_OUT = ROOT / "实验设计与执行计划v6.10-100GB分阶段执行版.md"
JSON_OUT = ROOT / "ExperimentExecutionPlan-v6.10.json"
TEMPLATE_OUT = ROOT / "MMETemplateMatrix-v6.10.csv"
ALLOCATION_OUT = ROOT / "MMEAllocation-v6.10-100GBStaged.csv"
STAGE_PLAN_OUT = ROOT / "StorageStagePlan-v6.10.csv"
SCHEMA_OUT = ROOT / "StorageStageManifest-v6.10.schema.json"

GB = 1_000_000_000
CAP = 100 * GB
COMMITTED = 80 * GB
SCRATCH = 10 * GB
RECOVERY = 5 * GB
MANIFEST = 5 * GB
TOTAL_VOLUME = 943_412_031_488
CURRENT_FREE = 217_182_134_272
R25 = 235_853_007_872
F_LAUNCH = R25 + CAP


def build_markdown() -> str:
    text = draft.BASE_MD.read_text(encoding="utf-8").replace("v6.9", "v6.10")
    text = text.replace(
        "# 实验设计与执行计划 v6.10：指定执行版——从机制验证到确认性试验",
        "# 实验设计与执行计划 v6.10：100GB分阶段执行版",
    )
    text = text.replace(
        text.splitlines()[2],
        "> **状态：STAGED-100GB-SPECIFIED / REMOTE-RUN-BLOCKED。** 本版继承v6.9统计设计，新增100GB硬配额、168/120-bundle平衡超块、双归档恢复门和禁止effect peeking协议。当前`G0_RESOURCE=FAIL / G0_STAGED=FAIL`，仍只允许本地开发与非晋级dry-run。",
        1,
    )
    text = text.replace(
        text.splitlines()[2],
        text.splitlines()[2]
        + "\n\n> **交付格式规则：** 论文正文继续以DOCX为正式稿；本实验计划及其门禁、运行记录和复核报告以MD/JSON/CSV为权威执行包。DOCX仅为可选阅读副本，不参与实验启动、版本冻结或总体验收。",
        1,
    )
    text = text.replace("MMEAllocation-v6.10.csv", "MMEAllocation-v6.10-100GBStaged.csv")
    start = text.index("## 8 当前服务器资源门")
    end = text.index("## 9 RACI 与不可兼任约束")
    text = text[:start] + SECTION.read_text(encoding="utf-8").rstrip() + "\n\n" + text[end:]
    replacements = {
        "| W3–4 | 容器/UID/ACL、candidate只读、负向探针、资源微基准与新容量计划 | G0决策 |":
            "| W3–4 | 容器/UID/ACL、100GB quota、P99 superblock微基准、双归档与全量restore drill | G0/G0-STAGED决策 |",
        "| W12 | 冻结MME margins、模板/feasibility、Williams分配；VERIFY加密密封 | G3a |":
            "| W12 | 冻结MME margins、模板/feasibility、Williams、execution batch与storage superblock；VERIFY密封 | G3a |",
        "| W13 | SCREEN后锁定实现；按预注册规则处理实现缺陷，不得挑模板 | G3b-SCREEN |":
            "| W13 | 按100GB stages完成SCREEN；每段双归档/恢复后才purge；672完成前不看arm差异 | G3b-SCREEN |",
        "| W14 | 一次性VERIFY、独立统计裁决、边界曲线、MME GO/NO-GO | G3b/c |":
            "| W14 | 按预密封100GB stages完成VERIFY；1,680全部锁定后一次独立裁决 | G3b/c |",
        "最低工件：本计划MD/DOCX、`ExperimentExecutionPlan-v6.10.json`、`MMETemplateMatrix-v6.10.csv`、`MMEAllocation-v6.10-100GBStaged.csv`及SHA；":
            "最低工件：权威执行稿为本计划MD；DOCX仅为可选阅读副本，不是启动或验收门禁。其余工件为`ExperimentExecutionPlan-v6.10.json`、`MMETemplateMatrix-v6.10.csv`、`MMEAllocation-v6.10-100GBStaged.csv`、`StorageStagePlan-v6.10.csv`、`StorageStageManifest-v6.10.schema.json`及SHA；",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.rstrip() + "\n"


def stage_row(phase: str, sb_id: str, kind: str, units: int | str, batches: int | str,
              methods: int | str, evaluations: int | str, provisional: str, note: str) -> dict[str, object]:
    return {
        "phase": phase,
        "balance_superblock_id": sb_id,
        "unit_kind": kind,
        "design_units": units,
        "execution_batches": batches,
        "method_count": methods,
        "method_evaluations": evaluations,
        "provisional_stage_bin_legacy_point": provisional,
        "actual_stage_bin": "PENDING_SHK001_P99_BINPACK",
        "stage_cap_bytes": CAP,
        "committed_budget_bytes": COMMITTED,
        "scratch_budget_bytes": SCRATCH,
        "recovery_budget_bytes": RECOVERY,
        "manifest_reserve_bytes": MANIFEST,
        "archive_uri_a": "PENDING_ARCHIVE_URI_A",
        "archive_uri_b": "PENDING_ARCHIVE_URI_B",
        "effect_look_allowed": False,
        "note": note,
    }


def mme_superblocks(rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    groups: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[(row["phase"], (int(row["execution_batch"]) - 1) // 6 + 1)].append(row)
    allocations: list[dict[str, object]] = []
    plan: list[dict[str, object]] = []
    for (phase, index), members in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1])):
        sb_id = f"{phase}-SB-{index:02d}"
        strata = Counter(row["stratum"] for row in members)
        sequences = Counter(row["method_sequence_id"] for row in members)
        templates = Counter(row["template_id"] for row in members)
        assert len(members) == 168
        assert len(strata) == 24 and set(strata.values()) == {7}
        assert len(sequences) == 14 and set(sequences.values()) == {12}
        assert set(templates.values()) == ({2} if phase == "SCREEN" else {6})
        provisional = "SCREEN-STAGE-01" if phase == "SCREEN" else ("VERIFY-STAGE-01" if index <= 5 else "VERIFY-STAGE-02")
        for row in members:
            allocations.append({
                **row,
                "balance_superblock_id": sb_id,
                "provisional_stage_bin_legacy_point": provisional,
                "actual_stage_bin": "PENDING_SHK001_P99_BINPACK",
                "stage_cap_bytes": CAP,
                "archive_uri_a": "PENDING_ARCHIVE_URI_A",
                "archive_uri_b": "PENDING_ARCHIVE_URI_B",
                "effect_look_allowed": False,
            })
        plan.append(stage_row(
            f"MME_{phase}", sb_id, "SEVEN_METHOD_BALANCE_SUPERBLOCK", 168, 6, 7, 1176,
            provisional,
            f"24 strata each 7; W7-01..14 each 12; templates each {'2' if phase == 'SCREEN' else '6'}",
        ))
    assert Counter(row["phase"] for row in plan) == Counter({"MME_SCREEN": 4, "MME_VERIFY": 10})
    return allocations, plan


def add_other_superblocks(plan: list[dict[str, object]]) -> None:
    for implementation in ["MAIN", "REFERENCE"]:
        for index in range(1, 11):
            plan.append(stage_row("PHASE0", f"P0-{implementation}-RANDOM-{index:02d}", "TRACE_BLOCK", 5000, "NA", 1, 5000, "PENDING", "qualification traces; not statistical n"))
        for index in range(1, 5):
            plan.append(stage_row("PHASE0", f"P0-{implementation}-CRASH-{index:02d}", "CRASH_TRACE_BLOCK", 250, "NA", 1, 250, "PENDING", "crash/restart/CAS qualification"))
    for index in range(1, 5):
        plan.append(stage_row("D_SELECT", f"DSEL-SB-{index:02d}", "SEVEN_METHOD_BALANCE_SUPERBLOCK", 168, 7, 7, 1176, "DSELECT-STAGE-01", "24 strata x 7 selection batches; preferred full closure"))
    for phase, count, provisional in [
        ("PILOT_W1", 6, "PILOT-W1-STAGE-01"),
        ("PILOT_W2", 6, "PILOT-W2-STAGE-01"),
        ("PILOT_W3", 4, "PILOT-W3-STAGE-01"),
        ("PILOT_HELDOUT", 4, "PILOT-HO-STAGE-01"),
    ]:
        for index in range(1, count + 1):
            plan.append(stage_row(phase, f"{phase}-SB-{index:02d}", "FIVE_METHOD_BALANCE_SUPERBLOCK", 120, 5, 5, 600, provisional, "24 strata each 5; ten Williams sequences balanced"))
    plan.append(stage_row(
        "CONFIRMATORY",
        "CONFIRM-AGGREGATE-PENDING",
        "CONFIRMATORY_AGGREGATE_PLACEHOLDER",
        "FINAL_N",
        "FINAL_N/24",
        5,
        "FINAL_N*5",
        "PENDING_POWER_CONFIRM",
        "expand into FINAL_N/120 five-method superblock rows only after joint power-confirm",
    ))
    plan.append(stage_row("EXTERNAL", "EXTERNAL-SB-PENDING", "FROZEN_INTERFACE_BLOCK", "PENDING", "PENDING", "PENDING", "PENDING", "PENDING", "independent simulator/shadow/HIL"))


def manifest_schema() -> dict[str, object]:
    archive = {
        "type": "object",
        "required": ["uri", "immutable", "off_volume_or_host", "hash_verified", "byte_count_verified"],
        "properties": {
            "uri": {"type": "string", "minLength": 1},
            "immutable": {"const": True},
            "off_volume_or_host": {"type": "boolean"},
            "hash_verified": {"const": True},
            "byte_count_verified": {"const": True},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "StorageStageManifest-v6.10.schema.json",
        "title": "StorageStageManifest v6.10",
        "type": "object",
        "additionalProperties": False,
        "required": ["stage_id", "phase", "state", "balance_superblock_ids", "used_bytes", "effect_look_performed", "file_manifest_sha256", "merkle_root", "archive_a", "archive_b", "restore"],
        "properties": {
            "stage_id": {"type": "string", "minLength": 1},
            "phase": {"type": "string", "minLength": 1},
            "state": {"enum": ["PLANNED", "RUNNING", "PAUSED_SAFE", "SEALED_LOCAL", "ARCHIVED_A", "ARCHIVED_B", "RESTORE_VERIFIED", "PURGE_AUTHORIZED", "PURGED", "RECONCILED", "QUARANTINED", "FAILED"]},
            "balance_superblock_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "stage_cap_bytes": {"const": CAP},
            "committed_budget_bytes": {"const": COMMITTED},
            "scratch_budget_bytes": {"const": SCRATCH},
            "recovery_budget_bytes": {"const": RECOVERY},
            "manifest_reserve_bytes": {"const": MANIFEST},
            "used_bytes": {"type": "integer", "minimum": 0, "maximum": CAP},
            "effect_look_performed": {"const": False},
            "file_manifest_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "merkle_root": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "archive_a": archive,
            "archive_b": archive,
            "restore": {
                "type": "object",
                "required": ["full_stream_hash_mismatches", "missing_files", "unexpected_files", "strata_replay_pass", "purge_authorized"],
                "properties": {
                    "full_stream_hash_mismatches": {"const": 0},
                    "missing_files": {"const": 0},
                    "unexpected_files": {"const": 0},
                    "strata_replay_pass": {"const": True},
                    "purge_authorized": {"type": "boolean"},
                },
            },
        },
    }


def main() -> None:
    MD_OUT.write_text(build_markdown(), encoding="utf-8")
    templates = [{**row, "plan_version": "v6.10", "storage_policy": "100GB_STAGED"} for row in draft.read_csv(draft.BASE_TEMPLATE)]
    draft.write_csv(TEMPLATE_OUT, templates)
    base_allocation = draft.read_csv(draft.BASE_ALLOCATION)
    for row in base_allocation:
        if row.get("r_alg") == "PENDING_DOMAIN_SIGNOFF":
            row["r_alg"] = "PENDING_G3A_PREREGISTRATION"
    allocation, stages = mme_superblocks(base_allocation)
    draft.write_csv(ALLOCATION_OUT, allocation)
    add_other_superblocks(stages)
    draft.write_csv(STAGE_PLAN_OUT, stages)
    SCHEMA_OUT.write_text(json.dumps(manifest_schema(), ensure_ascii=False, indent=2), encoding="utf-8")

    contract = json.loads(draft.BASE_JSON.read_text(encoding="utf-8"))
    contract.update({
        "schema": "experiment-execution-plan-v6.10-staged-1.0",
        "status": "STAGED_100GB_SPECIFIED_REMOTE_BLOCKED",
        "authoritative_generator": Path(__file__).name,
        "authoritative_artifact": MD_OUT.name,
        "delivery_format_policy": {
            "paper_body": "DOCX_FORMAL_MANUSCRIPT",
            "experiment_plan": "MARKDOWN_AUTHORITATIVE",
            "machine_readable_contracts": ["JSON", "CSV"],
            "docx_derivative_required": False,
            "docx_layout_gate_required": False,
        },
    })
    contract["storage_execution"] = {
        "unit": "decimal_bytes",
        "stage_cap_bytes": CAP,
        "subbudgets_bytes": {"committed": COMMITTED, "scratch_partial_retry": SCRATCH, "recovery_quarantine": RECOVERY, "manifests_checksums_reserve": MANIFEST},
        "units": {
            "storage_stage": "operational_not_n",
            "execution_batch": {"mme": 28, "d_select": 24, "pilot_confirm": 24},
            "balance_superblock": {
                "seven_methods": 168,
                "five_methods": 120,
                "mme_batches_per_superblock": 6,
                "d_select_batches_per_superblock": 7,
                "pilot_confirm_batches_per_superblock": 5,
            },
        },
        "fallback": "whole 28/24-bundle batches only; MME 6, D_select 7, or pilot-confirm 5 consecutive stages close a superblock; no interim analysis",
        "launch_checks": ["U_stage+B_next_p99<=100e9", "U_committed+B_next_p99<=80e9", "F_now-B_next_p99-B_unflushed>=R25", "quota_or_external_drift_guard"],
        "state_machine": ["PLANNED", "RUNNING", "SEALED_LOCAL", "ARCHIVED_A", "ARCHIVED_B", "RESTORE_VERIFIED", "PURGE_AUTHORIZED", "PURGED", "RECONCILED"],
        "archive_uri_a": "PENDING_ARCHIVE_URI_A",
        "archive_uri_b": "PENDING_ARCHIVE_URI_B",
        "effect_look_allowed_between_stages": False,
        "actual_stage_bins": "PENDING_SHK001_P99_BINPACK",
        "superblock_counts": {"phase0_blocks": 28, "mme_screen": 4, "mme_verify": 10, "d_select": 4, "pilot_wave1": 6, "pilot_wave2": 6, "pilot_wave3": 4, "pilot_heldout": 4, "confirmatory": "FINAL_N/120"},
        "legacy_planning_point_only": {"screen_bytes": 55_453_440_000, "verify_stage_bytes": [69_316_800_000, 69_316_800_000], "d_select_bytes": 55_453_440_000, "pilot_stage_bytes": [58_896_000_000, 58_896_000_000, 39_264_000_000, 39_264_000_000], "preconfirm_raw_bytes": 445_860_480_000, "two_archive_capacity_with_5pct_each_bytes": 936_307_008_000},
    }
    contract["resource_gates"].update({
        "current_G0_STAGED": "FAIL",
        "total_volume_bytes": TOTAL_VOLUME,
        "reserve_25pct_bytes": R25,
        "current_below_reserve_bytes": R25 - CURRENT_FREE,
        "target80_same_volume_start_free_bytes": R25 + COMMITTED,
        "target80_additional_free_bytes": R25 + COMMITTED - CURRENT_FREE,
        "hard100_same_volume_start_free_bytes": F_LAUNCH,
        "hard100_additional_free_bytes": F_LAUNCH - CURRENT_FREE,
        "dedicated_stage_volume_recommended_bytes": 150 * GB,
        "dedicated_stage_quota_required_bytes": CAP,
        "archive_a_signed": False,
        "archive_b_signed": False,
    })
    contract["files"] = {
        "markdown": {"name": MD_OUT.name, "sha256": draft.sha256(MD_OUT)},
        "template_matrix": {"name": TEMPLATE_OUT.name, "rows": len(templates), "sha256": draft.sha256(TEMPLATE_OUT)},
        "allocation": {"name": ALLOCATION_OUT.name, "rows": len(allocation), "sha256": draft.sha256(ALLOCATION_OUT)},
        "storage_stage_plan": {"name": STAGE_PLAN_OUT.name, "rows": len(stages), "sha256": draft.sha256(STAGE_PLAN_OUT)},
        "storage_manifest_schema": {"name": SCHEMA_OUT.name, "sha256": draft.sha256(SCHEMA_OUT)},
    }
    JSON_OUT.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")

    assert len(allocation) == 2352
    assert len(stages) == 68
    assert COMMITTED + SCRATCH + RECOVERY + MANIFEST == CAP
    print(json.dumps({"markdown": str(MD_OUT), "json": str(JSON_OUT), "templates": str(TEMPLATE_OUT), "allocation": str(ALLOCATION_OUT), "storage_stage_plan": str(STAGE_PLAN_OUT), "manifest_schema": str(SCHEMA_OUT), "allocation_rows": len(allocation), "stage_plan_rows": len(stages), "launch_free_bytes": F_LAUNCH, "additional_free_bytes": F_LAUNCH - CURRENT_FREE}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
