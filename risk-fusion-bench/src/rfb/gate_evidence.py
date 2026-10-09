"""Generate development evidence for the v6.13 component gates.

This module deliberately separates reproducible development evidence from
live gate evidence.  It never creates formal-stage admission evidence.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .archive_qa import PACKAGE_FILES, _sha256, copy_sealed_package, qa_archives
from .archive_targets import load_archive_targets
from .capacity import (
    CAPACITY_DRAIN_BYTES,
    CAPACITY_HARD_LIMIT_BYTES,
    PLANNING_PEAK_LIMIT_BYTES,
    CapacityTelemetry,
)
from .capacity_probe import filesystem_used_bytes, probe_capacity
from .contracts.canonical_json import canonical_bytes, sha256_hex
from .durable_package import seal_durable_package, validate_durable_package
from .g004_evidence import (
    generate_g004_development_evidence,
    validate_g004_development_evidence,
)

METHOD_IDS = ("B0", "B1", "B2", "B3", "B4", "B5", "Proposed")
DEVELOPMENT_BUNDLE_ID = "DEV-FIXTURE-BUNDLE-001"
DEVELOPMENT_SEED = 613
DEVELOPMENT_EXPECTED_KEYS = tuple(
    (DEVELOPMENT_BUNDLE_ID, method_id, str(DEVELOPMENT_SEED))
    for method_id in METHOD_IDS
)
DEVELOPMENT_FIXTURE = "DEVELOPMENT_FIXTURE_NOT_EXPERIMENT_RESULT"
LOCAL_MEASUREMENT = "DEVELOPMENT_LOCAL_TRUSTED_MEASUREMENT"
SYNTHETIC_BOUNDARY = "DEVELOPMENT_SYNTHETIC_BOUNDARY_TEST"
PENDING_GATES = (
    "segment_cap_gate",
    "durable_result_gate",
    "result_archive_gate",
    "regeneration_gate",
    "dataset_purge_gate",
)
SCHEMA_PATH = "src/rfb/contracts/result_archive_targets.schema.json"
G004_SCHEMA_PATHS = (
    "src/rfb/contracts/regeneration_sampling_qa.schema.json",
    "src/rfb/contracts/dataset_purge_ledger.schema.json",
    "src/rfb/contracts/dataset_purge_tombstone.schema.json",
)


def _timestamp(now: datetime | str | None = None) -> str:
    if now is None:
        now = datetime.now(timezone.utc)
    if isinstance(now, str):
        if not now.strip():
            raise ValueError("now must be a non-empty timestamp")
        return now
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _write_json(path: Path, value: Any) -> None:
    _atomic_write(path, canonical_bytes(value) + b"\n")


def _write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    payload = b"".join(canonical_bytes(dict(value)) + b"\n" for value in values)
    _atomic_write(path, payload)


def _is_strict_descendant(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return path != parent


def _assert_safe_root(path: Path, *, label: str) -> None:
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    if path == Path(path.anchor):
        raise ValueError(f"{label} cannot be a filesystem root")
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError(
                f"{label} path contains symbolic-link component: {current}"
            )


def _raw_path(path: Path, *, label: str) -> Path:
    """Validate raw path components before any resolve or replacement."""
    absolute = Path(os.path.abspath(path))
    _assert_safe_root(absolute, label=label)
    return absolute


def _replace_directory(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"replacement root is not a directory: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=False)


def _resolve_generation_roots(
    bench_root: str | os.PathLike[str],
    output_root: str | os.PathLike[str],
    archive_b_root: str | os.PathLike[str],
) -> tuple[Path, Path, Path]:
    # Inspect the user-supplied path before resolve: resolving first would make
    # a symlinked bench root indistinguishable from the trusted workspace.
    bench = _raw_path(Path(bench_root), label="bench_root").resolve(strict=True)
    if not bench.is_dir():
        raise ValueError("bench_root must be a directory")
    output_value = Path(output_root)
    output_raw = output_value if output_value.is_absolute() else bench / output_value
    output = _raw_path(output_raw, label="output_root")
    archive_value = Path(archive_b_root)
    if not archive_value.is_absolute():
        raise ValueError("archive_b_root must be explicitly supplied as absolute")
    archive_b = _raw_path(archive_value, label="archive_b_root")
    output_resolved = output.resolve(strict=False)
    archive_resolved = archive_b.resolve(strict=False)
    bench_resolved = bench.resolve(strict=True)
    if not _is_strict_descendant(output_resolved, bench_resolved):
        raise ValueError("output_root must be a strict descendant of bench_root")
    if (
        output_resolved == archive_resolved
        or _is_strict_descendant(output_resolved, archive_resolved)
        or _is_strict_descendant(archive_resolved, output_resolved)
    ):
        raise ValueError("output_root and archive_b_root must not overlap")
    if archive_resolved == bench_resolved:
        raise ValueError("archive_b_root cannot replace bench_root")
    return bench, output, archive_b


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fixture_row(method_id: str) -> dict[str, Any]:
    bundle_id = "DEV-FIXTURE-BUNDLE-001"
    seed = 613
    transaction_id = f"dev-fixture-{method_id.lower()}-{seed}"
    prediction = {
        "evidence_class": DEVELOPMENT_FIXTURE,
        "label": "REVIEW",
        "risk_score": (METHOD_IDS.index(method_id) + 1) / 10,
    }
    row: dict[str, Any] = {
        "schema_version": "1.0.0",
        "bundle_id": bundle_id,
        "method_id": method_id,
        "algorithm_seed": seed,
        "transaction_id": transaction_id,
        "contains_raw_dataset": False,
        "prediction_or_decision": prediction,
        "scorer_metrics": {
            "evidence_class": DEVELOPMENT_FIXTURE,
            "fixture_score": (METHOD_IDS.index(method_id) + 1) / 10,
        },
        "validity_status": "VALID",
        "failure_or_timeout_code": None,
        "stratum_template_batch_superblock_keys": {
            "stratum": "development",
            "template": "fixture-v1",
            "batch": "fixture-batch-001",
            "superblock": "fixture-superblock-001",
        },
        "resource_telemetry": {
            "evidence_class": DEVELOPMENT_FIXTURE,
            "capacity_bytes": 0,
        },
        "input_commitment": _hash_text("development-fixture-input-v1"),
        "generator_candidate_method_scorer_schema_container_allocation_prereg_hashes": {
            name: _hash_text(f"development-fixture:{method_id}:{name}")
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
    }
    row["result_sha256"] = sha256_hex(canonical_bytes(row))
    return row


def _capacity_evidence(bench: Path, output: Path, generated_at: str) -> dict[str, Any]:
    baseline = filesystem_used_bytes(bench)
    measured = probe_capacity(
        bench,
        filesystem_baseline_bytes=baseline,
        owned_external_layers_bytes=0,
        trusted_open_deleted_bytes=0,
        segment_state="DEVELOPMENT_LOCAL_PROBE",
        sample_reason="manual",
    ).as_dict()
    measured.update(
        {
            "sampled_at": generated_at,
            "segment_id": "DEVELOPMENT_LOCAL_BENCH_ROOT",
            "evidence_class": LOCAL_MEASUREMENT,
            "measurement_scope": "READ_ONLY_LOCAL_PROJECT_AND_FILESYSTEM_PROBE",
            "owned_external_layers_measurement": (
                "TRUSTED_ZERO_FOR_DEVELOPMENT_LOCAL_SCOPE"
            ),
            "open_deleted_measurement": ("TRUSTED_ZERO_NOT_OS_MEASURED_ON_WINDOWS"),
            "windows_open_deleted_claimed_measured": False,
            "formal_live_gate_evidence": False,
        }
    )

    boundary_inputs = (
        (
            "planning_exact_22gb",
            PLANNING_PEAK_LIMIT_BYTES,
            PLANNING_PEAK_LIMIT_BYTES,
        ),
        ("drain_exact_24gb", CAPACITY_DRAIN_BYTES, None),
        ("drain_exact_25gb", CAPACITY_HARD_LIMIT_BYTES, None),
        ("halt_25gb_plus_1", CAPACITY_HARD_LIMIT_BYTES + 1, None),
    )
    synthetic: list[dict[str, Any]] = []
    for case_id, observed_bytes, planning_peak in boundary_inputs:
        record = CapacityTelemetry(
            project_tree_allocated_bytes=observed_bytes,
            filesystem_used_delta_bytes=observed_bytes,
            owned_external_layers_bytes=0,
            open_deleted_bytes=0,
            sampled_at=generated_at,
            segment_state="DEVELOPMENT_SYNTHETIC",
            sample_reason="manual",
            segment_id=case_id,
            planning_peak_bytes=planning_peak,
        ).as_dict()
        record.update(
            {
                "case_id": case_id,
                "evidence_class": SYNTHETIC_BOUNDARY,
                "formal_live_gate_evidence": False,
            }
        )
        synthetic.append(record)

    telemetry = [measured, *synthetic]
    capacity_root = output / "capacity"
    _write_jsonl(capacity_root / "capacity_telemetry.jsonl", telemetry)
    cases = {
        record["case_id"]: {
            "capacity_bytes": record["capacity_bytes"],
            "state": record["state"],
            "planning_peak_bytes": record["planning_peak_bytes"],
        }
        for record in synthetic
    }
    qa = {
        "schema_version": "capacity-probe-qa.v1",
        "generated_at": generated_at,
        "development_status": "PASS",
        "live_status": "PENDING",
        "live_blocker": (
            "Requires a fresh live segment probe, explicit external-layer "
            "measurement, and OS-backed open-deleted evidence."
        ),
        "measurement_evidence_class": LOCAL_MEASUREMENT,
        "synthetic_evidence_class": SYNTHETIC_BOUNDARY,
        "windows_open_deleted_claimed_measured": False,
        "boundary_cases": cases,
    }
    _write_json(capacity_root / "capacity_probe_qa.json", qa)
    return qa


def _raw_exclusion_case(root: Path, case_id: str, row: Mapping[str, Any]) -> bool:
    source = root / case_id / "source"
    destination = root / case_id / "sealed"
    source.mkdir(parents=True)
    changed = copy.deepcopy(dict(row))
    if case_id == "path":
        (source / "raw_rows.json").write_bytes(canonical_bytes(changed))
    elif case_id == "nested_json":
        changed["prediction_or_decision"] = {"payload": "forbidden"}
        (source / "rows.json").write_bytes(canonical_bytes(changed))
    elif case_id == "jsonl":
        changed["scorer_metrics"] = {"truth": "forbidden"}
        (source / "rows.jsonl").write_bytes(canonical_bytes(changed) + b"\n")
    elif case_id == "binary":
        (source / "rows.json").write_bytes(b"\x00binary")
    elif case_id == "unsupported":
        (source / "rows.bin").write_bytes(b"unsupported")
    elif case_id == "arbitrary":
        (source / "rows.json").write_bytes(b"{}")
    else:  # pragma: no cover - internal closed case list
        raise AssertionError(case_id)
    try:
        seal_durable_package(source, destination)
    except (TypeError, ValueError, RuntimeError):
        return True
    return False


def _recompute_raw_exclusion_cases(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Run every adversarial probe in a fresh context using the real sealer."""
    case_ids = ("path", "nested_json", "jsonl", "binary", "unsupported", "arbitrary")
    with tempfile.TemporaryDirectory(prefix="rfb-raw-exclusion-verify-") as name:
        root = Path(name)
        return [
            {"case_id": case_id, "rejected": _raw_exclusion_case(root, case_id, row)}
            for case_id in case_ids
        ]


