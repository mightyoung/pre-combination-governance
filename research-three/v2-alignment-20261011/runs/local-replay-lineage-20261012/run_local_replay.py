"""Controlled local replay of the saved normalized USGS sample; no network."""

from __future__ import annotations

from datetime import datetime, timezone
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


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json_bytes(value: Any, *, trailing_newline: bool = False) -> bytes:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    if trailing_newline:
        rendered += "\n"
    return rendered.encode("utf-8")


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _verify_pre_run_manifest() -> tuple[dict[str, Any], str]:
    path = RUN_DIR / "PRE_RUN_MANIFEST.json"
    manifest = _read_object(path)
    for entry in manifest["files"]:
        raw = (REPO_ROOT / entry["path"]).read_bytes()
        if len(raw) != entry["bytes"] or _sha256(raw) != entry["sha256"]:
            raise ValueError(f"frozen pre-run file changed: {entry['path']}")
    return manifest, _sha256(path.read_bytes())


def _alias_projection(sample: dict[str, Any]) -> dict[str, Any]:
    feature = sample["feature"]
    properties = feature["properties"]
    return {
        "catalog_ids": [
            value for value in properties["ids_raw"].split(",") if value
        ],
        "catalog_record_ref": feature["id"],
        "catalog_source_labels": [
            value for value in properties["sources_raw"].split(",") if value
        ],
        "catalog_updated_time_utc": properties["updated_utc"],
        "description": properties["place"],
        "magnitude": properties["mag"],
        "source_event_time_utc": properties["time_utc"],
    }


def _receipt_with_digest(receipt: dict[str, Any]) -> dict[str, Any]:
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    signed = dict(unsigned)
    signed["receipt_sha256"] = _sha256(_canonical_json_bytes(unsigned))
    return signed


def _validate_child_receipt(
    receipt: dict[str, Any] | None,
    *,
    parent_receipt: dict[str, Any],
    parent_sha256: str,
    expected_child_sha256: str,
    transform_sha256: str,
) -> tuple[str, list[str]]:
    if receipt is None:
        return "MISSING_PARENT_CHILD_RECEIPT", ["MISSING_CHILD_RECEIPT"]
    issues: list[str] = []
    unsigned = dict(receipt)
    claimed_receipt_sha = unsigned.pop("receipt_sha256", None)
    if claimed_receipt_sha != _sha256(_canonical_json_bytes(unsigned)):
        issues.append("RECEIPT_SELF_HASH_MISMATCH")
    if receipt.get("parent_receipt_id") != parent_receipt["receipt_id"]:
        issues.append("PARENT_RECEIPT_ID_UNKNOWN")
    if receipt.get("parent_record_id") != parent_receipt["record_id"]:
        issues.append("PARENT_RECORD_ID_UNKNOWN")
    if receipt.get("parent_sha256") != parent_sha256:
        issues.append("PARENT_HASH_MISMATCH")
    if receipt.get("child_sha256") != expected_child_sha256:
        issues.append("CHILD_HASH_MISMATCH")
    if receipt.get("transform_code_sha256") != transform_sha256:
        issues.append("TRANSFORM_CODE_HASH_MISMATCH")
    try:
        parent_time = datetime.fromisoformat(
            parent_receipt["received_at_utc"].replace("Z", "+00:00")
        )
        child_time = datetime.fromisoformat(
            receipt["generated_at_utc"].replace("Z", "+00:00")
        )
        if child_time < parent_time:
            issues.append("CHILD_RECEIPT_PRECEDES_LOCAL_PARENT_RECEIPT")
    except (KeyError, TypeError, ValueError):
        issues.append("INVALID_LOCAL_RECEIPT_TIME")
    if issues:
        return issues[0], issues
    return "PASS", []


def _validate_parent_receipt(
    receipt: dict[str, Any], *, expected_sha256: str, expected_length: int
) -> tuple[str, list[str]]:
    unsigned = dict(receipt)
    claimed_receipt_sha = unsigned.pop("receipt_sha256", None)
    issues: list[str] = []
    if claimed_receipt_sha != _sha256(_canonical_json_bytes(unsigned)):
        issues.append("PARENT_RECEIPT_SELF_HASH_MISMATCH")
    if receipt.get("file_sha256") != expected_sha256:
        issues.append("PARENT_FILE_HASH_MISMATCH")
    if receipt.get("byte_length") != expected_length:
        issues.append("PARENT_FILE_LENGTH_MISMATCH")
    if issues:
        return issues[0], issues
    return "PASS", []


