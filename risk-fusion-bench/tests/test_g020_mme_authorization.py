from __future__ import annotations

import base64
import copy
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from rfb.contracts.canonical_json import canonical_bytes
from rfb.research import mme_authorization, phase0_qualification
from rfb.research.controller import (
    PreparedResearchRun,
    execute_remote,
    guard_mme_controller_entry,
    prepare_run,
)
from rfb.research.mme_authorization import MMEAuthorizationBlocked
from rfb.research.worker import run_worker

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parent
_LIVE_REQUEST: dict | None = None


def _sha(value: bytes) -> str:
    return mme_authorization._sha(value)


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _public(private: Ed25519PrivateKey) -> str:
    return base64.b64encode(private.public_key().public_bytes_raw()).decode()


def _resign_request(request: dict) -> dict:
    core = {
        k: v
        for k, v in request.items()
        if k not in {"request_id", "request_self_sha256"}
    }
    request = {**core, "request_id": _sha(canonical_bytes(core))}
    body = {k: v for k, v in request.items() if k != "request_self_sha256"}
    return {**body, "request_self_sha256": _sha(canonical_bytes(body))}


def _live_request() -> dict:
    global _LIVE_REQUEST
    if _LIVE_REQUEST is None:
        _LIVE_REQUEST = mme_authorization.build_unsigned_request(WORKSPACE)
    return copy.deepcopy(_LIVE_REQUEST)


def _test_authorization(tmp_path: Path, *, request: dict | None = None) -> dict:
    request = copy.deepcopy(request or _live_request())
    request_path = tmp_path / "request.json"
    _write(request_path, request)
    now = datetime.now(UTC).replace(microsecond=0)
    keys = {
        name: Ed25519PrivateKey.generate()
        for name in ("producer", "approver", "admin", "issuer")
    }
    roles = {
        "producer": (
            "G020_PRODUCER_ATTESTATION_KEY",
            "G020_AUTHORIZATION_REQUEST_GENERATOR",
            "PRODUCER_ATTESTER",
            False,
        ),
        "approver": (
            "approver-key",
            "independent-reviewer",
            "INDEPENDENT_EXECUTION_APPROVER",
            True,
        ),
        "admin": ("admin-key", "installation-admin", "TRUST_ADMIN", True),
        "issuer": ("issuer-key", "block-broker", "BLOCK_ISSUER", True),
    }
    trust_body = {
        "schema_version": "1.0.0",
        "trust_epoch": "TEST_ONLY_EPOCH_1",
        "keys": [
            {
                "key_id": kid,
                "signer_id": sid,
                "signer_role": role,
                "independent": independent,
                "algorithm": "ED25519",
                "public_key_b64": _public(keys[name]),
                "not_before_utc": _time(now - timedelta(hours=1)),
                "not_after_utc": _time(now + timedelta(hours=2)),
            }
            for name, (kid, sid, role, independent) in roles.items()
        ],
    }
    trust = {**trust_body, "trust_root_self_sha256": _sha(canonical_bytes(trust_body))}
    trust_hash = _sha(canonical_bytes(trust))
    issued = max(now, mme_authorization._parse_time(request["issued_at_utc"]))
    expires = min(
        issued + timedelta(minutes=30),
        mme_authorization._parse_time(request["expires_at_utc"]),
    )
    core = {
        "schema_version": "1.0.0",
        "status": "SIGNED_AUTHORIZATION",
        "execution_protocol_id": "RFB_MME_V1_EXACT27_LOCAL",
        "request_id": request["request_id"],
        "request_sha256": _sha(canonical_bytes(request)),
        "run_family": "MME_V1_LOCAL_EXACT27",
        "execution_plan_sha256": request["bindings"]["execution_plan"][
            "execution_plan_sha256"
        ],
        "issued_at_utc": _time(issued),
        "expires_at_utc": _time(expires),
        "trust_epoch": trust["trust_epoch"],
        "trust_root_sha256": trust_hash,
    }
    authorization_id = _sha(canonical_bytes(core))
    payload = canonical_bytes(
        {
            "domain": "RFB_MME_SIGNED_AUTHORIZATION_V1",
            "authorization_id": authorization_id,
            "authorization_core_sha256": _sha(canonical_bytes(core)),
        }
    )

    def signature(name: str) -> dict:
        kid, sid, role, _ = roles[name]
        return {
            "signer_id": sid,
            "signer_role": role,
            "key_id": kid,
            "algorithm": "ED25519",
            "signed_at_utc": _time(issued),
            "signature_b64": base64.b64encode(keys[name].sign(payload)).decode(),
        }

    authorization = {
        **core,
        "authorization_id": authorization_id,
        "producer_attestation": signature("producer"),
        "independent_signature": signature("approver"),
    }
    authorization_path = tmp_path / "authorization.json"
    _write(authorization_path, authorization)
    crl_body = {
        "schema_version": "1.0.0",
        "trust_epoch": trust["trust_epoch"],
        "trust_root_sha256": trust_hash,
        "revocation_epoch": 0,
        "previous_revocation_sha256": "0" * 64,
        "published_at_utc": _time(issued - timedelta(minutes=1)),
        "next_update_utc": _time(issued + timedelta(hours=1)),
        "revoked_key_ids": [],
        "revoked_request_ids": [],
        "revoked_signature_sha256": [],
        "signer_id": roles["admin"][1],
        "signer_role": "TRUST_ADMIN",
        "key_id": roles["admin"][0],
        "algorithm": "ED25519",
    }
    crl = {
        **crl_body,
        "signature_b64": base64.b64encode(
            keys["admin"].sign(
                canonical_bytes({"domain": "RFB_MME_CRL_V1", **crl_body})
            )
        ).decode(),
    }
    config = {
        "trust_root": trust,
        "crl": crl,
        "state_dir": tmp_path / "state",
        "block_issuer_private_key_b64": base64.b64encode(
            keys["issuer"].private_bytes_raw()
        ).decode(),
    }
    return locals()


