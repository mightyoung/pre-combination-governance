"""Frozen, fail-closed regeneration checks for v6.13 segment closeout.

Only commitments and public method results are emitted. Raw payloads and truth
never enter the returned audit report.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from pathlib import Path, PureWindowsPath
from collections.abc import Mapping, Sequence
from typing import Any
from dataclasses import dataclass

from .contracts.canonical_json import canonical_bytes
from .methods import METHOD_IDS

INVALID_STATUS = "INVALID_RESULT_KEEP_DATASET_STOP_NEXT_SEGMENT"
PASS_STATUS = "REGEN_VERIFIED"
CONSISTENT_UNATTESTED_STATUS = "REGEN_CONSISTENT_UNATTESTED"
PLAN_VERSION = "regeneration-plan.v2"
VERDICT_VERSION = "regeneration-verdict.v1"
STRICT_PLAN_VERSION = "regeneration-plan.v3"
EXACT_REPLAY_POLICY = {
    "schema_version": "replay-policy.v1",
    "mode": "exact",
}

_DOMAIN = b"rfb/g004/regeneration/v3\0"
_TOLERANCE_DOMAIN = b"rfb/g004/tolerance-policy/v1\0"
_ATTESTATION_DOMAIN = b"rfb/g006/regeneration-attestation/v1\0"


def _sha256(tag: bytes, value: bytes) -> str:
    return hashlib.sha256(_DOMAIN + tag + b"\0" + value).hexdigest()


def _finite(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, Mapping):
        return all(_finite(key) and _finite(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return all(_finite(item) for item in value)
    return True


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_digest(value: str, name: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return value
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _validated_bundle_ids(bundle_ids: Sequence[str]) -> list[str]:
    if isinstance(bundle_ids, (str, bytes, bytearray)):
        raise ValueError("bundle_ids must be a sequence of identifiers")
    identifiers = list(bundle_ids)
    if len(identifiers) < 2:
        raise ValueError(
            f"segment must contain at least 2 bundles (N={len(identifiers)})"
        )
    if any(not isinstance(item, str) or not item.strip() for item in identifiers):
        raise ValueError("bundle ids must be non-empty strings")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("duplicate bundle id")
    return identifiers


def payload_commitment(payload: Any) -> str:
    """Return a domain-separated commitment for bytes or canonical JSON."""

    if isinstance(payload, bytes):
        raw = b"bytes\0" + payload
    elif isinstance(payload, (bytearray, memoryview)):
        raw = b"bytes\0" + bytes(payload)
    else:
        if not _finite(payload):
            raise ValueError("payload contains NaN or Infinity")
        try:
            raw = b"canonical-json\0" + canonical_bytes(payload)
        except Exception as exc:
            raise ValueError(f"payload is not canonical JSON: {exc}") from exc
    return _sha256(b"payload", raw)


def panel_commitment(panel: Mapping[str, Any]) -> str:
    """Commit an exact seven-method public result panel."""

    if not isinstance(panel, Mapping) or set(panel) != set(METHOD_IDS):
        raise ValueError("panel must contain exactly B0-B5 and Proposed")
    if not _finite(panel):
        raise ValueError("panel contains NaN or Infinity")
    return _sha256(b"panel", canonical_bytes(dict(panel)))


def exact_replay_policy_hash() -> str:
    return hashlib.sha256(canonical_bytes(EXACT_REPLAY_POLICY)).hexdigest()


def select_frozen_samples(
    bundle_ids: Sequence[str], seed: int, segment_id: str | None = None
) -> list[str]:
    """Select an order-independent sample without replacement."""

    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if segment_id is not None and (
        not isinstance(segment_id, str) or not segment_id.strip()
    ):
        raise ValueError("segment_id must be a non-empty string")
    identifiers = _validated_bundle_ids(bundle_ids)
    sample_count = max(2, math.ceil(0.01 * len(identifiers)))
    segment_value = segment_id or ""
    ranked: list[tuple[str, str]] = []
    for bundle_id in identifiers:
        material = canonical_bytes(
            {
                "bundle_id": bundle_id,
                "seed": seed,
                "segment_id": segment_value,
            }
        )
        ranked.append((_sha256(b"sample-rank", material), bundle_id))
    ranked.sort()
    return [bundle_id for _, bundle_id in ranked[:sample_count]]


def freeze_regeneration_plan(
    *,
    segment_id: str,
    bundle_ids: Sequence[str],
    seed: int | None = None,
    sample_selection_seed: int | None = None,
    authority: Mapping[str, Any] | None = None,
    pre_execution_state: str = "PLANNED",
    pre_execution_ledger_head: str = "",
    method_registry_hash: str = "",
    replay_policy_hash: str | None = None,
    generator_hash: str = "",
    config_hash: str = "",
    container_hash: str = "",
    seed_commitment: str = "",
) -> dict[str, Any]:
    """Create a defensive, deterministic plan that must predate execution."""

    if sample_selection_seed is not None or authority is not None:
        if (
            sample_selection_seed is None
            or authority is None
            or replay_policy_hash is None
            or not pre_execution_ledger_head
        ):
            raise TypeError(
                "strict plan requires sample_selection_seed, authority, replay_policy_hash, and pre_execution_ledger_head"
            )
        return _freeze_v3(
            segment_id=segment_id,
            bundle_ids=bundle_ids,
            sample_selection_seed=sample_selection_seed,
            authority=authority,
            replay_policy_hash=replay_policy_hash,
            pre_execution_state=pre_execution_state,
            pre_execution_ledger_head=pre_execution_ledger_head,
        )
    if seed is None:
        raise TypeError("seed is required for compatibility plan")

    if not isinstance(segment_id, str) or not segment_id.strip():
        raise ValueError("segment_id must be a non-empty string")
    if pre_execution_state not in {"PLANNED", "ADMITTED", "MATERIALIZING"}:
        raise ValueError(
            "pre_execution_state must be PLANNED, ADMITTED, or MATERIALIZING"
        )
    identifiers = sorted(_validated_bundle_ids(bundle_ids))
    selected = select_frozen_samples(identifiers, seed, segment_id)
    policy_hash = (
        exact_replay_policy_hash() if replay_policy_hash is None else replay_policy_hash
    )
    commitments = {
        "method_registry_hash": _require_digest(
            method_registry_hash, "method_registry_hash", allow_empty=True
        ),
        "replay_policy_hash": _require_digest(policy_hash, "replay_policy_hash"),
        "generator_hash": _require_digest(
            generator_hash, "generator_hash", allow_empty=True
        ),
        "config_hash": _require_digest(config_hash, "config_hash", allow_empty=True),
        "container_hash": _require_digest(
            container_hash, "container_hash", allow_empty=True
        ),
    }
    if seed_commitment:
        seed_hash = _require_digest(seed_commitment, "seed_commitment")
    else:
        seed_hash = _sha256(
            b"seed-commitment",
            canonical_bytes({"segment_id": segment_id, "seed": seed}),
        )
    if pre_execution_ledger_head:
        ledger_head = _require_digest(
            pre_execution_ledger_head, "pre_execution_ledger_head"
        )
    else:
        ledger_head = _sha256(
            b"pre-execution-ledger-head",
            canonical_bytes(
                {"segment_id": segment_id, "seed": seed, "bundle_ids": identifiers}
            ),
        )
    body: dict[str, Any] = {
        "schema_version": PLAN_VERSION,
        "segment_id": segment_id,
        "bundle_ids": identifiers,
        "bundle_count": len(identifiers),
        "bundle_ids_hash": hashlib.sha256(canonical_bytes(identifiers)).hexdigest(),
        "selected_ids": selected,
        "selected_ids_hash": hashlib.sha256(canonical_bytes(selected)).hexdigest(),
        "sample_count": len(selected),
        "sample_rule": "max(2,ceil(0.01*N))_without_replacement",
        "seed": seed,
        "seed_commitment_sha256": seed_hash,
        "frozen_before_execution": True,
        "pre_execution_state": pre_execution_state,
        "pre_execution_ledger_head": ledger_head,
        **commitments,
    }
    raw = canonical_bytes(body)
    return {
        **body,
        "canonical_bytes": raw,
        "plan_hash": hashlib.sha256(raw).hexdigest(),
    }


build_regeneration_plan = freeze_regeneration_plan


def _validated_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, Mapping) or plan.get("frozen_before_execution") is not True:
        raise ValueError("plan is not frozen before execution")
    raw = plan.get("canonical_bytes")
    body = {
        key: plan[key] for key in plan if key not in {"canonical_bytes", "plan_hash"}
    }
    if (
        not isinstance(raw, bytes)
        or canonical_bytes(body) != raw
        or hashlib.sha256(raw).hexdigest() != plan.get("plan_hash")
    ):
        raise ValueError("plan hash mismatch")
    if body.get("schema_version") != PLAN_VERSION:
        raise ValueError("unsupported regeneration plan version")
    identifiers = _validated_bundle_ids(body.get("bundle_ids", []))
    if identifiers != sorted(identifiers):
        raise ValueError("plan bundle ids are not canonical")
    if body.get("bundle_count") != len(identifiers):
        raise ValueError("plan bundle count mismatch")
    if (
        body.get("bundle_ids_hash")
        != hashlib.sha256(canonical_bytes(identifiers)).hexdigest()
    ):
        raise ValueError("plan bundle commitment mismatch")
    selected = select_frozen_samples(
        identifiers,
        body.get("seed"),
        body.get("segment_id"),
    )
    if body.get("selected_ids") != selected:
        raise ValueError("plan sample selection mismatch")
    if body.get("sample_count") != len(selected) or len(selected) != len(set(selected)):
        raise ValueError("plan sample count or replacement invariant failed")
    if (
        body.get("selected_ids_hash")
        != hashlib.sha256(canonical_bytes(selected)).hexdigest()
    ):
        raise ValueError("plan selected-id commitment mismatch")
    for name in (
        "method_registry_hash",
        "generator_hash",
        "config_hash",
        "container_hash",
    ):
        _require_digest(body.get(name, ""), name, allow_empty=True)
    _require_digest(body.get("replay_policy_hash", ""), "replay_policy_hash")
    _require_digest(body.get("seed_commitment_sha256", ""), "seed_commitment_sha256")
    if body.get("pre_execution_state") not in {"PLANNED", "ADMITTED", "MATERIALIZING"}:
        raise ValueError("invalid pre-execution state")
    _require_digest(
        body.get("pre_execution_ledger_head", ""), "pre_execution_ledger_head"
    )
    return body


def execute_regeneration_plan(
    plan: Mapping[str, Any],
    *,
    current_bundle_ids: Sequence[str],
    segment_id: str,
    seed: int,
    method_registry_hash: str | None = None,
    replay_policy_hash: str | None = None,
    generator_hash: str | None = None,
    config_hash: str | None = None,
    container_hash: str | None = None,
    seed_commitment_sha256: str | None = None,
    pre_execution_state: str | None = None,
    pre_execution_ledger_head: str | None = None,
    authority_root: str | Path | None = None,
    current_authority: Mapping[str, Any] | None = None,
    freeze_event: Mapping[str, Any] | None = None,
    execution_ledger_rows: Sequence[Mapping[str, Any]] | None = None,
) -> list[str]:
    """Validate the frozen plan against authoritative execution-time inputs."""

    if (
        current_authority is not None
        or authority_root is not None
        or freeze_event is not None
        or execution_ledger_rows is not None
    ):
        if (
            authority_root is None
            or current_authority is None
            or freeze_event is None
            or execution_ledger_rows is None
        ):
            raise TypeError(
                "strict execution requires authority_root, current_authority, freeze_event, and execution_ledger_rows"
            )
        if plan.get("schema_version") != STRICT_PLAN_VERSION:
            raise ValueError("compatibility plan cannot execute on strict path")
        return execute_regeneration_plan_v3(
            plan,
            authority_root=authority_root,
            current_authority=current_authority,
            freeze_event=freeze_event,
            execution_ledger_rows=execution_ledger_rows,
            current_bundle_ids=current_bundle_ids,
            segment_id=segment_id,
            sample_selection_seed=seed,
        )

    body = _validated_plan(plan)
    current = sorted(_validated_bundle_ids(current_bundle_ids))
    if current != body["bundle_ids"]:
        raise ValueError("bundle inputs changed after plan freeze")
    if segment_id != body["segment_id"]:
        raise ValueError("segment_id changed after plan freeze")
    if seed != body["seed"]:
        raise ValueError("seed changed after plan freeze")
    if (
        body["method_registry_hash"]
        and method_registry_hash != body["method_registry_hash"]
    ):
        raise ValueError("method registry changed after plan freeze")
    if (
        replay_policy_hash is not None
        and replay_policy_hash != body["replay_policy_hash"]
    ):
        raise ValueError("replay policy changed after plan freeze")
    for name, value in (
        ("generator_hash", generator_hash),
        ("config_hash", config_hash),
        ("container_hash", container_hash),
    ):
        expected = body[name]
        if expected and value is not None and value != expected:
            raise ValueError(f"{name} changed after plan freeze")
    if (
        seed_commitment_sha256 is not None
        and seed_commitment_sha256 != body["seed_commitment_sha256"]
    ):
        raise ValueError("seed commitment changed after plan freeze")
    if (
        pre_execution_state is not None
        and pre_execution_state != body["pre_execution_state"]
    ):
        raise ValueError("pre-execution state changed after plan freeze")
    if (
        pre_execution_ledger_head is not None
        and pre_execution_ledger_head != body["pre_execution_ledger_head"]
    ):
        raise ValueError("pre-execution ledger head changed after plan freeze")
    return list(body["selected_ids"])


def build_tolerance_policy(
    paths: Mapping[str, float | Mapping[str, float]],
) -> dict[str, Any]:
    """Build a deterministic commitment for a pre-specified tolerance policy."""

    normalized: dict[str, dict[str, float]] = {}
    for path, specification in sorted(paths.items()):
        if not isinstance(path, str) or not path or path.startswith("/"):
            raise ValueError("invalid tolerance path")
        parts = path.split(".")
        if ".." in path or parts[0] not in METHOD_IDS:
            raise ValueError("tolerance path must start with a registered method")
        if _numeric(specification):
            absolute, relative = float(specification), 0.0
        elif isinstance(specification, Mapping):
            absolute = float(specification.get("abs", 0.0))
            relative = float(specification.get("rel", 0.0))
        else:
            raise ValueError("invalid tolerance specification")
        if (
            not math.isfinite(absolute)
            or not math.isfinite(relative)
            or absolute < 0
            or relative < 0
        ):
            raise ValueError("tolerances must be finite and non-negative")
        normalized[path] = {"abs": absolute, "rel": relative}
    body = {
        "schema_version": "tolerance-policy.v1",
        "paths": normalized,
    }
    encoded = canonical_bytes(body)
    policy_hash = hashlib.sha256(encoded).hexdigest()
    signature = hashlib.sha256(
        _TOLERANCE_DOMAIN + b"commitment\0" + encoded
    ).hexdigest()
    return {
        **body,
        "signed": True,
        "signature_scheme": "SHA256_DOMAIN_COMMITMENT",
        "signature": signature,
        "hash": policy_hash,
    }


def _parse_policy(
    policy: Mapping[str, Any] | None,
) -> tuple[dict[str, tuple[float, float]], str] | None:
    if policy is None:
        return {}, exact_replay_policy_hash()
    if not isinstance(policy, Mapping):
        return None
    allowed = {
        "schema_version",
        "paths",
        "signed",
        "signature_scheme",
        "signature",
        "hash",
    }
    if set(policy) != allowed:
        return None
    try:
        rebuilt = build_tolerance_policy(policy["paths"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if any(policy.get(key) != rebuilt[key] for key in allowed):
        return None
    return {
        path: (specification["abs"], specification["rel"])
        for path, specification in rebuilt["paths"].items()
    }, rebuilt["hash"]


def _equal(
    expected: Any,
    actual: Any,
    tolerances: Mapping[str, tuple[float, float]],
    path: str = "",
) -> bool:
    if (
        not _finite(expected)
        or not _finite(actual)
        or type(expected) is not type(actual)
    ):
        return False
    if _numeric(expected):
        if path not in tolerances:
            return expected == actual
        absolute, relative = tolerances[path]
        return math.isclose(expected, actual, abs_tol=absolute, rel_tol=relative)
    if isinstance(expected, Mapping):
        return set(expected) == set(actual) and all(
            _equal(
                expected[key],
                actual[key],
                tolerances,
                f"{path}.{key}".lstrip("."),
            )
            for key in expected
        )
    if isinstance(expected, (list, tuple)):
        return len(expected) == len(actual) and all(
            _equal(
                expected_item,
                actual_item,
                tolerances,
                f"{path}.{index}".lstrip("."),
            )
            for index, (expected_item, actual_item) in enumerate(
                zip(expected, actual, strict=True)
            )
        )
    return expected == actual


def compare_full_panel_replay(
    expected_panel: Mapping[str, Any],
    replayed_panel: Mapping[str, Any],
    tolerance_policy: Mapping[str, Any] | None = None,
    *,
    expected_policy_hash: str | None = None,
) -> bool:
    if not isinstance(expected_panel, Mapping) or not isinstance(
        replayed_panel, Mapping
    ):
        return False
    if set(expected_panel) != set(METHOD_IDS) or set(replayed_panel) != set(METHOD_IDS):
        return False
    parsed = _parse_policy(tolerance_policy)
    if parsed is None:
        return False
    tolerances, policy_hash = parsed
    if expected_policy_hash is not None and policy_hash != expected_policy_hash:
        return False
    return all(
        _equal(
            expected_panel[method_id], replayed_panel[method_id], tolerances, method_id
        )
        for method_id in METHOD_IDS
    )


def verify_regeneration(
    *,
    plan: Mapping[str, Any],
    current_bundle_ids: Sequence[str],
    bundle_id: str,
    expected_payload_commitment_sha256: str,
    regenerated_payload: Any,
    original_panel: Mapping[str, Any],
    expected_panel_commitment_sha256: str,
    regenerated_panel: Mapping[str, Any],
    method_registry_hash: str,
    tolerance_policy: Mapping[str, Any] | None = None,
    original_payload: Any | None = None,
) -> dict[str, Any]:
    """Verify one frozen sample against retained commitments and full-panel replay."""

    error_code: str | None = None
    try:
        body = _validated_plan(plan)
        selected = execute_regeneration_plan(
            plan,
            current_bundle_ids=current_bundle_ids,
            segment_id=body["segment_id"],
            seed=body["seed"],
            method_registry_hash=method_registry_hash,
            replay_policy_hash=body["replay_policy_hash"],
            generator_hash=body["generator_hash"],
            config_hash=body["config_hash"],
            container_hash=body["container_hash"],
            seed_commitment_sha256=body["seed_commitment_sha256"],
            pre_execution_state=body["pre_execution_state"],
            pre_execution_ledger_head=body["pre_execution_ledger_head"],
        )
        if bundle_id not in selected:
            raise ValueError("bundle_id is not in the frozen sample")
        expected_payload_hash = _require_digest(
            expected_payload_commitment_sha256,
            "expected_payload_commitment_sha256",
        )
        regenerated_payload_hash = payload_commitment(regenerated_payload)
        if (
            original_payload is not None
            and payload_commitment(original_payload) != expected_payload_hash
        ):
            raise ValueError(
                "stored payload commitment does not match original payload"
            )
        expected_panel_hash = _require_digest(
            expected_panel_commitment_sha256,
            "expected_panel_commitment_sha256",
        )
        observed_panel_hash = panel_commitment(original_panel)
        payload_ok = regenerated_payload_hash == expected_payload_hash
        expected_panel_ok = observed_panel_hash == expected_panel_hash
        panel_ok = expected_panel_ok and compare_full_panel_replay(
            original_panel,
            regenerated_panel,
            tolerance_policy,
            expected_policy_hash=body["replay_policy_hash"],
        )
    except Exception:
        body = dict(plan) if isinstance(plan, Mapping) else {}
        expected_payload_hash = None
        regenerated_payload_hash = None
        expected_panel_hash = None
        observed_panel_hash = None
        payload_ok = False
        expected_panel_ok = False
        panel_ok = False
        error_code = "INVALID_INPUT_OR_FROZEN_PLAN_MISMATCH"
        selected = []

    verified = payload_ok and panel_ok
    report: dict[str, Any] = {
        "status": PASS_STATUS if verified else INVALID_STATUS,
        "regeneration_verified": verified,
        "development_only": True,
        "local_live_gate_passed": False,
        "purge_authorized": False,
        "next_segment_allowed": False,
        "dataset_retained": not verified,
        "segment_id": body.get("segment_id"),
        "bundle_id": bundle_id,
        "plan_hash": plan.get("plan_hash") if isinstance(plan, Mapping) else None,
        "selected_ids_hash": body.get("selected_ids_hash"),
        "sample_count": body.get("sample_count"),
        "frozen_sample_member": bundle_id in selected,
        "payload_commitment_sha256": expected_payload_hash,
        "regenerated_payload_commitment_sha256": regenerated_payload_hash,
        "payload_commitment_match": payload_ok,
        "expected_panel_commitment_sha256": expected_panel_hash,
        "observed_panel_commitment_sha256": observed_panel_hash,
        "expected_panel_commitment_match": expected_panel_ok,
        "full_panel_replay_match": panel_ok,
        "method_registry_hash": body.get("method_registry_hash"),
        "replay_policy_hash": body.get("replay_policy_hash"),
        "method_ids": list(METHOD_IDS),
        "method_count": len(METHOD_IDS),
    }
    if error_code:
        report["error_code"] = error_code
    return report


def finalize_regeneration_verdict(
    plan: Mapping[str, Any], sample_reports: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Aggregate exactly the frozen sample reports into a canonical verdict."""
    body = _validated_plan(plan)
    if isinstance(sample_reports, (str, bytes, bytearray)):
        raise ValueError("sample_reports must be a sequence")
    reports = list(sample_reports)
    expected = set(body["selected_ids"])
    ids = [r.get("bundle_id") if isinstance(r, Mapping) else None for r in reports]
    if (
        len(reports) != len(expected)
        or len(set(ids)) != len(ids)
        or set(ids) != expected
    ):
        raise ValueError(
            "sample reports must contain every selected bundle exactly once"
        )
    ordered = sorted(reports, key=lambda item: item["bundle_id"])
    commitments = []
    all_pass = True
    for report in ordered:
        if (
            report.get("plan_hash") != plan.get("plan_hash")
            or report.get("selected_ids_hash") != body["selected_ids_hash"]
        ):
            raise ValueError("sample report plan commitment mismatch")
        if report.get("bundle_id") not in expected:
            raise ValueError("sample report replacement bundle")
        commitments.append(
            {
                "bundle_id": report["bundle_id"],
                "payload_commitment_sha256": report.get("payload_commitment_sha256"),
                "regenerated_payload_commitment_sha256": report.get(
                    "regenerated_payload_commitment_sha256"
                ),
                "expected_panel_commitment_sha256": report.get(
                    "expected_panel_commitment_sha256"
                ),
                "observed_panel_commitment_sha256": report.get(
                    "observed_panel_commitment_sha256"
                ),
            }
        )
        all_pass = (
            all_pass
            and report.get("status") == PASS_STATUS
            and report.get("regeneration_verified") is True
            and report.get("full_panel_replay_match") is True
        )
    verdict_body = {
        "schema_version": VERDICT_VERSION,
        "status": PASS_STATUS if all_pass else INVALID_STATUS,
        "development_only": True,
        "local_live_gate_passed": False,
        "regeneration_verified": all_pass,
        "fixture_purge_authorized": all_pass,
        "purge_authorized": False,
        "next_segment_allowed": False,
        "dataset_retained": not all_pass,
        "segment_id": body["segment_id"],
        "plan_hash": plan["plan_hash"],
        "selected_ids_hash": body["selected_ids_hash"],
        "selected_bundle_ids": list(body["selected_ids"]),
        "sample_count": len(ordered),
        "method_ids": list(METHOD_IDS),
        "method_count": len(METHOD_IDS),
        "sample_commitments": commitments,
    }
    encoded = canonical_bytes(verdict_body)
    return {
        **verdict_body,
        "canonical_bytes": encoded,
        "verdict_hash": hashlib.sha256(encoded).hexdigest(),
    }


