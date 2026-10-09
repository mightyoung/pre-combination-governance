import hashlib
import json
import shutil
from pathlib import Path

import pytest

import rfb.research.worker as installed_worker
from rfb.contracts.canonical_json import canonical_bytes, sha256_hex
from rfb.research.controller import (
    bind_downloaded_result,
    execute_remote,
    prepare_legacy_r006 as prepare_run,
    verify_final_receipt,
)
from rfb.research.models import CLASSIFICATION
from rfb.research.receipts import seal_receipt
from rfb.research.runtime_bundle import RuntimeBundleError, build_runtime_bundle
from rfb.research.transport import FakeTransport, TransportError
from rfb.research.worker import run_worker


class InvalidTepScorerReceiptTransport(FakeTransport):
    """Inject a hash-valid but scientifically ineligible TEP receipt."""

    def __init__(self, mode):
        super().__init__(run_worker)
        self.mode = mode

    def run(self, remote_argv):
        result = dict(super().run(remote_argv))
        if "worker" not in tuple(map(str, remote_argv)):
            return result
        receipt = json.loads(result["stdout"])
        receipt.pop("self_hash")
        receipt["adapter_id"] = "tep_nonconfirmatory_v1"
        if self.mode == "missing":
            receipt.pop("scorer_artifact", None)
        else:
            receipt["scorer_artifact"] = {
                "status": "NOT_APPLICABLE",
                "scientific_eligible": False,
                "failure_code": None,
                "excluded_from_result_tree": True,
                "ephemeral": True,
                "d_test_namespace_touched": False,
            }
        inner = {
            key: value
            for key, value in receipt.items()
            if key not in {"receipt_self_hash", *CLASSIFICATION}
        }
        receipt["receipt_self_hash"] = sha256_hex(canonical_bytes(inner))
        receipt = seal_receipt(receipt)
        remote_path = (
            Path(receipt["remote_run_root"])
            / f"{receipt['run_id']}.REMOTE_EXECUTION_RECEIPT.json"
        )
        remote_path.write_bytes(canonical_bytes(receipt))
        result["stdout"] = canonical_bytes(receipt).decode("utf-8")
        return result

    def download_file(self, *, remote_path, local_path):
        self.lifecycle.append("download_receipt")
        shutil.copyfile(remote_path, local_path)
        return local_path


def test_fake_runtime_stage_rejects_hash_drift_and_run_root_collision(tmp_path):
    transport = FakeTransport(run_worker)
    transport.bootstrap_parent_preflight(approved_remote_parent=tmp_path)
    created = transport.create_run_root(
        approved_remote_parent=tmp_path, run_id="remote-runtime"
    )

    drifted = build_runtime_bundle("tep_fixture", tmp_path / "drifted-cache")
    drifted.path.write_bytes(b"tampered")
    import pytest

    with pytest.raises(TransportError, match="RUNTIME_STAGE_VERIFY_FAILED"):
        transport.stage_runtime(bundle=drifted, remote_run_root=created.remote_run_root)

    with pytest.raises(TransportError, match="RUN_ROOT_COLLISION"):
        transport.create_run_root(
            approved_remote_parent=tmp_path, run_id="remote-runtime"
        )


def test_controller_blocks_nonportable_adapter_before_transport(tmp_path):
    remote = tmp_path / "nonportable"
    remote.mkdir()
    manifest = {
        "run_id": "nonportable",
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
        "adapter_id": "tep_nonconfirmatory_v1",
        "algorithm_seed": 0,
        "adapter_params": {
            "rows": [[float(i + j) for j in range(3)] for i in range(12)]
        },
        "capacity": {
            "planned_bytes": 22_000_000_000,
            "drain_bytes": 24_000_000_000,
            "dataset": 16_000_000_000,
            "durable_result": 3_000_000_000,
            "scratch_partial": 2_000_000_000,
            "retry_quarantine_wal": 1_000_000_000,
            "emergency_reserve": 3_000_000_000,
            "telemetry": {
                "project_tree_allocated_bytes": 1,
                "filesystem_used_delta_bytes": 1,
                "owned_external_layers_bytes": 0,
                "open_deleted_bytes": 0,
                "observed_peak_bytes": 1,
            },
        },
    }
    source = tmp_path / "nonportable.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")
    prepared = prepare_run(
        source, approved_remote_parent=tmp_path, approved_local_root=tmp_path
    )
    transport = FakeTransport(run_worker)

    import pytest

    with pytest.raises(
        RuntimeBundleError, match="RUNTIME_DEPENDENCY_CLOSURE_UNAVAILABLE"
    ):
        execute_remote(prepared, transport)
    assert transport.lifecycle == []


class BindingMismatchTransport(FakeTransport):
    def preflight(self, **kwargs):
        evidence = dict(super().preflight(**kwargs))
        evidence["prepared_manifest_sha256"] = "0" * 64
        return evidence


