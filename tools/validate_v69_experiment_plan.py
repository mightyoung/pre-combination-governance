from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from math import sqrt
from pathlib import Path

from scipy.stats import norm


ROOT = Path(__file__).resolve().parent.parent
MD = ROOT / "实验设计与执行计划v6.9-指定执行版-机制验证到确认性试验.md"
DOCX = MD.with_suffix(".docx")
CONTRACT = ROOT / "ExperimentExecutionPlan-v6.9.json"
TEMPLATES = ROOT / "MMETemplateMatrix-v6.9.csv"
ALLOCATION = ROOT / "MMEAllocation-v6.9.csv"
DOCX_REPORT = ROOT / "v6.9-指定实验计划交付与结构核验.json"
OUT = ROOT / "v6.9-指定实验计划最终验收.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def wilson(k: int, n: int, z: float) -> tuple[float, float]:
    p = k / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return center - half, center + half


def main() -> None:
    failures: list[str] = []
    checks: dict[str, object] = {}
    for path in [MD, DOCX, CONTRACT, TEMPLATES, ALLOCATION, DOCX_REPORT]:
        if not path.exists():
            failures.append(f"missing file: {path.name}")

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    templates = read_csv(TEMPLATES)
    allocation = read_csv(ALLOCATION)
    docx_report = json.loads(DOCX_REPORT.read_text(encoding="utf-8"))
    md_text = MD.read_text(encoding="utf-8")

    if contract["status"] != "EXECUTION_SPECIFIED_REMOTE_BLOCKED":
        failures.append("status is not remote-blocked")
    if contract["contains_executable_seeds"] is not False:
        failures.append("contract claims executable seeds")
    if contract["resource_gates"]["current_G0_RESOURCE"] != "FAIL":
        failures.append("G0 status is not FAIL")
    if contract["resource_gates"]["pilot_authorized"] or contract["resource_gates"]["d_test_authorized"]:
        failures.append("pilot or D_test is incorrectly authorized")

    template_phase = Counter(row["phase"] for row in templates)
    template_category = Counter((row["phase"], row["template_category"]) for row in templates)
    expected_categories = {
        ("SCREEN", "CORE_COVERAGE"): 72,
        ("SCREEN", "BOUNDARY_DOSE_RESPONSE"): 12,
        ("VERIFY", "POSTCOMMIT_LIFECYCLE"): 12,
        ("VERIFY", "SRI_NO_HARM"): 6,
        ("VERIFY", "TRANSPORT_NEGATIVE_CONTROL"): 4,
        ("VERIFY", "BOUNDARY_FAILSTOP"): 6,
    }
    if template_phase != Counter({"SCREEN": 84, "VERIFY": 28}):
        failures.append(f"template phase counts wrong: {dict(template_phase)}")
    if dict(template_category) != expected_categories:
        failures.append("template category counts wrong")

    allocation_phase = Counter(row["phase"] for row in allocation)
    if allocation_phase != Counter({"SCREEN": 672, "VERIFY": 1680}):
        failures.append(f"allocation phase counts wrong: {dict(allocation_phase)}")
    if len({row["bundle_slot"] for row in allocation}) != 2352:
        failures.append("bundle slots are not unique")
    if any(row["contains_executable_seed"].lower() == "true" for row in allocation):
        failures.append("allocation contains executable seeds")
    if any(row["physical_seed_commitment"] != "TO_BE_FILLED_BY_DS_AT_G3A" for row in allocation):
        failures.append("seed commitment placeholder contract changed")

    template_usage = Counter((row["phase"], row["template_id"]) for row in allocation)
    if {count for (phase, _), count in template_usage.items() if phase == "SCREEN"} != {8}:
        failures.append("SCREEN templates are not each used 8 times")
    if {count for (phase, _), count in template_usage.items() if phase == "VERIFY"} != {60}:
        failures.append("VERIFY templates are not each used 60 times")

    balance: dict[str, object] = {}
    for phase, expected_rows, expected_batches, expected_stratum, expected_sequence, expected_position, expected_pair in [
        ("SCREEN", 672, 24, 28, 48, 96, 96),
        ("VERIFY", 1680, 60, 70, 120, 240, 240),
    ]:
        subset = [row for row in allocation if row["phase"] == phase]
        batch_counts = Counter(row["execution_batch"] for row in subset)
        stratum_counts = Counter(row["stratum"] for row in subset)
        sequence_counts = Counter(row["method_sequence_id"] for row in subset)
        position_counts: Counter[tuple[str, int]] = Counter()
        carryover_counts: Counter[tuple[str, str]] = Counter()
        for row in subset:
            methods = row["method_order"].split("|")
            for position, method in enumerate(methods, start=1):
                position_counts[(method, position)] += 1
            carryover_counts.update(zip(methods, methods[1:]))
        if len(subset) != expected_rows:
            failures.append(f"{phase} row count wrong")
        if len(batch_counts) != expected_batches or set(batch_counts.values()) != {28}:
            failures.append(f"{phase} batch balance wrong")
        if len(stratum_counts) != 24 or set(stratum_counts.values()) != {expected_stratum}:
            failures.append(f"{phase} stratum balance wrong")
        if len(sequence_counts) != 14 or set(sequence_counts.values()) != {expected_sequence}:
            failures.append(f"{phase} Williams sequence balance wrong")
        if len(position_counts) != 49 or set(position_counts.values()) != {expected_position}:
            failures.append(f"{phase} method-position balance wrong")
        if len(carryover_counts) != 42 or set(carryover_counts.values()) != {expected_pair}:
            failures.append(f"{phase} first-order carryover balance wrong")
        balance[phase] = {
            "rows": len(subset),
            "batches": len(batch_counts),
            "strata": len(stratum_counts),
            "sequences": len(sequence_counts),
            "method_position_count": sorted(set(position_counts.values())),
            "ordered_carryover_count": sorted(set(carryover_counts.values())),
        }

    z16 = norm.ppf(1 - 0.05 / (2 * 16))
    z1 = norm.ppf(1 - 0.05 / 2)
    threshold_checks = {
        "power16_pass": wilson(18126, 20000, z16)[0] >= 0.90,
        "power16_previous_fails": wilson(18125, 20000, z16)[0] < 0.90,
        "type16_pass": wilson(1146, 50000, z16)[1] <= 0.025,
        "type16_next_fails": wilson(1147, 50000, z16)[1] > 0.025,
        "power1_pass": wilson(18084, 20000, z1)[0] >= 0.90,
        "power1_previous_fails": wilson(18083, 20000, z1)[0] < 0.90,
        "type1_pass": wilson(1181, 50000, z1)[1] <= 0.025,
        "type1_next_fails": wilson(1182, 50000, z1)[1] > 0.025,
    }
    if not all(threshold_checks.values()):
        failures.append(f"Wilson threshold contract failed: {threshold_checks}")

    screen_upper = 1 - 0.05 ** (1 / 8)
    verify_upper = 1 - 0.05 ** (1 / 60)
    if abs(contract["mme"]["screen"]["zero_event_upper_95_template"] - screen_upper) > 1e-10:
        failures.append("SCREEN zero-event upper bound mismatch")
    if abs(contract["mme"]["verify"]["zero_event_upper_95_template"] - verify_upper) > 1e-10:
        failures.append("VERIFY zero-event upper bound mismatch")

    if sha256(MD) != contract["files"]["markdown"]["sha256"]:
        failures.append("Markdown hash mismatch")
    if sha256(TEMPLATES) != contract["files"]["template_matrix"]["sha256"]:
        failures.append("template matrix hash mismatch")
    if sha256(ALLOCATION) != contract["files"]["allocation"]["sha256"]:
        failures.append("allocation hash mismatch")
    if docx_report["status"] != "PASS" or docx_report["structure"]["source_sha256"] != sha256(MD):
        failures.append("DOCX structure report is stale or failed")

    required_md = [
        "B2+",
        "method-specific clean counterfactual",
        "672 independent bundles",
        "1,680 independent bundles",
        "PILOT_PRECISION_FAIL",
        "alpha_run=0.020",
        "18,126",
        "D_TEST_AUTHORIZED=false",
        "G0_RESOURCE=FAIL",
    ]
    for token in required_md:
        if token not in md_text:
            failures.append(f"Markdown missing token: {token}")
    for stale in ["96 bundles", "17,472"]:
        if stale in md_text:
            failures.append(f"stale draft value remains: {stale}")

    checks.update(
        {
            "template_phase_counts": dict(template_phase),
            "template_category_counts": {f"{key[0]}::{key[1]}": value for key, value in template_category.items()},
            "allocation_phase_counts": dict(allocation_phase),
            "allocation_balance": balance,
            "williams_power_thresholds": threshold_checks,
            "zero_event_upper_95": {"n8": screen_upper, "n60": verify_upper},
            "docx_structure_status": docx_report["status"],
        }
    )
    report = {
        "status": "PASS" if not failures else "FAIL",
        "authoritative_plan": str(MD),
        "checks": checks,
        "failures": failures,
        "sha256": {
            "markdown": sha256(MD),
            "docx": sha256(DOCX),
            "json": sha256(CONTRACT),
            "templates": sha256(TEMPLATES),
            "allocation": sha256(ALLOCATION),
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(OUT), "status": report["status"], "failures": failures}, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
