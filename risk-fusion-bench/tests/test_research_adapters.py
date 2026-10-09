import hashlib
import json
from pathlib import Path

import pytest

from rfb.research.adapters import (
    DRAIN_BYTES,
    HARD_HALT_BYTES,
    METHOD_PANEL,
    PLANNED_BYTES,
    SUBBUDGETS,
    capacity_state,
    fixture_registry,
    production_registry,
    registry,
    resolve_adapter,
    validate_adapter_contract,
)
from rfb.research.isolation import (
    MethodSideTruthAccessDenied,
    build_method_event_bundle,
)
from rfb.research.scorer_owner import (
    ScorerTruthOwner,
    audit_d_test_namespace,
    seal_prediction_result,
)


def test_closed_registry_and_fixed_surface():
    assert registry()
    for aid, spec in registry().items():
        assert resolve_adapter(aid) is not None
        argv = spec.fixed_argv(Path("m.json"))
        assert argv[-2:] == ["--manifest", "m.json"]
        assert "argv" not in spec.minimal_environment()
        assert spec.minimal_environment()["CUDA_VISIBLE_DEVICES"] == "-1"


def test_adapter_contract_invariants():
    base = {"adapter_id": "tep_fixture", "method_panel": list(METHOD_PANEL)}
    validate_adapter_contract(base)
    with pytest.raises(ValueError):
        validate_adapter_contract({**base, "method_panel": ["B0"]})
    with pytest.raises(ValueError):
        validate_adapter_contract({**base, "effect_peeking": True})
    with pytest.raises(ValueError):
        validate_adapter_contract(
            {**base, "capacity": {"planned_bytes": HARD_HALT_BYTES + 1}}
        )


def _capacity(peak=PLANNED_BYTES):
    return {
        "planned_bytes": PLANNED_BYTES,
        "drain_bytes": DRAIN_BYTES,
        **SUBBUDGETS,
        "telemetry": {
            "project_tree_allocated_bytes": peak,
            "filesystem_used_delta_bytes": 0,
            "owned_external_layers_bytes": 0,
            "open_deleted_bytes": 0,
            "observed_peak_bytes": peak,
        },
    }


def test_production_capacity_is_required_and_exact():
    production_manifest = {
        "adapter_id": "tep_nonconfirmatory_v1",
        "method_panel": list(METHOD_PANEL),
    }
    with pytest.raises(ValueError, match="CAPACITY_REQUIRED"):
        validate_adapter_contract(production_manifest)
    for field in (
        "dataset",
        "durable_result",
        "scratch_partial",
        "retry_quarantine_wal",
        "emergency_reserve",
    ):
        bad = _capacity()
        bad[field] = 0
        with pytest.raises(ValueError):
            validate_adapter_contract({**production_manifest, "capacity": bad})


def test_capacity_thresholds_are_observable_and_fail_closed():
    assert capacity_state(_capacity()) == "PLANNED"
    assert capacity_state(_capacity(DRAIN_BYTES)) == "DRAIN_AND_SEAL"
    with pytest.raises(ValueError, match="CAPACITY_PLANNING_INVALID"):
        capacity_state(_capacity(PLANNED_BYTES + 1))
    with pytest.raises(ValueError, match="SAFE_HALT_CAP_BREACH"):
        capacity_state(_capacity(HARD_HALT_BYTES + 1))
    mismatched = _capacity()
    mismatched["telemetry"]["filesystem_used_delta_bytes"] = DRAIN_BYTES
    with pytest.raises(ValueError, match="CAPACITY_TELEMETRY_MISMATCH"):
        capacity_state(mismatched)


def test_fixture_and_production_registries_are_disjoint():
    assert set(fixture_registry()) == {"tep_fixture", "local_fixture_nonconfirmatory"}
    assert set(production_registry()) == {"tep_nonconfirmatory_v1"}
    fixture_manifest = {"adapter_id": "tep_fixture", "scientific_acceptance": True}
    with pytest.raises(ValueError, match="FIXTURE_ADAPTER_NOT_SCIENTIFIC"):
        validate_adapter_contract(fixture_manifest)


