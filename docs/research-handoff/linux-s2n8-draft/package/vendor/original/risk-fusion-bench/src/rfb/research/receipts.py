"""Closed-result scanning and two-phase receipt validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import ValidationError
from jsonschema import validate as schema_validate

from rfb.contracts.canonical_json import canonical_bytes, sha256_hex

from .models import CLASSIFICATION, reject_categorical, validate_classification
from .runtime_binding import validate_pinned_receipt_binding

_RUNTIME_BINDING_FIELDS = {
    "runtime_format",
    "runtime_path",
    "runtime_file_sha256",
    "runtime_source_sha256",
    "runtime_manifest_sha256",
    "runtime_dependency_profile",
}
_TEP_ADAPTER_ID = "tep_nonconfirmatory_v1"
_R77_LEGACY_RUN_ID = "g014-r006-20260816T130000Z-r77"
_R77_LEGACY_SELF_HASH = (
    "0a2bb101abd5365182dbf44bf97d4c65eeaedc55c2189e69f7cf425c9dc17859"
)
_R77_LEGACY_RECEIPT_HASH = (
    "dba7dd8c1360ca34c83f28be06993d53a4a25284c2114f43a477f7ba26b4a9df"
)


def _is_frozen_r77_legacy_receipt(receipt: Mapping[str, Any]) -> bool:
    """Permit scorer-less compatibility only for the exact frozen r77 receipt."""
    return (
        receipt.get("run_id") == _R77_LEGACY_RUN_ID
        and receipt.get("adapter_id") == _TEP_ADAPTER_ID
        and receipt.get("self_hash") == _R77_LEGACY_SELF_HASH
        and sha256_hex(canonical_bytes(receipt)) == _R77_LEGACY_RECEIPT_HASH
    )


def _validate_runtime_binding(value: Mapping[str, Any]) -> None:
    present = _RUNTIME_BINDING_FIELDS & set(value)
    if present and present != _RUNTIME_BINDING_FIELDS:
        raise ValueError("incomplete runtime binding")
    if not present:
        validate_pinned_receipt_binding(value)
        return
    if value.get("runtime_format") == "python_zipapp_v1":
        raise ValueError("RUNTIME_FORMAT_LEGACY_REJECTED")
    if value.get("runtime_format") not in {
        "python_zipapp_stdlib_v1",
        "python_pinned_venv_v1",
    }:
        raise ValueError("runtime format mismatch")
    expected_profile = (
        "stdlib_only"
        if value.get("runtime_format") == "python_zipapp_stdlib_v1"
        else "tep_nonconfirmatory_v1"
    )
    if value.get("runtime_dependency_profile") != expected_profile:
        raise ValueError("runtime dependency profile mismatch")
    if value.get("runtime_format") == "python_zipapp_stdlib_v1":
        expected_name = f"{value['runtime_file_sha256']}.pyz"
        if (
            str(value.get("runtime_path", "")).replace("\\", "/").rsplit("/", 1)[-1]
            != expected_name
        ):
            raise ValueError("runtime path/hash mismatch")
    validate_pinned_receipt_binding(value)


def _check_class(value: Mapping[str, Any]) -> None:
    for k, v in CLASSIFICATION.items():
        if value.get(k) != v:
            raise ValueError(f"immutable classification mismatch: {k}")


def scan_closed_result(directory: str | Path) -> None:
    root = Path(directory)
    if not root.is_dir():
        raise ValueError("result directory missing")
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if ".partial" in path.name:
            raise ValueError("partial artifact in closed result")
        raw = path.read_bytes()
        lowered = raw.lower()
        if b"\x00" in raw or any(
            token in lowered
            for token in (b"truth", b"password", b"secret", b"api_key", b"raw dataset")
        ):
            raise ValueError(
                f"binary categorical raw/truth/credential bytes rejected: {path}"
            )
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            # No diagnostic/raw-data exception: undecodable bytes cannot be
            # classified safely and therefore fail closed.
            raise ValueError(f"binary/undecodable result rejected: {path}") from exc
        reject_categorical(text, str(path))


def result_tree_manifest(
    directory: str | Path, *, allowlist: set[str] | None = None
) -> dict:
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError("result directory missing")
    entries = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if allowlist is not None and rel not in allowlist:
            raise ValueError(f"unallowlisted result: {rel}")
        data = path.read_bytes()
        entries[rel] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    scan_closed_result(root)
    return entries


def _tree_digest(entries: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_bytes(dict(sorted(entries.items()))))


def _validate_timestamp(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid COPY_VERIFICATION timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("COPY_VERIFICATION timestamp must be timezone-aware")
    if parsed.utcoffset().total_seconds() != 0:
        raise ValueError("COPY_VERIFICATION timestamp must be UTC")


def _validate_directory_path(value: str, *, label: str, require_exists: bool) -> Path:
    raw = Path(value)
    current = raw.absolute()
    while True:
        if current.exists() and current.is_symlink():
            raise ValueError(f"{label} contains symlink")
        if current == current.parent:
            break
        current = current.parent
    resolved = raw.resolve()
    if require_exists and (not resolved.is_dir() or resolved.is_symlink()):
        raise ValueError(f"{label} is not a directory")
    return resolved


def validate_copy_verification(
    evidence: Mapping[str, Any],
    *,
    remote_receipt: Mapping[str, Any] | None = None,
    local_result_path: str | Path | None = None,
) -> Mapping[str, Any]:
    """Validate a durable COPY_VERIFICATION.json evidence object.

    The validator is deliberately strict: the evidence is independently
    self-hashed, binds both prepared and execution manifests, and records the
    exact remote/local tree digests.  Existing local copies are reopened and
    rehashed when a path is available.
    """
    schema = json.loads(
        (
            Path(__file__).parent.parent / "contracts" / "copy_verification.schema.json"
        ).read_text(encoding="utf-8")
    )
    try:
        schema_validate(dict(evidence), schema)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    validate_classification({k: evidence.get(k) for k in CLASSIFICATION}, exact=True)
    _validate_runtime_binding(evidence)
    if (
        evidence.get("remote_result_tree_sha256")
        != evidence.get("local_result_tree_sha256")
        or evidence.get("equal_tree") is not True
    ):
        raise ValueError("COPY_VERIFICATION tree mismatch")
    _validate_timestamp(evidence["verified_at_utc"])
    body = {k: v for k, v in evidence.items() if k != "self_hash"}
    if sha256_hex(canonical_bytes(body)) != evidence["self_hash"]:
        raise ValueError("COPY_VERIFICATION self-hash mismatch")
    if remote_receipt is not None:
        validate_remote_receipt(remote_receipt)
        if evidence["remote_receipt_hash"] != sha256_hex(
            canonical_bytes(dict(remote_receipt))
        ):
            raise ValueError("COPY_VERIFICATION remote receipt hash mismatch")
        if evidence["remote_receipt_self_hash"] != remote_receipt.get("self_hash"):
            raise ValueError("COPY_VERIFICATION remote self-hash mismatch")
        for field in (
            "run_id",
            "execution_manifest_sha256",
            "prepared_manifest_sha256",
            "preflight_evidence_sha256",
            "runtime_format",
            "runtime_path",
            "runtime_file_sha256",
            "runtime_source_sha256",
            "runtime_manifest_sha256",
            "runtime_dependency_profile",
            "pinned_runtime_manifest_sha256",
            "pinned_runtime_closure_fingerprint",
        ):
            if field in remote_receipt and evidence.get(field) != remote_receipt.get(
                field
            ):
                raise ValueError(f"COPY_VERIFICATION binding mismatch: {field}")
        if evidence["remote_result_tree_sha256"] != remote_receipt.get(
            "remote_result_tree_sha256"
        ):
            raise ValueError("COPY_VERIFICATION remote tree mismatch")
    path_value = local_result_path or evidence.get("local_result_path")
    if path_value:
        local = _validate_directory_path(
            str(path_value), label="local result path", require_exists=True
        )
        if str(local) != str(Path(evidence["local_result_path"]).resolve()):
            raise ValueError("COPY_VERIFICATION local path mismatch")
        actual = _tree_digest(result_tree_manifest(local))
        if actual != evidence["local_result_tree_sha256"]:
            raise ValueError("COPY_VERIFICATION local tree mismatch")
    return evidence


def validate_remote_receipt(receipt: Mapping[str, Any]) -> Mapping[str, Any]:
    schema = json.loads(
        (
            Path(__file__).parent.parent
            / "contracts"
            / "remote_execution_receipt.schema.json"
        ).read_text()
    )
    try:
        schema_validate(dict(receipt), schema)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    validate_classification({k: receipt.get(k) for k in CLASSIFICATION}, exact=True)
    _validate_runtime_binding(receipt)
    scorer_artifact = receipt.get("scorer_artifact")
    if scorer_artifact is None:
        if receipt.get("adapter_id") == _TEP_ADAPTER_ID and not (
            _is_frozen_r77_legacy_receipt(receipt)
        ):
            raise ValueError("REMOTE_TEP_SCORER_ARTIFACT_REQUIRED")
    else:
        if (
            not isinstance(scorer_artifact, Mapping)
            or scorer_artifact.get("excluded_from_result_tree") is not True
            or scorer_artifact.get("ephemeral") is not True
            or scorer_artifact.get("d_test_namespace_touched") is not False
        ):
            raise ValueError("remote scorer artifact boundary invalid")
        status = scorer_artifact.get("status")
        scientific_eligible = scorer_artifact.get("scientific_eligible")
        failure_code = scorer_artifact.get("failure_code")
        if status == "SEALED":
            if scientific_eligible is not True or failure_code is not None:
                raise ValueError("remote scorer artifact success invalid")
        elif status == "SCORER_FAILED":
            if scientific_eligible is not False or failure_code not in {
                "SCORER_TRUTH_ALIGNMENT_INVALID",
                "SCORER_TRUTH_SEAL_FAILED",
            }:
                raise ValueError("remote scorer artifact failure invalid")
        elif status == "NOT_APPLICABLE":
            if scientific_eligible is not False or failure_code is not None:
                raise ValueError("remote scorer artifact not-applicable invalid")
        else:
            raise ValueError("remote scorer artifact status invalid")
        if receipt.get("adapter_id") == _TEP_ADAPTER_ID and status != "SEALED":
            if status == "SCORER_FAILED":
                raise ValueError(f"REMOTE_SCORER_FAILED:{failure_code}")
            raise ValueError("REMOTE_TEP_SCORER_NOT_ELIGIBLE")
    if receipt.get("terminal_state") not in {
        "RESULT_SEALED_REMOTE",
        "FAILED",
        "TIMEOUT",
        "CANCELLED",
        "BLOCKED",
    }:
        raise ValueError("remote receipt cannot be SUCCEEDED")
    if not receipt.get("self_hash") or receipt.get("self_hash") == "0" * 64:
        raise ValueError("remote receipt self-hash required")
    body = {k: v for k, v in receipt.items() if k != "self_hash"}
    if sha256_hex(canonical_bytes(body)) != receipt["self_hash"]:
        raise ValueError("remote receipt self-hash mismatch")
    if receipt.get("terminal_state") == "RESULT_SEALED_REMOTE":
        if not receipt.get("result_path") or not receipt.get(
            "remote_result_tree_sha256"
        ):
            raise ValueError("incomplete remote receipt")
        required = {
            "run_id",
            "execution_manifest_sha256",
            "result_tree_sha256",
            "receipt_self_hash",
            "directory_durable",
            "formal_artifacts_created",
            "formal_gate_effect",
            "shk001b_started",
        }
        if (
            not required <= set(receipt)
            or receipt.get("directory_durable") is not True
            or receipt.get("formal_artifacts_created") != []
            or receipt.get("shk001b_started") is not False
        ):
            raise ValueError("incomplete remote receipt")
        inner = {
            k: v
            for k, v in receipt.items()
            if k not in {"self_hash", "receipt_self_hash", *CLASSIFICATION}
        }
        if sha256_hex(canonical_bytes(inner)) != receipt["receipt_self_hash"]:
            raise ValueError("remote inner receipt hash mismatch")
        path_value = receipt.get("result_path")
        if path_value:
            raw_result_path = Path(path_value)
            current = raw_result_path.absolute()
            while True:
                if current.exists() and current.is_symlink():
                    raise ValueError("remote result path invalid")
                if current == current.parent:
                    break
                current = current.parent
            result_path = raw_result_path.resolve()
            if result_path.exists():
                if not result_path.is_dir() or result_path.is_symlink():
                    raise ValueError("remote result path invalid")
                entries = result_tree_manifest(result_path)
                expected = receipt.get("result_tree_sha256")
                if expected and _tree_digest(entries) != expected:
                    raise ValueError("remote result tree hash mismatch")
    return receipt


def require_remote_scorer_ready_for_final(receipt: Mapping[str, Any]) -> None:
    """Require a scientific scorer seal for TEP before controller success."""
    scorer_artifact = receipt.get("scorer_artifact")
    if not isinstance(scorer_artifact, Mapping):
        if receipt.get("adapter_id") == _TEP_ADAPTER_ID and not (
            _is_frozen_r77_legacy_receipt(receipt)
        ):
            raise ValueError("REMOTE_TEP_SCORER_ARTIFACT_REQUIRED")
        return
    if scorer_artifact.get("status") == "SCORER_FAILED":
        raise ValueError(
            "REMOTE_SCORER_FAILED:"
            f"{scorer_artifact.get('failure_code', 'SCORER_TRUTH_SEAL_FAILED')}"
        )
    if receipt.get("adapter_id") == _TEP_ADAPTER_ID and (
        scorer_artifact.get("status") != "SEALED"
        or scorer_artifact.get("scientific_eligible") is not True
    ):
        raise ValueError("REMOTE_TEP_SCORER_NOT_ELIGIBLE")


def validate_final_receipt(receipt: Mapping[str, Any]) -> Mapping[str, Any]:
    schema = json.loads(
        (
            Path(__file__).parent.parent / "contracts" / "final_run_receipt.schema.json"
        ).read_text()
    )
    # Resolve the sibling COPY_VERIFICATION contract explicitly.  The
    # validator receives an in-memory schema (without a filesystem base URI),
    # so a relative JSON-Schema $ref cannot otherwise be resolved reliably.
    copy_schema = json.loads(
        (
            Path(__file__).parent.parent / "contracts" / "copy_verification.schema.json"
        ).read_text(encoding="utf-8")
    )
    # Embedded ``#/$defs/hash`` references resolve against the enclosing
    # final-receipt document, so copy the shared definition into that root.
    schema.setdefault("$defs", {})["hash"] = copy_schema["$defs"]["hash"]
    schema["properties"]["copy_verification"] = copy_schema
    try:
        schema_validate(dict(receipt), schema)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    validate_classification({k: receipt.get(k) for k in CLASSIFICATION}, exact=True)
    _validate_runtime_binding(receipt)
    if receipt.get("terminal_state") not in {"SUCCEEDED", "FAILED", "BLOCKED"}:
        raise ValueError("invalid final terminal state")
    if receipt.get("terminal_state") == "SUCCEEDED" and not receipt.get("self_hash"):
        raise ValueError("final receipt self-hash required")
    if receipt.get("terminal_state") == "SUCCEEDED" and receipt.get(
        "remote_result_tree_sha256"
    ) != receipt.get("local_result_tree_sha256"):
        raise ValueError("two-copy hash chain mismatch")
    if receipt.get("terminal_state") == "SUCCEEDED":
        from .trace import validate_trace

        trace = receipt.get("lifecycle_trace")
        validate_trace(trace)
        if sha256_hex(canonical_bytes(trace)) != receipt.get("lifecycle_trace_sha256"):
            raise ValueError("lifecycle trace hash mismatch")
        if not receipt.get("copy_verification_hash"):
            raise ValueError("copy verification hash required")
        copy_value = receipt.get("copy_verification")
        if not isinstance(copy_value, Mapping):
            raise ValueError("COPY_VERIFICATION evidence required")
        validate_copy_verification(copy_value)
        if receipt.get("copy_verification_hash") != copy_value.get("self_hash"):
            raise ValueError("copy verification hash mismatch")
        for field in (
            "run_id",
            "execution_manifest_sha256",
            "prepared_manifest_sha256",
            "preflight_evidence_sha256",
            "runtime_format",
            "runtime_path",
            "runtime_file_sha256",
            "runtime_source_sha256",
            "runtime_manifest_sha256",
            "runtime_dependency_profile",
            "pinned_runtime_manifest_sha256",
            "pinned_runtime_closure_fingerprint",
        ):
            if receipt.get(field) != copy_value.get(field):
                raise ValueError(f"COPY_VERIFICATION binding mismatch: {field}")
        required = {
            "run_id",
            "execution_manifest_sha256",
            "remote_receipt_hash",
            "copy_verification_hash",
            "remote_result_tree_sha256",
            "local_result_tree_sha256",
            "directory_durable",
            "formal_side_effect_recheck",
        }
        if (
            not required <= set(receipt)
            or receipt.get("directory_durable") is not True
            or receipt.get("formal_side_effect_recheck") is not True
        ):
            raise ValueError("incomplete final receipt")
        if receipt.get("local_result_path"):
            local_path = Path(receipt["local_result_path"]).resolve()
            if not local_path.is_dir() or local_path.is_symlink():
                raise ValueError("local result path invalid")
    if receipt.get("self_hash"):
        body = {k: v for k, v in receipt.items() if k != "self_hash"}
        if sha256_hex(canonical_bytes(body)) != receipt["self_hash"]:
            raise ValueError("receipt self-hash mismatch")
    return receipt


def _reopen_json_receipt(path: str | Path, *, label: str) -> dict[str, Any]:
    """Read a published receipt without following a receipt-file symlink."""
    receipt_path = Path(path)
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise ValueError(f"{label} path invalid")
    try:
        value = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def reopen_validate_remote_receipt(
    path: str | Path, *, expected_hash: str | None = None
) -> dict[str, Any]:
    """Reopen and validate a remote receipt after durable publication."""
    value = _reopen_json_receipt(path, label="remote receipt")
    validate_remote_receipt(value)
    actual = sha256_hex(canonical_bytes(value))
    if expected_hash is not None and actual != expected_hash:
        raise ValueError("remote receipt publication hash mismatch")
    return value


def reopen_validate_final_receipt(
    path: str | Path, *, expected_hash: str | None = None
) -> dict[str, Any]:
    """Reopen and validate FINAL_RUN_RECEIPT after durable publication."""
    value = _reopen_json_receipt(path, label="final receipt")
    validate_final_receipt(value)
    actual = sha256_hex(canonical_bytes(value))
    if expected_hash is not None and actual != expected_hash:
        raise ValueError("final receipt publication hash mismatch")
    return value


def seal_receipt(body: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(body)
    out.update(CLASSIFICATION)
    out["self_hash"] = sha256_hex(canonical_bytes(out))
    return out