class ManifestTamperingTransport(FakeTransport):
    def stage(self, **kwargs):
        staged = super().stage(**kwargs)
        staged.write_bytes(staged.read_bytes() + b" ")
        return staged


class RootMismatchTransport(FakeTransport):
    def preflight(self, **kwargs):
        evidence = dict(super().preflight(**kwargs))
        evidence["root"] = str(Path(kwargs["root"]).parent / "other-root")
        return evidence


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("missing", "REMOTE_TEP_SCORER_ARTIFACT_REQUIRED"),
        ("not-applicable", "REMOTE_TEP_SCORER_NOT_ELIGIBLE"),
    ],
)
def test_execute_remote_rejects_ineligible_tep_scorer_before_final(
    tmp_path, mode, error
):
    local_root = tmp_path / "local"
    local_root.mkdir()
    source = tmp_path / f"{mode}.json"
    source.write_text(
        json.dumps(
            {
                "run_id": f"tep-{mode}",
                "execution_lane": "RESEARCH",
                "classification": "DEVELOPMENT_NONCONFIRMATORY",
                "formal_gate_effect": "NONE",
                "formal_admission_eligible": False,
                "shk001b_eligible": False,
                "contains_formal_claims": False,
                "adapter_id": "tep_fixture",
                "local_results": str(local_root),
            }
        ),
        encoding="utf-8",
    )
    prepared = prepare_run(
        source,
        approved_remote_parent=tmp_path,
        approved_local_root=tmp_path,
    )
    with pytest.raises(ValueError, match=error):
        execute_remote(prepared, InvalidTepScorerReceiptTransport(mode))
    assert not (local_root / f"tep-{mode}.receipts" / "FINAL_RUN_RECEIPT.json").exists()


def test_fake_remote_lifecycle_reaches_durable_final_receipt(tmp_path):
    remote_root = tmp_path / "e2e"
    local_root = tmp_path / "local"
    local_root.mkdir()
    manifest = {
        "run_id": "e2e",
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
        "adapter_id": "tep_fixture",
        "local_results": str(local_root),
    }
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")
    prepared = prepare_run(
        source,
        approved_remote_parent=tmp_path,
        approved_local_root=tmp_path,
    )

    transport = FakeTransport(run_worker)

    final = execute_remote(prepared, transport)

    assert final["terminal_state"] == "SUCCEEDED"
    assert transport.lifecycle == [
        "bootstrap_preflight",
        "create_run_root",
        "stage_runtime",
        "preflight",
        "stage",
        "stage",
        "run",
        "download_receipt",
        "download_evidence",
        "download",
    ]
    assert transport.calls[0][:5] == [
        "python3",
        "-I",
        "-S",
        final["runtime_path"],
        "worker",
    ]
    assert transport.calls[0][transport.calls[0].index("--manifest") + 1].endswith(
        ".e2e.execution.manifest.json"
    )
    assert final["runtime_file_sha256"] in final["runtime_path"]
    assert (local_root / "e2e" / "adapter_result.json").is_file()
    evidence = local_root / "e2e.receipts"
    assert (evidence / "COPY_VERIFICATION.json").is_file()
    assert (evidence / "REMOTE_EXECUTION_RECEIPT.json").is_file()
    assert (evidence / "FINAL_RUN_RECEIPT.json").is_file()
    durable_remote = json.loads(
        (evidence / "REMOTE_EXECUTION_RECEIPT.json").read_text(encoding="utf-8")
    )
    assert durable_remote["pre_post_hashes"]["config"]["before"]
    assert durable_remote["pre_post_hashes"]["config"]["after"]
    assert durable_remote["pre_post_hashes"]["input_manifest"]["before"]
    assert durable_remote["pre_post_hashes"]["input_manifest"]["after"]
    wrong_copy = tmp_path / "wrong-copy"
    wrong_copy.mkdir()

    with pytest.raises(ValueError, match="LOCAL_RESULT_PATH_MISMATCH"):
        verify_final_receipt(evidence / "FINAL_RUN_RECEIPT.json", local_copy=wrong_copy)

    remote_receipt = remote_root / "e2e.REMOTE_EXECUTION_RECEIPT.json"
    embedded_release = remote_root / "e2e.LOCK_RELEASE_PROOF.json"
    embedded_receipt_hash = hashlib.sha256(remote_receipt.read_bytes()).hexdigest()
    embedded_proof = json.loads(embedded_release.read_text(encoding="utf-8"))
    assert (
        embedded_proof["authoritative_remote_receipt_sha256"] == embedded_receipt_hash
    )
    embedded_tombstones = list(tmp_path.glob(".rfb-research-run.lock.*.tombstone"))
    assert len(embedded_tombstones) == 1
    assert (
        embedded_proof["lock_release_tombstone_sha256"]
        == hashlib.sha256(embedded_tombstones[0].read_bytes()).hexdigest()
    )
    original_receipt_hash = hashlib.sha256(remote_receipt.read_bytes()).hexdigest()

    with pytest.raises(TransportError, match="RUN_ROOT_COLLISION"):
        execute_remote(prepared, FakeTransport(run_worker))
    assert (
        hashlib.sha256(remote_receipt.read_bytes()).hexdigest() == original_receipt_hash
    )
    second_manifest = {**manifest, "run_id": "e2e-second"}
    second_source = tmp_path / "second-manifest.json"
    second_source.write_text(json.dumps(second_manifest), encoding="utf-8")
    second_prepared = prepare_run(
        second_source,
        approved_remote_parent=tmp_path,
        approved_local_root=tmp_path,
    )
    second = execute_remote(second_prepared, FakeTransport(run_worker))
    assert second["terminal_state"] == "SUCCEEDED"
    assert (local_root / "e2e.receipts" / "FINAL_RUN_RECEIPT.json").is_file()
    assert (local_root / "e2e-second.receipts" / "FINAL_RUN_RECEIPT.json").is_file()


