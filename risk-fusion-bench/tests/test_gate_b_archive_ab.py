from __future__ import annotations

import hashlib
import json
import os
from dataclasses import fields
from pathlib import Path

import pytest

from rfb.archive_qa import (
    ArchiveTarget,
    archive_qa,
    copy_sealed_package,
    qa_archives,
)
from rfb.archive_targets import (
    load_archive_targets,
    validate_archive_targets,
)
from rfb.durable_results import row_result_sha256
from rfb.durable_package import (
    MANIFEST_NAME,
    ROWS_NAME,
    seal_durable_package,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_row() -> dict[str, object]:
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


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "sealed"
    seal_durable_package(
        package, [_valid_row()], expected_keys=[("bundle-1", "B0", "7")]
    )
    return package


def _targets(
    tmp_path: Path,
    *,
    live: bool = False,
) -> list[ArchiveTarget]:
    evidence_a = None
    evidence_b = None
    if live:
        evidence_a = {
            "verified_at": "2026-07-19T00:00:00Z",
            "readback_receipt": "receipt-a",
            "storage_identity": "storage-a",
        }
        evidence_b = {
            "verified_at": "2026-07-19T00:00:00Z",
            "readback_receipt": "receipt-b",
            "storage_identity": "storage-b",
            "off_volume_verified": True,
        }
    return [
        ArchiveTarget(
            "A",
            str(tmp_path / "archive-a"),
            "domain-a",
            immutable=True,
            live_evidence=evidence_a,
        ),
        ArchiveTarget(
            "B",
            str(tmp_path / "archive-b"),
            "domain-b",
            off_volume=True,
            append_only=True,
            live_evidence=evidence_b,
        ),
    ]


def _expected(report: dict[str, object]) -> dict[str, str]:
    value = report["expected_sha256"]
    assert isinstance(value, dict)
    return value


def test_target_contract_is_exact_and_credential_free(tmp_path: Path):
    targets = _targets(tmp_path)
    assert validate_archive_targets(targets) == []
    assert {target.name for target in targets} == {"A", "B"}
    assert all(Path(target.root).is_absolute() for target in targets)
    runtime_fields = {field.name for field in fields(ArchiveTarget)}
    assert "credentials_ref" not in runtime_fields

    assert validate_archive_targets(targets[:1])
    assert validate_archive_targets([targets[0], targets[0]])
    same_domain_b = ArchiveTarget(
        "B",
        targets[1].root,
        "domain-a",
        off_volume=True,
        append_only=True,
    )
    assert validate_archive_targets([targets[0], same_domain_b])
    local_b = ArchiveTarget(
        "B",
        targets[1].root,
        "domain-b",
        append_only=True,
    )
    assert validate_archive_targets([targets[0], local_b])
    mutable_b = ArchiveTarget(
        "B",
        targets[1].root,
        "domain-b",
        off_volume=True,
    )
    assert validate_archive_targets([targets[0], mutable_b])
    assert ArchiveTarget(
        "A",
        "relative",
        "domain-a",
        immutable=True,
    ).validate()

    config = {
        "targets": [
            {
                "name": "A",
                "root": targets[0].root,
                "failure_domain": "domain-a",
                "immutable": True,
                "append_only": False,
                "credentials_ref": "secret-token",
            },
            {
                "name": "B",
                "root": targets[1].root,
                "failure_domain": "domain-b",
                "off_volume": True,
                "immutable": False,
                "append_only": True,
            },
        ]
    }
    with pytest.raises(ValueError, match="credential"):
        load_archive_targets(config)
    config["targets"][0].pop("credentials_ref")
    config["targets"][0]["live_evidence"] = {"note": {"password": "embedded"}}
    with pytest.raises(ValueError, match="credential"):
        load_archive_targets(config)


def test_schema_and_runtime_expose_the_same_target_fields():
    schema_path = (
        Path(__file__).parents[1]
        / "src"
        / "rfb"
        / "contracts"
        / "result_archive_targets.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_fields = set(schema["$defs"]["target"]["properties"])
    runtime_fields = {field.name for field in fields(ArchiveTarget)}
    assert schema_fields == runtime_fields


def test_sealed_package_copies_to_a_and_b_with_local_gate_false(
    tmp_path: Path,
):
    package = _package(tmp_path)
    targets = _targets(tmp_path)
    reports = [copy_sealed_package(package, target) for target in targets]
    expected = _expected(reports[0])
    assert all(report["files"] == [MANIFEST_NAME, ROWS_NAME] for report in reports)
    assert all(report["rejected"] == {} for report in reports)
    assert all(report["readback"]["pass"] is True for report in reports)
    qa = qa_archives(targets, expected)
    assert qa["pass"] is True
    assert qa["local_live_gate_passed"] is False


def test_readback_reports_tamper_missing_and_unexpected(tmp_path: Path):
    package = _package(tmp_path)
    target = _targets(tmp_path)[0]
    report = copy_sealed_package(package, target)
    expected = _expected(report)
    root = Path(target.root)
    (root / ROWS_NAME).write_text("tampered\n", encoding="utf-8")
    (root / MANIFEST_NAME).unlink()
    (root / "unexpected.json").write_text("{}", encoding="utf-8")
    qa = archive_qa(target, expected)
    assert qa["mismatch"] == [ROWS_NAME]
    assert qa["missing"] == [MANIFEST_NAME]
    assert qa["unexpected"] == ["unexpected.json"]
    assert qa["pass"] is False


def test_expected_must_map_paths_to_lowercase_sha256(tmp_path: Path):
    target = _targets(tmp_path)[0]
    with pytest.raises(TypeError, match="mapping"):
        archive_qa(target, [ROWS_NAME])
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        archive_qa(target, {ROWS_NAME: "not-a-hash"})


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        ("raw_payload.json", b"{}"),
        ("extra.bin", b"binary"),
        ("arbitrary.json", b"{}"),
    ],
)
def test_strict_copy_rejects_every_unexpected_file(
    tmp_path: Path,
    name: str,
    payload: bytes,
):
    package = _package(tmp_path)
    (package / name).write_bytes(payload)
    report = copy_sealed_package(package, _targets(tmp_path)[0])
    assert report["files"] == []
    assert name in report["rejected"]


