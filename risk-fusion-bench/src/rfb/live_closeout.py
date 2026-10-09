"""Fail-closed Stage C closeout rehearsal evidence assembler."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from rfb.live_gate import REQUIRED_LIVE_GATES, canonical_hash

FULL_PANEL = ("B0", "B1", "B2", "B3", "B4", "B5", "Proposed")
REQUIRED_PURGE_STATES = (
    "APPROVAL_RECORDED",
    "CLAIMED",
    "PURGE_INTENT",
    "COMMITTED",
)


class CloseoutBlocked(ValueError):
    pass


def _zero_archive_errors(item, name):
    for field in ("missing", "unexpected", "mismatch"):
        if item.get(field) != 0:
            raise CloseoutBlocked(f"{name}.{field} must be zero")
    if item.get("readback_status") != "PASS":
        raise CloseoutBlocked(f"{name} readback failed")


def _int_field(item: Mapping[str, Any], field: str) -> int:
    value = item.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CloseoutBlocked(f"{field} must be an integer")
    return value


def _hex_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise CloseoutBlocked(f"{field} must be a sha256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise CloseoutBlocked(f"{field} must be a sha256 hex digest") from exc
    return value.lower()


class LiveCloseoutRehearsal:
    """Validate a complete Stage C proof chain without minting authority."""

    def __init__(
        self,
        *,
        segment_id: str,
        bundle_ids: Sequence[str],
        method_ids: Sequence[str],
        active_failure_domain: str,
    ):
        if not segment_id:
            raise ValueError("segment_id is required")
        if (
            len(bundle_ids) < 2
            or any(
                not isinstance(bundle_id, str) or not bundle_id
                for bundle_id in bundle_ids
            )
            or len(set(bundle_ids)) != len(bundle_ids)
        ):
            raise CloseoutBlocked(
                "closeout rehearsal requires >=2 unique non-empty bundles"
            )
        if tuple(method_ids) != FULL_PANEL:
            raise CloseoutBlocked("the complete frozen seven-method panel is required")
        self.segment_id = segment_id
        self.bundle_ids = tuple(bundle_ids)
        self.active_failure_domain = active_failure_domain

    def seal(self, proofs: Mapping[str, Any]) -> dict[str, Any]:
        capacity = proofs.get("capacity")
        durable = proofs.get("durable_result")
        archives = proofs.get("archives")
        regeneration = proofs.get("regeneration")
        purge = proofs.get("purge")
        if not all(
            isinstance(x, Mapping)
            for x in (capacity, durable, archives, regeneration, purge)
        ):
            raise CloseoutBlocked("all five proof domains are required")

        peak_bytes = _int_field(capacity, "peak_bytes")
        planning_peak_bytes = _int_field(capacity, "planning_peak_bytes")
        sampling_interval = _int_field(capacity, "max_sampling_interval_seconds")
        if (
            peak_bytes > 25_000_000_000
            or planning_peak_bytes > 22_000_000_000
            or capacity.get("subbudget_borrowing") is not False
            or sampling_interval > 30
            or capacity.get("status") != "PASS"
        ):
            raise CloseoutBlocked("capacity proof failed")

        if (
            durable.get("status") != "PASS"
            or durable.get("sealed") is not True
            or durable.get("contains_raw_dataset") is not False
            or durable.get("truth_isolation") != "PASS"
            or _int_field(durable, "complete_rows")
            != len(self.bundle_ids) * len(FULL_PANEL)
        ):
            raise CloseoutBlocked("durable result proof failed")
        for field in ("manifest_hash", "merkle_root"):
            _hex_digest(durable.get(field), f"durable_result.{field}")

        archive_a = archives.get("A")
        archive_b = archives.get("B")
        if not isinstance(archive_a, Mapping) or not isinstance(archive_b, Mapping):
            raise CloseoutBlocked("Archive A and B proofs are required")
        _zero_archive_errors(archive_a, "archive A")
        _zero_archive_errors(archive_b, "archive B")
        if archive_a.get("storage_identity") == archive_b.get("storage_identity"):
            raise CloseoutBlocked("Archive A/B storage identities are not independent")
        if archive_a.get("failure_domain") == archive_b.get("failure_domain") or (
            archive_a.get("failure_domain") == self.active_failure_domain
            and archive_b.get("failure_domain") == self.active_failure_domain
        ):
            raise CloseoutBlocked("Archive A/B failure domains are not independent")
        for archive in (archive_a, archive_b):
            if archive.get("contains_raw_dataset") is not False:
                raise CloseoutBlocked("archives may contain durable results only")

        expected_samples = max(2, (len(self.bundle_ids) + 99) // 100)
        if (
            regeneration.get("status") != "PASS"
            or regeneration.get("sample_plan_frozen_before_execution") is not True
            or _int_field(regeneration, "sample_count") < expected_samples
            or regeneration.get("replacement_sampling") is not False
            or regeneration.get("payload_commitments_match") is not True
            or regeneration.get("full_panel_replay_match") is not True
        ):
            raise CloseoutBlocked("regeneration proof failed")

        if purge.get("status") != "PASS":
            raise CloseoutBlocked("purge proof failed")
        if purge.get("approval_artifact_status") != "ISSUED":
            raise CloseoutBlocked("execution approval must be a signed ISSUED artifact")
        if purge.get("ds_stat_used_as_authorization") is not False:
            raise CloseoutBlocked("DS/STAT must not authorize purge")
        states = tuple(purge.get("ledger_states", ()))
        cursor = 0
        for state in states:
            if (
                cursor < len(REQUIRED_PURGE_STATES)
                and state == REQUIRED_PURGE_STATES[cursor]
            ):
                cursor += 1
        if cursor != len(REQUIRED_PURGE_STATES):
            raise CloseoutBlocked("purge anti-replay ledger is incomplete")
        if (
            purge.get("ephemeral_files_remaining") != 0
            or purge.get("open_deleted_bytes") != 0
            or purge.get("unexplained_space_delta") != 0
            or purge.get("archive_a_reread") != "PASS"
            or purge.get("archive_b_reread") != "PASS"
        ):
            raise CloseoutBlocked("post-purge reconciliation failed")
        if purge.get("residual_paths", []) != []:
            raise CloseoutBlocked("post-purge residual paths must be empty")

        state_trace = (
            "PLANNED",
            "ADMITTED",
            "MATERIALIZING",
            "EXECUTING",
            "RESULT_SEALED_LOCAL",
            "RESULT_ARCHIVED_A",
            "RESULT_ARCHIVED_B",
            "REGEN_VERIFIED",
            "PURGE_APPROVAL_PENDING",
            "DATASET_PURGING",
            "DATASET_PURGED",
            "RECONCILED",
        )
        gate_sources = {
            "segment_cap_gate": capacity,
            "durable_result_gate": durable,
            "result_archive_gate": archives,
            "regeneration_gate": regeneration,
            "dataset_purge_gate": purge,
        }
        gates = {
            gate: {
                "status": "PASS",
                "evidence_refs": [f"sealed://{self.segment_id}/{gate}"],
                "evidence_hash": canonical_hash(gate_sources[gate]),
            }
            for gate in REQUIRED_LIVE_GATES
        }
        body = {
            "segment_id": self.segment_id,
            "manifest_hash": _hex_digest(durable["manifest_hash"], "manifest_hash"),
            "bundle_ids": list(self.bundle_ids),
            "bundle_count": len(self.bundle_ids),
            "method_ids": list(FULL_PANEL),
            "gate_proof_hashes": {
                gate: canonical_hash(gate_sources[gate]) for gate in REQUIRED_LIVE_GATES
            },
            "state_trace": list(state_trace),
            "proofs": deepcopy(dict(proofs)),
        }
        return {
            "classification": "LIVE_CLOSEOUT_REHEARSAL",
            "terminal_state": "RECONCILED",
            "bundle_count": len(self.bundle_ids),
            "bundle_ids": list(self.bundle_ids),
            "method_ids": list(FULL_PANEL),
            "contains_development_evidence": True,
            "c2_evidence_state": "REHEARSAL_NON_PROMOTABLE",
            "sealed": True,
            "sealed_body": body,
            "sealed_evidence_hash": canonical_hash(body),
            "manifest_hash": durable["manifest_hash"],
            "segment_id": self.segment_id,
            "gates": gates,
        }