def test_iso_neg_01_tep_adapter_traps_both_scorer_only_apis(monkeypatch, tmp_path):
    from rfb import methods
    from rfb.loaders.tep import TEPLoader

    captured = {}
    original_to_bpa = TEPLoader.to_bpa

    def capture_to_bpa(self, observation):
        captured["calls"] = captured.get("calls", 0) + 1
        return original_to_bpa(self, observation)

    def capture_run_all(data):
        captured["events"] = data["events"]
        captured["run_all_keys"] = set(data)
        return {method_id: {} for method_id in METHOD_PANEL}

    def deny_scorer_capability(*_args, **_kwargs):
        raise AssertionError("ISO-NEG-01: method path touched scorer-only capability")

    monkeypatch.setattr(TEPLoader, "to_bpa", capture_to_bpa)
    monkeypatch.setattr(TEPLoader, "scorer_only_metadata", deny_scorer_capability)
    monkeypatch.setattr(TEPLoader, "scorer_only_sidecar", deny_scorer_capability)
    monkeypatch.setattr(methods, "run_all", capture_run_all)
    rows = [[float(i * 2 + j) for j in range(3)] for i in range(12)]
    manifest = {
        "run_id": "tep-support-check",
        "adapter_id": "tep_nonconfirmatory_v1",
        "method_panel": list(METHOD_PANEL),
        "capacity": _capacity(),
        "algorithm_seed": 0,
        "adapter_params": {"rows": rows},
    }

    resolve_adapter("tep_nonconfirmatory_v1").execute(
        manifest, tmp_path / "tep-support-check"
    )
    assert captured["calls"] == len(captured["events"])
    supports = [event["support"] for event in captured["events"]]
    assert supports
    assert any(support != 0.5 for support in supports)
    assert captured["run_all_keys"] == {
        "bundle_id",
        "algorithm_seed",
        "transaction_id",
        "events",
    }


def _tep_loader_and_observations():
    from rfb.loaders.tep import TEPLoader

    loader = TEPLoader()
    rows = [[float(i * 3 + j) for j in range(3)] for i in range(12)]
    loader.fit_normal(rows)
    observations = loader.from_array(
        rows,
        window=4,
        fault_label=7,
        simulation_run_id="private-run",
    )
    return loader, observations


def _method_payload_and_outputs(loader, observations, run_id="iso-neg"):
    from rfb.methods import run_all

    bundle = build_method_event_bundle(
        bundle_id=run_id,
        algorithm_seed=0,
        observations=observations,
        bpa_mapper=loader.to_bpa,
        prop_mask=loader.PROP_MASK,
    )
    payload = bundle.to_run_all_payload()
    return bundle, payload, run_all(payload)


def test_iso_neg_02_fault_label_cannot_change_method_payload_or_outputs():
    loader, observations = _tep_loader_and_observations()
    _, baseline_payload, baseline_outputs = _method_payload_and_outputs(
        loader, observations
    )
    loader._set_scorer_only_sidecar(
        observations, [{"fault_label": 999999} for _ in observations]
    )
    _, changed_payload, changed_outputs = _method_payload_and_outputs(
        loader, observations
    )
    assert changed_payload == baseline_payload
    assert changed_outputs == baseline_outputs


def test_iso_neg_03_source_paths_cannot_change_method_payload_or_outputs():
    loader, observations = _tep_loader_and_observations()
    _, baseline_payload, baseline_outputs = _method_payload_and_outputs(
        loader, observations
    )
    loader._set_scorer_only_sidecar(
        observations,
        [
            {
                "source_path": "C:/private/../../truth.dat",
                "source_filename": "truth-secret.dat",
            }
            for _ in observations
        ],
    )
    _, changed_payload, changed_outputs = _method_payload_and_outputs(
        loader, observations
    )
    assert changed_payload == baseline_payload
    assert changed_outputs == baseline_outputs
    assert "truth-secret" not in repr(changed_payload)


