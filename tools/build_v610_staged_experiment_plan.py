from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BASE_MD = ROOT / "实验设计与执行计划v6.9-指定执行版-机制验证到确认性试验.md"
BASE_JSON = ROOT / "ExperimentExecutionPlan-v6.9.json"
BASE_TEMPLATE = ROOT / "MMETemplateMatrix-v6.9.csv"
BASE_ALLOCATION = ROOT / "MMEAllocation-v6.9.csv"

MD_OUT = ROOT / "实验设计与执行计划v6.10-100GB分阶段执行版.md"
JSON_OUT = ROOT / "ExperimentExecutionPlan-v6.10.json"
TEMPLATE_OUT = ROOT / "MMETemplateMatrix-v6.10.csv"
ALLOCATION_OUT = ROOT / "MMEAllocation-v6.10-100GBStaged.csv"
STAGE_PLAN_OUT = ROOT / "StorageStageCyclePlan-v6.10.csv"
SCHEMA_OUT = ROOT / "StorageStageManifest-v6.10.schema.json"

GB = 1_000_000_000
STAGE_CAP = 100 * GB
RETAINED_TARGET = 80 * GB
SCRATCH_BUDGET = 10 * GB
EMERGENCY_RESERVE = 10 * GB
TOTAL_VOLUME = 943_412_031_488
CURRENT_FREE = 217_182_134_272
RESERVE_25 = 235_853_007_872
TARGET_START_FREE = RESERVE_25 + RETAINED_TARGET
HARD_START_FREE = RESERVE_25 + STAGE_CAP


