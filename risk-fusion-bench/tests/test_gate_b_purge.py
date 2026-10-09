from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rfb.contracts.canonical_json import canonical_bytes
from rfb.methods import METHOD_IDS
from rfb.purge import (
    append_purge_ledger,
    build_purge_plan,
    create_development_purge_capability,
    create_purge_authorization,
    execute_purge,
    freeze_purge_manifest,
    reconcile_purge,
)
from rfb.regeneration import (
    build_regeneration_attestation,
    build_regeneration_expectation,
    exact_replay_policy_hash,
    finalize_regeneration_verdict_v2,
    freeze_regeneration_plan_v3,
    panel_commitment,
    payload_commitment,
    verify_regeneration_sample,
)


TRUST_STORE = {
    "key_id": "regen-attester-1",
    "role": "RegenerationAttester",
    "trust_epoch": "dev-1",
    "secret": "development-attester-secret-123",
    "independent_key_ids": ["regen-attester-1"],
}


def _genesis(segment_id: str = "seg-1") -> dict:
    body = {
        "schema_version": "segment-ledger-entry.v1",
        "event": "SEGMENT_PRE_EXECUTION",
        "segment_id": segment_id,
        "state": "PLANNED",
        "prev_hash": "0" * 64,
    }
    return {**body, "entry_hash": hashlib.sha256(canonical_bytes(body)).hexdigest()}


def _write_embedded(gate: Path, name: str, field: str, body: dict) -> str:
    value = {**body, field: hashlib.sha256(canonical_bytes(body)).hexdigest()}
    (gate / name).write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    return value[field]


def _authority_fixture(root: Path) -> dict:
    """Create the complete filesystem-backed v1 runtime authority fixture."""
    gate = root / "outputs" / "runtime_gate"
    source = root / "src" / "rfb"
    gate.mkdir(parents=True)
    source.mkdir(parents=True)
    generator = source / "regeneration.py"
    generator.write_bytes(
        Path(__file__).parents[1].joinpath("src/rfb/regeneration.py").read_bytes()
    )
    generator_hash = hashlib.sha256(generator.read_bytes()).hexdigest()
    registry_hash = _write_embedded(
        gate, "method_registry.json", "registry_sha256", {"methods": list(METHOD_IDS)}
    )
    container_hash = _write_embedded(
        gate,
        "container_lock.json",
        "container_definition_sha256",
        {"runtime": "fixture"},
    )
    seed_hash = _write_embedded(
        gate, "seed_commitment.json", "seed_commitment_sha256", {"seed": 17}
    )
    allocation_hash = _write_embedded(
        gate,
        "allocation_commitment.json",
        "allocation_commitment_sha256",
        {"allocation": "fixture"},
    )
    config = root / "segment-config.json"
    config.write_text('{"segment":"seg-1"}', encoding="utf-8")
    config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
    manifest_files = [{"path": "src/rfb/regeneration.py", "sha256": generator_hash}]
    manifest = {
        "files": manifest_files,
        "source_tree_sha256": hashlib.sha256(
            canonical_bytes(manifest_files)
        ).hexdigest(),
    }
    (gate / "source_tree_manifest.json").write_text(
        json.dumps(manifest, separators=(",", ":")), encoding="utf-8"
    )
    baseline = {
        "code_baseline": {
            "source_tree_manifest": "source_tree_manifest.json",
            "source_tree_sha256": manifest["source_tree_sha256"],
        },
        "method_registry": {
            "path": "method_registry.json",
            "registry_sha256": registry_hash,
        },
        "container": {
            "container_lock": "container_lock.json",
            "container_definition_sha256": container_hash,
        },
        "seed_commitment": {"path": "seed_commitment.json", "sha256": seed_hash},
        "allocation_commitment": {
            "path": "allocation_commitment.json",
            "sha256": allocation_hash,
        },
    }
    baseline["runtime_baseline_sha256"] = hashlib.sha256(
        canonical_bytes(baseline)
    ).hexdigest()
    (gate / "runtime_baseline.json").write_text(
        json.dumps(baseline, separators=(",", ":")), encoding="utf-8"
    )
    authority = {
        "schema_version": "runtime-commitment-authority.v1",
        "development_only": True,
        "live_use_allowed": False,
        "runtime_baseline_path": "outputs/runtime_gate/runtime_baseline.json",
        "runtime_baseline_self_sha256": baseline["runtime_baseline_sha256"],
        "source_tree_manifest_path": "outputs/runtime_gate/source_tree_manifest.json",
        "source_tree_sha256": manifest["source_tree_sha256"],
        "generator_path": "src/rfb/regeneration.py",
        "generator_sha256": generator_hash,
        "method_registry_path": "outputs/runtime_gate/method_registry.json",
        "method_registry_sha256": registry_hash,
        "container_lock_path": "outputs/runtime_gate/container_lock.json",
        "container_definition_sha256": container_hash,
        "seed_commitment_path": "outputs/runtime_gate/seed_commitment.json",
        "algorithm_seed_commitment_sha256": seed_hash,
        "allocation_commitment_path": "outputs/runtime_gate/allocation_commitment.json",
        "allocation_commitment_sha256": allocation_hash,
        "segment_config_path": "segment-config.json",
        "segment_config_sha256": config_hash,
    }
    authority["authority_hash"] = hashlib.sha256(canonical_bytes(authority)).hexdigest()
    return authority


