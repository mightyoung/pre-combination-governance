from __future__ import annotations

import hashlib
from pathlib import Path

from rfb.archive_qa import ArchiveTarget, archive_qa, copy_durable_only
from rfb.durable_results import row_result_sha256, validate_durable_row
from rfb.durable_package import seal_durable_package


def _hash(value: str = "x") -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_row():
    row = {
        "bundle_id": "bundle-1",
        "method_id": "B0",
        "algorithm_seed": 7,
        "transaction_id": "tx-1",
        "schema_version": "1.0.0",
        "contains_raw_dataset": False,
        "prediction_or_decision": {"label": "REVIEW"},
        "scorer_metrics": {"score": 0.5},
        "validity_status": "VALID",
        "failure_or_timeout_code": None,
        "stratum_template_batch_superblock_keys": {
            "stratum": "s",
            "template": "t",
            "batch": "b",
            "superblock": "sb",
        },
        "resource_telemetry": {"capacity_bytes": 1},
        "input_commitment": _hash("input"),
        "generator_candidate_method_scorer_schema_container_allocation_prereg_hashes": {
            "generator": _hash("g"),
            "candidate": _hash("c"),
            "method": _hash("m"),
            "scorer": _hash("s"),
            "schema": _hash("schema"),
            "container": _hash("container"),
            "allocation": _hash("allocation"),
            "prereg": _hash("prereg"),
        },
        "result_sha256": "",
    }
    row["result_sha256"] = row_result_sha256(row)
    return row


def test_durable_row_accepts_closed_v613_row():
    assert validate_durable_row(_valid_row()) == []


def test_durable_row_rejects_missing_v613_required_fields():
    for required in (
        "prediction_or_decision",
        "scorer_metrics",
        "resource_telemetry",
        "input_commitment",
    ):
        row = _valid_row()
        row.pop(required)
        assert validate_durable_row(row)


def test_durable_row_rejects_raw_truth_and_nested_payload_leakage():
    for key, value in (
        ("truth", 1),
        ("raw_payload", {"x": 1}),
        ("nested", {"raw": "x"}),
    ):
        row = _valid_row()
        row[key] = value
        assert validate_durable_row(row)


def test_durable_row_requires_false_raw_dataset_marker_and_hashes():
    row = _valid_row()
    row.pop("result_sha256")
    assert validate_durable_row(row)
    row = _valid_row()
    row["contains_raw_dataset"] = True
    assert validate_durable_row(row)
    row = _valid_row()
    row["input_commitment"] = "short"
    assert validate_durable_row(row)


def test_durable_row_rejects_unknown_fields_and_wrong_granularity_types():
    row = _valid_row()
    row["unexpected"] = "x"
    assert validate_durable_row(row)
    row = _valid_row()
    row["algorithm_seed"] = "7"
    assert validate_durable_row(row)


def test_archive_copy_is_durable_only_and_live_gate_stays_false(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "result.json").write_text("{}", encoding="utf-8")
    (source / "raw_payload.bin").write_bytes(b"secret")
    target = ArchiveTarget("A", str(tmp_path / "archive"), "domain-a", immutable=True)
    report = copy_durable_only(source, target)
    assert report["files"] == []
    assert report["local_live_gate_passed"] is False
    assert "$package" in report["rejected"]


def test_archive_copy_rejects_truth_inside_json_content(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "result.json").write_text(
        '{"contains_raw_dataset": false, "truth": 1}', encoding="utf-8"
    )
    target = ArchiveTarget("A", str(tmp_path / "archive"), "domain-a", immutable=True)
    report = copy_durable_only(source, target)
    assert report["files"] == []
    assert "result.json" in report["rejected"]


def report_hash(root, relative):
    return hashlib.sha256((Path(root) / relative).read_bytes()).hexdigest()


def test_archive_readback_detects_tamper_and_unexpected_file(tmp_path):
    target = ArchiveTarget(
        "B", str(tmp_path / "archive"), "domain-b", off_volume=True, append_only=True
    )
    root = Path(target.root)
    seal_durable_package(root, [_valid_row()], expected_keys=[("bundle-1", "B0", "7")])
    expected = {
        path.name: report_hash(target.root, path.name)
        for path in root.iterdir()
        if path.is_file()
    }
    (root / "durable_rows.jsonl").write_text("tampered", encoding="utf-8")
    (root / "extra.json").write_text("unexpected", encoding="utf-8")
    qa = archive_qa(target, expected)
    assert qa["mismatch"] == ["durable_rows.jsonl"]
    assert qa["unexpected"] == ["extra.json"]
    assert qa["pass"] is False
