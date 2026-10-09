"""Independent live-gate verification.

This module deliberately has no authority/checklist write surface.  It turns a
sealed live-closeout evidence package into a signed verdict set that a logical
checklist committer may later carry to the policy broker.
"""

from __future__ import annotations

import hashlib
import hmac
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Mapping

from rfb.contracts.canonical_json import canonical_bytes

REQUIRED_LIVE_GATES = (
    "segment_cap_gate",
    "durable_result_gate",
    "result_archive_gate",
    "regeneration_gate",
    "dataset_purge_gate",
)
_FULL_PANEL = ["B0", "B1", "B2", "B3", "B4", "B5", "Proposed"]


class LiveGateBlocked(ValueError):
    """The candidate cannot be promoted to live-gate evidence."""


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise LiveGateBlocked(f"{field} must be a sha256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise LiveGateBlocked(f"{field} must be a sha256 hex digest") from exc
    return value.lower()


def _int_field(item: Mapping[str, Any], field: str) -> int:
    value = item.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise LiveGateBlocked(f"{field} must be an integer")
    return value


def _nonnegative_int_field(item: Mapping[str, Any], field: str) -> int:
    value = _int_field(item, field)
    if value < 0:
        raise LiveGateBlocked(f"{field} must be non-negative")
    return value


def _reconstruct_gate_proofs(
    proofs: Mapping[str, Any], bundle_ids: list[str]
) -> dict[str, Mapping[str, Any]]:
    """Recompute every live gate from the sealed proof bodies.

    The verifier intentionally does not accept a caller-supplied status as
    evidence.  Each proof domain is checked here and the original immutable
    body is returned for hash binding.
    """
    if set(proofs) != {
        "capacity",
        "durable_result",
        "archives",
        "regeneration",
        "purge",
    }:
        raise LiveGateBlocked("sealed_body proofs must contain exactly five domains")
    if not all(isinstance(item, Mapping) for item in proofs.values()):
        raise LiveGateBlocked("sealed_body proofs must be objects")
    capacity, durable, archives = (
        proofs["capacity"],
        proofs["durable_result"],
        proofs["archives"],
    )
    regeneration, purge = proofs["regeneration"], proofs["purge"]
    peak_bytes = _nonnegative_int_field(capacity, "peak_bytes")
    planning_peak_bytes = _nonnegative_int_field(capacity, "planning_peak_bytes")
    max_sampling_interval = _nonnegative_int_field(
        capacity, "max_sampling_interval_seconds"
    )
    if (
        peak_bytes > 25_000_000_000
        or planning_peak_bytes > 22_000_000_000
        or capacity.get("subbudget_borrowing") is not False
        or max_sampling_interval > 30
    ):
        raise LiveGateBlocked("capacity proof failed reconstruction")
    if (
        durable.get("sealed") is not True
        or durable.get("contains_raw_dataset") is not False
        or durable.get("truth_isolation") != "PASS"
        or _int_field(durable, "complete_rows") != len(bundle_ids) * len(_FULL_PANEL)
    ):
        raise LiveGateBlocked("durable result proof failed reconstruction")
    for field in ("manifest_hash", "merkle_root"):
        _hash(durable.get(field), f"durable_result.{field}")
    a, b = archives.get("A"), archives.get("B")
    if not isinstance(a, Mapping) or not isinstance(b, Mapping):
        raise LiveGateBlocked("Archive A and B proofs are required")
    for name, archive in (("A", a), ("B", b)):
        if any(
            archive.get(field) != 0 for field in ("missing", "unexpected", "mismatch")
        ):
            raise LiveGateBlocked(f"archive {name} proof failed reconstruction")
        if (
            archive.get("readback_status") != "PASS"
            or archive.get("contains_raw_dataset") is not False
        ):
            raise LiveGateBlocked(f"archive {name} proof failed reconstruction")
    if a.get("storage_identity") == b.get("storage_identity") or a.get(
        "failure_domain"
    ) == b.get("failure_domain"):
        raise LiveGateBlocked("Archive A/B identities are not independent")
    expected_samples = max(2, (len(bundle_ids) + 99) // 100)
    if (
        regeneration.get("sample_plan_frozen_before_execution") is not True
        or _int_field(regeneration, "sample_count") < expected_samples
        or regeneration.get("replacement_sampling") is not False
        or regeneration.get("payload_commitments_match") is not True
        or regeneration.get("full_panel_replay_match") is not True
    ):
        raise LiveGateBlocked("regeneration proof failed reconstruction")
    states = tuple(purge.get("ledger_states", ()))
    required_states = ("APPROVAL_RECORDED", "CLAIMED", "PURGE_INTENT", "COMMITTED")
    if states != required_states:
        raise LiveGateBlocked("purge ledger must exactly match required lifecycle")
    if (
        purge.get("approval_artifact_status") != "ISSUED"
        or purge.get("ds_stat_used_as_authorization") is not False
        or purge.get("ephemeral_files_remaining") != 0
        or purge.get("open_deleted_bytes") != 0
        or purge.get("unexplained_space_delta") != 0
        or purge.get("archive_a_reread") != "PASS"
        or purge.get("archive_b_reread") != "PASS"
        or purge.get("residual_paths", []) != []
    ):
        raise LiveGateBlocked("purge residual reconciliation failed")
    return {
        "segment_cap_gate": capacity,
        "durable_result_gate": durable,
        "result_archive_gate": archives,
        "regeneration_gate": regeneration,
        "dataset_purge_gate": purge,
    }


class LiveGateVerifier:
    """Read-only verifier operating under an independent signing identity."""

    schema_id = "live-gate-verdict-set.v1"

    def __init__(
        self,
        *,
        signer_id: str,
        signing_key: bytes,
        trust_epoch: str,
        closeout_attestation_key: bytes | None = None,
    ) -> None:
        if not signer_id or not signing_key or not trust_epoch:
            raise ValueError("signer_id, signing_key and trust_epoch are required")
        self.signer_id = signer_id
        self._key = bytes(signing_key)
        self.trust_epoch = trust_epoch
        self._closeout_key = bytes(closeout_attestation_key or b"")
        if self._closeout_key and hmac.compare_digest(self._key, self._closeout_key):
            raise ValueError(
                "closeout attestation key must be distinct from verdict signing key"
            )

    def verify_and_sign(
        self,
        evidence_package: Mapping[str, Any],
        *,
        source_snapshot: Mapping[str, Any],
        expected_snapshot_hash: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Validate a live closeout package and emit a signed verdict set."""

        snapshot_hash = canonical_hash(source_snapshot)
        if not hmac.compare_digest(
            snapshot_hash, _hash(expected_snapshot_hash, "expected_snapshot_hash")
        ):
            raise LiveGateBlocked("source snapshot hash mismatch")
        if evidence_package.get("classification") != "LIVE_CLOSEOUT_EVIDENCE":
            raise LiveGateBlocked(
                "development, rehearsal and C2 evidence cannot be promoted"
            )
        if evidence_package.get("terminal_state") != "RECONCILED":
            raise LiveGateBlocked("segment is not RECONCILED")
        bundle_count = evidence_package.get("bundle_count")
        if isinstance(bundle_count, bool) or not isinstance(bundle_count, int):
            raise LiveGateBlocked("bundle_count must be an integer")
        if bundle_count < 2:
            raise LiveGateBlocked("live closeout requires at least two bundles")
        if evidence_package.get("contains_development_evidence") is not False:
            raise LiveGateBlocked("development evidence is not live evidence")
        if evidence_package.get("c2_evidence_state") is not None:
            raise LiveGateBlocked("C2 sizing evidence is permanently non-promotable")
        if evidence_package.get("sealed") is not True:
            raise LiveGateBlocked("evidence package must be sealed")
        attestation = evidence_package.get("closeout_attestation")
        if not self._closeout_key or not isinstance(attestation, Mapping):
            raise LiveGateBlocked("independent closeout attestation is required")
        if attestation.get("schema_id") != "live-closeout-attestation.v1":
            raise LiveGateBlocked("closeout attestation schema is invalid")
        attester_id = attestation.get("signer_id")
        if not isinstance(attester_id, str) or not attester_id:
            raise LiveGateBlocked("closeout attestation signer is required")
        if attester_id == self.signer_id:
            raise LiveGateBlocked("closeout attester must be independent")
        key_id = attestation.get("key_id")
        if not isinstance(key_id, str) or not key_id or key_id == self.signer_id:
            raise LiveGateBlocked(
                "closeout attestation key_id is required and independent"
            )
        attester_epoch = attestation.get("trust_epoch")
        if not isinstance(attester_epoch, str) or not attester_epoch:
            raise LiveGateBlocked("closeout attestation trust epoch is required")
        attestation_sig = attestation.get("signature")
        if not isinstance(attestation_sig, str) or len(attestation_sig) != 64:
            raise LiveGateBlocked("invalid closeout attestation signature")

        sealed_body = evidence_package.get("sealed_body")
        if not isinstance(sealed_body, Mapping):
            raise LiveGateBlocked("sealed_body is required")
        segment_id = evidence_package.get("segment_id")
        if not isinstance(segment_id, str) or not segment_id:
            raise LiveGateBlocked("segment_id is required")
        if sealed_body.get("segment_id") != segment_id:
            raise LiveGateBlocked("segment_id binding mismatch")
        manifest_hash = _hash(evidence_package.get("manifest_hash"), "manifest_hash")
        if sealed_body.get("manifest_hash") != manifest_hash:
            raise LiveGateBlocked("manifest_hash binding mismatch")
        body_bundle_count = sealed_body.get("bundle_count")
        if isinstance(body_bundle_count, bool) or not isinstance(
            body_bundle_count, int
        ):
            raise LiveGateBlocked("sealed_body.bundle_count must be an integer")
        if body_bundle_count != bundle_count:
            raise LiveGateBlocked("bundle_count binding mismatch")
        panel = ["B0", "B1", "B2", "B3", "B4", "B5", "Proposed"]
        if (
            sealed_body.get("bundle_ids") is None
            or sealed_body.get("method_ids") is None
        ):
            raise LiveGateBlocked("sealed_body bundle/panel binding is required")
        if evidence_package.get("bundle_ids") != sealed_body.get("bundle_ids"):
            raise LiveGateBlocked("bundle_ids binding mismatch")
        if evidence_package.get("method_ids") != sealed_body.get("method_ids"):
            raise LiveGateBlocked("method_ids binding mismatch")
        bundle_ids = evidence_package.get("bundle_ids")
        if (
            not isinstance(bundle_ids, list)
            or not bundle_ids
            or len(bundle_ids) != bundle_count
            or any(not isinstance(item, str) or not item for item in bundle_ids)
            or len(set(bundle_ids)) != len(bundle_ids)
        ):
            raise LiveGateBlocked(
                "bundle_ids must be a non-empty unique list matching bundle_count"
            )
        if sealed_body.get("method_ids") != panel:
            raise LiveGateBlocked("sealed_body method panel mismatch")
        reconstructed = _reconstruct_gate_proofs(
            sealed_body.get("proofs", {}), bundle_ids
        )
        attestation_body = {
            "schema_id": attestation["schema_id"],
            "signer_id": attester_id,
            "key_id": key_id,
            "trust_epoch": attester_epoch,
            "sealed_body": deepcopy(dict(sealed_body)),
            "segment_id": segment_id,
            "manifest_hash": manifest_hash,
            "bundle_count": bundle_count,
            "bundle_ids": list(evidence_package["bundle_ids"]),
            "method_ids": list(evidence_package["method_ids"]),
        }
        expected_attestation = hmac.new(
            self._closeout_key, canonical_bytes(attestation_body), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_attestation, attestation_sig.lower()):
            raise LiveGateBlocked("closeout attestation mismatch")
        expected_sealed_hash = _hash(
            evidence_package.get("sealed_evidence_hash"), "sealed_evidence_hash"
        )
        if not hmac.compare_digest(canonical_hash(sealed_body), expected_sealed_hash):
            raise LiveGateBlocked("sealed evidence hash mismatch")

        gate_evidence = evidence_package.get("gates")
        if not isinstance(gate_evidence, Mapping):
            raise LiveGateBlocked("gates must be an object")
        if set(gate_evidence) != set(REQUIRED_LIVE_GATES):
            raise LiveGateBlocked("exactly five live gates are required")

        verdicts: dict[str, Any] = {}
        for gate in REQUIRED_LIVE_GATES:
            item = gate_evidence[gate]
            if not isinstance(item, Mapping) or item.get("status") != "PASS":
                raise LiveGateBlocked(f"{gate} is not independently proven PASS")
            refs = item.get("evidence_refs")
            if not isinstance(refs, list) or refs != [f"sealed://{segment_id}/{gate}"]:
                raise LiveGateBlocked(f"{gate} lacks canonical immutable evidence refs")
            item_hash = _hash(item.get("evidence_hash"), f"{gate}.evidence_hash")
            expected_gate_hashes = sealed_body.get("gate_proof_hashes")
            if not isinstance(expected_gate_hashes, Mapping):
                raise LiveGateBlocked("sealed_body gate proof hashes are required")
            if item_hash != canonical_hash(reconstructed[gate]) or item_hash != _hash(
                expected_gate_hashes.get(gate), f"sealed_body.{gate}.evidence_hash"
            ):
                raise LiveGateBlocked(f"{gate} evidence hash binding mismatch")
            verdicts[gate] = {
                "status": "PASS",
                "evidence_refs": list(refs),
                "evidence_hash": item_hash,
            }

        stamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        body = {
            "schema_id": self.schema_id,
            "classification": "LIVE_GATE_VERDICT_SET",
            "signer_role": "LiveGateVerifier",
            "signer_id": self.signer_id,
            "trust_epoch": self.trust_epoch,
            "source_snapshot": deepcopy(dict(source_snapshot)),
            "source_snapshot_hash": snapshot_hash,
            "sealed_evidence_hash": expected_sealed_hash,
            "segment_id": segment_id,
            "manifest_hash": manifest_hash,
            "verdicts": verdicts,
            "issued_at": stamp,
        }
        signature = hmac.new(
            self._key, canonical_bytes(body), hashlib.sha256
        ).hexdigest()
        return {**body, "signature": signature}

    def verify_signature(self, verdict_set: Mapping[str, Any]) -> bool:
        body = dict(verdict_set)
        signature = body.pop("signature", None)
        if not isinstance(signature, str):
            return False
        expected = hmac.new(
            self._key, canonical_bytes(body), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