def test_iso_neg_04_split_and_dtest_marker_cannot_reach_method_path():
    loader, observations = _tep_loader_and_observations()
    _, baseline_payload, baseline_outputs = _method_payload_and_outputs(
        loader, observations
    )
    loader._set_scorer_only_sidecar(
        observations, [{"split": "D_test_FORBIDDEN"} for _ in observations]
    )
    _, changed_payload, changed_outputs = _method_payload_and_outputs(
        loader, observations
    )
    assert changed_payload == baseline_payload
    assert changed_outputs == baseline_outputs
    assert "D_test" not in repr(changed_payload)


def test_iso_neg_05_fake_sidecar_reliability_cannot_override_public_quality():
    loader, observations = _tep_loader_and_observations()
    observations[0].quality["completeness"] = 0.625
    _, baseline_payload, baseline_outputs = _method_payload_and_outputs(
        loader, observations
    )
    loader._set_scorer_only_sidecar(
        observations, [{"reliability": -999.0} for _ in observations]
    )
    _, changed_payload, changed_outputs = _method_payload_and_outputs(
        loader, observations
    )
    assert changed_payload == baseline_payload
    assert changed_outputs == baseline_outputs
    assert changed_payload["events"][0]["reliability"] == 0.625


def test_iso_neg_06_future_truth_fields_missing_sidecar_and_illegal_access_fail_closed(
    tmp_path,
):
    loader, observations = _tep_loader_and_observations()
    method_bundle, baseline_payload, baseline_outputs = _method_payload_and_outputs(
        loader, observations
    )
    loader._set_scorer_only_sidecar(
        observations,
        [
            {
                "truth_graph": {"root": "SECRET"},
                "physical_acquisition_id": "SECRET-ROOT",
                "action_state": "SECRET-ACTION",
                "future_nested": {"reliability": 1000.0},
            }
            for _ in observations
        ],
    )
    method_result_path = tmp_path / "method-result.json"
    method_result_path.write_text("{}", encoding="utf-8")
    prediction_receipt = seal_prediction_result(
        bundle_id="iso-neg", method_result_path=method_result_path
    )
    truth_bundle = ScorerTruthOwner(loader).seal_after_prediction(
        prediction_receipt=prediction_receipt,
        method_result_path=method_result_path,
        expected_count=len(observations),
    )
    _, changed_payload, changed_outputs = _method_payload_and_outputs(
        loader, observations
    )
    assert truth_bundle.records
    assert method_bundle.opaque_join_tokens == tuple(
        record["opaque_join_token"] for record in truth_bundle.records
    )
    assert changed_payload == baseline_payload
    assert changed_outputs == baseline_outputs
    with pytest.raises(MethodSideTruthAccessDenied):
        _ = method_bundle.scorer_only_sidecar
    with pytest.raises(MethodSideTruthAccessDenied):
        truth_bundle.to_run_all_payload()

    loader._scorer_only_records = ()
    loader._scorer_only_by_observation_id = {}
    _, missing_payload, missing_outputs = _method_payload_and_outputs(
        loader, observations
    )
    assert missing_payload == baseline_payload
    assert missing_outputs == baseline_outputs