def _lineage_evidence(source_ref: str, observed_at: str, trust: str) -> LineageEvidence:
    return LineageEvidence(
        source_ref=source_ref,
        actual_available_at=observed_at,
        earliest_known_at=observed_at,
        trust_status=trust,
        valid_until=None,
    )


def _contract_pair(
    *,
    local_file_sha: str,
    observed_at: str,
    child_receipt: dict[str, Any] | None,
    receipt_status: str,
) -> dict[str, Any]:
    source_node_id = "LOCAL-SAVED-SAMPLE-FILE"
    transform_node_id = "LOCAL-ALIAS-TRANSFORM-RUN"
    alias_node_id = "LOCAL-ALIAS-PAYLOAD"
    local_root = f"LOCAL-SAVED-FILE-SHA256-{local_file_sha}"
    source_node = LineageNode(
        node_id=source_node_id,
        node_type="LOCAL_SAVED_ARTIFACT",
        evidence=_lineage_evidence(
            f"local-file-sha256:{local_file_sha}", observed_at, "VERIFIED"
        ),
    )
    completeness = _lineage_evidence(
        "local-replay-receipt-validation:" + receipt_status,
        observed_at,
        "VERIFIED" if receipt_status == "PASS" else "UNVERIFIED",
    )
    left = ObservationLineage(
        observation_id="LOCAL-SAVED-USGS-NORMALIZED-SAMPLE",
        declared_root_id=local_root,
        terminal_node_id=source_node_id,
        trace_complete=True,
        completeness_evidence=completeness,
        nodes=(source_node,),
        edges=(),
    )

    if receipt_status == "PASS" and child_receipt is not None:
        transform_node = LineageNode(
            node_id=transform_node_id,
            node_type="LOCAL_TRANSFORM_RUN",
            evidence=_lineage_evidence(
                f"local-transform-sha256:{child_receipt['transform_code_sha256']}",
                observed_at,
                "VERIFIED",
            ),
        )
        alias_node = LineageNode(
            node_id=alias_node_id,
            node_type="LOCAL_ALIAS_OUTPUT",
            evidence=_lineage_evidence(
                f"local-alias-sha256:{child_receipt['child_sha256']}",
                observed_at,
                "VERIFIED",
            ),
        )
        receipt_ref = f"local-receipt-sha256:{child_receipt['receipt_sha256']}"
        left_edge = LineageEdge(
            edge_id="LOCAL-RECEIPT-EDGE-PARENT-TO-TRANSFORM",
            upstream_node_id=source_node_id,
            downstream_node_id=transform_node_id,
            evidence=_lineage_evidence(receipt_ref, observed_at, "VERIFIED"),
        )
        right_edge = LineageEdge(
            edge_id="LOCAL-RECEIPT-EDGE-TRANSFORM-TO-ALIAS",
            upstream_node_id=transform_node_id,
            downstream_node_id=alias_node_id,
            evidence=_lineage_evidence(receipt_ref, observed_at, "VERIFIED"),
        )
        right = ObservationLineage(
            observation_id="LOCAL-ALIAS-PROJECTION",
            declared_root_id=local_root,
            terminal_node_id=alias_node_id,
            trace_complete=True,
            completeness_evidence=completeness,
            nodes=(source_node, transform_node, alias_node),
            edges=(left_edge, right_edge),
        )
    else:
        alias_node = LineageNode(
            node_id=alias_node_id,
            node_type="LOCAL_ALIAS_OUTPUT",
            evidence=_lineage_evidence(
                "local-alias-bytes-without-valid-parent-receipt",
                observed_at,
                "UNVERIFIED",
            ),
        )
        right = ObservationLineage(
            observation_id="LOCAL-ALIAS-PROJECTION",
            declared_root_id=local_root,
            terminal_node_id=alias_node_id,
            trace_complete=False,
            completeness_evidence=completeness,
            nodes=(alias_node,),
            edges=(),
        )

    assessment = assess_source_lineage(left, right, as_of=observed_at)
    return {
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


def _render_svg(result: dict[str, Any]) -> str:
    replay_time = result["local_replay_received_at_utc"]
    hash_prefix = result["saved_sample"]["file_sha256"][:16]
    child_prefix = result["alias_payload"]["sha256"][:16]
    preserve = result["cases"]["lineage_preserved"]
    drop = result["cases"]["lineage_omitted"]
    forged = result["cases"]["forged_parent_link"]
    mismatch = result["cases"]["parent_hash_mismatch"]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1320" height="920" viewBox="0 0 1320 920" role="img" aria-labelledby="title desc">
<title id="title">Local controlled replay: lineage preserved versus omitted</title>
<desc id="desc">A saved normalized USGS sample is replayed locally with a new receipt time. The same alias bytes are processed with lineage retained or omitted. Forged-parent and hash-mismatch receipts are rejected. No original USGS response or historic receipt is claimed.</desc>
<rect width="1320" height="920" fill="#f5f7fb"/>
<text x="48" y="54" font-family="Arial, sans-serif" font-size="28" font-weight="700" fill="#17243b">本地受控回放：保留谱系与丢失谱系对照</text>
<text x="48" y="84" font-family="Arial, sans-serif" font-size="15" fill="#52627b">Saved normalized USGS sample · no new collection · no NWS access · no notification</text>
<rect x="48" y="108" width="1224" height="170" rx="14" fill="#ffffff" stroke="#d4deea"/>
<text x="76" y="145" font-family="Arial, sans-serif" font-size="19" font-weight="700" fill="#17243b">1 · 已保存文件（不是原始 USGS 响应）</text>
<text x="76" y="175" font-family="Arial, sans-serif" font-size="14" fill="#37475e">REAL_PUBLIC_FEED_SAMPLE.json · feature ci41346535 · {result['saved_sample']['byte_length']} bytes</text>
<text x="76" y="201" font-family="Arial, sans-serif" font-size="14" fill="#37475e">SHA-256: {hash_prefix}… · historical receive time: UNKNOWN</text>
<line x1="450" y1="194" x2="598" y2="194" stroke="#718096" stroke-width="3"/><polygon points="598,194 584,186 584,202" fill="#718096"/>
<rect x="620" y="126" width="590" height="110" rx="12" fill="#edf4fb"/>
<text x="642" y="157" font-family="Arial, sans-serif" font-size="15" font-weight="700" fill="#27527a">LOCAL REPLAY RECEIPT · {replay_time}</text>
<text x="642" y="184" font-family="Arial, sans-serif" font-size="13" fill="#344b66">New local clock time; not the source event/update/feed time</text>
<text x="642" y="208" font-family="Arial, sans-serif" font-size="13" fill="#344b66">Parent receipt binds file SHA and byte length</text>
<rect x="48" y="300" width="1224" height="249" rx="14" fill="#ffffff" stroke="#d4deea"/>
<text x="76" y="339" font-family="Arial, sans-serif" font-size="19" font-weight="700" fill="#17243b">2 · 同一字段投影，alias payload bytes 相同</text>
<text x="76" y="369" font-family="Arial, sans-serif" font-size="14" fill="#37475e">Child SHA-256: {child_prefix}… · transform code hash recorded in receipt · local replay only</text>
<rect x="76" y="396" width="538" height="126" rx="12" fill="#eaf6ef" stroke="#9acdb1"/>
<text x="98" y="428" font-family="Arial, sans-serif" font-size="15" font-weight="700" fill="#275c43">A · Parent / child receipt preserved</text>
<text x="98" y="456" font-family="Arial, sans-serif" font-size="14" fill="#275c43">Receipt hashes and parent-child IDs validate</text>
<text x="98" y="484" font-family="Arial, sans-serif" font-size="14" fill="#275c43">{preserve['lineage']['status']} · shared local file ancestor</text>
<rect x="644" y="396" width="566" height="126" rx="12" fill="#fff4dd" stroke="#e2c780"/>
<text x="666" y="428" font-family="Arial, sans-serif" font-size="15" font-weight="700" fill="#765600">B · Same alias bytes, receipts omitted</text>
<text x="666" y="456" font-family="Arial, sans-serif" font-size="14" fill="#765600">No parent-child edge submitted as complete</text>
<text x="666" y="484" font-family="Arial, sans-serif" font-size="14" fill="#765600">{drop['lineage']['status']} · TRACE_INCOMPLETE</text>
<rect x="48" y="570" width="1224" height="207" rx="14" fill="#ffffff" stroke="#d4deea"/>
<text x="76" y="608" font-family="Arial, sans-serif" font-size="19" font-weight="700" fill="#17243b">3 · 伪造 / 不一致回执负例</text>
<rect x="76" y="630" width="538" height="112" rx="12" fill="#fff0ee" stroke="#e9b7b0"/>
<text x="98" y="663" font-family="Arial, sans-serif" font-size="15" font-weight="700" fill="#8e3028">Forged parent link</text>
<text x="98" y="691" font-family="Arial, sans-serif" font-size="14" fill="#8e3028">{forged['receipt_validation']['status']}</text>
<text x="98" y="718" font-family="Arial, sans-serif" font-size="14" fill="#8e3028">Lineage: {forged['lineage']['status']}</text>
<rect x="644" y="630" width="566" height="112" rx="12" fill="#fff0ee" stroke="#e9b7b0"/>
<text x="666" y="663" font-family="Arial, sans-serif" font-size="15" font-weight="700" fill="#8e3028">Parent hash mismatch</text>
<text x="666" y="691" font-family="Arial, sans-serif" font-size="14" fill="#8e3028">{mismatch['receipt_validation']['status']}</text>
<text x="666" y="718" font-family="Arial, sans-serif" font-size="14" fill="#8e3028">Lineage: {mismatch['lineage']['status']}</text>
<rect x="48" y="800" width="1224" height="75" rx="14" fill="#eaf0f7" stroke="#cbd7e5"/>
<text x="76" y="831" font-family="Arial, sans-serif" font-size="14" font-weight="700" fill="#263850">Boundary: locally recomputed hashes support attribution to this saved file only.</text>
<text x="76" y="854" font-family="Arial, sans-serif" font-size="13" fill="#40536b">Unsigned local receipts do not prove USGS authenticity, historic receipt, transport integrity, source independence, risk confidence, or delivery.</text>
<text x="48" y="903" font-family="Arial, sans-serif" font-size="12" fill="#687891">Delivery: NOT_DELIVERED · event truth: NOT_EVALUATED · numeric risk-confidence delta: NOT_COMPUTED</text>
</svg>'''


def main() -> None:
    pre_manifest, pre_manifest_sha = _verify_pre_run_manifest()
    inputs = _read_object(RUN_DIR / "INPUTS.json")
    if inputs.get("status") != "FROZEN_PRE_RUN":
        raise ValueError("local replay inputs are not frozen")
    replay_received_at = _utc_now()
    source_path = REPO_ROOT / inputs["source_sample"]["path"]
    source_bytes = source_path.read_bytes()
    source_sha = _sha256(source_bytes)
    if len(source_bytes) != inputs["source_sample"]["exact_local_file_bytes_length"]:
        raise ValueError("saved normalized sample byte length differs from pre-run input")
    if source_sha != inputs["source_sample"]["exact_local_file_bytes_sha256"]:
        raise ValueError("saved normalized sample SHA-256 differs from pre-run input")
    sample = json.loads(source_bytes.decode("utf-8"))
    alias_payload = _alias_projection(sample)
    alias_bytes = _canonical_json_bytes(alias_payload, trailing_newline=True)
    alias_sha = _sha256(alias_bytes)
    transform_code_sha = _sha256(Path(__file__).read_bytes())
    receipt_issued_at = _utc_now()
    parent_receipt = {
        "receipt_id": "LOCAL-PARENT-RECEIPT-0001",
        "record_id": "LOCAL-SAVED-NORMALIZED-USGS-SAMPLE",
        "file_path": inputs["source_sample"]["path"],
        "file_sha256": source_sha,
        "byte_length": len(source_bytes),
        "received_at_utc": replay_received_at,
        "receipt_issuer": "LOCAL_CONTROLLED_REPLAY_RUNNER",
        "signature": None,
        "timestamp_semantics": "THIS_RUN_LOCAL_REPLAY_RECEIPT_NOT_HISTORICAL_SOURCE_RECEIVE_TIME",
    }
    parent_receipt = _receipt_with_digest(parent_receipt)
    parent_receipt_status, parent_receipt_issues = _validate_parent_receipt(
        parent_receipt, expected_sha256=source_sha, expected_length=len(source_bytes)
    )

    child_receipt_base = {
        "receipt_id": "LOCAL-CHILD-RECEIPT-PRESERVED-0001",
        "parent_receipt_id": parent_receipt["receipt_id"],
        "parent_record_id": parent_receipt["record_id"],
        "parent_sha256": source_sha,
        "child_record_id": "LOCAL-ALIAS-USGS-FEATURE-CI41346535",
        "child_sha256": alias_sha,
        "transform_id": inputs["transform"]["transform_id"],
        "transform_version": inputs["transform"]["version"],
        "transform_code_sha256": transform_code_sha,
        "generated_at_utc": receipt_issued_at,
        "receipt_issuer": "LOCAL_CONTROLLED_REPLAY_RUNNER",
        "signature": None,
        "timestamp_semantics": "THIS_RUN_LOCAL_TRANSFORM_TIME_NOT_HISTORICAL_SOURCE_RECEIVE_TIME",
    }
    preserved_receipt = _receipt_with_digest(child_receipt_base)
    forged_receipt = _receipt_with_digest(
        {**child_receipt_base, "receipt_id": "LOCAL-CHILD-RECEIPT-FORGED-0001", "parent_record_id": "ATTACKER-FORGED-PARENT"}
    )
    mismatch_receipt = _receipt_with_digest(
        {**child_receipt_base, "receipt_id": "LOCAL-CHILD-RECEIPT-MISMATCH-0001", "parent_sha256": "0" * 64}
    )

    transform_hashes = [entry["sha256"] for entry in pre_manifest["files"] if entry["path"].endswith("/run_local_replay.py")]
    if transform_hashes != [transform_code_sha]:
        raise ValueError("runner code hash is not the frozen pre-run runner hash")

    receipt_cases = {
        "lineage_preserved": _validate_child_receipt(
            preserved_receipt,
            parent_receipt=parent_receipt,
            parent_sha256=source_sha,
            expected_child_sha256=alias_sha,
            transform_sha256=transform_code_sha,
        ),
        "lineage_omitted": _validate_child_receipt(
            None,
            parent_receipt=parent_receipt,
            parent_sha256=source_sha,
            expected_child_sha256=alias_sha,
            transform_sha256=transform_code_sha,
        ),
        "forged_parent_link": _validate_child_receipt(
            forged_receipt,
            parent_receipt=parent_receipt,
            parent_sha256=source_sha,
            expected_child_sha256=alias_sha,
            transform_sha256=transform_code_sha,
        ),
        "parent_hash_mismatch": _validate_child_receipt(
            mismatch_receipt,
            parent_receipt=parent_receipt,
            parent_sha256=source_sha,
            expected_child_sha256=alias_sha,
            transform_sha256=transform_code_sha,
        ),
    }
    case_receipts = [
        parent_receipt,
        preserved_receipt,
        forged_receipt,
        mismatch_receipt,
    ]
    (RUN_DIR / "ALIAS_WITH_LINEAGE.json").write_bytes(alias_bytes)
    (RUN_DIR / "ALIAS_WITHOUT_LINEAGE.json").write_bytes(alias_bytes)
    (RUN_DIR / "LOCAL_RECEIPTS.json").write_text(
        json.dumps(
            {
                "artifact_classification": "LOCAL_UNSIGNED_REPLAY_RECEIPTS_NOT_SOURCE_AUTHENTICATION",
                "local_replay_received_at_utc": replay_received_at,
                "parent_receipt": parent_receipt,
                "child_receipts": case_receipts[1:],
                "omitted_lineage_arm": "No child receipt emitted; alias bytes equal the preserved arm.",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    as_of = receipt_issued_at
    lineage_cases: dict[str, dict[str, Any]] = {}
    for case_id, receipt_status in receipt_cases.items():
        if isinstance(receipt_status, tuple):
            status, issues = receipt_status
        else:
            raise TypeError("receipt validation did not return a status tuple")
        child_receipt = {
            "lineage_preserved": preserved_receipt,
            "lineage_omitted": None,
            "forged_parent_link": forged_receipt,
            "parent_hash_mismatch": mismatch_receipt,
        }[case_id]
        if case_id == "lineage_omitted":
            status = "MISSING_PARENT_CHILD_RECEIPT"
        lineage = _contract_pair(
            local_file_sha=source_sha,
            observed_at=as_of,
            child_receipt=child_receipt,
            receipt_status=status,
        )
        lineage_cases[case_id] = {
            "receipt_validation": {"status": status, "issues": issues},
            "lineage": lineage,
            "child_sha256": alias_sha,
            "child_byte_length": len(alias_bytes),
            "numeric_risk_confidence_delta": None,
        }

    checks = {
        "saved_normalized_file_hash_matches_frozen_input": source_sha == inputs["source_sample"]["exact_local_file_bytes_sha256"],
        "alias_payload_matches_frozen_projection": alias_payload == inputs["transform"]["expected_alias_payload"],
        "alias_payload_hash_matches_frozen_expectation": alias_sha == inputs["transform"]["expected_alias_payload_sha256"],
        "alias_payload_length_matches_frozen_expectation": len(alias_bytes) == inputs["transform"]["expected_alias_payload_byte_length"],
        "parent_receipt_matches_saved_bytes": parent_receipt_status == "PASS",
        "preserved_and_omitted_alias_hashes_equal": _sha256((RUN_DIR / "ALIAS_WITH_LINEAGE.json").read_bytes()) == _sha256((RUN_DIR / "ALIAS_WITHOUT_LINEAGE.json").read_bytes()),
        "preserved_receipt_chain_passes": lineage_cases["lineage_preserved"]["receipt_validation"]["status"] == "PASS",
        "preserved_lineage_is_local_shared_ancestor": lineage_cases["lineage_preserved"]["lineage"]["status"] == "SHARED_KNOWN_ANCESTOR" and lineage_cases["lineage_preserved"]["lineage"]["shared_ancestor_node_ids"] == ["LOCAL-SAVED-SAMPLE-FILE"],
        "omitted_lineage_fails_closed": lineage_cases["lineage_omitted"]["receipt_validation"]["status"] == "MISSING_PARENT_CHILD_RECEIPT" and lineage_cases["lineage_omitted"]["lineage"]["status"] == "UNKNOWN",
        "forged_parent_link_fails_closed": lineage_cases["forged_parent_link"]["receipt_validation"]["status"] == "PARENT_RECORD_ID_UNKNOWN" and lineage_cases["forged_parent_link"]["lineage"]["status"] == "UNKNOWN",
        "parent_hash_mismatch_fails_closed": lineage_cases["parent_hash_mismatch"]["receipt_validation"]["status"] == "PARENT_HASH_MISMATCH" and lineage_cases["parent_hash_mismatch"]["lineage"]["status"] == "UNKNOWN",
        "independence_never_asserted": all(case["lineage"]["statistical_independence_established"] is False for case in lineage_cases.values()),
    }
    expected = {item["case_id"]: item for item in inputs["comparison_arms"] + inputs["negative_controls"]}
    checks["lineage_states_match_frozen_expectations"] = all(
        lineage_cases[case_id]["lineage"]["status"] == item["expected_lineage_status"]
        for case_id, item in expected.items()
    )
    checks["receipt_states_match_frozen_expectations"] = all(
        lineage_cases[case_id]["receipt_validation"]["status"] == item["expected_receipt_validation"]
        for case_id, item in expected.items()
    )
    checks["preserved_root_and_edge_fields_match_frozen_expectations"] = (
        lineage_cases["lineage_preserved"]["lineage"]["declared_root_id_relation"]
        == expected["lineage_preserved"]["expected_root_relation"]
        and lineage_cases["lineage_preserved"]["lineage"]["shared_ancestor_node_ids"]
        == expected["lineage_preserved"]["expected_shared_ancestor_ids"]
        and lineage_cases["lineage_preserved"]["lineage"]["unique_edge_count"]
        == expected["lineage_preserved"]["expected_unique_edge_count"]
    )
    checks["unknown_cases_report_frozen_reason"] = all(
        item.get("expected_reason_code")
        in lineage_cases[item["case_id"]]["lineage"]["reason_codes"]
        for item in expected.values()
        if "expected_reason_code" in item
    )
    all_passed = all(checks.values())
    method_outputs = {
        case_id: case["lineage"] for case_id, case in lineage_cases.items()
    }
    method_outputs_hash = _sha256(_canonical_json_bytes(method_outputs))
    result = {
        "run_id": inputs["run_id"],
        "run_status": "COMPLETED_LOCAL_CONTROLLED_REPLAY" if all_passed else "FROZEN_CHECK_FAILED",
        "classification": inputs["classification"],
        "pre_run_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip(),
        "method_source_commit": pre_manifest["source_code_commit"],
        "pre_run_manifest_sha256": pre_manifest_sha,
        "inputs_sha256": _sha256((RUN_DIR / "INPUTS.json").read_bytes()),
        "method_outputs_sha256_before_expectation_checks": method_outputs_hash,
        "network_or_model_called": False,
        "nws_endpoint_accessed": False,
        "notification_created": False,
        "delivery_status": "NOT_DELIVERED",
        "event_identity_status": "NOT_EVALUATED",
        "numeric_risk_confidence": "NOT_COMPUTED",
        "saved_sample": {
            "classification": "REAL_PUBLIC_SAMPLE_NORMALIZED_EXTRACT",
            "path": inputs["source_sample"]["path"],
            "feature_id": inputs["source_sample"]["feature_id"],
            "file_sha256": source_sha,
            "byte_length": len(source_bytes),
            "original_usgs_response_bytes_available": False,
            "original_response_sha256": None,
            "historical_source_or_collector_received_at": "UNKNOWN_NOT_IN_SAVED_SAMPLE",
        },
        "local_replay_received_at_utc": replay_received_at,
        "local_receipts_issued_at_utc": receipt_issued_at,
        "receipt_authenticity": "UNSIGNED_LOCAL_RUNNER_ASSERTION; digest/link checks do not prove source authenticity or historical transport.",
        "alias_payload": {
            "preserved_path": str((RUN_DIR / "ALIAS_WITH_LINEAGE.json").relative_to(REPO_ROOT)),
            "omitted_path": str((RUN_DIR / "ALIAS_WITHOUT_LINEAGE.json").relative_to(REPO_ROOT)),
            "sha256": alias_sha,
            "byte_length": len(alias_bytes),
            "same_bytes_in_both_arms": True,
            "transform_code_sha256": transform_code_sha,
        },
        "parent_receipt_id": parent_receipt["receipt_id"],
        "parent_receipt_validation": {"status": parent_receipt_status, "issues": parent_receipt_issues},
        "receipt_artifact_path": str((RUN_DIR / "LOCAL_RECEIPTS.json").relative_to(REPO_ROOT)),
        "cases": lineage_cases,
        "checks_after_method_output_freeze": checks,
        "all_frozen_checks_passed": all_passed,
        "interpretation": {
            "preserved_lineage": "Attributable to this locally saved normalized file under unsigned in-run receipt/hash assumptions only.",
            "omitted_or_invalid_lineage": "UNKNOWN; the same alias bytes do not constitute an independent source.",
            "risk_fusion": "No numeric confidence or D-S combination was computed.",
        },
    }
    (RUN_DIR / "RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (RUN_DIR / "VISUALIZATION.svg").write_text(
        _render_svg(result), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "run_status": result["run_status"],
                "local_replay_received_at_utc": replay_received_at,
                "saved_sample_sha256": source_sha,
                "alias_sha256": alias_sha,
                "method_outputs_sha256": method_outputs_hash,
                "checks": checks,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not all_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
