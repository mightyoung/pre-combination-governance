from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MD = ROOT / "实验资源协同与多阶段执行计划v6.11-本机与11.16服务器.md"
JSON_OUT = ROOT / "ResourceAwareExecutionPlan-v6.11.json"
CSV_OUT = ROOT / "ResourceStageMatrix-v6.11.csv"
GB = 1_000_000_000

REMOTE = {
    "snapshot_time": "2026-07-15T12:50:07+08:00",
    "host": "192.168.11.16:10022",
    "hostname": "r4900g3-UniServer-R4900-G3",
    "cpu": "2 x Intel Xeon Silver 4214",
    "physical_cores": 24,
    "logical_cpus": 48,
    "ram_total_bytes": 134_788_022_272,
    "ram_available_bytes": 84_578_299_904,
    "gpu": "NVIDIA L20",
    "gpu_total_mib": 46_068,
    "gpu_used_mib": 22_403,
    "gpu_free_mib": 23_192,
    "gpu_existing_largest_process_mib": 20_880,
    "root_total_bytes": 943_412_031_488,
    "root_free_bytes": 216_635_019_264,
    "experiment_root": "/home/r4900g3/yhh/provenance-fusion",
    "experiment_root_bytes": 337_321_984,
    "docker_containers_running": 40,
}
LOCAL = {
    "snapshot_time": "2026-07-15",
    "hostname": "YHHWORKPC",
    "cpu": "Intel Core i5-1340P",
    "physical_cores": 12,
    "logical_cpus": 16,
    "ram_total_bytes": 16_890_716_160,
    "ram_free_bytes": 2_563_903_488,
    "gpu": "Intel Iris Xe; no CUDA",
    "c_free_bytes": 10_845_196_288,
    "d_total_bytes": 786_147_831_808,
    "d_free_bytes": 78_749_585_408,
}

HARD_CAP = 100 * GB
MICRO_CAP = 25 * GB
COMMITTED = 20 * GB
SCRATCH = 2_500_000_000
RECOVERY = 1_250_000_000
MANIFEST = 1_250_000_000
REMOTE_RESERVE25 = REMOTE["root_total_bytes"] // 4
REMOTE_DEV_FLOOR = 180 * GB
DRIFT_GUARD = 5 * GB
LOCAL_D_FLOOR = 45 * GB
LOCAL_RESTORE_SCRATCH = 5 * GB
FORMAL_START_MIN = REMOTE_RESERVE25 + MICRO_CAP + DRIFT_GUARD
FORMAL_SHORTFALL = FORMAL_START_MIN - REMOTE["root_free_bytes"]
DEV_START_MIN = REMOTE_DEV_FLOOR + MICRO_CAP + DRIFT_GUARD
DEV_MARGIN = REMOTE["root_free_bytes"] - DEV_START_MIN
LOCAL_RESTORE_MIN = LOCAL_D_FLOOR + MICRO_CAP + LOCAL_RESTORE_SCRATCH
LOCAL_RESTORE_MARGIN = LOCAL["d_free_bytes"] - LOCAL_RESTORE_MIN
HARD100_START_MIN = REMOTE_RESERVE25 + HARD_CAP
HARD100_SHORTFALL = HARD100_START_MIN - REMOTE["root_free_bytes"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bins(byte_count: int | None) -> int | str:
    return math.ceil(byte_count / COMMITTED) if byte_count is not None else "PENDING_SHK001"


def phase(order, name, units, batch_size, batch_count, superblock, legacy, formal, compute, gate):
    return {
        "order": order,
        "phase": name,
        "independent_units": units,
        "execution_batch_bundles": batch_size,
        "execution_batches": batch_count,
        "superblock_rule": superblock,
        "legacy_bytes": "" if legacy is None else legacy,
        "provisional_microstages": bins(legacy) if legacy else ("PENDING_SHK001" if legacy is None else 0),
        "formal": formal,
        "compute": compute,
        "gate": gate,
    }


PHASES = [
    phase(0, "CONTROL_PREFLIGHT", 0, "NA", "NA", "NA", 0, False, "LOCAL control + REMOTE read-only", "allowed"),
    phase(1, "SHK001A_GENERATOR_CANARY", "28 non-promotable bundles", 28, 1, "not inferential; no methods", 100_000_000, False, "REMOTE 4 CPU workers", "development admission"),
    phase(2, "SHK001B_FULL_PANEL_SIZE", "28 bundles x 7 methods", 28, 1, "not inferential; full panel", None, False, "REMOTE after runtime exists", "MethodRegistry and runtime PASS"),
    phase(3, "PHASE0_G1_G2", "2 x (50k random + 1k crash traces)", "5000/250 traces", 28, "qualification only", None, False, "REMOTE CPU + LOCAL audit", "SHK001B and contracts PASS"),
    phase(4, "MME_SCREEN", 672, 28, 24, "6 batches x 4 superblocks", 55_453_440_000, True, "REMOTE 7 methods together", "G0-G3a PASS"),
    phase(5, "MME_VERIFY", 1680, 28, 60, "6 batches x 10 superblocks", 138_633_600_000, True, "REMOTE presealed", "SCREEN locked"),
    phase(6, "D_SELECT", 672, 24, 28, "7 batches x 4 superblocks", 55_453_440_000, True, "REMOTE + LOCAL blinded bootstrap", "MME GO"),
    phase(7, "PILOT_W1", 720, 24, 30, "5 batches x 6 superblocks", 58_896_000_000, True, "REMOTE nuisance only", "G* frozen"),
    phase(8, "PILOT_W2", 720, 24, 30, "5 batches x 6 superblocks", 58_896_000_000, True, "REMOTE nuisance only", "W1 precision"),
    phase(9, "PILOT_W3", 480, 24, 20, "5 batches x 4 superblocks", 39_264_000_000, True, "REMOTE nuisance only", "W2 precision"),
    phase(10, "PILOT_HELDOUT", 480, 24, 20, "5 batches x 4 superblocks", 39_264_000_000, True, "REMOTE kernel validation", "fit precision PASS"),
    phase(11, "CONFIRMATORY", "FINAL_N", 24, "FINAL_N/24", "5 batches; FINAL_N/120 superblocks", None, True, "REMOTE frozen + LOCAL audit", "joint power-confirm"),
]


def write_csv() -> None:
    with CSV_OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PHASES[0]))
        writer.writeheader()
        writer.writerows(PHASES)


