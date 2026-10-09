"""Fail-closed MME execution authorization request and signature validation."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate

from rfb.contracts.canonical_json import canonical_bytes

SCHEMA_VERSION = "1.0.0"
SIGNATURE_ALGORITHM = "ED25519"
INDEPENDENT_ROLE = "INDEPENDENT_EXECUTION_APPROVER"
BLOCKED_NO_SIGNATURE = "BLOCKED_NO_INDEPENDENT_SIGNATURE"
OUTPUT_RELATIVE = ".omx/handoff/g020-authorization"
CONSUMED_RELATIVE = ".omx/handoff/g020-authorization/consumed"
_HASH = "0123456789abcdef"
MAX_AUTHORIZATION_TTL = timedelta(hours=1)
MAX_CLOCK_ROLLBACK = timedelta(seconds=0)
MME_PROTOCOL_ID = "RFB_MME_V1_EXACT27_LOCAL"
LEGACY_PROTOCOL_ID = "RFB_RESEARCH_LEGACY_R006"
ADMIN_TRUST_ROOT_FILENAME = "trust-root.json"
ADMIN_CRL_FILENAME = "revocations.json"
ADMIN_BLOCK_ISSUER_KEY_FILENAME = "block-issuer-private-key.b64"
ADMIN_BROKER_PROTOCOL = "RFB_MME_AUTHORITY_BROKER_V1"
OFFLINE_SIGNING_MANIFEST_FILENAME = "MMEOfflineSigningManifest.json"
OFFLINE_SIGNING_INSTRUCTIONS_FILENAME = "MMEOfflineSigningInstructions.md"
BLOCK_CONTEXT_KEYS = frozenset(
    {
        "schema_version",
        "execution_protocol_id",
        "authorization_id",
        "request_id",
        "execution_plan_sha256",
        "runtime_environment_id",
        "phase0_manifest_self_sha256",
        "gate_checklist_sha256",
        "run_family",
        "block_id",
        "attempt_id",
        "checkpoint_id",
        "deadline_utc",
        "security_epoch",
        "block_context_sha256",
        "block_issuer_key_id",
        "block_context_signature_b64",
    }
)


class MMEAuthorizationBlocked(RuntimeError):
    """Raised before any MME preparation, remote action, block, or formal write."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("MME_AUTH_TIME_NOT_AWARE")
    return parsed.astimezone(UTC)


def _workspace(path: str | Path) -> Path:
    root = Path(path).resolve()
    if not (root / "risk-fusion-bench").is_dir() or not (root / ".omx").is_dir():
        raise ValueError("MME_AUTH_WORKSPACE_INVALID")
    return root


def _contracts(workspace: Path) -> Path:
    return workspace / "risk-fusion-bench/src/rfb/contracts"


def _schema_names() -> tuple[str, ...]:
    return (
        "mme_authorization_request.schema.json",
        "mme_execution_authorization.schema.json",
        "mme_authorization_decision.schema.json",
        "mme_authorization_signature.schema.json",
        "mme_authorization_trust_root.schema.json",
        "mme_authorization_revocation.schema.json",
    )


def _execution_plan(workspace: Path) -> dict[str, Any]:
    prereg_path = workspace / ".omx/plans/MMEPreregistration-v1.json"
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    blocks = [
        *prereg["pairwise_core_coverage"],
        *prereg["boundary_bundles"],
    ]
    if len(blocks) != 27 or len({block["block_id"] for block in blocks}) != 27:
        raise ValueError("MME_AUTH_PREREG_BLOCK_SET_INVALID")
    method_ids = [method["method_id"] for method in prereg["method_panel"]]
    if len(method_ids) != 7 or len(set(method_ids)) != 7:
        raise ValueError("MME_AUTH_PREREG_METHOD_SET_INVALID")
    commitment = prereg["blocking_and_order"]["method_order_seed_commitment"]
    method_orders = [
        {
            "block_id": block["block_id"],
            "method_order": sorted(
                method_ids,
                key=lambda method_id: hashlib.sha256(
                    f"{commitment}|{block['block_id']}|{method_id}".encode()
                ).hexdigest(),
            ),
        }
        for block in blocks
    ]
    from .phase0_frozen_runtime import RECEIPT_DERIVATION_CONTRACT, TEST_PLAN

    body = {
        "preregistration_sha256": _file_sha(prereg_path),
        "core_factors": prereg["core_factors"],
        "blocks": blocks,
        "block_ids": [block["block_id"] for block in blocks],
        "method_panel": method_ids,
        "method_orders": method_orders,
        "test_plan_sha256": _sha(canonical_bytes(TEST_PLAN)),
        "receipt_derivation_contract_sha256": _sha(
            canonical_bytes(RECEIPT_DERIVATION_CONTRACT)
        ),
    }
    return {**body, "execution_plan_sha256": _sha(canonical_bytes(body))}


def _schema_bindings(workspace: Path) -> list[dict[str, str]]:
    contracts = _contracts(workspace)
    return [
        {
            "path": f"risk-fusion-bench/src/rfb/contracts/{name}",
            "sha256": _file_sha(contracts / name),
        }
        for name in _schema_names()
    ]


def _live_bindings(workspace: Path) -> dict[str, Any]:
    from .phase0_frozen_runtime import validate_frozen_runtime
    from .phase0_qualification import validate_phase0_qualification

    g018 = workspace / ".omx/handoff/g018-phase0"
    phase0_path = g018 / "Phase0QualificationManifest.json"
    phase0_receipt = g018 / "Phase0QualificationManifest.raw-hash-receipt.json"
    phase0 = validate_phase0_qualification(workspace, phase0_path, phase0_receipt)
    if phase0["decision"] != {
        "phase0_qualified": True,
        "authorization_eligible": True,
        "execution_authorized": False,
        "authorization_artifact_created": False,
    }:
        raise ValueError("MME_AUTH_PHASE0_NOT_ELIGIBLE")
    g019 = workspace / ".omx/handoff/g019-phase0"
    runtime = validate_frozen_runtime(g019)
    paths = {
        "preregistration": workspace / ".omx/plans/MMEPreregistration-v1.json",
        "scope": workspace / ".omx/plans/论文范围冻结决议-20260820.md",
        "gate_checklist": workspace / "GateChecklist-v6.13.json",
        "phase0_manifest": phase0_path,
        "phase0_raw_receipt": phase0_receipt,
        "runtime_manifest": g019 / "runtime-manifest.json",
        "runtime_qualification": g019 / "qualification.json",
    }
    return {
        "files": {
            name: {
                "path": path.relative_to(workspace).as_posix(),
                "sha256": _file_sha(path),
            }
            for name, path in paths.items()
        },
        "phase0_manifest_self_sha256": phase0["manifest_self_sha256"],
        "runtime_environment_id": runtime["environment_id"],
        "schemas": _schema_bindings(workspace),
        "execution_plan": _execution_plan(workspace),
    }


