"""Generate and independently revalidate development-only G004 evidence."""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .archive_qa import PACKAGE_FILES, _sha256
from .archive_targets import load_archive_targets
from .closeout_audit import (
    copy_closeout_to_local_ab,
    seal_closeout,
    validate_closeout,
)
from .contracts.canonical_json import canonical_bytes, sha256_hex
from .purge import (
    build_purge_plan,
    create_development_purge_capability,
    create_purge_authorization,
    execute_purge,
    freeze_purge_manifest,
    reconcile_purge,
)
from .regeneration import (
    RuntimeCommitmentAuthority,
    build_regeneration_expectation,
    execute_regeneration_plan_v3,
    build_regeneration_attestation,
    finalize_regeneration_verdict_v2,
    freeze_regeneration_plan_v3,
    exact_replay_policy_hash,
    panel_commitment,
    payload_commitment,
    select_frozen_samples,
    verify_regeneration_sample,
)

METHOD_IDS = ("B0", "B1", "B2", "B3", "B4", "B5", "Proposed")
DEVELOPMENT_TRUST_STORE = {
    "key_id": "regen-attester-1",
    "role": "RegenerationAttester",
    "trust_epoch": "dev-1",
    "secret": "development-attester-secret-123",
    "independent_key_ids": ["regen-attester-1"],
}
SEGMENT_ID = "DEV-G004-SEGMENT-001"
EVIDENCE_CLASS = "DEVELOPMENT_CONTROLLED_FIXTURE_NOT_EXPERIMENT_RESULT"

_REGEN_SCHEMA = "src/rfb/contracts/regeneration_sampling_qa.schema.json"
_LEDGER_SCHEMA = "src/rfb/contracts/dataset_purge_ledger.schema.json"
_TOMBSTONE_SCHEMA = "src/rfb/contracts/dataset_purge_tombstone.schema.json"


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(dict(value)) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema(bench: Path, relative: str) -> dict[str, Any]:
    value = _load_json(bench / relative)
    if not isinstance(value, dict):
        raise ValueError(f"schema is not an object: {relative}")
    return value


def _method_panel(bundle_id: str) -> dict[str, dict[str, str]]:
    return {
        method_id: {
            "result_sha256": sha256_hex(
                canonical_bytes(
                    {
                        "bundle_id": bundle_id,
                        "evidence_class": EVIDENCE_CLASS,
                        "method_id": method_id,
                    }
                )
            )
        }
        for method_id in METHOD_IDS
    }


def _public_sample(report: Mapping[str, Any]) -> dict[str, Any]:
    return dict(report)


def _embedded_artifact(path: Path, field: str, body: Mapping[str, Any]) -> str:
    """Write a deterministic self-hashed runtime artifact and return its hash."""
    digest = sha256_hex(canonical_bytes(dict(body)))
    _atomic_json(path, {**dict(body), field: digest})
    return digest