def build_markdown() -> str:
    table = "\n".join(
        f"| {p['phase']} | {p['independent_units']} | {p['execution_batches']} | "
        f"{p['provisional_microstages']} | {'是' if p['formal'] else '否'} | {p['gate']} |"
        for p in PHASES
    )
    return f"""# 实验资源协同与多阶段执行计划 v6.11：本机与11.16服务器

> **状态：GENERATOR-CANARY-ALLOWED / FULL-RUNTIME-AND-FORMAL-BLOCKED。** 本文件是v6.10统计计划的资源执行附录，不改变独立单位、随机化、方法面板、superblock、IUT或功效规则。100GB继续作为单阶段硬上限；按当前资源实际采用25GB物理微阶段。

## 0 结论

- 11.16服务器可立即运行SHK001A生成器隔离canary，每个微阶段总占用不得超过25GB。
- 当前仓库canary不执行候选方法；SHK001B完整七方法容量试验与完整G1/G2资格运行必须等待MethodRegistry和事务运行时实现。
- MME、D_select、pilot和confirmatory仍禁止启动：正式微阶段尚缺{FORMAL_SHORTFALL:,} bytes可用空间，且两份外部归档均未配置。
- 本机只承担代码控制、测试、清单、独立复算和单个25GB阶段的滚动恢复缓存，不承担正式计算或永久归档。
- 服务器实测GPU是NVIDIA L20 46,068MiB，不是T4；已有22,403MiB被共享服务占用，不能按独占卡规划。

## 1 实时资源

| 节点 | CPU/RAM | GPU | 存储 | 合理职责 |
| --- | --- | --- | --- | --- |
| 本机YHHWORKPC | i5-1340P，12核16线程；RAM 16.89GB，仅余2.56GB | Iris Xe，无CUDA | C盘余10.85GB；D盘余78.75GB | 控制面、测试、清单、恢复缓存 |
| 11.16服务器 | 双Xeon 4214，24核48线程；RAM 134.79GB，可用84.58GB | L20；余23,192MiB | 根盘943.41GB，余216.64GB；40个容器共盘 | 生成器、方法容器、replay和性能试验 |

SSH主机密钥指纹为 SHA256:eDfwLjrpTces2mQp4d+gKdg2i/4t7k7sLfF/nLtx1oA。指纹变化必须停止连接。

## 2 25GB微阶段预算

| 子预算 | 当前物理微阶段 | 100GB硬上限 |
| --- | ---: | ---: |
| committed evidence | 20GB | 80GB |
| scratch/partial/retry | 2.5GB | 10GB |
| recovery/quarantine | 1.25GB | 5GB |
| manifests/checksum/reserve | 1.25GB | 5GB |
| 合计 | **25GB** | **100GB** |

正式启动要求服务器free至少{FORMAL_START_MIN:,} bytes，当前短缺{FORMAL_SHORTFALL:,} bytes。若坚持100GB活动阶段，则需free至少{HARD100_START_MIN:,} bytes，短缺{HARD100_SHORTFALL:,} bytes。25GB微阶段把待释放空间降低70GB。

非确认性开发采用180GB紧急地板，启动阈值{DEV_START_MIN:,} bytes；当前只多{DEV_MARGIN:,} bytes，必须逐batch准入。本机恢复阈值{LOCAL_RESTORE_MIN:,} bytes，当前只多{LOCAL_RESTORE_MARGIN:,} bytes，因此D盘一次只能恢复一个阶段，C盘禁止实验数据落盘。

## 3 双机资源约束

- 本机默认最多4线程、4GB工作内存；D盘设置25GB恢复区和5GB校验scratch，free不得低于45GB。
- 服务器默认8逻辑CPU，最大12；内存soft 24GiB、hard 32GiB；nice=10、ionice class2/n7。
- GPU默认OFF。预约后只允许1个GPU作业，单进程预算不超过12,000MiB；GPU free低于18,000MiB、Xid、OOM或共享服务异常即暂停。
- 同一bundle的全部方法必须在同一微阶段，顺序继续服从冻结Williams序列。

## 4 多阶段矩阵

| 阶段 | 科学/资格单位 | execution batches | 预计25GB微阶段 | 正式数据 | 启动门 |
| --- | --- | ---: | ---: | --- | --- |
{table}

预计微阶段数仅用v6.10旧容量点除以20GB committed预算计算。SHK-001后必须用q99(batch_bytes)重新bin-pack完整execution batch；禁止拆bundle、拆方法面板或改变随机化。superblock可以跨物理微阶段，但其全部batches完成前不得分析。

## 5 生命周期与归档

物理微阶段状态机：

PLANNED → ADMITTED → RUNNING → SEALED_LOCAL → ARCHIVED_A → ARCHIVED_B → RESTORE_VERIFIED → PURGE_AUTHORIZED → PURGED → RECONCILED

启动必须同时满足：

1. used_stage + q99(next_batch)不超过25GB；
2. committed + q99(next_batch)不超过20GB；
3. 服务器free扣除下一批和5GB外部写入漂移后不低于相应地板；
4. formal阶段两份独立持久归档已签署，至少一份off-host/off-volume且immutable；
5. 本机做全量恢复时D盘free不低于75GB；
6. CPU、RAM、GPU、container digest、candidate hash和ACL负测全部通过。

服务器根盘与Docker共卷，不是归档盘。本机D盘也不是永久Archive A，只是滚动恢复缓存。没有ARCHIVE_A/B时，只能运行带NON_CONFIRMATORY_DO_NOT_PROMOTE标记的可再生开发数据。

阶段边界只允许检查容量、hash、缺失/重复、配额平衡、失败码、资源和双实现一致性；禁止查看效应方向、排名、p值、CI或IUT通过率。

## 6 立即执行顺序

1. 固化本快照和SSH主机指纹；
2. 本机执行测试、schema和manifest校验；
3. 服务器运行SHK001A_GENERATOR_CANARY：28个非晋级bundle、2个noise views、2个arrival views，输出硬停0.1GB；它只测生成器和隔离工件，不执行候选方法；
4. 完成MethodRegistry、A/B0-B5、事务运行时和统一ledger后，运行SHK001B_FULL_PANEL_SIZE，输出硬停5GB，测量完整batch的bytes/time/RAM/VRAM P50/P95/P99；
5. 在SHK001B比较CPU并发4/8/12，选择吞吐提升仍大于等于15%且不扰动共享服务的最低档；
6. 未获得GPU预约时冻结CPU-only路线，不得抢占现有VLLM或ASR服务；
7. 用SHK001B实测值更新ResourceStageMatrix；
8. 只有服务器再释放至少{FORMAL_SHORTFALL:,} bytes且两归档就绪，才签署首个MME_SCREEN formal stage。

## 7 停止条件

- 服务器free预计跌破180GB，或正式阶段跌破25%地板；
- 本机D盘free预计跌破45GB，或C盘出现实验数据；
- 微阶段总量超过25GB或committed超过20GB；
- GPU free低于18,000MiB、发生Xid/OOM或共享服务异常；
- 任一archive/hash/restore失败；
- 阶段间effect peeking、选择性重跑、拆bundle或结果后改规则。
"""


