from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

import rfb.regeneration as regeneration
from rfb.methods import METHOD_IDS
from rfb.contracts.canonical_json import canonical_bytes


def _panel(score: float = 1.0):
    return {name: {"score": score} for name in METHOD_IDS}


def _genesis(segment_id: str = "seg-1") -> dict:
    body = {
        "schema_version": "segment-ledger-entry.v1",
        "event": "SEGMENT_PRE_EXECUTION",
        "segment_id": segment_id,
        "state": "PLANNED",
        "prev_hash": "0" * 64,
    }
    return {**body, "entry_hash": hashlib.sha256(canonical_bytes(body)).hexdigest()}


def _strict_fixture(tmp_path: Path):
    """Build a small authority-root fixture with canonical self-hashes."""
    root = tmp_path
    gate = root / "outputs" / "runtime_gate"
    source = root / "src" / "rfb"
    gate.mkdir(parents=True)
    source.mkdir(parents=True)
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
    return root, authority


@pytest.mark.parametrize("seed", [True, -1])
def test_frozen_sample_selection_rejects_boolean_or_negative_seed(seed):
    with pytest.raises(ValueError):
        regeneration.select_frozen_samples(["b-1", "b-2"], seed=seed)


def test_frozen_sample_selection_rejects_empty_segment_identifier():
    with pytest.raises(ValueError):
        regeneration.select_frozen_samples(["b-1", "b-2"], seed=7, segment_id="")


def test_freeze_plan_is_order_stable_and_records_all_commitments():
    commitments = {
        "method_registry_hash": "1" * 64,
        "generator_hash": "2" * 64,
        "config_hash": "3" * 64,
        "container_hash": "4" * 64,
    }
    first = regeneration.freeze_regeneration_plan(
        segment_id="seg-1", bundle_ids=["b-2", "b-1"], seed=7, **commitments
    )
    second = regeneration.freeze_regeneration_plan(
        segment_id="seg-1", bundle_ids=["b-1", "b-2"], seed=7, **commitments
    )
    assert first == second
    assert first["plan_hash"] == hashlib.sha256(first["canonical_bytes"]).hexdigest()
    assert first["sample_count"] == 2
    assert first["frozen_before_execution"] is True


def test_freeze_plan_defaults_replay_policy_hash_when_omitted_or_none():
    omitted = regeneration.freeze_regeneration_plan(
        segment_id="seg-1", bundle_ids=["b-1", "b-2"], seed=7
    )
    explicit_none = regeneration.freeze_regeneration_plan(
        segment_id="seg-1",
        bundle_ids=["b-1", "b-2"],
        seed=7,
        replay_policy_hash=None,
    )
    expected = regeneration.exact_replay_policy_hash()
    assert omitted["replay_policy_hash"] == expected
    assert explicit_none["replay_policy_hash"] == expected


def test_freeze_plan_preserves_valid_supplied_replay_policy_hash():
    supplied = "a" * 64
    plan = regeneration.freeze_regeneration_plan(
        segment_id="seg-1",
        bundle_ids=["b-1", "b-2"],
        seed=7,
        replay_policy_hash=supplied,
    )
    assert plan["replay_policy_hash"] == supplied


def test_freeze_plan_rejects_empty_replay_policy_hash():
    with pytest.raises(ValueError, match="replay_policy_hash"):
        regeneration.freeze_regeneration_plan(
            segment_id="seg-1",
            bundle_ids=["b-1", "b-2"],
            seed=7,
            replay_policy_hash="",
        )


def test_frozen_plan_binds_authoritative_execution_inputs():
    bundles = ["b-1", "b-2"]
    plan = regeneration.freeze_regeneration_plan(
        segment_id="seg-1", bundle_ids=bundles, seed=7
    )
    bundles.append("b-3")
    assert plan["bundle_ids"] == ["b-1", "b-2"]
    with pytest.raises(ValueError, match="bundle inputs changed"):
        regeneration.execute_regeneration_plan(
            plan,
            current_bundle_ids=bundles,
            segment_id="seg-1",
            seed=7,
        )
    assert (
        regeneration.execute_regeneration_plan(
            plan,
            current_bundle_ids=["b-1", "b-2"],
            segment_id="seg-1",
            seed=7,
        )
        == plan["selected_ids"]
    )