def test_strict_copy_rejects_arbitrary_json_and_forbidden_content(
    tmp_path: Path,
):
    arbitrary = tmp_path / "arbitrary-source"
    arbitrary.mkdir()
    (arbitrary / "result.json").write_text("{}", encoding="utf-8")
    report = copy_sealed_package(arbitrary, _targets(tmp_path)[0])
    assert report["files"] == []
    assert "result.json" in report["rejected"]

    package = _package(tmp_path)
    (package / ROWS_NAME).write_text(
        '{"truth":"forbidden"}\n',
        encoding="utf-8",
    )
    report = copy_sealed_package(package, _targets(tmp_path)[0])
    assert report["files"] == []
    assert ROWS_NAME in report["rejected"]


def test_strict_copy_rejects_invalid_utf8_and_json(tmp_path: Path):
    package = _package(tmp_path)
    (package / ROWS_NAME).write_bytes(b"\xff\xfe")
    report = copy_sealed_package(package, _targets(tmp_path)[0])
    assert report["files"] == []
    assert ROWS_NAME in report["rejected"]

    invalid = tmp_path / "invalid-json"
    invalid.mkdir()
    (invalid / ROWS_NAME).write_text("not-json\n", encoding="utf-8")
    (invalid / MANIFEST_NAME).write_text("{}", encoding="utf-8")
    report = copy_sealed_package(invalid, _targets(tmp_path)[0])
    assert report["files"] == []
    assert ROWS_NAME in report["rejected"]