@contextmanager
def _admin_fixture(bundle: dict):
    yield


def _accept(bundle: dict, *, now: datetime | None = None):
    instant = now or bundle["issued"]
    validated = mme_authorization._validate_authorization_documents(
        WORKSPACE,
        bundle["request"],
        bundle["authorization"],
        bundle["config"]["trust_root"],
        bundle["config"]["crl"],
        instant,
    )
    mme_authorization._update_security_state(
        bundle["config"]["state_dir"],
        bundle["config"]["crl"],
        validated["crl_hash"],
        instant,
    )
    return validated


def _claim_fixture(bundle: dict, *, block_id: str, attempt_id: str, checkpoint_id: str):
    validated = _accept(bundle)
    return mme_authorization._claim_validated_block(
        validated,
        bundle["config"]["state_dir"],
        bundle["config"]["block_issuer_private_key_b64"],
        block_id=block_id,
        attempt_id=attempt_id,
        checkpoint_id=checkpoint_id,
    )


def _reauthorize(bundle: dict, trust: dict) -> dict:
    core = {
        key: value
        for key, value in bundle["authorization"].items()
        if key
        not in {"authorization_id", "producer_attestation", "independent_signature"}
    }
    core["trust_root_sha256"] = _sha(canonical_bytes(trust))
    core["trust_epoch"] = trust["trust_epoch"]
    authorization_id = _sha(canonical_bytes(core))
    payload = canonical_bytes(
        {
            "domain": "RFB_MME_SIGNED_AUTHORIZATION_V1",
            "authorization_id": authorization_id,
            "authorization_core_sha256": _sha(canonical_bytes(core)),
        }
    )

    def signature(name: str) -> dict:
        key_id, signer_id, role, _ = bundle["roles"][name]
        return {
            "signer_id": signer_id,
            "signer_role": role,
            "key_id": key_id,
            "algorithm": "ED25519",
            "signed_at_utc": core["issued_at_utc"],
            "signature_b64": base64.b64encode(
                bundle["keys"][name].sign(payload)
            ).decode(),
        }

    return {
        **core,
        "authorization_id": authorization_id,
        "producer_attestation": signature("producer"),
        "independent_signature": signature("approver"),
    }


def _sign_crl(bundle: dict, body: dict) -> dict:
    return {
        **body,
        "signature_b64": base64.b64encode(
            bundle["keys"]["admin"].sign(
                canonical_bytes({"domain": "RFB_MME_CRL_V1", **body})
            )
        ).decode(),
    }