def test_plan_tampering_is_rejected():
    plan = regeneration.freeze_regeneration_plan(
        segment_id="seg-1", bundle_ids=["b-1", "b-2"], seed=7
    )
    plan["selected_ids"] = list(reversed(plan["selected_ids"]))
    with pytest.raises(ValueError, match="plan hash"):
        regeneration.execute_regeneration_plan(
            plan,
            current_bundle_ids=["b-1", "b-2"],
            segment_id="seg-1",
            seed=7,
        )


def test_payload_commitment_uses_domain_separation_from_bare_sha256():
    assert (
        regeneration.payload_commitment(b"payload")
        != hashlib.sha256(b"payload").hexdigest()
    )


def test_exact_panel_equality_is_not_affected_by_shared_object_identity():
    row = {"result_sha256": "x"}
    panel = {name: row for name in METHOD_IDS}
    assert regeneration.compare_full_panel_replay(panel, panel.copy()) is True


@pytest.mark.parametrize(
    "policy",
    [
        {"signed": False, "paths": {"B0.score": 0.1}},
        {"signed": True, "paths": {"B0.score": 0.1}},
        {"signed": True, "paths": {"B0.score": 0.1}, "hash": "0" * 64},
        {"signed": True, "paths": {"../B0.score": 0.1}, "signature": "s"},
        {"signed": True, "paths": {"B0.score": math.nan}, "signature": "s"},
    ],
)
def test_tolerance_policy_fails_closed_without_valid_commitment(policy):
    assert (
        regeneration.compare_full_panel_replay(_panel(), _panel(1.0001), policy)
        is False
    )


def test_prespecified_tolerance_is_bound_to_frozen_plan():
    tolerance = regeneration.build_tolerance_policy(
        {"B0.score": {"abs": 0.01, "rel": 0.0}}
    )
    plan = regeneration.freeze_regeneration_plan(
        segment_id="seg-1",
        bundle_ids=["b-1", "b-2"],
        seed=7,
        method_registry_hash="1" * 64,
        replay_policy_hash=tolerance["hash"],
    )
    expected = _panel()
    replay = _panel()
    replay["B0"]["score"] = 1.005
    report = regeneration.verify_regeneration(
        plan=plan,
        current_bundle_ids=["b-1", "b-2"],
        bundle_id=plan["selected_ids"][0],
        expected_payload_commitment_sha256=regeneration.payload_commitment({"x": 1}),
        regenerated_payload={"x": 1},
        original_payload={"x": 1},
        original_panel=expected,
        expected_panel_commitment_sha256=regeneration.panel_commitment(expected),
        regenerated_panel=replay,
        method_registry_hash="1" * 64,
        tolerance_policy=tolerance,
    )
    assert report["status"] == "REGEN_VERIFIED"
    changed_policy = regeneration.build_tolerance_policy({"B0.score": 0.1})
    changed = regeneration.verify_regeneration(
        plan=plan,
        current_bundle_ids=["b-1", "b-2"],
        bundle_id=plan["selected_ids"][0],
        expected_payload_commitment_sha256=regeneration.payload_commitment({"x": 1}),
        regenerated_payload={"x": 1},
        original_panel=expected,
        expected_panel_commitment_sha256=regeneration.panel_commitment(expected),
        regenerated_panel=replay,
        method_registry_hash="1" * 64,
        tolerance_policy=changed_policy,
    )
    assert changed["status"] == regeneration.INVALID_STATUS


