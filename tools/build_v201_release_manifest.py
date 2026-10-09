from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


ARTIFACT_SPECS = {
    "00-论文-中文阅读稿v20.1-一致性修复与投稿主线收敛版.md": ("normative_manuscript", True),
    "00-论文-中文阅读稿v20.1-一致性修复与投稿主线收敛版.docx": ("reading_copy", False),
    "补充材料S1-v20.1-组合前治理证明与性质测试.md": ("normative_supplement_s1", True),
    "补充材料S1-v20.1-组合前治理证明与性质测试.docx": ("reading_copy", False),
    "补充材料S2-v20.1-运行合同与观察映射规范.md": ("normative_supplement_s2", True),
    "补充材料S2-v20.1-运行合同与观察映射规范.docx": ("reading_copy", False),
    "实验设计与执行计划v6.7-精简确认性预注册蓝图.md": ("normative_experiment_design", True),
    "实验设计与执行计划v6.7-精简确认性预注册蓝图.docx": ("reading_copy", False),
    "实验资源与样本量预算v6.7.xlsx": ("formula_driven_resource_plan", False),
    "outputs/v67-workbook-preview/inspection.json": ("workbook_structural_inspection", False),
    "AllocationManifest-v6.7.template.json": ("unsealed_allocation_template", False),
    "TestManifest-v6.7.template.json": ("unsealed_test_template", False),
    "PowerConfirmConfig-v6.7.template.json": ("unsealed_power_template", False),
    "NormativeReleaseManifest-v20.1-v6.7.schema.json": ("normative_manifest_schema", True),
    "v20.1-v6.7-DOCX结构核验报告.json": ("docx_structural_verification", False),
    "研判报告二十二-v20与实验v6.6复审-Information-Fusion硬伤与v20.1-v6.7改进.md": ("critical_review_report", False),
    "研判报告二十二-v20与实验v6.6复审-Information-Fusion硬伤与v20.1-v6.7改进.docx": ("critical_review_reading_copy", False),
    "figures/图1-安全工件到在线融合闭环-v20.png": ("main_figure_asset", False),
}


def binding(status: str, artifact: str | None) -> dict[str, str | None]:
    return {
        "status": status,
        "artifact": artifact,
        "sha256": sha256(ROOT / artifact) if artifact else None,
    }