def test_g020_only_unsigned_request_and_blocked_decision_are_produced(tmp_path):
    request_path, decision_path = (
        mme_authorization.write_unsigned_request_and_blocked_decision(
            WORKSPACE, tmp_path
        )
    )
    request, decision = mme_authorization.validate_unsigned_blocked_artifacts(
        WORKSPACE, request_path, decision_path
    )
    assert request["status"] == "DRAFT_UNSIGNED"
    assert len(request["bindings"]["execution_plan"]["blocks"]) == 27
    assert len(request["bindings"]["execution_plan"]["method_panel"]) == 7
    assert decision["blocker_code"] == "BLOCKED_NO_INDEPENDENT_SIGNATURE"
    assert decision["execution_authorized"] is False
    assert not (tmp_path / "MMEExecutionAuthorization.json").exists()


def test_g020_signed_draft_and_production_root_injection_never_authorize(
    tmp_path, monkeypatch
):
    bundle = _test_authorization(tmp_path)
    with pytest.raises(MMEAuthorizationBlocked):
        mme_authorization.assert_mme_authorization_available(
            WORKSPACE,
            bundle["request_path"],
            bundle["request_path"],
            now=bundle["issued"],
        )
    monkeypatch.setenv("RFB_MME_TRUST_ROOT", str(tmp_path / "root.json"))
    monkeypatch.setattr(
        mme_authorization,
        "_installation_admin_root",
        lambda: tmp_path / "missing-admin-root",
    )
    with pytest.raises(
        MMEAuthorizationBlocked, match="EXTERNAL_AUTHORITY_BROKER_UNAVAILABLE"
    ):
        mme_authorization.assert_mme_authorization_available(
            WORKSPACE,
            bundle["request_path"],
            bundle["authorization_path"],
            now=bundle["issued"],
        )


def test_g020_production_admin_loader_uses_fixed_external_layout(tmp_path, monkeypatch):
    request = json.loads(
        (
            WORKSPACE
            / ".omx/handoff/g020-authorization/MMEExecutionAuthorizationRequest.unsigned.json"
        ).read_text(encoding="utf-8")
    )
    bundle = _test_authorization(tmp_path / "fixture", request=request)
    admin_root = tmp_path / "admin-root"
    admin_root.mkdir()
    _write(admin_root / "trust-root.json", bundle["config"]["trust_root"])
    _write(admin_root / "revocations.json", bundle["config"]["crl"])
    (admin_root / "block-issuer-private-key.b64").write_text(
        bundle["config"]["block_issuer_private_key_b64"], encoding="ascii"
    )
    monkeypatch.setattr(
        mme_authorization, "_installation_admin_root", lambda: admin_root
    )
    monkeypatch.setattr(
        mme_authorization,
        "_installation_security_state_root",
        lambda: tmp_path / "security-state",
    )
    monkeypatch.setattr(
        mme_authorization, "_assert_admin_layout_secure", lambda *_args: None
    )
    monkeypatch.setattr(
        mme_authorization, "_assert_security_state_secure", lambda *_args: None
    )
    monkeypatch.setenv("RFB_MME_TRUST_ROOT", str(tmp_path / "ignored.json"))

    loaded = mme_authorization._load_production_admin_configuration()

    assert loaded["trust_root"] == bundle["config"]["trust_root"]
    assert loaded["crl"] == bundle["config"]["crl"]
    assert loaded["state_dir"] == tmp_path / "security-state"
    assert (
        loaded["block_issuer_private_key_b64"]
        == bundle["config"]["block_issuer_private_key_b64"]
    )


def test_g020_offline_package_replaces_expired_request_without_authorizing(
    tmp_path,
):
    old_now = datetime(2026, 8, 28, tzinfo=UTC)
    old_request = mme_authorization.build_unsigned_request(WORKSPACE, now=old_now)
    old_decision = mme_authorization.blocked_decision(old_request, generated_at=old_now)
    _write(tmp_path / "MMEExecutionAuthorizationRequest.unsigned.json", old_request)
    _write(tmp_path / "MMEExecutionAuthorizationDecision.json", old_decision)
    new_now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)

    paths = mme_authorization.write_offline_signing_package(
        WORKSPACE, tmp_path, now=new_now
    )

    request, decision = mme_authorization.validate_unsigned_blocked_artifacts(
        WORKSPACE, paths["request"], paths["decision"]
    )
    manifest = mme_authorization.validate_offline_signing_manifest(
        paths["manifest"], request
    )
    archived = tmp_path / "expired" / old_request["request_id"]
    assert (archived / "MMEExecutionAuthorizationRequest.unsigned.json").is_file()
    assert (archived / "MMEExecutionAuthorizationDecision.json").is_file()
    assert (archived / "InvalidationReceipt.json").is_file()
    assert request["request_id"] != old_request["request_id"]
    assert request["execution_scope"] == {
        "mode": "LOCAL_ONLY",
        "independent_blocks": 27,
        "dataset_split": "D_development",
        "remote_actions": False,
        "formal_writes": False,
        "d_test_access": False,
    }
    assert decision["execution_authorized"] is False
    assert manifest["package_status"] == "UNSIGNED_AWAITING_FOUR_PARTY_MATERIALS"
    assert manifest["contains_private_keys"] is False
    assert manifest["execution_authorized"] is False
    assert not (tmp_path / "MMEExecutionAuthorization.json").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows system directory API")