def _prepare_runtime_authority(
    bench: Path,
) -> tuple[RuntimeCommitmentAuthority, Path, list[dict[str, Any]]]:
    """Load the frozen authority, or create a temporary fixture authority.

    A real bench is frozen by ``refresh_runtime_freeze`` before evidence
    generation.  In that case this function must be read-only with respect to
    the runtime artifacts; only contract tests with an otherwise empty bench
    may take the fixture-construction path below.
    """
    runtime = bench / "outputs/runtime_gate"
    runtime.mkdir(parents=True, exist_ok=True)
    generator = bench / "src/rfb/g004_evidence.py"
    config_path = bench / "development_regeneration_config.json"
    frozen_paths = (
        runtime / "source_tree_manifest.json",
        runtime / "runtime_baseline.json",
        runtime / "method_registry.json",
        runtime / "container_lock.json",
        runtime / "seed_commitment.json",
        runtime / "allocation_commitment.json",
        config_path,
    )
    if all(path.is_file() for path in frozen_paths):
        authority = RuntimeCommitmentAuthority.load(
            bench,
            generator_path="src/rfb/g004_evidence.py",
            segment_config_path="development_regeneration_config.json",
        )
        pre_body = {
            "schema_version": "segment-ledger-entry.v1",
            "event": "SEGMENT_PRE_EXECUTION",
            "segment_id": SEGMENT_ID,
            "state": "PLANNED",
            "prev_hash": "0" * 64,
        }
        pre_hash = sha256_hex(canonical_bytes(pre_body))
        return authority, config_path, [{**pre_body, "entry_hash": pre_hash}]
    if not generator.is_file():
        # Temporary test benches contain contracts only; bind to this generator
        # implementation by copying it into the bench before authority loading.
        source = Path(__file__).resolve()
        generator.parent.mkdir(parents=True, exist_ok=True)
        generator.write_bytes(source.read_bytes())
    registry_hash = _embedded_artifact(
        runtime / "method_registry.json",
        "registry_sha256",
        {"methods": list(METHOD_IDS)},
    )
    container_hash = _embedded_artifact(
        runtime / "container_lock.json",
        "container_definition_sha256",
        {"runtime": "g004-development-fixture"},
    )
    seed_hash = _embedded_artifact(
        runtime / "seed_commitment.json",
        "seed_commitment_sha256",
        {"algorithm_seed": 613},
    )
    allocation_hash = _embedded_artifact(
        runtime / "allocation_commitment.json",
        "allocation_commitment_sha256",
        {"allocation": SEGMENT_ID},
    )
    pre_body = {
        "schema_version": "segment-ledger-entry.v1",
        "event": "SEGMENT_PRE_EXECUTION",
        "segment_id": SEGMENT_ID,
        "state": "PLANNED",
        "prev_hash": "0" * 64,
    }
    pre_hash = sha256_hex(canonical_bytes(pre_body))
    config = {
        "schema_version": "development-regeneration-config.v1",
        "segment_id": SEGMENT_ID,
        "sample_selection_seed": 613,
        "pre_execution_state": "PLANNED",
        "replay_policy_hash": exact_replay_policy_hash(),
        "bundle_count": 200,
        "sample_rule": "max(2,ceil(0.01*N))_without_replacement",
        "pre_execution_ledger_head": pre_hash,
    }
    _atomic_json(config_path, config)
    source_files: list[dict[str, Any]] = []
    for source_root in (bench / "src", bench / "tests"):
        if not source_root.exists():
            continue
        for source_path in source_root.rglob("*"):
            if (
                not source_path.is_file()
                or source_path.is_symlink()
                or "__pycache__" in source_path.parts
                or source_path.suffix in {".pyc", ".pyo"}
            ):
                continue
            payload = source_path.read_bytes()
            source_files.append(
                {
                    "path": source_path.relative_to(bench).as_posix(),
                    "bytes": len(payload),
                    "sha256": sha256_hex(payload),
                }
            )
    source_files.sort(key=lambda item: item["path"])
    source_tree_hash = sha256_hex(canonical_bytes(source_files))
    _atomic_json(
        runtime / "source_tree_manifest.json",
        {"files": source_files, "source_tree_sha256": source_tree_hash},
    )
    baseline_body = {
        "schema_version": "runtime-baseline.v1",
        "code_baseline": {
            "source_tree_manifest": "source_tree_manifest.json",
            "source_tree_sha256": source_tree_hash,
        },
        "method_registry": {
            "path": "method_registry.json",
            "registry_sha256": registry_hash,
        },
        "container": {
            "container_lock": "container_lock.json",
            "container_definition_sha256": container_hash,
        },
        "seed_commitment": {"path": "seed_commitment.json", "sha256": seed_hash},
        "allocation_commitment": {
            "path": "allocation_commitment.json",
            "sha256": allocation_hash,
        },
    }
    baseline = {
        **baseline_body,
        "runtime_baseline_sha256": sha256_hex(canonical_bytes(baseline_body)),
    }
    _atomic_json(runtime / "runtime_baseline.json", baseline)
    authority = RuntimeCommitmentAuthority.load(
        bench,
        generator_path="src/rfb/g004_evidence.py",
        segment_config_path="development_regeneration_config.json",
    )
    return authority, config_path, [{**pre_body, "entry_hash": pre_hash}]