def test_sidecar_presence_content_and_count_do_not_change_durable_method_result(
    monkeypatch, tmp_path
):
    from rfb.loaders.tep import TEPLoader

    rows = [[float(i * 2 + j) for j in range(3)] for i in range(12)]
    manifest = {
        "run_id": "tep-isolation",
        "adapter_id": "tep_nonconfirmatory_v1",
        "method_panel": list(METHOD_PANEL),
        "capacity": _capacity(),
        "algorithm_seed": 0,
        "adapter_params": {"rows": rows},
    }
    adapter = resolve_adapter("tep_nonconfirmatory_v1")
    baseline = adapter.execute(manifest, tmp_path / "baseline")
    monkeypatch.setattr(TEPLoader, "scorer_only_sidecar", lambda _self: ())
    missing = adapter.execute(manifest, tmp_path / "missing")
    monkeypatch.setattr(
        TEPLoader,
        "scorer_only_sidecar",
        lambda _self: (
            {"fault_label": 999, "reliability": -1000.0},
            {"source_path": "SECRET", "split": "D_test"},
        ),
    )
    changed_count_and_content = adapter.execute(manifest, tmp_path / "changed")
    assert missing == baseline
    assert changed_count_and_content == baseline
    assert "scorer_only" not in baseline
    assert "sidecar" not in repr(baseline).lower()
    assert tuple(baseline["method_outputs"]) == METHOD_PANEL


def test_scorer_owner_requires_valid_prediction_seal_and_is_not_adapter_input(
    tmp_path,
):
    loader, observations = _tep_loader_and_observations()
    owner = ScorerTruthOwner(loader)
    result_path = tmp_path / "method-result.json"
    result_path.write_text('{"sealed": true}', encoding="utf-8")
    receipt = seal_prediction_result(bundle_id="sealed", method_result_path=result_path)
    result_path.write_text('{"sealed": false}', encoding="utf-8")
    with pytest.raises(ValueError, match="PREDICTION_RESULT_CHANGED_AFTER_SEAL"):
        owner.seal_after_prediction(
            prediction_receipt=receipt,
            method_result_path=result_path,
            expected_count=len(observations),
        )
    result_path.write_text('{"sealed": true}', encoding="utf-8")
    truth_bundle = owner.seal_after_prediction(
        prediction_receipt=receipt,
        method_result_path=result_path,
        expected_count=len(observations),
    )
    with pytest.raises(MethodSideTruthAccessDenied):
        truth_bundle.to_run_all_payload()


def test_scorer_truth_metadata_is_canonical_hashed_and_deeply_immutable(tmp_path):
    loader, observations = _tep_loader_and_observations()
    mutable_truth = {
        "truth_graph": {"roots": ["r1", "r2"]},
        "action_state": ["hold", {"code": 7}],
    }
    loader._set_scorer_only_sidecar(observations, [mutable_truth for _ in observations])
    result_path = tmp_path / "method-result.json"
    result_path.write_text("{}", encoding="utf-8")
    receipt = seal_prediction_result(
        bundle_id="immutable", method_result_path=result_path
    )
    bundle = ScorerTruthOwner(loader).seal_after_prediction(
        prediction_receipt=receipt,
        method_result_path=result_path,
        expected_count=len(observations),
    )
    payload_before = bundle.to_canonical_payload()
    mutable_truth["truth_graph"]["roots"].append("MUTATED")
    assert bundle.to_canonical_payload() == payload_before
    with pytest.raises(TypeError):
        bundle.records[0]["metadata"]["truth_graph"]["new"] = "denied"
    assert len(bundle.content_sha256) == 64