def validate_regeneration_verdict(
    plan: Mapping[str, Any], verdict: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate an aggregate verdict's canonical hash and plan binding."""
    body = _validated_plan(plan)
    if not isinstance(verdict, Mapping):
        raise ValueError("verdict must be a mapping")
    raw = verdict.get("canonical_bytes")
    unsigned = {
        key: verdict[key]
        for key in verdict
        if key not in {"canonical_bytes", "verdict_hash"}
    }
    if (
        not isinstance(raw, bytes)
        or canonical_bytes(unsigned) != raw
        or hashlib.sha256(raw).hexdigest() != verdict.get("verdict_hash")
    ):
        raise ValueError("verdict hash mismatch")
    if (
        verdict.get("plan_hash") != plan.get("plan_hash")
        or verdict.get("selected_ids_hash") != body["selected_ids_hash"]
    ):
        raise ValueError("verdict plan commitment mismatch")
    if verdict.get("selected_bundle_ids") != body["selected_ids"] or verdict.get(
        "sample_count"
    ) != len(body["selected_ids"]):
        raise ValueError("verdict sample selection mismatch")
    commitments = verdict.get("sample_commitments")
    if not isinstance(commitments, list) or [
        item.get("bundle_id") for item in commitments
    ] != sorted(body["selected_ids"]):
        raise ValueError("verdict sample commitments mismatch")
    if (
        verdict.get("status") == PASS_STATUS
        and verdict.get("regeneration_verified") is not True
    ):
        raise ValueError("successful verdict must be verified")
    if (
        verdict.get("status") == INVALID_STATUS
        and verdict.get("next_segment_allowed") is not False
    ):
        raise ValueError("invalid verdict must stop next segment")
    return dict(verdict)


# Strict G006 contracts.  Legacy v2 helpers remain available under their
# existing names for non-destructive fixtures; strict callers use the v3
# keyword surface below and cannot fall back to optional commitments.
_AUTHORITY_FIELDS = (
    "schema_version",
    "development_only",
    "live_use_allowed",
    "runtime_baseline_path",
    "runtime_baseline_self_sha256",
    "source_tree_manifest_path",
    "source_tree_sha256",
    "generator_path",
    "generator_sha256",
    "method_registry_path",
    "method_registry_sha256",
    "container_lock_path",
    "container_definition_sha256",
    "seed_commitment_path",
    "algorithm_seed_commitment_sha256",
    "allocation_commitment_path",
    "allocation_commitment_sha256",
    "segment_config_path",
    "segment_config_sha256",
    "authority_hash",
)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, Mapping):
        raise ValueError(f"JSON object required: {path}")
    return dict(value)


