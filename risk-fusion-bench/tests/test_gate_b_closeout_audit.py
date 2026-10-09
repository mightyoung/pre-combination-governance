from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from rfb.archive_qa import ArchiveTarget
from rfb.closeout_audit import (
    CLOSEOUT_FILES,
    copy_closeout_to_local_ab,
    seal_closeout,
    validate_closeout,
)
from rfb.contracts.canonical_json import canonical_bytes, sha256_hex
from rfb.durable_package import seal_durable_package
from rfb.gate_evidence import _fixture_row
from rfb.methods import METHOD_IDS
from rfb.purge import (
    build_purge_plan,
    create_development_purge_capability,
    create_purge_authorization,
    execute_purge,
    freeze_purge_manifest,
    reconcile_purge,
)
from rfb.regeneration import (
    build_regeneration_expectation,
    exact_replay_policy_hash,
    finalize_regeneration_verdict_v2,
    freeze_regeneration_plan_v3,
    panel_commitment,
    payload_commitment,
    verify_regeneration_sample,
    build_regeneration_attestation,
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
    return {
        **body,
        "entry_hash": hashlib.sha256(canonical_bytes(body)).hexdigest(),
    }


def _strict_authority_fixture(tmp_path: Path):
    """Small self-contained runtime authority root for closeout reconstruction."""
    root = tmp_path / "authority"
    gate = root / "outputs" / "runtime_gate"
    source = root / "src" / "rfb"
    gate.mkdir(parents=True)
    source.mkdir(parents=True)
    generator_source = Path(__file__).parents[1] / "src/rfb/regeneration.py"
    generator = source / "regeneration.py"
    shutil.copyfile(generator_source, generator)
    generator_hash = hashlib.sha256(generator.read_bytes()).hexdigest()

    def embedded(name: str, field: str, body: dict[str, object]) -> str:
        value = {**body, field: sha256_hex(canonical_bytes(body))}
        (gate / name).write_text(
            json.dumps(value, separators=(",", ":")), encoding="utf-8"
        )
        return value[field]

    registry = embedded(
        "method_registry.json", "registry_sha256", {"methods": list(METHOD_IDS)}
    )
    container = embedded(
        "container_lock.json", "container_definition_sha256", {"runtime": "fixture"}
    )
    seed = embedded("seed_commitment.json", "seed_commitment_sha256", {"seed": 17})
    allocation = embedded(
        "allocation_commitment.json",
        "allocation_commitment_sha256",
        {"allocation": "fixture"},
    )
    config = root / "segment-config.json"
    config.write_text('{"segment":"seg-1"}', encoding="utf-8")
    config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
    manifest_files = [{"path": "src/rfb/regeneration.py", "sha256": generator_hash}]
    source_manifest = {
        "files": manifest_files,
        "source_tree_sha256": hashlib.sha256(
            canonical_bytes(manifest_files)
        ).hexdigest(),
    }
    (gate / "source_tree_manifest.json").write_text(
        json.dumps(source_manifest, separators=(",", ":")), encoding="utf-8"
    )
    baseline = {
        "code_baseline": {
            "source_tree_manifest": "source_tree_manifest.json",
            "source_tree_sha256": source_manifest["source_tree_sha256"],
        },
        "method_registry": {
            "path": "method_registry.json",
            "registry_sha256": registry,
        },
        "container": {
            "container_lock": "container_lock.json",
            "container_definition_sha256": container,
        },
        "seed_commitment": {"path": "seed_commitment.json", "sha256": seed},
        "allocation_commitment": {
            "path": "allocation_commitment.json",
            "sha256": allocation,
        },
    }
    baseline["runtime_baseline_sha256"] = sha256_hex(canonical_bytes(baseline))
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
        "source_tree_sha256": source_manifest["source_tree_sha256"],
        "generator_path": "src/rfb/regeneration.py",
        "generator_sha256": generator_hash,
        "method_registry_path": "outputs/runtime_gate/method_registry.json",
        "method_registry_sha256": registry,
        "container_lock_path": "outputs/runtime_gate/container_lock.json",
        "container_definition_sha256": container,
        "seed_commitment_path": "outputs/runtime_gate/seed_commitment.json",
        "algorithm_seed_commitment_sha256": seed,
        "allocation_commitment_path": "outputs/runtime_gate/allocation_commitment.json",
        "allocation_commitment_sha256": allocation,
        "segment_config_path": "segment-config.json",
        "segment_config_sha256": config_hash,
    }
    authority["authority_hash"] = sha256_hex(canonical_bytes(authority))
    return root, authority


