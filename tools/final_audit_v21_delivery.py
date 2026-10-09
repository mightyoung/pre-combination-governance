from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from deliver_v20_v65 import citation_audit


ROOT = Path(__file__).resolve().parent.parent
STRUCTURE = ROOT / "v21-v6.8-DOCX结构与引用核验报告.json"
REFERENCES = ROOT / "v21-参考文献外部元数据核验.json"
RUN_RESULT = ROOT / "outputs" / "remote-shakedown" / "SHK-000-remote-20260714T0900Z" / "RUN_RESULT.v3.json"
REMOTE_AUDIT = ROOT / "outputs" / "remote-shakedown" / "SHK-000-remote-20260714T0900Z" / "FINAL_REMOTE_AUDIT.json"
OUT = ROOT / "v21-v6.8-最终只读验收.json"

FILES = [
    "00-论文-中文阅读稿v21-生命周期一致组合前治理与IF创新主线版.md",
    "00-论文-中文阅读稿v21-生命周期一致组合前治理与IF创新主线版.docx",
    "实验设计与执行计划v6.8-机制先行与表示中立验证蓝图.md",
    "实验设计与执行计划v6.8-机制先行与表示中立验证蓝图.docx",
    "研判报告二十四-报告二十三裁决与v21-Information-Fusion创新性论证.md",
    "研判报告二十四-报告二十三裁决与v21-Information-Fusion创新性论证.docx",
    "实验执行记录v6.7-SHK-000-远程资格启动.md",
    "实验执行记录v6.7-SHK-000-远程资格启动.docx",
    "v21-v6.8-DOCX结构与引用核验报告.json",
    "v21-参考文献外部元数据核验.json",
]

WORD_STATS = {
    "00-论文-中文阅读稿v21-生命周期一致组合前治理与IF创新主线版.docx": {"pages": 13, "words": 9884, "tables": 4, "inline_shapes": 1},
    "实验设计与执行计划v6.8-机制先行与表示中立验证蓝图.docx": {"pages": 4, "words": 2365, "tables": 4, "inline_shapes": 0},
    "研判报告二十四-报告二十三裁决与v21-Information-Fusion创新性论证.docx": {"pages": 4, "words": 2876, "tables": 3, "inline_shapes": 0},
    "实验执行记录v6.7-SHK-000-远程资格启动.docx": {"pages": 6, "words": 4851, "tables": 6, "inline_shapes": 0},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    structure = json.loads(STRUCTURE.read_text(encoding="utf-8"))
    references = json.loads(REFERENCES.read_text(encoding="utf-8"))
    run = json.loads(RUN_RESULT.read_text(encoding="utf-8"))
    remote = json.loads(REMOTE_AUDIT.read_text(encoding="utf-8"))
    main_path = ROOT / FILES[0]
    main_text = main_path.read_text(encoding="utf-8")
    shk_text = (ROOT / "实验执行记录v6.7-SHK-000-远程资格启动.md").read_text(encoding="utf-8")
    citations = citation_audit(main_text)

    checks = {
        "all_delivery_files_exist": all((ROOT / name).exists() for name in FILES),
        "docx_structure_pass": structure["status"] == "PASS" and not structure["failures"],
        "reference_external_verification_50_of_50": references["status"] == "PASS" and references["passed"] == 50,
        "citation_sequence_and_usage_pass": citations["sequence_ok"] and not citations["missing_entries"] and not citations["uncited_references"],
        "information_fusion_reference_limit": citations["reference_count"] <= 50,
        "information_fusion_page_range": 10 <= WORD_STATS["00-论文-中文阅读稿v21-生命周期一致组合前治理与IF创新主线版.docx"]["pages"] <= 35,
        "main_figure_present": WORD_STATS["00-论文-中文阅读稿v21-生命周期一致组合前治理与IF创新主线版.docx"]["inline_shapes"] == 1,
        "shk_uses_v3_authoritative_results": "RUN_RESULT.v3.json" in shk_text and "REMOTE_RETRIEVAL_MANIFEST.v3.json" in shk_text,
        "shk_no_stale_v2_links": "RUN_RESULT.v2.json" not in shk_text and "REMOTE_RETRIEVAL_MANIFEST.v2.json" not in shk_text,
        "shk_absolute_local_links": not bool(re.search(r"\]\((?!https?://|<D:/|#)", shk_text)),
        "shk_pip_check_recorded": "No broken requirements found" in shk_text,
        "remote_boundary_audit_pass": remote["status"] == "PASS" and remote["credential_literal_hits"] == 0,
        "no_d_test_or_confirmatory_activity": not remote["remote"]["actual_d_test_namespace_dirs"] and not remote["remote"]["data_test_exists"] and not remote["remote"]["runs_confirm_exists"],
        "candidate_and_release_boundaries_clean": not remote["remote"]["candidate_writeable_entries"] and not remote["remote"]["release_entries"],
        "experiment_claim_support_none": run["run_policy"]["claim_support"] == "none" and not run["run_policy"]["confirmatory"],
        "resource_gate_honestly_fails": run["gates"]["G0_RESOURCE"] == "FAIL",
        "pilot_and_d_test_not_authorized": not run["gates"]["PILOT_AUTHORIZED"] and not run["gates"]["D_TEST_AUTHORIZED"],
        "normative_supplements_not_silently_versioned": not any(ROOT.glob("补充材料S?-v21*")),
    }
    failures = [name for name, ok in checks.items() if not ok]
    file_manifest = {
        name: {"bytes": (ROOT / name).stat().st_size, "sha256": sha256(ROOT / name)}
        for name in FILES
    }
    report = {
        "status": "PASS" if not failures else "FAIL",
        "delivery_readiness": "PASS" if not failures else "FAIL",
        "submission_readiness": "BLOCKED",
        "editorial_judgment": "PREMATURE_REJECT_UNTIL_LIFECYCLE_RUNTIME_ORACLE_AND_MME_PASS",
        "checks": checks,
        "failures": failures,
        "citation_audit": citations,
        "word_com_readonly_statistics": WORD_STATS,
        "reference_verification": {k: references[k] for k in ["status", "reference_count", "passed", "failed", "method"]},
        "experiment_gates": run["gates"],
        "experiment_evidence_class": run["run_policy"],
        "remote_boundary_audit": remote,
        "file_manifest": file_manifest,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(OUT), "status": report["status"], "submission_readiness": report["submission_readiness"], "failures": failures}, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
