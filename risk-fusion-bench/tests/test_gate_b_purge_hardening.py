from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from rfb.archive_qa import PACKAGE_FILES, ArchiveTarget
from rfb.contracts.canonical_json import canonical_bytes, sha256_hex
from rfb.durable_package import seal_durable_package
from rfb.gate_evidence import _fixture_row
from rfb.purge import (
    append_purge_ledger,
    build_purge_plan,
    create_development_purge_capability,
    create_purge_authorization,
    execute_purge,
    freeze_purge_manifest,
    reconcile_purge,
)
import rfb.regeneration as regeneration
from rfb.methods import METHOD_IDS
from rfb.regeneration import freeze_regeneration_plan, build_regeneration_attestation


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
    return {
        **body,
        "entry_hash": hashlib.sha256(canonical_bytes(body)).hexdigest(),
    }


def _plan(root: Path, entries, *, dry_run: bool = True):
    manifest = freeze_purge_manifest(root, entries, segment_id="seg-1")
    return build_purge_plan(root, manifest, dry_run=dry_run)


def _strict_authority_fixture(root: Path):
    """Create a self-contained development authority with canonical commitments."""
    gate = root / "outputs" / "runtime_gate"
    source = root / "src" / "rfb"
    gate.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)
    generator = source / "regeneration.py"
    generator.write_bytes(
        Path(__file__).parents[1].joinpath("src/rfb/regeneration.py").read_bytes()
    )
    generator_hash = hashlib.sha256(generator.read_bytes()).hexdigest()

    def write_embedded(name, field, body):
        value = {**body, field: hashlib.sha256(canonical_bytes(body)).hexdigest()}
        (gate / name).write_text(
            json.dumps(value, separators=(",", ":")), encoding="utf-8"
        )
        return value[field]

    registry_hash = write_embedded(
        "method_registry.json", "registry_sha256", {"methods": list(METHOD_IDS)}
    )
    container_hash = write_embedded(
        "container_lock.json", "container_definition_sha256", {"runtime": "fixture"}
    )
    seed_hash = write_embedded(
        "seed_commitment.json", "seed_commitment_sha256", {"seed": 17}
    )
    allocation_hash = write_embedded(
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


def _prerequisites(plan, authority_root: Path, **overrides):
    authority = _strict_authority_fixture(authority_root)
    regeneration_plan = regeneration.freeze_regeneration_plan_v3(
        segment_id=plan["segment_id"],
        bundle_ids=["bundle-1", "bundle-2"],
        authority=authority,
        replay_policy_hash=regeneration.exact_replay_policy_hash(),
        sample_selection_seed=17,
        pre_execution_ledger_head=_genesis(plan["segment_id"])["entry_hash"],
    )
    event = regeneration_plan["freeze_event"]
    ledger_rows = [
        _genesis(plan["segment_id"]),
        event,
    ]
    payload, panel = (
        {"bundle": "fixture"},
        {name: {"score": 1.0} for name in METHOD_IDS},
    )
    expectations = [
        regeneration.build_regeneration_expectation(
            plan=regeneration_plan,
            bundle_id=bundle_id,
            payload_commitment_sha256=regeneration.payload_commitment(payload),
            expected_panel_commitment_sha256=regeneration.panel_commitment(panel),
        )
        for bundle_id in regeneration_plan["selected_ids"]
    ]
    reports = [
        regeneration.verify_regeneration_sample(
            plan=regeneration_plan,
            expectation=expectation,
            authority_root=authority_root,
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
    regeneration_verdict = regeneration.finalize_regeneration_verdict_v2(
        regeneration_plan, expectations, reports
    )
    regeneration_evidence = {
        "plan": regeneration_plan,
        "expectations": expectations,
        "reports": reports,
        "verdict": regeneration_verdict,
        "runtime_authority": authority,
        "current_authority": authority,
        "freeze_event": event,
        "execution_ledger_rows": ledger_rows,
        "current_bundle_ids": regeneration_plan["bundle_ids"],
    }

    attester = {
        "key_id": "regen-attester-1",
        "role": "RegenerationAttester",
        "trust_epoch": "dev-1",
        "secret": "development-attester-secret-123",
        "independent_key_ids": ["regen-attester-1"],
    }
    regeneration_evidence["regeneration_attestation"] = build_regeneration_attestation(
        plan=regeneration_plan,
        expectations=expectations,
        reports=reports,
        verdict=regeneration_verdict,
        freeze_event=event,
        execution_ledger_rows=ledger_rows,
        attester=attester,
        independent_key_ids=TRUST_STORE["independent_key_ids"],
        sealed_commitments={
            "result_manifest_hash": "2" * 64,
            "archive_a_readback_root": "3" * 64,
            "archive_b_readback_root": "4" * 64,
            "truth_isolation_commitment": "9" * 64,
            "sealed_package_root": "a" * 64,
        },
    )

    value = {
        "result_sealed": True,
        "archive_a_verified": True,
        "archive_b_verified": True,
        "truth_isolation_verified": True,
        "truth_isolation_hash": "9" * 64,
        "truth_isolation_commitment": "9" * 64,
        "archive_a_readback_root": "3" * 64,
        "archive_b_readback_root": "4" * 64,
        "sealed_package_root": "a" * 64,
        "contains_raw_dataset": False,
        "segment_state": "REGEN_VERIFIED",
        "manifest_hash": plan["manifest_hash"],
        "state_signature": "1" * 64,
        "result_manifest_hash": "2" * 64,
        "archive_a_hash": "3" * 64,
        "archive_b_hash": "4" * 64,
        "regeneration_plan": regeneration_plan,
        "regeneration_verdict": regeneration_verdict,
        "regeneration_evidence": regeneration_evidence,
        "authority_root": str(authority_root),
        "dataset_approval_commitment": "7" * 64,
        "stat_approval_commitment": "8" * 64,
        "development_only": True,
    }
    value.update(overrides)
    return value


def _authorization(plan, authority_root: Path):
    prerequisites = _prerequisites(plan, authority_root)
    capability = create_development_purge_capability(
        plan["root"], quiescence_confirmed=True
    )
    return create_purge_authorization(
        prerequisites,
        plan,
        authority_root=authority_root,
        regeneration_evidence=prerequisites["regeneration_evidence"],
        development_capability=capability,
        trust_store=TRUST_STORE,
    )


def _symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool = False):
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows account lacks symbolic-link privilege")
        raise


def _archives(tmp_path: Path):
    package = tmp_path / "archive-source"
    row = _fixture_row("B0")
    seal_durable_package(
        package,
        [row],
        expected_keys=[
            (row["bundle_id"], row["method_id"], str(row["algorithm_seed"]))
        ],
    )
    expected = {
        name: sha256_hex((package / name).read_bytes()) for name in PACKAGE_FILES
    }
    targets = [
        ArchiveTarget("A", str(tmp_path / "archive-a"), "domain-a", immutable=True),
        ArchiveTarget(
            "B",
            str(tmp_path / "archive-b"),
            "domain-b",
            off_volume=True,
            append_only=True,
        ),
    ]
    for target in targets:
        root = Path(target.root)
        root.mkdir()
        for name in PACKAGE_FILES:
            (root / name).write_bytes((package / name).read_bytes())
    return targets, expected


def test_default_dry_run_does_not_write_ledger_or_delete(tmp_path: Path):
    target = tmp_path / "x.bin"
    target.write_bytes(b"x")
    plan = _plan(tmp_path, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    result = execute_purge(plan)
    assert result["dry_run"] is True and target.exists()
    assert not (tmp_path / "dataset_purge_ledger.jsonl").exists()


@pytest.mark.parametrize(
    "name",
    [
        "durable-result.json",
        "ledger.jsonl",
        "dataset_purge_tombstone.json",
        "archive-a.bin",
        "archive-b.bin",
    ],
)
def test_manifest_reserved_tokens_are_rejected(tmp_path: Path, name: str):
    (tmp_path / name).write_bytes(b"keep")
    with pytest.raises(ValueError):
        freeze_purge_manifest(
            tmp_path,
            [{"path": name, "kind": "EPHEMERAL_DATASET"}],
            segment_id="seg-1",
        )


def test_manifest_hash_is_computed_and_tamper_evident(tmp_path: Path):
    (tmp_path / "x.bin").write_bytes(b"x")
    manifest = freeze_purge_manifest(
        tmp_path,
        [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}],
        segment_id="seg-1",
    )
    manifest["entries"][0]["kind"] = "TRANSIENT_RUNTIME"
    with pytest.raises(ValueError, match="manifest hash"):
        build_purge_plan(tmp_path, manifest)


def test_plan_rejects_file_identity_or_hash_swap_before_unlink(tmp_path: Path):
    target = tmp_path / "x.bin"
    target.write_bytes(b"x")
    plan = _plan(tmp_path, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    authorization = _authorization(plan, Path(plan["root"]))
    target.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="changed"):
        execute_purge(plan, authorization, trust_store=TRUST_STORE, dry_run=False)
    assert target.exists()


def test_boolean_destructive_authorization_bypass_is_rejected(tmp_path: Path):
    target = tmp_path / "x.bin"
    target.write_bytes(b"x")
    plan = _plan(tmp_path, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    with pytest.raises(PermissionError):
        execute_purge(plan, True, dry_run=False)
    assert target.exists()


def test_destructive_capability_requires_temp_root_and_explicit_quiescence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    with pytest.raises(PermissionError, match="quiescence"):
        create_development_purge_capability(tmp_path)
    alternate_temp = tmp_path / "unrelated-temp-root"
    alternate_temp.mkdir()
    monkeypatch.setattr("rfb.purge.tempfile.gettempdir", lambda: str(alternate_temp))
    with pytest.raises(PermissionError, match="OS temp"):
        create_development_purge_capability(tmp_path, quiescence_confirmed=True)


def test_authorization_tamper_and_missing_marker_fail_before_unlink(tmp_path: Path):
    target = tmp_path / "x.bin"
    target.write_bytes(b"x")
    plan = _plan(tmp_path, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    authorization = _authorization(plan, Path(plan["root"]))
    authorization["dataset_approval_commitment"] = "9" * 64
    with pytest.raises(PermissionError, match="authorization hash"):
        execute_purge(plan, authorization, trust_store=TRUST_STORE, dry_run=False)
    assert target.exists()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("result_sealed", False),
        ("archive_a_verified", False),
        ("archive_b_verified", False),
        ("truth_isolation_verified", False),
        ("contains_raw_dataset", True),
        ("segment_state", "PURGED"),
    ],
)
def test_rehashed_prerequisite_tamper_is_reconstructed_before_unlink(
    tmp_path: Path, key, value
):
    target = tmp_path / "x.bin"
    target.write_bytes(b"x")
    plan = _plan(tmp_path, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    authorization = _authorization(plan, Path(plan["root"]))
    authorization["prerequisites"][key] = value
    body = {k: v for k, v in authorization.items() if k != "authorization_hash"}
    authorization["authorization_hash"] = sha256_hex(canonical_bytes(body))
    with pytest.raises(PermissionError, match="reconstruct|prerequisite"):
        execute_purge(plan, authorization, trust_store=TRUST_STORE, dry_run=False)
    assert target.exists()


def test_rehashed_capability_marker_tamper_fails_closed(tmp_path: Path):
    target = tmp_path / "x.bin"
    target.write_bytes(b"x")
    plan = _plan(tmp_path, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    authorization = _authorization(plan, Path(plan["root"]))
    marker = Path(plan["root"]) / authorization["development_capability"]["marker"]
    body = json.loads(marker.read_text(encoding="utf-8"))
    body["root"] = str(tmp_path.parent)
    body["marker_hash"] = sha256_hex(
        canonical_bytes(
            {key: value for key, value in body.items() if key != "marker_hash"}
        )
    )
    marker.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(PermissionError, match="marker|root identity|hash"):
        execute_purge(plan, authorization, trust_store=TRUST_STORE, dry_run=False)
    assert target.exists()


def test_authorization_requires_full_strict_regeneration_evidence(tmp_path: Path):
    target = tmp_path / "x.bin"
    target.write_bytes(b"x")
    plan = _plan(tmp_path, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    capability = create_development_purge_capability(
        plan["root"], quiescence_confirmed=True
    )
    prerequisites = _prerequisites(plan, Path(plan["root"]))
    with pytest.raises(ValueError, match="strict regeneration"):
        create_purge_authorization(
            prerequisites,
            plan,
            authority_root=Path(plan["root"]),
            regeneration_evidence={},
            development_capability=capability,
        )


@pytest.mark.parametrize("missing", ["current_authority", "current_bundle_ids"])
def test_authorization_rejects_missing_strict_execution_inputs(
    tmp_path: Path, missing: str
):
    target = tmp_path / "x.bin"
    target.write_bytes(b"x")
    plan = _plan(tmp_path, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    capability = create_development_purge_capability(
        plan["root"], quiescence_confirmed=True
    )
    prerequisites = _prerequisites(plan, Path(plan["root"]))
    evidence = dict(prerequisites["regeneration_evidence"])
    evidence.pop(missing)
    with pytest.raises(ValueError, match="strict current authority"):
        create_purge_authorization(
            prerequisites,
            plan,
            authority_root=Path(plan["root"]),
            regeneration_evidence=evidence,
            development_capability=capability,
        )


def test_compatibility_regeneration_plan_cannot_authorize_purge(tmp_path: Path):
    target = tmp_path / "x.bin"
    target.write_bytes(b"x")
    plan = _plan(tmp_path, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    capability = create_development_purge_capability(
        plan["root"], quiescence_confirmed=True
    )
    prerequisites = _prerequisites(plan, Path(plan["root"]))
    legacy = freeze_regeneration_plan(
        segment_id=plan["segment_id"], bundle_ids=["bundle-1", "bundle-2"], seed=17
    )
    compatibility_evidence = {
        "plan": legacy,
        "expectations": [],
        "reports": [],
        "verdict": prerequisites["regeneration_verdict"],
    }
    prerequisites["regeneration_plan"] = legacy
    with pytest.raises(ValueError, match="compatibility"):
        create_purge_authorization(
            prerequisites,
            plan,
            authority_root=Path(plan["root"]),
            regeneration_evidence=compatibility_evidence,
            development_capability=capability,
        )

    authorization = _authorization(plan, Path(plan["root"]))
    (Path(plan["root"]) / authorization["development_capability"]["marker"]).unlink()
    with pytest.raises(PermissionError, match="marker"):
        execute_purge(plan, authorization, trust_store=TRUST_STORE, dry_run=False)
    assert target.exists()


def test_exclusive_execution_lock_blocks_concurrent_purge(tmp_path: Path):
    target = tmp_path / "x.bin"
    target.write_bytes(b"x")
    plan = _plan(tmp_path, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    authorization = _authorization(plan, Path(plan["root"]))
    lock = tmp_path / ".rfb-purge-execution.lock"
    lock.write_text("other-writer", encoding="ascii")
    with pytest.raises(RuntimeError, match="locked"):
        execute_purge(plan, authorization, trust_store=TRUST_STORE, dry_run=False)
    assert target.exists()
    lock.unlink()


def test_root_identity_swap_fails_closed(tmp_path: Path):
    root = tmp_path / "dataset"
    root.mkdir()
    target = root / "x.bin"
    target.write_bytes(b"x")
    plan = _plan(root, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    authorization = _authorization(plan, Path(plan["root"]))
    moved = tmp_path / "dataset-original"
    root.rename(moved)
    root.mkdir()
    (root / "x.bin").write_bytes(b"replacement")
    with pytest.raises(ValueError, match="root identity"):
        execute_purge(plan, authorization, trust_store=TRUST_STORE, dry_run=False)
    assert (root / "x.bin").exists()
    assert (moved / "x.bin").exists()


def test_plan_rejects_broken_symlink_and_ancestor_symlink(tmp_path: Path):
    _symlink_or_skip(tmp_path / "broken", tmp_path / "missing")
    with pytest.raises(ValueError):
        freeze_purge_manifest(
            tmp_path,
            [{"path": "broken", "kind": "EPHEMERAL_DATASET"}],
            segment_id="seg-1",
        )
    child = tmp_path / "child"
    child.mkdir()
    _symlink_or_skip(tmp_path / "alias", child, target_is_directory=True)
    (child / "x").write_bytes(b"x")
    with pytest.raises(ValueError):
        freeze_purge_manifest(
            tmp_path,
            [{"path": "alias/x", "kind": "EPHEMERAL_DATASET"}],
            segment_id="seg-1",
        )


def test_root_identity_or_plan_hash_change_is_rejected(tmp_path: Path):
    (tmp_path / "x.bin").write_bytes(b"x")
    plan = _plan(tmp_path, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    plan["root_lstat"]["ino"] += 1
    with pytest.raises(ValueError, match="plan hash"):
        execute_purge(plan)


def test_corrupt_ledger_fails_closed(tmp_path: Path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text('{"event":"BAD"}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        append_purge_ledger(ledger, {"event": "PURGE_INTENT"})


def test_purge_records_intent_unlink_and_commit_and_is_idempotent(tmp_path: Path):
    target = tmp_path / "x.bin"
    target.write_bytes(b"x")
    outside = tmp_path.parent / "purge-outside-sentinel.bin"
    outside.write_bytes(b"must remain")
    ledger = tmp_path / "purge-ledger.jsonl"
    plan = _plan(tmp_path, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    authorization = _authorization(plan, Path(plan["root"]))
    execute_purge(
        plan, authorization, trust_store=TRUST_STORE, dry_run=False, ledger_path=ledger
    )
    events = [
        json.loads(line)["event"]
        for line in ledger.read_text(encoding="utf-8").splitlines()
    ]
    assert events == ["PURGE_INTENT", "UNLINK_INTENT", "UNLINK", "PURGE_COMMITTED"]
    before = ledger.read_bytes()
    assert (
        execute_purge(
            plan,
            authorization,
            trust_store=TRUST_STORE,
            dry_run=False,
            ledger_path=ledger,
        )["deleted"]
        == []
    )
    assert ledger.read_bytes() == before
    assert outside.read_bytes() == b"must remain"
    outside.unlink()


def test_missing_after_fsynced_unlink_intent_is_recovered(tmp_path: Path):
    target = tmp_path / "x.bin"
    target.write_bytes(b"x")
    ledger = tmp_path / "purge-ledger.jsonl"
    plan = _plan(tmp_path, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    authorization = _authorization(plan, Path(plan["root"]))
    operation_id = sha256_hex(
        canonical_bytes(
            {
                "authorization_hash": authorization["authorization_hash"],
                "plan_hash": plan["plan_hash"],
            }
        )
    )
    append_purge_ledger(
        ledger,
        {
            "event": "PURGE_INTENT",
            "operation_id": operation_id,
            "plan_hash": plan["plan_hash"],
            "manifest_hash": plan["manifest_hash"],
            "authorization_hash": authorization["authorization_hash"],
            "development_only": True,
        },
    )
    append_purge_ledger(
        ledger,
        {
            "event": "UNLINK_INTENT",
            "operation_id": operation_id,
            "path": "x.bin",
            "expected_lstat": plan["entries"][0]["lstat"],
            "plan_hash": plan["plan_hash"],
        },
    )
    target.unlink()
    result = execute_purge(
        plan, authorization, trust_store=TRUST_STORE, dry_run=False, ledger_path=ledger
    )
    assert result["remaining"] == 0
    rows = [
        json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
    ]
    recovered = next(row for row in rows if row["event"] == "UNLINK")
    assert recovered["recovered_missing_after_intent"] is True


def test_reconcile_collects_residual_archive_and_space_evidence(tmp_path: Path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "x.bin").write_bytes(b"x" * 4096)
    plan = _plan(dataset, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    authorization = _authorization(plan, Path(plan["root"]))
    ledger = tmp_path / "purge-ledger.jsonl"
    execute_purge(
        plan, authorization, trust_store=TRUST_STORE, dry_run=False, ledger_path=ledger
    )
    targets, expected = _archives(tmp_path)
    tombstone = tmp_path / "tombstone.json"
    result = reconcile_purge(
        plan,
        ledger,
        tombstone,
        archive_targets=targets,
        archive_expected=expected,
        trusted_open_deleted_bytes=0,
        development_only=True,
        space_tolerance_bytes=1_000_000,
    )
    assert result["pass"] is True
    assert result["ephemeral_files_remaining"] == 0
    assert result["open_deleted_bytes"] == 0
    assert result["unexplained_delta"] == 0
    assert result["local_live_gate_passed"] is False
    assert tombstone.is_file()


def test_reconcile_failure_does_not_emit_tombstone(tmp_path: Path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "x.bin").write_bytes(b"x")
    plan = _plan(dataset, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    tombstone = tmp_path / "tombstone.json"
    targets, expected = _archives(tmp_path)
    result = reconcile_purge(
        plan,
        tmp_path / "missing-ledger.jsonl",
        tombstone,
        archive_targets=targets,
        archive_expected=expected,
        trusted_open_deleted_bytes=0,
        development_only=True,
        space_tolerance_bytes=1_000_000,
    )
    assert result["pass"] is False
    assert not tombstone.exists()


def test_independent_regeneration_attestation_tamper_fails_closed(tmp_path: Path):
    target = tmp_path / "x.bin"
    target.write_bytes(b"x")
    plan = _plan(tmp_path, [{"path": "x.bin", "kind": "EPHEMERAL_DATASET"}])
    prerequisites = _prerequisites(plan, Path(plan["root"]))
    evidence = dict(prerequisites["regeneration_evidence"])
    forged = dict(evidence["regeneration_attestation"])
    forged["signature"] = "0" * 64
    evidence["regeneration_attestation"] = forged
    with pytest.raises(ValueError, match="attestation"):
        create_purge_authorization(
            {**prerequisites},
            plan,
            authority_root=Path(plan["root"]),
            regeneration_evidence=evidence,
            trust_store=TRUST_STORE,
            development_capability=create_development_purge_capability(
                plan["root"], quiescence_confirmed=True
            ),
        )