def _persistable(value):
    if isinstance(value, dict):
        return {k: _persistable(v) for k, v in value.items() if k != "canonical_bytes"}
    if isinstance(value, list):
        return [_persistable(v) for v in value]
    return value


def _result_package(tmp_path: Path) -> Path:
    source = tmp_path / "result-package"
    row = _fixture_row("B0")
    seal_durable_package(
        source,
        [row],
        expected_keys=[
            (row["bundle_id"], row["method_id"], str(row["algorithm_seed"]))
        ],
    )
    return source


def _hashes(source: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((source / name).read_bytes()).hexdigest()
        for name in ("durable_rows.jsonl", "durable_result_manifest.json")
    }


def _regeneration_authorization_evidence(
    tmp_path: Path,
    segment_id: str,
) -> tuple[Path, dict[str, object], dict[str, object], dict[str, object]]:
    authority_root, authority = _strict_authority_fixture(tmp_path)
    bundle_ids = ["bundle-1", "bundle-2"]
    plan = freeze_regeneration_plan_v3(
        segment_id=segment_id,
        bundle_ids=bundle_ids,
        authority=authority,
        replay_policy_hash=exact_replay_policy_hash(),
        sample_selection_seed=17,
        pre_execution_ledger_head=_genesis(segment_id)["entry_hash"],
    )
    event = plan["freeze_event"]
    rows = [_genesis(segment_id), event]
    reports = []
    expectations = []
    for bundle_id in plan["selected_ids"]:
        payload = {"bundle_id": bundle_id, "fixture": "closeout-audit"}
        panel = {
            method_id: {"bundle_id": bundle_id, "method_index": index}
            for index, method_id in enumerate(METHOD_IDS)
        }
        expectation = build_regeneration_expectation(
            plan=plan,
            bundle_id=bundle_id,
            payload_commitment_sha256=payload_commitment(payload),
            expected_panel_commitment_sha256=panel_commitment(panel),
        )
        report = verify_regeneration_sample(
            plan=plan,
            expectation=expectation,
            authority_root=authority_root,
            current_authority=authority,
            freeze_event=event,
            execution_ledger_rows=rows,
            current_bundle_ids=bundle_ids,
            regenerated_payload=dict(payload),
            original_payload=payload,
            original_panel=panel,
            regenerated_panel={key: dict(value) for key, value in panel.items()},
        )
        expectations.append(expectation)
        reports.append(report)
    verdict = finalize_regeneration_verdict_v2(plan, expectations, reports)
    attestation = build_regeneration_attestation(
        plan=plan,
        expectations=expectations,
        reports=reports,
        verdict=verdict,
        freeze_event=event,
        execution_ledger_rows=rows,
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
    evidence = {
        "schema_version": "regeneration-sampling-qa.v3",
        "generated_at": "2026-07-22T00:00:00Z",
        "status": "REGEN_CONSISTENT_UNATTESTED",
        "authoritative": False,
        "development_status": "PASS",
        "live_status": "PENDING",
        "development_only": True,
        "local_live_gate_passed": False,
        "regeneration_verified": True,
        "purge_authorized": False,
        "frozen_before_execution": True,
        "segment_id": segment_id,
        "bundle_count": len(bundle_ids),
        "sample_count": len(plan["selected_ids"]),
        "sample_rule": "max(2,ceil(0.01*N))_without_replacement",
        "selected_bundle_ids": list(plan["selected_ids"]),
        "no_replacement": True,
        "runtime_authority": authority,
        "current_authority": authority,
        "plan": _persistable(plan),
        "freeze_event": event,
        "expectations": _persistable(expectations),
        "sample_reports": _persistable(reports),
        "aggregate_verdict": verdict,
        "execution_ledger_rows": rows,
        "current_bundle_ids": list(plan["bundle_ids"]),
        "regeneration_attestation": attestation,
    }
    return authority_root, authority, evidence, verdict


def _closeout_inputs(tmp_path: Path, source: Path):
    expected = _hashes(source)
    archive_targets = [
        ArchiveTarget(
            "A", str(tmp_path / "result-archive-a"), "domain-a", immutable=True
        ),
        ArchiveTarget(
            "B",
            str(tmp_path / "result-archive-b"),
            "domain-b",
            off_volume=True,
            append_only=True,
        ),
    ]
    for target in archive_targets:
        root = Path(target.root)
        root.mkdir()
        for name in expected:
            shutil.copyfile(source / name, root / name)

    ledger_path = tmp_path / "dataset_purge_ledger.jsonl"
    tombstone_path = tmp_path / "dataset_purge_tombstone.json"
    with tempfile.TemporaryDirectory(prefix="rfb-closeout-fixture-") as temporary:
        dataset = Path(temporary) / "dataset"
        dataset.mkdir()
        (dataset / "ephemeral.bin").write_bytes(b"development fixture")
        frozen = freeze_purge_manifest(
            dataset,
            [{"path": "ephemeral.bin", "kind": "EPHEMERAL_DATASET"}],
            segment_id="seg-1",
        )
        plan = build_purge_plan(dataset, frozen)
        authority_root, authority, regeneration, regeneration_verdict = (
            _regeneration_authorization_evidence(tmp_path, "seg-1")
        )
        regeneration_plan = regeneration["plan"]
        regeneration_plan_runtime = {
            **regeneration_plan,
            "canonical_bytes": canonical_bytes(
                {
                    key: value
                    for key, value in regeneration_plan.items()
                    if key not in {"canonical_bytes", "plan_hash", "freeze_event"}
                }
            ),
        }
        archive_commitment = sha256_hex(canonical_bytes(dict(sorted(expected.items()))))
        attestation = build_regeneration_attestation(
            plan=regeneration_plan_runtime,
            expectations=regeneration["expectations"],
            reports=regeneration["sample_reports"],
            verdict=regeneration["aggregate_verdict"],
            freeze_event=regeneration["freeze_event"],
            execution_ledger_rows=regeneration["execution_ledger_rows"],
            attester=TRUST_STORE,
            independent_key_ids=TRUST_STORE["independent_key_ids"],
            sealed_commitments={
                "result_manifest_hash": expected["durable_result_manifest.json"],
                "archive_a_readback_root": archive_commitment,
                "archive_b_readback_root": archive_commitment,
                "truth_isolation_commitment": sha256_hex(
                    canonical_bytes({"scorer_only": True, "development_only": True})
                ),
                "sealed_package_root": expected["durable_result_manifest.json"],
            },
        )
        # The public regeneration evidence and purge authorization must carry
        # the same attestation bound to this result package's actual artifacts.
        regeneration["regeneration_attestation"] = attestation
        authorization_evidence = {
            "plan": regeneration_plan_runtime,
            "expectations": regeneration["expectations"],
            "reports": regeneration["sample_reports"],
            "verdict": regeneration["aggregate_verdict"],
            "runtime_authority": authority,
            "current_authority": authority,
            "freeze_event": regeneration["freeze_event"],
            "execution_ledger_rows": regeneration["execution_ledger_rows"],
            "current_bundle_ids": regeneration_plan["bundle_ids"],
            "regeneration_attestation": attestation,
        }
        prerequisites = {
            "result_sealed": True,
            "archive_a_verified": True,
            "archive_b_verified": True,
            "truth_isolation_verified": True,
            "truth_isolation_hash": sha256_hex(
                canonical_bytes({"scorer_only": True, "development_only": True})
            ),
            "contains_raw_dataset": False,
            "segment_state": "REGEN_VERIFIED",
            "manifest_hash": plan["manifest_hash"],
            "state_signature": sha256_hex(
                canonical_bytes(
                    {
                        "segment_id": "seg-1",
                        "state": "REGEN_VERIFIED",
                        "verdict_hash": regeneration_verdict["verdict_hash"],
                    }
                )
            ),
            "result_manifest_hash": expected["durable_result_manifest.json"],
            "archive_a_hash": archive_commitment,
            "archive_b_hash": archive_commitment,
            "archive_a_readback_root": archive_commitment,
            "archive_b_readback_root": archive_commitment,
            "truth_isolation_commitment": sha256_hex(
                canonical_bytes({"scorer_only": True, "development_only": True})
            ),
            "sealed_package_root": expected["durable_result_manifest.json"],
            "regeneration_plan": regeneration_plan_runtime,
            "regeneration_verdict": regeneration_verdict,
            "dataset_approval_commitment": sha256_hex(
                canonical_bytes(
                    {
                        "scope": "DEVELOPMENT_FIXTURE_DATASET_APPROVAL",
                        "manifest_hash": plan["manifest_hash"],
                    }
                )
            ),
            "stat_approval_commitment": sha256_hex(
                canonical_bytes(
                    {
                        "scope": "DEVELOPMENT_FIXTURE_STAT_APPROVAL",
                        "verdict_hash": regeneration_verdict["verdict_hash"],
                    }
                )
            ),
            "development_only": True,
        }
        capability = create_development_purge_capability(
            dataset, quiescence_confirmed=True
        )
        authorization = create_purge_authorization(
            prerequisites,
            plan,
            trust_store=TRUST_STORE,
            authority_root=authority_root,
            regeneration_evidence=authorization_evidence,
            development_capability=capability,
        )
        execute_purge(
            plan,
            authorization,
            trust_store=TRUST_STORE,
            dry_run=False,
            ledger_path=ledger_path,
        )
        tombstone = reconcile_purge(
            plan,
            ledger_path,
            tombstone_path,
            archive_targets=archive_targets,
            archive_expected=expected,
            trusted_open_deleted_bytes=0,
            development_only=True,
            space_tolerance_bytes=1_000_000,
        )
    events = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
    ]
    ledger = {
        "schema_version": "dataset-purge-ledger-document.v2",
        "version": 2,
        "development_status": "PASS",
        "live_status": "PENDING",
        "development_only": True,
        "local_live_gate_passed": False,
        "segment_id": "seg-1",
        "plan_hash": plan["plan_hash"],
        "manifest_hash": plan["manifest_hash"],
        "ledger_head": events[-1]["entry_hash"],
        "events": events,
    }
    return expected, regeneration, authorization, ledger, tombstone, authority_root


