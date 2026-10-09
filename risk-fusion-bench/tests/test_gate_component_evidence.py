from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

from jsonschema import Draft202012Validator

import rfb.gate_evidence as gate_evidence
from rfb.contracts.canonical_json import canonical_bytes
from rfb.gate_evidence import (
    METHOD_IDS,
    generate_component_evidence,
    refresh_runtime_freeze,
    update_gate_checklist,
)
from rfb.regeneration import RuntimeCommitmentAuthority


TRUST_STORE = {
    "key_id": "regen-attester-1",
    "role": "RegenerationAttester",
    "trust_epoch": "dev-1",
    "secret": "development-attester-secret-123",
    "independent_key_ids": ["regen-attester-1"],
}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _temporary_bench(tmp_path: Path) -> Path:
    bench = tmp_path / "bench"
    contracts_source = Path(__file__).parents[1] / "src/rfb/contracts"
    contracts_target = bench / "src/rfb/contracts"
    contracts_target.parent.mkdir(parents=True)
    shutil.copytree(contracts_source, contracts_target)
    (bench / "tests").mkdir()
    (bench / "tests/test_marker.py").write_text("def test_marker(): pass\n")
    return bench


def test_generate_component_evidence_closes_development_contracts(tmp_path):
    bench = _temporary_bench(tmp_path)
    output = bench / "outputs/gate_components"
    archive_b = tmp_path / "explicit-archive-b"
    summary = generate_component_evidence(
        bench,
        output,
        archive_b,
        "2026-07-19T00:00:00Z",
    )
    assert summary["status"] == "DEVELOPMENT_COMPONENT_EVIDENCE_PASS"
    assert summary["formal_experiment_result"] is False
    assert summary["formal_stage_admission_created"] is False

    expected_artifacts = (
        "capacity/capacity_telemetry.jsonl",
        "capacity/capacity_probe_qa.json",
        "durable_result/fixture_package/durable_rows.jsonl",
        "durable_result/fixture_package/durable_result_manifest.json",
        "durable_result/raw_dataset_exclusion_qa.json",
        "durable_result/durable_result_schema_qa.json",
        "archive/result_archive_targets.json",
        "archive/result_archive_ab_qa.json",
        "regeneration/regeneration_sampling_qa.json",
        "purge/dataset_purge_ledger.jsonl",
        "purge/dataset_purge_ledger.json",
        "purge/dataset_purge_tombstone.json",
        "closeout/fixture_package/segment_closeout_manifest.json",
        "closeout/segment_closeout_qa.json",
        "gate_component_evidence_summary.json",
    )
    assert all((output / relative).is_file() for relative in expected_artifacts)
    assert not (output / "purge/controlled_fixture_dataset").exists()
    assert all(
        not (output / relative).read_bytes().startswith(b"\xef\xbb\xbf")
        for relative in expected_artifacts
    )
    component_status = summary["component_status"]
    assert component_status["regeneration"] == "PASS"
    assert component_status["purge"] == "PASS"
    assert component_status["closeout"] == "PASS"
    regeneration = _json(output / "regeneration/regeneration_sampling_qa.json")
    assert regeneration["development_status"] == "PASS"
    assert regeneration["live_status"] == "PENDING"
    purge_ledger = _json(output / "purge/dataset_purge_ledger.json")
    purge_tombstone = _json(output / "purge/dataset_purge_tombstone.json")
    assert purge_ledger["events"][-1]["event"] == "PURGE_COMMITTED"
    assert purge_tombstone["pass"] is True
    assert purge_tombstone["live_status"] == "PENDING"
    closeout = _json(output / "closeout/segment_closeout_qa.json")
    closeout_manifest = _json(
        output / "closeout/fixture_package/segment_closeout_manifest.json"
    )
    assert closeout["development_status"] == "PASS"
    assert closeout["live_status"] == "PENDING"
    assert closeout["formal_stage_admission_created"] is False
    assert closeout_manifest["development_only"] is True
    assert closeout_manifest["contains_raw_dataset"] is False

    rows = [
        json.loads(line)
        for line in (output / "durable_result/fixture_package/durable_rows.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["method_id"] for row in rows] == list(METHOD_IDS)
    assert len(rows) == 7
    assert all(row["contains_raw_dataset"] is False for row in rows)
    assert all(
        row["prediction_or_decision"]["evidence_class"]
        == "DEVELOPMENT_FIXTURE_NOT_EXPERIMENT_RESULT"
        for row in rows
    )
    manifest = _json(
        output / "durable_result/fixture_package/durable_result_manifest.json"
    )
    manifest_schema = _json(
        bench / "src/rfb/contracts/durable_result_manifest.schema.json"
    )
    Draft202012Validator(manifest_schema).validate(manifest)
    assert manifest["row_count"] == 7
    assert manifest["contains_raw_dataset"] is False

    raw_qa = _json(output / "durable_result/raw_dataset_exclusion_qa.json")
    assert raw_qa["development_status"] == "PASS"
    assert {case["case_id"] for case in raw_qa["cases"]} == {
        "path",
        "nested_json",
        "jsonl",
        "binary",
        "unsupported",
        "arbitrary",
    }
    assert all(case["rejected"] is True for case in raw_qa["cases"])

    archive_config = _json(output / "archive/result_archive_targets.json")
    archive_schema = _json(
        bench / "src/rfb/contracts/result_archive_targets.schema.json"
    )
    Draft202012Validator(archive_schema).validate(archive_config)
    archive_qa = _json(output / "archive/result_archive_ab_qa.json")
    assert archive_qa["pass"] is True
    assert archive_qa["development_status"] == "PASS"
    assert archive_qa["local_live_gate_passed"] is False
    assert archive_qa["live_status"] == "PENDING"

    capacity = [
        json.loads(line)
        for line in (output / "capacity/capacity_telemetry.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    cases = {item.get("case_id"): item for item in capacity if "case_id" in item}
    assert cases["planning_exact_22gb"]["capacity_bytes"] == 22_000_000_000
    assert cases["planning_exact_22gb"]["state"] == "NORMAL"
    assert cases["drain_exact_24gb"]["capacity_bytes"] == 24_000_000_000
    assert cases["drain_exact_24gb"]["state"] == "DRAIN_AND_SEAL"
    assert cases["drain_exact_25gb"]["capacity_bytes"] == 25_000_000_000
    assert cases["drain_exact_25gb"]["state"] == "DRAIN_AND_SEAL"
    assert cases["halt_25gb_plus_1"]["capacity_bytes"] == 25_000_000_001
    assert cases["halt_25gb_plus_1"]["state"] == "SAFE_HALT_CAP_BREACH"
    measured = capacity[0]
    assert measured["evidence_class"] == "DEVELOPMENT_LOCAL_TRUSTED_MEASUREMENT"
    assert measured["owned_external_layers_bytes"] == 0
    assert measured["open_deleted_bytes"] == 0
    assert measured["windows_open_deleted_claimed_measured"] is False


def test_generation_reuses_frozen_runtime_authority_without_rewriting(tmp_path):
    """Evidence generation must not replace a previously frozen runtime."""
    bench = _temporary_bench(tmp_path)
    output = bench / "outputs/gate_components"
    archive_b = tmp_path / "explicit-archive-b"
    generate_component_evidence(bench, output, archive_b, "2026-07-19T00:00:00Z")
    runtime = bench / "outputs/runtime_gate"
    frozen = {
        name: (runtime / name).read_bytes()
        for name in (
            "source_tree_manifest.json",
            "runtime_baseline.json",
            "method_registry.json",
            "container_lock.json",
            "seed_commitment.json",
            "allocation_commitment.json",
        )
    }
    authority = RuntimeCommitmentAuthority.load(
        bench,
        generator_path="src/rfb/g004_evidence.py",
        segment_config_path="development_regeneration_config.json",
    )
    generate_component_evidence(bench, output, archive_b, "2026-07-19T00:01:00Z")
    assert {name: (runtime / name).read_bytes() for name in frozen} == frozen
    qa = _json(output / "regeneration/regeneration_sampling_qa.json")
    assert qa["runtime_authority"] == authority.to_dict()
    baseline = _json(runtime / "runtime_baseline.json")
    unsigned = {
        key: value
        for key, value in baseline.items()
        if key != "runtime_baseline_sha256"
    }
    assert (
        baseline["runtime_baseline_sha256"]
        == hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
    )
    assert not Path(qa["runtime_authority"]["runtime_baseline_path"]).is_absolute()
    summary = _json(output / "gate_component_evidence_summary.json")
    assert summary["output_root"] == "outputs/gate_components"
    assert summary["archive_b_root"] == "EXPLICIT_DEVELOPMENT_ARCHIVE_B"

    persisted_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in output.rglob("*")
        if path.is_file() and path.suffix in {".json", ".jsonl"}
    )
    assert "rfb-g004-fixture-" not in persisted_text
    assert "controlled_fixture_dataset" not in persisted_text


def test_cli_refreshes_runtime_before_generating_evidence(tmp_path, monkeypatch):
    bench = tmp_path / "bench"
    bench.mkdir()
    checklist = tmp_path / "GateChecklist-v6.13.json"
    checklist.write_text("{}", encoding="utf-8")
    calls: list[str] = []

    def refresh(_bench):
        calls.append("refresh")
        return {}

    def generate(_bench, _output, _archive_b, _now):
        calls.append("generate")
        return {}

    def update(_checklist, _relative, _now):
        calls.append("update")
        return {}

    monkeypatch.setattr(gate_evidence, "refresh_runtime_freeze", refresh)
    monkeypatch.setattr(gate_evidence, "generate_component_evidence", generate)
    monkeypatch.setattr(gate_evidence, "update_gate_checklist", update)
    assert (
        gate_evidence.main(
            [
                "--bench-root",
                str(bench),
                "--output-root",
                "outputs/gate_components",
                "--archive-b-root",
                str((tmp_path / "archive-b").resolve()),
                "--gate-checklist",
                str(checklist),
                "--refresh-runtime-freeze",
                "--update-checklist",
            ]
        )
        == 0
    )
    assert calls == ["refresh", "generate", "update"]


def _task(task_id: str, status: str = "PENDING") -> dict[str, object]:
    return {"id": task_id, "status": status, "evidence": []}


def test_update_gate_checklist_is_conservative(tmp_path):
    checklist = {
        "status": "FORMAL_EXPERIMENT_BLOCKED",
        "runtime_gate": {"status": "PASS", "tasks": []},
        "segment_cap_gate": {
            "status": "PENDING",
            "tasks": [
                _task("C0"),
                _task("C1"),
                _task("C2", "BLOCKED_BY_RUNTIME_GATE"),
                _task("C3", "BLOCKED_BY_C2"),
            ],
        },
        "durable_result_gate": {
            "status": "PENDING",
            "tasks": [_task("R0"), _task("R1"), _task("R2")],
        },
        "result_archive_gate": {
            "status": "PENDING",
            "tasks": [_task("B0"), _task("B1"), _task("B2")],
        },
        "regeneration_gate": {"status": "PENDING", "tasks": [_task("G0"), _task("G1")]},
        "dataset_purge_gate": {
            "status": "PENDING",
            "tasks": [_task(task_id) for task_id in ("P0", "P1", "P2", "P3")],
        },
        "formal_stage_admission": {"status": "BLOCKED"},
    }
    path = tmp_path / "GateChecklist-v6.13.json"
    path.write_bytes(canonical_bytes(checklist) + b"\n")
    bench = _temporary_bench(tmp_path)
    generate_component_evidence(
        bench,
        bench / "outputs/gate_components",
        tmp_path / "archive-b",
        "2026-07-19T00:00:00Z",
    )
    updated = update_gate_checklist(
        path, "bench/outputs/gate_components", "2026-07-19T00:00:00Z"
    )
    assert updated["status"] == "FORMAL_EXPERIMENT_BLOCKED"
    assert updated["formal_stage_admission"]["status"] == "BLOCKED"
    assert all(
        updated[name]["status"] == "PENDING"
        for name in (
            "segment_cap_gate",
            "durable_result_gate",
            "result_archive_gate",
            "regeneration_gate",
            "dataset_purge_gate",
        )
    )
    tasks = {
        task["id"]: task
        for gate_name in (
            "segment_cap_gate",
            "durable_result_gate",
            "result_archive_gate",
        )
        for task in updated[gate_name]["tasks"]
    }
    for task_id in ("C0", "C1", "R0", "R1", "R2", "B0", "B1", "B2"):
        assert tasks[task_id]["development_status"] == "PASS"
        assert tasks[task_id]["live_status"] == "PENDING"
        assert tasks[task_id]["development_evidence"]
    g004_tasks = {
        task["id"]: task
        for gate_name in ("regeneration_gate", "dataset_purge_gate")
        for task in updated[gate_name]["tasks"]
    }
    for task_id in ("G0", "G1", "P0", "P1", "P2", "P3"):
        assert g004_tasks[task_id]["development_status"] == "PASS"
        assert g004_tasks[task_id]["live_status"] == "PENDING"
        assert g004_tasks[task_id]["development_evidence"]
    assert any(
        item.endswith("purge/dataset_purge_tombstone.json")
        for item in g004_tasks["P3"]["development_evidence"]
    )
    assert any(
        item.endswith("closeout/segment_closeout_qa.json")
        for item in g004_tasks["P3"]["development_evidence"]
    )
    assert tasks["C2"]["status"] == "READY_FOR_NONCONFIRMATORY_SIZING_SMOKE"
    assert tasks["C3"]["status"] == "BLOCKED_BY_C2"
    assert not (tmp_path / "FORMAL_STAGE_ADMISSION-v6.13.json").exists()
    assert path.read_bytes().endswith(b"\n")
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_refresh_runtime_freeze_hashes_source_schemas_and_self(tmp_path):
    bench = tmp_path / "bench"
    (bench / "src/rfb/contracts").mkdir(parents=True)
    (bench / "tests/__pycache__").mkdir(parents=True)
    (bench / "outputs/runtime_gate").mkdir(parents=True)
    (bench / "src/rfb/example.py").write_bytes(b"VALUE = 1\n")
    (bench / "tests/test_example.py").write_bytes(b"def test_value(): pass\n")
    (bench / "tests/__pycache__/ignored.pyc").write_bytes(b"ignored")
    method_schema = bench / "src/rfb/contracts/method_output.schema.json"
    archive_schema = bench / "src/rfb/contracts/result_archive_targets.schema.json"
    regeneration_schema = (
        bench / "src/rfb/contracts/regeneration_sampling_qa.schema.json"
    )
    purge_ledger_schema = bench / "src/rfb/contracts/dataset_purge_ledger.schema.json"
    purge_tombstone_schema = (
        bench / "src/rfb/contracts/dataset_purge_tombstone.schema.json"
    )
    method_schema.write_bytes(b"{}\n")
    archive_schema.write_bytes(b'{"type":"object"}\n')
    regeneration_schema.write_bytes(b'{"type":"object"}\n')
    purge_ledger_schema.write_bytes(b'{"type":"object"}\n')
    purge_tombstone_schema.write_bytes(b'{"type":"object"}\n')
    baseline = {
        "schema_version": "1.0.0",
        "code_baseline": {},
        "schemas": [
            {"path": "src/rfb/contracts/method_output.schema.json", "sha256": "0" * 64},
            {
                "path": "src/rfb/contracts/regeneration_sampling_qa.schema.json",
                "sha256": "0" * 64,
            },
            {
                "path": "src/rfb/contracts/dataset_purge_ledger.schema.json",
                "sha256": "0" * 64,
            },
            {
                "path": "src/rfb/contracts/dataset_purge_tombstone.schema.json",
                "sha256": "0" * 64,
            },
        ],
        "excluded_gates": {
            name: "PASS"
            for name in (
                "segment_cap_gate",
                "durable_result_gate",
                "result_archive_gate",
                "regeneration_gate",
                "dataset_purge_gate",
            )
        },
        "formal_stage_admission": "CREATED",
        "runtime_baseline_sha256": "0" * 64,
    }
    baseline_path = bench / "outputs/runtime_gate/runtime_baseline.json"
    baseline_path.write_bytes(canonical_bytes(baseline) + b"\n")
    refreshed = refresh_runtime_freeze(bench)
    manifest = _json(bench / "outputs/runtime_gate/source_tree_manifest.json")
    paths = [item["path"] for item in manifest["files"]]
    assert paths == sorted(paths)
    assert "src/rfb/example.py" in paths
    assert "tests/test_example.py" in paths
    assert not any("__pycache__" in path or path.endswith(".pyc") for path in paths)
    assert (
        manifest["source_tree_sha256"]
        == hashlib.sha256(canonical_bytes(manifest["files"])).hexdigest()
    )
    schema_hashes = {item["path"]: item["sha256"] for item in refreshed["schemas"]}
    assert schema_hashes["src/rfb/contracts/method_output.schema.json"] == (
        hashlib.sha256(method_schema.read_bytes()).hexdigest()
    )
    assert (
        schema_hashes["src/rfb/contracts/result_archive_targets.schema.json"]
        == hashlib.sha256(archive_schema.read_bytes()).hexdigest()
    )
    for schema_path, schema_file in (
        ("src/rfb/contracts/regeneration_sampling_qa.schema.json", regeneration_schema),
        ("src/rfb/contracts/dataset_purge_ledger.schema.json", purge_ledger_schema),
        (
            "src/rfb/contracts/dataset_purge_tombstone.schema.json",
            purge_tombstone_schema,
        ),
    ):
        assert (
            schema_hashes[schema_path]
            == hashlib.sha256(schema_file.read_bytes()).hexdigest()
        )
    assert all(value == "PENDING" for value in refreshed["excluded_gates"].values())
    assert refreshed["formal_stage_admission"] == "NOT_CREATED"
    unsigned = copy.deepcopy(refreshed)
    actual_self_hash = unsigned.pop("runtime_baseline_sha256")
    assert actual_self_hash == hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
    assert baseline_path.read_bytes() == canonical_bytes(refreshed) + b"\n"


def test_update_gate_checklist_rejects_tampered_archive_evidence(tmp_path):
    bench = _temporary_bench(tmp_path)
    output = bench / "outputs/gate_components"
    generate_component_evidence(
        bench, output, tmp_path / "archive-b", "2026-07-19T00:00:00Z"
    )
    archive_qa = output / "archive/result_archive_ab_qa.json"
    value = _json(archive_qa)
    value["pass"] = False
    archive_qa.write_bytes(canonical_bytes(value) + b"\n")
    checklist = {
        "status": "FORMAL_EXPERIMENT_BLOCKED",
        "runtime_gate": {"status": "PASS", "tasks": []},
        "segment_cap_gate": {"status": "PENDING", "tasks": [_task("C0")]},
        "durable_result_gate": {"status": "PENDING", "tasks": []},
        "result_archive_gate": {"status": "PENDING", "tasks": [_task("B0")]},
        "regeneration_gate": {"status": "PENDING", "tasks": []},
        "dataset_purge_gate": {"status": "PENDING", "tasks": []},
        "formal_stage_admission": {"status": "BLOCKED"},
    }
    checklist_path = tmp_path / "GateChecklist-v6.13.json"
    checklist_path.write_bytes(canonical_bytes(checklist) + b"\n")
    updated = update_gate_checklist(
        checklist_path, "bench/outputs/gate_components", "2026-07-19T00:00:00Z"
    )
    assert updated["segment_cap_gate"]["tasks"][0]["development_status"] == "FAIL"
    assert updated["result_archive_gate"]["tasks"][0]["development_status"] == "FAIL"
    assert updated["result_archive_gate"]["tasks"][0]["development_evidence"] == []


def test_checklist_fails_tampered_regeneration_plan_hash(tmp_path):
    bench = _temporary_bench(tmp_path)
    output = bench / "outputs/gate_components"
    generate_component_evidence(
        bench, output, tmp_path / "archive-b", "2026-07-19T00:00:00Z"
    )
    path = output / "regeneration/regeneration_sampling_qa.json"
    value = _json(path)
    value["plan"]["plan_hash"] = "0" * 64
    path.write_bytes(canonical_bytes(value) + b"\n")
    checklist = {
        "status": "FORMAL_EXPERIMENT_BLOCKED",
        "regeneration_gate": {"status": "PENDING", "tasks": [_task("G0"), _task("G1")]},
        "formal_stage_admission": {"status": "BLOCKED"},
    }
    checklist_path = tmp_path / "GateChecklist-v6.13.json"
    checklist_path.write_bytes(canonical_bytes(checklist) + b"\n")
    updated = update_gate_checklist(
        checklist_path, "bench/outputs/gate_components", "2026-07-19T00:00:00Z"
    )
    assert all(
        task["development_status"] == "FAIL" and task["development_evidence"] == []
        for task in updated["regeneration_gate"]["tasks"]
    )
    assert not (tmp_path / "FORMAL_STAGE_ADMISSION-v6.13.json").exists()


def test_checklist_fails_tampered_purge_tombstone_ledger_binding(tmp_path):
    bench = _temporary_bench(tmp_path)
    output = bench / "outputs/gate_components"
    generate_component_evidence(
        bench, output, tmp_path / "archive-b", "2026-07-19T00:00:00Z"
    )
    path = output / "purge/dataset_purge_tombstone.json"
    value = _json(path)
    value["purge_ledger_head"] = "0" * 64
    unsigned = {key: item for key, item in value.items() if key != "tombstone_hash"}
    value["tombstone_hash"] = hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
    path.write_bytes(canonical_bytes(value) + b"\n")
    checklist = {
        "status": "FORMAL_EXPERIMENT_BLOCKED",
        "dataset_purge_gate": {
            "status": "PENDING",
            "tasks": [_task(task_id) for task_id in ("P0", "P1", "P2", "P3")],
        },
        "formal_stage_admission": {"status": "BLOCKED"},
    }
    checklist_path = tmp_path / "GateChecklist-v6.13.json"
    checklist_path.write_bytes(canonical_bytes(checklist) + b"\n")
    updated = update_gate_checklist(
        checklist_path, "bench/outputs/gate_components", "2026-07-19T00:00:00Z"
    )
    assert all(
        task["development_status"] == "FAIL" and task["development_evidence"] == []
        for task in updated["dataset_purge_gate"]["tasks"]
    )
    assert not (tmp_path / "FORMAL_STAGE_ADMISSION-v6.13.json").exists()


def test_generation_rejects_output_ancestor_symlink_before_replacement(tmp_path):
    import pytest

    bench = _temporary_bench(tmp_path)
    real = tmp_path / "real-output"
    real.mkdir()
    link = tmp_path / "linked-output"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink unavailable")
    with pytest.raises(ValueError, match="symbolic-link"):
        generate_component_evidence(
            bench, link / "nested", tmp_path / "archive-b", "2026-07-19T00:00:00Z"
        )
    assert not (real / "nested").exists()


def test_checklist_fails_empty_raw_case_set(tmp_path):
    bench = _temporary_bench(tmp_path)
    output = bench / "outputs/gate_components"
    generate_component_evidence(
        bench, output, tmp_path / "archive-b", "2026-07-19T00:00:00Z"
    )
    raw = output / "durable_result/raw_dataset_exclusion_qa.json"
    value = _json(raw)
    value["cases"] = []
    raw.write_bytes(canonical_bytes(value) + b"\n")
    checklist = {
        "status": "FORMAL_EXPERIMENT_BLOCKED",
        "formal_stage_admission": {"status": "BLOCKED"},
    }
    path = tmp_path / "GateChecklist-v6.13.json"
    path.write_bytes(canonical_bytes(checklist) + b"\n")
    updated = update_gate_checklist(
        path, "bench/outputs/gate_components", "2026-07-19T00:00:00Z"
    )
    assert updated["status"] == "FORMAL_EXPERIMENT_BLOCKED"


def test_generation_rejects_symlinked_bench_root_before_replacement(tmp_path):
    import pytest

    bench = _temporary_bench(tmp_path)
    link = tmp_path / "bench-link"
    try:
        link.symlink_to(bench, target_is_directory=True)
    except OSError:
        pytest.skip("symlink unavailable")
    with pytest.raises(ValueError, match="symbolic-link"):
        generate_component_evidence(
            link, tmp_path / "output", tmp_path / "archive-b", "2026-07-19T00:00:00Z"
        )
    assert not (tmp_path / "output").exists()


def test_refresh_rejects_symlinked_bench_root_before_writing(tmp_path):
    import pytest

    bench = tmp_path / "bench"
    (bench / "outputs/runtime_gate").mkdir(parents=True)
    (bench / "outputs/runtime_gate/runtime_baseline.json").write_text(
        "{}\n", encoding="utf-8"
    )
    link = tmp_path / "bench-link"
    try:
        link.symlink_to(bench, target_is_directory=True)
    except OSError:
        pytest.skip("symlink unavailable")
    with pytest.raises(ValueError, match="symbolic-link"):
        refresh_runtime_freeze(link)
    assert not (bench / "outputs/runtime_gate/source_tree_manifest.json").exists()


def test_checklist_rejects_forged_raw_qa_when_package_probe_changes(tmp_path):
    bench = _temporary_bench(tmp_path)
    output = bench / "outputs/gate_components"
    generate_component_evidence(
        bench, output, tmp_path / "archive-b", "2026-07-19T00:00:00Z"
    )
    rows_path = output / "durable_result/fixture_package/durable_rows.jsonl"
    row = json.loads(rows_path.read_text(encoding="utf-8").splitlines()[0])
    row["prediction_or_decision"] = {"payload": "forbidden"}
    rows_path.write_text(canonical_bytes(row).decode() + "\n", encoding="utf-8")
    checklist_path = tmp_path / "GateChecklist-v6.13.json"
    checklist_path.write_bytes(
        canonical_bytes(
            {
                "status": "FORMAL_EXPERIMENT_BLOCKED",
                "formal_stage_admission": {"status": "BLOCKED"},
            }
        )
        + b"\n"
    )
    updated = update_gate_checklist(
        checklist_path, "bench/outputs/gate_components", "2026-07-19T00:00:00Z"
    )
    assert updated["status"] == "FORMAL_EXPERIMENT_BLOCKED"
    assert not (tmp_path / "FORMAL_STAGE_ADMISSION-v6.13.json").exists()
