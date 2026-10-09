from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from rfb.research.mme_events import METHOD_IDS, generate_experiment
from rfb.research.mme_runner import (
    MMERunConfig,
    _run_method_prefixes,
    _validated_config,
    run_mme,
)


def _one_prefix_block(run_class: str = "D_impl_unit"):
    block = generate_experiment(run_class)[0]
    return replace(block, prefixes=block.prefixes[:1])


def _config(workspace: Path, *, run_id: str = "runner-test") -> dict[str, object]:
    design = workspace / "design.json"
    source = workspace / "source.py"
    input_path = workspace / "input.json"
    design.write_text("{}", encoding="utf-8")
    source.write_text("VERSION = 1\n", encoding="utf-8")
    input_path.write_text("{}", encoding="utf-8")
    return {
        "workspace_root": str(workspace),
        "output_root": str(workspace / "outputs"),
        "run_class": "D_impl_unit",
        "run_id": run_id,
        "source_paths": [str(source)],
        "design_paths": [str(design)],
        "input_paths": [str(input_path)],
        "deterministic_replay": False,
    }


@pytest.mark.parametrize("run_class", ["D_test", "D_actual", "unknown"])
def test_runner_rejects_non_mme_run_classes(run_class, tmp_path):
    with pytest.raises(ValueError, match="run_class"):
        _validated_config(
            {
                "workspace_root": str(tmp_path),
                "output_root": str(tmp_path / "out"),
                "run_class": run_class,
            }
        )


@pytest.mark.parametrize("field", ["method_cpu_seconds", "method_wall_seconds"])
def test_runner_rejects_non_finite_limits(field, tmp_path):
    with pytest.raises(ValueError, match="limits"):
        _validated_config(
            {
                "workspace_root": str(tmp_path),
                "output_root": str(tmp_path / "out"),
                "run_class": "D_impl_unit",
                field: float("nan"),
            }
        )


def test_isolated_process_denies_truth_and_oracle_source_reads(tmp_path):
    secret = tmp_path / "truth-sidecar.json"
    secret.write_text('{"truth":1}', encoding="utf-8")
    source_root = Path(__file__).resolve().parents[1] / "src"
    process_module = source_root / "rfb" / "research" / "mme_process.py"
    oracle = source_root / "rfb" / "research" / "mme_oracle.py"
    script = (
        "import sys;from pathlib import Path;"
        f"sys.path.insert(0,{str(source_root)!r});"
        "from rfb.research.mme_process import _install_read_boundary;"
        f"_install_read_boundary(Path({str(source_root)!r}));"
        f"Path({str(secret)!r}).read_bytes()"
    )
    denied_truth = subprocess.run(
        [sys.executable, "-I", "-c", script], capture_output=True, text=True
    )
    source_script = script.rsplit(";", 1)[0] + f";Path({str(oracle)!r}).read_bytes()"
    denied_oracle = subprocess.run(
        [sys.executable, "-I", "-c", source_script], capture_output=True, text=True
    )
    assert process_module.is_file()
    assert denied_truth.returncode != 0
    assert "MME_METHOD_FILESYSTEM_READ_DENIED" in denied_truth.stderr
    assert denied_oracle.returncode != 0
    assert "MME_METHOD_SCORER_SOURCE_READ_DENIED" in denied_oracle.stderr


def test_real_method_process_uses_public_prefix_and_real_resource_sampling():
    block = _one_prefix_block()
    prefix = block.prefixes[0]
    assert not {
        "truth",
        "truth_sidecar",
        "oracle",
        "block_id",
        "arm_id",
        "prefix_id",
        "prefix_index",
    }.intersection(prefix.method_payload())
    required = 1_000_000_000 + 256 * 1024 * 1024
    import psutil

    if psutil.virtual_memory().available < required:
        pytest.skip("host memory below the runner's real launch threshold")
    rows = _run_method_prefixes(
        "Proposed",
        (prefix,),
        MMERunConfig(
            output_root="outputs",
            deterministic_replay=True,
            method_wall_seconds=20.0,
            method_cpu_seconds=10.0,
            method_memory_bytes=1_000_000_000,
        ),
    )
    assert rows[0]["status"] == "SUCCEEDED"
    assert rows[0]["replay_verified"] is True
    assert rows[0]["measurements"]["peak_rss_bytes"] > 0
    assert rows[0]["measurements"]["cpu_seconds"] >= 0