def test_replacement_sample_cannot_be_verified():
    plan = regeneration.freeze_regeneration_plan(
        segment_id="seg-1", bundle_ids=["b-1", "b-2", "b-3"], seed=7
    )
    replacement = next(
        item for item in plan["bundle_ids"] if item not in plan["selected_ids"]
    )
    panel = _panel()
    result = regeneration.verify_regeneration(
        plan=plan,
        current_bundle_ids=plan["bundle_ids"],
        bundle_id=replacement,
        expected_payload_commitment_sha256=regeneration.payload_commitment(b"x"),
        regenerated_payload=b"x",
        original_panel=panel,
        expected_panel_commitment_sha256=regeneration.panel_commitment(panel),
        regenerated_panel=panel,
        method_registry_hash="",
    )
    assert result["status"] == regeneration.INVALID_STATUS
    assert result["dataset_retained"] is True


def test_successful_regeneration_has_contract_status_and_never_authorizes_purge():
    plan = regeneration.freeze_regeneration_plan(
        segment_id="seg-1", bundle_ids=["b-1", "b-2"], seed=7
    )
    panel = {name: {"result_sha256": name} for name in METHOD_IDS}
    result = regeneration.verify_regeneration(
        plan=plan,
        current_bundle_ids=plan["bundle_ids"],
        bundle_id=plan["selected_ids"][0],
        expected_payload_commitment_sha256=regeneration.payload_commitment({"x": 1}),
        regenerated_payload={"x": 1},
        original_payload={"x": 1},
        original_panel=panel,
        expected_panel_commitment_sha256=regeneration.panel_commitment(panel),
        regenerated_panel={key: dict(value) for key, value in panel.items()},
        method_registry_hash="",
    )
    assert result["status"] == "REGEN_VERIFIED"
    assert result["purge_authorized"] is False
    assert result["next_segment_allowed"] is False


def test_aggregate_verdict_requires_exact_frozen_sample_set_and_validates_hash():
    plan = regeneration.freeze_regeneration_plan(
        segment_id="seg-1", bundle_ids=["b-1", "b-2", "b-3"], seed=7
    )
    panel = _panel()
    reports = [
        regeneration.verify_regeneration(
            plan=plan,
            current_bundle_ids=plan["bundle_ids"],
            bundle_id=bundle_id,
            expected_payload_commitment_sha256=regeneration.payload_commitment(
                {"x": bundle_id}
            ),
            regenerated_payload={"x": bundle_id},
            original_payload={"x": bundle_id},
            original_panel=panel,
            expected_panel_commitment_sha256=regeneration.panel_commitment(panel),
            regenerated_panel=panel,
            method_registry_hash="",
        )
        for bundle_id in plan["selected_ids"]
    ]
    verdict = regeneration.finalize_regeneration_verdict(plan, reports)
    assert verdict["fixture_purge_authorized"] is True
    assert verdict["purge_authorized"] is False
    assert (
        regeneration.validate_regeneration_verdict(plan, verdict)["verdict_hash"]
        == verdict["verdict_hash"]
    )
    tampered = dict(verdict)
    tampered["sample_commitments"] = list(reversed(verdict["sample_commitments"]))
    with pytest.raises(ValueError, match="verdict hash"):
        regeneration.validate_regeneration_verdict(plan, tampered)


def test_aggregate_failure_latches_stop_and_rejects_missing_or_replacement():
    plan = regeneration.freeze_regeneration_plan(
        segment_id="seg-1", bundle_ids=["b-1", "b-2", "b-3"], seed=7
    )
    panel = _panel()
    good = regeneration.verify_regeneration(
        plan=plan,
        current_bundle_ids=plan["bundle_ids"],
        bundle_id=plan["selected_ids"][0],
        expected_payload_commitment_sha256=regeneration.payload_commitment(b"x"),
        regenerated_payload=b"x",
        original_panel=panel,
        expected_panel_commitment_sha256=regeneration.panel_commitment(panel),
        regenerated_panel=panel,
        method_registry_hash="",
    )
    bad = dict(
        good,
        bundle_id=plan["selected_ids"][1],
        status=regeneration.INVALID_STATUS,
        regeneration_verified=False,
        full_panel_replay_match=False,
    )
    verdict = regeneration.finalize_regeneration_verdict(plan, [good, bad])
    assert verdict["status"] == regeneration.INVALID_STATUS
    assert verdict["next_segment_allowed"] is False
    with pytest.raises(ValueError, match="every selected bundle"):
        regeneration.finalize_regeneration_verdict(plan, [good])


