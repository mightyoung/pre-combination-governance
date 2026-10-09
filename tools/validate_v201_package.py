from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from deliver_v20_v65 import citation_audit  # noqa: E402

MAIN = ROOT / "00-论文-中文阅读稿v20.1-一致性修复与投稿主线收敛版.md"
S1 = ROOT / "补充材料S1-v20.1-组合前治理证明与性质测试.md"
S2 = ROOT / "补充材料S2-v20.1-运行合同与观察映射规范.md"
EXP = ROOT / "实验设计与执行计划v6.7-精简确认性预注册蓝图.md"
REPORT = ROOT / "研判报告二十二-v20与实验v6.6复审-Information-Fusion硬伤与v20.1-v6.7改进.md"
MANIFEST = ROOT / "NormativeReleaseManifest-v20.1-v6.7.json"
SCHEMA = ROOT / "NormativeReleaseManifest-v20.1-v6.7.schema.json"
DOCX_REPORT = ROOT / "v20.1-v6.7-DOCX结构核验报告.json"
WB_INSPECTION = ROOT / "outputs" / "v67-workbook-roundtrip-preview" / "inspection.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require(checks: dict[str, bool], key: str, value: bool) -> None:
    checks[key] = bool(value)


def main() -> None:
    texts = {"main": MAIN.read_text(encoding="utf-8"), "s1": S1.read_text(encoding="utf-8"), "s2": S2.read_text(encoding="utf-8"), "experiment": EXP.read_text(encoding="utf-8")}
    checks: dict[str, bool] = {}

    # Submission format and citation closure.
    citation = citation_audit(texts["main"])
    abstract_match = re.search(r"## Abstract\s+(.*?)\s+Keywords:", texts["main"], re.S)
    abstract_words = re.findall(r"\b[A-Za-z][A-Za-z0-9–'’-]*\b", abstract_match.group(1) if abstract_match else "")
    keywords_match = re.search(r"(?m)^Keywords:\s*(.+)$", texts["main"])
    keyword_count = len([x for x in (keywords_match.group(1).split(";") if keywords_match else []) if x.strip()])
    require(checks, "main_reference_count_50", citation["reference_count"] == 50)
    require(checks, "main_reference_sequence_1_to_50", citation["sequence_ok"])
    require(checks, "main_no_missing_or_uncited_references", not citation["missing_entries"] and not citation["uncited_references"])
    require(checks, "english_abstract_at_most_250", len(abstract_words) <= 250)
    require(checks, "english_keywords_1_to_7", 1 <= keyword_count <= 7)

    # Cross-document P0 closure.
    for name, text in texts.items():
        require(checks, f"{name}_has_release_manifest_binding", "NormativeReleaseManifest" in text)
        require(checks, f"{name}_has_split_conservation_claims", "C-Conserve-Inv" in text and "C-Conserve-Benefit" in text)
        require(checks, f"{name}_no_unsplit_C_Conserve", re.search(r"C-Conserve(?!-(?:Inv|Benefit))", text) is None)
    require(checks, "main_shared_u_is_sensitivity_only", "共享 \(u\) 交集编译器仅保留为一个具名敏感性模型" in texts["main"])
    require(checks, "s1_shared_u_not_primary", "绝不是主路径强制项" in texts["s1"])
    require(checks, "s2_has_unique_auth_route", "action=REJECT_AUTH" in texts["s2"] and "NO_ATTEMPT 不属于 attempt_status enum" in texts["s2"])
    require(checks, "main_has_unique_auth_route", "action=REJECT_AUTH" in texts["main"] and "NO_ATTEMPT 不属于 attempt_status enum" in texts["main"])
    require(checks, "all_have_root_mapper_contract", all(("RootLevelMapperManifest" in t or "RootLevelMapper" in t) for t in texts.values()))
    require(checks, "main_action_truth_rule_preseed", "任何 test seed 生成前" in texts["main"] and "ActionTruthRuleManifest" in texts["main"])
    require(checks, "experiment_action_truth_rule_preseed", "任何 test seed 生成前" in texts["experiment"] and "ActionTruthRuleManifest" in texts["experiment"])
    require(checks, "s2_setwise_generator_fields", all(token in texts["s2"] for token in ["generator_version/hash", "witness_subgraph/hash", "adjudication_policy_hash"]))
    require(checks, "experiment_estimator_frozen", "唯一主估计为按目标层权的 paired stratified bootstrap" in texts["experiment"] and "score estimator/estimating equation 只作 sensitivity" in texts["experiment"])
    require(checks, "experiment_gate5_in_sequence", "C-Budget→表示一致性 Gate 5" in texts["experiment"])

    # Algorithm order: require unique increasing token positions inside Algorithm 2.
    algorithm = texts["main"].split("**算法 2：单个候选的原子运行路径。**", 1)[1].split("## 5 ", 1)[0]
    stage_tokens = [
        "predictor",
        "验证 credential chain",
        "processing token",
        "canonical root/class redirect",
        "sealed outer contract",
        "SourceAdapter",
        "root/class-level",
        "SetwiseEligibilityCertificate",
        "joint gate",
        "原子提交",
    ]
    stage_positions = [algorithm.find(token) for token in stage_tokens]
    require(checks, "algorithm2_all_stages_present", all(p >= 0 for p in stage_positions))
    require(checks, "algorithm2_stage_order_increasing", stage_positions == sorted(stage_positions))
    require(checks, "algorithm2_cas_restarts_at_step1", "从本算法第 1 步" in algorithm)

    # Manifest schema and artifact hash integrity.
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(manifest)
    require(checks, "manifest_schema_validation", True)
    hash_mismatches = []
    for name, record in manifest["artifacts"].items():
        path = ROOT / name
        if not path.exists() or sha256(path) != record["sha256"] or path.stat().st_size != record["bytes"]:
            hash_mismatches.append(name)
    require(checks, "manifest_artifact_hashes_match", not hash_mismatches)
    require(checks, "manifest_status_confirm_blocked", manifest["status"] == "DESIGN_REPAIRED_CONFIRM_BLOCKED")
    require(checks, "manifest_has_open_blockers", len(manifest["unresolved_blockers"]) >= 1)

    # DOCX and workbook round-trip reports.
    docx_report = json.loads(DOCX_REPORT.read_text(encoding="utf-8"))
    require(checks, "docx_delivery_pass", docx_report["status"] == "PASS" and not docx_report["failures"])
    require(checks, "docx_main_figure_embedded", docx_report["main_figure"]["inline_shapes"] == 1 and docx_report["main_figure"]["width_cm"] <= 16.2)
    require(checks, "docx_no_comments_or_revisions", all(not x["comments"] and x["tracked_insertions"] == 0 and x["tracked_deletions"] == 0 for x in docx_report["files"].values()))

    workbook = json.loads(WB_INSPECTION.read_text(encoding="utf-8"))
    wb_corpus = json.dumps(workbook, ensure_ascii=False)
    wb_errors = {token: wb_corpus.count(token) for token in ["#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A"]}
    require(checks, "workbook_roundtrip_10_sheets", len(workbook["sheets"]) == 10)
    require(checks, "workbook_no_formula_errors", not any(wb_errors.values()))
    require(checks, "workbook_math_gate_pass", workbook["critical"]["resourceGates"][0] == ["算术勾稽", "PASS"])
    require(checks, "workbook_resource_gate_honestly_fails", workbook["critical"]["resourceGates"][1] == ["资源容量门", "FAIL"])
    require(checks, "workbook_planning_n_not_null", workbook["critical"]["planningN"][1][0] == 9144)
    require(checks, "workbook_person_days_reconcile", workbook["critical"]["personnelTotal"][0][0] == workbook["critical"]["scheduleTotals"][0][2])

    templates = {}
    for name in ["AllocationManifest-v6.7.template.json", "TestManifest-v6.7.template.json", "PowerConfirmConfig-v6.7.template.json"]:
        obj = json.loads((ROOT / name).read_text(encoding="utf-8"))
        templates[name] = obj["status"]
    require(checks, "experiment_templates_parse_and_unsealed", all(x == "TEMPLATE_UNSEALED" for x in templates.values()))

    # Current legacy test evidence is recorded without misclassifying it as v20.1 qualification.
    pytest = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT / "risk-fusion-bench", text=True, capture_output=True, timeout=120)
    require(checks, "legacy_pytest_currently_passes", pytest.returncode == 0)

    failed = [key for key, ok in checks.items() if not ok]
    report = {
        "status": "PASS" if not failed else "FAIL",
        "delivery_readiness": "PASS" if not failed else "FAIL",
        "submission_readiness": "BLOCKED",
        "confirmatory_generation": "BLOCKED",
        "paper_editorial_judgment": "REJECT_RESUBMIT_UNTIL_EVIDENCE_GATES_CLOSE",
        "checks": checks,
        "failures": failed,
        "citation_audit": citation,
        "english_abstract_words": len(abstract_words),
        "english_keyword_count": keyword_count,
        "algorithm2_stage_tokens": stage_tokens,
        "algorithm2_stage_positions": stage_positions,
        "manifest_hash_mismatches": hash_mismatches,
        "workbook_formula_errors": wb_errors,
        "template_status": templates,
        "legacy_pytest": {"returncode": pytest.returncode, "stdout": pytest.stdout.strip(), "stderr": pytest.stderr.strip(), "classification": "LEGACY_SMOKE_ONLY_NOT_V20_1_QUALIFICATION"},
        "unresolved_blockers": manifest["unresolved_blockers"],
    }
    out = ROOT / "v20.1-v6.7-结构核验报告.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(out), "status": report["status"], "failures": failed, "submission_readiness": report["submission_readiness"], "pytest": report["legacy_pytest"]["stdout"]}, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
