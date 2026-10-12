"""One deterministic two-hop synthetic replay over an existing saved sample."""

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
BASE_UTC = "2000-01-01T00:00:00Z"
AS_OF_UTC = "2000-01-01T00:00:03Z"


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def verify_pre_run_manifest() -> tuple[dict[str, Any], str]:
    path = RUN_DIR / "PRE_RUN_MANIFEST.json"
    manifest = read_json(path)
    for entry in manifest["files"]:
        raw = (REPO_ROOT / entry["path"]).read_bytes()
        if len(raw) != entry["bytes"] or sha256(raw) != entry["sha256"]:
            raise ValueError(f"frozen pre-run file changed: {entry['path']}")
    return manifest, sha256(path.read_bytes())


def receipt_digest(receipt: dict[str, Any]) -> dict[str, Any]:
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    return {**unsigned, "receipt_sha256": sha256(canonical_json_bytes(unsigned))}


def validate_receipt(
    receipt: dict[str, Any] | None,
    *,
    parent_id: str,
    parent_sha256: str,
    child_id: str,
    child_sha256: str,
    transform_id: str,
    transform_code_sha256: str,
) -> str:
    if receipt is None:
        return "MISSING_RECEIPT"
    unsigned = dict(receipt)
    claimed = unsigned.pop("receipt_sha256", None)
    if claimed != sha256(canonical_json_bytes(unsigned)):
        return "RECEIPT_HASH_MISMATCH"
    if receipt.get("parent_observation_id") != parent_id:
        return "PARENT_ID_MISMATCH"
    if receipt.get("parent_sha256") != parent_sha256:
        return "PARENT_HASH_MISMATCH"
    if receipt.get("child_observation_id") != child_id:
        return "CHILD_ID_MISMATCH"
    if receipt.get("child_sha256") != child_sha256:
        return "CHILD_HASH_MISMATCH"
    if receipt.get("transform_id") != transform_id:
        return "TRANSFORM_ID_MISMATCH"
    if receipt.get("transform_code_sha256") != transform_code_sha256:
        return "TRANSFORM_CODE_HASH_MISMATCH"
    return "PASS_LOCAL_RUNNER_CONSISTENCY"


def local_evidence(source_ref: str, known_at: str, *, trust: str = "VERIFIED") -> LineageEvidence:
    return LineageEvidence(
        source_ref=source_ref,
        actual_available_at=known_at,
        earliest_known_at=known_at,
        trust_status=trust,
        valid_until=None,
    )


def node(
    node_id: str,
    node_type: str,
    ref: str,
    *,
    trust: str = "VERIFIED",
    known_at: str = BASE_UTC,
) -> LineageNode:
    return LineageNode(
        node_id=node_id,
        node_type=node_type,
        evidence=local_evidence(ref, known_at, trust=trust),
    )


def edge(
    edge_id: str,
    upstream: str,
    downstream: str,
    receipt_id: str,
    *,
    known_at: str,
) -> LineageEdge:
    return LineageEdge(
        edge_id=edge_id,
        upstream_node_id=upstream,
        downstream_node_id=downstream,
        evidence=local_evidence(f"synthetic-local-receipt:{receipt_id}", known_at),
    )


def lineage(
    observation_id: str,
    terminal: str,
    nodes: tuple[LineageNode, ...],
    edges: tuple[LineageEdge, ...],
    *,
    complete: bool,
    completeness_known_at: str = BASE_UTC,
    root_id: str = "SYNTHETIC-ROOT-001",
) -> ObservationLineage:
    completeness_trust = "VERIFIED" if complete else "UNVERIFIED"
    return ObservationLineage(
        observation_id=observation_id,
        declared_root_id=root_id,
        terminal_node_id=terminal,
        trace_complete=complete,
        completeness_evidence=local_evidence(
            f"synthetic-trace-completeness:{observation_id}:{complete}",
            completeness_known_at,
            trust=completeness_trust,
        ),
        nodes=nodes,
        edges=edges,
    )


def assessment(left: ObservationLineage, right: ObservationLineage) -> dict[str, Any]:
    value = assess_source_lineage(left, right, as_of=AS_OF_UTC)
    return {
        "lineage_status": value.status.value,
        "root_id_relation": value.declared_root_id_relation.value,
        "shared_ancestor_node_ids": list(value.shared_ancestor_node_ids),
        "reason_codes": list(value.reason_codes),
        "unique_edge_count": value.unique_edge_count,
        "statistical_independence_established": value.statistical_independence_established,
    }