def main() -> None:
    missing = [name for name in ARTIFACT_SPECS if not (ROOT / name).exists()]
    if missing:
        raise FileNotFoundError("missing release artifacts: " + ", ".join(missing))

    artifacts = {
        name: {
            "sha256": sha256(ROOT / name),
            "bytes": (ROOT / name).stat().st_size,
            "role": role,
            "normative": normative,
        }
        for name, (role, normative) in ARTIFACT_SPECS.items()
    }
    package_hash = hashlib.sha256(
        "\n".join(f"{name}:{record['sha256']}" for name, record in sorted(artifacts.items())).encode("utf-8")
    ).hexdigest()

    manifest = {
        "release_id": "v20.1-v6.7-design-repaired-2026-07-14",
        "status": "DESIGN_REPAIRED_CONFIRM_BLOCKED",
        "authority": {
            "manuscript": "v20.1",
            "supplement_s1": "v20.1",
            "supplement_s2": "v20.1",
            "experiment": "v6.7",
        },
        "artifacts": artifacts,
        "claim_register": [
            {"id": "C-Audit", "class": "implementation_invariant", "gate": 0, "status": "PENDING_IMPLEMENTATION"},
            {"id": "C-Conserve-Inv", "class": "implementation_invariant", "gate": 0, "status": "PENDING_IMPLEMENTATION"},
            {"id": "C-System", "class": "confirmatory_empirical", "gate": 1, "status": "PENDING_CONFIRMATORY_EVIDENCE"},
            {"id": "C-HB", "class": "confirmatory_empirical", "gate": 2, "status": "PENDING_CONFIRMATORY_EVIDENCE"},
            {"id": "C-Conserve-Benefit", "class": "confirmatory_empirical", "gate": 3, "status": "PENDING_CONFIRMATORY_EVIDENCE"},
            {"id": "C-Budget", "class": "confirmatory_empirical", "gate": 4, "status": "PENDING_CONFIRMATORY_EVIDENCE"},
        ],
        "transaction_order": [
            "READ_LATEST_SERIALIZABLE_STATE_AND_PREDICT",
            "MINIMAL_AUTH_OR_REJECT_AUTH",
            "FREEZE_TTL_AND_IDEMPOTENT_PROCESSING_TOKEN",
            "RESOLVE_REDIRECT_RETIRE_EXPIRY",
            "OUTER_VALIDATE_OR_REJECT_SCHEMA",
            "EXACT_DUPLICATE_AUDIT",
            "SOURCE_ADAPTER",
            "ROOT_LEVEL_MAPPER_AND_SCOPE_CLOSURE",
            "REBUILD_SETWISE_ELIGIBILITY_CERTIFICATE",
            "RESERVE_COMMITMENT_QUEUE_ACCEPTANCE",
            "APPLY_ONE_ROOT_GLOBAL_DISCOUNT",
            "COMPUTE_JOINT_GATE_AND_GATE_STATE",
            "ATOMIC_COMMIT_THEN_ACTION_STATE"
        ],
        "root_identity_contract": {
            "identity_is_observation_event": True,
            "eventifier_id_hash": None,
            "acquisition_identity": None,
            "root_epoch": None,
            "observation_validity_interval": None,
            "causal_boundary_rule_hash": None,
            "root_type": None,
            "ttl_policy_id": None,
            "schema_hash": None,
            "acquisition_manifest_hash": None,
        },
        "mapper_contract": {
            "source_adapter": "authenticated raw observation -> certified per-source z_r; raw truth and labels forbidden",
            "primary_root_mapper": "f_o({z_r}, context) -> one root-global joint valuation under RootLevelMapperManifest",
            "shared_u_role": "NAMED_SENSITIVITY_ONLY",
            "coupling_family_hash": None,
        },
        "setwise_certificate_contract": {
            "generator_id_hash": None,
            "algorithm_and_cap_version": None,
            "witness_subgraph_hash": None,
            "edge_adjudication_policy_hash": None,
            "active_root_set_hash": None,
            "context_hash": None,
            "decision": "PENDING",
        },
        "reason_action_attempt_crosswalk": [
            {"reason_family": "CREDENTIAL_CHAIN_INVALID|ROOT_IDENTITY_MANIFEST_SIGNATURE_INVALID", "action": "REJECT_AUTH", "attempt_status": None, "processing_token_charged": False},
            {"reason_family": "ROOT_TYPE_BINDING_INVALID|ROOT_IDENTITY_BINDING_INVALID|BUNDLE_SEAL_INVALID|ENVELOPE_EQUIVOCATION", "action": "REJECT_SCHEMA", "attempt_status": "QUARANTINED", "processing_token_charged": True},
            {"reason_family": "MAPPING_CERTIFICATE_INVALID|MAPPING_VALIDITY_DOMAIN_EXCEEDED|MAPPING_DRIFT_DETECTED|MAPPING_UNKNOWN", "action": "ABSTAIN_MAPPING", "attempt_status": "ABSTAIN_MAPPING", "processing_token_charged": True},
            {"reason_family": "COMPILER_CAP_EXCEEDED", "action": "ABSTAIN_COMPLEXITY", "attempt_status": "ABSTAIN_COMPLEXITY", "processing_token_charged": True},
            {"reason_family": "MAPPING_INVALID|TARGET_SCOPE_CONFLICT|STRUCTURAL_CONSTRAINT_FAIL|NO_EVIDENCE|INTRABUNDLE_DISCORD|SETWISE_*", "action": "ABSTAIN_RELATION", "attempt_status": "ABSTAIN_RELATION", "processing_token_charged": True},
            {"reason_family": "COUPLING_SENSITIVE|UTILITY_SENSITIVE", "action": "PROBE", "attempt_status": "ABSTAIN_SENSITIVITY", "processing_token_charged": True},
            {"reason_family": "BUDGET_CAP", "action": "ABSTAIN_BUDGET", "attempt_status": "ABSTAIN_BUDGET", "processing_token_charged": True},
            {"reason_family": "RATE_CAP", "action": "ABSTAIN_RATE", "attempt_status": "ABSTAIN_RATE", "processing_token_charged": True},
            {"reason_family": "JOINT_GATE_FAIL", "action": "ABSTAIN_CONFLICT", "attempt_status": "ABSTAIN_CONFLICT", "processing_token_charged": True},
            {"reason_family": "SUPERSEDE_PRINCIPAL_CAP", "action": "SUPERSEDE_PRINCIPAL_BLOCKED", "attempt_status": "SUPERSEDE_PRINCIPAL_BLOCKED", "processing_token_charged": True},
            {"reason_family": "TARGET_SCOPE_CHANGE", "action": "TARGET_SCOPE_CHANGE_BLOCKED", "attempt_status": "TARGET_SCOPE_CHANGE_BLOCKED", "processing_token_charged": True},
            {"reason_family": "ACCEPTANCE_COMPLETE", "action": "ACCEPT_CONTRIBUTION", "attempt_status": "ACCEPTED", "processing_token_charged": True},
            {"reason_family": "DUPLICATE_AUDIT|RETIRED_LATE_AUDIT", "action": "AUDIT_ONLY", "attempt_status": None, "processing_token_charged": True},
        ],
        "experiment_bindings": {
            "claim_register": binding("PENDING_ARTIFACT", None),
            "scenario_support": binding("PENDING_ARTIFACT", None),
            "method_registry": binding("PENDING_ARTIFACT", None),
            "arm_frame_matrix": binding("BOUND", "实验资源与样本量预算v6.7.xlsx"),
            "seed_manifest": binding("PENDING_ARTIFACT", None),
            "allocation_manifest": binding("TEMPLATE_UNSEALED", "AllocationManifest-v6.7.template.json"),
            "test_manifest": binding("TEMPLATE_UNSEALED", "TestManifest-v6.7.template.json"),
            "power_confirm_config": binding("TEMPLATE_UNSEALED", "PowerConfirmConfig-v6.7.template.json"),
            "container_digests": binding("PENDING_ARTIFACT", None),
            "analysis_code": binding("PENDING_ARTIFACT", None),
        },
        "unresolved_blockers": [
            "reference implementation and P0 property tests are not complete",
            "physical-seed generator and truth/payload isolation are not qualified",
            "root identity, mapper, coupling family and setwise generator hashes are pending",
            "scenario support, method registry, claim register and seed manifest are pending standalone artifacts",
            "pilot precision and nuisance estimates are unavailable",
            "formal sample size and simultaneous power/type-I confirmation are unavailable",
            "allocation and test manifests remain unsealed templates",
            "4 TB nominal storage fails the 25% headroom high-envelope gate",
            "confirmatory test, independent recomputation and external support have not been run"
        ],
        "package_hash": package_hash,
    }
    out = ROOT / "NormativeReleaseManifest-v20.1-v6.7.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(out), "status": manifest["status"], "artifacts": len(artifacts), "package_hash": package_hash}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