def test_seal_validate_and_local_ab_readback(tmp_path: Path):
    source = _result_package(tmp_path)
    expected, regeneration, authorization, ledger, tombstone, authority_root = (
        _closeout_inputs(tmp_path, source)
    )
    output = tmp_path / "closeout"
    result = seal_closeout(
        source,
        output,
        segment_id="seg-1",
        archive_expected=expected,
        regeneration=regeneration,
        purge_authorization=authorization,
        purge_ledger=ledger,
        purge_tombstone=tombstone,
        trust_store=TRUST_STORE,
        authority_root=authority_root,
    )
    assert result["pass"] is True
    assert result["semantic_closeout_pass"] is True
    assert set(result["files"]) == set(CLOSEOUT_FILES)
    report = validate_closeout(
        output,
        archive_expected=expected,
        authority_root=authority_root,
        trust_store=TRUST_STORE,
    )
    assert report["pass"] is True
    copied = copy_closeout_to_local_ab(
        output,
        tmp_path / "A",
        tmp_path / "B",
        authority_root=authority_root,
        trust_store=TRUST_STORE,
    )
    assert copied["pass"] is True
    assert copied["local_live_gate_passed"] is False


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
def test_closeout_rejects_rehashed_prerequisite_tamper(tmp_path: Path, key, value):
    source = _result_package(tmp_path)
    expected, regeneration, authorization, ledger, tombstone, authority_root = (
        _closeout_inputs(tmp_path, source)
    )
    output = tmp_path / "closeout"
    seal_closeout(
        source,
        output,
        segment_id="seg-1",
        archive_expected=expected,
        regeneration=regeneration,
        purge_authorization=authorization,
        purge_ledger=ledger,
        purge_tombstone=tombstone,
        trust_store=TRUST_STORE,
        authority_root=authority_root,
    )
    auth_path = output / "purge_authorization.json"
    tampered = json.loads(auth_path.read_text(encoding="utf-8"))
    tampered["prerequisites"][key] = value
    body = {k: v for k, v in tampered.items() if k != "authorization_hash"}
    tampered["authorization_hash"] = sha256_hex(canonical_bytes(body))
    auth_path.write_text(json.dumps(tampered), encoding="utf-8")
    report = validate_closeout(
        output, authority_root=authority_root, trust_store=TRUST_STORE
    )
    assert report["pass"] is False


