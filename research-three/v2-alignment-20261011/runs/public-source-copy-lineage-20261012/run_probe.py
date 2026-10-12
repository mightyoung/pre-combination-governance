"""Run the frozen synthetic source-copy boundary probe; no network or delivery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from rfb.research.source_lineage_contract_v1 import (
    LineageEdge,
    LineageEvidence,
    LineageNode,
    ObservationLineage,
    assess_source_lineage,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
RUN_DIR = Path(__file__).resolve().parent


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _verify_pre_run_manifest() -> tuple[dict[str, Any], str]:
    manifest_path = RUN_DIR / "PRE_RUN_MANIFEST.json"
    manifest = _read_json(manifest_path)
    for entry in manifest["files"]:
        path = REPO_ROOT / entry["path"]
        raw = path.read_bytes()
        if len(raw) != entry["bytes"] or _digest(raw) != entry["sha256"]:
            raise ValueError(f"pre-run artifact hash mismatch: {entry['path']}")
    return manifest, _digest(manifest_path.read_bytes())


def _evidence(spec: dict[str, Any]) -> LineageEvidence:
    return LineageEvidence(
        source_ref=spec["source_ref"],
        actual_available_at=spec["actual_available_at"],
        earliest_known_at=spec["earliest_known_at"],
        trust_status=spec["trust_status"],
        valid_until=spec.get("valid_until"),
    )


def _lineage(spec: dict[str, Any]) -> ObservationLineage:
    nodes = tuple(
        LineageNode(
            node_id=item["node_id"],
            node_type=item["node_type"],
            evidence=_evidence(item["evidence"]),
        )
        for item in spec["nodes"]
    )
    edges = tuple(
        LineageEdge(
            edge_id=item["edge_id"],
            upstream_node_id=item["upstream_node_id"],
            downstream_node_id=item["downstream_node_id"],
            evidence=_evidence(item["evidence"]),
        )
        for item in spec["edges"]
    )
    return ObservationLineage(
        observation_id=spec["observation_id"],
        declared_root_id=spec.get("declared_root_id"),
        terminal_node_id=spec["terminal_node_id"],
        trace_complete=spec["trace_complete"],
        completeness_evidence=_evidence(spec["completeness_evidence"]),
        nodes=nodes,
        edges=edges,
    )


def _assessment_row(case: dict[str, Any], *, as_of: str) -> dict[str, Any]:
    assessment = assess_source_lineage(
        _lineage(case["left"]), _lineage(case["right"]), as_of=as_of
    )
    return {
        "case_id": case["case_id"],
        "duplicate_assertion_copies": case["duplicate_assertion_copies"],
        "status": assessment.status.value,
        "declared_root_id_relation": assessment.declared_root_id_relation.value,
        "shared_ancestor_node_ids": list(assessment.shared_ancestor_node_ids),
        "reason_codes": list(assessment.reason_codes),
        "evidence_refs": list(assessment.evidence_refs),
        "unique_edge_count": assessment.unique_edge_count,
        "statistical_independence_established": (
            assessment.statistical_independence_established
        ),
        "numeric_risk_confidence_delta": None,
    }


def _public_sample_summary(spec: dict[str, Any]) -> dict[str, Any]:
    sample_path = REPO_ROOT / spec["sample_path"]
    sample = _read_json(sample_path)
    feature = sample["feature"]
    properties = feature["properties"]
    ids = [part for part in properties["ids_raw"].split(",") if part]
    sources = [part for part in properties["sources_raw"].split(",") if part]
    observed = {
        "feature_id": feature["id"],
        "ids": ids,
        "source_labels": sources,
        "event_origin_time": properties["time_utc"],
        "catalog_updated_time": properties["updated_utc"],
        "feed_generated_time": sample["feed_metadata"]["generated_utc"],
        "lineage_status": sample["audit_interpretation"]["lineage_status"],
        "raw_bytes_saved": sample["source"]["raw_bytes_saved"],
        "raw_response_sha256": sample["source"]["raw_response_sha256"],
        "exact_local_capture_time_utc": sample["source"]["exact_local_capture_time_utc"],
        "directional_forwarding_receipts_available": (
            sample["audit_interpretation"]["directional_forwarding_receipt_available"]
        ),
        "confidence_change": "UNKNOWN_NO_CONFIDENCE_UPDATE",
        "not_submitted_to_contract_as_complete_graph": True,
    }
    for key in (
        "feature_id",
        "ids",
        "source_labels",
        "event_origin_time",
        "catalog_updated_time",
        "feed_generated_time",
        "lineage_status",
        "raw_bytes_saved",
        "raw_response_sha256",
        "exact_local_capture_time_utc",
        "directional_forwarding_receipts_available",
    ):
        if observed[key] != spec[key]:
            raise ValueError(f"saved public sample differs from frozen input at {key}")
    return observed


def _assert_frozen_expectations(
    cases: list[dict[str, Any]], outputs: list[dict[str, Any]]
) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for case, output in zip(cases, outputs, strict=True):
        expected = case["expected"]
        checks[f"{case['case_id']}:contract_fields"] = all(
            output[key] == expected[key]
            for key in (
                "status",
                "declared_root_id_relation",
                "shared_ancestor_node_ids",
                "unique_edge_count",
                "statistical_independence_established",
            )
        )
    baseline, duplicate = outputs[0], outputs[1]
    checks["exact_duplicate_claims_do_not_change_lineage_support"] = all(
        baseline[key] == duplicate[key]
        for key in (
            "status",
            "declared_root_id_relation",
            "shared_ancestor_node_ids",
            "unique_edge_count",
            "evidence_refs",
            "statistical_independence_established",
        )
    )
    checks["independence_never_asserted"] = all(
        row["statistical_independence_established"] is False for row in outputs
    )
    return checks


def _svg(public: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    base, duplicate, disjoint = rows
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1320" height="900" viewBox="0 0 1320 900" role="img" aria-labelledby="title desc">
<title id="title">Public USGS row and synthetic replay lineage boundary</title>
<desc id="desc">The real USGS row has two catalog IDs and two source labels but lineage remains unknown. Synthetic duplicate assertions leave the shared lineage result unchanged. A disjoint synthetic graph still does not establish statistical independence.</desc>
<rect width="1320" height="900" fill="#f5f7fb"/>
<text x="48" y="54" font-family="Arial, sans-serif" font-size="28" font-weight="700" fill="#17243b">重复来源副本不应增加风险置信度</text>
<text x="48" y="86" font-family="Arial, sans-serif" font-size="15" fill="#53647d">Research 3 · USGS public snapshot + synthetic lineage counterexamples · no real delivery or risk score</text>
<rect x="48" y="112" width="1224" height="265" rx="16" fill="#ffffff" stroke="#d4deea"/>
<text x="78" y="151" font-family="Arial, sans-serif" font-size="20" font-weight="700" fill="#17243b">REAL PUBLIC ROW · USGS feature {public['feature_id']}</text>
<text x="78" y="180" font-family="Arial, sans-serif" font-size="13" font-weight="700" fill="#52627b">SOURCE-PROVIDED CHRONOLOGY ONLY · NOT A TRANSFER TRACE</text>
<line x1="162" y1="235" x2="1120" y2="235" stroke="#aab7c8" stroke-width="3"/>
<circle cx="208" cy="235" r="12" fill="#2877b8"/><circle cx="642" cy="235" r="12" fill="#8b5bb5"/><circle cx="1070" cy="235" r="12" fill="#11826b"/>
<text x="122" y="215" font-family="Arial, sans-serif" font-size="13" font-weight="700" fill="#2877b8">EVENT ORIGIN</text>
<text x="550" y="215" font-family="Arial, sans-serif" font-size="13" font-weight="700" fill="#8b5bb5">CATALOG UPDATE</text>
<text x="987" y="215" font-family="Arial, sans-serif" font-size="13" font-weight="700" fill="#11826b">FEED GENERATED</text>
<text x="113" y="265" font-family="Arial, sans-serif" font-size="14" fill="#17243b">{public['event_origin_time']}</text>
<text x="545" y="265" font-family="Arial, sans-serif" font-size="14" fill="#17243b">{public['catalog_updated_time']}</text>
<text x="967" y="265" font-family="Arial, sans-serif" font-size="14" fill="#17243b">{public['feed_generated_time']}</text>
<rect x="78" y="293" width="533" height="55" rx="10" fill="#eaf1f9"/>
<text x="96" y="318" font-family="Arial, sans-serif" font-size="14" fill="#263850">Catalog metadata: {len(public['ids'])} IDs · {len(public['source_labels'])} source labels · one feature row</text>
<text x="96" y="339" font-family="Arial, sans-serif" font-size="13" fill="#8c442a">These counts do not prove separate acquisition paths.</text>
<rect x="629" y="293" width="613" height="55" rx="10" fill="#fff4dd"/>
<text x="647" y="318" font-family="Arial, sans-serif" font-size="14" font-weight="700" fill="#765600">LINEAGE: UNKNOWN · raw hash / receipt / hop records absent</text>
<text x="647" y="339" font-family="Arial, sans-serif" font-size="13" fill="#765600">Risk confidence update: UNKNOWN / NOT COMPUTED</text>
<rect x="48" y="401" width="1224" height="249" rx="16" fill="#ffffff" stroke="#d4deea"/>
<text x="78" y="440" font-family="Arial, sans-serif" font-size="20" font-weight="700" fill="#17243b">SYNTHETIC REPLAY COUNTEREXAMPLE · not observed deliveries</text>
<text x="78" y="468" font-family="Arial, sans-serif" font-size="14" fill="#53647d">Hypothetical copies of one feature assertion at t+0s, t+1s, t+2s. The graph and VERIFIED labels are fixture assumptions.</text>
<rect x="78" y="500" width="230" height="76" rx="12" fill="#eaf6ef" stroke="#9acdb1"/>
<text x="98" y="530" font-family="Arial, sans-serif" font-size="14" font-weight="700" fill="#275c43">1 assertion</text>
<text x="98" y="554" font-family="Arial, sans-serif" font-size="13" fill="#275c43">{base['status']}</text>
<text x="325" y="546" font-family="Arial, sans-serif" font-size="25" fill="#64748b">→</text>
<rect x="370" y="500" width="270" height="76" rx="12" fill="#eaf6ef" stroke="#9acdb1"/>
<text x="390" y="530" font-family="Arial, sans-serif" font-size="14" font-weight="700" fill="#275c43">4 identical assertions</text>
<text x="390" y="554" font-family="Arial, sans-serif" font-size="13" fill="#275c43">{duplicate['status']} · {duplicate['unique_edge_count']} unique edges</text>
<rect x="675" y="500" width="566" height="76" rx="12" fill="#eef2f7" stroke="#cbd5e1"/>
<text x="697" y="530" font-family="Arial, sans-serif" font-size="14" font-weight="700" fill="#34465f">Shared ancestor stays: {', '.join(duplicate['shared_ancestor_node_ids'])}</text>
<text x="697" y="554" font-family="Arial, sans-serif" font-size="13" fill="#34465f">Duplicate support delta: 0 · independence: false · numeric score: not computed</text>
<text x="78" y="613" font-family="Arial, sans-serif" font-size="13" fill="#53647d">Different declared root strings still resolve to a shared known ancestor in this synthetic graph; root-label difference is not independence evidence.</text>
<rect x="48" y="674" width="1224" height="174" rx="16" fill="#ffffff" stroke="#d4deea"/>
<text x="78" y="713" font-family="Arial, sans-serif" font-size="20" font-weight="700" fill="#17243b">NEGATIVE CONTROL · synthetic disjoint complete graphs</text>
<rect x="78" y="738" width="505" height="73" rx="12" fill="#f0f4f8"/>
<text x="98" y="768" font-family="Arial, sans-serif" font-size="14" fill="#34465f">Contract result: {disjoint['status']}</text>
<text x="98" y="790" font-family="Arial, sans-serif" font-size="13" fill="#34465f">No shared known ancestor in supplied graphs only.</text>
<rect x="609" y="738" width="633" height="73" rx="12" fill="#fff4dd"/>
<text x="629" y="768" font-family="Arial, sans-serif" font-size="14" font-weight="700" fill="#765600">Statistical independence: false</text>
<text x="629" y="790" font-family="Arial, sans-serif" font-size="13" fill="#765600">No numeric risk-confidence update; event identity remains unevaluated.</text>
<text x="48" y="879" font-family="Arial, sans-serif" font-size="12" fill="#687891">Source: saved USGS public-domain sample (attribution requested). All copies/lineage graphs are synthetic. No NWS fetch, notification, or delivery receipt.</text>
</svg>'''


def main() -> None:
    pre_manifest, pre_manifest_sha = _verify_pre_run_manifest()
    inputs_path = RUN_DIR / "INPUTS.json"
    inputs = _read_json(inputs_path)
    if inputs.get("status") != "FROZEN_PRE_RUN":
        raise ValueError("input fixture must be frozen before execution")
    if inputs.get("classification") != (
        "REAL_PUBLIC_SNAPSHOT_ANCHOR_PLUS_SYNTHETIC_LINEAGE_CONTRACT_CASES"
    ):
        raise ValueError("unexpected fixture classification")

    public_summary = _public_sample_summary(inputs["public_source_anchor"])
    outputs = [
        _assessment_row(case, as_of=inputs["as_of"]) for case in inputs["cases"]
    ]
    method_outputs = json.dumps(
        outputs, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    frozen_method_output_sha = _digest(method_outputs)

    checks = _assert_frozen_expectations(inputs["cases"], outputs)
    all_passed = all(checks.values())
    if not all_passed:
        raise AssertionError(f"frozen lineage expectations failed: {checks}")

    duplicate_decision = {
        "confidence_change": "NO_INCREMENT_FROM_EXACT_DUPLICATE_ASSERTIONS",
        "numeric_risk_confidence_delta": None,
        "basis": "The shared source graph result and unique edge/reference set are invariant under exact duplicate assertions.",
    }
    result = {
        "run_id": inputs["run_id"],
        "run_status": "COMPLETED_SYNTHETIC_LINEAGE_BOUNDARY_CHECK",
        "classification": inputs["classification"],
        "synthetic_only_for_method_calls": True,
        "pre_run_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip(),
        "pre_run_manifest_sha256": pre_manifest_sha,
        "input_sha256": _digest(inputs_path.read_bytes()),
        "method_source_commit": pre_manifest["source_code_commit"],
        "method": inputs["method"],
        "network_or_model_called": False,
        "nws_endpoint_accessed": False,
        "notification_created": False,
        "delivery_status": "NOT_DELIVERED",
        "event_identity_status": "NOT_EVALUATED",
        "efficacy_status": "NOT_ASSESSED",
        "public_sample_summary": public_summary,
        "synthetic_copy_sequence": {
            **inputs["synthetic_copy_sequence"],
            "confidence_change": duplicate_decision["confidence_change"],
        },
        "method_outputs": outputs,
        "method_outputs_sha256_before_expectation_checks": frozen_method_output_sha,
        "checks_after_output_freeze": checks,
        "all_frozen_contract_checks_passed": all_passed,
        "interpretation": {
            "public_sample": "UNKNOWN_LINEAGE_AND_NO_CONFIDENCE_UPDATE; listed IDs/source labels are not proof of independent acquisition.",
            "synthetic_duplicate_case": duplicate_decision,
            "synthetic_disjoint_control": "NO_SHARED_KNOWN_ANCESTOR is not statistical independence and does not authorize a confidence increase.",
            "risk_probability_or_severity": "NOT_COMPUTED",
        },
        "limitations": [
            "The USGS feature is one real public row; its original response bytes, exact local receipt time, and forwarding receipts are absent.",
            "Synthetic graph trust and trace-completeness claims are fixture assumptions, not verified USGS lineage.",
            "The lineage contract does not compute risk confidence, event identity, or notification timeliness.",
            "The probe does not estimate efficacy; contract check counts are not effect sizes or independent samples.",
        ],
    }
    (RUN_DIR / "RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (RUN_DIR / "SOURCE_COPY_SEQUENCE.svg").write_text(
        _svg(public_summary, outputs), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "result_path": str(RUN_DIR / "RESULT.json"),
                "result_sha256": _digest((RUN_DIR / "RESULT.json").read_bytes()),
                "method_outputs_sha256": frozen_method_output_sha,
                "checks": checks,
                "all_frozen_contract_checks_passed": all_passed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