def test_allowlist_escape_and_source_symlink_are_rejected(tmp_path: Path):
    package = _package(tmp_path)
    target = _targets(tmp_path)[0]
    report = copy_sealed_package(
        package,
        target,
        allowlist=[ROWS_NAME, MANIFEST_NAME, "../escape.json"],
    )
    assert report["files"] == []
    assert "../escape.json" in report["rejected"]
    assert not (tmp_path / "escape.json").exists()

    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    link = package / "extra.json"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable on this platform")
    report = copy_sealed_package(package, target)
    assert report["files"] == []
    assert "extra.json" in report["rejected"]


def test_complete_live_evidence_requires_both_hash_sets_to_pass(
    tmp_path: Path,
):
    package = _package(tmp_path)
    targets = _targets(tmp_path)
    reports = [copy_sealed_package(package, target) for target in targets]
    expected = _expected(reports[0])
    for target, report in zip(targets, reports):
        object.__setattr__(
            target,
            "live_evidence",
            {
                "verified_at": "2026-07-19T00:00:00Z",
                "storage_identity": f"storage-{target.name}",
                "readback_receipt": {
                    "target_identity": target.name,
                    "storage_identity": f"storage-{target.name}",
                    "expected_sha256": expected,
                    "observed_sha256": report["readback"]["observed_sha256"],
                },
                "operational_proof": {
                    "verified": True,
                    "immutable": target.immutable,
                    "append_only": target.append_only,
                },
                **({"off_volume_verified": True} if target.name == "B" else {}),
            },
        )
    qa = qa_archives(targets, expected)
    assert qa["pass"] is True
    assert qa["local_live_gate_passed"] is True

    (Path(targets[1].root) / ROWS_NAME).write_text(
        "tampered\n",
        encoding="utf-8",
    )
    qa = qa_archives(targets, expected)
    assert qa["pass"] is False
    assert qa["local_live_gate_passed"] is False


def test_archive_roots_reject_alias_and_nested_paths(tmp_path: Path):
    targets = _targets(tmp_path)
    alias = ArchiveTarget(
        "B",
        str(Path(targets[0].root) / "child"),
        "domain-b",
        off_volume=True,
        append_only=True,
    )
    assert any(
        "nested" in error for error in validate_archive_targets([targets[0], alias])
    )
    same = ArchiveTarget(
        "B", targets[0].root, "domain-b", off_volume=True, append_only=True
    )
    assert any(
        "distinct" in error for error in validate_archive_targets([targets[0], same])
    )


def test_live_evidence_arbitrary_strings_and_booleans_never_promote(tmp_path: Path):
    package = _package(tmp_path)
    targets = _targets(tmp_path, live=True)
    reports = [copy_sealed_package(package, target) for target in targets]
    expected = _expected(reports[0])
    assert qa_archives(targets, expected)["local_live_gate_passed"] is False


def test_expected_rejects_arbitrary_filename_key(tmp_path: Path):
    target = _targets(tmp_path)[0]
    with pytest.raises(ValueError, match="exactly PACKAGE_FILES"):
        archive_qa(target, {"truth.json": _hash("truth")})


def test_atomic_swap_failure_preserves_existing_archive_and_cleans_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import importlib

    archive_module = importlib.import_module("rfb.archive_qa")
    package = _package(tmp_path)
    target = _targets(tmp_path)[0]
    initial = copy_sealed_package(package, target)
    root = Path(target.root)
    before = {name: (root / name).read_bytes() for name in initial["files"]}
    real_replace = archive_module.os.replace

    def fail_stage_swap(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ):
        if ".stage-" in str(source) and Path(destination) == root:
            raise OSError("injected stage swap failure")
        return real_replace(source, destination)

    monkeypatch.setattr(archive_module.os, "replace", fail_stage_swap)
    report = copy_sealed_package(package, target)
    assert report["files"] == []
    assert "$copy" in report["rejected"]
    assert {name: (root / name).read_bytes() for name in before} == before
    assert not list(root.parent.glob(f".{root.name}.stage-*"))
    assert not list(root.parent.glob(f".{root.name}.rollback-*"))