def test_strict_v3_reloads_authority_and_reconstructs_report_and_verdict(tmp_path):
    root, authority = _strict_fixture(tmp_path)
    plan = regeneration.freeze_regeneration_plan_v3(
        segment_id="seg-1",
        bundle_ids=["b-1", "b-2"],
        authority=authority,
        replay_policy_hash=regeneration.exact_replay_policy_hash(),
        sample_selection_seed=17,
        pre_execution_ledger_head=_genesis()["entry_hash"],
    )
    event = plan["freeze_event"]
    rows = [_genesis(), event]
    payload = {"x": 1}
    panel = _panel()
    expectations = [
        regeneration.build_regeneration_expectation(
            plan=plan,
            bundle_id=bundle_id,
            payload_commitment_sha256=regeneration.payload_commitment(payload),
            expected_panel_commitment_sha256=regeneration.panel_commitment(panel),
        )
        for bundle_id in plan["selected_ids"]
    ]
    reports = [
        regeneration.verify_regeneration_sample(
            plan=plan,
            expectation=expectation,
            authority_root=root,
            current_authority=authority,
            freeze_event=event,
            execution_ledger_rows=rows,
            current_bundle_ids=["b-1", "b-2"],
            regenerated_payload=payload,
            original_payload=payload,
            original_panel=panel,
            regenerated_panel=panel,
        )
        for expectation in expectations
    ]
    assert all(report["status"] == regeneration.PASS_STATUS for report in reports)
    verdict = regeneration.finalize_regeneration_verdict_v2(plan, expectations, reports)
    assert verdict["regeneration_verified"] is True


def test_strict_report_rejects_rehashed_forgery_and_exact_closure(tmp_path):
    root, authority = _strict_fixture(tmp_path)
    plan = regeneration.freeze_regeneration_plan_v3(
        segment_id="seg-1",
        bundle_ids=["b-1", "b-2", "b-3"],
        authority=authority,
        replay_policy_hash=regeneration.exact_replay_policy_hash(),
        sample_selection_seed=17,
        pre_execution_ledger_head=_genesis()["entry_hash"],
    )
    event = plan["freeze_event"]
    rows = [_genesis(), event]
    payload = {"x": 1}
    panel = _panel()
    expectations = [
        regeneration.build_regeneration_expectation(
            plan=plan,
            bundle_id=bundle,
            payload_commitment_sha256=regeneration.payload_commitment(payload),
            expected_panel_commitment_sha256=regeneration.panel_commitment(panel),
        )
        for bundle in plan["selected_ids"]
    ]
    reports = [
        regeneration.verify_regeneration_sample(
            plan=plan,
            expectation=exp,
            authority_root=root,
            current_authority=authority,
            freeze_event=event,
            execution_ledger_rows=rows,
            current_bundle_ids=plan["bundle_ids"],
            regenerated_payload=payload,
            original_payload=payload,
            original_panel=panel,
            regenerated_panel=panel,
        )
        for exp in expectations
    ]
    forged = dict(reports[0])
    forged["regeneration_verified"] = False
    forged["report_hash"] = hashlib.sha256(
        canonical_bytes({k: forged[k] for k in forged if k != "report_hash"})
    ).hexdigest()
    with pytest.raises(ValueError, match="status or booleans"):
        regeneration.validate_regeneration_sample_report(
            forged, expectation=expectations[0], plan=plan
        )
    substituted = dict(reports[0])
    substituted.update(
        {
            "plan_hash": "a" * 64,
            "authority_hash": "b" * 64,
            "payload_commitment_sha256": "c" * 64,
            "regenerated_payload_commitment_sha256": "c" * 64,
            "expected_panel_commitment_sha256": "d" * 64,
            "observed_panel_commitment_sha256": "d" * 64,
            "regenerated_panel_commitment_sha256": "d" * 64,
            "payload_commitment_match": True,
            "expected_panel_commitment_match": True,
            "full_panel_replay_match": True,
            "regeneration_verified": True,
            "status": regeneration.PASS_STATUS,
        }
    )
    substituted["report_hash"] = hashlib.sha256(
        canonical_bytes(
            {key: value for key, value in substituted.items() if key != "report_hash"}
        )
    ).hexdigest()
    with pytest.raises(
        ValueError, match="(plan_hash|authority_hash|authority binding)"
    ):
        regeneration.validate_regeneration_sample_report(
            substituted, expectation=expectations[0], plan=plan
        )
    with pytest.raises(ValueError, match="every selected"):
        regeneration.finalize_regeneration_verdict_v2(
            plan, expectations[:-1], reports[:-1]
        )


