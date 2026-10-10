from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from jsonschema import ValidationError, validate

from .models import reject_categorical, validate_classification

CLASSIFICATION_FIELDS = (
    "run_id",
    "execution_lane",
    "classification",
    "formal_gate_effect",
    "formal_admission_eligible",
    "shk001b_eligible",
    "contains_formal_claims",
)
_DENY = (
    "d_test",
    "gatechecklist",
    "formal_stage_admission",
    "authority",
    "current",
    "purge",
    "shk-001b",
    "live_verdict",
)


def _check_paths(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _check_paths(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _check_paths(v, f"{path}[{i}]")
    elif isinstance(value, str) and (
        path.endswith("root") or path.endswith("_root") or "path" in path.lower()
    ):
        norm = value.replace("\\", "/").casefold()
        if (
            any(token in norm for token in _DENY)
            or ".." in PurePosixPath(norm).parts
            or ".." in PureWindowsPath(value).parts
        ):
            raise ValueError(f"{path}: forbidden or non-confined path")


def _check_manifest_paths(manifest: dict) -> None:
    # The controller-owned pinned manifest has its own strict schema, relative
    # path confinement, hashes and closure verification.  Its source inventory
    # may legitimately contain package names such as ``rfb/authority``; those
    # are evidence paths, not user-selected write capabilities.
    _check_paths({k: v for k, v in manifest.items() if k != "pinned_runtime_manifest"})


def validate_manifest(manifest: dict, *, phase: str | None = None) -> dict:
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    selected_phase = phase or manifest.get("manifest_phase")
    if selected_phase not in {
        None,
        "user_manifest",
        "prepared_manifest",
        "execution_manifest",
    }:
        raise ValueError("MANIFEST_PHASE_INVALID")
    capability_fields = {
        "approved_remote_parent",
        "remote_run_root",
        "remote_root",
        "expected_fingerprint",
        "pinned_runtime_root",
        "pinned_runtime_manifest",
    }
    if selected_phase == "user_manifest" and capability_fields & set(manifest):
        raise ValueError("CONTROLLER_CAPABILITY_FIELD_FORBIDDEN")
    if selected_phase == "execution_manifest" or (
        selected_phase == "prepared_manifest"
        and {"approved_remote_parent", "remote_run_root"} & set(manifest)
    ):
        missing = {"approved_remote_parent", "remote_run_root"} - set(manifest)
        if missing:
            raise ValueError("CONTROLLER_CAPABILITY_BINDING_MISSING")
    if selected_phase == "execution_manifest":
        required = {
            "prepared_manifest_sha256",
            "preflight_evidence",
            "run_root_creation_evidence",
            "preflight_evidence_sha256",
            "runtime_format",
            "runtime_path",
            "runtime_file_sha256",
            "runtime_source_sha256",
            "runtime_manifest_sha256",
            "runtime_dependency_profile",
        }
        if not required <= set(manifest):
            raise ValueError("EXECUTION_MANIFEST_BINDING_MISSING")
        if manifest.get("runtime_dependency_profile") == "tep_nonconfirmatory_v1":
            pinned_required = {
                "pinned_runtime_manifest",
                "pinned_runtime_root",
                "pinned_runtime_manifest_sha256",
                "pinned_runtime_closure_fingerprint",
            }
            if not pinned_required <= set(manifest):
                raise ValueError("PINNED_RUNTIME_BINDING_MISSING")
    runtime_format = manifest.get("runtime_format")
    if runtime_format == "python_zipapp_v1":
        raise ValueError("RUNTIME_FORMAT_LEGACY_REJECTED")
    if runtime_format is not None and runtime_format not in {
        "python_zipapp_stdlib_v1",
        "python_pinned_venv_v1",
    }:
        raise ValueError("RUNTIME_PROFILE_UNAVAILABLE")
    if runtime_format == "python_zipapp_stdlib_v1" and manifest.get(
        "runtime_dependency_profile"
    ) not in {None, "stdlib_only"}:
        raise ValueError("RUNTIME_PROFILE_FIELD_MIXED")
    if (
        runtime_format == "python_pinned_venv_v1"
        and manifest.get("runtime_dependency_profile") != "tep_nonconfirmatory_v1"
    ):
        raise ValueError("RUNTIME_PROFILE_FIELD_MIXED")
    validate_classification(
        {k: manifest.get(k) for k in manifest if k in CLASSIFICATION_FIELDS[1:]},
        exact=False,
    )
    # Controller-owned capability paths are validated separately and may be
    # absolute; all source/code/config/input paths remain categorically banned.
    expected_fingerprint = manifest.get("expected_fingerprint")
    if expected_fingerprint is not None and not re.fullmatch(
        r"SHA256:[A-Za-z0-9+/]{43}", expected_fingerprint
    ):
        raise ValueError(
            "expected_fingerprint must be an exact SHA256 host fingerprint"
        )
    capability = {
        k: manifest.get(k)
        for k in (
            "remote_root",
            "approved_remote_parent",
            "remote_run_root",
            "local_root",
            "local_results",
            "staged_manifest_path",
            "known_hosts",
            "dataset_root",
            "preflight_evidence",
            "run_root_creation_evidence",
            "runtime_path",
            "pinned_runtime_root",
            "pinned_runtime_manifest",
            # Valid SHA-256 fingerprints can contain '/' and superficially
            # resemble POSIX paths. Exempt only this schema-validated field;
            # categorical scanning remains unchanged for all other values.
            "expected_fingerprint",
        )
        if k in manifest
    }
    scrubbed = {k: v for k, v in manifest.items() if k not in capability}
    reject_categorical(scrubbed)
    _check_manifest_paths(manifest)
    schema = json.loads(
        (
            Path(__file__).parent.parent
            / "contracts"
            / "research_run_manifest.schema.json"
        ).read_text(encoding="utf-8")
    )
    try:
        validate(manifest, schema)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return manifest