def main() -> None:
    pre_manifest, pre_manifest_sha256 = verify_pre_run_manifest()
    inputs = read_json(RUN_DIR / "INPUTS.json")
    if inputs.get("status") != "FROZEN_PRE_RUN":
        raise ValueError("inputs are not frozen")

    execution_started_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    source_path = REPO_ROOT / inputs["source_sample"]["path"]
    source_bytes = source_path.read_bytes()
    source_sha = sha256(source_bytes)
    if len(source_bytes) != inputs["source_sample"]["bytes"]:
        raise ValueError("saved normalized source byte length changed")
    if source_sha != inputs["source_sample"]["sha256"]:
        raise ValueError("saved normalized source hash changed")
    sample = json.loads(source_bytes.decode("utf-8"))
    feature = sample["feature"]
    properties = feature["properties"]
    source_id = feature["id"]
    source_projection_keys = sorted(properties)
    runner_code_sha256 = sha256(Path(__file__).read_bytes())

    hop1 = {
        "artifact_kind": "CONTROLLED_SYNTHETIC_ALIAS",
        "synthetic": True,
        "observation_id": "HOP1",
        "outer_id": f"relay-one/{source_id}",
        "projection": {
            "record_ref": source_id,
            "magnitude_value": properties["mag"],
            "location_text": properties["place"],
            "event_timestamp": properties["time_utc"],
        },
    }
    hop1_bytes = canonical_json_bytes(hop1)
    hop1_sha = sha256(hop1_bytes)

    hop2 = {
        "artifact_kind": "CONTROLLED_SYNTHETIC_ALIAS",
        "synthetic": True,
        "observation_id": "HOP2",
        "outer_id": f"relay-two::{hop1['outer_id']}",
        "projection": {
            "source_alias": hop1["outer_id"],
            "summary": f"{hop1['projection']['magnitude_value']} M · {hop1['projection']['location_text']}",
            "updated_epoch_ms": properties["updated_epoch_ms"],
        },
    }
    hop2_bytes = canonical_json_bytes(hop2)
    hop2_sha = sha256(hop2_bytes)
    (RUN_DIR / "ALIAS_HOP1.json").write_bytes(hop1_bytes)
    (RUN_DIR / "ALIAS_HOP2.json").write_bytes(hop2_bytes)

    receipt1 = receipt_digest({
        "receipt_id": "RECEIPT-HOP1",
        "parent_observation_id": "SOURCE",
        "parent_sha256": source_sha,
        "child_observation_id": "HOP1",
        "child_sha256": hop1_sha,
        "transform_id": "SYNTHETIC-RELAY-ONE-V1",
        "transform_code_sha256": runner_code_sha256,
        "generated_at_utc": "2000-01-01T00:00:01Z",
        "issuer": "LOCAL_CONTROLLED_SYNTHETIC_RUNNER",
        "signature": None,
    })
    receipt2 = receipt_digest({
        "receipt_id": "RECEIPT-HOP2",
        "parent_observation_id": "HOP1",
        "parent_sha256": hop1_sha,
        "child_observation_id": "HOP2",
        "child_sha256": hop2_sha,
        "transform_id": "SYNTHETIC-RELAY-TWO-V1",
        "transform_code_sha256": runner_code_sha256,
        "generated_at_utc": "2000-01-01T00:00:02Z",
        "issuer": "LOCAL_CONTROLLED_SYNTHETIC_RUNNER",
        "signature": None,
    })
    validation1 = validate_receipt(
        receipt1, parent_id="SOURCE", parent_sha256=source_sha,
        child_id="HOP1", child_sha256=hop1_sha,
        transform_id="SYNTHETIC-RELAY-ONE-V1",
        transform_code_sha256=runner_code_sha256,
    )
    validation2 = validate_receipt(
        receipt2, parent_id="HOP1", parent_sha256=hop1_sha,
        child_id="HOP2", child_sha256=hop2_sha,
        transform_id="SYNTHETIC-RELAY-TWO-V1",
        transform_code_sha256=runner_code_sha256,
    )

    source_node = node("NODE-SOURCE", "SAVED_NORMALIZED_SAMPLE", f"local-file-sha256:{source_sha}")
    hop1_transform = node("NODE-TRANSFORM-1", "LOCAL_TRANSFORM", f"synthetic-transform:{receipt1['transform_id']}", known_at="2000-01-01T00:00:01Z")
    hop1_node = node("NODE-HOP1", "SYNTHETIC_ALIAS", f"synthetic-alias-sha256:{hop1_sha}", known_at="2000-01-01T00:00:01Z")
    hop2_transform = node("NODE-TRANSFORM-2", "LOCAL_TRANSFORM", f"synthetic-transform:{receipt2['transform_id']}", known_at="2000-01-01T00:00:02Z")
    hop2_node = node("NODE-HOP2", "SYNTHETIC_ALIAS", f"synthetic-alias-sha256:{hop2_sha}", known_at="2000-01-01T00:00:02Z")
    source_to_transform1 = edge("EDGE-SOURCE-TRANSFORM1", "NODE-SOURCE", "NODE-TRANSFORM-1", "RECEIPT-HOP1", known_at="2000-01-01T00:00:01Z")
    transform1_to_hop1 = edge("EDGE-TRANSFORM1-HOP1", "NODE-TRANSFORM-1", "NODE-HOP1", "RECEIPT-HOP1", known_at="2000-01-01T00:00:01Z")
    hop1_to_transform2 = edge("EDGE-HOP1-TRANSFORM2", "NODE-HOP1", "NODE-TRANSFORM-2", "RECEIPT-HOP2", known_at="2000-01-01T00:00:02Z")
    transform2_to_hop2 = edge("EDGE-TRANSFORM2-HOP2", "NODE-TRANSFORM-2", "NODE-HOP2", "RECEIPT-HOP2", known_at="2000-01-01T00:00:02Z")

    source_lineage = lineage("SOURCE", "NODE-SOURCE", (source_node,), (), complete=True)
    hop1_lineage = lineage(
        "HOP1", "NODE-HOP1", (source_node, hop1_transform, hop1_node),
        (source_to_transform1, transform1_to_hop1), complete=validation1 == "PASS_LOCAL_RUNNER_CONSISTENCY",
        completeness_known_at="2000-01-01T00:00:01Z",
    )
    hop2_full_lineage = lineage(
        "HOP2", "NODE-HOP2",
        (source_node, hop1_transform, hop1_node, hop2_transform, hop2_node),
        (source_to_transform1, transform1_to_hop1, hop1_to_transform2, transform2_to_hop2),
        complete=validation1 == "PASS_LOCAL_RUNNER_CONSISTENCY" and validation2 == "PASS_LOCAL_RUNNER_CONSISTENCY",
        completeness_known_at="2000-01-01T00:00:02Z",
    )
    hop2_incomplete_lineage = lineage(
        "HOP2", "NODE-HOP2", (hop2_node,), (), complete=False,
        completeness_known_at="2000-01-01T00:00:02Z",
    )
    pairs = (("SOURCE/HOP1", "SOURCE", "HOP1"), ("SOURCE/HOP2", "SOURCE", "HOP2"), ("HOP1/HOP2", "HOP1", "HOP2"))

    observations = {
        "SOURCE": source_lineage,
        "HOP1": hop1_lineage,
        "HOP2_FULL": hop2_full_lineage,
        "HOP2_INCOMPLETE": hop2_incomplete_lineage,
    }
    full_pair_rows = []
    missing_pair_rows = []
    for pair_id, left_id, right_id in pairs:
        full_pair_rows.append({
            "pair_id": pair_id,
            **assessment(observations[left_id], observations["HOP2_FULL"] if right_id == "HOP2" else observations[right_id]),
        })
        missing_pair_rows.append({
            "pair_id": pair_id,
            **assessment(observations[left_id], observations["HOP2_INCOMPLETE"] if right_id == "HOP2" else observations[right_id]),
        })

    payload_hashes = {"SOURCE": source_sha, "HOP1": hop1_sha, "HOP2": hop2_sha}
    hash_pairs = []
    for pair_id, left_id, right_id in pairs:
        hash_pairs.append({
            "pair_id": pair_id,
            "dedup_outcome": "SAME_HASH_BUCKET" if payload_hashes[left_id] == payload_hashes[right_id] else "DISTINCT_HASH_BUCKETS",
            "left_sha256": payload_hashes[left_id],
            "right_sha256": payload_hashes[right_id],
        })

    output = {
        "run_id": inputs["run_id"],
        "classification": inputs["classification"],
        "world_id": inputs["split"]["name"],
        "source_anchor": {
            "observation_id": "SOURCE",
            "classification": "SAVED_NORMALIZED_PUBLIC_SAMPLE_NOT_RAW_RESPONSE",
            "sha256": source_sha,
            "byte_length": len(source_bytes),
            "projection_keys": source_projection_keys,
            "historical_receiver_time": "UNKNOWN_NOT_IN_SAVED_SAMPLE",
        },
        "runner_code_sha256": runner_code_sha256,
        "synthetic_aliases": [
            {"observation_id": "HOP1", "outer_id": hop1["outer_id"], "projection_keys": sorted(hop1["projection"]), "sha256": hop1_sha, "byte_length": len(hop1_bytes)},
            {"observation_id": "HOP2", "outer_id": hop2["outer_id"], "projection_keys": sorted(hop2["projection"]), "sha256": hop2_sha, "byte_length": len(hop2_bytes)},
        ],
        "receipts": [receipt1, receipt2],
        "receipt_authenticity": "UNSIGNED_LOCAL_RUNNER_ASSERTIONS; PASS means internal IDs/hashes/transform references are consistent under this controlled runner only.",
        "conditions": {
            "FULL_RECEIPT_CHAIN": {
                "available_receipt_ids": ["RECEIPT-HOP1", "RECEIPT-HOP2"],
                "receipt_statuses": [validation1, validation2],
                "pair_results": full_pair_rows,
            },
            "MISSING_INTERMEDIATE_RECEIPT": {
                "available_receipt_ids": ["RECEIPT-HOP1"],
                "omitted_receipt_id": "RECEIPT-HOP2",
                "receipt_statuses": [validation1, "MISSING_RECEIPT"],
                "pair_results": missing_pair_rows,
            },
            "HASH_ONLY_DEDUP": {
                "available_receipt_ids": [],
                "distinct_hash_bucket_count": len(set(payload_hashes.values())),
                "pair_results": hash_pairs,
            },
        },
        "independence_established": False,
        "event_identity_status": "NOT_EVALUATED",
        "delivery_status": "NOT_DELIVERED",
        "production_truth_denominator": "UNAVAILABLE",
    }
    output_bytes = json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    outputs_path = RUN_DIR / "METHOD_OUTPUTS.json"
    outputs_path.write_bytes(output_bytes)
    frozen_hash = sha256(output_bytes)
    (RUN_DIR / "METHOD_OUTPUT_FREEZE.json").write_text(
        json.dumps({
            "run_id": inputs["run_id"],
            "freeze_sequence": "METHOD_OUTPUTS_WRITTEN_AND_HASHED_BEFORE_EXPECTATION_COMPARISON",
            "method_outputs_path": str(outputs_path.relative_to(REPO_ROOT)),
            "bytes": len(output_bytes),
            "sha256": frozen_hash,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    expected = inputs["expected_output_checks"]
    checks = {
        "source_sample_hash_matches_frozen_input": source_sha == inputs["source_sample"]["sha256"],
        "all_three_payload_hashes_distinct": len(set(payload_hashes.values())) == 3,
        "outer_id_changes_at_each_hop": len({source_id, hop1["outer_id"], hop2["outer_id"]}) == 3,
        "projection_key_sets_change_at_each_hop": len({tuple(source_projection_keys), tuple(sorted(hop1["projection"])), tuple(sorted(hop2["projection"]))}) == 3,
        "full_receipts_pass_local_runner_consistency": [validation1, validation2] == expected["full_receipt_statuses"],
        "full_receipt_pair_states_match_frozen_expectations": {r["pair_id"]: r["lineage_status"] for r in full_pair_rows} == inputs["conditions"][0]["expected_pair_statuses"],
        "missing_hop2_receipt_is_unknown_for_hop2_pairs": {r["pair_id"]: r["lineage_status"] for r in missing_pair_rows} == inputs["conditions"][1]["expected_pair_statuses"],
        "missing_hop2_receipt_status_matches_frozen_expectation": "MISSING_RECEIPT" == expected["missing_hop2_status"],
        "hash_only_bucket_count_matches_frozen_expectation": len(set(payload_hashes.values())) == expected["hash_only_bucket_count"],
        "independence_not_asserted": output["independence_established"] is False and all(not r.get("statistical_independence_established", False) for r in full_pair_rows + missing_pair_rows),
    }
    checks["all_frozen_expectation_checks_passed"] = all(checks.values())
    (RUN_DIR / "RUNNER_CHECKS.json").write_text(
        json.dumps({
            "run_id": inputs["run_id"],
            "pre_run_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip(),
            "pre_run_manifest_sha256": sha256((RUN_DIR / "PRE_RUN_MANIFEST.json").read_bytes()),
            "method_outputs_sha256_at_freeze": frozen_hash,
            "execution_started_at_utc": execution_started_at,
            "method_runner_read_truth_log": False,
            "network_or_model_or_notification_called": False,
            "checks": checks,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "run_id": inputs["run_id"],
        "method_outputs_sha256_at_freeze": frozen_hash,
        "checks": checks,
    }, ensure_ascii=False, indent=2))
    if not checks["all_frozen_expectation_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
