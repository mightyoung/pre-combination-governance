from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace

import pytest
from rfb.contracts.canonical_json import canonical_bytes, sha256_hex
from rfb.orchestration.report import C2ReportBuilder, atomic_write_report
from rfb.orchestration.segment import (
    PANEL_METHODS,
    real_tep_panel_provider,
    validate_manifest,
    validate_trusted_probe,
)


def manifest(root):
    value = {
        "dataset_domain": "TEP",
        "bundle_count": 1,
        "panel": list(PANEL_METHODS),
        "D_test": False,
        "input_sha256": "a" * 64,
        "allocation_commitment": "b" * 64,
        "segment_root_base": str(root),
        "segment_id": "segment-1",
        "run_id": "run-1",
        "probe_mount": "test-mount",
        "probe_owner": "test-owner",
        "probe_mode": "0700",
        "execution_mode": "REAL_TEP_NONCONFIRMATORY",
    }
    value["manifest_sha256"] = sha256_hex(canonical_bytes(value))
    return value


def signed_probe(manifest_value):
    unsigned = {
        "probe_id": "probe-1",
        "source": "capacity-producer",
        "signer": "capacity-producer",
        "key_id": "capacity-key",
        "role": "capacity",
        "revocation_epoch": 0,
        "implementation_sha256": "c" * 64,
        "manifest_sha256": manifest_value["manifest_sha256"],
        "segment_id": manifest_value["segment_id"],
        "root": str(
            __import__("pathlib").Path(manifest_value["segment_root_base"])
            / manifest_value["segment_id"]
        ),
        "mount": "test-mount",
        "owner": "test-owner",
        "mode": "0700",
        "run_id": manifest_value["run_id"],
        "sampled_at": 1.0,
        "process_telemetry": {
            "gpu_processes": [],
            "owned_processes": [],
            "owned_gpu_processes": [],
        },
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
    unsigned["artifact_sha256"] = sha256_hex(canonical_bytes(unsigned))
    signature_body = {k: v for k, v in unsigned.items() if k != "artifact_sha256"}
    return {
        **unsigned,
        "signature": hmac.new(
            b"secret", canonical_bytes(signature_body), hashlib.sha256
        ).hexdigest(),
    }


@pytest.mark.parametrize(
    "field", ["manifest_sha256", "input_sha256", "allocation_commitment"]
)
def test_manifest_requires_all_commitments(tmp_path, field):
    value = manifest(tmp_path)
    value.pop(field)
    with pytest.raises(ValueError):
        validate_manifest(value)


@pytest.mark.parametrize(
    "field",
    [
        "run_id",
        "process_telemetry",
        "gpu_used",
        "project_tree_allocated_bytes",
        "filesystem_used_delta_bytes",
        "owned_external_layers_bytes",
        "open_deleted_bytes",
        "planning_peak_bytes",
        "subbudget_usage",
    ],
)
def test_probe_requires_complete_runtime_evidence(tmp_path, field):
    value = manifest(tmp_path)
    probe = signed_probe(value)
    probe.pop(field)
    with pytest.raises(ValueError):
        validate_trusted_probe(
            probe,
            manifest_sha256=value["manifest_sha256"],
            manifest=value,
            trust_keys={
                "capacity-key": {"secret": "secret", "role": "capacity", "epoch": 0}
            },
        )


@pytest.mark.parametrize(
    "trust_record",
    [
        "secret",
        {"secret": "secret"},
        {"secret": "secret", "role": "other", "epoch": 0},
        {"secret": "secret", "role": "capacity", "epoch": 1},
    ],
)
def test_probe_rejects_legacy_or_mismatched_trust_records(tmp_path, trust_record):
    value = manifest(tmp_path)
    probe = signed_probe(value)
    with pytest.raises(ValueError):
        validate_trusted_probe(
            probe,
            manifest_sha256=value["manifest_sha256"],
            manifest=value,
            trust_keys={"capacity-key": trust_record},
        )


def test_real_provider_uses_segment_local_dataset_and_runs_once(tmp_path):
    value = manifest(tmp_path)
    dataset = tmp_path / "segment-1" / "dataset"
    dataset.mkdir(parents=True)
    calls = {"loader": [], "runner": [], "durable": []}

    class Loader:
        def load(self, data_dir, **kwargs):
            calls["loader"].append((data_dir, kwargs))
            return [
                SimpleNamespace(
                    value=[1.0],
                    unit="u",
                    t_gen=1.0,
                    feature_of_interest="tep",
                    procedure="fixture",
                    quality={"completeness": 1.0},
                    metadata={},
                )
            ]

    class Runner:
        def run_all(self, **kwargs):
            calls["runner"].append(kwargs)
            bundle = kwargs["bundle_id"]
            seed = kwargs["seed"]
            return SimpleNamespace(
                rows={
                    (bundle, method_id, seed): {
                        "bundle_id": bundle,
                        "method_id": method_id,
                        "algorithm_seed": seed,
                        "output_sha256": str(index) * 64,
                    }
                    for index, method_id in enumerate(PANEL_METHODS, start=1)
                }
            )

    def seal(rows, **kwargs):
        calls["durable"].append((rows, kwargs))
        return {"manifest_sha256": value["manifest_sha256"]}

    rows = real_tep_panel_provider(
        value,
        loader=Loader(),
        formal_runner=Runner(),
        durable_package_provider=seal,
    )
    assert calls["loader"][0][0] == str(dataset.resolve())
    assert len(calls["runner"]) == 1
    assert calls["runner"][0]["transaction_id"] == "c2-run-1"
    assert calls["runner"][0]["truth"] is None
    durable_kwargs = calls["durable"][0][1]
    assert durable_kwargs["manifest"] == value
    assert durable_kwargs["segment_root"] == str((tmp_path / "segment-1").resolve())
    assert durable_kwargs["run_id"] == "run-1"
    assert len(durable_kwargs["formal_rows"]) == 7
    assert {row["method_id"] for row in rows} == set(PANEL_METHODS)
    assert all(
        row["durable_manifest_sha256"] == value["manifest_sha256"] for row in rows
    )


def report_inputs():
    rows = [
        {
            "method_id": method_id,
            "terminal_state": "SEALED",
            "panel_closed": True,
            "result_sha256": "e" * 64,
            "durable_manifest_sha256": "f" * 64,
        }
        for method_id in PANEL_METHODS
    ]
    telemetry = [
        {"state": "PLANNED", "sampled_at": 0},
        {"state": "ADMITTED", "sampled_at": 1},
        {"state": "MATERIALIZING", "sampled_at": 2},
        {
            "state": "EXECUTING",
            "sampled_at": 3,
            "capacity_bytes": 1,
            "gpu_used": False,
            "gpu_not_used": True,
        },
        {
            "state": "RESULT_SEALED_LOCAL",
            "sampled_at": 4,
            "capacity_bytes": 1,
            "gpu_used": False,
            "gpu_not_used": True,
        },
    ]
    return rows, telemetry


def test_report_rejects_unknown_row_field_and_bad_hash(tmp_path):
    value = manifest(tmp_path)
    rows, telemetry = report_inputs()
    rows[0]["secret_alias"] = "x"
    with pytest.raises(ValueError):
        C2ReportBuilder(value).build(
            {"terminal_rows": rows, "capacity_transitions": telemetry[-2:]}, telemetry
        )
    rows, telemetry = report_inputs()
    rows[0]["result_sha256"] = "bad"
    with pytest.raises(ValueError):
        C2ReportBuilder(value).build(
            {"terminal_rows": rows, "capacity_transitions": telemetry[-2:]}, telemetry
        )


def test_report_parent_fsync_failure_is_fail_closed(tmp_path):
    class FailingDurability:
        def fsync_dir(self, path):
            raise OSError("forced")

    with pytest.raises(OSError, match="parent directory fsync"):
        atomic_write_report(
            tmp_path / "report.json",
            {
                "classification": "NONCONFIRMATORY_SIZING_ONLY",
                "live_gate_effect": "NONE",
            },
            durability_provider=FailingDurability(),
        )


def test_real_provider_rejects_durable_manifest_mismatch(tmp_path):
    value = manifest(tmp_path)
    with pytest.raises(ValueError, match="durable package manifest"):
        real_tep_panel_provider(
            value,
            loader=type(
                "L",
                (),
                {
                    "load": lambda self, *a, **k: [
                        SimpleNamespace(
                            value=[1],
                            unit="u",
                            t_gen=1,
                            feature_of_interest="f",
                            procedure="p",
                            quality={},
                            metadata={},
                        )
                    ]
                },
            )(),
            formal_runner=type(
                "R",
                (),
                {
                    "run_all": lambda self, **k: SimpleNamespace(
                        rows={
                            (k["bundle_id"], m, k["seed"]): {"method_id": m}
                            for m in PANEL_METHODS
                        }
                    )
                },
            )(),
            durable_package_provider=lambda *a, **k: {"manifest_sha256": "d" * 64},
        )