def test_source_ancestor_symlink_is_rejected(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    package = _package(real)
    link_parent = tmp_path / "linked"
    try:
        os.symlink(real, link_parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable on this platform")
    report = copy_sealed_package(link_parent / package.name, _targets(tmp_path)[0])
    assert report["files"] == []
    assert "$source" in report["rejected"]


def test_parent_fsync_failure_restores_preexisting_target_and_cleans_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import importlib

    module = importlib.import_module("rfb.archive_qa")
    package = _package(tmp_path)
    target = _targets(tmp_path)[0]
    initial = copy_sealed_package(package, target)
    root = Path(target.root)
    before = {name: (root / name).read_bytes() for name in initial["files"]}
    real_fsync = module._fsync_directory

    def fail_parent(path: Path) -> None:
        if Path(path) == root.parent:
            raise OSError("injected parent fsync failure")
        real_fsync(path)

    monkeypatch.setattr(module, "_fsync_directory", fail_parent)
    report = copy_sealed_package(package, target)
    assert report["files"] == []
    assert {name: (root / name).read_bytes() for name in before} == before
    assert not list(root.parent.glob(f".{root.name}.stage-*"))
    assert not list(root.parent.glob(f".{root.name}.rollback-*"))


def test_parent_fsync_failure_restores_initial_absence_and_cleans_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import importlib

    module = importlib.import_module("rfb.archive_qa")
    package = _package(tmp_path)
    target = _targets(tmp_path)[0]
    root = Path(target.root)
    real_fsync = module._fsync_directory

    def fail_parent(path: Path) -> None:
        if Path(path) == root.parent:
            raise OSError("injected parent fsync failure")
        real_fsync(path)

    monkeypatch.setattr(module, "_fsync_directory", fail_parent)
    report = copy_sealed_package(package, target)
    assert report["files"] == []
    assert not root.exists()
    assert not list(root.parent.glob(f".{root.name}.stage-*"))
    assert not list(root.parent.glob(f".{root.name}.rollback-*"))


def test_cleanup_failure_restores_preexisting_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import importlib

    module = importlib.import_module("rfb.archive_qa")
    package = _package(tmp_path)
    target = _targets(tmp_path)[0]
    initial = copy_sealed_package(package, target)
    root = Path(target.root)
    before = {name: (root / name).read_bytes() for name in initial["files"]}
    real_remove = module._remove_tree

    def fail_backup(path: Path) -> None:
        if ".rollback-" in path.name:
            raise RuntimeError("injected rollback cleanup failure")
        real_remove(path)

    monkeypatch.setattr(module, "_remove_tree", fail_backup)
    report = copy_sealed_package(package, target)
    assert report["files"] == []
    assert {name: (root / name).read_bytes() for name in before} == before
    assert not list(root.parent.glob(f".{root.name}.stage-*"))
    assert not list(root.parent.glob(f".{root.name}.rollback-*"))


def test_readback_failure_restores_preexisting_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import importlib

    module = importlib.import_module("rfb.archive_qa")
    package = _package(tmp_path)
    target = _targets(tmp_path)[0]
    initial = copy_sealed_package(package, target)
    root = Path(target.root)
    before = {name: (root / name).read_bytes() for name in initial["files"]}
    monkeypatch.setattr(module, "archive_qa", lambda *_args, **_kwargs: {"pass": False})
    report = copy_sealed_package(package, target)
    assert report["files"] == []
    assert {name: (root / name).read_bytes() for name in before} == before
    assert not list(root.parent.glob(f".{root.name}.stage-*"))
    assert not list(root.parent.glob(f".{root.name}.rollback-*"))