def _durable_evidence(
    bench: Path, output: Path, generated_at: str
) -> tuple[Path, dict[str, Any]]:
    rows = [_fixture_row(method_id) for method_id in METHOD_IDS]
    expected = DEVELOPMENT_EXPECTED_KEYS
    durable_root = output / "durable_result"
    package = durable_root / "fixture_package"
    manifest = seal_durable_package(package, rows, expected_keys=expected)
    validation_errors = validate_durable_package(package, expected_keys=expected)
    manifest_schema = json.loads(
        (bench / "src/rfb/contracts/durable_result_manifest.schema.json").read_text(
            encoding="utf-8-sig"
        )
    )
    schema_errors = [
        error.message
        for error in Draft202012Validator(manifest_schema).iter_errors(manifest)
    ]
    schema_qa = {
        "schema_version": "durable-result-schema-qa.v1",
        "generated_at": generated_at,
        "evidence_class": DEVELOPMENT_FIXTURE,
        "development_status": (
            "PASS" if not validation_errors and not schema_errors else "FAIL"
        ),
        "live_status": "PENDING",
        "formal_experiment_result": False,
        "contains_raw_dataset": False,
        "method_ids": list(METHOD_IDS),
        "row_count": len(rows),
        "package_validation_errors": validation_errors,
        "schema_validation_errors": schema_errors,
        "manifest_sha256": manifest["manifest_sha256"],
    }
    _write_json(durable_root / "durable_result_schema_qa.json", schema_qa)

    cases = _recompute_raw_exclusion_cases(rows[0])
    raw_qa = {
        "schema_version": "raw-dataset-exclusion-qa.v1",
        "generated_at": generated_at,
        "development_status": (
            "PASS" if all(case["rejected"] for case in cases) else "FAIL"
        ),
        "live_status": "PENDING",
        "contains_raw_dataset": False,
        "cases": cases,
    }
    _write_json(durable_root / "raw_dataset_exclusion_qa.json", raw_qa)
    if schema_qa["development_status"] != "PASS":
        raise RuntimeError("durable development fixture did not validate")
    if raw_qa["development_status"] != "PASS":
        raise RuntimeError("raw-dataset exclusion adversarial cases did not close")
    return package, schema_qa