def test_controller_can_bind_existing_remote_seal_after_download(tmp_path):
    remote_parent = tmp_path / "remote"
    remote_parent.mkdir()
    local_root = tmp_path / "local"
    local_root.mkdir()
    source = tmp_path / "manifest.json"
    source.write_text(
        json.dumps(
            {
                "run_id": "handoff",
                "execution_lane": "RESEARCH",
                "classification": "DEVELOPMENT_NONCONFIRMATORY",
                "formal_gate_effect": "NONE",
                "formal_admission_eligible": False,
                "shk001b_eligible": False,
                "contains_formal_claims": False,
                "adapter_id": "tep_fixture",
                "local_results": str(local_root),
            }
        ),
        encoding="utf-8",
    )
    prepared = prepare_run(
        source, approved_remote_parent=remote_parent, approved_local_root=tmp_path
    )
    execute_remote(prepared, FakeTransport(run_worker))
    remote_root = remote_parent / "handoff"
    remote_receipt = remote_root / "handoff.REMOTE_EXECUTION_RECEIPT.json"
    remote = json.loads(remote_receipt.read_text(encoding="utf-8"))
    downloaded = tmp_path / "downloaded"
    import shutil

    shutil.copytree(Path(remote["result_path"]), downloaded)
    local_receipt = tmp_path / "downloaded-remote-receipt.json"
    local_receipt.write_bytes(remote_receipt.read_bytes())
    final = bind_downloaded_result(
        prepared,
        remote_receipt_path=local_receipt,
        lock_release_proof_path=remote_root / "handoff.LOCK_RELEASE_PROOF.json",
        local_result=downloaded,
        evidence_root=tmp_path / "controller-receipts",
    )
    assert final["terminal_state"] == "SUCCEEDED"
    assert (
        final["remote_receipt_hash"]
        == hashlib.sha256(local_receipt.read_bytes()).hexdigest()
    )
    assert (tmp_path / "controller-receipts" / "COPY_VERIFICATION.json").is_file()
    assert (tmp_path / "controller-receipts" / "LOCK_RELEASE_PROOF.json").is_file()


def test_real_installed_worker_receipt_release_proof_sequence(tmp_path, monkeypatch):
    root = tmp_path / "installed"
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
        # A fixture has no external dataset manifest.  This mirrors the real
        # remote preflight contract instead of granting fixture-only evidence
        # a property it cannot truthfully claim.
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
    manifest = {
        "run_id": "installed",
        "approved_remote_parent": str(tmp_path.resolve()),
        "remote_run_root": str(root.resolve()),
        "adapter_id": "tep_fixture",
        "controller_nonce": "2" * 32,
        "preflight_evidence": preflight,
        "preflight_evidence_sha256": "ignored-by-patched-binding",
    }
    path = tmp_path / "installed.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    class Spec:
        adapter_id = "tep_fixture"
        fixture_only = True
        implementation_sha256 = "3" * 64

        @staticmethod
        def execute(_manifest, output):
            output.mkdir()
            (output / "adapter_result.json").write_text("{}", encoding="utf-8")

        @staticmethod
        def fixed_argv(_path):
            return ["worker"]

        @staticmethod
        def minimal_environment(*, root):
            return {"RFB_RESEARCH_ROOT": str(root)}

    monkeypatch.setattr(installed_worker, "validate_manifest", lambda value: value)
    monkeypatch.setattr(
        installed_worker, "validate_adapter_contract", lambda _value: None
    )
    monkeypatch.setattr(
        installed_worker, "_validate_preflight_binding", lambda _value: None
    )
    monkeypatch.setattr(installed_worker, "resolve_adapter", lambda _value: Spec())
    monkeypatch.setattr(
        installed_worker, "collect_preflight", lambda *_args, **_kwargs: dict(preflight)
    )
    receipt = installed_worker.run_worker(path)
    receipt_path = root / "installed.REMOTE_EXECUTION_RECEIPT.json"
    proof_path = root / "installed.LOCK_RELEASE_PROOF.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt
    assert (
        proof["authoritative_remote_receipt_sha256"]
        == hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    )
    tombstones = list(tmp_path.glob(".rfb-research-run.lock.*.tombstone"))
    assert len(tombstones) == 1
    assert (
        proof["lock_release_tombstone_sha256"]
        == hashlib.sha256(tombstones[0].read_bytes()).hexdigest()
    )