def _regeneration_evidence(
    bench: Path, output: Path, generated_at: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    bundle_ids = [f"DEV-BUNDLE-{index:03d}" for index in range(1, 201)]
    authority, _config_path, pre_rows = _prepare_runtime_authority(bench)
    pre_head = pre_rows[-1]["entry_hash"]
    plan = freeze_regeneration_plan_v3(
        segment_id=SEGMENT_ID,
        bundle_ids=bundle_ids,
        authority=authority,
        replay_policy_hash=exact_replay_policy_hash(),
        sample_selection_seed=613,
        pre_execution_state="PLANNED",
        pre_execution_ledger_head=pre_head,
    )
    freeze_event = plan["freeze_event"]
    execution_rows = [*pre_rows, freeze_event]
    # Persist the ordered proof before any sample is executed.  It is kept
    # only in-memory here and is copied into the JSON-safe evidence below.
    reports: list[dict[str, Any]] = []
    expectations: list[dict[str, Any]] = []
    for bundle_id in plan["selected_ids"]:
        payload = {
            "bundle_id": bundle_id,
            "evidence_class": EVIDENCE_CLASS,
            "fixture_value": len(bundle_id),
        }
        panel = _method_panel(bundle_id)
        expectation = build_regeneration_expectation(
            plan=plan,
            bundle_id=bundle_id,
            payload_commitment_sha256=payload_commitment(payload),
            expected_panel_commitment_sha256=panel_commitment(panel),
        )
        expectations.append(expectation)
        report = verify_regeneration_sample(
            plan=plan,
            expectation=expectation,
            authority_root=bench,
            current_authority=authority,
            freeze_event=freeze_event,
            execution_ledger_rows=execution_rows,
            current_bundle_ids=bundle_ids,
            regenerated_payload=dict(payload),
            original_payload=payload,
            original_panel=panel,
            regenerated_panel={key: dict(value) for key, value in panel.items()},
        )
        if report.get("regeneration_verified") is not True:
            raise RuntimeError(f"development regeneration failed for {bundle_id}")
        reports.append(report)
    verdict = finalize_regeneration_verdict_v2(plan, expectations, reports)
    public_plan = {
        key: value
        for key, value in plan.items()
        if key not in {"canonical_bytes", "freeze_event"}
    }
    public_authority = dict(authority)
    document: dict[str, Any] = {
        "schema_version": "regeneration-sampling-qa.v3",
        "generated_at": generated_at,
        "status": "REGEN_CONSISTENT_UNATTESTED",
        "authoritative": False,
        "development_status": "PASS",
        "live_status": "PENDING",
        "development_only": True,
        "local_live_gate_passed": False,
        "regeneration_verified": True,
        "purge_authorized": False,
        "frozen_before_execution": True,
        "segment_id": SEGMENT_ID,
        "bundle_count": len(bundle_ids),
        "sample_count": len(plan["selected_ids"]),
        "sample_rule": "max(2,ceil(0.01*N))_without_replacement",
        "selected_bundle_ids": list(plan["selected_ids"]),
        "no_replacement": len(plan["selected_ids"]) == len(set(plan["selected_ids"])),
        "runtime_authority": public_authority,
        "plan": public_plan,
        "freeze_event": freeze_event,
        "execution_ledger_rows": execution_rows,
        "expectations": expectations,
        "reports": reports,
        "aggregate_verdict": verdict,
    }
    Draft202012Validator(_schema(bench, _REGEN_SCHEMA)).validate(document)
    _atomic_json(output / "regeneration/regeneration_sampling_qa.json", document)
    return document, plan, verdict


def _authorization_prerequisites(
    purge_plan: Mapping[str, Any],
    regeneration_plan: Mapping[str, Any],
    regeneration_verdict: Mapping[str, Any],
    package: Path,
    archive_expected: Mapping[str, str],
) -> dict[str, Any]:
    archive_commitment = sha256_hex(
        canonical_bytes(dict(sorted(archive_expected.items())))
    )
    return {
        "result_sealed": True,
        "archive_a_verified": True,
        "archive_b_verified": True,
        "truth_isolation_verified": True,
        "truth_isolation_hash": sha256_hex(
            canonical_bytes({"scorer_only": True, "development_only": True})
        ),
        "contains_raw_dataset": False,
        "segment_state": "REGEN_VERIFIED",
        "manifest_hash": purge_plan["manifest_hash"],
        "state_signature": sha256_hex(
            canonical_bytes(
                {
                    "plan_hash": purge_plan["plan_hash"],
                    "state": "REGEN_VERIFIED",
                    "verdict_hash": regeneration_verdict["verdict_hash"],
                }
            )
        ),
        "result_manifest_hash": _sha256(package / "durable_result_manifest.json"),
        "archive_a_hash": archive_commitment,
        "archive_b_hash": archive_commitment,
        "archive_a_readback_root": archive_commitment,
        "archive_b_readback_root": archive_commitment,
        "truth_isolation_commitment": sha256_hex(
            canonical_bytes({"scorer_only": True, "development_only": True})
        ),
        "sealed_package_root": _sha256(package / "durable_result_manifest.json"),
        "regeneration_plan": regeneration_plan,
        "regeneration_verdict": regeneration_verdict,
        "dataset_approval_commitment": sha256_hex(
            canonical_bytes(
                {
                    "scope": "DEVELOPMENT_FIXTURE_DATASET_APPROVAL",
                    "manifest_hash": purge_plan["manifest_hash"],
                    "segment_id": purge_plan["segment_id"],
                }
            )
        ),
        "stat_approval_commitment": sha256_hex(
            canonical_bytes(
                {
                    "scope": "DEVELOPMENT_FIXTURE_STAT_APPROVAL",
                    "sample_count": regeneration_verdict["sample_count"],
                    "verdict_hash": regeneration_verdict["verdict_hash"],
                }
            )
        ),
        "development_only": True,
        "live_destructive_use_allowed": False,
    }


def _purge_and_closeout_evidence(
    bench: Path,
    output: Path,
    package: Path,
    regeneration: Mapping[str, Any],
    regeneration_plan: Mapping[str, Any],
    regeneration_verdict: Mapping[str, Any],
    generated_at: str,
    trust_store: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    effective_trust_store = (
        DEVELOPMENT_TRUST_STORE if trust_store is None else trust_store
    )
    purge_root = output / "purge"
    purge_root.mkdir(parents=True, exist_ok=True)
    archive_expected = {name: _sha256(package / name) for name in sorted(PACKAGE_FILES)}
    archive_commitment = sha256_hex(
        canonical_bytes(dict(sorted(archive_expected.items())))
    )
    truth_commitment = sha256_hex(
        canonical_bytes({"scorer_only": True, "development_only": True})
    )
    attestation = build_regeneration_attestation(
        plan=regeneration_plan,
        expectations=regeneration.get("expectations", []),
        reports=regeneration.get("reports", []),
        verdict=regeneration_verdict,
        freeze_event=regeneration.get("freeze_event"),
        execution_ledger_rows=regeneration.get("execution_ledger_rows", []),
        attester=effective_trust_store,
        independent_key_ids=effective_trust_store["independent_key_ids"],
        sealed_commitments={
            "result_manifest_hash": archive_expected["durable_result_manifest.json"],
            "archive_a_readback_root": archive_commitment,
            "archive_b_readback_root": archive_commitment,
            "truth_isolation_commitment": truth_commitment,
            "sealed_package_root": archive_expected["durable_result_manifest.json"],
        },
    )
    ledger_jsonl = purge_root / "dataset_purge_ledger.jsonl"
    archive_config = _load_json(output / "archive/result_archive_targets.json")
    archive_targets = load_archive_targets(archive_config)
    tombstone_path = purge_root / "dataset_purge_tombstone.json"
    with tempfile.TemporaryDirectory(prefix="rfb-g004-fixture-") as temporary:
        fixture_root = Path(temporary) / "controlled_fixture_dataset"
        (fixture_root / "ephemeral").mkdir(parents=True)
        (fixture_root / "scratch").mkdir()
        (fixture_root / "ephemeral/bundle.bin").write_bytes(b"g004-development-bundle")
        (fixture_root / "scratch/cache.tmp").write_bytes(b"g004-development-cache")
        frozen_manifest = freeze_purge_manifest(
            fixture_root,
            [
                {"path": "ephemeral/bundle.bin", "kind": "EPHEMERAL_DATASET"},
                {"path": "scratch/cache.tmp", "kind": "TRANSIENT_RUNTIME"},
            ],
            segment_id=SEGMENT_ID,
        )
        plan = build_purge_plan(fixture_root, frozen_manifest)
        capability = create_development_purge_capability(
            fixture_root, quiescence_confirmed=True
        )
        regeneration["regeneration_attestation"] = attestation
        strict_evidence = {
            "plan": regeneration_plan,
            "expectations": regeneration.get("expectations", []),
            "reports": regeneration.get("reports", []),
            "verdict": regeneration_verdict,
            "runtime_authority": regeneration.get("runtime_authority"),
            "current_authority": regeneration.get("runtime_authority"),
            "freeze_event": regeneration.get("freeze_event"),
            "execution_ledger_rows": regeneration.get("execution_ledger_rows", []),
            "current_bundle_ids": regeneration_plan["bundle_ids"],
            "regeneration_attestation": attestation,
        }
        if not strict_evidence["execution_ledger_rows"]:
            raise RuntimeError(
                "regeneration QA is missing persisted execution ledger rows"
            )
        authorization = create_purge_authorization(
            _authorization_prerequisites(
                plan,
                regeneration_plan,
                regeneration_verdict,
                package,
                archive_expected,
            ),
            plan,
            authority_root=bench,
            regeneration_evidence=strict_evidence,
            development_capability=capability,
            trust_store=effective_trust_store,
        )
        _atomic_json(purge_root / "dataset_purge_authorization.json", authorization)
        execution = execute_purge(
            plan,
            authorization,
            dry_run=False,
            ledger_path=ledger_jsonl,
            trust_store=effective_trust_store,
        )
        allocated = sum(entry["lstat"]["allocated_bytes"] for entry in plan["entries"])
        tombstone = reconcile_purge(
            plan,
            ledger_jsonl,
            tombstone_path,
            archive_targets=archive_targets,
            archive_expected=archive_expected,
            trusted_open_deleted_bytes=0,
            development_only=True,
            space_tolerance_bytes=allocated + 4_000_000,
        )
        if tombstone.get("pass") is not True:
            raise RuntimeError(f"development purge reconciliation failed: {tombstone}")
        events = [
            json.loads(line)
            for line in ledger_jsonl.read_text(encoding="utf-8").splitlines()
        ]
        ledger_document: dict[str, Any] = {
            "schema_version": "dataset-purge-ledger-document.v2",
            "version": 2,
            "development_status": "PASS",
            "live_status": "PENDING",
            "development_only": True,
            "local_live_gate_passed": False,
            "segment_id": SEGMENT_ID,
            "plan_hash": plan["plan_hash"],
            "manifest_hash": plan["manifest_hash"],
            "ledger_head": events[-1]["entry_hash"],
            "events": events,
        }
        Draft202012Validator(_schema(bench, _LEDGER_SCHEMA)).validate(ledger_document)
        Draft202012Validator(_schema(bench, _TOMBSTONE_SCHEMA)).validate(tombstone)
        _atomic_json(purge_root / "dataset_purge_ledger.json", ledger_document)

    closeout_root = output / "closeout"
    closeout_root.mkdir()
    closeout_regeneration = dict(regeneration)
    closeout_regeneration.update(
        {
            "plan": {
                key: value
                for key, value in regeneration_plan.items()
                if key != "canonical_bytes"
            },
            "aggregate_verdict": regeneration_verdict,
            "current_authority": regeneration.get("runtime_authority"),
            "execution_ledger_rows": regeneration.get("execution_ledger_rows", []),
            "current_bundle_ids": regeneration_plan["bundle_ids"],
        }
    )
    sealed = seal_closeout(
        package,
        closeout_root / "fixture_package",
        segment_id=SEGMENT_ID,
        archive_expected=archive_expected,
        regeneration=closeout_regeneration,
        purge_authorization=authorization,
        purge_ledger=ledger_document,
        purge_tombstone=tombstone,
        authority_root=str(bench),
        trust_store=effective_trust_store,
    )
    copied = copy_closeout_to_local_ab(
        closeout_root / "fixture_package",
        closeout_root / "archive_a",
        closeout_root / "archive_b",
        authority_root=str(bench),
        trust_store=effective_trust_store,
    )
    closeout_qa = {
        "schema_version": "segment-closeout-qa.v1",
        "generated_at": generated_at,
        "development_status": "PASS"
        if sealed.get("pass") is True and copied.get("pass") is True
        else "FAIL",
        "live_status": "PENDING",
        "development_only": True,
        "local_live_gate_passed": False,
        "controlled_fixture_destructive_path": True,
        "real_dataset_deleted": False,
        "remote_contacted": False,
        "formal_stage_admission_created": False,
        "purge_execution": execution,
        "sealed": sealed,
        "local_archive_ab": copied,
    }
    if closeout_qa["development_status"] != "PASS":
        raise RuntimeError(f"development closeout QA failed: {closeout_qa}")
    _atomic_json(closeout_root / "segment_closeout_qa.json", closeout_qa)
    return ledger_document, tombstone, closeout_qa


def generate_g004_development_evidence(
    bench: Path,
    output: Path,
    package: Path,
    generated_at: str,
    trust_store: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    regeneration, regeneration_plan, regeneration_verdict = _regeneration_evidence(
        bench, output, generated_at
    )
    ledger, tombstone, closeout = _purge_and_closeout_evidence(
        bench,
        output,
        package,
        regeneration,
        regeneration_plan,
        regeneration_verdict,
        generated_at,
        trust_store=trust_store,
    )
    return {
        "regeneration": regeneration["development_status"],
        "purge": "PASS" if tombstone["pass"] else "FAIL",
        "closeout": closeout["development_status"],
        "ledger_head": ledger["ledger_head"],
    }


def _validate_hash_chain(events: Any) -> list[str]:
    if not isinstance(events, list) or not events:
        return ["purge ledger events missing"]
    errors: list[str] = []
    previous = ""
    for index, row in enumerate(events):
        if not isinstance(row, dict):
            errors.append(f"purge ledger row {index} is not an object")
            continue
        unsigned = {key: value for key, value in row.items() if key != "entry_hash"}
        if row.get("prev_hash") != previous or row.get("entry_hash") != sha256_hex(
            canonical_bytes(unsigned)
        ):
            errors.append(f"purge ledger row {index} hash chain mismatch")
        previous = row.get("entry_hash", "")
    if events[-1].get("event") != "PURGE_COMMITTED":
        errors.append("purge ledger does not end in PURGE_COMMITTED")
    return errors


def validate_g004_development_evidence(bench: Path, output: Path) -> list[str]:
    errors: list[str] = []
    try:
        regeneration = _load_json(output / "regeneration/regeneration_sampling_qa.json")
        Draft202012Validator(_schema(bench, _REGEN_SCHEMA)).validate(regeneration)
        plan = regeneration["plan"]
        plan_body = {key: value for key, value in plan.items() if key != "plan_hash"}
        plan_runtime = {
            **plan,
            "canonical_bytes": canonical_bytes(plan_body),
            "freeze_event": regeneration["freeze_event"],
        }
        if plan["plan_hash"] != sha256_hex(plan_runtime["canonical_bytes"]):
            errors.append("regeneration plan hash mismatch")
        authority = RuntimeCommitmentAuthority.load(
            bench,
            generator_path=plan["runtime_authority"]["generator_path"],
            segment_config_path=plan["runtime_authority"]["segment_config_path"],
        )
        if authority.to_dict() != regeneration["runtime_authority"]:
            errors.append("regeneration runtime authority mismatch")
        selected = select_frozen_samples(
            plan["bundle_ids"], plan["sample_selection_seed"], plan["segment_id"]
        )
        if (
            selected != plan["selected_ids"]
            or selected != regeneration["selected_bundle_ids"]
        ):
            errors.append("regeneration frozen sample mismatch")
        expected_count = max(2, math.ceil(0.01 * regeneration["bundle_count"]))
        if (
            regeneration["sample_count"] != expected_count
            or len(regeneration["reports"]) != expected_count
        ):
            errors.append("regeneration sample-count formula mismatch")
        rows = regeneration.get("execution_ledger_rows", [])
        if not rows:
            raise ValueError("regeneration QA execution ledger rows are missing")
        execute_regeneration_plan_v3(
            plan_runtime,
            authority_root=bench,
            current_authority=authority,
            freeze_event=regeneration["freeze_event"],
            execution_ledger_rows=rows,
            current_bundle_ids=plan["bundle_ids"],
            segment_id=plan["segment_id"],
            sample_selection_seed=plan["sample_selection_seed"],
        )
        rebuilt = finalize_regeneration_verdict_v2(
            plan_runtime, regeneration["expectations"], regeneration["reports"]
        )
        if rebuilt != regeneration["aggregate_verdict"]:
            errors.append("regeneration aggregate verdict is not reconstructive")
        if rebuilt.get("regeneration_verified") is not True:
            errors.append("regeneration aggregate verdict is not successful")
    except Exception as exc:
        errors.append(f"regeneration evidence invalid: {exc}")

    try:
        ledger = _load_json(output / "purge/dataset_purge_ledger.json")
        Draft202012Validator(_schema(bench, _LEDGER_SCHEMA)).validate(ledger)
        errors.extend(_validate_hash_chain(ledger["events"]))
        if ledger["ledger_head"] != ledger["events"][-1]["entry_hash"]:
            errors.append("purge ledger head mismatch")
        tombstone = _load_json(output / "purge/dataset_purge_tombstone.json")
        Draft202012Validator(_schema(bench, _TOMBSTONE_SCHEMA)).validate(tombstone)
        unsigned_tombstone = {
            key: value for key, value in tombstone.items() if key != "tombstone_hash"
        }
        if tombstone["tombstone_hash"] != sha256_hex(
            canonical_bytes(unsigned_tombstone)
        ):
            errors.append("purge tombstone hash mismatch")
        for key in ("segment_id", "plan_hash", "manifest_hash"):
            if tombstone[key] != ledger[key]:
                errors.append(f"purge tombstone/ledger {key} mismatch")
        if tombstone["purge_ledger_head"] != ledger["ledger_head"]:
            errors.append("purge tombstone/ledger head mismatch")
    except Exception as exc:
        errors.append(f"purge evidence invalid: {exc}")

    fixture_root = output / "purge/controlled_fixture_dataset"
    if fixture_root.exists():
        errors.append("controlled purge fixture leaked into audit evidence output")
    try:
        closeout = validate_closeout(
            output / "closeout/fixture_package",
            authority_root=str(bench),
            trust_store=DEVELOPMENT_TRUST_STORE,
        )
        if closeout.get("pass") is not True:
            errors.append(f"closeout package invalid: {closeout.get('errors')}")
        closeout_qa = _load_json(output / "closeout/segment_closeout_qa.json")
        if (
            closeout_qa.get("development_status") != "PASS"
            or closeout_qa.get("live_status") != "PENDING"
            or closeout_qa.get("local_live_gate_passed") is not False
            or closeout_qa.get("real_dataset_deleted") is not False
            or closeout_qa.get("remote_contacted") is not False
            or closeout_qa.get("formal_stage_admission_created") is not False
        ):
            errors.append("closeout QA development/formal separation failed")
    except Exception as exc:
        errors.append(f"closeout evidence invalid: {exc}")
    return errors


__all__ = [
    "generate_g004_development_evidence",
    "validate_g004_development_evidence",
]