def build_unsigned_request(
    workspace_root: str | Path,
    *,
    now: datetime | None = None,
    lifetime: timedelta = timedelta(hours=24),
) -> dict[str, Any]:
    workspace = _workspace(workspace_root)
    issued = (now or datetime.now(UTC)).astimezone(UTC)
    if lifetime <= timedelta(0) or lifetime > timedelta(hours=24):
        raise ValueError("MME_AUTH_REQUEST_LIFETIME_INVALID")
    bindings = _live_bindings(workspace)
    request_core = {
        "schema_version": SCHEMA_VERSION,
        "status": "DRAFT_UNSIGNED",
        "execution_protocol_id": MME_PROTOCOL_ID,
        "request_nonce": secrets.token_hex(16),
        "producer_id": "G020_AUTHORIZATION_REQUEST_GENERATOR",
        "producer_key_id": "G020_PRODUCER_ATTESTATION_KEY",
        "requested_action": "EXECUTE_MME_LOCAL_EXACT27_DEVELOPMENT",
        "execution_scope": {
            "mode": "LOCAL_ONLY",
            "independent_blocks": 27,
            "dataset_split": "D_development",
            "remote_actions": False,
            "formal_writes": False,
            "d_test_access": False,
        },
        "classification": {
            "execution_lane": "RESEARCH",
            "classification": "DEVELOPMENT_NONCONFIRMATORY",
            "formal_gate_effect": "NONE",
            "formal_admission_eligible": False,
            "shk001b_eligible": False,
            "contains_formal_claims": False,
        },
        "issued_at_utc": issued.isoformat().replace("+00:00", "Z"),
        "expires_at_utc": (issued + lifetime).isoformat().replace("+00:00", "Z"),
        "bindings": bindings,
    }
    request_id = _sha(canonical_bytes(request_core))
    body = {**request_core, "request_id": request_id}
    return {**body, "request_self_sha256": _sha(canonical_bytes(body))}


def blocked_decision(
    request: dict[str, Any], *, generated_at: datetime | None = None
) -> dict[str, Any]:
    body = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request["request_id"],
        "request_sha256": _sha(canonical_bytes(request)),
        "generated_at_utc": (generated_at or datetime.now(UTC))
        .astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "status": "BLOCKED",
        "blocker_code": BLOCKED_NO_SIGNATURE,
        "execution_authorized": False,
        "signature_present": False,
        "trust_root_present": False,
        "revocation_state_present": False,
    }
    return {**body, "decision_self_sha256": _sha(canonical_bytes(body))}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.partial"
    temporary.write_bytes(canonical_bytes(value))
    os.replace(temporary, path)