def test_g020_system_powershell_path_ignores_systemroot(monkeypatch, tmp_path):
    expected = mme_authorization._system_powershell_path()
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    assert mme_authorization._system_powershell_path() == expected


def test_g020_completed_review_record_survives_append_only_ledger_growth(
    tmp_path,
):
    recorded = phase0_qualification._legacy_review_source(WORKSPACE, "G016")
    workspace = tmp_path / "workspace"
    ledger = workspace / recorded["container_path"]
    ledger.parent.mkdir(parents=True)
    source = (WORKSPACE / recorded["container_path"]).read_bytes()
    ledger.write_bytes(source + canonical_bytes({"event": "appended"}) + b"\n")
    assert phase0_qualification._review_source_record_is_still_present(
        workspace, "G016", recorded
    )
    rewritten = bytearray(ledger.read_bytes())
    rewritten[0] ^= 1
    ledger.write_bytes(rewritten)
    assert not phase0_qualification._review_source_record_is_still_present(
        workspace, "G016", recorded
    )


def test_g020_test_only_signed_authorization_uses_distinct_attesters(tmp_path):
    bundle = _test_authorization(tmp_path)
    assert _accept(bundle)["authorization_id"] == bundle["authorization_id"]
    assert not hasattr(mme_authorization, "_CAPABILITY_TOKEN")
    assert not hasattr(
        mme_authorization, "_require_mme_execution_authorization_test_only"
    )
    assert not hasattr(mme_authorization, "_reopen_production_authority")
    altered = copy.deepcopy(bundle["authorization"])
    altered["independent_signature"]["signer_id"] = altered["producer_attestation"][
        "signer_id"
    ]
    _write(bundle["authorization_path"], altered)
    bundle["authorization"] = altered
    with pytest.raises(MMEAuthorizationBlocked):
        _accept(bundle)


def test_g020_weak_key_unsigned_crl_expiry_and_ttl_fail_closed(tmp_path):
    bundle = _test_authorization(tmp_path)
    weak = copy.deepcopy(bundle["config"])
    weak["trust_root"]["keys"][0]["public_key_b64"] = base64.b64encode(
        bytes(32)
    ).decode()
    body = {
        k: v for k, v in weak["trust_root"].items() if k != "trust_root_self_sha256"
    }
    weak["trust_root"] = {**body, "trust_root_self_sha256": _sha(canonical_bytes(body))}
    bundle["config"] = weak
    with pytest.raises(MMEAuthorizationBlocked):
        _accept(bundle)
    bundle = _test_authorization(tmp_path / "unsigned")
    unsigned = copy.deepcopy(bundle["config"])
    unsigned["crl"].pop("signature_b64")
    bundle["config"] = unsigned
    with pytest.raises(MMEAuthorizationBlocked):
        _accept(bundle)
    bundle = _test_authorization(tmp_path / "expired")
    with pytest.raises(MMEAuthorizationBlocked, match="EXPIRED|TIME"):
        _accept(bundle, now=bundle["expires"] + timedelta(seconds=1))


def test_g020_same_public_key_across_roles_is_rejected(tmp_path):
    bundle = _test_authorization(tmp_path)
    trust = copy.deepcopy(bundle["trust"])
    trust["keys"][1]["public_key_b64"] = trust["keys"][0]["public_key_b64"]
    body = {k: v for k, v in trust.items() if k != "trust_root_self_sha256"}
    trust = {**body, "trust_root_self_sha256": _sha(canonical_bytes(body))}
    authorization = _reauthorize(bundle, trust)
    crl_body = {k: v for k, v in bundle["crl"].items() if k != "signature_b64"}
    crl_body["trust_root_sha256"] = _sha(canonical_bytes(trust))
    bundle["config"]["trust_root"] = trust
    bundle["config"]["crl"] = _sign_crl(bundle, crl_body)
    bundle["authorization"] = authorization
    _write(bundle["authorization_path"], authorization)
    with pytest.raises(MMEAuthorizationBlocked, match="KEY_ALIAS"):
        _accept(bundle)


