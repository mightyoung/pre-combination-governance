"""Closed registry, provenance envelope, and public execution API."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .algorithms import (
    AlgorithmResult,
    cautious_simple_support,
    lifecycle_precombination,
    lineage_ancestor_elimination,
    normalized_noisy_or,
    partial_dependence_strong_neighbor,
    transport_exactly_once,
    unknown_correlation_interval,
)
from .models import MethodInput, parse_method_input

METHOD_IDS = ("B0", "B1", "B2", "B3", "B4", "B5", "Proposed")
SCHEMA_VERSION = "1.0.0"
SCORER_ID = "preregistered_scorer_v1"
_SCORER_CONTRACT = {
    "id": SCORER_ID,
    "input": "sealed_method_prediction_and_separate_oracle_record",
    "method_visibility": "prediction_only",
    "version": "1.0.0",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _schema_sha256() -> str:
    path = Path(__file__).parents[1] / "contracts" / "method_output.schema.json"
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class MethodSpec:
    method_id: str
    paper_alias: str | None
    method_family: str
    implementation_version: str
    implementation_sha256: str
    semantics_sha256: str
    semantics: Mapping[str, Any]
    input_contract: str
    output_contract: str
    scorer_binding: str
    qualification_evidence_sha256: str | None
    algorithm: Callable[[MethodInput], AlgorithmResult]

    @property
    def formal_eligible(self) -> bool:
        evidence = self.qualification_evidence_sha256
        return (
            evidence is not None
            and len(evidence) == 64
            and all(char in "0123456789abcdef" for char in evidence)
        )

    def execute(self, observations: MethodInput | Mapping[str, Any]) -> dict[str, Any]:
        data = parse_method_input(observations)
        computed = self.algorithm(data)
        prediction = {
            "risk_score": computed.risk_score,
            "risk_interval": [computed.lower, computed.upper],
            "confidence": computed.confidence,
            "evidence_count": computed.evidence_count,
            "active_root_count": computed.active_root_count,
        }
        admissible = list(computed.admissible_actions)
        decision = {
            "label": admissible[0] if len(admissible) == 1 else "ABSTAIN",
            "admissible_actions": admissible,
        }
        audit = {
            "rationale": computed.rationale,
            "canonical_roots": list(computed.canonical_roots),
            "duplicate_count": computed.duplicate_count,
            "eliminated_count": computed.eliminated_count,
            "rebuild_count": computed.rebuild_count,
        }
        input_document = asdict(data)
        input_commitment = _sha(input_document)
        transaction_document = {
            "transaction_id": data.transaction_id,
            "bundle_id": data.bundle_id,
            "method_id": self.method_id,
            "algorithm_seed": data.algorithm_seed,
            "input_commitment_sha256": input_commitment,
        }
        compatibility_result = {
            "risk_score": computed.risk_score,
            "confidence": computed.confidence,
            "evidence_count": computed.evidence_count,
            "rationale": computed.rationale,
            "prediction": prediction,
            "decision": decision,
            "audit": audit,
        }
        envelope: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "transaction_id": data.transaction_id,
            "transaction_sha256": _sha(transaction_document),
            "bundle_id": data.bundle_id,
            "algorithm_seed": data.algorithm_seed,
            "method_id": self.method_id,
            "implementation_version": self.implementation_version,
            "implementation_sha256": self.implementation_sha256,
            "semantics_sha256": self.semantics_sha256,
            "input_commitment_sha256": input_commitment,
            "output_schema_sha256": _schema_sha256(),
            "scorer_id": self.scorer_binding,
            "scorer_sha256": _sha(_SCORER_CONTRACT),
            "formal_eligible": self.formal_eligible,
            "valid": True,
            "failure_code": None,
            "prediction": prediction,
            "decision": decision,
            "audit": audit,
            "result": compatibility_result,
        }
        envelope["result_sha256"] = _sha(envelope)
        return envelope


def _spec(
    method_id: str,
    family: str,
    algorithm: Callable[[MethodInput], AlgorithmResult],
    semantics: dict[str, Any],
) -> MethodSpec:
    source = inspect.getsource(algorithm).replace("\r\n", "\n")
    semantic_document = {"method_id": method_id, "version": "1.0.0", **semantics}
    implementation_document = {"source": source, "semantics": semantic_document}
    implementation_sha256 = _sha(implementation_document)
    semantics_sha256 = _sha(semantic_document)
    qualification_evidence_sha256 = _sha(
        {
            "method_id": method_id,
            "implementation_sha256": implementation_sha256,
            "semantics_sha256": semantics_sha256,
            "output_schema_sha256": _schema_sha256(),
            "scorer_sha256": _sha(_SCORER_CONTRACT),
            "input_contract": "rfb.methods.MethodInput@1.0.0",
        }
    )
    return MethodSpec(
        method_id=method_id,
        paper_alias="A" if method_id == "Proposed" else None,
        method_family=family,
        implementation_version="1.0.0",
        implementation_sha256=implementation_sha256,
        semantics_sha256=semantics_sha256,
        semantics=MappingProxyType(semantic_document),
        input_contract="rfb.methods.MethodInput@1.0.0",
        output_contract="rfb.contracts/method_output.schema.json@1.0.0",
        scorer_binding=SCORER_ID,
        qualification_evidence_sha256=qualification_evidence_sha256,
        algorithm=algorithm,
    )


_BUILTINS = (
    _spec(
        "B0",
        "baseline",
        normalized_noisy_or,
        {"rule": "normalized_conjunctive", "frame": "binary_simple_support"},
    ),
    _spec(
        "B1",
        "baseline",
        transport_exactly_once,
        {"rule": "transport_exactly_once", "dedupe_key": ["message_id", "version"]},
    ),
    _spec(
        "B2",
        "baseline",
        lineage_ancestor_elimination,
        {"rule": "lineage_ancestor_elimination", "lineage_source": "declared_only"},
    ),
    _spec(
        "B3",
        "baseline",
        cautious_simple_support,
        {
            "rule": "cautious",
            "scope": "binary_simple_support",
            "operator": "maximum_canonical_weight",
        },
    ),
    _spec(
        "B4",
        "baseline",
        partial_dependence_strong_neighbor,
        {
            "rule": "er_tld_family_strong_neighbor",
            "dependence": 0.70,
            "neighbor_weight": 0.30,
            "endpoint_zero": "independent_conjunctive",
            "endpoint_one": "cautious_strongest",
        },
    ),
    _spec(
        "B5",
        "baseline",
        unknown_correlation_interval,
        {
            "rule": "unknown_correlation_frechet_interval",
            "point_policy": "upper_safety_bound",
            "duplicate_policy": "identical_public_support_invariant",
        },
    ),
    _spec(
        "Proposed",
        "proposed",
        lifecycle_precombination,
        {
            "rule": "lifecycle_consistent_precombination",
            "controls": ["EQUIVALENCE", "SUPERSEDE", "MERGE", "RETIRE", "REPLAY"],
            "exact_retry": True,
            "canonical_root_rebuild": True,
        },
    ),
)

BUILTIN_REGISTRY: Mapping[str, MethodSpec] = MappingProxyType(
    {spec.method_id: spec for spec in _BUILTINS}
)


def get_registry() -> dict[str, MethodSpec]:
    return dict(BUILTIN_REGISTRY)


def get_method(method_id: str) -> MethodSpec:
    try:
        return BUILTIN_REGISTRY[method_id]
    except KeyError as exc:
        raise ValueError(f"unknown method_id: {method_id}") from exc


def run_method(
    method_id: str, observations: MethodInput | Mapping[str, Any]
) -> dict[str, Any]:
    return get_method(method_id).execute(observations)


def _validate_registry(registry: Mapping[str, MethodSpec]) -> None:
    if tuple(registry) != METHOD_IDS or len(registry) != len(METHOD_IDS):
        raise ValueError("closed registry requires exactly B0-B5 and Proposed in order")
    if any(registry[method_id].method_id != method_id for method_id in METHOD_IDS):
        raise ValueError("registry key and method_id differ")


def run_all(
    observations: MethodInput | Mapping[str, Any],
    *,
    registry: Mapping[str, MethodSpec] | None = None,
) -> dict[str, dict[str, Any]]:
    selected = BUILTIN_REGISTRY if registry is None else registry
    _validate_registry(selected)
    return {
        method_id: selected[method_id].execute(observations) for method_id in METHOD_IDS
    }


def generate_registry_document(
    registry: Mapping[str, MethodSpec] | None = None,
) -> dict[str, Any]:
    selected = BUILTIN_REGISTRY if registry is None else registry
    _validate_registry(selected)
    rows = []
    for method_id in METHOD_IDS:
        spec = selected[method_id]
        rows.append(
            {
                "method_id": method_id,
                "paper_alias": spec.paper_alias,
                "method_family": spec.method_family,
                "implementation_version": spec.implementation_version,
                "implementation_sha256": spec.implementation_sha256,
                "semantics_sha256": spec.semantics_sha256,
                "semantics": dict(spec.semantics),
                "input_contract": spec.input_contract,
                "output_contract": spec.output_contract,
                "output_schema_sha256": _schema_sha256(),
                "scorer_binding": spec.scorer_binding,
                "formal_eligible": spec.formal_eligible,
                "qualification_evidence_sha256": spec.qualification_evidence_sha256,
            }
        )
    document = {"schema_version": SCHEMA_VERSION, "closed": True, "methods": rows}
    document["registry_sha256"] = _sha(document)
    return document