def test_run_seals_methods_before_truth_scoring_and_tampered_resume_retries(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = _config(workspace)
    block = _one_prefix_block()

    def fake_method(method_id, prefixes, _cfg):
        return [
            {
                "prefix_id": prefix.prefix_id,
                "status": "SUCCEEDED",
                "failure_code": None,
                "output": {
                    "method_id": method_id,
                    "status": "SUCCEEDED",
                    "failure_code": None,
                    "risk_interval": [0.5, 1.0],
                    "action_state": ["REVIEW"],
                },
                "measurements": {
                    "wall_seconds": 0.01,
                    "cpu_seconds": 0.01,
                    "peak_rss_bytes": 1,
                    "sampling_interval_seconds": 0.005,
                    "platform": sys.platform,
                },
            }
            for prefix in prefixes
        ]

    monkeypatch.setattr("rfb.research.mme_runner._run_method_prefixes", fake_method)
    scoring_calls = []

    def scorer(sidecar, rows):
        attempt = workspace / "outputs" / "runner-test" / "attempts" / "attempt-0001"
        sealed = attempt / "blocks" / block.block_id / "method_outputs.json"
        assert sealed.is_file()
        assert not list(attempt.rglob("*truth*"))
        scoring_calls.append((sidecar.block_id, tuple(rows)))
        return {"status": "SCORED", "method_count": len(rows)}

    first = run_mme(config, blocks=(block,), scorer=scorer)
    resumed = run_mme(config, blocks=(block,), scorer=scorer, resume=True)
    assert first["status"] == "SUCCEEDED"
    assert first["method_slot_count"] == len(METHOD_IDS)
    assert resumed["deduplicated_resume"] is True
    assert len(scoring_calls) == 1

    methods_path = (
        workspace
        / "outputs"
        / "runner-test"
        / "attempts"
        / "attempt-0001"
        / "blocks"
        / block.block_id
        / "method_outputs.json"
    )
    methods_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="SEALED_ATTEMPT_INTEGRITY_FAILURE"):
        run_mme(config, blocks=(block,), scorer=scorer, resume=True)
    assert not (
        workspace / "outputs" / "runner-test" / "attempts" / "attempt-0002"
    ).exists()


def test_unsupported_block_preserves_all_unexecuted_slots(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = _config(workspace, run_id="unsupported")
    block = replace(_one_prefix_block(), generation_status="NOT_IMPLEMENTED_SCOPE_BOUNDARY")

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("unsupported block launched a method")

    monkeypatch.setattr("rfb.research.mme_runner._run_method_prefixes", must_not_run)
    result = run_mme(
        config,
        blocks=(block,),
        scorer=lambda _truth, _rows: {"status": "NOT_SCORED"},
    )
    assert result["terminal_state"] == "COMPLETED_WITH_FAILURES"
    assert result["method_terminal_counts"] == {"UNEXECUTED": len(METHOD_IDS)}
    rows = json.loads(
        (
            workspace
            / "outputs"
            / "unsupported"
            / "attempts"
            / "attempt-0001"
            / "blocks"
            / block.block_id
            / "method_outputs.json"
        ).read_text(encoding="utf-8")
    )
    assert all(
        prefix["failure_code"] == "NOT_IMPLEMENTED_SCOPE_BOUNDARY"
        for method in rows.values()
        for prefix in method["prefixes"]
    )