def test_g020_revocation_after_prior_validation_is_rejected(tmp_path):
    bundle = _test_authorization(tmp_path)
    _accept(bundle)
    body = {k: v for k, v in bundle["crl"].items() if k != "signature_b64"}
    body["revoked_key_ids"] = ["approver-key"]
    revoked = _sign_crl(bundle, body)
    bundle["config"]["crl"] = revoked
    with pytest.raises(MMEAuthorizationBlocked, match="REVOKED"):
        _accept(bundle, now=bundle["issued"] + timedelta(seconds=1))


@pytest.mark.parametrize("mutation", ["duplicate", "reorder", "replace"])
def test_g020_exact_27_plan_is_order_and_object_bound(tmp_path, mutation):
    request = _live_request()
    blocks = request["bindings"]["execution_plan"]["blocks"]
    if mutation == "duplicate":
        blocks[1] = copy.deepcopy(blocks[0])
    elif mutation == "reorder":
        blocks[0], blocks[1] = blocks[1], blocks[0]
    else:
        blocks[0] = {**blocks[0], "block_id": "P99"}
    request = _resign_request(request)
    path = tmp_path / "request.json"
    _write(path, request)
    with pytest.raises(MMEAuthorizationBlocked, match="BINDING_DRIFT"):
        mme_authorization.assert_mme_authorization_available(WORKSPACE, path, None)


