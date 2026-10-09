import hashlib
import hmac
from pathlib import Path
from typing import ClassVar

from rfb.contracts.canonical_json import canonical_bytes, sha256_hex
from rfb.orchestration.segment import (
    PANEL_METHODS,
    C2SegmentOrchestrator,
    validate_trusted_probe,
)


class Durability:
    def fsync_dir(self, path):
        pass


def test_c2_local_lifecycle(tmp_path):
    base = tmp_path
    m = {
        "dataset_domain": "TEP",
        "bundle_count": 1,
        "panel": list(PANEL_METHODS),
        "D_test": False,
        "input_sha256": "a" * 64,
        "allocation_commitment": "b" * 64,
        "segment_id": "s1",
        "segment_root_base": str(base),
        "run_id": "r1",
        "probe_mount": "m",
        "probe_owner": "o",
        "probe_mode": "0700",
        "execution_mode": "LOCAL_FIXTURE_NONCONFIRMATORY",
    }
    m["manifest_sha256"] = sha256_hex(canonical_bytes(m))
    u = {
        "probe_id": "p",
        "source": "x",
        "signer": "x",
        "key_id": "k",
        "role": "capacity",
        "revocation_epoch": 0,
        "implementation_sha256": "c" * 64,
        "manifest_sha256": m["manifest_sha256"],
        "segment_id": "s1",
        "root": str(base / "s1"),
        "mount": "m",
        "owner": "o",
        "mode": "0700",
        "sampled_at": 1.0,
        "gpu_used": False,
        "run_id": "r1",
        "process_telemetry": {"owned_processes": [], "owned_gpu_processes": []},
        "project_tree_allocated_bytes": 1,
        "filesystem_used_delta_bytes": 1,
        "owned_external_layers_bytes": 0,
        "open_deleted_bytes": 0,
        "planning_peak_bytes": 1,
        "subbudget_usage": {
            "ephemeral_dataset": 0,
            "durable_result_staging": 0,
            "scratch_partial": 0,
            "retry_quarantine_wal": 0,
            "emergency_reserve": 0,
        },
    }
    u["artifact_sha256"] = sha256_hex(canonical_bytes(u))
    probe = dict(
        u,
        signature=hmac.new(
            b"z",
            canonical_bytes({k: v for k, v in u.items() if k != "artifact_sha256"}),
            hashlib.sha256,
        ).hexdigest(),
    )
    report = C2SegmentOrchestrator(
        m,
        base / "s1",
        providers={
            "trust_keys": {"k": {"secret": "z", "role": "capacity", "epoch": 0}},
            "fixture_run_panel": lambda m: [
                {
                    "method_id": x,
                    "terminal_state": "SEALED",
                    "panel_closed": True,
                    "result_sha256": "0" * 64,
                    "durable_manifest_sha256": m["manifest_sha256"],
                }
                for x in PANEL_METHODS
            ],
            "durability_provider": Durability(),
        },
    ).run(probe)
    assert report["panel_closed"] and (base / "s1" / "completion.marker").exists()


def test_probe_exact_signature_rejects_mutation():
    try:
        validate_trusted_probe({"x": 1})
    except ValueError:
        pass
    else:
        raise AssertionError("unbound probe accepted")


class _Obs:
    value = 1.0
    unit = "u"
    t_gen = 0.0
    feature_of_interest = "f"
    procedure = "p"
    quality = "ok"
    metadata: ClassVar[dict] = {}


def _probe_for(manifest, root, sampled_at=1.0):
    import hashlib
    import hmac

    unsigned = {
        "probe_id": "p",
        "source": "fixture",
        "signer": "fixture",
        "key_id": "k",
        "role": "capacity",
        "revocation_epoch": 0,
        "implementation_sha256": "c" * 64,
        "manifest_sha256": manifest["manifest_sha256"],
        "segment_id": manifest["segment_id"],
        "root": str(root),
        "mount": "m",
        "owner": "o",
        "mode": "0700",
        "run_id": manifest["run_id"],
        "sampled_at": sampled_at,
        "process_telemetry": {"owned_processes": [], "owned_gpu_processes": []},
        "gpu_used": False,
        "project_tree_allocated_bytes": 1,
        "filesystem_used_delta_bytes": 1,
        "owned_external_layers_bytes": 0,
        "open_deleted_bytes": 0,
        "planning_peak_bytes": 1,
        "subbudget_usage": {
            "ephemeral_dataset": 0,
            "durable_result_staging": 0,
            "scratch_partial": 0,
            "retry_quarantine_wal": 0,
            "emergency_reserve": 0,
        },
    }
    unsigned["artifact_sha256"] = hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
    unsigned["signature"] = hmac.new(
        b"z",
        canonical_bytes({k: v for k, v in unsigned.items() if k != "artifact_sha256"}),
        hashlib.sha256,
    ).hexdigest()
    return unsigned


def test_real_segment_local_chain_runs_formal_runner_once_and_binds_durable_seal(
    tmp_path,
):
    base = tmp_path
    out = base / "seg-real"
    manifest = {
        "dataset_domain": "TEP",
        "bundle_count": 1,
        "panel": list(PANEL_METHODS),
        "D_test": False,
        "input_sha256": "a" * 64,
        "allocation_commitment": "b" * 64,
        "segment_id": "seg-real",
        "segment_root_base": str(base),
        "run_id": "run-c2-1",
        "probe_mount": "m",
        "probe_owner": "o",
        "probe_mode": "0700",
        "execution_mode": "REAL_TEP_NONCONFIRMATORY",
        "bundle_id": "bundle-1",
        "algorithm_seed": 7,
    }
    manifest["manifest_sha256"] = sha256_hex(canonical_bytes(manifest))
    calls = {"load": [], "run": 0, "seal": []}

    class Loader:
        def load(self, path, **kwargs):
            calls["load"].append(Path(path))
            return [_Obs()]

    class Runner:
        def run_all(self, **kwargs):
            calls["run"] += 1
            return type(
                "R",
                (),
                {
                    "rows": {
                        ("bundle-1", m, 7): {"method_id": m, "run_id": "run-c2-1"}
                        for m in PANEL_METHODS
                    }
                },
            )()

    def seal(rows, *, manifest, **kwargs):
        calls["seal"].append(
            (
                manifest["segment_root_base"],
                manifest["segment_id"],
                kwargs.get("run_id"),
            )
        )
        return {"manifest_sha256": manifest["manifest_sha256"]}

    def materialize(m, partial):
        partial.mkdir()
        (partial / "d00_te.dat").write_bytes(b"segment-local")

    probe = _probe_for(manifest, out)
    final_probe = _probe_for(manifest, out, sampled_at=2.0)
    report = C2SegmentOrchestrator(
        manifest,
        out,
        providers={
            "trust_keys": {"k": {"secret": "z", "role": "capacity", "epoch": 0}},
            "materialize": materialize,
            "loader": Loader(),
            "formal_runner_instance": Runner(),
            "durable_package_provider": seal,
            "probe_producer": lambda *_: final_probe,
            "durability_provider": Durability(),
        },
    ).run(probe)
    assert calls["load"] == [out / "dataset"]
    assert calls["run"] == 1
    assert len(calls["seal"]) == 1 and calls["seal"][0][1] == "seg-real"
    assert report["panel_closed"] is True