def test_real_adapter_worker_scorer_chain_keeps_truth_outside_result_tree(tmp_path):
    from rfb.research.receipts import result_tree_manifest, scan_closed_result
    from rfb.research.worker import _run_post_prediction_scorer

    run_id = "worker-scorer-chain"
    output = tmp_path / f"{run_id}.results.partial"
    manifest = {
        "run_id": run_id,
        "adapter_id": "tep_nonconfirmatory_v1",
        "method_panel": list(METHOD_PANEL),
        "capacity": _capacity(),
        "algorithm_seed": 0,
        "adapter_params": {
            "rows": [[float(i * 2 + j) for j in range(3)] for i in range(12)]
        },
    }
    adapter = resolve_adapter("tep_nonconfirmatory_v1")
    method_result = adapter.execute(manifest, output)
    status, receipt = _run_post_prediction_scorer(
        manifest=manifest,
        output=output,
        remote_run_root=tmp_path,
        adapter_id=adapter.adapter_id,
    )
    assert receipt is not None
    receipt.validate(output / "tep_result.json")
    assert status["status"] == "SEALED"
    assert status["excluded_from_result_tree"] is True
    assert status["ephemeral"] is True
    assert status["d_test_namespace_touched"] is False
    scan_closed_result(output)
    assert set(result_tree_manifest(output)) == {"tep_result.json"}
    encoded_result = json.dumps(method_result, sort_keys=True)
    assert "truth_graph" not in encoded_result
    assert "fault_label" not in encoded_result
    scorer_artifact = (
        tmp_path / ".scorer-only-ephemeral" / run_id / "scorer_truth_bundle.json"
    )
    assert scorer_artifact.is_file()
    assert output not in scorer_artifact.parents
    assert not any(part.casefold() == "d_test" for part in scorer_artifact.parts)


def test_scorer_alignment_failure_is_independent_of_sealed_method_result(
    monkeypatch, tmp_path
):
    from rfb.loaders.tep import TEPLoader
    from rfb.research.worker import _run_post_prediction_scorer

    run_id = "worker-scorer-failure"
    output = tmp_path / f"{run_id}.results.partial"
    manifest = {
        "run_id": run_id,
        "adapter_id": "tep_nonconfirmatory_v1",
        "method_panel": list(METHOD_PANEL),
        "capacity": _capacity(),
        "algorithm_seed": 0,
        "adapter_params": {
            "rows": [[float(i * 2 + j) for j in range(3)] for i in range(12)]
        },
    }
    adapter = resolve_adapter("tep_nonconfirmatory_v1")
    method_result = adapter.execute(manifest, output)
    method_result_bytes = (output / "tep_result.json").read_bytes()
    monkeypatch.setattr(TEPLoader, "scorer_only_sidecar", lambda _self: ())
    status, receipt = _run_post_prediction_scorer(
        manifest=manifest,
        output=output,
        remote_run_root=tmp_path,
        adapter_id=adapter.adapter_id,
    )
    assert status["status"] == "SCORER_FAILED"
    assert status["failure_code"] == "SCORER_TRUTH_ALIGNMENT_INVALID"
    assert status["scientific_eligible"] is False
    assert receipt is not None
    receipt.validate(output / "tep_result.json")
    assert (output / "tep_result.json").read_bytes() == method_result_bytes
    assert tuple(method_result["method_outputs"]) == METHOD_PANEL
    assert not (output / "scorer_failure.json").exists()


def test_r77_public_input_and_seven_method_golden_artifact_is_unchanged():
    project_root = Path(__file__).resolve().parents[2]
    golden_path = (
        project_root
        / ".omx"
        / "handoff"
        / "g014-live"
        / "g014-r006-20260816T130000Z-r77"
        / "controller"
        / "results"
        / "g014-r006-20260816T130000Z-r77"
        / "tep_result.json"
    )
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    assert golden["durable_result_sha256"] == (
        "c36a177a52ca8e022f60bbaa97c7064b4087de4a268ecb02243fe0e61dc4a447"
    )
    assert tuple(golden["method_panel"]) == METHOD_PANEL
    assert tuple(golden["method_outputs"]) == METHOD_PANEL
    assert {
        output["input_commitment_sha256"]
        for output in golden["method_outputs"].values()
    } == {"448a40e47169b27d8e8d6358f940adabb477abc07c13bfbb27180026aba91cb7"}
    assert {
        method_id: output["prediction"]["risk_score"]
        for method_id, output in golden["method_outputs"].items()
    } == {
        "B0": 1.0,
        "B1": 1.0,
        "B2": 1.0,
        "B3": 0.85,
        "B4": 1.0,
        "B5": 1.0,
        "Proposed": 1.0,
    }