def test_execution_manifest_tampering_fails_before_result_creation(tmp_path):
    remote_root = tmp_path / "tamper"
    source = tmp_path / "tamper.json"
    source.write_text(
        json.dumps(
            {
                "run_id": "tamper",
                "execution_lane": "RESEARCH",
                "classification": "DEVELOPMENT_NONCONFIRMATORY",
                "formal_gate_effect": "NONE",
                "formal_admission_eligible": False,
                "shk001b_eligible": False,
                "contains_formal_claims": False,
                "adapter_id": "tep_fixture",
            }
        ),
        encoding="utf-8",
    )
    prepared = prepare_run(
        source,
        approved_remote_parent=tmp_path,
        approved_local_root=tmp_path,
    )

    with pytest.raises(RuntimeError, match="EXECUTION_FAILED"):
        execute_remote(prepared, ManifestTamperingTransport(run_worker))

    assert not list(remote_root.glob("*.remote-result"))
    assert not list(remote_root.glob(".*.remote-result.partial"))
    assert not (tmp_path / ".rfb-research-run.lock").exists()


def test_installed_worker_rejects_legacy_phase_less_manifest(tmp_path):
    manifest = {
        "run_id": "worker-e2e",
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
        "adapter_id": "tep_fixture",
    }
    source = tmp_path / "worker-manifest.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        ValueError, match="controller-bound absolute remote_root required"
    ):
        run_worker(source)
    assert not list(tmp_path.glob("*.results"))


def test_controller_rejects_preflight_not_bound_to_prepared_manifest(tmp_path):
    manifest = {
        "run_id": "binding-mismatch",
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
        "adapter_id": "tep_fixture",
    }
    source = tmp_path / "binding-manifest.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")
    prepared = prepare_run(
        source,
        approved_remote_parent=tmp_path,
        approved_local_root=tmp_path,
    )
    import pytest

    with pytest.raises(RuntimeError, match="PREFLIGHT_BINDING_MISMATCH"):
        execute_remote(prepared, BindingMismatchTransport(run_worker))

    second_manifest = {
        **manifest,
        "run_id": "root-mismatch",
    }
    second_source = tmp_path / "root-mismatch-manifest.json"
    second_source.write_text(json.dumps(second_manifest), encoding="utf-8")
    second_prepared = prepare_run(
        second_source,
        approved_remote_parent=tmp_path,
        approved_local_root=tmp_path,
    )
    with pytest.raises(RuntimeError, match="PREFLIGHT_BINDING_MISMATCH"):
        execute_remote(second_prepared, RootMismatchTransport(run_worker))


def test_installed_worker_rejects_legacy_stale_preflight_manifest(tmp_path):
    manifest = {
        "run_id": "stale-preflight",
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
        "adapter_id": "tep_fixture",
    }
    source = tmp_path / "stale.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(
        ValueError, match="controller-bound absolute remote_root required"
    ):
        run_worker(source)


def test_malformed_manifest_replay_does_not_overwrite_failure_receipt(tmp_path):
    remote_root = tmp_path / "malformed-remote"
    remote_root.mkdir()
    manifest_path = tmp_path / "malformed.json"
    manifest_path.write_text(
        json.dumps({"run_id": "malformed", "remote_root": str(remote_root)}),
        encoding="utf-8",
    )

    first = run_worker(manifest_path)
    receipt_path = tmp_path / "malformed.REMOTE_EXECUTION_RECEIPT.json"
    original = receipt_path.read_bytes()

    assert first["failure_code"] == "MANIFEST_INVALID"
    import pytest

    with pytest.raises(ValueError, match="IMMUTABLE_RECEIPT_EXISTS"):
        run_worker(manifest_path)
    assert receipt_path.read_bytes() == original


def test_installed_worker_rejects_legacy_post_drift_manifest(tmp_path):
    manifest = {
        "run_id": "post-drift",
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
        "adapter_id": "tep_fixture",
    }
    source = tmp_path / "post-drift.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(
        ValueError, match="controller-bound absolute remote_root required"
    ):
        run_worker(source)