def _plan(root: Path, entries, *, dry_run: bool = True):
    manifest = freeze_purge_manifest(root, entries, segment_id="seg-1")
    return build_purge_plan(root, manifest, dry_run=dry_run)


def _strict_prerequisites(root: Path, plan):
    authority = _authority_fixture(root)
    regeneration_plan = freeze_regeneration_plan_v3(
        segment_id=plan["segment_id"],
        bundle_ids=["bundle-1", "bundle-2"],
        authority=authority,
        replay_policy_hash=exact_replay_policy_hash(),
        sample_selection_seed=17,
        pre_execution_ledger_head=_genesis(plan["segment_id"])["entry_hash"],
    )
    event = regeneration_plan["freeze_event"]
    ledger_rows = [
        _genesis(plan["segment_id"]),
        event,
    ]
    payload = {"x": 1}
    panel = {name: {"score": 1.0} for name in METHOD_IDS}
    expectations = [
        build_regeneration_expectation(
            plan=regeneration_plan,
            bundle_id=bundle_id,
            payload_commitment_sha256=payload_commitment(payload),
            expected_panel_commitment_sha256=panel_commitment(panel),
        )
        for bundle_id in regeneration_plan["selected_ids"]
    ]
    reports = [
        verify_regeneration_sample(
            plan=regeneration_plan,
            expectation=expectation,
            authority_root=root,
            current_authority=authority,
            freeze_event=event,
            execution_ledger_rows=ledger_rows,
            current_bundle_ids=regeneration_plan["bundle_ids"],
            regenerated_payload=payload,
            original_payload=payload,
            original_panel=panel,
            regenerated_panel=panel,
        )
        for expectation in expectations
    ]
    verdict = finalize_regeneration_verdict_v2(regeneration_plan, expectations, reports)
    attestation = build_regeneration_attestation(
        plan=regeneration_plan,
        expectations=expectations,
        reports=reports,
        verdict=verdict,
        freeze_event=event,
        execution_ledger_rows=ledger_rows,
        attester=TRUST_STORE,
        independent_key_ids=TRUST_STORE["independent_key_ids"],
        sealed_commitments={
            "result_manifest_hash": "2" * 64,
            "archive_a_readback_root": "3" * 64,
            "archive_b_readback_root": "4" * 64,
            "truth_isolation_commitment": "9" * 64,
            "sealed_package_root": "a" * 64,
        },
    )
    prerequisites = {
        "result_sealed": True,
        "archive_a_verified": True,
        "archive_b_verified": True,
        "truth_isolation_verified": True,
        "truth_isolation_hash": "9" * 64,
        "contains_raw_dataset": False,
        "segment_state": "REGEN_VERIFIED",
        "manifest_hash": plan["manifest_hash"],
        "state_signature": "1" * 64,
        "result_manifest_hash": "2" * 64,
        "archive_a_hash": "3" * 64,
        "archive_b_hash": "4" * 64,
        "archive_a_readback_root": "3" * 64,
        "archive_b_readback_root": "4" * 64,
        "truth_isolation_commitment": "9" * 64,
        "sealed_package_root": "a" * 64,
        "regeneration_plan": regeneration_plan,
        "regeneration_verdict": verdict,
        "regeneration_attestation": attestation,
        "dataset_approval_commitment": "7" * 64,
        "stat_approval_commitment": "8" * 64,
        "development_only": True,
    }
    evidence = {
        "plan": regeneration_plan,
        "expectations": expectations,
        "reports": reports,
        "verdict": verdict,
        "regeneration_attestation": attestation,
        "runtime_authority": authority,
        "current_authority": authority,
        "freeze_event": event,
        "execution_ledger_rows": ledger_rows,
        "current_bundle_ids": regeneration_plan["bundle_ids"],
    }
    return prerequisites, evidence


def _authorization(root: Path, plan):
    prerequisites, evidence = _strict_prerequisites(root, plan)
    capability = create_development_purge_capability(root, quiescence_confirmed=True)
    return create_purge_authorization(
        prerequisites,
        plan,
        authority_root=root,
        regeneration_evidence=evidence,
        development_capability=capability,
        trust_store=TRUST_STORE,
    )