def test_current_adapter_replays_frozen_r77_equivalent_public_fixture(tmp_path):
    rows = [[float(i * 2 + j) for j in range(3)] for i in range(12)]
    manifest = {
        "run_id": "r77-equivalent-public-fixture-v1",
        "adapter_id": "tep_nonconfirmatory_v1",
        "method_panel": list(METHOD_PANEL),
        "capacity": _capacity(),
        "algorithm_seed": 0,
        "adapter_params": {"rows": rows},
    }
    result = resolve_adapter("tep_nonconfirmatory_v1").execute(
        manifest, tmp_path / "current-r77-equivalent"
    )
    assert tuple(result["method_outputs"]) == METHOD_PANEL
    assert {
        output["input_commitment_sha256"]
        for output in result["method_outputs"].values()
    } == {"f7e2b924f53759949092032ad7dd0591a59f46df0868723466e8700b3b9c5198"}
    assert {
        method_id: output["prediction"]
        for method_id, output in result["method_outputs"].items()
    } == {
        "B0": {
            "risk_score": 0.438108803548,
            "risk_interval": [0.438108803548, 0.438108803548],
            "confidence": 1.0,
            "evidence_count": 3,
            "active_root_count": 3,
        },
        "B1": {
            "risk_score": 0.438108803548,
            "risk_interval": [0.438108803548, 0.438108803548],
            "confidence": 1.0,
            "evidence_count": 3,
            "active_root_count": 3,
        },
        "B2": {
            "risk_score": 0.438108803548,
            "risk_interval": [0.438108803548, 0.438108803548],
            "confidence": 1.0,
            "evidence_count": 3,
            "active_root_count": 3,
        },
        "B3": {
            "risk_score": 0.237197611129,
            "risk_interval": [0.237197611129, 0.237197611129],
            "confidence": 1.0,
            "evidence_count": 3,
            "active_root_count": 3,
        },
        "B4": {
            "risk_score": 0.298775433617,
            "risk_interval": [0.298775433617, 0.298775433617],
            "confidence": 1.0,
            "evidence_count": 3,
            "active_root_count": 3,
        },
        "B5": {
            "risk_score": 0.508726558084,
            "risk_interval": [0.237197611129, 0.508726558084],
            "confidence": 0.728471053045,
            "evidence_count": 3,
            "active_root_count": 3,
        },
        "Proposed": {
            "risk_score": 0.438108803548,
            "risk_interval": [0.438108803548, 0.438108803548],
            "confidence": 1.0,
            "evidence_count": 3,
            "active_root_count": 3,
        },
    }
    for output in result["method_outputs"].values():
        assert output["audit"]["duplicate_count"] == 0
        assert output["audit"]["eliminated_count"] == 0
        assert output["audit"]["rebuild_count"] == 0
        assert output["audit"]["canonical_roots"] == ["tep-0", "tep-1", "tep-2"]


@pytest.mark.parametrize(
    "variant",
    [
        "D_test",
        "d-test",
        "D_TEST",
        "dTeSt",
        "nested-d_test-artifacts",
        "prefixD_testSuffix",
        "d__t-e_s_t",
    ],
)
def test_d_test_namespace_variants_fail_closed(variant):
    with pytest.raises(ValueError, match="D_TEST_NAMESPACE_FORBIDDEN"):
        audit_d_test_namespace(Path("safe") / variant / "scorer.json")
    assert audit_d_test_namespace(Path("safe") / "d-score-test") is False