def test_closeout_rejects_authorization_bound_to_another_purge_plan(tmp_path: Path):
    source = _result_package(tmp_path)
    expected, regeneration, authorization, ledger, tombstone, authority_root = (
        _closeout_inputs(tmp_path, source)
    )
    authorization["plan_hash"] = "f" * 64
    authorization["authorization_hash"] = sha256_hex(
        canonical_bytes(
            {
                key: value
                for key, value in authorization.items()
                if key != "authorization_hash"
            }
        )
    )
    result = seal_closeout(
        source,
        tmp_path / "closeout",
        segment_id="seg-1",
        archive_expected=expected,
        regeneration=regeneration,
        purge_authorization=authorization,
        purge_ledger=ledger,
        purge_tombstone=tombstone,
        trust_store=TRUST_STORE,
        authority_root=authority_root,
    )
    assert result["pass"] is False
    assert any(
        "plan_hash mismatch" in error or "plan hash mismatch" in error
        for error in result["errors"]
    )


def test_closeout_rejects_relative_or_parent_bearing_authority_root(
    tmp_path: Path, monkeypatch
):
    source = _result_package(tmp_path)
    expected, regeneration, authorization, ledger, tombstone, authority_root = (
        _closeout_inputs(tmp_path, source)
    )
    authority_root = Path(authority_root)
    monkeypatch.chdir(authority_root.parent)
    unsafe_roots = (
        Path(authority_root.name),
        authority_root.parent / "unused" / ".." / authority_root.name,
    )
    for index, unsafe_root in enumerate(unsafe_roots):
        result = seal_closeout(
            source,
            tmp_path / f"unsafe-closeout-{index}",
            segment_id="seg-1",
            archive_expected=expected,
            regeneration=regeneration,
            purge_authorization=authorization,
            purge_ledger=ledger,
            purge_tombstone=tombstone,
            authority_root=unsafe_root,
        )
        assert result["pass"] is False
        assert any("absolute normalized" in error for error in result["errors"])


