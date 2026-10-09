from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MD = ROOT / "实验资源协同与多阶段执行计划v6.11-本机与11.16服务器.md"
CONTRACT = ROOT / "ResourceAwareExecutionPlan-v6.11.json"
MATRIX = ROOT / "ResourceStageMatrix-v6.11.csv"
OUT = ROOT / "v6.11-双机资源多阶段计划验收.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    failures: list[str] = []
    for path in [MD, CONTRACT, MATRIX]:
        if not path.exists():
            failures.append(f"missing file: {path.name}")
    if failures:
        raise SystemExit("; ".join(failures))

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    with MATRIX.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    text = MD.read_text(encoding="utf-8")
    storage = contract["storage_policy"]
    compute = contract["compute_policy"]
    remote = contract["remote_snapshot"]
    local = contract["local_snapshot"]

    if contract["status"] != "GENERATOR_CANARY_ALLOWED_FULL_RUNTIME_AND_FORMAL_BLOCKED":
        failures.append("status changed")
    if contract["statistical_authority"] != "实验设计与执行计划v6.10-100GB分阶段执行版.md":
        failures.append("v6.10 statistical authority lost")
    if contract["resource_execution_authority"] != MD.name:
        failures.append("v6.11 Markdown is not resource authority")
    if storage["hard_stage_cap_bytes"] != 100_000_000_000:
        failures.append("100GB hard cap changed")
    if storage["current_microstage_cap_bytes"] != 25_000_000_000:
        failures.append("25GB microstage cap changed")
    expected_sub = {
        "committed": 20_000_000_000,
        "scratch_partial_retry": 2_500_000_000,
        "recovery_quarantine": 1_250_000_000,
        "manifests_checksums_reserve": 1_250_000_000,
    }
    if storage["current_subbudgets_bytes"] != expected_sub:
        failures.append("microstage subbudget contract changed")
    if sum(storage["current_subbudgets_bytes"].values()) != 25_000_000_000:
        failures.append("microstage subbudgets do not sum to 25GB")

    formula_checks = {
        "reserve25": storage["remote_reserve_25pct_bytes"] == 235_853_007_872,
        "formal_start": storage["formal_start_free_min_bytes"] == 265_853_007_872,
        "formal_shortfall": storage["formal_current_shortfall_bytes"] == 49_217_988_608,
        "development_start": storage["development_start_free_min_bytes"] == 210_000_000_000,
        "development_margin": storage["development_current_margin_bytes"] == 6_635_019_264,
        "hard100_start": storage["hard100_start_free_min_bytes"] == 335_853_007_872,
        "hard100_shortfall": storage["hard100_current_shortfall_bytes"] == 119_217_988_608,
        "local_restore_start": storage["local_restore_start_free_min_bytes"] == 75_000_000_000,
        "local_restore_margin": storage["local_restore_current_margin_bytes"] == 3_749_585_408,
    }
    if not all(formula_checks.values()):
        failures.append(f"capacity formulas wrong: {formula_checks}")

    if remote["gpu"] != "NVIDIA L20" or remote["gpu_total_mib"] != 46_068:
        failures.append("remote GPU inventory wrong")
    if remote["docker_containers_running"] != 40:
        failures.append("shared Docker load omitted")
    if local["gpu"] != "Intel Iris Xe; no CUDA":
        failures.append("local GPU role wrong")
    if compute["remote_gpu_default"] != "OFF" or compute["remote_gpu_process_budget_mib"] > 12_000:
        failures.append("GPU policy is too aggressive")
    if compute["remote_cpu_max_logical"] > 12 or compute["local_cpu_max_logical"] > 4:
        failures.append("CPU policy is too aggressive")
    if not storage["local_is_rolling_restore_cache_not_archive"]:
        failures.append("local disk incorrectly treated as archive")
    if storage["effect_look_between_microstages"]:
        failures.append("effect look enabled")
    if not str(storage["archive_a"]).startswith("PENDING") or not str(storage["archive_b"]).startswith("PENDING"):
        failures.append("archive endpoints changed without signoff")

    expected = {
        "CONTROL_PREFLIGHT": ("NA", "0"),
        "SHK001A_GENERATOR_CANARY": ("1", "1"),
        "SHK001B_FULL_PANEL_SIZE": ("1", "PENDING_SHK001"),
        "PHASE0_G1_G2": ("28", "PENDING_SHK001"),
        "MME_SCREEN": ("24", "3"),
        "MME_VERIFY": ("60", "7"),
        "D_SELECT": ("28", "3"),
        "PILOT_W1": ("30", "3"),
        "PILOT_W2": ("30", "3"),
        "PILOT_W3": ("20", "2"),
        "PILOT_HELDOUT": ("20", "2"),
        "CONFIRMATORY": ("FINAL_N/24", "PENDING_SHK001"),
    }
    actual = {row["phase"]: (row["execution_batches"], row["provisional_microstages"]) for row in rows}
    if len(rows) != 12 or actual != expected:
        failures.append(f"stage matrix changed: {actual}")

    required_tokens = [
        "25GB物理微阶段",
        "NVIDIA L20 46,068MiB",
        "49,217,988,608",
        "119,217,988,608",
        "一次只能恢复一个阶段",
        "禁止拆bundle",
        "ARCHIVED_A",
        "ARCHIVED_B",
        "effect peeking",
        "NON_CONFIRMATORY_DO_NOT_PROMOTE",
        "当前仓库canary不执行候选方法",
        "SHK001B_FULL_PANEL_SIZE",
    ]
    for token in required_tokens:
        if token not in text:
            failures.append(f"Markdown missing token: {token}")

    if contract["files"]["markdown"]["sha256"] != sha256(MD):
        failures.append("Markdown hash mismatch")
    if contract["files"]["stage_matrix"]["sha256"] != sha256(MATRIX):
        failures.append("CSV hash mismatch")
    if contract["files"]["stage_matrix"]["rows"] != len(rows):
        failures.append("CSV row count mismatch")

    report = {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "checks": {
            "capacity_formulas": formula_checks,
            "phase_count": len(rows),
            "formal_stage_blocked": storage["formal_current_shortfall_bytes"] > 0,
            "development_microstage_allowed": storage["development_current_margin_bytes"] > 0,
            "local_single_restore_margin_positive": storage["local_restore_current_margin_bytes"] > 0,
            "remote_gpu_actual": remote["gpu"],
        },
        "sha256": {
            "markdown": sha256(MD),
            "json": sha256(CONTRACT),
            "stage_matrix": sha256(MATRIX),
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(OUT), "status": report["status"], "failures": failures}, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