def test_installed_worker_closes_method_tree_and_excludes_scorer_truth(
    monkeypatch, tmp_path
):
    import rfb.research.worker as installed_worker

    root = tmp_path / "real-worker"
    root.mkdir()
    preflight = {
        "root": str(root.resolve()),
        "hostname": "host",
        "mount_identity": "mount",
        "source_tree_sha256": "a" * 64,
        "package_inventory_sha256": "b" * 64,
        "config_sha256": "c" * 64,
        "input_manifest_sha256": "d" * 64,
        "dataset_manifest_sha256": "e" * 64,
        "dataset_manifest_verified": False,
        "gpu_policy": "cpu_only",
        "gpu_identity": "N/A",
        "capacity_available": True,
        "filesystem_used_bytes": 1,
        "filesystem_free_bytes": 300_000_000_000,
        "owned_process_snapshot_sha256": "4" * 64,
        "foreign_process_snapshot_sha256": "5" * 64,
        "gpu_inventory_sha256": "f" * 64,
        "gpu_process_snapshot_sha256": "1" * 64,
    }
    run_id = "real-worker"
    manifest = {
        "run_id": run_id,
        "approved_remote_parent": str(tmp_path.resolve()),
        "remote_run_root": str(root.resolve()),
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
        "adapter_id": "tep_nonconfirmatory_v1",
        "controller_nonce": "2" * 32,
        "prepared_manifest_sha256": "3" * 64,
        "formal_snapshot_sha256": "4" * 64,
        "preflight_evidence": preflight,
        "preflight_evidence_sha256": "8" * 64,
        "gpu_policy": "cpu_only",
        "runtime_format": "python_zipapp_stdlib_v1",
        "runtime_path": f"{'5' * 64}.pyz",
        "runtime_file_sha256": "5" * 64,
        "runtime_source_sha256": "6" * 64,
        "runtime_manifest_sha256": "7" * 64,
        "runtime_dependency_profile": "stdlib_only",
        "method_panel": list(METHOD_PANEL),
        "capacity": _capacity(),
        "algorithm_seed": 0,
        "adapter_params": {
            "rows": [[float(i * 2 + j) for j in range(3)] for i in range(12)]
        },
    }
    path = tmp_path / "real-worker.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    real_adapter = resolve_adapter("tep_nonconfirmatory_v1")

    class TestSpec:
        adapter_id = "tep_nonconfirmatory_v1"
        fixture_only = True
        implementation_sha256 = real_adapter.implementation_sha256

        @staticmethod
        def execute(run_manifest, output):
            return real_adapter.execute(run_manifest, output)

        @staticmethod
        def fixed_argv(_path):
            return ["worker"]

        @staticmethod
        def minimal_environment(*, root):
            return {"RFB_RESEARCH_ROOT": str(root)}

    monkeypatch.setattr(installed_worker, "validate_manifest", lambda value: value)
    monkeypatch.setattr(
        installed_worker, "_validate_preflight_binding", lambda _value: None
    )
    monkeypatch.setattr(installed_worker, "resolve_adapter", lambda _value: TestSpec())
    monkeypatch.setattr(
        installed_worker,
        "collect_preflight",
        lambda *_args, **_kwargs: dict(preflight),
    )
    from rfb.research.models import CLASSIFICATION
    from rfb.research.receipts import (
        reopen_validate_remote_receipt,
        validate_remote_receipt,
    )
    from rfb.research.trace import LifecycleTraceRecorder

    trace = LifecycleTraceRecorder(
        run_id=run_id,
        approved_remote_parent=manifest["approved_remote_parent"],
        remote_run_root=manifest["remote_run_root"],
    )
    for step in range(11):
        trace.append(
            input_hashes={
                f"input_{step}": hashlib.sha256(f"i{step}".encode()).hexdigest()
            },
            output_hashes={
                f"output_{step}": hashlib.sha256(f"o{step}".encode()).hexdigest()
            },
        )
    trace_prefix = {
        "schema_version": "1.0.0-prefix",
        "run_id": run_id,
        "approved_remote_parent": manifest["approved_remote_parent"],
        "remote_run_root": manifest["remote_run_root"],
        "execution_manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        **CLASSIFICATION,
        "records": trace.records,
        "trace_head_sha256": trace.records[-1]["trace_hash"],
    }
    trace_prefix_path = tmp_path / "real-worker.trace-prefix.json"
    trace_prefix_path.write_text(json.dumps(trace_prefix), encoding="utf-8")
    receipt = installed_worker.run_worker(
        path,
        trace_prefix=trace_prefix_path,
        trace_prefix_sha256=hashlib.sha256(trace_prefix_path.read_bytes()).hexdigest(),
    )
    closed_result = root / f"{run_id}.results"
    assert receipt["terminal_state"] == "RESULT_SEALED_REMOTE"
    assert receipt["scorer_artifact"]["status"] == "SEALED"
    assert receipt["scorer_artifact"]["excluded_from_result_tree"] is True
    assert receipt["scorer_artifact"]["d_test_namespace_touched"] is False
    assert {item.name for item in closed_result.iterdir()} == {"tep_result.json"}
    closed_text = (closed_result / "tep_result.json").read_text(encoding="utf-8")
    assert "truth_graph" not in closed_text
    assert "fault_label" not in closed_text
    scorer_artifact = (
        root / ".scorer-only-ephemeral" / run_id / "scorer_truth_bundle.json"
    )
    assert scorer_artifact.is_file()
    assert closed_result not in scorer_artifact.parents
    assert validate_remote_receipt(receipt) == receipt
    assert (
        reopen_validate_remote_receipt(root / f"{run_id}.REMOTE_EXECUTION_RECEIPT.json")
        == receipt
    )
    assert not any(
        part.casefold() == "d_test" for path in root.rglob("*") for part in path.parts
    )