def test_strict_execution_rejects_missing_or_synthetic_authority(tmp_path):
    root, authority = _strict_fixture(tmp_path)
    plan = regeneration.freeze_regeneration_plan_v3(
        segment_id="seg-1",
        bundle_ids=["b-1", "b-2"],
        authority=authority,
        replay_policy_hash=regeneration.exact_replay_policy_hash(),
        sample_selection_seed=17,
        pre_execution_ledger_head=_genesis()["entry_hash"],
    )
    event = plan["freeze_event"]
    rows = [_genesis(), event]
    with pytest.raises((TypeError, ValueError)):
        regeneration.execute_regeneration_plan_v3(
            plan,
            authority_root=root,
            current_authority={},
            freeze_event=event,
            execution_ledger_rows=rows,
            current_bundle_ids=plan["bundle_ids"],
            segment_id="seg-1",
            sample_selection_seed=17,
        )
    altered = dict(authority)
    altered["generator_sha256"] = "f" * 64
    altered["authority_hash"] = hashlib.sha256(
        canonical_bytes({k: altered[k] for k in altered if k != "authority_hash"})
    ).hexdigest()
    with pytest.raises(ValueError):
        regeneration.execute_regeneration_plan_v3(
            plan,
            authority_root=root,
            current_authority=altered,
            freeze_event=event,
            execution_ledger_rows=rows,
            current_bundle_ids=plan["bundle_ids"],
            segment_id="seg-1",
            sample_selection_seed=17,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: {
            key: value for key, value in row.items() if key != "schema_version"
        },
        lambda row: {**row, "event": "RUNNING"},
        lambda row: {**row, "state": "RUNNING"},
        lambda row: {**row, "prev_hash": "f" * 64},
    ],
)
def test_strict_execution_rejects_noncanonical_genesis(tmp_path, mutation):
    root, authority = _strict_fixture(tmp_path)
    genesis = _genesis()
    plan = regeneration.freeze_regeneration_plan_v3(
        segment_id="seg-1",
        bundle_ids=["b-1", "b-2"],
        authority=authority,
        replay_policy_hash=regeneration.exact_replay_policy_hash(),
        sample_selection_seed=17,
        pre_execution_ledger_head=genesis["entry_hash"],
    )
    altered = mutation(genesis)
    unsigned = {key: value for key, value in altered.items() if key != "entry_hash"}
    altered["entry_hash"] = hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
    with pytest.raises(ValueError, match="canonical genesis"):
        regeneration.execute_regeneration_plan_v3(
            plan,
            authority_root=root,
            current_authority=authority,
            freeze_event=plan["freeze_event"],
            execution_ledger_rows=[altered, plan["freeze_event"]],
            current_bundle_ids=plan["bundle_ids"],
            segment_id="seg-1",
            sample_selection_seed=17,
        )