def main() -> None:
    assert COMMITTED + SCRATCH + RECOVERY + MANIFEST == MICRO_CAP
    write_csv()
    MD.write_text(build_markdown().rstrip() + "\n", encoding="utf-8")
    contract = {
        "schema": "resource-aware-execution-plan-v6.11-1.0",
        "status": "GENERATOR_CANARY_ALLOWED_FULL_RUNTIME_AND_FORMAL_BLOCKED",
        "statistical_authority": "实验设计与执行计划v6.10-100GB分阶段执行版.md",
        "resource_execution_authority": MD.name,
        "remote_snapshot": REMOTE,
        "local_snapshot": LOCAL,
        "storage_policy": {
            "hard_stage_cap_bytes": HARD_CAP,
            "current_microstage_cap_bytes": MICRO_CAP,
            "current_subbudgets_bytes": {
                "committed": COMMITTED,
                "scratch_partial_retry": SCRATCH,
                "recovery_quarantine": RECOVERY,
                "manifests_checksums_reserve": MANIFEST,
            },
            "remote_reserve_25pct_bytes": REMOTE_RESERVE25,
            "remote_emergency_floor_nonconfirmatory_bytes": REMOTE_DEV_FLOOR,
            "external_drift_guard_bytes": DRIFT_GUARD,
            "formal_start_free_min_bytes": FORMAL_START_MIN,
            "formal_current_shortfall_bytes": FORMAL_SHORTFALL,
            "development_start_free_min_bytes": DEV_START_MIN,
            "development_current_margin_bytes": DEV_MARGIN,
            "hard100_start_free_min_bytes": HARD100_START_MIN,
            "hard100_current_shortfall_bytes": HARD100_SHORTFALL,
            "local_d_floor_bytes": LOCAL_D_FLOOR,
            "local_restore_start_free_min_bytes": LOCAL_RESTORE_MIN,
            "local_restore_current_margin_bytes": LOCAL_RESTORE_MARGIN,
            "archive_a": "PENDING_EXTERNAL_DURABLE_URI_A",
            "archive_b": "PENDING_EXTERNAL_DURABLE_URI_B",
            "local_is_rolling_restore_cache_not_archive": True,
            "effect_look_between_microstages": False,
        },
        "compute_policy": {
            "remote_cpu_default_logical": 8,
            "remote_cpu_max_logical": 12,
            "remote_memory_soft_bytes": 24 * 1024**3,
            "remote_memory_hard_bytes": 32 * 1024**3,
            "remote_gpu_default": "OFF",
            "remote_gpu_max_jobs": 1,
            "remote_gpu_process_budget_mib": 12_000,
            "remote_gpu_min_free_mib": 18_000,
            "local_cpu_max_logical": 4,
            "local_working_memory_max_bytes": 4 * 1024**3,
        },
        "phases": PHASES,
        "files": {},
    }
    contract["files"] = {
        "markdown": {"name": MD.name, "sha256": sha256(MD)},
        "stage_matrix": {"name": CSV_OUT.name, "rows": len(PHASES), "sha256": sha256(CSV_OUT)},
    }
    JSON_OUT.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "markdown": str(MD),
        "json": str(JSON_OUT),
        "csv": str(CSV_OUT),
        "formal_shortfall_bytes": FORMAL_SHORTFALL,
        "development_margin_bytes": DEV_MARGIN,
        "local_restore_margin_bytes": LOCAL_RESTORE_MARGIN,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