@pytest.mark.parametrize("adapter_id", sorted(registry()))
def test_each_closed_adapter_wires_capacity_panel_and_scientific_guards(
    adapter_id, tmp_path
):
    spec = resolve_adapter(adapter_id)
    manifest = {
        "run_id": adapter_id,
        "adapter_id": adapter_id,
        "method_panel": list(METHOD_PANEL),
        "capacity": {
            "planned_bytes": PLANNED_BYTES,
            "drain_bytes": DRAIN_BYTES,
            "dataset": SUBBUDGETS["dataset"],
            "durable_result": SUBBUDGETS["durable_result"],
            "scratch_partial": SUBBUDGETS["scratch_partial"],
            "retry_quarantine_wal": SUBBUDGETS["retry_quarantine_wal"],
            "emergency_reserve": SUBBUDGETS["emergency_reserve"],
        },
        "algorithm_seed": 0,
    }
    manifest["capacity"]["telemetry"] = _capacity()["telemetry"]
    if adapter_id == "tep_nonconfirmatory_v1":
        manifest["adapter_params"] = {
            "rows": [[float(i + j) for j in range(3)] for i in range(12)]
        }
    validate_adapter_contract(manifest)
    spec.execute(manifest, tmp_path / adapter_id)
    for field, value in (
        ("planned_bytes", PLANNED_BYTES),
        ("drain_bytes", DRAIN_BYTES),
    ):
        bad = {**manifest, "capacity": {**manifest["capacity"], field: value + 1}}
        if field == "planned_bytes":
            # Planning beyond the frozen hard halt is always rejected.
            bad["capacity"][field] = HARD_HALT_BYTES + 1
        else:
            bad["capacity"][field] = DRAIN_BYTES + 1
            with pytest.raises(ValueError, match="CAPACITY_DRAIN"):
                validate_adapter_contract(bad)
    with pytest.raises(ValueError, match="SUBBUDGET"):
        validate_adapter_contract(
            {
                **manifest,
                "capacity": {
                    **manifest["capacity"],
                    "dataset": SUBBUDGETS["dataset"] + 1,
                },
            }
        )
    with pytest.raises(ValueError):
        validate_adapter_contract({**manifest, "method_panel": ["B0"]})
    with pytest.raises(ValueError):
        validate_adapter_contract({**manifest, "adaptive_segmentation": True})
