"""Closed schemas for stage-1 normative package manifests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .failure_codes import FailureCode
from .schema_versions import parse_semantic_version


PENDING_HASH = "PENDING-HASH"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SchemaError:
    code: FailureCode
    path: str
    message: str


@dataclass(frozen=True)
class SchemaValidationResult:
    schema_name: str
    valid: bool
    errors: tuple[SchemaError, ...]
    pending_hash_paths: tuple[str, ...]


@dataclass(frozen=True)
class FieldSpec:
    kind: str
    required: bool = True
    item_schema: dict[str, "FieldSpec"] | None = None
    pending_capable: bool = False


def _field(kind: str, *, pending_capable: bool = False) -> FieldSpec:
    return FieldSpec(kind, pending_capable=pending_capable)


def _str() -> FieldSpec:
    return _field("str")


def _label() -> FieldSpec:
    return _field("label")


def _schema_version() -> FieldSpec:
    return _field("schema_version")


def _hash() -> FieldSpec:
    return _field("hash", pending_capable=True)


def _int() -> FieldSpec:
    return _field("int")


def _bool() -> FieldSpec:
    return _field("bool")


def _edge_array() -> FieldSpec:
    return FieldSpec(
        "array",
        item_schema={
            "from": _str(),
            "to": _str(),
        },
    )


SCHEMA_DEFINITIONS: dict[str, dict[str, FieldSpec]] = {
    "NormativeReleaseManifest": {
        "schema_version": _schema_version(),
        "release_id": _str(),
        "main_version": _label(),
        "main_sha256": _hash(),
        "S1_version": _label(),
        "S1_sha256": _hash(),
        "S2_version": _label(),
        "S2_sha256": _hash(),
        "experiment_version": _label(),
        "experiment_sha256": _hash(),
        "ClaimRegister_sha256": _hash(),
        "SafetyArtifactIR_schema_version": _schema_version(),
        "SafetyArtifactIR_schema_sha256": _hash(),
        "SafetyArtifactIR_sha256": _hash(),
        "compiler_version": _label(),
        "compiler_sha256": _hash(),
        "failure_code_registry_sha256": _hash(),
        "RootIdentityManifest_schema_sha256": _hash(),
        "AcquisitionManifest_schema_sha256": _hash(),
        "Eventifier_version": _label(),
        "Eventifier_sha256": _hash(),
        "SourceAdapterRegistry_sha256": _hash(),
        "RootLevelMapperRegistry_sha256": _hash(),
        "CouplingFamilyRegistry_sha256": _hash(),
        "SetwiseEligibilityGenerator_version": _label(),
        "SetwiseEligibilityGenerator_sha256": _hash(),
        "OperationalSafetyArtifact_sha256": _hash(),
        "MethodRegistry_sha256": _hash(),
        "ArmFrameMatrix_sha256": _hash(),
        "SeedManifest_sha256": _hash(),
        "AllocationManifest_sha256": _hash(),
        "TestManifest_sha256": _hash(),
        "analysis_container_sha256": _hash(),
        "dependency_edges": _edge_array(),
    },
    "RootIdentity": {
        "schema_version": _schema_version(),
        "credential_subject": _str(),
        "acquisition_uuid": _str(),
        "root_epoch": _str(),
        "root_type": _str(),
        "TTL_policy_id": _str(),
        "acquisition_manifest_hash": _hash(),
        "signature": _str(),
    },
    "Acquisition": {
        "schema_version": _schema_version(),
        "acquisition_uuid": _str(),
        "root_epoch": _str(),
        "Eventifier_id": _str(),
        "Eventifier_version": _label(),
        "Eventifier_sha256": _hash(),
        "trusted_clock_domain": _str(),
        "t_start": _str(),
        "t_end": _str(),
        "causal_boundary_id": _str(),
        "causal_boundary_sha256": _hash(),
        "raw_acquisition_identity": _str(),
        "segmentation_evidence_sha256": _hash(),
        "signature": _str(),
    },
    "Event": {
        "schema_version": _schema_version(),
        "event_id": _str(),
        "root_id": _str(),
        "acquisition_id": _str(),
        "eventifier_version": _label(),
        "event_sha256": _hash(),
    },
    "Method": {
        "schema_version": _schema_version(),
        "method_id": _str(),
        "method_family": _str(),
        "implementation_version": _label(),
        "implementation_sha256": _hash(),
    },
    "ArmFrame": {
        "schema_version": _schema_version(),
        "arm_id": _str(),
        "frame_id": _str(),
        "method_id": _str(),
        "eligibility_sha256": _hash(),
    },
    "Seed": {
        "schema_version": _schema_version(),
        "seed_id": _str(),
        "algorithm_seed": _int(),
        "commitment_sha256": _hash(),
    },
    "Allocation": {
        "schema_version": _schema_version(),
        "allocation_id": _str(),
        "seed_id": _str(),
        "arm_id": _str(),
        "bundle_id": _str(),
    },
    "Test": {
        "schema_version": _schema_version(),
        "test_id": _str(),
        "allocation_id": _str(),
        "sealed": _bool(),
        "manifest_sha256": _hash(),
    },
}

EXPECTED_SCHEMA_VERSIONS: dict[str, str] = {
    name: "1.0.0" for name in SCHEMA_DEFINITIONS
}


def manifest_hash_fields() -> tuple[str, ...]:
    return tuple(
        name
        for name in SCHEMA_DEFINITIONS["NormativeReleaseManifest"]
        if name.endswith("_sha256")
    )


def _non_pending_string(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value != PENDING_HASH
        and value != "PENDING_HASH"
        and not any(0xD800 <= ord(ch) <= 0xDFFF for ch in value)
    )


def _validate_object(
    obj: Any,
    fields: dict[str, FieldSpec],
    path: str,
    errors: list[SchemaError],
    pending: list[str],
) -> None:
    if not isinstance(obj, dict):
        errors.append(
            SchemaError(FailureCode.MANIFEST_SCHEMA_INVALID, path, "expected object")
        )
        return
    allowed = set(fields)
    for key in obj:
        if key not in allowed:
            errors.append(
                SchemaError(
                    FailureCode.MANIFEST_SCHEMA_INVALID,
                    f"{path}.{key}",
                    "unknown field",
                )
            )
    for name, spec in fields.items():
        child_path = f"{path}.{name}"
        if name not in obj:
            if spec.required:
                errors.append(
                    SchemaError(
                        FailureCode.MANIFEST_SCHEMA_INVALID,
                        child_path,
                        "missing required field",
                    )
                )
            continue
        _validate_value(obj[name], spec, child_path, errors, pending)


def _validate_value(
    value: Any,
    spec: FieldSpec,
    path: str,
    errors: list[SchemaError],
    pending: list[str],
) -> None:
    if value == PENDING_HASH:
        if spec.pending_capable:
            pending.append(path)
        else:
            errors.append(
                SchemaError(
                    FailureCode.MANIFEST_SCHEMA_INVALID,
                    path,
                    "PENDING-HASH not allowed here",
                )
            )
            return

    if spec.kind == "str":
        ok = _non_pending_string(value)
    elif spec.kind == "label":
        ok = _non_pending_string(value)
    elif spec.kind == "schema_version":
        try:
            parse_semantic_version(value)
            ok = True
        except (TypeError, ValueError):
            ok = False
    elif spec.kind == "hash":
        ok = isinstance(value, str) and (
            value == PENDING_HASH or bool(_SHA256_RE.fullmatch(value))
        )
    elif spec.kind == "int":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif spec.kind == "bool":
        ok = isinstance(value, bool)
    elif spec.kind == "array":
        ok = isinstance(value, list)
        if ok and spec.item_schema is not None:
            for idx, child in enumerate(value):
                _validate_object(
                    child, spec.item_schema, f"{path}[{idx}]", errors, pending
                )
    else:
        ok = False
    if not ok:
        errors.append(
            SchemaError(
                FailureCode.MANIFEST_SCHEMA_INVALID, path, f"expected {spec.kind}"
            )
        )


def collect_pending_hash_paths(value: Any, path: str = "$") -> tuple[str, ...]:
    """Recursively find exact ``PENDING-HASH`` placeholders."""

    found: list[str] = []
    if value == PENDING_HASH:
        found.append(path)
    elif isinstance(value, dict):
        for key, child in value.items():
            found.extend(collect_pending_hash_paths(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            found.extend(collect_pending_hash_paths(child, f"{path}[{idx}]"))
    return tuple(found)


def validate_schema(schema_name: str, obj: Any) -> SchemaValidationResult:
    """Validate *obj* against one of the nine closed schemas."""

    if schema_name not in SCHEMA_DEFINITIONS:
        error = SchemaError(
            FailureCode.SCHEMA_INCOMPATIBLE, "$", f"unknown schema {schema_name}"
        )
        return SchemaValidationResult(schema_name, False, (error,), ())
    errors: list[SchemaError] = []
    pending: list[str] = []
    _validate_object(obj, SCHEMA_DEFINITIONS[schema_name], "$", errors, pending)
    return SchemaValidationResult(
        schema_name, not errors, tuple(errors), tuple(pending)
    )