def _archive_evidence(
    bench: Path,
    output: Path,
    archive_b: Path,
    package: Path,
    generated_at: str,
) -> dict[str, Any]:
    archive_a = output / "archive" / "archive_a"
    config = {
        "targets": [
            {
                "name": "A",
                "root": str(archive_a),
                "failure_domain": "development-local-archive-a",
                "off_host": False,
                "off_volume": False,
                "immutable": True,
                "append_only": False,
            },
            {
                "name": "B",
                "root": str(archive_b),
                "failure_domain": "development-explicit-archive-b",
                "off_host": False,
                "off_volume": True,
                "immutable": False,
                "append_only": True,
            },
        ]
    }
    schema = json.loads((bench / SCHEMA_PATH).read_text(encoding="utf-8-sig"))
    Draft202012Validator(schema).validate(config)
    targets = load_archive_targets(config)
    archive_root = output / "archive"
    _write_json(archive_root / "result_archive_targets.json", config)
    reports = [copy_sealed_package(package, target) for target in targets]
    if any(report.get("rejected") for report in reports):
        raise RuntimeError("development Archive A/B copy rejected package content")
    expected = reports[0]["expected_sha256"]
    if reports[1]["expected_sha256"] != expected:
        raise RuntimeError("Archive A/B source hash sets disagree")
    qa = qa_archives(targets, expected)
    qa.update(
        {
            "schema_version": "result-archive-ab-qa.v1",
            "generated_at": generated_at,
            "development_status": "PASS" if qa["pass"] else "FAIL",
            "live_status": "PENDING",
            "live_blocker": (
                "Archive declarations have no live_evidence receipts or "
                "independent storage identity verification."
            ),
            "formal_live_gate_evidence": False,
            "copy_reports": reports,
        }
    )
    _write_json(archive_root / "result_archive_ab_qa.json", qa)
    if not qa["pass"] or qa["local_live_gate_passed"]:
        raise RuntimeError("Archive development/live status separation failed")
    return qa


