"""Formal-admission construction and SHK-001B guard.

The builder is read-only by default.  It can only write an admission document
when a caller explicitly opts in *and* all five live gates plus distinct
role-bound DS/STAT signatures over one complete intent have been verified.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from rfb.contracts.canonical_json import canonical_bytes
from rfb.live_gate import REQUIRED_LIVE_GATES, canonical_hash

REQUIRED_CONTEXT_FIELDS = (
    "runtime_baseline_hash",
    "source_tree_hash",
    "container_hash",
    "method_registry_hash",
    "archive_a_identity",
    "archive_a_readback_root",
    "archive_b_identity",
    "archive_b_readback_root",
    "segment_id",
    "segment_manifest_hash",
)


class AdmissionBlocked(ValueError):
    """Formal admission is not valid or not authorized."""


def _pass_value(value: Any) -> bool:
    return value == "PASS" or (
        isinstance(value, Mapping) and value.get("status") == "PASS"
    )


def _sha256_value(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _signature_payload(
    *, role: str, key_id: str, trust_epoch: str, digest: str
) -> dict[str, str]:
    return {
        "role": role,
        "key_id": key_id,
        "trust_epoch": trust_epoch,
        "admission_intent_digest": digest,
    }


def sign_admission_intent(
    *,
    role: str,
    key_id: str,
    trust_epoch: str,
    key: bytes,
    digest: str,
) -> dict[str, str]:
    payload = _signature_payload(
        role=role, key_id=key_id, trust_epoch=trust_epoch, digest=digest
    )
    return {
        **payload,
        "signature": hmac.new(
            key, canonical_bytes(payload), hashlib.sha256
        ).hexdigest(),
    }


class AdmissionBuilder:
    schema_id = "formal-stage-admission-v6.13.v1"

    def __init__(
        self,
        *,
        live_verifier_keys: Mapping[str, Mapping[str, Any]],
        signer_keys: Mapping[str, Mapping[str, Any]],
    ) -> None:
        self._verifiers = dict(live_verifier_keys)
        self._signers = dict(signer_keys)

    def _verify_trust_store_independence(self) -> list[str]:
        """Fail closed when trust labels alias keys or identifiers."""
        missing: list[str] = []
        records = [
            (f"LiveGateVerifier:{name}", value)
            for name, value in self._verifiers.items()
        ]
        records.extend((role, value) for role, value in self._signers.items())
        ids: dict[str, str] = {}
        keys: dict[bytes, str] = {}
        for label, record in records:
            if not isinstance(record, Mapping):
                missing.append(f"trust_store.{label}")
                continue
            key_id = record.get("key_id") or (
                label.split(":", 1)[1]
                if label.startswith("LiveGateVerifier:")
                else None
            )
            key = record.get("key")
            if not isinstance(key_id, str) or not key_id:
                missing.append(f"trust_store.{label}.key_id")
            elif key_id in ids and ids[key_id] != label:
                missing.append("trust_store.duplicate_key_id")
            else:
                ids[key_id] = label
            if not isinstance(key, (bytes, bytearray)) or not key:
                missing.append(f"trust_store.{label}.key")
            else:
                normalized = bytes(key)
                if normalized in keys and keys[normalized] != label:
                    missing.append("trust_store.duplicate_key_material.distinct")
                else:
                    keys[normalized] = label
        return missing

    def _verify_verdict_set(self, verdict_set: Mapping[str, Any]) -> list[str]:
        missing: list[str] = self._verify_trust_store_independence()
        if verdict_set.get("schema_id") != "live-gate-verdict-set.v1":
            missing.append("live_verdict_set.schema_id")
        if verdict_set.get("classification") != "LIVE_GATE_VERDICT_SET":
            missing.append("live_verdict_set.classification")
        if verdict_set.get("signer_role") != "LiveGateVerifier":
            missing.append("live_verdict_set.signer_role")
        source_snapshot = verdict_set.get("source_snapshot")
        if not isinstance(source_snapshot, Mapping):
            missing.append("live_verdict_set.source_snapshot")
        elif verdict_set.get("source_snapshot_hash") != canonical_hash(source_snapshot):
            missing.append("live_verdict_set.source_snapshot_hash")
        signer_id = verdict_set.get("signer_id")
        trust = self._verifiers.get(str(signer_id))
        if not trust:
            missing.append("live_verdict_set.trusted_signer")
            return missing
        if verdict_set.get("trust_epoch") != trust.get("trust_epoch"):
            missing.append("live_verdict_set.trust_epoch")
        body = dict(verdict_set)
        signature = body.pop("signature", None)
        expected = hmac.new(
            trust["key"], canonical_bytes(body), hashlib.sha256
        ).hexdigest()
        if not isinstance(signature, str) or not hmac.compare_digest(
            signature, expected
        ):
            missing.append("live_verdict_set.signature")
        verdicts = verdict_set.get("verdicts")
        if not isinstance(verdicts, Mapping):
            missing.append("live_verdict_set.verdicts")
        else:
            for gate in REQUIRED_LIVE_GATES:
                value = verdicts.get(gate)
                if not _pass_value(value):
                    missing.append(f"live_verdict_set.{gate}")
                elif not isinstance(value, Mapping):
                    missing.append(f"live_verdict_set.{gate}.evidence")
                else:
                    refs = value.get("evidence_refs")
                    evidence_hash = value.get("evidence_hash")
                    if (
                        not isinstance(refs, list)
                        or not refs
                        or any(not isinstance(ref, str) or not ref for ref in refs)
                    ):
                        missing.append(f"live_verdict_set.{gate}.evidence_refs")
                    if not _sha256_value(evidence_hash):
                        missing.append(f"live_verdict_set.{gate}.evidence_hash")
        return missing

    @staticmethod
    def _verify_broker_projection_proof(
        proof, *, verdict_set, checklist_hash, predecessor, successor, current
    ):
        missing = []
        if not isinstance(proof, Mapping):
            return ["context.broker_projection_proof"]
        chain, prepared, committed = (
            proof.get("audit_chain"),
            proof.get("prepared"),
            proof.get("committed"),
        )
        if not isinstance(chain, list) or not chain:
            missing.append("context.broker_projection_proof.audit_chain")
            chain = []
        previous = ""
        valid = []
        for row in chain:
            if not isinstance(row, Mapping):
                missing.append("context.broker_projection_proof.audit_row")
                continue
            if row.get("previous_hash", "") != previous:
                missing.append("context.broker_projection_proof.chain")
            observed = row.get("entry_hash")
            if observed != canonical_hash(
                {k: v for k, v in row.items() if k != "entry_hash"}
            ):
                missing.append("context.broker_projection_proof.entry_hash")
            previous = observed if isinstance(observed, str) else ""
            valid.append(row)
        if not isinstance(prepared, Mapping) or not isinstance(committed, Mapping):
            return sorted(set(missing + ["context.broker_projection_proof.terminals"]))
        if prepared not in valid or committed not in valid:
            missing.append("context.broker_projection_proof.terminals_chain_binding")
        if prepared.get("status") != "BROKER_PREPARED":
            missing.append("context.broker_projection_proof.prepared_status")
        if committed.get("status") != "BROKER_COMMITTED":
            missing.append("context.broker_projection_proof.committed_status")
        pb, cb = prepared.get("binding"), committed.get("binding")
        if not isinstance(pb, Mapping) or not isinstance(cb, Mapping):
            return sorted(set(missing + ["context.broker_projection_proof.binding"]))
        for field in (
            "request_id",
            "operation_id",
            "generation_id",
            "predecessor_generation_id",
            "predecessor_checklist_hash",
            "successor_checklist_hash",
            "source_hash",
            "projection_policy_id",
            "projection_policy_version",
            "receipt_hash",
            "manifest_hash",
        ):
            if pb.get(field) != cb.get(field):
                missing.append("context.broker_projection_proof." + field)
        if pb.get("predecessor_generation_id") != predecessor:
            missing.append("context.broker_projection_proof.predecessor_generation_id")
        if pb.get("generation_id") != successor or current != successor:
            missing.append("context.broker_projection_proof.successor_generation_id")
        if pb.get("predecessor_checklist_hash") != proof.get(
            "predecessor_checklist_hash"
        ):
            missing.append("context.broker_projection_proof.predecessor_checklist_hash")
        if pb.get("successor_checklist_hash") != checklist_hash:
            missing.append("context.broker_projection_proof.successor_checklist_hash")
        if pb.get("source_hash") != proof.get("verdict_artifact_hash"):
            missing.append("context.broker_projection_proof.verdict_artifact_hash")
        if proof.get("verdict_artifact_hash") != canonical_hash(verdict_set):
            missing.append("context.broker_projection_proof.verdict_artifact_binding")
        for field in (
            "projection_policy_id",
            "projection_policy_version",
            "receipt_hash",
            "manifest_hash",
        ):
            if proof.get(field) != pb.get(field):
                missing.append("context.broker_projection_proof." + field)
        if (
            proof.get("current_generation_id") != successor
            or proof.get("current_checklist_hash") != checklist_hash
        ):
            missing.append("context.broker_projection_proof.current_authority")
        return sorted(set(missing))

    def dry_run(
        self,
        *,
        checklist_snapshot: Mapping[str, Any],
        verdict_set: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        missing = self._verify_verdict_set(verdict_set)
        checklist_hash = canonical_hash(checklist_snapshot)
        predecessor_snapshot = context.get("predecessor_checklist_snapshot")
        predecessor_hash = context.get("predecessor_checklist_hash")
        successor_snapshot = context.get("successor_checklist_snapshot")
        successor_hash = context.get("successor_checklist_hash")
        if isinstance(predecessor_snapshot, Mapping):
            if predecessor_hash != canonical_hash(predecessor_snapshot):
                missing.append("context.predecessor_checklist_hash")
            if verdict_set.get("source_snapshot_hash") != canonical_hash(
                predecessor_snapshot
            ):
                missing.append("live_verdict_set.predecessor_snapshot_binding")
            projected = deepcopy(dict(predecessor_snapshot))
            for gate in REQUIRED_LIVE_GATES:
                projected[gate] = deepcopy(verdict_set.get("verdicts", {}).get(gate))
            if (
                not isinstance(successor_snapshot, Mapping)
                or successor_snapshot != projected
            ):
                missing.append("context.successor_checklist_projection")
            if successor_hash != canonical_hash(projected):
                missing.append("context.successor_checklist_hash")
            if checklist_snapshot != projected:
                missing.append("checklist.successor_snapshot_binding")
        elif verdict_set.get("source_snapshot_hash") != checklist_hash:
            missing.append("live_verdict_set.checklist_snapshot_binding")
        if not _pass_value(checklist_snapshot.get("runtime_gate")):
            missing.append("checklist.runtime_gate")
        for gate in REQUIRED_LIVE_GATES:
            if not _pass_value(checklist_snapshot.get(gate)):
                missing.append(f"checklist.{gate}")

        for field in REQUIRED_CONTEXT_FIELDS:
            if not isinstance(context.get(field), str) or not context.get(field):
                missing.append(f"context.{field}")
        for field in (
            "runtime_baseline_hash",
            "source_tree_hash",
            "container_hash",
            "method_registry_hash",
            "archive_a_readback_root",
            "archive_b_readback_root",
            "segment_manifest_hash",
        ):
            if not _sha256_value(context.get(field)):
                missing.append(f"context.{field}.sha256")
        if verdict_set.get("segment_id") != context.get("segment_id"):
            missing.append("context.segment_id.verdict_binding")
        if verdict_set.get("manifest_hash") != context.get("segment_manifest_hash"):
            missing.append("context.segment_manifest_hash.verdict_binding")
        if context.get("raw_dataset_retained") is not False:
            missing.append("context.raw_dataset_retained=false")
        if context.get("effect_peeking") is not False:
            missing.append("context.effect_peeking=false")
        if context.get("formal_start_allowed") is not True:
            missing.append("context.formal_start_allowed=true")
        if context.get("checklist_snapshot_hash") != checklist_hash:
            missing.append("context.checklist_snapshot_hash")
        if context.get("verdict_set_hash") != canonical_hash(verdict_set):
            missing.append("context.verdict_set_hash")

        # A formal intent is valid only when it names a complete authority
        # lineage. The verdict/source snapshot are predecessor-bound while
        # CURRENT and the trusted authority identify the committed successor.
        predecessor = context.get("predecessor_generation_id")
        successor = context.get("successor_generation_id")
        current = context.get("current_generation_id")
        for field in (
            "predecessor_generation_id",
            "successor_generation_id",
            "current_generation_id",
        ):
            if not isinstance(context.get(field), str) or not context.get(field):
                missing.append(f"context.{field}")
        if context.get("current_checklist_snapshot_hash") != checklist_hash:
            missing.append("context.current_checklist_snapshot_hash")
        if context.get("verdict_predecessor_generation_id") != predecessor:
            missing.append("context.verdict_predecessor_generation_id")
        if context.get("source_snapshot_predecessor_generation_id") != predecessor:
            missing.append("context.source_snapshot_predecessor_generation_id")
        if current != successor:
            missing.append("context.current_generation_id.trusted_successor")
        missing.extend(
            self._verify_broker_projection_proof(
                context.get("broker_projection_proof"),
                verdict_set=verdict_set,
                checklist_hash=checklist_hash,
                predecessor=predecessor,
                successor=successor,
                current=current,
            )
        )
        receipt = context.get("successor_receipt")
        manifest = context.get("successor_manifest")
        if not isinstance(receipt, Mapping):
            missing.append("context.successor_receipt")
        if not isinstance(manifest, Mapping):
            missing.append("context.successor_manifest")
        if isinstance(receipt, Mapping) and isinstance(manifest, Mapping):
            if (
                receipt.get("generation_id") != successor
                or manifest.get("generation_id") != successor
            ):
                missing.append("context.successor.generation_binding")
            if (
                receipt.get("parent_generation") != predecessor
                or manifest.get("parent_generation") != predecessor
            ):
                missing.append("context.successor.parent_binding")
            if receipt.get("status") != "COMMITTED":
                missing.append("context.successor.receipt_committed")
            if context.get("successor_receipt_hash") != canonical_hash(receipt):
                missing.append("context.successor_receipt_hash")
            if context.get("successor_manifest_hash") != canonical_hash(manifest):
                missing.append("context.successor_manifest_hash")
        trusted = context.get("trusted_authority")
        if not isinstance(trusted, Mapping):
            missing.append("context.trusted_authority")
        else:
            if trusted.get("generation_id") != successor:
                missing.append("context.trusted_authority.generation_binding")
            if trusted.get("checklist_hash") != checklist_hash:
                missing.append("context.trusted_authority.checklist_binding")
        intent = {
            "schema_id": "admission-intent-v6.13.v1",
            "checklist_snapshot": deepcopy(dict(checklist_snapshot)),
            "checklist_snapshot_hash": checklist_hash,
            "live_verdict_set": deepcopy(dict(verdict_set)),
            "live_verdict_set_hash": canonical_hash(verdict_set),
            "context": deepcopy(dict(context)),
        }
        digest = canonical_hash(intent)
        return {
            "ready": not missing,
            "missing": sorted(set(missing)),
            "intent": intent,
            "admission_intent_digest": digest,
        }

    def _verify_role_signature(
        self, role: str, signature: Mapping[str, Any], digest: str
    ) -> None:
        trust = self._signers.get(role)
        if not trust:
            raise AdmissionBlocked(f"no trusted {role} signer")
        payload = _signature_payload(
            role=role,
            key_id=str(signature.get("key_id")),
            trust_epoch=str(signature.get("trust_epoch")),
            digest=digest,
        )
        if signature.get("role") != role:
            raise AdmissionBlocked(f"{role} signature has wrong role")
        if signature.get("admission_intent_digest") != digest:
            raise AdmissionBlocked(f"{role} signed a different intent")
        if payload["key_id"] != trust.get("key_id"):
            raise AdmissionBlocked(f"{role} key id is not trusted")
        if payload["trust_epoch"] != trust.get("trust_epoch"):
            raise AdmissionBlocked(f"{role} trust epoch is stale")
        expected = hmac.new(
            trust["key"], canonical_bytes(payload), hashlib.sha256
        ).hexdigest()
        if not isinstance(signature.get("signature"), str) or not hmac.compare_digest(
            signature["signature"], expected
        ):
            raise AdmissionBlocked(f"{role} signature is invalid")

    def build(
        self,
        *,
        checklist_snapshot: Mapping[str, Any],
        verdict_set: Mapping[str, Any],
        context: Mapping[str, Any],
        ds_signature: Mapping[str, Any],
        stat_signature: Mapping[str, Any],
        output_path: Path | str | None = None,
        allow_write: bool = False,
    ) -> dict[str, Any]:
        dry = self.dry_run(
            checklist_snapshot=checklist_snapshot,
            verdict_set=verdict_set,
            context=context,
        )
        if not dry["ready"]:
            raise AdmissionBlocked(
                "admission prerequisites missing: " + ", ".join(dry["missing"])
            )
        digest = dry["admission_intent_digest"]
        self._verify_role_signature("DS", ds_signature, digest)
        self._verify_role_signature("STAT", stat_signature, digest)

        ds_trust = self._signers["DS"]
        stat_trust = self._signers["STAT"]
        if ds_trust.get("key_id") == stat_trust.get("key_id") or ds_trust.get(
            "key"
        ) == stat_trust.get("key"):
            raise AdmissionBlocked("DS and STAT must use distinct role-bound keys")

        unsigned = {
            "schema_id": self.schema_id,
            "status": "ADMITTED",
            "formal_start_allowed": True,
            "raw_dataset_retained": False,
            "effect_peeking": False,
            "admission_intent_digest": digest,
            "intent": dry["intent"],
            "signatures": {
                "DS": deepcopy(dict(ds_signature)),
                "STAT": deepcopy(dict(stat_signature)),
            },
        }
        document = {
            **unsigned,
            "admission_sha256": canonical_hash(unsigned),
        }
        if output_path is not None:
            if not allow_write:
                raise AdmissionBlocked(
                    "formal admission write requires allow_write=True"
                )
            self._atomic_write(Path(output_path), document)
        return document

    @staticmethod
    def _atomic_write(path: Path, document: Mapping[str, Any]) -> None:
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{os.getpid()}.partial")
        data = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        try:
            with temp.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()

    def verify_document(self, document: Mapping[str, Any]) -> bool:
        try:
            unsigned = dict(document)
            observed_hash = unsigned.pop("admission_sha256")
            if not hmac.compare_digest(canonical_hash(unsigned), observed_hash):
                return False
            if (
                document.get("schema_id") != self.schema_id
                or document.get("status") != "ADMITTED"
                or document.get("formal_start_allowed") is not True
                or document.get("raw_dataset_retained") is not False
                or document.get("effect_peeking") is not False
            ):
                return False
            digest = document["admission_intent_digest"]
            intent = document["intent"]
            if digest != canonical_hash(intent):
                return False
            dry = self.dry_run(
                checklist_snapshot=intent["checklist_snapshot"],
                verdict_set=intent["live_verdict_set"],
                context=intent["context"],
            )
            if not dry["ready"] or dry["intent"] != intent:
                return False
            self._verify_role_signature("DS", document["signatures"]["DS"], digest)
            self._verify_role_signature("STAT", document["signatures"]["STAT"], digest)
            ds_trust = self._signers["DS"]
            stat_trust = self._signers["STAT"]
            if ds_trust.get("key_id") == stat_trust.get("key_id") or ds_trust.get(
                "key"
            ) == stat_trust.get("key"):
                return False
            return True
        except (AdmissionBlocked, KeyError, TypeError, ValueError):
            return False


def require_verified_admission(
    admission_path: Path | str,
    builder: AdmissionBuilder,
    *,
    expected_checklist_snapshot_hash: str,
) -> dict[str, Any]:
    """Fail-closed SHK-001B pre-start guard bound to current authority."""

    if not _sha256_value(expected_checklist_snapshot_hash):
        raise AdmissionBlocked(
            "SHK-001B blocked: current checklist snapshot is invalid"
        )

    path = Path(admission_path)
    if not path.is_file():
        raise AdmissionBlocked("SHK-001B blocked: formal admission is absent")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdmissionBlocked("SHK-001B blocked: admission is unreadable") from exc
    if not builder.verify_document(document):
        raise AdmissionBlocked("SHK-001B blocked: admission verification failed")
    embedded_hash = document["intent"].get("checklist_snapshot_hash")
    if not hmac.compare_digest(embedded_hash, expected_checklist_snapshot_hash):
        raise AdmissionBlocked("SHK-001B blocked: admission snapshot is stale")
    return document