def test_strict_execution_rejects_incomplete_predecessor_chain(tmp_path):
    root, authority = _strict_fixture(tmp_path)
    genesis = _genesis()
    plan = regeneration.freeze_regeneration_plan_v3(
        segment_id="seg-1",
        bundle_ids=["b-1", "b-2"],
        authority=authority,
        replay_policy_hash=regeneration.exact_replay_policy_hash(),
        sample_selection_seed=17,
        pre_execution_ledger_head=genesis["entry_hash"],
    )
    inserted_body = {
        "schema_version": "segment-ledger-entry.v1",
        "event": "SEGMENT_READY",
        "segment_id": "seg-1",
        "state": "PLANNED",
        "prev_hash": genesis["entry_hash"],
    }
    inserted = {
        **inserted_body,
        "entry_hash": hashlib.sha256(canonical_bytes(inserted_body)).hexdigest(),
    }
    with pytest.raises(ValueError, match="predecessor discontinuity"):
        regeneration.execute_regeneration_plan_v3(
            plan,
            authority_root=root,
            current_authority=authority,
            freeze_event=plan["freeze_event"],
            execution_ledger_rows=[genesis, inserted, plan["freeze_event"]],
            current_bundle_ids=plan["bundle_ids"],
            segment_id="seg-1",
            sample_selection_seed=17,
        )


@pytest.mark.parametrize("unsafe_path", ["../outside.py", "C:/outside.py"])
def test_runtime_authority_rejects_absolute_or_parent_paths(tmp_path, unsafe_path):
    root, authority = _strict_fixture(tmp_path)
    altered = dict(authority)
    altered["generator_path"] = unsafe_path
    altered["authority_hash"] = hashlib.sha256(
        canonical_bytes(
            {key: value for key, value in altered.items() if key != "authority_hash"}
        )
    ).hexdigest()
    with pytest.raises(ValueError, match="relative and root-confined"):
        regeneration.validate_runtime_commitment_authority(root, altered)


def test_runtime_authority_rejects_reparse_component(tmp_path):
    root, authority = _strict_fixture(tmp_path)
    external = tmp_path.parent / f"{tmp_path.name}-external.py"
    external.write_text("external = True\n", encoding="utf-8")
    link = root / "src" / "linked-generator.py"
    try:
        link.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    altered = dict(authority)
    altered["generator_path"] = "src/linked-generator.py"
    altered["generator_sha256"] = hashlib.sha256(external.read_bytes()).hexdigest()
    altered["authority_hash"] = hashlib.sha256(
        canonical_bytes(
            {key: value for key, value in altered.items() if key != "authority_hash"}
        )
    ).hexdigest()
    with pytest.raises(ValueError, match="reparse component"):
        regeneration.validate_runtime_commitment_authority(root, altered)


def test_runtime_authority_rejects_relative_or_reparse_root(tmp_path, monkeypatch):
    root, authority = _strict_fixture(tmp_path)
    monkeypatch.chdir(root.parent)
    with pytest.raises(ValueError, match="absolute normalized"):
        regeneration.validate_runtime_commitment_authority(Path(root.name), authority)
    alias = root.parent / f"{root.name}-alias"
    try:
        alias.symlink_to(root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink creation unavailable: {exc}")
    with pytest.raises(ValueError, match="authority root crosses reparse"):
        regeneration.validate_runtime_commitment_authority(alias, authority)


def test_runtime_authority_rejects_non_generator_source_mutation(tmp_path):
    root, authority = _strict_fixture(tmp_path)
    extra = root / "tests" / "non_generator_marker.py"
    extra.parent.mkdir()
    extra.write_text("changed = True\n", encoding="utf-8")
    with pytest.raises(ValueError, match="file parity mismatch"):
        regeneration.validate_runtime_commitment_authority(root, authority)
