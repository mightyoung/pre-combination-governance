"""Frozen V2 one-chain synthetic replay with declared transform inputs."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import inspect
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
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def verify_pre_run_manifest() -> tuple[dict[str, Any], str]:
    path = RUN_DIR / "PRE_RUN_MANIFEST_V2.json"
    manifest = read_json(path)
    for entry in manifest["files"]:
        data = (REPO_ROOT / entry["path"]).read_bytes()
        if len(data) != entry["bytes"] or sha256(data) != entry["sha256"]:
            raise ValueError(f"frozen method file changed: {entry['path']}")
    return manifest, sha256(path.read_bytes())


def transform_hop1_from_saved_sample(sample: dict[str, Any]) -> dict[str, Any]:
    feature = sample["feature"]
    props = feature["properties"]
    return {
        "artifact_kind": "CONTROLLED_SYNTHETIC_ALIAS",
        "synthetic": True,
        "observation_id": "HOP1",
        "outer_id": f"relay-one/{feature['id']}",
        "projection": {
            "record_ref": feature["id"],
            "magnitude_value": props["mag"],
            "location_text": props["place"],
            "event_timestamp": props["time_utc"],
            "updated_epoch_ms": props["updated_epoch_ms"],
            "source_namespace": props["net"],
        },
    }


def transform_hop2_from_persisted_hop1(persisted_hop1_bytes: bytes) -> dict[str, Any]:
    """One input only: exact bytes reread from the persisted Hop 1 artifact."""
    hop1 = json.loads(persisted_hop1_bytes.decode("utf-8"))
    projection = hop1["projection"]
    return {
        "artifact_kind": "CONTROLLED_SYNTHETIC_ALIAS",
        "synthetic": True,
        "observation_id": "HOP2",
        "outer_id": f"relay-two::{hop1['outer_id']}",
        "projection": {
            "source_alias": hop1["outer_id"],
            "summary": f"{projection['magnitude_value']} M · {projection['location_text']}",
            "updated_epoch_ms": projection["updated_epoch_ms"],
            "source_namespace": projection["source_namespace"],
        },
    }


def defective_hop2_with_unreported_source_side_input(
    persisted_hop1_bytes: bytes,
    source_namespace_side_input: str,
) -> dict[str, Any]:
    """Deliberate negative control: reads SOURCE outside its declared HOP1 parent."""
    hop1 = json.loads(persisted_hop1_bytes.decode("utf-8"))
    projection = hop1["projection"]
    return {
        "artifact_kind": "CONTROLLED_SYNTHETIC_NEGATIVE_CONTROL",
        "synthetic": True,
        "observation_id": "HOP2-SIDEINPUT-NEGATIVE",
        "outer_id": f"relay-two-sideinput::{hop1['outer_id']}",
        "projection": {
            "source_alias": hop1["outer_id"],
            "summary": f"{projection['magnitude_value']} M · {projection['location_text']}",
            "updated_epoch_ms": projection["updated_epoch_ms"],
            "source_namespace": source_namespace_side_input,
        },
    }


def receipt_with_digest(value: dict[str, Any]) -> dict[str, Any]:
    unsigned = dict(value)
    unsigned.pop("receipt_sha256", None)
    return {**unsigned, "receipt_sha256": sha256(canonical_json_bytes(unsigned))}


def validate_receipt(
    receipt: dict[str, Any] | None,
    *,
    observed_inputs: list[dict[str, str]],
    expected_child_id: str,
    expected_child_sha256: str,
    expected_transform_id: str,
    expected_transform_code_sha256: str,
) -> str:
    if receipt is None:
        return "MISSING_RECEIPT"
    unsigned = dict(receipt)
    supplied_digest = unsigned.pop("receipt_sha256", None)
    if supplied_digest != sha256(canonical_json_bytes(unsigned)):
        return "RECEIPT_HASH_MISMATCH"
    if receipt.get("child_observation_id") != expected_child_id:
        return "CHILD_ID_MISMATCH"
    if receipt.get("child_sha256") != expected_child_sha256:
        return "CHILD_HASH_MISMATCH"
    if receipt.get("transform_id") != expected_transform_id:
        return "TRANSFORM_ID_MISMATCH"
    if receipt.get("transform_code_sha256") != expected_transform_code_sha256:
        return "TRANSFORM_CODE_HASH_MISMATCH"
    declared = receipt.get("declared_inputs")
    if not isinstance(declared, list):
        return "INVALID_DECLARED_INPUTS"
    if sorted(declared, key=lambda item: (item.get("observation_id", ""), item.get("sha256", ""))) != sorted(
        observed_inputs,
        key=lambda item: (item.get("observation_id", ""), item.get("sha256", "")),
    ):
        return "UNDECLARED_SIDE_INPUT"
    return "PASS_LOCAL_RUNNER_CONSISTENCY"


def make_evidence(ref: str, at: str, trust: str = "VERIFIED") -> LineageEvidence:
    return LineageEvidence(
        source_ref=ref,
        actual_available_at=at,
        earliest_known_at=at,
        trust_status=trust,
        valid_until=None,
    )


def make_node(node_id: str, node_type: str, ref: str, at: str = BASE_UTC) -> LineageNode:
    return LineageNode(node_id, node_type, make_evidence(ref, at))


def make_edge(edge_id: str, upstream: str, downstream: str, receipt_id: str, at: str) -> LineageEdge:
    return LineageEdge(
        edge_id,
        upstream,
        downstream,
        make_evidence(f"synthetic-local-receipt:{receipt_id}", at),
    )


def make_lineage(
    observation_id: str,
    terminal: str,
    nodes: tuple[LineageNode, ...],
    edges: tuple[LineageEdge, ...],
    *,
    complete: bool,
    completeness_at: str = BASE_UTC,
) -> ObservationLineage:
    return ObservationLineage(
        observation_id=observation_id,
        declared_root_id="SYNTHETIC-ROOT-001",
        terminal_node_id=terminal,
        trace_complete=complete,
        completeness_evidence=make_evidence(
            f"synthetic-completeness:{observation_id}:{complete}",
            completeness_at,
            "VERIFIED" if complete else "UNVERIFIED",
        ),
        nodes=nodes,
        edges=edges,
    )


def assess_pair(left: ObservationLineage, right: ObservationLineage) -> dict[str, Any]:
    result = assess_source_lineage(left, right, as_of=AS_OF_UTC)
    return {
        "lineage_status": result.status.value,
        "shared_ancestor_node_ids": list(result.shared_ancestor_node_ids),
        "reason_codes": list(result.reason_codes),
        "unique_edge_count": result.unique_edge_count,
        "statistical_independence_established": result.statistical_independence_established,
    }


def hash_only_observation(left_sha: str, right_sha: str) -> dict[str, str]:
    relation = "BYTE_IDENTICAL_ONLY" if left_sha == right_sha else "BYTE_DIFFERENT_ONLY"
    reason = "HASH_EQUAL_NO_PROVENANCE" if left_sha == right_sha else "HASH_DIFFERENT_NO_PROVENANCE"
    return {"byte_relation": relation, "lineage_status": "UNKNOWN", "reason": reason}


def main() -> None:
    pre_manifest, pre_manifest_hash = verify_pre_run_manifest()
    inputs = read_json(RUN_DIR / "INPUTS_V2.json")
    if inputs.get("status") != "FROZEN_PRE_RUN":
        raise ValueError("V2 inputs are not frozen")
    started_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    source_path = REPO_ROOT / inputs["source_sample"]["path"]
    source_bytes = source_path.read_bytes()
    source_sha = sha256(source_bytes)
    if len(source_bytes) != inputs["source_sample"]["bytes"] or source_sha != inputs["source_sample"]["sha256"]:
        raise ValueError("saved normalized source no longer matches frozen input")
    sample = json.loads(source_bytes.decode("utf-8"))
    runner_code_sha = sha256(Path(__file__).read_bytes())

    hop1 = transform_hop1_from_saved_sample(sample)
    hop1_bytes = canonical_json_bytes(hop1)
    hop1_path = RUN_DIR / "ALIAS_HOP1_V2.json"
    hop1_path.write_bytes(hop1_bytes)
    persisted_hop1_bytes = hop1_path.read_bytes()
    hop1_sha = sha256(persisted_hop1_bytes)
    if hop1_sha != sha256(hop1_bytes):
        raise ValueError("persisted Hop 1 bytes differ from generated Hop 1 bytes")

    # The valid Hop 2 transform receives no source object or side input.
    if list(inspect.signature(transform_hop2_from_persisted_hop1).parameters) != ["persisted_hop1_bytes"]:
        raise ValueError("Hop 2 transform signature changed from the frozen one-input contract")
    hop2_input_record = {"observation_id": "HOP1", "sha256": hop1_sha}
    hop2 = transform_hop2_from_persisted_hop1(persisted_hop1_bytes)
    hop2_bytes = canonical_json_bytes(hop2)
    hop2_path = RUN_DIR / "ALIAS_HOP2_V2.json"
    hop2_path.write_bytes(hop2_bytes)
    hop2_sha = sha256(hop2_bytes)

    source_record = {"observation_id": "SOURCE", "sha256": source_sha}
    receipt1 = receipt_with_digest({
        "receipt_id": "RECEIPT-HOP1-V2",
        "child_observation_id": "HOP1",
        "child_sha256": hop1_sha,
        "transform_id": "SYNTHETIC-RELAY-ONE-V2",
        "transform_code_sha256": runner_code_sha,
        "declared_inputs": [source_record],
        "generated_at_utc": "2000-01-01T00:00:01Z",
        "issuer": "LOCAL_CONTROLLED_SYNTHETIC_RUNNER",
        "signature": None,
    })
    receipt2 = receipt_with_digest({
        "receipt_id": "RECEIPT-HOP2-V2",
        "child_observation_id": "HOP2",
        "child_sha256": hop2_sha,
        "transform_id": "SYNTHETIC-RELAY-TWO-V2",
        "transform_code_sha256": runner_code_sha,
        "declared_inputs": [hop2_input_record],
        "generated_at_utc": "2000-01-01T00:00:02Z",
        "issuer": "LOCAL_CONTROLLED_SYNTHETIC_RUNNER",
        "signature": None,
    })
    receipt1_status = validate_receipt(
        receipt1, observed_inputs=[source_record], expected_child_id="HOP1",
        expected_child_sha256=hop1_sha, expected_transform_id="SYNTHETIC-RELAY-ONE-V2",
        expected_transform_code_sha256=runner_code_sha,
    )
    receipt2_status = validate_receipt(
        receipt2, observed_inputs=[hop2_input_record], expected_child_id="HOP2",
        expected_child_sha256=hop2_sha, expected_transform_id="SYNTHETIC-RELAY-TWO-V2",
        expected_transform_code_sha256=runner_code_sha,
    )

    props = sample["feature"]["properties"]
    bad_hop2 = defective_hop2_with_unreported_source_side_input(
        persisted_hop1_bytes,
        str(props["net"]).upper(),
    )
    bad_hop2_bytes = canonical_json_bytes(bad_hop2)
    bad_hop2_sha = sha256(bad_hop2_bytes)
    (RUN_DIR / "SIDEINPUT_NEGATIVE_HOP2_V2.json").write_bytes(bad_hop2_bytes)
    sideinput_receipt = receipt_with_digest({
        "receipt_id": "RECEIPT-HOP2-SIDEINPUT-NEGATIVE-V2",
        "child_observation_id": "HOP2-SIDEINPUT-NEGATIVE",
        "child_sha256": bad_hop2_sha,
        "transform_id": "SYNTHETIC-RELAY-TWO-SIDEINPUT-NEGATIVE-V2",
        "transform_code_sha256": runner_code_sha,
        "declared_inputs": [hop2_input_record],
        "generated_at_utc": "2000-01-01T00:00:02Z",
        "issuer": "LOCAL_CONTROLLED_SYNTHETIC_RUNNER",
        "signature": None,
    })
    sideinput_observed = [hop2_input_record, source_record]
    sideinput_status = validate_receipt(
        sideinput_receipt, observed_inputs=sideinput_observed,
        expected_child_id="HOP2-SIDEINPUT-NEGATIVE", expected_child_sha256=bad_hop2_sha,
        expected_transform_id="SYNTHETIC-RELAY-TWO-SIDEINPUT-NEGATIVE-V2",
        expected_transform_code_sha256=runner_code_sha,
    )

    source_node = make_node("NODE-SOURCE", "SAVED_NORMALIZED_SAMPLE", f"local-file-sha256:{source_sha}")
    hop1_transform_node = make_node("NODE-TRANSFORM-1", "LOCAL_TRANSFORM", f"synthetic-transform:{receipt1['transform_id']}", "2000-01-01T00:00:01Z")
    hop1_node = make_node("NODE-HOP1", "SYNTHETIC_ALIAS", f"synthetic-alias-sha256:{hop1_sha}", "2000-01-01T00:00:01Z")
    hop2_transform_node = make_node("NODE-TRANSFORM-2", "LOCAL_TRANSFORM", f"synthetic-transform:{receipt2['transform_id']}", "2000-01-01T00:00:02Z")
    hop2_node = make_node("NODE-HOP2", "SYNTHETIC_ALIAS", f"synthetic-alias-sha256:{hop2_sha}", "2000-01-01T00:00:02Z")
    edge1a = make_edge("EDGE-SOURCE-TRANSFORM1", "NODE-SOURCE", "NODE-TRANSFORM-1", "RECEIPT-HOP1-V2", "2000-01-01T00:00:01Z")
    edge1b = make_edge("EDGE-TRANSFORM1-HOP1", "NODE-TRANSFORM-1", "NODE-HOP1", "RECEIPT-HOP1-V2", "2000-01-01T00:00:01Z")
    edge2a = make_edge("EDGE-HOP1-TRANSFORM2", "NODE-HOP1", "NODE-TRANSFORM-2", "RECEIPT-HOP2-V2", "2000-01-01T00:00:02Z")
    edge2b = make_edge("EDGE-TRANSFORM2-HOP2", "NODE-TRANSFORM-2", "NODE-HOP2", "RECEIPT-HOP2-V2", "2000-01-01T00:00:02Z")
    source_lineage = make_lineage("SOURCE", "NODE-SOURCE", (source_node,), (), complete=True)
    hop1_lineage = make_lineage(
        "HOP1", "NODE-HOP1", (source_node, hop1_transform_node, hop1_node), (edge1a, edge1b),
        complete=receipt1_status == "PASS_LOCAL_RUNNER_CONSISTENCY", completeness_at="2000-01-01T00:00:01Z",
    )
    hop2_full_lineage = make_lineage(
        "HOP2", "NODE-HOP2", (source_node, hop1_transform_node, hop1_node, hop2_transform_node, hop2_node),
        (edge1a, edge1b, edge2a, edge2b),
        complete=receipt1_status == "PASS_LOCAL_RUNNER_CONSISTENCY" and receipt2_status == "PASS_LOCAL_RUNNER_CONSISTENCY",
        completeness_at="2000-01-01T00:00:02Z",
    )
    hop2_incomplete_lineage = make_lineage(
        "HOP2", "NODE-HOP2", (hop2_node,), (), complete=False, completeness_at="2000-01-01T00:00:02Z",
    )
    pair_spec = (("SOURCE/HOP1", "SOURCE", "HOP1"), ("SOURCE/HOP2", "SOURCE", "HOP2"), ("HOP1/HOP2", "HOP1", "HOP2"))
    lineages_full = {"SOURCE": source_lineage, "HOP1": hop1_lineage, "HOP2": hop2_full_lineage}
    lineages_missing = {"SOURCE": source_lineage, "HOP1": hop1_lineage, "HOP2": hop2_incomplete_lineage}
    full_rows = [{"pair_id": pair_id, **assess_pair(lineages_full[left], lineages_full[right])} for pair_id, left, right in pair_spec]
    missing_rows = [{"pair_id": pair_id, **assess_pair(lineages_missing[left], lineages_missing[right])} for pair_id, left, right in pair_spec]

    payloads = {"SOURCE": {"sha256": source_sha, "byte_length": len(source_bytes), "outer_id": sample["feature"]["id"], "projection_keys": sorted(props)},
                "HOP1": {"sha256": hop1_sha, "byte_length": len(hop1_bytes), "outer_id": hop1["outer_id"], "projection_keys": sorted(hop1["projection"])},
                "HOP2": {"sha256": hop2_sha, "byte_length": len(hop2_bytes), "outer_id": hop2["outer_id"], "projection_keys": sorted(hop2["projection"])}}
    hash_rows = []
    for pair_id, left, right in pair_spec:
        row = hash_only_observation(payloads[left]["sha256"], payloads[right]["sha256"])
        hash_rows.append({"pair_id": pair_id, **row, "left_sha256": payloads[left]["sha256"], "right_sha256": payloads[right]["sha256"]})

    output = {
        "run_id": inputs["run_id"],
        "classification": inputs["classification"],
        "world_id": inputs["split"]["name"],
        "source_anchor": {**payloads["SOURCE"], "historical_receiver_time": "UNKNOWN_NOT_IN_SAVED_SAMPLE", "raw_usgs_response_available": False},
        "synthetic_aliases": [payloads["HOP1"], payloads["HOP2"]],
        "hop2_input_audit": {
            "persisted_hop1_path": str(hop1_path.relative_to(REPO_ROOT)),
            "persisted_hop1_sha256": hop1_sha,
            "transform_function_parameters": list(inspect.signature(transform_hop2_from_persisted_hop1).parameters),
            "observed_input_records": [hop2_input_record],
            "receipt_declared_inputs": receipt2["declared_inputs"],
        },
        "receipts": [receipt1, receipt2],
        "receipt_authenticity": "UNSIGNED LOCAL RUNNER CONSISTENCY ONLY; does not authenticate real source or historic transport.",
        "conditions": {
            "FULL_RECEIPT_CHAIN": {"available_receipt_ids": ["RECEIPT-HOP1-V2", "RECEIPT-HOP2-V2"], "receipt_statuses": [receipt1_status, receipt2_status], "pair_results": full_rows},
            "MISSING_INTERMEDIATE_RECEIPT": {"available_receipt_ids": ["RECEIPT-HOP1-V2"], "omitted_receipt_id": "RECEIPT-HOP2-V2", "receipt_statuses": [receipt1_status, "MISSING_RECEIPT"], "pair_results": missing_rows},
            "HASH_ONLY_DEDUP": {"available_receipt_ids": [], "hash_policy": "BYTE_EQUALITY_OR_INEQUALITY_ONLY; lineage UNKNOWN", "pair_results": hash_rows},
        },
        "side_input_negative_control": {
            "control_id": "UNDECLARED_SOURCE_SIDE_INPUT",
            "validator_visible_receipt_id": sideinput_receipt["receipt_id"],
            "receipt": sideinput_receipt,
            "receipt_declared_inputs": sideinput_receipt["declared_inputs"],
            "observed_input_records": sideinput_observed,
            "receipt_validation_status": sideinput_status,
            "lineage_status": "UNKNOWN" if sideinput_status != "PASS_LOCAL_RUNNER_CONSISTENCY" else "NOT_EVALUATED",
            "included_in_three_pair_denominator": False,
        },
        "policy_branch_checks": {
            "equal_hash_policy": hash_only_observation("FIXTURE-HASH", "FIXTURE-HASH"),
            "different_hash_policy": hash_only_observation("FIXTURE-HASH-A", "FIXTURE-HASH-B"),
            "note": "Two policy logic checks only; they do not create payloads or pair rows.",
        },
        "independence_established": False,
        "production_truth_denominator": 0,
    }
    output_bytes = json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    output_path = RUN_DIR / "METHOD_OUTPUTS_V2.json"
    output_path.write_bytes(output_bytes)
    output_hash = sha256(output_bytes)
    (RUN_DIR / "METHOD_OUTPUT_FREEZE_V2.json").write_text(
        json.dumps({"run_id": inputs["run_id"], "freeze_sequence": "WRITE_AND_HASH_METHOD_OUTPUT_BEFORE_EXPECTATION_COMPARISON", "method_outputs_path": str(output_path.relative_to(REPO_ROOT)), "bytes": len(output_bytes), "sha256": output_hash}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    expected_conditions = {item["condition_id"]: item for item in inputs["conditions"]}
    actual_statuses = {
        "FULL_RECEIPT_CHAIN": {row["pair_id"]: row["lineage_status"] for row in full_rows},
        "MISSING_INTERMEDIATE_RECEIPT": {row["pair_id"]: row["lineage_status"] for row in missing_rows},
        "HASH_ONLY_DEDUP": {row["pair_id"]: row["lineage_status"] for row in hash_rows},
    }
    checks = {
        "source_hash_matches_frozen_input": source_sha == inputs["source_sample"]["sha256"],
        "hop1_persisted_bytes_match_written_bytes": sha256(persisted_hop1_bytes) == sha256(hop1_bytes),
        "hop2_transform_has_one_persisted_bytes_argument": list(inspect.signature(transform_hop2_from_persisted_hop1).parameters) == ["persisted_hop1_bytes"],
        "hop2_receipt_declares_exact_observed_hop1_input": receipt2["declared_inputs"] == [hop2_input_record] and output["hop2_input_audit"]["observed_input_records"] == [hop2_input_record],
        "hop2_parent_hash_is_persisted_hop1_hash": receipt2["declared_inputs"][0]["sha256"] == sha256(hop1_path.read_bytes()),
        "outer_id_changes_at_each_hop": len({payloads["SOURCE"]["outer_id"], payloads["HOP1"]["outer_id"], payloads["HOP2"]["outer_id"]}) == 3,
        "projection_schema_changes_at_each_hop": len({tuple(payloads[key]["projection_keys"]) for key in ("SOURCE", "HOP1", "HOP2")}) == 3,
        "all_payload_hashes_are_distinct": len({payloads[key]["sha256"] for key in payloads}) == 3,
        "both_valid_receipts_pass_local_consistency": [receipt1_status, receipt2_status] == ["PASS_LOCAL_RUNNER_CONSISTENCY"] * 2,
        "full_chain_states_match_frozen_expectations": actual_statuses["FULL_RECEIPT_CHAIN"] == expected_conditions["FULL_RECEIPT_CHAIN"]["expected_pair_statuses"],
        "missing_receipt_states_match_frozen_expectations": actual_statuses["MISSING_INTERMEDIATE_RECEIPT"] == expected_conditions["MISSING_INTERMEDIATE_RECEIPT"]["expected_pair_statuses"],
        "hash_only_returns_unknown_for_all_pair_rows": actual_statuses["HASH_ONLY_DEDUP"] == expected_conditions["HASH_ONLY_DEDUP"]["expected_pair_statuses"],
        "hash_equal_and_different_policy_checks_return_unknown": output["policy_branch_checks"]["equal_hash_policy"]["lineage_status"] == "UNKNOWN" and output["policy_branch_checks"]["different_hash_policy"]["lineage_status"] == "UNKNOWN",
        "undeclared_side_input_fails_closed": sideinput_status == "UNDECLARED_SIDE_INPUT" and output["side_input_negative_control"]["lineage_status"] == "UNKNOWN",
        "no_statistical_independence_claim": output["independence_established"] is False and all(row["statistical_independence_established"] is False for row in full_rows + missing_rows),
    }
    checks["all_frozen_expectations_passed"] = all(checks.values())
    (RUN_DIR / "RUNNER_CHECKS_V2.json").write_text(
        json.dumps({"run_id": inputs["run_id"], "pre_run_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip(), "pre_run_manifest_sha256": pre_manifest_hash, "method_outputs_sha256_at_freeze": output_hash, "execution_started_at_utc": started_at, "method_runner_read_truth_log": False, "network_or_model_or_notification_called": False, "checks": checks}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"run_id": inputs["run_id"], "method_outputs_sha256_at_freeze": output_hash, "checks": checks}, ensure_ascii=False, indent=2))
    if not checks["all_frozen_expectations_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