def test_missing_extra_hash_and_raw_result_are_rejected(tmp_path: Path):
    source = _result_package(tmp_path)
    expected, regeneration, authorization, ledger, tombstone, authority_root = (
        _closeout_inputs(tmp_path, source)
    )
    output = tmp_path / "closeout"
    seal_closeout(
        source,
        output,
        segment_id="seg-1",
        archive_expected=expected,
        regeneration=regeneration,
        purge_authorization=authorization,
        purge_ledger=ledger,
        purge_tombstone=tombstone,
        trust_store=TRUST_STORE,
        authority_root=authority_root,
    )
    (output / "dataset_purge_ledger.json").unlink()
    assert validate_closeout(output)["pass"] is False
    (output / "dataset_purge_ledger.json").write_text("{}", encoding="utf-8")
    (output / "extra.json").write_text("{}", encoding="utf-8")
    assert validate_closeout(output)["pass"] is False

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "durable_rows.jsonl").write_text("truth payload", encoding="utf-8")
    (raw / "durable_result_manifest.json").write_text("{}", encoding="utf-8")
    result = seal_closeout(
        raw,
        tmp_path / "bad",
        segment_id="seg-1",
        archive_expected=_hashes(raw),
        regeneration=regeneration,
        purge_authorization=authorization,
        purge_ledger=ledger,
        purge_tombstone=tombstone,
        trust_store=TRUST_STORE,
        authority_root=authority_root,
    )
    assert result["pass"] is False