def write_unsigned_request_and_blocked_decision(
    workspace_root: str | Path,
    output_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    workspace = _workspace(workspace_root)
    output = Path(output_dir or workspace / OUTPUT_RELATIVE).resolve()
    request = build_unsigned_request(workspace)
    decision = blocked_decision(request)
    request_path = output / "MMEExecutionAuthorizationRequest.unsigned.json"
    decision_path = output / "MMEExecutionAuthorizationDecision.json"
    _atomic_json(request_path, request)
    _atomic_json(decision_path, decision)
    validate_unsigned_blocked_artifacts(workspace, request_path, decision_path)
    return request_path, decision_path


def _validate_closed(document: dict[str, Any], schema_path: Path) -> None:
    validate(document, json.loads(schema_path.read_text(encoding="utf-8")))


def _validate_closed_or_block(document: dict[str, Any], schema_path: Path) -> None:
    try:
        _validate_closed(document, schema_path)
    except (ValidationError, json.JSONDecodeError, OSError) as exc:
        raise MMEAuthorizationBlocked("BLOCKED_AUTHORIZATION_SCHEMA_INVALID") from exc


def _validate_self_hash(document: dict[str, Any], field: str) -> None:
    body = {key: value for key, value in document.items() if key != field}
    if document[field] != _sha(canonical_bytes(body)):
        raise ValueError(f"MME_AUTH_SELF_HASH_MISMATCH:{field}")


def validate_unsigned_blocked_artifacts(
    workspace_root: str | Path, request_path: str | Path, decision_path: str | Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    workspace = _workspace(workspace_root)
    request_raw = Path(request_path).read_bytes()
    decision_raw = Path(decision_path).read_bytes()
    request = json.loads(request_raw)
    decision = json.loads(decision_raw)
    contracts = _contracts(workspace)
    _validate_closed(request, contracts / _schema_names()[0])
    _validate_closed(decision, contracts / _schema_names()[2])
    if request_raw != canonical_bytes(request) or decision_raw != canonical_bytes(
        decision
    ):
        raise ValueError("MME_AUTH_ARTIFACT_NOT_CANONICAL")
    _validate_self_hash(request, "request_self_sha256")
    _validate_self_hash(decision, "decision_self_sha256")
    request_core = {
        key: value
        for key, value in request.items()
        if key not in {"request_id", "request_self_sha256"}
    }
    if request["request_id"] != _sha(canonical_bytes(request_core)):
        raise ValueError("MME_AUTH_REQUEST_ID_MISMATCH")
    if request["bindings"] != _live_bindings(workspace):
        raise ValueError("MME_AUTH_LIVE_BINDING_DRIFT")
    if _parse_time(request["expires_at_utc"]) <= _parse_time(request["issued_at_utc"]):
        raise ValueError("MME_AUTH_REQUEST_TIME_ORDER_INVALID")
    if (
        decision["request_id"] != request["request_id"]
        or decision["request_sha256"] != _sha(request_raw)
        or decision["status"] != "BLOCKED"
        or decision["blocker_code"] != BLOCKED_NO_SIGNATURE
        or decision["execution_authorized"] is not False
        or any(
            decision[key]
            for key in (
                "signature_present",
                "trust_root_present",
                "revocation_state_present",
            )
        )
    ):
        raise ValueError("MME_AUTH_BLOCKED_DECISION_INVALID")
    return request, decision


def _offline_signing_manifest(request: dict[str, Any]) -> dict[str, Any]:
    admin_root = _installation_admin_root()
    state_root = _installation_security_state_root()
    broker_path = _installation_broker_path()
    body = {
        "schema_version": SCHEMA_VERSION,
        "package_status": "UNSIGNED_AWAITING_FOUR_PARTY_MATERIALS",
        "execution_authorized": False,
        "contains_private_keys": False,
        "request": {
            "request_id": request["request_id"],
            "request_sha256": _sha(canonical_bytes(request)),
            "request_self_sha256": request["request_self_sha256"],
            "issued_at_utc": request["issued_at_utc"],
            "expires_at_utc": request["expires_at_utc"],
            "execution_protocol_id": request["execution_protocol_id"],
        },
        "execution_scope": copy.deepcopy(request["execution_scope"]),
        "classification": copy.deepcopy(request["classification"]),
        "required_roles": [
            {
                "signer_role": "PRODUCER_ATTESTER",
                "signer_id": request["producer_id"],
                "key_id": request["producer_key_id"],
                "independent": False,
            },
            {
                "signer_role": INDEPENDENT_ROLE,
                "signer_id": "ASSIGN_OFFLINE",
                "key_id": "ASSIGN_OFFLINE",
                "independent": True,
            },
            {
                "signer_role": "TRUST_ADMIN",
                "signer_id": "ASSIGN_OFFLINE",
                "key_id": "ASSIGN_OFFLINE",
                "independent": True,
            },
            {
                "signer_role": "BLOCK_ISSUER",
                "signer_id": "ASSIGN_OFFLINE",
                "key_id": "ASSIGN_OFFLINE",
                "independent": True,
            },
        ],
        "independence_contract": {
            "distinct_signer_ids": 4,
            "distinct_key_ids": 4,
            "distinct_public_keys": 4,
            "private_keys_must_remain_offline_or_admin_installed": True,
        },
        "authorization_contract": {
            "schema": "risk-fusion-bench/src/rfb/contracts/mme_execution_authorization.schema.json",
            "signature_domain": "RFB_MME_SIGNED_AUTHORIZATION_V1",
            "maximum_authorization_ttl_seconds": int(
                MAX_AUTHORIZATION_TTL.total_seconds()
            ),
            "required_signatures": [
                "PRODUCER_ATTESTER",
                INDEPENDENT_ROLE,
            ],
        },
        "revocation_contract": {
            "schema": "risk-fusion-bench/src/rfb/contracts/mme_authorization_revocation.schema.json",
            "signature_domain": "RFB_MME_CRL_V1",
            "signer_role": "TRUST_ADMIN",
            "fresh_at_every_authority_boundary": True,
        },
        "installation_layout": {
            "authority_broker_path": str(broker_path),
            "authority_broker_protocol": ADMIN_BROKER_PROTOCOL,
            "trust_root_path": str(admin_root / ADMIN_TRUST_ROOT_FILENAME),
            "revocation_path": str(admin_root / ADMIN_CRL_FILENAME),
            "block_issuer_private_key_path": str(
                admin_root / ADMIN_BLOCK_ISSUER_KEY_FILENAME
            ),
            "security_state_path": str(state_root),
            "workspace_or_environment_override_allowed": False,
            "regular_non_reparse_files_required": True,
            "admin_read_only_permissions_required": True,
            "application_process_loads_private_material": False,
        },
        "hard_prohibitions": {
            "d_test_access": True,
            "remote_actions": True,
            "formal_writes": True,
            "data_deletion": True,
            "experiment_start_before_complete_validation": True,
        },
    }
    return {**body, "manifest_self_sha256": _sha(canonical_bytes(body))}


def validate_offline_signing_manifest(
    manifest_path: str | Path, request: dict[str, Any]
) -> dict[str, Any]:
    raw = Path(manifest_path).read_bytes()
    manifest = json.loads(raw)
    if raw != canonical_bytes(manifest):
        raise ValueError("MME_OFFLINE_MANIFEST_NOT_CANONICAL")
    _validate_self_hash(manifest, "manifest_self_sha256")
    expected = _offline_signing_manifest(request)
    if manifest != expected:
        raise ValueError("MME_OFFLINE_MANIFEST_BINDING_MISMATCH")
    if (
        manifest["execution_authorized"] is not False
        or manifest["contains_private_keys"] is not False
        or manifest["execution_scope"]
        != {
            "mode": "LOCAL_ONLY",
            "independent_blocks": 27,
            "dataset_split": "D_development",
            "remote_actions": False,
            "formal_writes": False,
            "d_test_access": False,
        }
    ):
        raise ValueError("MME_OFFLINE_MANIFEST_SCOPE_INVALID")
    return manifest


def _invalidation_receipt(
    request: dict[str, Any], decision: dict[str, Any], invalidated: datetime
) -> dict[str, Any]:
    body = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request["request_id"],
        "request_sha256": _sha(canonical_bytes(request)),
        "decision_sha256": _sha(canonical_bytes(decision)),
        "issued_at_utc": request["issued_at_utc"],
        "expired_at_utc": request["expires_at_utc"],
        "invalidated_at_utc": invalidated.isoformat().replace("+00:00", "Z"),
        "reason": "USER_AUTHORIZED_EXPIRED_REQUEST_REPLACEMENT",
        "execution_authorized": False,
    }
    return {**body, "receipt_self_sha256": _sha(canonical_bytes(body))}


def _archive_expired_request(output: Path, now: datetime) -> Path | None:
    request_path = output / "MMEExecutionAuthorizationRequest.unsigned.json"
    decision_path = output / "MMEExecutionAuthorizationDecision.json"
    if not request_path.exists() and not decision_path.exists():
        return None
    if not request_path.is_file() or not decision_path.is_file():
        raise ValueError("MME_AUTH_CURRENT_PACKAGE_INCOMPLETE")
    request_raw = request_path.read_bytes()
    decision_raw = decision_path.read_bytes()
    request = json.loads(request_raw)
    decision = json.loads(decision_raw)
    if (
        request_raw != canonical_bytes(request)
        or decision_raw != canonical_bytes(decision)
        or now < _parse_time(request["expires_at_utc"])
    ):
        raise ValueError("MME_AUTH_CURRENT_REQUEST_NOT_EXPIRED")
    archive = output / "expired" / request["request_id"]
    if archive.exists():
        raise ValueError("MME_AUTH_EXPIRY_ARCHIVE_ALREADY_EXISTS")
    _atomic_json(archive / "MMEExecutionAuthorizationRequest.unsigned.json", request)
    _atomic_json(archive / "MMEExecutionAuthorizationDecision.json", decision)
    _atomic_json(
        archive / "InvalidationReceipt.json",
        _invalidation_receipt(request, decision, now),
    )
    return archive


def _offline_signing_instructions(manifest: dict[str, Any]) -> str:
    layout = manifest["installation_layout"]
    return "\n".join(
        (
            "# MME 离线签署说明",
            "",
            f"请求 ID：`{manifest['request']['request_id']}`",
            f"有效期截止：`{manifest['request']['expires_at_utc']}`",
            "",
            "该材料包不包含私钥、签名、信任根或执行授权。四个角色必须使用不同主体、不同密钥 ID 和不同 Ed25519 公钥。",
            "",
            "管理员安装位置：",
            "",
            f"- 外部授权 broker：`{layout['authority_broker_path']}`",
            f"- 信任根：`{layout['trust_root_path']}`",
            f"- 新鲜 CRL：`{layout['revocation_path']}`",
            f"- 区组签发私钥：`{layout['block_issuer_private_key_path']}`",
            f"- 单调安全状态：`{layout['security_state_path']}`",
            "",
            "先按 schema 构造信任根和 CRL，再构造不超过 1 小时的授权核心。生产者与独立审批人分别对 `RFB_MME_SIGNED_AUTHORIZATION_V1` 域载荷签名。CRL 由 TRUST_ADMIN 对 `RFB_MME_CRL_V1` 域载荷签名。",
            "",
            "私钥不得写入工作区、聊天、日志或本材料包。信任验证、CRL 单调状态和区组签发均由管理员安装的独立 broker 完成，应用进程不得读取私钥。管理员文件必须为普通非重解析文件并受系统 ACL 保护；缺少 broker 或任一材料时执行入口保持阻塞。",
            "",
            "范围始终限定为本地 D_development、固定 27 区组和 DEVELOPMENT_NONCONFIRMATORY。D_test、远端动作、正式写入及数据删除均被禁止。",
            "",
        )
    )


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.partial"
    temporary.write_text(value, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def write_offline_signing_package(
    workspace_root: str | Path,
    output_dir: str | Path | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Path]:
    workspace = _workspace(workspace_root)
    output = Path(output_dir or workspace / OUTPUT_RELATIVE).resolve()
    instant = (now or datetime.now(UTC)).astimezone(UTC)
    request = build_unsigned_request(workspace, now=instant)
    decision = blocked_decision(request, generated_at=instant)
    manifest = _offline_signing_manifest(request)
    _archive_expired_request(output, instant)
    paths = {
        "request": output / "MMEExecutionAuthorizationRequest.unsigned.json",
        "decision": output / "MMEExecutionAuthorizationDecision.json",
        "manifest": output / OFFLINE_SIGNING_MANIFEST_FILENAME,
        "instructions": output / OFFLINE_SIGNING_INSTRUCTIONS_FILENAME,
    }
    _atomic_json(paths["request"], request)
    _atomic_json(paths["decision"], decision)
    _atomic_json(paths["manifest"], manifest)
    _atomic_text(paths["instructions"], _offline_signing_instructions(manifest))
    validate_unsigned_blocked_artifacts(workspace, paths["request"], paths["decision"])
    validate_offline_signing_manifest(paths["manifest"], request)
    return paths


_WEAK_ED25519_KEYS = {
    bytes(32),
    b"\x01" + bytes(31),
}


def _verify_ed25519(public_key_b64: str, payload: bytes, signature_b64: str) -> None:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise MMEAuthorizationBlocked("BLOCKED_CRYPTO_BACKEND_UNAVAILABLE") from exc
    try:
        public_key = base64.b64decode(public_key_b64, validate=True)
        signature = base64.b64decode(signature_b64, validate=True)
        if (
            len(public_key) != 32
            or len(signature) != 64
            or public_key in _WEAK_ED25519_KEYS
        ):
            raise ValueError
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise MMEAuthorizationBlocked(
            "BLOCKED_SIGNATURE_CRYPTOGRAPHICALLY_INVALID"
        ) from exc


def _sign_ed25519(private_key_b64: str, payload: bytes) -> str:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as exc:
        raise MMEAuthorizationBlocked("BLOCKED_CRYPTO_BACKEND_UNAVAILABLE") from exc
    try:
        private_key = base64.b64decode(private_key_b64, validate=True)
        if len(private_key) != 32 or private_key in _WEAK_ED25519_KEYS:
            raise ValueError
        return base64.b64encode(
            Ed25519PrivateKey.from_private_bytes(private_key).sign(payload)
        ).decode()
    except (ValueError, TypeError) as exc:
        raise MMEAuthorizationBlocked(
            "BLOCKED_BLOCK_ISSUER_PRIVATE_KEY_INVALID"
        ) from exc


def _installation_admin_root() -> Path:
    if os.name == "nt":
        return Path(r"C:\ProgramData\RFB\MMEAuthorization\v1")
    if sys.platform == "darwin":
        return Path("/Library/Application Support/RFB/MMEAuthorization/v1")
    return Path("/etc/rfb/mme-authorization/v1")


def _installation_security_state_root() -> Path:
    if os.name == "nt":
        return Path(r"C:\ProgramData\RFB\MMEAuthorization\state-v1")
    if sys.platform == "darwin":
        return Path("/Library/Application Support/RFB/MMEAuthorization/state-v1")
    return Path("/var/lib/rfb/mme-authorization/v1")


def _installation_broker_path() -> Path:
    if os.name == "nt":
        return Path(
            r"C:\Program Files\RFB\MMEAuthorization\rfb-mme-authorization-broker.exe"
        )
    if sys.platform == "darwin":
        return Path("/Library/PrivilegedHelperTools/rfb-mme-authorization-broker")
    return Path("/usr/libexec/rfb-mme-authorization-broker")


def _is_reparse_or_symlink(path: Path) -> bool:
    information = path.lstat()
    attributes = getattr(information, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(attributes & reparse)


def _assert_no_reparse_ancestors(path: Path) -> None:
    current = path
    while True:
        if current.exists() and _is_reparse_or_symlink(current):
            raise MMEAuthorizationBlocked("BLOCKED_ADMIN_TRUST_PATH_INVALID")
        if current.parent == current:
            return
        current = current.parent


def _system_powershell_path() -> Path:
    if os.name != "nt":
        raise OSError("Windows system directory is unavailable")
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemWindowsDirectoryW(buffer, len(buffer))
    if length <= 0 or length >= len(buffer):
        raise OSError("Windows system directory lookup failed")
    return Path(buffer.value) / "System32/WindowsPowerShell/v1.0/powershell.exe"


def _windows_acl_admin_controlled(path: Path) -> bool:
    script = (
        "$a=Get-Acl -LiteralPath $args[0];"
        "$o=$a.Owner;"
        "$r=@($a.Access|ForEach-Object{"
        "$s=$_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value;"
        "[pscustomobject]@{sid=$s;type=$_.AccessControlType.ToString();"
        "rights=[int64]$_.FileSystemRights}});"
        "[pscustomobject]@{owner=$o;rules=$r}|ConvertTo-Json -Compress -Depth 4"
    )
    try:
        powershell = _system_powershell_path()
        completed = subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if completed.returncode != 0:
            return False
        descriptor = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError):
        return False
    allowed = {
        "S-1-5-18",
        "S-1-5-32-544",
        "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",
    }
    owner = str(descriptor.get("owner", ""))
    if owner not in allowed and "\\Administrators" not in owner:
        return False
    write_mask = 2 | 4 | 16 | 64 | 256 | 65536 | 262144 | 524288
    rules = descriptor.get("rules", [])
    if isinstance(rules, dict):
        rules = [rules]
    return all(
        rule.get("type") != "Allow"
        or not int(rule.get("rights", 0)) & write_mask
        or rule.get("sid") in allowed
        for rule in rules
        if isinstance(rule, dict)
    )


def _assert_admin_layout_secure(root: Path, paths: tuple[Path, ...]) -> None:
    _assert_no_reparse_ancestors(root)
    if not root.is_absolute() or not root.is_dir() or _is_reparse_or_symlink(root):
        raise MMEAuthorizationBlocked("BLOCKED_ADMIN_TRUST_ANCHOR_UNAVAILABLE")
    expected = _installation_admin_root()
    if root != expected or root.resolve(strict=True) != expected:
        raise MMEAuthorizationBlocked("BLOCKED_ADMIN_TRUST_PATH_INVALID")
    if os.name == "nt" and not _windows_acl_admin_controlled(root):
        raise MMEAuthorizationBlocked("BLOCKED_ADMIN_TRUST_PERMISSIONS_INVALID")
    for path in paths:
        if (
            path.parent != root
            or not path.is_file()
            or _is_reparse_or_symlink(path)
            or path.resolve(strict=True).parent != root
            or path.stat().st_nlink != 1
        ):
            raise MMEAuthorizationBlocked("BLOCKED_ADMIN_TRUST_FILE_INVALID")
        information = path.stat()
        if os.name == "posix":
            if information.st_uid != 0 or information.st_mode & 0o022:
                raise MMEAuthorizationBlocked("BLOCKED_ADMIN_TRUST_PERMISSIONS_INVALID")
            if (
                path.name == ADMIN_BLOCK_ISSUER_KEY_FILENAME
                and information.st_mode & 0o077
            ):
                raise MMEAuthorizationBlocked(
                    "BLOCKED_ADMIN_PRIVATE_KEY_PERMISSIONS_INVALID"
                )
        elif os.name == "nt":
            if not _windows_acl_admin_controlled(path):
                raise MMEAuthorizationBlocked("BLOCKED_ADMIN_TRUST_PERMISSIONS_INVALID")


def _assert_security_state_secure(state_root: Path) -> None:
    _assert_no_reparse_ancestors(state_root)
    if (
        state_root != _installation_security_state_root()
        or not state_root.is_dir()
        or _is_reparse_or_symlink(state_root)
        or not os.access(state_root, os.W_OK)
    ):
        raise MMEAuthorizationBlocked("BLOCKED_SECURITY_STATE_PATH_INVALID")
    information = state_root.stat()
    if os.name == "posix" and information.st_mode & 0o077:
        raise MMEAuthorizationBlocked("BLOCKED_SECURITY_STATE_PERMISSIONS_INVALID")
    if os.name == "nt" and not _windows_acl_admin_controlled(state_root):
        raise MMEAuthorizationBlocked("BLOCKED_SECURITY_STATE_PERMISSIONS_INVALID")


def _canonical_json_file(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise MMEAuthorizationBlocked("BLOCKED_ADMIN_TRUST_FILE_INVALID") from exc
    if not isinstance(value, dict) or raw != canonical_bytes(value):
        raise MMEAuthorizationBlocked("BLOCKED_ADMIN_TRUST_FILE_NOT_CANONICAL")
    return value


def _block_issuer_private_key(path: Path, trust: dict[str, Any]) -> str:
    try:
        encoded = path.read_text(encoding="ascii")
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) != 32 or raw in _WEAK_ED25519_KEYS:
            raise ValueError
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        public = base64.b64encode(
            Ed25519PrivateKey.from_private_bytes(raw).public_key().public_bytes_raw()
        ).decode()
        issuers = [
            key
            for key in trust.get("keys", [])
            if key.get("signer_role") == "BLOCK_ISSUER"
        ]
        if len(issuers) != 1 or issuers[0].get("public_key_b64") != public:
            raise ValueError
        return encoded
    except (ImportError, OSError, UnicodeError, ValueError, TypeError) as exc:
        raise MMEAuthorizationBlocked(
            "BLOCKED_BLOCK_ISSUER_PRIVATE_KEY_INVALID"
        ) from exc


def _load_production_admin_configuration() -> dict[str, Any]:
    root = _installation_admin_root()
    state_root = _installation_security_state_root()
    trust_path = root / ADMIN_TRUST_ROOT_FILENAME
    crl_path = root / ADMIN_CRL_FILENAME
    issuer_path = root / ADMIN_BLOCK_ISSUER_KEY_FILENAME
    try:
        _assert_admin_layout_secure(root, (trust_path, crl_path, issuer_path))
        _assert_security_state_secure(state_root)
    except (FileNotFoundError, OSError) as exc:
        raise MMEAuthorizationBlocked("BLOCKED_ADMIN_TRUST_ANCHOR_UNAVAILABLE") from exc
    trust = _canonical_json_file(trust_path)
    crl = _canonical_json_file(crl_path)
    return {
        "trust_root": trust,
        "crl": crl,
        "state_dir": state_root,
        "block_issuer_private_key_b64": _block_issuer_private_key(issuer_path, trust),
    }


def _key(trust: dict[str, Any], key_id: str, role: str) -> dict[str, Any]:
    matches = [
        key
        for key in trust["keys"]
        if key["key_id"] == key_id and key["signer_role"] == role
    ]
    if len(matches) != 1:
        raise MMEAuthorizationBlocked("BLOCKED_SIGNING_KEY_NOT_TRUSTED")
    return matches[0]


def _verify_role_signature(
    signature: dict[str, Any],
    role: str,
    trust: dict[str, Any],
    payload: bytes,
    issued: datetime,
) -> dict[str, Any]:
    if (
        signature["signer_role"] != role
        or signature["algorithm"] != SIGNATURE_ALGORITHM
    ):
        raise MMEAuthorizationBlocked("BLOCKED_SIGNATURE_ROLE_INVALID")
    key = _key(trust, signature["key_id"], role)
    signed_at = _parse_time(signature["signed_at_utc"])
    if (
        key["signer_id"] != signature["signer_id"]
        or signed_at != issued
        or signed_at < _parse_time(key["not_before_utc"])
        or signed_at >= _parse_time(key["not_after_utc"])
    ):
        raise MMEAuthorizationBlocked("BLOCKED_SIGNATURE_IDENTITY_OR_TIME_INVALID")
    _verify_ed25519(key["public_key_b64"], payload, signature["signature_b64"])
    return key


def _verify_crl(
    workspace: Path,
    crl: dict[str, Any],
    trust: dict[str, Any],
    trust_hash: str,
    now: datetime,
) -> str:
    _validate_closed_or_block(
        crl, _contracts(workspace) / "mme_authorization_revocation.schema.json"
    )
    if (
        crl["trust_root_sha256"] != trust_hash
        or crl["trust_epoch"] != trust["trust_epoch"]
    ):
        raise MMEAuthorizationBlocked("BLOCKED_CRL_TRUST_BINDING_INVALID")
    issued = _parse_time(crl["published_at_utc"])
    if issued > now or now >= _parse_time(crl["next_update_utc"]):
        raise MMEAuthorizationBlocked("BLOCKED_CRL_STALE")
    body = {key: value for key, value in crl.items() if key not in {"signature_b64"}}
    admin = _key(trust, crl["key_id"], "TRUST_ADMIN")
    if admin["signer_id"] != crl["signer_id"]:
        raise MMEAuthorizationBlocked("BLOCKED_CRL_SIGNER_INVALID")
    _verify_ed25519(
        admin["public_key_b64"],
        canonical_bytes({"domain": "RFB_MME_CRL_V1", **body}),
        crl["signature_b64"],
    )
    return _sha(canonical_bytes(crl))


def _validate_live_request(
    workspace: Path, request_path: Path, now: datetime
) -> dict[str, Any]:
    raw = request_path.read_bytes()
    request = json.loads(raw)
    _validate_closed_or_block(request, _contracts(workspace) / _schema_names()[0])
    if raw != canonical_bytes(request):
        raise MMEAuthorizationBlocked("BLOCKED_REQUEST_NOT_CANONICAL")
    _validate_self_hash(request, "request_self_sha256")
    core = {
        key: value
        for key, value in request.items()
        if key not in {"request_id", "request_self_sha256"}
    }
    if request["request_id"] != _sha(canonical_bytes(core)):
        raise MMEAuthorizationBlocked("BLOCKED_REQUEST_ID_MISMATCH")
    if request["bindings"] != _live_bindings(workspace):
        raise MMEAuthorizationBlocked("BLOCKED_AUTHORIZATION_BINDING_DRIFT")
    if now < _parse_time(request["issued_at_utc"]) or now >= _parse_time(
        request["expires_at_utc"]
    ):
        raise MMEAuthorizationBlocked("BLOCKED_AUTHORIZATION_EXPIRED")
    return request


def _update_security_state(
    state_dir: Path, crl: dict[str, Any], crl_hash: str, now: datetime
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "security-state.lock"
    descriptor = None
    for _ in range(500):
        try:
            descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            break
        except FileExistsError:
            time.sleep(0.01)
    if descriptor is None:
        raise MMEAuthorizationBlocked("BLOCKED_SECURITY_STATE_LOCK_TIMEOUT")
    os.close(descriptor)
    try:
        _update_security_state_locked(state_dir, crl, crl_hash, now)
    finally:
        lock_path.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_replace_with_retry(source: Path, destination: Path) -> None:
    """Tolerate bounded Windows scanner/share interference without weakening CAS."""
    for attempt in range(100):
        try:
            os.replace(source, destination)
            return
        except PermissionError as exc:
            if attempt == 99:
                source.unlink(missing_ok=True)
                raise MMEAuthorizationBlocked(
                    "BLOCKED_SECURITY_STATE_ATOMIC_REPLACE"
                ) from exc
            time.sleep(0.01)


def _update_security_state_locked(
    state_dir: Path, crl: dict[str, Any], crl_hash: str, now: datetime
) -> None:
    state_path = state_dir / "security-state.json"
    previous = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.is_file()
        else None
    )
    if previous is None:
        if (
            crl["revocation_epoch"] != 0
            or crl["previous_revocation_sha256"] != "0" * 64
        ):
            raise MMEAuthorizationBlocked("BLOCKED_CRL_GENESIS_INVALID")
    else:
        last_seen = _parse_time(previous["last_seen_utc"])
        if now < last_seen - MAX_CLOCK_ROLLBACK:
            raise MMEAuthorizationBlocked("BLOCKED_AUTHORIZATION_CLOCK_ROLLBACK")
        if crl["revocation_epoch"] < previous["highest_crl_epoch"]:
            raise MMEAuthorizationBlocked("BLOCKED_CRL_EPOCH_ROLLBACK")
        if crl["revocation_epoch"] == previous["highest_crl_epoch"]:
            if crl_hash != previous["last_crl_sha256"]:
                raise MMEAuthorizationBlocked("BLOCKED_CRL_EQUIVOCATION")
        elif (
            crl["revocation_epoch"] != previous["highest_crl_epoch"] + 1
            or crl["previous_revocation_sha256"] != previous["last_crl_sha256"]
        ):
            raise MMEAuthorizationBlocked("BLOCKED_CRL_CHAIN_INVALID")
    body = {
        "highest_crl_epoch": crl["revocation_epoch"],
        "last_crl_sha256": crl_hash,
        "last_seen_utc": now.isoformat().replace("+00:00", "Z"),
    }
    temporary = state_dir / f".security-state.{secrets.token_hex(8)}.partial"
    with temporary.open("wb") as stream:
        stream.write(canonical_bytes(body))
        stream.flush()
        os.fsync(stream.fileno())
    _atomic_replace_with_retry(temporary, state_path)
    _fsync_directory(state_dir)


def _claim_validated_block(
    validated: dict[str, Any],
    state_dir: str | Path,
    issuer_private_key_b64: str,
    *,
    block_id: str,
    attempt_id: str,
    checkpoint_id: str,
) -> dict[str, Any]:
    plan = validated["execution_plan"]
    if block_id not in plan["block_ids"] or not attempt_id or not checkpoint_id:
        raise MMEAuthorizationBlocked("BLOCKED_MME_BLOCK_CLAIM_INVALID")
    root = Path(state_dir).resolve() / "claims" / validated["authorization_id"]
    block_root = root / validated["run_family"] / block_id
    block_root.mkdir(parents=True, exist_ok=True)
    claim_path = block_root / "claim.json"
    if claim_path.is_file():
        value = json.loads(claim_path.read_text(encoding="utf-8"))
        if set(value) != BLOCK_CONTEXT_KEYS:
            raise MMEAuthorizationBlocked("BLOCKED_MME_BLOCK_CONTEXT_NOT_CLOSED")
        recovered_body = {
            key: item
            for key, item in value.items()
            if key not in {"block_context_sha256", "block_context_signature_b64"}
        }
        if value.get("block_context_sha256") != _sha(canonical_bytes(recovered_body)):
            raise MMEAuthorizationBlocked("BLOCKED_MME_BLOCK_CONTEXT_TAMPERED")
        signed_body = {
            key: item
            for key, item in value.items()
            if key != "block_context_signature_b64"
        }
        _verify_ed25519(
            validated["block_issuer_public_key_b64"],
            canonical_bytes({"domain": "RFB_MME_BLOCK_CONTEXT_V1", **signed_body}),
            value["block_context_signature_b64"],
        )
        if value["attempt_id"] != attempt_id:
            raise MMEAuthorizationBlocked("BLOCKED_MME_BLOCK_RESUBMISSION")
        if value["checkpoint_id"] != checkpoint_id:
            raise MMEAuthorizationBlocked("BLOCKED_MME_ATTEMPT_REPLAY")
        return {**value, "recovered": True}
    body = {
        "schema_version": SCHEMA_VERSION,
        "execution_protocol_id": MME_PROTOCOL_ID,
        "authorization_id": validated["authorization_id"],
        "request_id": validated["request_id"],
        "execution_plan_sha256": plan["execution_plan_sha256"],
        "runtime_environment_id": validated["runtime_environment_id"],
        "phase0_manifest_self_sha256": validated["phase0_manifest_self_sha256"],
        "gate_checklist_sha256": validated["gate_checklist_sha256"],
        "run_family": validated["run_family"],
        "block_id": block_id,
        "attempt_id": attempt_id,
        "checkpoint_id": checkpoint_id,
        "deadline_utc": validated["expires_at_utc"],
        "security_epoch": validated["security_epoch"],
        "block_issuer_key_id": validated["block_issuer_key_id"],
    }
    body["block_context_sha256"] = _sha(canonical_bytes(body))
    body["block_context_signature_b64"] = _sign_ed25519(
        issuer_private_key_b64,
        canonical_bytes({"domain": "RFB_MME_BLOCK_CONTEXT_V1", **body}),
    )
    _verify_ed25519(
        validated["block_issuer_public_key_b64"],
        canonical_bytes(
            {
                "domain": "RFB_MME_BLOCK_CONTEXT_V1",
                **{k: v for k, v in body.items() if k != "block_context_signature_b64"},
            }
        ),
        body["block_context_signature_b64"],
    )
    try:
        descriptor = os.open(claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as exc:
        raise MMEAuthorizationBlocked("BLOCKED_MME_BLOCK_CAS_LOST") from exc
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_bytes(body))
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(block_root)
    return {**body, "recovered": False}


def _validate_authorization_documents(
    workspace: Path,
    request: dict[str, Any],
    authorization: dict[str, Any],
    trust: dict[str, Any],
    revocations: dict[str, Any],
    instant: datetime,
) -> dict[str, Any]:
    trust = copy.deepcopy(trust)
    revocations = copy.deepcopy(revocations)
    trust_raw = canonical_bytes(trust)
    trust_hash = _sha(trust_raw)
    _validate_closed_or_block(
        trust, _contracts(workspace) / "mme_authorization_trust_root.schema.json"
    )
    _validate_self_hash(trust, "trust_root_self_sha256")
    roles = {key["signer_role"] for key in trust["keys"]}
    public_keys = [key["public_key_b64"] for key in trust["keys"]]
    key_ids = [key["key_id"] for key in trust["keys"]]
    signer_ids = [key["signer_id"] for key in trust["keys"]]
    if (
        len(trust["keys"]) != 4
        or roles
        != {"PRODUCER_ATTESTER", INDEPENDENT_ROLE, "TRUST_ADMIN", "BLOCK_ISSUER"}
        or len(public_keys) != len(set(public_keys))
        or len(key_ids) != len(set(key_ids))
        or len(signer_ids) != len(set(signer_ids))
    ):
        raise MMEAuthorizationBlocked("BLOCKED_TRUST_ROLE_OR_KEY_ALIAS_INVALID")
    authorization_raw = canonical_bytes(authorization)
    _validate_closed_or_block(
        authorization, _contracts(workspace) / "mme_execution_authorization.schema.json"
    )
    if authorization_raw != canonical_bytes(authorization):
        raise MMEAuthorizationBlocked("BLOCKED_AUTHORIZATION_NOT_CANONICAL")
    issued = _parse_time(authorization["issued_at_utc"])
    expires = _parse_time(authorization["expires_at_utc"])
    if (
        request.get("execution_protocol_id") != MME_PROTOCOL_ID
        or authorization["execution_protocol_id"] != MME_PROTOCOL_ID
        or authorization["request_id"] != request["request_id"]
        or authorization["request_sha256"] != _sha(canonical_bytes(request))
        or authorization["execution_plan_sha256"]
        != request["bindings"]["execution_plan"]["execution_plan_sha256"]
        or authorization["trust_root_sha256"] != trust_hash
        or authorization["trust_epoch"] != trust["trust_epoch"]
        or issued < _parse_time(request["issued_at_utc"])
        or expires > _parse_time(request["expires_at_utc"])
        or expires <= issued
        or expires - issued > MAX_AUTHORIZATION_TTL
        or instant < issued
        or instant >= expires
    ):
        raise MMEAuthorizationBlocked("BLOCKED_AUTHORIZATION_BINDING_OR_TIME_INVALID")
    auth_core = {
        key: value
        for key, value in authorization.items()
        if key
        not in {"authorization_id", "producer_attestation", "independent_signature"}
    }
    if authorization["authorization_id"] != _sha(canonical_bytes(auth_core)):
        raise MMEAuthorizationBlocked("BLOCKED_AUTHORIZATION_ID_INVALID")
    payload = canonical_bytes(
        {
            "domain": "RFB_MME_SIGNED_AUTHORIZATION_V1",
            "authorization_id": authorization["authorization_id"],
            "authorization_core_sha256": _sha(canonical_bytes(auth_core)),
        }
    )
    producer_key = _verify_role_signature(
        authorization["producer_attestation"],
        "PRODUCER_ATTESTER",
        trust,
        payload,
        issued,
    )
    independent_key = _verify_role_signature(
        authorization["independent_signature"],
        INDEPENDENT_ROLE,
        trust,
        payload,
        issued,
    )
    admin_key = _key(trust, revocations["key_id"], "TRUST_ADMIN")
    issuer_key = next(
        key for key in trust["keys"] if key["signer_role"] == "BLOCK_ISSUER"
    )
    if (
        producer_key["key_id"] == independent_key["key_id"]
        or producer_key["signer_id"] == independent_key["signer_id"]
        or independent_key["independent"] is not True
        or producer_key["signer_id"]
        != authorization["producer_attestation"]["signer_id"]
        or producer_key["signer_id"] != request["producer_id"]
        or producer_key["key_id"] != request["producer_key_id"]
        or any(
            not (
                _parse_time(key["not_before_utc"])
                <= instant
                < _parse_time(key["not_after_utc"])
            )
            for key in (producer_key, independent_key, admin_key, issuer_key)
        )
    ):
        raise MMEAuthorizationBlocked("BLOCKED_PRODUCER_SIGNER_NOT_INDEPENDENT")
    crl_hash = _verify_crl(workspace, revocations, trust, trust_hash, instant)
    if (
        revocations["trust_root_sha256"] != trust_hash
        or revocations["trust_epoch"] != trust["trust_epoch"]
        or producer_key["key_id"] in revocations["revoked_key_ids"]
        or independent_key["key_id"] in revocations["revoked_key_ids"]
        or issuer_key["key_id"] in revocations["revoked_key_ids"]
        or request["request_id"] in revocations["revoked_request_ids"]
        or _sha(authorization_raw) in revocations["revoked_signature_sha256"]
    ):
        raise MMEAuthorizationBlocked("BLOCKED_AUTHORIZATION_REVOKED")
    return {
        "authorization_id": authorization["authorization_id"],
        "request_id": request["request_id"],
        "run_family": authorization["run_family"],
        "expires_at_utc": authorization["expires_at_utc"],
        "security_epoch": revocations["revocation_epoch"],
        "crl_hash": crl_hash,
        "execution_plan": copy.deepcopy(request["bindings"]["execution_plan"]),
        "runtime_environment_id": request["bindings"]["runtime_environment_id"],
        "phase0_manifest_self_sha256": request["bindings"][
            "phase0_manifest_self_sha256"
        ],
        "gate_checklist_sha256": request["bindings"]["files"]["gate_checklist"][
            "sha256"
        ],
        "block_issuer_key_id": issuer_key["key_id"],
        "block_issuer_public_key_b64": issuer_key["public_key_b64"],
    }


def _assert_external_broker_secure(path: Path) -> None:
    expected = _installation_broker_path()
    try:
        _assert_no_reparse_ancestors(path)
        information = path.stat()
    except (FileNotFoundError, OSError) as exc:
        raise MMEAuthorizationBlocked(
            "BLOCKED_EXTERNAL_AUTHORITY_BROKER_UNAVAILABLE"
        ) from exc
    if (
        path != expected
        or not path.is_file()
        or _is_reparse_or_symlink(path)
        or information.st_nlink != 1
    ):
        raise MMEAuthorizationBlocked("BLOCKED_EXTERNAL_AUTHORITY_BROKER_INVALID")
    if os.name == "posix":
        if information.st_uid != 0 or information.st_mode & 0o022:
            raise MMEAuthorizationBlocked(
                "BLOCKED_EXTERNAL_AUTHORITY_BROKER_PERMISSIONS"
            )
    elif os.name == "nt" and not _windows_acl_admin_controlled(path):
        raise MMEAuthorizationBlocked("BLOCKED_EXTERNAL_AUTHORITY_BROKER_PERMISSIONS")


def _call_external_authority_broker(
    workspace_root: str | Path,
    request_path: str | Path,
    authorization_path: str | Path | None,
    *,
    operation: str,
    now: datetime | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workspace = _workspace(workspace_root)
    instant = (now or datetime.now(UTC)).astimezone(UTC)
    _validate_live_request(workspace, Path(request_path), instant)
    if authorization_path is None or not Path(authorization_path).is_file():
        raise MMEAuthorizationBlocked(BLOCKED_NO_SIGNATURE)
    broker = _installation_broker_path()
    _assert_external_broker_secure(broker)
    message = {
        "protocol": ADMIN_BROKER_PROTOCOL,
        "operation": operation,
        "workspace": str(workspace),
        "request_path": str(Path(request_path).resolve()),
        "authorization_path": str(Path(authorization_path).resolve()),
        "evaluated_at_utc": instant.isoformat().replace("+00:00", "Z"),
        "payload": payload or {},
    }
    try:
        completed = subprocess.run(
            [str(broker)],
            input=canonical_bytes(message),
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MMEAuthorizationBlocked(
            "BLOCKED_EXTERNAL_AUTHORITY_BROKER_FAILED"
        ) from exc
    if completed.returncode != 0:
        raise MMEAuthorizationBlocked("BLOCKED_EXTERNAL_AUTHORITY_BROKER_REJECTED")
    try:
        response = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise MMEAuthorizationBlocked(
            "BLOCKED_EXTERNAL_AUTHORITY_BROKER_RESPONSE"
        ) from exc
    if (
        not isinstance(response, dict)
        or completed.stdout != canonical_bytes(response)
        or response.get("protocol") != ADMIN_BROKER_PROTOCOL
        or response.get("operation") != operation
        or response.get("status") != "AUTHORIZED"
        or response.get("request_id")
        != json.loads(Path(request_path).read_bytes()).get("request_id")
        or "private_key" in json.dumps(response, sort_keys=True).lower()
    ):
        raise MMEAuthorizationBlocked("BLOCKED_EXTERNAL_AUTHORITY_BROKER_RESPONSE")
    return response


def assert_mme_authorization_available(
    workspace_root: str | Path,
    request_path: str | Path,
    authorization_path: str | Path | None,
    *,
    now: datetime | None = None,
    _broker=_call_external_authority_broker,
) -> None:
    _broker(
        workspace_root,
        request_path,
        authorization_path,
        operation="AUTHORIZE",
        now=now,
    )


def claim_mme_block_attempt(
    workspace_root: str | Path,
    request_path: str | Path,
    authorization_path: str | Path | None,
    *,
    block_id: str,
    attempt_id: str,
    checkpoint_id: str,
    now: datetime | None = None,
    _broker=_call_external_authority_broker,
) -> dict[str, Any]:
    return _broker(
        workspace_root,
        request_path,
        authorization_path,
        operation="CLAIM_BLOCK",
        now=now,
        payload={
            "block_id": block_id,
            "attempt_id": attempt_id,
            "checkpoint_id": checkpoint_id,
        },
    )


def validate_mme_block_context(
    workspace_root: str | Path,
    request_path: str | Path,
    authorization_path: str | Path,
    context: dict[str, Any],
    *,
    now: datetime | None = None,
    _broker=_call_external_authority_broker,
) -> dict[str, Any]:
    return _broker(
        workspace_root,
        request_path,
        authorization_path,
        operation="VALIDATE_BLOCK_CONTEXT",
        now=now,
        payload={"context": context},
    )


def prepare_mme_local_fixture(
    workspace_root: str | Path,
    request_path: str | Path,
    authorization_path: str | Path,
    context: dict[str, Any],
    *,
    now: datetime | None = None,
    _validate=validate_mme_block_context,
) -> dict[str, Any]:
    checked = _validate(
        workspace_root, request_path, authorization_path, context, now=now
    )
    return {**checked, "fixture_stage": "PREPARED_NO_WRITE"}


def run_mme_local_fixture(
    workspace_root: str | Path,
    request_path: str | Path,
    authorization_path: str | Path,
    prepared: dict[str, Any],
    *,
    now: datetime | None = None,
    _validate=validate_mme_block_context,
) -> dict[str, Any]:
    context = {key: value for key, value in prepared.items() if key != "fixture_stage"}
    checked = _validate(
        workspace_root, request_path, authorization_path, context, now=now
    )
    return {**checked, "fixture_stage": "WORKER_DRY_RUN_COMPLETE"}


_assert_impl = assert_mme_authorization_available
_claim_impl = claim_mme_block_attempt
_validate_impl = validate_mme_block_context
_prepare_impl = prepare_mme_local_fixture
_run_impl = run_mme_local_fixture


def _bind_path_authority(
    assert_impl, claim_impl, validate_impl, prepare_impl, run_impl
):
    def assert_available(workspace_root, request_path, authorization_path, *, now=None):
        return assert_impl(workspace_root, request_path, authorization_path, now=now)

    def claim(
        workspace_root,
        request_path,
        authorization_path,
        *,
        block_id,
        attempt_id,
        checkpoint_id,
        now=None,
    ):
        return claim_impl(
            workspace_root,
            request_path,
            authorization_path,
            block_id=block_id,
            attempt_id=attempt_id,
            checkpoint_id=checkpoint_id,
            now=now,
        )

    def validate(
        workspace_root, request_path, authorization_path, context, *, now=None
    ):
        return validate_impl(
            workspace_root, request_path, authorization_path, context, now=now
        )

    def prepare(workspace_root, request_path, authorization_path, context, *, now=None):
        return prepare_impl(
            workspace_root, request_path, authorization_path, context, now=now
        )

    def run(workspace_root, request_path, authorization_path, prepared, *, now=None):
        return run_impl(
            workspace_root, request_path, authorization_path, prepared, now=now
        )

    return assert_available, claim, validate, prepare, run


(
    assert_mme_authorization_available,
    claim_mme_block_attempt,
    validate_mme_block_context,
    prepare_mme_local_fixture,
    run_mme_local_fixture,
) = _bind_path_authority(
    _assert_impl, _claim_impl, _validate_impl, _prepare_impl, _run_impl
)
del _assert_impl
del _claim_impl
del _validate_impl
del _prepare_impl
del _run_impl
del _bind_path_authority
del _call_external_authority_broker


__all__ = [
    "MMEAuthorizationBlocked",
    "assert_mme_authorization_available",
    "build_unsigned_request",
    "blocked_decision",
    "claim_mme_block_attempt",
    "prepare_mme_local_fixture",
    "run_mme_local_fixture",
    "validate_offline_signing_manifest",
    "validate_mme_block_context",
    "validate_unsigned_blocked_artifacts",
    "write_offline_signing_package",
    "write_unsigned_request_and_blocked_decision",
]