def generate_component_evidence(
    bench_root: str | os.PathLike[str],
    output_root: str | os.PathLike[str],
    archive_b_root: str | os.PathLike[str],
    now: datetime | str | None,
    trust_store: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Replace the two explicit roots and generate development-only evidence."""

    bench, output, archive_b = _resolve_generation_roots(
        bench_root, output_root, archive_b_root
    )
    _replace_directory(output)
    _replace_directory(archive_b)
    generated_at = _timestamp(now)
    capacity_qa = _capacity_evidence(bench, output, generated_at)
    package, durable_qa = _durable_evidence(bench, output, generated_at)
    archive_qa = _archive_evidence(bench, output, archive_b, package, generated_at)
    g004_qa = generate_g004_development_evidence(
        bench, output, package, generated_at, trust_store=trust_store
    )
    summary = {
        "schema_version": "gate-component-evidence-summary.v1",
        "generated_at": generated_at,
        "status": "DEVELOPMENT_COMPONENT_EVIDENCE_PASS",
        "formal_experiment_result": False,
        "formal_stage_admission_created": False,
        "formal_gate_status": "PENDING",
        "claim": (
            "Development fixtures and local QA only; no formal experiment "
            "result, method ranking, or live gate claim."
        ),
        # Keep the persisted summary portable and free of host-specific paths.
        # The caller already records the actual roots in its local execution
        # context; evidence consumers only need stable logical locations.
        "output_root": output.relative_to(bench).as_posix(),
        "archive_b_root": "EXPLICIT_DEVELOPMENT_ARCHIVE_B",
        "component_status": {
            "capacity": capacity_qa["development_status"],
            "durable_result": durable_qa["development_status"],
            "archive_ab": archive_qa["development_status"],
            "regeneration": g004_qa["regeneration"],
            "purge": g004_qa["purge"],
            "closeout": g004_qa["closeout"],
        },
    }
    _write_json(output / "gate_component_evidence_summary.json", summary)
    return summary


_TASK_EVIDENCE = {
    "C0": (
        "capacity/capacity_telemetry.jsonl",
        "capacity/capacity_probe_qa.json",
    ),
    "C1": ("capacity/capacity_probe_qa.json",),
    "R0": (
        "durable_result/fixture_package/durable_result_manifest.json",
        "durable_result/durable_result_schema_qa.json",
    ),
    "R1": ("durable_result/raw_dataset_exclusion_qa.json",),
    "R2": (
        "durable_result/fixture_package/durable_result_manifest.json",
        "durable_result/durable_result_schema_qa.json",
    ),
    "B0": (
        "archive/result_archive_targets.json",
        "archive/result_archive_ab_qa.json",
    ),
    "B1": (
        "archive/result_archive_targets.json",
        "archive/result_archive_ab_qa.json",
    ),
    "B2": ("archive/result_archive_ab_qa.json",),
    "G0": ("regeneration/regeneration_sampling_qa.json",),
    "G1": ("regeneration/regeneration_sampling_qa.json",),
    "P0": ("purge/dataset_purge_ledger.json",),
    "P1": ("purge/dataset_purge_ledger.json",),
    "P2": ("purge/dataset_purge_tombstone.json",),
    "P3": (
        "purge/dataset_purge_tombstone.json",
        "closeout/segment_closeout_qa.json",
    ),
}


def _evidence_paths(root: Path) -> tuple[dict[str, Path], list[str]]:
    paths: dict[str, Path] = {}
    errors: list[str] = []
    raw_root = Path(os.path.abspath(root))
    try:
        _assert_safe_root(raw_root, label="evidence_root")
    except ValueError as exc:
        return paths, [str(exc)]
    if not raw_root.exists() or not raw_root.is_dir():
        return paths, ["evidence root is missing or not a directory"]
    root_resolved = raw_root.resolve(strict=True)
    for task_id, relatives in _TASK_EVIDENCE.items():
        for relative in relatives:
            candidate = raw_root / relative
            try:
                # Check raw components first; never resolve a symlinked artifact.
                _assert_safe_root(candidate, label=f"{task_id} artifact")
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(root_resolved)
            except (OSError, RuntimeError, ValueError) as exc:
                errors.append(
                    f"{task_id}: artifact escapes or is missing: {relative} ({exc})"
                )
                continue
            paths[relative] = resolved
    return paths, errors


def _archive_config_shape(value: Any) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("targets"), list):
        return False
    targets = value["targets"]
    return [item.get("name") for item in targets if isinstance(item, dict)] == [
        "A",
        "B",
    ]


def _validate_component_artifacts(root: Path) -> tuple[dict[str, Path], list[str]]:
    paths, errors = _evidence_paths(root)
    if errors:
        return paths, errors

    def load(relative: str) -> Any:
        try:
            return json.loads(paths[relative].read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError) as exc:
            errors.append(f"invalid JSON artifact {relative}: {exc}")
            return None

    telemetry_path = paths[_TASK_EVIDENCE["C0"][0]]
    telemetry: list[dict[str, Any]] = []
    try:
        for line in telemetry_path.read_text(encoding="utf-8-sig").splitlines():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("telemetry rows must be objects")
            telemetry.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"invalid capacity telemetry: {exc}")
    qa = load("capacity/capacity_probe_qa.json")
    if not isinstance(qa, dict):
        errors.append("capacity QA is not an object")
    else:
        if qa.get("development_status") != "PASS" or qa.get("live_status") != "PENDING":
            errors.append("capacity QA status is not PASS/PENDING")
        if qa.get("windows_open_deleted_claimed_measured") is not False:
            errors.append("capacity QA must not claim live open-deleted evidence")
        cases = qa.get("boundary_cases")
        required = {
            "planning_exact_22gb": (22_000_000_000, "NORMAL"),
            "drain_exact_24gb": (24_000_000_000, "DRAIN_AND_SEAL"),
            "drain_exact_25gb": (25_000_000_000, "DRAIN_AND_SEAL"),
            "halt_25gb_plus_1": (25_000_000_001, "SAFE_HALT_CAP_BREACH"),
        }
        if not isinstance(cases, dict):
            errors.append("capacity QA boundary_cases missing")
        else:
            for case, (size, state) in required.items():
                item = cases.get(case)
                if (
                    not isinstance(item, dict)
                    or item.get("capacity_bytes") != size
                    or item.get("state") != state
                ):
                    errors.append(f"capacity boundary contract failed: {case}")
        by_case = {item.get("case_id"): item for item in telemetry}
        for case, (size, state) in required.items():
            item = by_case.get(case)
            if (
                not isinstance(item, dict)
                or item.get("capacity_bytes") != size
                or item.get("state") != state
            ):
                errors.append(f"capacity telemetry boundary failed: {case}")
    manifest_path = paths["durable_result/fixture_package/durable_result_manifest.json"]
    package = manifest_path.parent
    durable_errors = validate_durable_package(
        package, expected_keys=DEVELOPMENT_EXPECTED_KEYS
    )
    errors.extend(f"durable package: {error}" for error in durable_errors)
    manifest = load("durable_result/fixture_package/durable_result_manifest.json")
    durable_qa = load("durable_result/durable_result_schema_qa.json")
    if (
        not isinstance(manifest, dict)
        or manifest.get("row_count") != 7
        or manifest.get("contains_raw_dataset") is not False
    ):
        errors.append("durable manifest is not a closed seven-row raw-free package")
    if (
        not isinstance(durable_qa, dict)
        or durable_qa.get("development_status") != "PASS"
        or durable_qa.get("live_status") != "PENDING"
        or durable_qa.get("contains_raw_dataset") is not False
    ):
        errors.append("durable QA status/raw exclusion failed")
    raw_qa = load("durable_result/raw_dataset_exclusion_qa.json")
    recomputed_raw_cases: list[dict[str, Any]] | None = None
    try:
        rows_path = package / "durable_rows.jsonl"
        rows = [
            json.loads(line)
            for line in rows_path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
        if not rows or not isinstance(rows[0], dict):
            raise ValueError("durable rows are empty or invalid")
        recomputed_raw_cases = _recompute_raw_exclusion_cases(rows[0])
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        errors.append(f"raw-dataset exclusion recomputation failed: {exc}")
    expected_raw_cases = recomputed_raw_cases or []
    if (
        not isinstance(raw_qa, dict)
        or raw_qa.get("development_status") != "PASS"
        or raw_qa.get("live_status") != "PENDING"
        or raw_qa.get("contains_raw_dataset") is not False
        or {
            case.get("case_id")
            for case in raw_qa.get("cases", [])
            if isinstance(case, dict)
        }
        != {"path", "nested_json", "jsonl", "binary", "unsupported", "arbitrary"}
        or len(raw_qa.get("cases", [])) != 6
        or not all(
            isinstance(case, dict) and case.get("rejected") is True
            for case in raw_qa.get("cases", [])
        )
        or recomputed_raw_cases is None
        or raw_qa.get("cases") != expected_raw_cases
        or any(case.get("rejected") is not True for case in expected_raw_cases)
    ):
        errors.append(
            "raw-dataset exclusion QA failed: exact nonempty adversarial case set required"
        )
    archive_qa = load("archive/result_archive_ab_qa.json")
    archive_config = load("archive/result_archive_targets.json")
    targets = None
    if not _archive_config_shape(archive_config):
        errors.append("Archive target configuration shape is invalid")
    else:
        try:
            schema_path = (
                Path(__file__).parent
                / "contracts"
                / "result_archive_targets.schema.json"
            )
            schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
            schema_errors = list(
                Draft202012Validator(schema).iter_errors(archive_config)
            )
            if schema_errors:
                errors.extend(
                    f"Archive target schema: {e.message}" for e in schema_errors
                )
            targets = load_archive_targets(archive_config)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"Archive target configuration is invalid: {exc}")
    expected = {name: _sha256(package / name) for name in sorted(PACKAGE_FILES)}
    recomputed = qa_archives(targets or [], expected)
    if not isinstance(archive_qa, dict):
        errors.append("Archive A/B QA is not an object")
    else:
        if (
            archive_qa.get("development_status") != "PASS"
            or archive_qa.get("live_status") != "PENDING"
            or archive_qa.get("local_live_gate_passed") is not False
            or archive_qa.get("pass") is not True
        ):
            errors.append("Archive A/B QA is not a development-only pass")
        # Recompute all target/readback fields, so forged booleans cannot pass.
        for key in ("targets", "target_errors", "local_live_gate_passed", "pass"):
            if archive_qa.get(key) != recomputed.get(key):
                errors.append(f"Archive A/B QA forged or stale field: {key}")
        reports = archive_qa.get("copy_reports")
        if not isinstance(reports, list) or {
            r.get("target") for r in reports if isinstance(r, dict)
        } != {"A", "B"}:
            errors.append("Archive copy_reports must contain exactly A and B")
        else:
            by_name = {r.get("target"): r for r in reports}
            for target_name in ("A", "B"):
                report = by_name[target_name]
                if report.get("rejected") not in ({}, None) or report.get(
                    "files"
                ) != sorted(PACKAGE_FILES):
                    errors.append(f"Archive copy report invalid for {target_name}")
                if report.get("expected_sha256") != expected:
                    errors.append(
                        f"Archive copy report hash set invalid for {target_name}"
                    )
                readback = report.get("readback")
                if (
                    not isinstance(readback, dict)
                    or readback.get("observed_sha256") != expected
                    or readback.get("pass") is not True
                ):
                    errors.append(f"Archive copy readback invalid for {target_name}")
    errors.extend(validate_g004_development_evidence(root.parents[1], root))
    return paths, errors


def update_gate_checklist(
    path: str | os.PathLike[str],
    evidence_root_rel: str,
    now: datetime | str | None,
) -> dict[str, Any]:
    """Promote only validated development evidence; never advance live gates."""
    checklist_path = Path(path)
    checklist = json.loads(checklist_path.read_text(encoding="utf-8-sig"))
    generated_at = _timestamp(now)
    root = evidence_root_rel.replace("\\", "/").rstrip("/")
    if not root or root.startswith("/") or ".." in root.split("/"):
        raise ValueError("evidence_root_rel must be a safe relative path")
    evidence_root = Path(os.path.abspath(checklist_path.parent / root))
    _, errors = _validate_component_artifacts(evidence_root)
    checklist["status"] = "FORMAL_EXPERIMENT_BLOCKED"
    for gate_name in PENDING_GATES:
        gate = checklist.get(gate_name)
        if not isinstance(gate, dict):
            continue
        gate["status"] = "PENDING"
        for task in gate.get("tasks", []):
            task_id = task.get("id")
            if task_id not in _TASK_EVIDENCE:
                continue
            if errors:
                task["development_status"] = "FAIL"
                task["development_evidence"] = []
                task["development_verification_errors"] = errors
            else:
                task["development_status"] = "PASS"
                task["development_evidence"] = [
                    f"{root}/{relative}" for relative in _TASK_EVIDENCE[task_id]
                ]
                task["development_verified_at"] = generated_at
            task["live_status"] = "PENDING"
            task["live_blocker"] = (
                "Development evidence is not fresh live-segment gate evidence."
            )
    runtime = checklist.get("runtime_gate", {})
    capacity_gate = checklist.get("segment_cap_gate", {})
    for task in capacity_gate.get("tasks", []):
        if (
            task.get("id") == "C2"
            and task.get("status") == "BLOCKED_BY_RUNTIME_GATE"
            and runtime.get("status") == "PASS"
        ):
            task["status"] = "READY_FOR_NONCONFIRMATORY_SIZING_SMOKE"
        if task.get("id") == "C3":
            task["status"] = "BLOCKED_BY_C2"
    formal = checklist.get("formal_stage_admission")
    if isinstance(formal, dict):
        formal["status"] = "BLOCKED"
    _write_json(checklist_path, checklist)
    return checklist


def _source_files(bench: Path) -> list[dict[str, Any]]:
    selected: list[tuple[str, Path]] = []
    for top_name in ("src", "tests"):
        top = bench / top_name
        if not top.exists():
            continue
        for path in top.rglob("*"):
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.is_file() and not path.is_symlink():
                selected.append((path.relative_to(bench).as_posix(), path))
    files = []
    for relative, path in sorted(selected):
        data = path.read_bytes()
        files.append(
            {
                "path": relative,
                "bytes": len(data),
                "sha256": sha256_hex(data),
            }
        )
    return files


def refresh_runtime_freeze(
    bench_root: str | os.PathLike[str],
) -> dict[str, Any]:
    """Refresh source/schema hashes while retaining formal gate exclusions."""

    bench = _raw_path(Path(bench_root), label="bench_root").resolve(strict=True)
    runtime_root = bench / "outputs" / "runtime_gate"
    baseline_path = runtime_root / "runtime_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8-sig"))
    files = _source_files(bench)
    source_tree_sha256 = sha256_hex(canonical_bytes(files))
    source_manifest = {
        "schema_version": "1.0.0",
        "source": "risk-fusion-bench regular files under src and tests",
        "files": files,
        "source_tree_sha256": source_tree_sha256,
    }
    _write_json(runtime_root / "source_tree_manifest.json", source_manifest)

    baseline.setdefault("code_baseline", {})["source_tree_manifest"] = (
        "source_tree_manifest.json"
    )
    baseline["code_baseline"]["source_tree_sha256"] = source_tree_sha256
    baseline["generated_at"] = _timestamp()
    schemas = baseline.setdefault("schemas", [])
    if not isinstance(schemas, list):
        raise ValueError("runtime baseline schemas must be an array")
    required_schema_paths = (SCHEMA_PATH, *G004_SCHEMA_PATHS)
    for required_path in required_schema_paths:
        if not any(
            isinstance(item, Mapping) and item.get("path") == required_path
            for item in schemas
        ):
            schemas.append({"path": required_path})
    refreshed = []
    for item in schemas:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise ValueError("runtime baseline schema entries require path")
        schema_file = bench / item["path"]
        refreshed.append(
            {
                "path": item["path"],
                "sha256": sha256_hex(schema_file.read_bytes()),
            }
        )
    baseline["schemas"] = sorted(refreshed, key=lambda item: item["path"])
    excluded = baseline.setdefault("excluded_gates", {})
    if not isinstance(excluded, dict):
        raise ValueError("runtime baseline excluded_gates must be an object")
    for gate_name in PENDING_GATES:
        excluded[gate_name] = "PENDING"
    baseline["formal_stage_admission"] = "NOT_CREATED"
    unsigned = {
        key: value
        for key, value in baseline.items()
        if key != "runtime_baseline_sha256"
    }
    baseline["runtime_baseline_sha256"] = sha256_hex(canonical_bytes(unsigned))
    _write_json(baseline_path, baseline)
    return baseline


def _parser() -> argparse.ArgumentParser:
    bench_default = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Generate v6.13 development component-gate evidence."
    )
    parser.add_argument("--bench-root", type=Path, default=bench_default)
    parser.add_argument(
        "--output-root", type=Path, default=Path("outputs/gate_components")
    )
    parser.add_argument(
        "--archive-b-root",
        type=Path,
        default=Path(r"C:\tmp\rfb-g003-archive-b"),
    )
    parser.add_argument("--gate-checklist", type=Path)
    parser.add_argument("--update-checklist", action="store_true")
    parser.add_argument("--refresh-runtime-freeze", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bench = args.bench_root.resolve(strict=True)
    output = (
        args.output_root if args.output_root.is_absolute() else bench / args.output_root
    )
    checklist = args.gate_checklist or bench.parent / "GateChecklist-v6.13.json"
    now = datetime.now(timezone.utc)
    if args.refresh_runtime_freeze:
        refresh_runtime_freeze(bench)
    summary = generate_component_evidence(bench, output, args.archive_b_root, now)
    if args.refresh_runtime_freeze:
        summary["runtime_freeze_refreshed"] = True
    if args.update_checklist:
        relative = os.path.relpath(output, checklist.parent).replace("\\", "/")
        update_gate_checklist(checklist, relative, now)
        summary["gate_checklist_updated"] = str(checklist)
    print(canonical_bytes(summary).decode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through CLI
    raise SystemExit(main())