def test_semantically_pending_closeout_cannot_report_pass(tmp_path: Path):
    source = _result_package(tmp_path)
    result = seal_closeout(
        source,
        tmp_path / "closeout",
        segment_id="seg-1",
        archive_expected=_hashes(source),
    )
    assert result["pass"] is False
    assert result["semantic_closeout_pass"] is False
    assert not (tmp_path / "closeout").exists()


def test_manifest_self_hash_tamper_is_rejected(tmp_path: Path):
    source = _result_package(tmp_path)
    expected, regeneration, authorization, ledger, tombstone, authority_root = (
        _closeout_inputs(tmp_path, source)
    )
    output = tmp_path / "closeout"
    assert (
        seal_closeout(
            source,
            output,
            segment_id="seg-1",
            archive_expected=expected,
            regeneration=regeneration,
            purge_authorization=authorization,
            purge_ledger=ledger,
            purge_tombstone=tombstone,
            trust_store=TRUST_STORE,
            authority_root=authority_root,
        )["pass"]
        is True
    )
    manifest_path = output / "segment_closeout_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["segment_id"] = "changed"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert validate_closeout(output)["pass"] is False


def test_result_package_is_unchanged(tmp_path: Path):
    source = _result_package(tmp_path)
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    expected, regeneration, authorization, ledger, tombstone, authority_root = (
        _closeout_inputs(tmp_path, source)
    )
    seal_closeout(
        source,
        tmp_path / "closeout",
        segment_id="seg-1",
        archive_expected=expected,
        regeneration=regeneration,
        purge_authorization=authorization,
        purge_ledger=ledger,
        purge_tombstone=tombstone,
        trust_store=TRUST_STORE,
        authority_root=authority_root,
    )
    assert before == {path.name: path.read_bytes() for path in source.iterdir()}


def test_signed_commitments_must_match_actual_result_package(tmp_path: Path):
    source = _result_package(tmp_path)
    expected, regeneration, authorization, ledger, tombstone, authority_root = (
        _closeout_inputs(tmp_path, source)
    )
    package_b = tmp_path / "package-b"
    shutil.copytree(source, package_b)
    manifest_path = package_b / "durable_result_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_binding_probe"] = "package-b"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    expected_b = _hashes(package_b)
    result = seal_closeout(
        package_b,
        tmp_path / "mismatched-closeout",
        segment_id="seg-1",
        archive_expected=expected_b,
        regeneration=regeneration,
        purge_authorization=authorization,
        purge_ledger=ledger,
        purge_tombstone=tombstone,
        trust_store=TRUST_STORE,
        authority_root=authority_root,
    )
    assert result["pass"] is False
    assert any("sealed commitments" in error for error in result["errors"])


def test_attestation_builder_rejects_non_independent_key_id(tmp_path: Path):
    source = _result_package(tmp_path)
    _expected, _regeneration, authorization, _ledger, _tombstone, _root = (
        _closeout_inputs(tmp_path, source)
    )
    evidence = authorization["regeneration_evidence"]
    plan = evidence["plan"]
    plan = {
        **plan,
        "canonical_bytes": canonical_bytes(
            {
                key: value
                for key, value in plan.items()
                if key not in {"canonical_bytes", "plan_hash", "freeze_event"}
            }
        ),
    }
    with pytest.raises(ValueError, match="independently identified"):
        build_regeneration_attestation(
            plan=plan,
            expectations=evidence["expectations"],
            reports=evidence["reports"],
            verdict=evidence["verdict"],
            freeze_event=evidence["freeze_event"],
            execution_ledger_rows=evidence["execution_ledger_rows"],
            attester=TRUST_STORE,
            independent_key_ids={"different-key"},
            sealed_commitments={
                "result_manifest_hash": "1" * 64,
                "archive_a_readback_root": "2" * 64,
                "archive_b_readback_root": "3" * 64,
                "truth_isolation_commitment": "4" * 64,
                "sealed_package_root": "5" * 64,
            },
        )