def test_g020_crl_epoch_chain_and_clock_are_persistent(tmp_path):
    bundle = _test_authorization(tmp_path)
    _accept(bundle)
    next_crl = copy.deepcopy(bundle["crl"])
    next_crl["revocation_epoch"] = 1
    next_crl["previous_revocation_sha256"] = _sha(canonical_bytes(bundle["crl"]))
    body = {k: v for k, v in next_crl.items() if k != "signature_b64"}
    next_crl["signature_b64"] = base64.b64encode(
        bundle["keys"]["admin"].sign(
            canonical_bytes({"domain": "RFB_MME_CRL_V1", **body})
        )
    ).decode()
    bundle["config"]["crl"] = next_crl

    def update(crl, digest, instant):
        try:
            mme_authorization._update_security_state(
                bundle["config"]["state_dir"], crl, digest, instant
            )
        except MMEAuthorizationBlocked as exc:
            return str(exc)
        return "PASS"

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(
                lambda args: update(*args),
                (
                    (
                        bundle["crl"],
                        _sha(canonical_bytes(bundle["crl"])),
                        bundle["issued"],
                    ),
                    (
                        next_crl,
                        _sha(canonical_bytes(next_crl)),
                        bundle["issued"] + timedelta(seconds=1),
                    ),
                ),
            )
        )
    state = json.loads(
        (bundle["config"]["state_dir"] / "security-state.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["highest_crl_epoch"] == 1
    bundle["config"]["crl"] = next_crl
    with pytest.raises(MMEAuthorizationBlocked, match="CLOCK_ROLLBACK"):
        _accept(bundle, now=bundle["issued"])


def test_g020_claims_bind_every_block_attempt_and_checkpoint(tmp_path, monkeypatch):
    bundle = _test_authorization(tmp_path)
    live_bindings = copy.deepcopy(bundle["request"]["bindings"])
    monkeypatch.setattr(
        mme_authorization,
        "_live_bindings",
        lambda _workspace: copy.deepcopy(live_bindings),
    )
    ids = bundle["request"]["bindings"]["execution_plan"]["block_ids"]
    with _admin_fixture(bundle):
        for index, block_id in enumerate(ids):
            claim = _claim_fixture(
                bundle,
                block_id=block_id,
                attempt_id=f"a{index}",
                checkpoint_id=f"c{index}",
            )
            assert claim["recovered"] is False
        assert _claim_fixture(
            bundle,
            block_id=ids[0],
            attempt_id="a0",
            checkpoint_id="c0",
        )["recovered"]
        with pytest.raises(MMEAuthorizationBlocked, match="REPLAY"):
            _claim_fixture(
                bundle,
                block_id=ids[0],
                attempt_id="a0",
                checkpoint_id="changed",
            )
        with pytest.raises(MMEAuthorizationBlocked, match="RESUBMISSION"):
            _claim_fixture(
                bundle,
                block_id=ids[0],
                attempt_id="new",
                checkpoint_id="new",
            )
        with pytest.raises(MMEAuthorizationBlocked, match="CLAIM_INVALID"):
            _claim_fixture(
                bundle,
                block_id="ATTACK_BLOCK",
                attempt_id="attack",
                checkpoint_id="attack",
            )

    race_block = ids[1]
    race_root = tmp_path / "race-claims"

    def race(attempt: str):
        try:
            return _claim_fixture(
                bundle,
                block_id=race_block,
                attempt_id=attempt,
                checkpoint_id=attempt,
            )["attempt_id"]
        except MMEAuthorizationBlocked as exc:
            return str(exc)

    bundle["config"]["state_dir"] = race_root
    with _admin_fixture(bundle), ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(race, ("race-a", "race-b")))
    assert sum(result in {"race-a", "race-b"} for result in results) == 1
    assert (
        sum("CAS_LOST" in result or "RESUBMISSION" in result for result in results) == 1
    )


def test_g020_direct_prepare_worker_and_remote_paths_cannot_bypass(tmp_path):
    manifest_path = tmp_path / "mme.json"
    _write(
        manifest_path,
        {
            "run_id": "FIRST_ROUND",
            "execution_protocol_id": "RFB_MME_V1_EXACT27_LOCAL",
        },
    )
    with pytest.raises(RuntimeError, match="DEDICATED_CONTROLLER"):
        prepare_run(manifest_path, tmp_path / "prepared.json")
    assert not (tmp_path / "prepared.json").exists()
    with pytest.raises(ValueError, match="WORKER_ENTRY_FORBIDDEN"):
        run_worker(manifest_path)
    prepared = PreparedResearchRun(
        {
            "run_id": "FIRST_ROUND",
            "execution_protocol_id": "RFB_MME_V1_EXACT27_LOCAL",
        },
        manifest_path,
        "0" * 64,
    )
    with pytest.raises(RuntimeError, match="REMOTE_FORBIDDEN"):
        execute_remote(prepared)

    missing_protocol = tmp_path / "renamed-first-round.json"
    _write(
        missing_protocol,
        {
            "run_id": "P01",
            "execution_lane": "RESEARCH",
            "classification": "DEVELOPMENT_NONCONFIRMATORY",
            "formal_gate_effect": "NONE",
            "formal_admission_eligible": False,
            "shk001b_eligible": False,
            "contains_formal_claims": False,
            "block_id": "FIRST_ROUND",
        },
    )
    with pytest.raises(ValueError, match="EXECUTION_PROTOCOL_REQUIRED"):
        prepare_run(missing_protocol)
    from rfb.research.controller import prepare_legacy_r006

    with pytest.raises(RuntimeError, match="DEDICATED_CONTROLLER"):
        prepare_legacy_r006(missing_protocol)


def test_g020_signed_claim_cannot_enter_worker_without_external_broker(tmp_path):
    bundle = _test_authorization(tmp_path)
    block_id = bundle["request"]["bindings"]["execution_plan"]["block_ids"][0]
    with _admin_fixture(bundle):
        context = _claim_fixture(
            bundle,
            block_id=block_id,
            attempt_id="e2e-attempt",
            checkpoint_id="e2e-checkpoint",
        )
        with pytest.raises(
            MMEAuthorizationBlocked, match="EXTERNAL_AUTHORITY_BROKER_UNAVAILABLE"
        ):
            mme_authorization.prepare_mme_local_fixture(
                WORKSPACE,
                bundle["request_path"],
                bundle["authorization_path"],
                context,
            )


def test_g020_legacy_authorization_flags_are_not_live_cli_protocol(tmp_path):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rfb.research",
            "mme-run",
            "--workspace",
            str(WORKSPACE),
            "--request",
            str(tmp_path / "old-request.json"),
        ],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unrecognized arguments: --request" in result.stderr


def test_g020_scope_guard_rejects_nonlocal_without_reading_authorization(tmp_path):
    with pytest.raises(ValueError, match="NONLOCAL"):
        guard_mme_controller_entry(
            WORKSPACE,
            operation="REMOTE",
            independent_blocks=27,
            dataset_split="D_development",
        )