def _validated_authority_root(root: Path) -> Path:
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("authority root must be an absolute normalized path")
    cursor = Path(root.anchor)
    for part in root.parts[1:]:
        cursor /= part
        if cursor.exists() and (
            cursor.is_symlink() or getattr(cursor, "is_junction", lambda: False)()
        ):
            raise ValueError(f"authority root crosses reparse component: {cursor}")
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("authority root must be a directory")
    return resolved


def _authority_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("authority path must be a non-empty POSIX relative path")
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or PureWindowsPath(relative).is_absolute()
        or PureWindowsPath(relative).drive
        or ".." in candidate.parts
    ):
        raise ValueError("authority path must remain relative and root-confined")
    root_resolved = _validated_authority_root(root)
    cursor = root_resolved
    for part in candidate.parts:
        cursor = cursor / part
        if cursor.exists() and (
            cursor.is_symlink() or getattr(cursor, "is_junction", lambda: False)()
        ):
            raise ValueError(f"authority path crosses reparse component: {relative}")
    resolved = cursor.resolve(strict=True)
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError("authority path escapes authority root")
    return resolved


def _file_hash(root: Path, relative: str) -> str:
    path = _authority_path(root, relative)
    if not path.is_file():
        raise ValueError(f"authority reference missing: {relative}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _embedded_hash(root: Path, relative: str, field: str) -> str:
    """Validate an artifact's *declared canonical* commitment.

    Runtime baseline, registry, container, seed and allocation artifacts all
    carry a self-hash over their canonical body (with the self-hash field
    removed).  They must not be compared with the SHA-256 of their pretty
    printed JSON bytes; the latter is intentionally a different value.
    """

    artifact = _read_json(_authority_path(root, relative))
    declared = artifact.get(field)
    if not isinstance(declared, str):
        raise ValueError(f"missing embedded commitment {relative}:{field}")
    body = {key: value for key, value in artifact.items() if key != field}
    actual = hashlib.sha256(canonical_bytes(body)).hexdigest()
    if actual != declared:
        raise ValueError(f"embedded commitment mismatch: {relative}")
    return declared


def _authority_hash(authority: Mapping[str, Any]) -> str:
    body = {key: authority[key] for key in authority if key != "authority_hash"}
    return hashlib.sha256(canonical_bytes(body)).hexdigest()


def validate_runtime_commitment_authority(
    authority_root: str | Path, authority: Mapping[str, Any]
) -> dict[str, Any]:
    root = Path(authority_root)
    if not isinstance(authority, Mapping) or set(authority) != set(_AUTHORITY_FIELDS):
        raise ValueError("runtime authority fields are not exact")
    if authority.get("schema_version") != "runtime-commitment-authority.v1":
        raise ValueError("unsupported runtime authority version")
    if (
        authority.get("development_only") is not True
        or authority.get("live_use_allowed") is not False
    ):
        raise ValueError("runtime authority is not development-only")
    for key in _AUTHORITY_FIELDS:
        if key.endswith("sha256") or key.endswith("_hash"):
            _require_digest(authority.get(key), key)
    for key in _AUTHORITY_FIELDS:
        if key.endswith("_path") or key == "generator_path":
            _authority_path(root, authority[key])
    baseline_path = authority["runtime_baseline_path"]
    baseline = _read_json(_authority_path(root, baseline_path))
    baseline_self = baseline.get("runtime_baseline_sha256")
    if (
        not isinstance(baseline_self, str)
        or hashlib.sha256(
            canonical_bytes(
                {
                    key: value
                    for key, value in baseline.items()
                    if key != "runtime_baseline_sha256"
                }
            )
        ).hexdigest()
        != baseline_self
    ):
        raise ValueError("runtime baseline embedded self-hash mismatch")
    if authority["runtime_baseline_self_sha256"] != baseline_self:
        raise ValueError("runtime baseline commitment differs from authority")
    manifest = _read_json(_authority_path(root, authority["source_tree_manifest_path"]))
    baseline_dir = Path(baseline_path).parent

    def _same_artifact_ref(group: str, field: str, authority_field: str) -> bool:
        declared = baseline.get(group, {}).get(field)
        if not isinstance(declared, str):
            return False
        return Path(authority[authority_field]).as_posix() in {
            Path(declared).as_posix(),
            (baseline_dir / declared).as_posix(),
        }

    if not _same_artifact_ref(
        "code_baseline", "source_tree_manifest", "source_tree_manifest_path"
    ):
        raise ValueError("source tree manifest path differs from baseline")
    if manifest.get("source_tree_sha256") != authority["source_tree_sha256"]:
        raise ValueError("source tree commitment differs from manifest")
    if authority["source_tree_sha256"] != baseline.get("code_baseline", {}).get(
        "source_tree_sha256"
    ):
        raise ValueError("source tree commitment differs from baseline")
    if authority["method_registry_sha256"] != baseline.get("method_registry", {}).get(
        "registry_sha256"
    ):
        raise ValueError("method registry commitment differs from baseline")
    if authority["container_definition_sha256"] != baseline.get("container", {}).get(
        "container_definition_sha256"
    ):
        raise ValueError("container commitment differs from baseline")
    for group, field, path_field in (
        ("method_registry", "path", "method_registry_path"),
        ("container", "container_lock", "container_lock_path"),
        ("seed_commitment", "path", "seed_commitment_path"),
        ("allocation_commitment", "path", "allocation_commitment_path"),
    ):
        if not _same_artifact_ref(group, field, path_field):
            raise ValueError(f"{group} path differs from baseline")
    if _file_hash(root, authority["generator_path"]) != authority["generator_sha256"]:
        raise ValueError("generator source commitment mismatch")
    if (
        _embedded_hash(root, authority["method_registry_path"], "registry_sha256")
        != authority["method_registry_sha256"]
    ):
        raise ValueError("method registry embedded commitment mismatch")
    if (
        _embedded_hash(
            root, authority["container_lock_path"], "container_definition_sha256"
        )
        != authority["container_definition_sha256"]
    ):
        raise ValueError("container embedded commitment mismatch")
    if (
        _embedded_hash(
            root, authority["seed_commitment_path"], "seed_commitment_sha256"
        )
        != authority["algorithm_seed_commitment_sha256"]
    ):
        raise ValueError("seed commitment embedded hash mismatch")
    if (
        _embedded_hash(
            root,
            authority["allocation_commitment_path"],
            "allocation_commitment_sha256",
        )
        != authority["allocation_commitment_sha256"]
    ):
        raise ValueError("allocation commitment embedded hash mismatch")
    if (
        _file_hash(root, authority["segment_config_path"])
        != authority["segment_config_sha256"]
    ):
        raise ValueError("segment configuration commitment mismatch")
    manifest_items = manifest.get("files", [])
    if not isinstance(manifest_items, list):
        raise ValueError("source tree manifest files must be a list")
    files = {
        item.get("path"): item for item in manifest_items if isinstance(item, Mapping)
    }
    if len(files) != len(manifest_items) or any(
        not isinstance(path, str) or not isinstance(item.get("sha256"), str)
        for path, item in files.items()
    ):
        raise ValueError("source tree manifest contains malformed entries")
    current: dict[str, dict[str, Any]] = {}
    for base in (root / "src", root / "tests"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if (
                not path.is_file()
                or path.is_symlink()
                or "__pycache__" in path.parts
                or path.suffix in {".pyc", ".pyo"}
            ):
                continue
            data = path.read_bytes()
            current[path.relative_to(root).as_posix()] = {
                "path": path.relative_to(root).as_posix(),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
    if set(files) != set(current):
        raise ValueError(
            f"source tree manifest file parity mismatch: missing={sorted(set(current) - set(files))} extra={sorted(set(files) - set(current))}"
        )
    if any(
        files[key].get("sha256") != current[key]["sha256"]
        or ("bytes" in files[key] and files[key]["bytes"] != current[key]["bytes"])
        for key in current
    ):
        raise ValueError("source tree manifest file bytes/hash mismatch")
    canonical_files = [
        {"path": key, "sha256": current[key]["sha256"]}
        if "bytes" not in files[key]
        else current[key]
        for key in sorted(current)
    ]
    if (
        manifest.get("source_tree_sha256")
        != hashlib.sha256(canonical_bytes(canonical_files)).hexdigest()
    ):
        raise ValueError("source tree manifest digest mismatch")
    if (
        files.get(authority["generator_path"], {}).get("sha256")
        != authority["generator_sha256"]
    ):
        raise ValueError("generator is not bound to source manifest")
    if authority.get("authority_hash") != _authority_hash(authority):
        raise ValueError("authority hash mismatch")
    return dict(authority)


def load_runtime_commitment_authority(
    authority_root: str | Path, *, generator_path: str, segment_config_path: str
) -> dict[str, Any]:
    root = Path(authority_root)
    baseline_path = Path("outputs/runtime_gate/runtime_baseline.json")
    baseline = _read_json(root / baseline_path)
    runtime_dir = baseline_path.parent

    def baseline_hash(group: str, field: str) -> str:
        value = baseline.get(group, {}).get(field)
        if not isinstance(value, str):
            raise ValueError(f"missing baseline commitment {group}.{field}")
        return value

    authority = {
        "schema_version": "runtime-commitment-authority.v1",
        "development_only": True,
        "live_use_allowed": False,
        "runtime_baseline_path": baseline_path.as_posix(),
        "runtime_baseline_self_sha256": baseline.get("runtime_baseline_sha256"),
        "source_tree_manifest_path": (
            runtime_dir
            / baseline.get("code_baseline", {}).get(
                "source_tree_manifest", "source_tree_manifest.json"
            )
        ).as_posix(),
        "source_tree_sha256": baseline_hash("code_baseline", "source_tree_sha256"),
        "generator_path": generator_path,
        "generator_sha256": _file_hash(root, generator_path),
        "method_registry_path": (
            runtime_dir
            / baseline.get("method_registry", {}).get("path", "method_registry.json")
        ).as_posix(),
        "method_registry_sha256": baseline_hash("method_registry", "registry_sha256"),
        "container_lock_path": (
            runtime_dir
            / baseline.get("container", {}).get("container_lock", "container_lock.json")
        ).as_posix(),
        "container_definition_sha256": baseline_hash(
            "container", "container_definition_sha256"
        ),
        "seed_commitment_path": (
            runtime_dir
            / baseline.get("seed_commitment", {}).get("path", "seed_commitment.json")
        ).as_posix(),
        "algorithm_seed_commitment_sha256": baseline_hash("seed_commitment", "sha256"),
        "allocation_commitment_path": (
            runtime_dir
            / baseline.get("allocation_commitment", {}).get(
                "path", "allocation_commitment.json"
            )
        ).as_posix(),
        "allocation_commitment_sha256": baseline_hash(
            "allocation_commitment", "sha256"
        ),
        "segment_config_path": segment_config_path,
        "segment_config_sha256": _file_hash(root, segment_config_path),
    }
    authority["authority_hash"] = _authority_hash(authority)
    return validate_runtime_commitment_authority(root, authority)


def _freeze_event(plan: Mapping[str, Any]) -> dict[str, Any]:
    body = {
        "schema_version": "regeneration-freeze-event.v1",
        "event": "REGENERATION_PLAN_FROZEN",
        "segment_id": plan["segment_id"],
        "state": plan["pre_execution_state"],
        "prev_hash": plan["pre_execution_ledger_head"],
        "plan_hash": plan["plan_hash"],
        "authority_hash": plan["authority_hash"],
    }
    return {**body, "entry_hash": hashlib.sha256(canonical_bytes(body)).hexdigest()}


def _freeze_v3(
    *,
    segment_id: str,
    bundle_ids: Sequence[str],
    sample_selection_seed: int,
    authority: Mapping[str, Any],
    replay_policy_hash: str,
    pre_execution_state: str,
    pre_execution_ledger_head: str,
) -> dict[str, Any]:
    if pre_execution_state not in {"PLANNED", "ADMITTED", "MATERIALIZING"}:
        raise ValueError("invalid pre-execution state")
    _require_digest(replay_policy_hash, "replay_policy_hash")
    _require_digest(pre_execution_ledger_head, "pre_execution_ledger_head")
    if (
        isinstance(sample_selection_seed, bool)
        or not isinstance(sample_selection_seed, int)
        or sample_selection_seed < 0
    ):
        raise ValueError("sample_selection_seed must be a non-negative integer")
    if not isinstance(authority, Mapping) or set(authority) != set(_AUTHORITY_FIELDS):
        raise ValueError("runtime authority is required")
    ids = sorted(_validated_bundle_ids(bundle_ids))
    selected = select_frozen_samples(ids, sample_selection_seed, segment_id)
    body = {
        "schema_version": STRICT_PLAN_VERSION,
        "development_only": True,
        "authoritative_commitments_bound": True,
        "segment_id": segment_id,
        "bundle_ids": ids,
        "bundle_count": len(ids),
        "bundle_ids_hash": hashlib.sha256(canonical_bytes(ids)).hexdigest(),
        "sample_selection_seed": sample_selection_seed,
        "sample_rule": "max(2,ceil(0.01*N))_without_replacement",
        "selected_ids": selected,
        "selected_ids_hash": hashlib.sha256(canonical_bytes(selected)).hexdigest(),
        "sample_count": len(selected),
        "replay_policy_hash": replay_policy_hash,
        "runtime_authority": dict(authority),
        "authority_hash": authority["authority_hash"],
        "pre_execution_state": pre_execution_state,
        "pre_execution_ledger_head": pre_execution_ledger_head,
        "frozen_before_execution": True,
    }
    encoded = canonical_bytes(body)
    plan = {
        **body,
        "canonical_bytes": encoded,
        "plan_hash": hashlib.sha256(encoded).hexdigest(),
    }
    return {**plan, "freeze_event": _freeze_event(plan)}


# ---------------------------------------------------------------------------
# G006 strict, reconstructive contracts


@dataclass(frozen=True)
class RuntimeCommitmentAuthority(Mapping[str, Any]):
    """Immutable v1 authority wrapper used by strict execution callers."""

    values: Mapping[str, Any]

    def __post_init__(self) -> None:
        validated = dict(self.values)
        object.__setattr__(self, "values", validated)

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def __iter__(self):
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.values)

    @classmethod
    def load(
        cls,
        authority_root: str | Path,
        *,
        generator_path: str,
        segment_config_path: str,
    ) -> "RuntimeCommitmentAuthority":
        return cls(
            load_runtime_commitment_authority(
                authority_root,
                generator_path=generator_path,
                segment_config_path=segment_config_path,
            )
        )


def _strict_authority_dict(
    authority: Mapping[str, Any] | RuntimeCommitmentAuthority,
) -> dict[str, Any]:
    if isinstance(authority, RuntimeCommitmentAuthority):
        authority = authority.values
    if not isinstance(authority, Mapping) or set(authority) != set(_AUTHORITY_FIELDS):
        raise ValueError("strict runtime authority must be a complete v1 object")
    if not all(
        isinstance(authority.get(field), str) and authority.get(field).strip()
        for field in _AUTHORITY_FIELDS
        if field.endswith("path")
    ):
        raise ValueError("strict runtime authority contains an empty path")
    return dict(authority)


def freeze_regeneration_plan_v3(
    *,
    segment_id: str,
    bundle_ids: Sequence[str],
    authority: Mapping[str, Any] | RuntimeCommitmentAuthority,
    replay_policy_hash: str,
    sample_selection_seed: int,
    pre_execution_state: str = "PLANNED",
    pre_execution_ledger_head: str,
) -> dict[str, Any]:
    """Freeze a strict v3 plan and its hash-linked ledger event.

    The authority and ledger head are mandatory and are never synthesized.
    Validation of filesystem artifacts is deliberately repeated by strict
    execution, where ``authority_root`` is available.
    """

    auth = _strict_authority_dict(authority)
    _require_digest(auth["authority_hash"], "authority_hash")
    if auth["authority_hash"] != _authority_hash(auth):
        raise ValueError("runtime authority hash mismatch")
    return _freeze_v3(
        segment_id=segment_id,
        bundle_ids=bundle_ids,
        sample_selection_seed=sample_selection_seed,
        authority=auth,
        replay_policy_hash=replay_policy_hash,
        pre_execution_state=pre_execution_state,
        pre_execution_ledger_head=pre_execution_ledger_head,
    )


build_regeneration_plan_v3 = freeze_regeneration_plan_v3


def _validated_strict_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if (
        not isinstance(plan, Mapping)
        or plan.get("schema_version") != STRICT_PLAN_VERSION
    ):
        raise ValueError("strict execution requires regeneration-plan.v3")
    raw = plan.get("canonical_bytes")
    body = {
        key: plan[key]
        for key in plan
        if key not in {"canonical_bytes", "plan_hash", "freeze_event"}
    }
    if (
        not isinstance(raw, bytes)
        or canonical_bytes(body) != raw
        or hashlib.sha256(raw).hexdigest() != plan.get("plan_hash")
    ):
        raise ValueError("strict plan hash mismatch")
    if plan.get("frozen_before_execution") is not True:
        raise ValueError("strict plan is not frozen")
    ids = _validated_bundle_ids(body.get("bundle_ids", []))
    if ids != sorted(ids) or body.get("bundle_count") != len(ids):
        raise ValueError("strict plan bundle closure mismatch")
    if body.get("bundle_ids_hash") != hashlib.sha256(canonical_bytes(ids)).hexdigest():
        raise ValueError("strict plan bundle commitment mismatch")
    seed = body.get("sample_selection_seed")
    selected = select_frozen_samples(ids, seed, body.get("segment_id"))
    if (
        body.get("selected_ids") != selected
        or body.get("selected_ids_hash")
        != hashlib.sha256(canonical_bytes(selected)).hexdigest()
    ):
        raise ValueError("strict plan sample commitment mismatch")
    if body.get("sample_count") != len(selected):
        raise ValueError("strict plan sample count mismatch")
    _require_digest(body.get("replay_policy_hash", ""), "replay_policy_hash")
    _require_digest(
        body.get("pre_execution_ledger_head", ""), "pre_execution_ledger_head"
    )
    _strict_authority_dict(body.get("runtime_authority", {}))
    if body.get("authority_hash") != body["runtime_authority"].get("authority_hash"):
        raise ValueError("strict plan authority mismatch")
    return body


def execute_regeneration_plan_v3(
    plan: Mapping[str, Any],
    *,
    authority_root: str | Path,
    current_authority: Mapping[str, Any] | RuntimeCommitmentAuthority,
    freeze_event: Mapping[str, Any],
    execution_ledger_rows: Sequence[Mapping[str, Any]],
    current_bundle_ids: Sequence[str],
    segment_id: str,
    sample_selection_seed: int,
) -> list[str]:
    """Reload authority and verify freeze ordering at execution time."""

    body = _validated_strict_plan(plan)
    supplied = _strict_authority_dict(current_authority)
    loaded = load_runtime_commitment_authority(
        authority_root,
        generator_path=body["runtime_authority"]["generator_path"],
        segment_config_path=body["runtime_authority"]["segment_config_path"],
    )
    if supplied != loaded or loaded != body["runtime_authority"]:
        raise ValueError("execution authority does not match reloaded authority")
    if (
        segment_id != body["segment_id"]
        or sample_selection_seed != body["sample_selection_seed"]
    ):
        raise ValueError("execution inputs changed after strict freeze")
    if sorted(_validated_bundle_ids(current_bundle_ids)) != body["bundle_ids"]:
        raise ValueError("bundle inputs changed after strict freeze")
    event = dict(freeze_event) if isinstance(freeze_event, Mapping) else {}
    event_body = {key: event[key] for key in event if key != "entry_hash"}
    if event_body != {
        "schema_version": "regeneration-freeze-event.v1",
        "event": "REGENERATION_PLAN_FROZEN",
        "segment_id": body["segment_id"],
        "state": body["pre_execution_state"],
        "prev_hash": body["pre_execution_ledger_head"],
        "plan_hash": plan["plan_hash"],
        "authority_hash": body["authority_hash"],
    } or hashlib.sha256(canonical_bytes(event_body)).hexdigest() != event.get(
        "entry_hash"
    ):
        raise ValueError("strict freeze event mismatch")
    rows = list(execution_ledger_rows)
    if not rows:
        raise ValueError("execution ledger rows are missing")
    genesis = rows[0] if isinstance(rows[0], Mapping) else {}
    if genesis != {
        "schema_version": "segment-ledger-entry.v1",
        "event": "SEGMENT_PRE_EXECUTION",
        "segment_id": body["segment_id"],
        "state": body["pre_execution_state"],
        "prev_hash": "0" * 64,
        "entry_hash": genesis.get("entry_hash"),
    }:
        raise ValueError("execution ledger row zero is not the canonical genesis")
    for row_index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError("execution ledger row is not an object")
        entry_hash = row.get("entry_hash")
        _require_digest(entry_hash, "entry_hash")
        unsigned = {key: row[key] for key in row if key != "entry_hash"}
        if hashlib.sha256(canonical_bytes(unsigned)).hexdigest() != entry_hash:
            raise ValueError("execution ledger entry hash mismatch")
        if row.get("segment_id") != body["segment_id"]:
            raise ValueError("execution ledger segment mismatch")
        if row_index and row.get("prev_hash") != rows[row_index - 1].get("entry_hash"):
            raise ValueError("execution ledger predecessor discontinuity")
    index = next(
        (
            i
            for i, row in enumerate(rows)
            if isinstance(row, Mapping)
            and row.get("entry_hash") == event.get("entry_hash")
            and row.get("event") == "REGENERATION_PLAN_FROZEN"
        ),
        None,
    )
    if index is None:
        raise ValueError("strict freeze event is absent from execution ledger")
    if index == 0:
        raise ValueError("strict freeze event cannot be ledger row zero")
    if rows[index - 1].get("entry_hash") != body["pre_execution_ledger_head"]:
        raise ValueError("strict freeze event is not linked to ledger head")
    return list(body["selected_ids"])


execute_regeneration_plan_strict = execute_regeneration_plan_v3


_EXPECTATION_FIELDS = {
    "schema_version",
    "segment_id",
    "bundle_id",
    "plan_hash",
    "authority_hash",
    "selected_ids_hash",
    "payload_commitment_sha256",
    "expected_panel_commitment_sha256",
    "replay_policy_hash",
    "method_registry_hash",
    "expectation_hash",
}


def build_regeneration_expectation(
    *,
    plan: Mapping[str, Any],
    bundle_id: str,
    payload_commitment_sha256: str,
    expected_panel_commitment_sha256: str,
) -> dict[str, Any]:
    """Create a canonical expectation record; it carries no verification verdict."""

    body = _validated_strict_plan(plan)
    if bundle_id not in body["selected_ids"]:
        raise ValueError("expectation bundle is not selected")
    for value, name in (
        (payload_commitment_sha256, "payload_commitment_sha256"),
        (expected_panel_commitment_sha256, "expected_panel_commitment_sha256"),
    ):
        _require_digest(value, name)
    record = {
        "schema_version": "regeneration-expectation.v1",
        "segment_id": body["segment_id"],
        "bundle_id": bundle_id,
        "plan_hash": plan["plan_hash"],
        "authority_hash": body["authority_hash"],
        "selected_ids_hash": body["selected_ids_hash"],
        "payload_commitment_sha256": payload_commitment_sha256,
        "expected_panel_commitment_sha256": expected_panel_commitment_sha256,
        "replay_policy_hash": body["replay_policy_hash"],
        "method_registry_hash": body["runtime_authority"]["method_registry_sha256"],
    }
    encoded = canonical_bytes(record)
    return {**record, "expectation_hash": hashlib.sha256(encoded).hexdigest()}


def _validated_expectation(
    expectation: Mapping[str, Any], plan: Mapping[str, Any]
) -> dict[str, Any]:
    body = dict(expectation)
    if set(body) != _EXPECTATION_FIELDS:
        raise ValueError("expectation fields are not exact")
    digest_fields = [
        field
        for field in _EXPECTATION_FIELDS
        if field.endswith("hash") or field.endswith("sha256")
    ]
    for field in digest_fields:
        _require_digest(body[field], field)
    expected_hash = hashlib.sha256(
        canonical_bytes({key: body[key] for key in body if key != "expectation_hash"})
    ).hexdigest()
    if expected_hash != body["expectation_hash"]:
        raise ValueError("expectation hash mismatch")
    if body.get("schema_version") != "regeneration-expectation.v1":
        raise ValueError("unsupported regeneration expectation version")
    pbody = _validated_strict_plan(plan)
    if any(
        body[key] != expected
        for key, expected in (
            ("plan_hash", plan["plan_hash"]),
            ("authority_hash", pbody["authority_hash"]),
            ("selected_ids_hash", pbody["selected_ids_hash"]),
            ("segment_id", pbody["segment_id"]),
        )
    ):
        raise ValueError("expectation plan commitment mismatch")
    if (
        body["replay_policy_hash"] != pbody["replay_policy_hash"]
        or body["method_registry_hash"]
        != pbody["runtime_authority"]["method_registry_sha256"]
    ):
        raise ValueError("expectation authority commitment mismatch")
    if body["bundle_id"] not in pbody["selected_ids"]:
        raise ValueError("expectation bundle is not selected")
    return body


_REPORT_FIELDS = {
    "schema_version",
    "segment_id",
    "bundle_id",
    "plan_hash",
    "expectation_hash",
    "authority_hash",
    "payload_commitment_sha256",
    "regenerated_payload_commitment_sha256",
    "expected_panel_commitment_sha256",
    "observed_panel_commitment_sha256",
    "regenerated_panel_commitment_sha256",
    "payload_commitment_match",
    "expected_panel_commitment_match",
    "full_panel_replay_match",
    "regeneration_verified",
    "status",
    "report_hash",
}


def validate_regeneration_sample_report(
    report: Mapping[str, Any],
    *,
    expectation: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a v1 report and reconstruct its booleans/status from hashes."""

    if not isinstance(report, Mapping) or set(report) != _REPORT_FIELDS:
        raise ValueError("sample report fields are not exact")
    exp = _validated_expectation(expectation, plan)
    body = {key: report[key] for key in report if key != "report_hash"}
    if hashlib.sha256(canonical_bytes(body)).hexdigest() != report["report_hash"]:
        raise ValueError("sample report hash mismatch")
    if report["schema_version"] != "regeneration-sample-report.v1":
        raise ValueError("sample report schema version mismatch")
    for field in (
        "segment_id",
        "plan_hash",
        "authority_hash",
        "bundle_id",
        "expectation_hash",
    ):
        expected = exp[field] if field in exp else plan[field]
        if report[field] != expected:
            raise ValueError(f"sample report {field} mismatch")
    if report["payload_commitment_sha256"] != exp["payload_commitment_sha256"]:
        raise ValueError("sample report payload expectation mismatch")
    if (
        report["expected_panel_commitment_sha256"]
        != exp["expected_panel_commitment_sha256"]
    ):
        raise ValueError("sample report panel expectation mismatch")
    if report["expectation_hash"] != exp["expectation_hash"]:
        raise ValueError("sample report expectation mismatch")
    for field in (
        "payload_commitment_sha256",
        "regenerated_payload_commitment_sha256",
        "expected_panel_commitment_sha256",
        "observed_panel_commitment_sha256",
        "regenerated_panel_commitment_sha256",
        "plan_hash",
        "authority_hash",
    ):
        _require_digest(report[field], field)
    payload_ok = (
        report["payload_commitment_sha256"]
        == report["regenerated_payload_commitment_sha256"]
    )
    expected_panel_ok = (
        report["expected_panel_commitment_sha256"]
        == report["observed_panel_commitment_sha256"]
    )
    replay_ok = (
        expected_panel_ok
        and report["regenerated_panel_commitment_sha256"]
        == report["expected_panel_commitment_sha256"]
    )
    verified = payload_ok and expected_panel_ok and replay_ok
    if (
        report["payload_commitment_match"] is not payload_ok
        or report["expected_panel_commitment_match"] is not expected_panel_ok
        or report["full_panel_replay_match"] is not replay_ok
        or report["regeneration_verified"] is not verified
        or report["status"] != (PASS_STATUS if verified else INVALID_STATUS)
    ):
        raise ValueError("sample report status or booleans are not reconstructive")
    return dict(report)


def verify_regeneration_sample(
    *,
    plan: Mapping[str, Any],
    expectation: Mapping[str, Any],
    authority_root: str | Path,
    current_authority: Mapping[str, Any] | RuntimeCommitmentAuthority,
    freeze_event: Mapping[str, Any],
    execution_ledger_rows: Sequence[Mapping[str, Any]],
    current_bundle_ids: Sequence[str],
    regenerated_payload: Any,
    original_panel: Mapping[str, Any],
    regenerated_panel: Mapping[str, Any],
    original_payload: Any | None = None,
    tolerance_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Only successful constructor for strict sample reports."""

    body = _validated_strict_plan(plan)
    execute_regeneration_plan_v3(
        plan,
        authority_root=authority_root,
        current_authority=current_authority,
        freeze_event=freeze_event,
        execution_ledger_rows=execution_ledger_rows,
        current_bundle_ids=current_bundle_ids,
        segment_id=body["segment_id"],
        sample_selection_seed=body["sample_selection_seed"],
    )
    exp = _validated_expectation(expectation, plan)
    original_payload_hash = (
        payload_commitment(original_payload)
        if original_payload is not None
        else exp["payload_commitment_sha256"]
    )
    regenerated_hash = payload_commitment(regenerated_payload)
    observed_panel_hash = panel_commitment(original_panel)
    panel_match = compare_full_panel_replay(
        original_panel,
        regenerated_panel,
        tolerance_policy,
        expected_policy_hash=body["replay_policy_hash"],
    )
    report_body = {
        "schema_version": "regeneration-sample-report.v1",
        "segment_id": body["segment_id"],
        "bundle_id": exp["bundle_id"],
        "plan_hash": plan["plan_hash"],
        "expectation_hash": exp["expectation_hash"],
        "authority_hash": body["authority_hash"],
        "payload_commitment_sha256": exp["payload_commitment_sha256"],
        "regenerated_payload_commitment_sha256": regenerated_hash,
        "expected_panel_commitment_sha256": exp["expected_panel_commitment_sha256"],
        "observed_panel_commitment_sha256": observed_panel_hash,
        "regenerated_panel_commitment_sha256": panel_commitment(regenerated_panel),
        "payload_commitment_match": original_payload_hash
        == exp["payload_commitment_sha256"]
        and regenerated_hash == exp["payload_commitment_sha256"],
        "expected_panel_commitment_match": observed_panel_hash
        == exp["expected_panel_commitment_sha256"],
        "full_panel_replay_match": panel_match
        and panel_commitment(regenerated_panel)
        == exp["expected_panel_commitment_sha256"],
        "regeneration_verified": False,
        "status": INVALID_STATUS,
    }
    verified = (
        report_body["payload_commitment_match"]
        and report_body["expected_panel_commitment_match"]
        and panel_match
    )
    report_body["regeneration_verified"] = verified
    report_body["status"] = PASS_STATUS if verified else INVALID_STATUS
    return {
        **report_body,
        "report_hash": hashlib.sha256(canonical_bytes(report_body)).hexdigest(),
    }


def finalize_regeneration_verdict_v2(
    plan: Mapping[str, Any],
    expectations: Sequence[Mapping[str, Any]],
    reports: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Reconstruct a v2 verdict from exact expectation/report closure."""

    body = _validated_strict_plan(plan)
    exps = list(expectations)
    reps = list(reports)
    if len(exps) != len(body["selected_ids"]) or {
        e.get("bundle_id") for e in exps
    } != set(body["selected_ids"]):
        raise ValueError("expectations must cover every selected bundle exactly once")
    if (
        len(reps) != len(body["selected_ids"])
        or len({r.get("bundle_id") for r in reps}) != len(reps)
        or {r.get("bundle_id") for r in reps} != set(body["selected_ids"])
    ):
        raise ValueError("reports must cover every selected bundle exactly once")
    exp_by_id = {e["bundle_id"]: _validated_expectation(e, plan) for e in exps}
    validated = [
        validate_regeneration_sample_report(
            r, expectation=exp_by_id[r.get("bundle_id")], plan=plan
        )
        for r in reps
    ]
    ordered = sorted(validated, key=lambda r: r["bundle_id"])
    all_pass = all(r["regeneration_verified"] is True for r in ordered)
    verdict_body = {
        "schema_version": "regeneration-verdict.v2",
        "segment_id": body["segment_id"],
        "plan_hash": plan["plan_hash"],
        "authority_hash": body["authority_hash"],
        "selected_bundle_ids": list(body["selected_ids"]),
        "sample_count": len(ordered),
        "status": CONSISTENT_UNATTESTED_STATUS if all_pass else INVALID_STATUS,
        "authoritative": False,
        "regeneration_verified": all_pass,
        "next_segment_allowed": False,
        "dataset_retained": not all_pass,
        "purge_authorized": False,
        "report_hashes": [r["report_hash"] for r in ordered],
    }
    return {
        **verdict_body,
        "verdict_hash": hashlib.sha256(canonical_bytes(verdict_body)).hexdigest(),
    }


_ATTESTATION_FIELDS = {
    "schema_id",
    "status",
    "segment_id",
    "plan_hash",
    "authority_hash",
    "selected_ids_hash",
    "freeze_event_hash",
    "pre_execution_ledger_head",
    "final_ledger_head",
    "expectation_root",
    "report_root",
    "report_hashes",
    "replay_policy_hash",
    "method_registry_hash",
    "runtime_authority_hash",
    "verdict_hash",
    "sealed_commitments",
    "key_id",
    "role",
    "trust_epoch",
    "signature",
}


def build_regeneration_attestation(
    *,
    plan,
    expectations,
    reports,
    verdict,
    freeze_event,
    execution_ledger_rows,
    attester,
    sealed_commitments=None,
    independent_key_ids=None,
):
    """Create an independently keyed attestation for strict regeneration."""
    body_plan = _validated_strict_plan(plan)
    if not isinstance(attester, Mapping):
        raise ValueError("independent regeneration attester is required")
    key_id, role, epoch, secret = (
        attester.get(k) for k in ("key_id", "role", "trust_epoch", "secret")
    )
    if not all(isinstance(v, str) and v.strip() for v in (key_id, role, epoch)):
        raise ValueError("attester key_id, role and trust_epoch are required")
    if independent_key_ids is None or key_id not in set(independent_key_ids):
        raise ValueError("attestation key is not independently identified")
    if not isinstance(secret, (str, bytes, bytearray)) or not secret:
        raise ValueError("attester verified secret is required")
    key = secret.encode() if isinstance(secret, str) else bytes(secret)
    if len(key) < 16 or role in {"generator", "runtime"}:
        raise ValueError("attester identity is not independent")
    exps = [_validated_expectation(item, plan) for item in expectations]
    exp_by_id = {item["bundle_id"]: item for item in exps}
    reps = [
        validate_regeneration_sample_report(
            item, expectation=exp_by_id[item.get("bundle_id")], plan=plan
        )
        for item in reports
    ]
    rebuilt = finalize_regeneration_verdict_v2(plan, exps, reps)
    if (
        dict(verdict) != rebuilt
        or rebuilt.get("status") != CONSISTENT_UNATTESTED_STATUS
    ):
        raise ValueError("only a reconstructively consistent verdict can be attested")
    rows = list(execution_ledger_rows)
    if not rows or not all(isinstance(row, Mapping) for row in rows):
        raise ValueError("execution ledger rows are required")
    if not isinstance(sealed_commitments, Mapping):
        raise ValueError("exact sealed commitments are required")
    required_sealed = {
        "result_manifest_hash",
        "archive_a_readback_root",
        "archive_b_readback_root",
        "truth_isolation_commitment",
        "sealed_package_root",
    }
    sealed = dict(sealed_commitments)
    if set(sealed) != required_sealed:
        raise ValueError("sealed commitments must contain the exact required set")
    for name, value in sealed.items():
        _require_digest(value, name)
    unsigned = {
        "schema_id": "regeneration-attestation.v1",
        "status": PASS_STATUS,
        "segment_id": body_plan["segment_id"],
        "plan_hash": plan["plan_hash"],
        "authority_hash": body_plan["authority_hash"],
        "selected_ids_hash": body_plan["selected_ids_hash"],
        "freeze_event_hash": hashlib.sha256(
            canonical_bytes(dict(freeze_event))
        ).hexdigest(),
        "pre_execution_ledger_head": body_plan["pre_execution_ledger_head"],
        "final_ledger_head": rows[-1].get("entry_hash"),
        "expectation_root": hashlib.sha256(canonical_bytes(exps)).hexdigest(),
        "report_root": hashlib.sha256(canonical_bytes(reps)).hexdigest(),
        "report_hashes": [
            item["report_hash"] for item in sorted(reps, key=lambda x: x["bundle_id"])
        ],
        "replay_policy_hash": body_plan["replay_policy_hash"],
        "method_registry_hash": body_plan["runtime_authority"][
            "method_registry_sha256"
        ],
        "runtime_authority_hash": hashlib.sha256(
            canonical_bytes(dict(body_plan["runtime_authority"]))
        ).hexdigest(),
        "verdict_hash": rebuilt["verdict_hash"],
        "sealed_commitments": sealed,
        "key_id": key_id,
        "role": role,
        "trust_epoch": epoch,
    }
    return {
        **unsigned,
        "signature": hmac.new(
            _ATTESTATION_DOMAIN + key, canonical_bytes(unsigned), hashlib.sha256
        ).hexdigest(),
    }


def verify_regeneration_attestation(
    attestation,
    *,
    trust,
    plan,
    expectations,
    reports,
    verdict,
    freeze_event,
    execution_ledger_rows,
    independent_key_ids=None,
):
    if not isinstance(attestation, Mapping) or not isinstance(trust, Mapping):
        raise ValueError("signed regeneration attestation and trust are required")
    if set(attestation) != _ATTESTATION_FIELDS:
        raise ValueError("regeneration attestation schema is invalid")
    if "secret" not in trust:
        raise ValueError("attestation trust material must be supplied out-of-band")
    if independent_key_ids is None or attestation.get("key_id") not in set(
        independent_key_ids
    ):
        raise ValueError("attestation key is not independently identified")
    if attestation.get("key_id") != trust.get("key_id"):
        raise ValueError("attestation key id is not trusted")
    if (
        attestation.get("role") != "RegenerationAttester"
        or trust.get("role") != "RegenerationAttester"
    ):
        raise ValueError("attestation role is invalid")
    if attestation.get("trust_epoch") != trust.get("trust_epoch"):
        raise ValueError("attestation trust epoch is not current")
    expected = build_regeneration_attestation(
        plan=plan,
        expectations=expectations,
        reports=reports,
        verdict=verdict,
        freeze_event=freeze_event,
        execution_ledger_rows=execution_ledger_rows,
        attester=trust,
        sealed_commitments=attestation.get("sealed_commitments"),
        independent_key_ids=independent_key_ids,
    )
    if not hmac.compare_digest(
        str(attestation.get("signature", "")), expected["signature"]
    ):
        raise ValueError("regeneration attestation binding or signature mismatch")
    if dict(attestation) != expected:
        raise ValueError("regeneration attestation binding mismatch")
    return dict(attestation)


finalize_regeneration_verdict_strict = finalize_regeneration_verdict_v2


__all__ = [
    "INVALID_STATUS",
    "PASS_STATUS",
    "build_regeneration_plan",
    "build_tolerance_policy",
    "compare_full_panel_replay",
    "exact_replay_policy_hash",
    "execute_regeneration_plan",
    "freeze_regeneration_plan",
    "panel_commitment",
    "payload_commitment",
    "select_frozen_samples",
    "verify_regeneration",
    "finalize_regeneration_verdict",
    "validate_regeneration_verdict",
    "RuntimeCommitmentAuthority",
    "validate_runtime_commitment_authority",
    "load_runtime_commitment_authority",
    "freeze_regeneration_plan_v3",
    "build_regeneration_plan_v3",
    "execute_regeneration_plan_v3",
    "execute_regeneration_plan_strict",
    "build_regeneration_expectation",
    "validate_regeneration_sample_report",
    "verify_regeneration_sample",
    "finalize_regeneration_verdict_v2",
    "finalize_regeneration_verdict_strict",
    "build_regeneration_attestation",
    "verify_regeneration_attestation",
]