STORAGE_SECTION = r"""## 8 100GB 分阶段存储与当前服务器资源门

### 8.1 100GB 的口径

每次 storage stage 的**本地活动工作集硬上限**固定为十进制 `100,000,000,000 bytes`，不是100GiB，也不是全项目总归档容量。每阶段预算如下：

| 分区 | 上限 | 内容 |
| --- | ---: | --- |
| 永久/归档候选 retained payload | 60GB | 结果、truth/action labels、ledger/checkpoint、失败记录 |
| lossless replay capsule | 15GB | 事件流、seed tree、必要重放输入 |
| manifest/index/resource logs | 5GB | SHA/Merkle、容器/环境、计数、资源与ACL审计 |
| scratch/compression/temp | 10GB | 可重建临时文件；阶段关闭前清理 |
| emergency reserve | 10GB | 防止单cycle P99低估与文件系统元数据增长 |
| **合计** | **100GB** | retained目标≤80GB；硬上限100GB |

100GB只降低服务器的**峰值本地占用**。如果完整原始工件需要长期保留，总归档容量并不会因分阶段自动降为100GB；必须有独立归档端，或证明被清理数据可由冻结seed/code/container逐字节再生。

### 8.2 设计兼容的最小存储周期

storage stage 是运维分片，不是统计 interim。阶段边界只能按预签字节规则触发，不得按A−baseline效果、p值、赢家或趋势触发。

- 七方法阶段以一套14条Williams序列为最小cycle：14 bundles、98 method evaluations；
- 五方法阶段以一套10条Williams序列为最小cycle：10 bundles、50 evaluations；
- 同一bundle的全部方法必须在同一cycle完成；不得把方法拆到不同stage；
- 每个stage只装入整数个完整cycle。`k_stage=floor((80GB-fixed_overhead_q99)/q99_cycle_bytes)`；若 `k_stage<1`，G0-STAGED FAIL，必须降低无损日志体积或更换存储，不能拆坏cycle；
- `StorageStageCyclePlan-v6.10.csv` 冻结cycle；实际 `stage_bin` 仅在SHK-001得到q99后由确定性bin-packing生成并签署。

指定cycle总量：MME-SCREEN 48、MME-VERIFY 120、D_select 48；pilot Wave1/2/3/heldout分别72/72/48/48。确认性cycle数为最终 `n/10`，只能在joint power-confirm后生成。

### 8.3 阶段状态机与写入门

每stage严格经过：

`PREPARED → RUNNING → SEALED → ARCHIVED → RESTORE_VERIFIED → PURGE_ALLOWED`。

新cycle仅在以下条件同时满足时启动：

`current_usage + q99(next_cycle) + 10,000,000,000 <= 100,000,000,000`。

retained达到80GB或下一完整cycle不满足公式时，在bundle边界关闭stage。90GB后禁止新cycle；达到/预测达到100GB立即SAFE_HALT并保留失败账本。不得通过删除当前stage的truth、ledger、失败运行或唯一副本为后续cycle腾空间。

### 8.4 归档、恢复验证与清理授权

每个sealed stage必须生成 `StorageStageManifest`、文件清单、逐文件SHA-256、Merkle root、bundle/template/arm计数、seed/container/scorer digest、失败账本和资源日志。归档端当前标记为 `PENDING_ARCHIVE_URI`；未签署归档端不得启动正式stage。

清理本地retained payload前必须：

1. 完整上传到独立归档端；
2. 服务端与归档端SHA/Merkle一致；
3. manifest行数、bundle数、method数和失败数一致；
4. 完成一次只读恢复并重放预签样本；首stage全量restore drill，之后至少每10 stages一次；
5. 对不可再生唯一数据保有两个独立验证副本，或一个immutable完整归档加一个本地最小reproducibility capsule；
6. DS与STAT双签 `PURGE_ALLOWED=true`。

只允许清理scratch、cache、重复中间矩阵和已通过上述门的本地归档副本。永久保留：所有stage manifests/hash roots、Seed/Allocation/Test manifests、统计结果表、失败/排除账本、容器/SBOM/digest、ActionTruth规则、归档证明和恢复日志。

### 8.5 当前磁盘仍未解锁

当前总卷943,412,031,488 bytes，25%保留线235,853,007,872 bytes；当前free=217,182,134,272 bytes，已低于保留线18,670,873,600 bytes。

- 若在同一卷执行80GB retained目标，启动free必须≥315,853,007,872 bytes，当前还差98,670,873,600 bytes；
- 若允许stage触及100GB硬上限，启动free必须≥335,853,007,872 bytes，当前还差118,670,873,600 bytes（118.671GB，约110.52GiB）；
- 若使用独立stage卷，建议有效容量≥150GB，并建立独占100GB quota/reservation；同时仍须有独立归档端；
- 还须把其他用户/服务在stage期间的写入漂移纳入预签guard。没有quota时，仅达到上述free阈值也不构成充分条件。

因此当前仍为 `G0_RESOURCE=FAIL / G0_STAGED=FAIL`。100GB分阶段方案减少未来峰值，但不会绕过现有空间不足、GPU共享、ACL隔离和归档端缺失。

### 8.6 允许的阶段QC与禁止的窥视

阶段间只允许查看：schema/hash/计数完整性、invariant、在线-重放一致性、资源用量、磁盘预测误差、基础设施失败分类和restore结果。禁止查看或计算匿名arm间差异、A−baseline符号、效应区间、p值、赢家、joint gate或按结果改变剩余stage、模板、margin、层权和方法。

若stage中途发生容量/基础设施失败，保留整个attempt；未完整完成全部方法的bundle不进入分析。仅可按冻结规则在新stage用同一seed重跑**整个bundle**，并保留原失败attempt的关联ID。统计分析仍等待完整phase锁定，并包含storage_stage_id与execution_batch项；bootstrap继续按execution batch整簇抽样。
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_markdown() -> str:
    text = BASE_MD.read_text(encoding="utf-8").replace("v6.9", "v6.10")
    text = text.replace(
        "# 实验设计与执行计划 v6.10：指定执行版——从机制验证到确认性试验",
        "# 实验设计与执行计划 v6.10：100GB分阶段执行版",
    )
    old_status = text.splitlines()[2]
    new_status = (
        "> **状态：STAGED-100GB-SPECIFIED / REMOTE-RUN-BLOCKED。** 本版继承v6.9的统计设计，"
        "新增每次storage stage十进制100GB硬上限、设计兼容cycle、归档恢复门和禁止effect peeking协议。"
        "当前`G0_RESOURCE=FAIL / G0_STAGED=FAIL`，因此仍只允许本地开发与非晋级dry-run。"
    )
    text = text.replace(old_status, new_status, 1)
    start = text.index("## 8 当前服务器资源门")
    end = text.index("## 9 RACI 与不可兼任约束")
    text = text[:start] + STORAGE_SECTION.rstrip() + "\n\n" + text[end:]
    text = text.replace(
        "| W3–4 | 容器/UID/ACL、candidate只读、负向探针、资源微基准与新容量计划 | G0决策 |",
        "| W3–4 | 容器/UID/ACL、100GB stage微基准、q99 cycle估计、归档端与restore drill | G0/G0-STAGED决策 |",
    )
    text = text.replace(
        "| W12 | 冻结MME margins、模板/feasibility、Williams分配；VERIFY加密密封 | G3a |",
        "| W12 | 冻结MME margins、模板/feasibility、Williams与storage-cycle分配；VERIFY加密密封 | G3a |",
    )
    text = text.replace(
        "| W13 | SCREEN后锁定实现；按预注册规则处理实现缺陷，不得挑模板 | G3b-SCREEN |",
        "| W13 | 按100GB stages执行SCREEN；每stage归档/恢复后才释放本地空间；phase结束前不看arm差异 | G3b-SCREEN |",
    )
    text = text.replace(
        "| W14 | 一次性VERIFY、独立统计裁决、边界曲线、MME GO/NO-GO | G3b/c |",
        "| W14 | 按预密封100GB stages完成VERIFY；全phase锁定后一次独立裁决 | G3b/c |",
    )
    text = text.replace(
        "最低工件：本计划MD/DOCX、`ExperimentExecutionPlan-v6.10.json`、`MMETemplateMatrix-v6.10.csv`、`MMEAllocation-v6.10.csv`及SHA；",
        "最低工件：本计划MD/DOCX、`ExperimentExecutionPlan-v6.10.json`、`MMETemplateMatrix-v6.10.csv`、`MMEAllocation-v6.10-100GBStaged.csv`、`StorageStageCyclePlan-v6.10.csv`、`StorageStageManifest-v6.10.schema.json`及SHA；",
    )
    return text.rstrip() + "\n"


def add_storage_cycles_to_allocation(rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["phase"], row["execution_batch"])].append(row)

    staged_rows: list[dict[str, object]] = []
    cycle_rows: list[dict[str, object]] = []
    phase_cycle_counter: Counter[str] = Counter()
    for (phase, batch), batch_rows in sorted(grouped.items(), key=lambda item: (item[0][0], int(item[0][1]))):
        by_sequence: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in sorted(batch_rows, key=lambda item: int(item["run_order_within_batch"])):
            by_sequence[row["method_sequence_id"]].append(row)
        assert len(by_sequence) == 14 and {len(items) for items in by_sequence.values()} == {2}
        for occurrence in [0, 1]:
            phase_cycle_counter[phase] += 1
            cycle_id = f"{phase}-W7C-{phase_cycle_counter[phase]:03d}"
            members = [by_sequence[f"W7-{sequence:02d}"][occurrence] for sequence in range(1, 15)]
            for member_order, row in enumerate(members, start=1):
                staged_rows.append(
                    {
                        **row,
                        "storage_cycle_id": cycle_id,
                        "storage_cycle_member_order": member_order,
                        "storage_stage_bin": "PENDING_Q99_BINPACK",
                        "stage_cap_bytes": STAGE_CAP,
                        "retained_target_bytes": RETAINED_TARGET,
                        "archive_uri": "PENDING_ARCHIVE_URI",
                        "effect_look_allowed": False,
                    }
                )
            cycle_rows.append(
                stage_cycle_row(
                    phase=f"MME_{phase}",
                    cycle_id=cycle_id,
                    cycle_kind="WILLIAMS_14",
                    design_units=14,
                    method_count=7,
                    evaluations=98,
                    note=f"execution_batch={batch}; one occurrence of W7-01..W7-14",
                )
            )
    assert phase_cycle_counter == Counter({"SCREEN": 48, "VERIFY": 120})
    return staged_rows, cycle_rows


def stage_cycle_row(
    phase: str,
    cycle_id: str,
    cycle_kind: str,
    design_units: int | str,
    method_count: int | str,
    evaluations: int | str,
    note: str,
) -> dict[str, object]:
    return {
        "phase": phase,
        "storage_cycle_id": cycle_id,
        "cycle_kind": cycle_kind,
        "design_units": design_units,
        "method_count": method_count,
        "method_evaluations": evaluations,
        "storage_stage_bin": "PENDING_Q99_BINPACK",
        "stage_cap_bytes": STAGE_CAP,
        "retained_target_bytes": RETAINED_TARGET,
        "scratch_budget_bytes": SCRATCH_BUDGET,
        "emergency_reserve_bytes": EMERGENCY_RESERVE,
        "archive_uri": "PENDING_ARCHIVE_URI",
        "archive_restore_required": True,
        "effect_look_allowed": False,
        "note": note,
    }


def add_non_mme_cycles(cycles: list[dict[str, object]]) -> None:
    for implementation in ["MAIN", "REFERENCE"]:
        for idx in range(1, 11):
            cycles.append(stage_cycle_row("PHASE0", f"P0-{implementation}-RANDOM-{idx:02d}", "TRACE_BLOCK", 5000, 1, 5000, "qualification traces; not statistical n"))
        for idx in range(1, 5):
            cycles.append(stage_cycle_row("PHASE0", f"P0-{implementation}-CRASH-{idx:02d}", "CRASH_TRACE_BLOCK", 250, 1, 250, "crash/restart/CAS qualification traces"))
    for idx in range(1, 49):
        cycles.append(stage_cycle_row("D_SELECT", f"DSEL-W7C-{idx:03d}", "WILLIAMS_14", 14, 7, 98, "G* selection; whole-phase analysis only"))
    pilot_specs = [("PILOT_W1", 72), ("PILOT_W2", 72), ("PILOT_W3", 48), ("PILOT_HELDOUT", 48)]
    for phase, count in pilot_specs:
        for idx in range(1, count + 1):
            cycles.append(stage_cycle_row(phase, f"{phase}-W5C-{idx:03d}", "WILLIAMS_10", 10, 5, 50, "five-method paired cycle; no effect look"))
    cycles.append(stage_cycle_row("CONFIRMATORY", "CONFIRM-W5C-PENDING", "WILLIAMS_10", "FINAL_N/10_CYCLES", 5, "FINAL_N*5", "generated only after joint power-confirm"))
    cycles.append(stage_cycle_row("EXTERNAL", "EXTERNAL-PENDING", "FROZEN_INTERFACE_BLOCK", "PENDING", "PENDING", "PENDING", "independent simulator/shadow/HIL plan"))


def storage_manifest_schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "StorageStageManifest-v6.10.schema.json",
        "title": "StorageStageManifest v6.10",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "stage_id", "phase", "state", "storage_cycle_ids", "cap_bytes", "used_bytes",
            "effect_look_performed", "file_manifest_sha256", "merkle_root", "archive",
        ],
        "properties": {
            "stage_id": {"type": "string", "minLength": 1},
            "phase": {"type": "string", "minLength": 1},
            "state": {"enum": ["PREPARED", "RUNNING", "SEALED", "ARCHIVED", "RESTORE_VERIFIED", "PURGE_ALLOWED", "FAILED"]},
            "storage_cycle_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "cap_bytes": {"const": STAGE_CAP},
            "retained_target_bytes": {"const": RETAINED_TARGET},
            "used_bytes": {"type": "integer", "minimum": 0, "maximum": STAGE_CAP},
            "effect_look_performed": {"const": False},
            "file_manifest_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "merkle_root": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "bundle_counts": {"type": "object"},
            "failure_counts": {"type": "object"},
            "seed_manifest_sha256": {"type": "string"},
            "container_digests": {"type": "array", "items": {"type": "string"}},
            "archive": {
                "type": "object",
                "additionalProperties": False,
                "required": ["uri", "copy_count", "hash_verified", "restore_verified", "purge_authorized"],
                "properties": {
                    "uri": {"type": "string", "minLength": 1},
                    "copy_count": {"type": "integer", "minimum": 1},
                    "hash_verified": {"type": "boolean"},
                    "restore_verified": {"type": "boolean"},
                    "purge_authorized": {"type": "boolean"},
                },
            },
        },
    }


def main() -> None:
    for path in [BASE_MD, BASE_JSON, BASE_TEMPLATE, BASE_ALLOCATION]:
        if not path.exists():
            raise FileNotFoundError(path)

    MD_OUT.write_text(build_markdown(), encoding="utf-8")

    template_rows = read_csv(BASE_TEMPLATE)
    staged_templates = [{**row, "plan_version": "v6.10", "storage_policy": "100GB_STAGED"} for row in template_rows]
    write_csv(TEMPLATE_OUT, staged_templates)

    staged_allocation, cycle_rows = add_storage_cycles_to_allocation(read_csv(BASE_ALLOCATION))
    write_csv(ALLOCATION_OUT, staged_allocation)
    add_non_mme_cycles(cycle_rows)
    write_csv(STAGE_PLAN_OUT, cycle_rows)

    schema = storage_manifest_schema()
    SCHEMA_OUT.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")

    contract = json.loads(BASE_JSON.read_text(encoding="utf-8"))
    contract.update(
        {
            "schema": "experiment-execution-plan-v6.10-staged-1.0",
            "status": "STAGED_100GB_SPECIFIED_REMOTE_BLOCKED",
            "authoritative_generator": Path(__file__).name,
            "storage_execution": {
                "unit": "decimal_bytes",
                "stage_cap_bytes": STAGE_CAP,
                "retained_target_bytes": RETAINED_TARGET,
                "retained_breakdown_bytes": {
                    "authoritative_payload": 60 * GB,
                    "lossless_replay_capsule": 15 * GB,
                    "manifests_indices_resource_logs": 5 * GB,
                },
                "scratch_budget_bytes": SCRATCH_BUDGET,
                "emergency_reserve_bytes": EMERGENCY_RESERVE,
                "cycle_start_formula": "current_usage + q99_next_cycle + 10000000000 <= 100000000000",
                "soft_close_retained_bytes": RETAINED_TARGET,
                "no_new_cycle_bytes": 90 * GB,
                "state_machine": ["PREPARED", "RUNNING", "SEALED", "ARCHIVED", "RESTORE_VERIFIED", "PURGE_ALLOWED"],
                "archive_uri": "PENDING_ARCHIVE_URI",
                "archive_required_before_formal_run": True,
                "effect_look_allowed_between_stages": False,
                "actual_stage_bins": "PENDING_SHK001_Q99_DETERMINISTIC_BINPACK",
                "minimum_cycles": {"seven_methods": "14 bundles", "five_methods": "10 bundles"},
                "cycle_counts": {
                    "phase0_blocks": 28,
                    "mme_screen": 48,
                    "mme_verify": 120,
                    "d_select": 48,
                    "pilot_wave1": 72,
                    "pilot_wave2": 72,
                    "pilot_wave3": 48,
                    "pilot_heldout": 48,
                    "confirmatory": "FINAL_N/10",
                },
                "purge_requires": [
                    "archive_hash_match", "manifest_count_match", "restore_verified",
                    "two_copies_or_one_immutable_plus_local_repro_capsule", "DS_STAT_dual_signoff",
                ],
            },
        }
    )
    contract["resource_gates"].update(
        {
            "current_G0_STAGED": "FAIL",
            "total_volume_bytes": TOTAL_VOLUME,
            "reserve_25pct_bytes": RESERVE_25,
            "target80_same_volume_start_free_bytes": TARGET_START_FREE,
            "target80_additional_free_bytes": TARGET_START_FREE - CURRENT_FREE,
            "hard100_same_volume_start_free_bytes": HARD_START_FREE,
            "hard100_additional_free_bytes": HARD_START_FREE - CURRENT_FREE,
            "dedicated_stage_volume_recommended_bytes": 150 * GB,
            "dedicated_stage_quota_required_bytes": STAGE_CAP,
            "archive_uri_signed": False,
        }
    )
    contract["files"] = {
        "markdown": {"name": MD_OUT.name, "sha256": sha256(MD_OUT)},
        "template_matrix": {"name": TEMPLATE_OUT.name, "rows": len(staged_templates), "sha256": sha256(TEMPLATE_OUT)},
        "allocation": {"name": ALLOCATION_OUT.name, "rows": len(staged_allocation), "sha256": sha256(ALLOCATION_OUT)},
        "storage_cycle_plan": {"name": STAGE_PLAN_OUT.name, "rows": len(cycle_rows), "sha256": sha256(STAGE_PLAN_OUT)},
        "storage_manifest_schema": {"name": SCHEMA_OUT.name, "sha256": sha256(SCHEMA_OUT)},
    }
    JSON_OUT.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")

    assert len(staged_allocation) == 2352
    assert len(cycle_rows) == 486
    assert STAGE_CAP == RETAINED_TARGET + SCRATCH_BUDGET + EMERGENCY_RESERVE
    print(
        json.dumps(
            {
                "markdown": str(MD_OUT),
                "json": str(JSON_OUT),
                "templates": str(TEMPLATE_OUT),
                "allocation": str(ALLOCATION_OUT),
                "storage_cycle_plan": str(STAGE_PLAN_OUT),
                "manifest_schema": str(SCHEMA_OUT),
                "allocation_rows": len(staged_allocation),
                "storage_cycle_rows": len(cycle_rows),
                "hard_start_free_bytes": HARD_START_FREE,
                "hard_additional_free_bytes": HARD_START_FREE - CURRENT_FREE,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
