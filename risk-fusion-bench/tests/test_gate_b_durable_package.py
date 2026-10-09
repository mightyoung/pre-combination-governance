from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import rfb.durable_package as durable_package
from rfb.durable_package import (
    ROWS_NAME,
    seal_durable_package,
    validate_durable_package,
)
from rfb.durable_results import (
    build_durable_manifest,
    validate_durable_manifest,
    write_durable_manifest,
    row_result_sha256,
    validate_durable_row,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _row(bundle: str = "bundle-1", method: str = "B0", seed: int = 7):
    row = {
        "bundle_id": bundle,
        "method_id": method,
        "algorithm_seed": seed,
        "transaction_id": f"tx-{bundle}-{method}-{seed}",
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
            name: _hash(name)
            for name in (
                "generator",
                "candidate",
                "method",
                "scorer",
                "schema",
                "container",
                "allocation",
                "prereg",
            )
        },
        "result_sha256": "0" * 64,
    }
    row["result_sha256"] = row_result_sha256(row)
    return row


def _key(row):
    return (row["bundle_id"], row["method_id"], str(row["algorithm_seed"]))


def _schema():
    path = (
        Path(__file__).parents[1]
        / "src/rfb/contracts/durable_result_manifest.schema.json"
    )
    return json.loads(path.read_text(encoding="utf-8-sig"))


def test_seal_validate_schema_stable_merkle_and_atomic_residue(tmp_path):
    row = _row()
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest = seal_durable_package(first, [row], expected_keys=[_key(row)])
    other = seal_durable_package(second, [row], expected_keys=[_key(row)])
    assert validate_durable_package(first, expected_keys=[_key(row)]) == []
    assert validate_durable_manifest(manifest, [row], strict=True) == []
    Draft202012Validator(_schema()).validate(manifest)
    assert manifest["merkle_root_sha256"] == other["merkle_root_sha256"]
    assert not [path for path in first.iterdir() if path.suffix in {".tmp", ".partial"}]
    target = tmp_path / "manifest.json"
    write_durable_manifest(target, [row], expected_keys=[_key(row)], strict=True)
    assert target.is_file()
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize(
    "rows,expected",
    [
        ([_row(), _row()], [_key(_row())]),
        ([_row()], [("bundle-1", "B0", "7"), ("bundle-2", "B0", "7")]),
        ([_row()], [("bundle-2", "B0", "7")]),
    ],
)
def test_duplicate_missing_and_unexpected_closure_raise(tmp_path, rows, expected):
    with pytest.raises(ValueError, match="duplicate|closure"):
        seal_durable_package(tmp_path / "package", rows, expected_keys=expected)
    with pytest.raises(ValueError, match="duplicate|closure"):
        build_durable_manifest(rows, expected_keys=expected, strict=True)


def test_manifest_builder_reports_duplicates_and_rejects_malformed_triples():
    manifest = build_durable_manifest([_row(), _row()])
    assert manifest["duplicate"] == [["bundle-1", "B0", "7"]]
    with pytest.raises(ValueError, match="three-item"):
        build_durable_manifest([_row()], expected_keys=[("bundle-1", "B0")])


@pytest.mark.parametrize("suffix", [".json", ".jsonl"])
@pytest.mark.parametrize("token", ["raw", "truth", "payload", "sidecar"])
def test_nested_sensitive_content_is_rejected(tmp_path, suffix, token):
    source = tmp_path / "source"
    source.mkdir()
    row = _row()
    row["prediction_or_decision"] = {token: "secret"}
    text = json.dumps(row)
    (source / f"rows{suffix}").write_text(text + ("\n" if suffix == ".jsonl" else ""))
    with pytest.raises(ValueError, match="forbidden"):
        seal_durable_package(source, tmp_path / "package")


def test_forbidden_path_binary_unsupported_and_arbitrary_object(tmp_path):
    cases = [
        ("raw_rows.json", json.dumps(_row()).encode()),
        ("rows.json", b"\x00binary"),
        ("rows.bin", b"binary"),
        ("rows.json", b"{}"),
    ]
    for index, (name, data) in enumerate(cases):
        source = tmp_path / f"source-{index}"
        source.mkdir()
        (source / name).write_bytes(data)
        with pytest.raises(ValueError):
            seal_durable_package(source, tmp_path / f"package-{index}")


