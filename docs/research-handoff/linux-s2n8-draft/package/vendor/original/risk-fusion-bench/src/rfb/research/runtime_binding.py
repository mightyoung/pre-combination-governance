"""Runtime-profile bindings shared by the controller, worker and receipts."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rfb.contracts.canonical_json import canonical_bytes, sha256_hex

from .pinned_runtime import (
    PROFILE_ID,
    PinnedRuntimeError,
    verify_controller_staging,
)

PINNED_MANIFEST_FIELD = "pinned_runtime_manifest"
PINNED_ROOT_FIELD = "pinned_runtime_root"
PINNED_HASH_FIELD = "pinned_runtime_manifest_sha256"
PINNED_FINGERPRINT_FIELD = "pinned_runtime_closure_fingerprint"


def pinned_runtime_binding(manifest: Mapping[str, Any]) -> dict[str, str]:
    """Verify and derive the immutable receipt binding for a pinned profile.

    The controller is the only component allowed to verify a local closure.
    Remote transports must carry the resulting two hashes and may not infer or
    replace them with a fixture runtime.
    """
    if manifest.get("runtime_dependency_profile") != PROFILE_ID:
        return {}
    value = manifest.get(PINNED_MANIFEST_FIELD)
    root = manifest.get(PINNED_ROOT_FIELD)
    if not isinstance(value, Mapping) or not isinstance(root, str) or not root:
        raise PinnedRuntimeError("pinned runtime manifest/root binding missing")
    verify_controller_staging(value, Path(root))
    closure = value.get("closure_fingerprint")
    if not isinstance(closure, str) or not closure.startswith("sha256:"):
        raise PinnedRuntimeError("pinned runtime closure fingerprint missing")
    return {
        PINNED_HASH_FIELD: sha256_hex(canonical_bytes(dict(value))),
        PINNED_FINGERPRINT_FIELD: closure,
    }


def validate_pinned_receipt_binding(value: Mapping[str, Any]) -> None:
    """Require complete pinned hashes whenever a pinned profile is recorded."""
    if value.get("runtime_dependency_profile") != PROFILE_ID:
        return
    manifest_hash = value.get(PINNED_HASH_FIELD)
    fingerprint = value.get(PINNED_FINGERPRINT_FIELD)
    if not isinstance(manifest_hash, str) or len(manifest_hash) != 64:
        raise ValueError("pinned runtime manifest hash required")
    try:
        int(manifest_hash, 16)
    except ValueError as exc:
        raise ValueError("pinned runtime manifest hash invalid") from exc
    if not isinstance(fingerprint, str) or not fingerprint.startswith("sha256:"):
        raise ValueError("pinned runtime closure fingerprint required")
    if len(fingerprint) != 71:
        raise ValueError("pinned runtime closure fingerprint invalid")


def runtime_binding_args(binding: Mapping[str, Any]) -> list[str]:
    """Stable argv representation for runtime and worker launch metadata."""
    args = [
        "--runtime-file-sha256",
        str(binding["runtime_file_sha256"]),
        "--runtime-source-sha256",
        str(binding["runtime_source_sha256"]),
        "--runtime-manifest-sha256",
        str(binding["runtime_manifest_sha256"]),
        "--runtime-dependency-profile",
        str(binding["runtime_dependency_profile"]),
        "--runtime-path",
        str(binding["runtime_path"]),
    ]
    if PINNED_HASH_FIELD in binding or PINNED_FINGERPRINT_FIELD in binding:
        if PINNED_HASH_FIELD not in binding or PINNED_FINGERPRINT_FIELD not in binding:
            raise ValueError("incomplete pinned runtime launch binding")
        args.extend(
            ["--pinned-runtime-manifest-sha256", str(binding[PINNED_HASH_FIELD])]
        )
        args.extend(
            [
                "--pinned-runtime-closure-fingerprint",
                str(binding[PINNED_FINGERPRINT_FIELD]),
            ]
        )
    return args