def test_purge_defaults_to_dry_run_and_requires_strict_prerequisites(tmp_path: Path):
    target = tmp_path / "payload.bin"
    target.write_bytes(b"x")
    plan = _plan(tmp_path, [{"path": "payload.bin", "kind": "EPHEMERAL_DATASET"}])
    result = execute_purge(plan)
    assert result["dry_run"] is True and target.exists()
    assert not (tmp_path / "dataset_purge_ledger.jsonl").exists()
    with pytest.raises((ValueError, PermissionError)):
        create_purge_authorization(
            {"regeneration_verdict": {"regeneration_verified": True}},
            plan,
            authority_root=tmp_path,
            regeneration_evidence={},
            development_capability={},
        )


@pytest.mark.parametrize(
    "path", ["durable.json", "/absolute", r"C:\\x", r"..\\escape", "name:stream"]
)
def test_purge_rejects_non_ephemeral_or_escaping_paths(tmp_path: Path, path: str):
    with pytest.raises(ValueError):
        freeze_purge_manifest(
            tmp_path, [{"path": path, "kind": "EPHEMERAL_DATASET"}], segment_id="seg-1"
        )
    (tmp_path / "x").write_bytes(b"x")
    with pytest.raises(ValueError):
        freeze_purge_manifest(
            tmp_path, [{"path": "x", "kind": "DURABLE_RESULT"}], segment_id="seg-1"
        )


def test_explicit_authorized_purge_unlinks_only_allowlisted_file(tmp_path: Path):
    target = tmp_path / "payload.bin"
    target.write_bytes(b"x")
    durable = tmp_path / "keep.json"
    durable.write_text("keep", encoding="utf-8")
    plan = _plan(tmp_path, [{"path": "payload.bin", "kind": "EPHEMERAL_DATASET"}])
    authorization = _authorization(tmp_path, plan)
    assert (
        authorization["approval_commitment_scope"]
        == "DEVELOPMENT_COMMITMENTS_NOT_AUTHENTIC_LIVE_SIGNATURES"
    )
    result = execute_purge(
        plan,
        authorization,
        trust_store=TRUST_STORE,
        dry_run=False,
        ledger_path=tmp_path / "purge-ledger.jsonl",
    )
    assert result["dry_run"] is False
    assert result["deleted"] == ["payload.bin"]
    assert not target.exists()
    assert durable.read_text(encoding="utf-8") == "keep"


def test_recomputed_authorization_after_regeneration_mutation_is_rejected(
    tmp_path: Path,
):
    target = tmp_path / "payload.bin"
    target.write_bytes(b"x")
    plan = _plan(tmp_path, [{"path": "payload.bin", "kind": "EPHEMERAL_DATASET"}])
    prerequisites, evidence = _strict_prerequisites(tmp_path, plan)
    capability = create_development_purge_capability(
        tmp_path, quiescence_confirmed=True
    )
    evidence["reports"] = list(evidence["reports"])
    evidence["reports"][0] = {
        **evidence["reports"][0],
        "payload_commitment_sha256": "f" * 64,
    }
    with pytest.raises(ValueError):
        create_purge_authorization(
            prerequisites,
            plan,
            authority_root=tmp_path,
            regeneration_evidence=evidence,
            development_capability=capability,
        )
    assert target.exists()


def test_recomputed_authorization_after_approval_mutation_cannot_use_old_hash(
    tmp_path: Path,
):
    target = tmp_path / "payload.bin"
    target.write_bytes(b"x")
    plan = _plan(tmp_path, [{"path": "payload.bin", "kind": "EPHEMERAL_DATASET"}])
    authorization = _authorization(tmp_path, plan)
    authorization["prerequisites"]["dataset_approval_commitment"] = "a" * 64
    authorization["authorization_hash"] = hashlib.sha256(
        canonical_bytes(
            {
                key: authorization[key]
                for key in authorization
                if key != "authorization_hash"
            }
        )
    ).hexdigest()
    with pytest.raises(PermissionError, match="authorization (hash|prerequisite)"):
        execute_purge(plan, authorization, trust_store=TRUST_STORE, dry_run=False)
    assert target.exists()


def test_ledger_rows_are_hash_linked(tmp_path: Path):
    ledger = tmp_path / "purge-ledger.jsonl"
    first = append_purge_ledger(ledger, {"event": "PURGE_INTENT"})
    second = append_purge_ledger(ledger, {"event": "UNLINK", "path": "payload.bin"})
    rows = [
        json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
    ]
    assert rows[1]["prev_hash"] == first["entry_hash"]
    assert second["entry_hash"] == rows[1]["entry_hash"]


def test_reconcile_failure_never_emits_tombstone(tmp_path: Path):
    target = tmp_path / "payload.bin"
    target.write_bytes(b"x")
    plan = _plan(tmp_path, [{"path": "payload.bin", "kind": "EPHEMERAL_DATASET"}])
    tombstone = tmp_path / "tombstone.json"
    result = reconcile_purge(
        plan,
        tmp_path / "missing-ledger.jsonl",
        tombstone,
        archive_targets=[],
        archive_expected={},
        trusted_open_deleted_bytes=0,
        development_only=True,
        space_tolerance_bytes=1_000_000,
    )
    assert result["pass"] is False
    assert not tombstone.exists()