def test_source_symlink_is_rejected_when_supported(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    real = source / "real.json"
    real.write_text(json.dumps(_row()))
    link = source / "linked.json"
    try:
        os.symlink(real, link)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    with pytest.raises(ValueError, match="symbolic links"):
        seal_durable_package(source, tmp_path / "package")


def test_rows_manifest_and_unexpected_entry_tamper_are_detected(tmp_path):
    package = tmp_path / "package"
    row = _row()
    seal_durable_package(package, [row], expected_keys=[_key(row)])
    rows_path = package / "durable_rows.jsonl"
    rows_path.write_bytes(rows_path.read_bytes() + b" ")
    assert validate_durable_package(package)
    package = tmp_path / "package-2"
    seal_durable_package(package, [row], expected_keys=[_key(row)])
    (package / "extra.json").write_text("{}")
    assert any("unexpected" in error for error in validate_durable_package(package))


@pytest.mark.parametrize(
    "field,value",
    [
        ("rows_sha256", "0" * 64),
        ("merkle_root_sha256", "0" * 64),
        ("manifest_sha256", "0" * 64),
        ("row_count", 2),
        ("extra", True),
    ],
)
def test_manifest_hash_self_merkle_count_and_closed_shape_tamper(
    tmp_path, field, value
):
    package = tmp_path / field
    row = _row()
    seal_durable_package(package, [row], expected_keys=[_key(row)])
    path = package / "durable_result_manifest.json"
    manifest = json.loads(path.read_text())
    manifest[field] = value
    path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")
    assert validate_durable_package(package)


def test_runtime_manifest_validator_detects_internal_tamper():
    row = _row()
    manifest = build_durable_manifest([row], expected_keys=[_key(row)], strict=True)
    for field in ("rows_sha256", "merkle_root_sha256", "manifest_sha256"):
        changed = copy.deepcopy(manifest)
        changed[field] = "0" * 64
        assert validate_durable_manifest(changed, [row], strict=True)


def test_row_result_hash_rejects_wrong_hash_and_post_hash_mutation():
    row = _row()
    assert row_result_sha256(row) == row["result_sha256"]
    wrong = dict(row)
    wrong["result_sha256"] = "0" * 64
    assert any(
        "result_sha256 does not match" in error for error in validate_durable_row(wrong)
    )
    row["scorer_metrics"] = {"score": 0.9}
    assert any(
        "result_sha256 does not match" in error for error in validate_durable_row(row)
    )


def _assert_no_publication_residue(parent: Path, name: str):
    assert not list(parent.glob(f".{name}.stage-*"))
    assert not list(parent.glob(f".{name}.rollback-*"))


def test_publication_failure_old_root_to_backup_preserves_package(
    tmp_path, monkeypatch
):
    package = tmp_path / "package"
    row = _row()
    seal_durable_package(package, [row], expected_keys=[_key(row)])
    original = (package / ROWS_NAME).read_bytes()
    real_replace = os.replace

    def fail(source, destination):
        if Path(source) == package:
            raise OSError("injected old-root backup failure")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="old-root"):
        seal_durable_package(package, [row], expected_keys=[_key(row)])
    assert (package / ROWS_NAME).read_bytes() == original
    assert validate_durable_package(package, expected_keys=[_key(row)]) == []
    _assert_no_publication_residue(tmp_path, package.name)


def test_publication_failure_stage_to_root_rolls_back(tmp_path, monkeypatch):
    package = tmp_path / "package"
    row = _row()
    seal_durable_package(package, [row], expected_keys=[_key(row)])
    real_replace = os.replace

    def fail(source, destination):
        if Path(destination) == package and Path(source).name.startswith(
            f".{package.name}.stage-"
        ):
            raise OSError("injected stage-root failure")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="stage-root"):
        seal_durable_package(package, [row], expected_keys=[_key(row)])
    assert validate_durable_package(package, expected_keys=[_key(row)]) == []
    _assert_no_publication_residue(tmp_path, package.name)


def test_publication_failure_parent_fsync_rolls_back(tmp_path, monkeypatch):
    package = tmp_path / "package"
    row = _row()
    seal_durable_package(package, [row], expected_keys=[_key(row)])
    real_fsync = durable_package._fsync_directory

    def fail(path):
        if Path(path) == tmp_path:
            raise OSError("injected parent fsync failure")
        return real_fsync(path)

    monkeypatch.setattr(durable_package, "_fsync_directory", fail)
    with pytest.raises(OSError, match="parent fsync"):
        seal_durable_package(package, [row], expected_keys=[_key(row)])
    assert validate_durable_package(package, expected_keys=[_key(row)]) == []
    _assert_no_publication_residue(tmp_path, package.name)
