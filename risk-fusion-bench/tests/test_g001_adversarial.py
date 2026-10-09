from __future__ import annotations
from test_g001_c3_adversarial import valid_c2_report

import json
import hashlib
import hmac
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from rfb.authority.generation import GenerationReader, ReaderBlocked
from rfb.authority.migration import GenesisMigrator, LegacyAuthorityFreeze
from rfb.broker.policy import (
    BrokerBlocked,
    CASPolicyBroker,
    ChecklistCommitter,
    sign_acl_attestation,
)
from rfb.capacity_probe import ProbeUnavailable, probe_capacity
from rfb.contracts.canonical_json import canonical_bytes, sha256_hex
from rfb.orchestration.c3 import plan_c3
from rfb.orchestration.report import C2ReportBuilder, atomic_write_report

from g001_fixture_helpers import strict_genesis
from rfb.orchestration.segment import (
    C2SegmentOrchestrator,
    validate_output_target,
    validate_trusted_probe,
)

OTHER = {
    "scratch_partial": 2_000_000_000,
    "retry_quarantine_wal": 1_000_000_000,
    "emergency_reserve": 3_000_000_000,
}
OTHER_TWO = {
    "scratch_partial": 1_000_000_000,
    "retry_quarantine_wal": 500_000_000,
    "emergency_reserve": 3_000_000_000,
}


def _legacy(root: Path) -> dict[str, str]:
    a, b = root / "GateChecklist.json", root / "ExecutionPlan.md"
    a.write_text("{}", encoding="utf-8")
    b.write_text("{}", encoding="utf-8")
    return {"checklist": str(a), "plan": str(b)}


TEST_KEY = b"g001-explicit-test-key"
ATTEST_KEY = b"g001-independent-attester-key"


class Durability:
    def fsync_file(self, p):
        pass

    def fsync_dir(self, p):
        pass


def _strict(root):
    legacy = _legacy(root)
    hashes = {
        k: __import__("hashlib").sha256(Path(v).read_bytes()).hexdigest()
        for k, v in legacy.items()
    }
    freeze = LegacyAuthorityFreeze(legacy)
    freeze.__enter__()
    proof = freeze.proof()
    m = GenesisMigrator(root, signing_key=TEST_KEY, freeze_verifier=freeze)
    m.builder.durability_provider = Durability()
    from datetime import datetime, timedelta, timezone
    from rfb.authority import NoWriterTrustStore, sign_no_writer_attestation
    from types import MethodType

    identities = {}
    for name, value in legacy.items():
        st = Path(value).stat()
        identities[name] = {
            "path": str(Path(value).resolve()),
            "dev": st.st_dev,
            "ino": st.st_ino,
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "sha256": hashes[name],
        }
    now = datetime.now(timezone.utc)
    body = {
        "trust_epoch": "e1",
        "root": str(root.resolve()),
        "planned_hashes": hashes,
        "identities": identities,
        "issued": now.isoformat(),
        "expires": (now + timedelta(hours=1)).isoformat(),
    }
    att = sign_no_writer_attestation(body, signer_id="signer", key=ATTEST_KEY)
    trust = NoWriterTrustStore({"signer": ATTEST_KEY}, trust_epoch="e1")
    original_bootstrap = m.bootstrap

    def strict_bootstrap(self, *args, **kwargs):
        kwargs.setdefault("no_writer_attestation", att)
        kwargs.setdefault("trust_store", trust)
        return original_bootstrap(*args, **kwargs)

    m.bootstrap = MethodType(strict_bootstrap, m)
    m._fixture_attestation, m._fixture_trust = att, trust
    return m, legacy, hashes, proof, freeze


def _genesis(root):
    out, _migrator, _legacy, _hashes, _freeze = strict_genesis(root, key=TEST_KEY)
    return out


def _manifest(root: Path) -> dict:
    manifest = {
        "dataset_domain": "TEP",
        "bundle_count": 1,
        "panel": ["B0", "B1", "B2", "B3", "B4", "B5", "Proposed"],
        "D_test": False,
        "input_sha256": "a" * 64,
        "allocation_commitment": "b" * 64,
        "segment_root_base": str(root.resolve()),
        "segment_id": "_g001-output",
        "run_id": "adversarial-run",
        "probe_mount": "test-mount",
        "probe_owner": "test-owner",
        "probe_mode": "0700",
        "execution_mode": "LOCAL_FIXTURE_NONCONFIRMATORY",
    }
    manifest["manifest_sha256"] = sha256_hex(canonical_bytes(manifest))
    return manifest


def test_prepared_drift_keeps_current_absent(tmp_path: Path, monkeypatch):
    legacy = _legacy(tmp_path)
    migrator, legacy, hashes, proof, _freeze = _strict(tmp_path)
    original = migrator._hash_legacy
    calls = {"n": 0}

    def drift(values):
        calls["n"] += 1
        result = original(values)
        if calls["n"] == 3:
            result = dict(result)
            result["plan"] = "0" * 64
        return result

    monkeypatch.setattr(migrator, "_hash_legacy", drift)
    with pytest.raises(ReaderBlocked):
        migrator.bootstrap(legacy, expected_hashes=hashes, freeze=proof)
    assert not (tmp_path / "CURRENT").exists()


def test_prepared_no_drift_resumes_same_generation(tmp_path: Path):
    legacy = _legacy(tmp_path)
    migrator, legacy, hashes, proof, _freeze = _strict(tmp_path)
    with pytest.raises(RuntimeError, match="GENESIS_PREPARED"):
        migrator.bootstrap(
            legacy, expected_hashes=hashes, freeze=proof, crash_at="prepared"
        )
    prepared = [
        json.loads(x)
        for x in (tmp_path / "authority_audit.jsonl").read_text().splitlines()
    ]
    gid = prepared[-1]["binding"]["generation_id"]
    result = migrator.bootstrap(legacy, expected_hashes=hashes, freeze=proof)
    assert result["generation_id"] == gid


def test_concurrent_genesis_has_one_winner(tmp_path: Path):
    owner, legacy, hashes, proof, _freeze = _strict(tmp_path)
    results, errors = [], []

    def run():
        try:
            migrator = GenesisMigrator(
                tmp_path, signing_key=TEST_KEY, freeze_verifier=_freeze
            )
            migrator.builder.durability_provider = Durability()
            results.append(
                migrator.bootstrap(
                    legacy,
                    expected_hashes=hashes,
                    freeze=proof,
                    no_writer_attestation=owner._fixture_attestation,
                    trust_store=owner._fixture_trust,
                )
            )
        except Exception as exc:  # noqa: BLE001 - loser must be captured for thread assertion
            errors.append((exc, __import__("traceback").format_exc()))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 1, repr(errors)
    assert len(errors) == 1
    assert (tmp_path / "CURRENT").read_text().strip() == results[0]["generation_id"]


@pytest.mark.parametrize("mutation", ["writable", "mixed", "tampered", "missing-audit"])
def test_reader_rejects_untrusted_or_incomplete_generation(
    tmp_path: Path, mutation: str
):
    _genesis(tmp_path)
    gid = (tmp_path / "CURRENT").read_text().strip()
    generation = tmp_path / "generations" / gid
    if mutation == "writable":
        (generation / "receipt.json").chmod(0o644)
    elif mutation == "mixed":
        for p in generation.iterdir():
            if p.is_file():
                p.chmod(0o644)
        (generation / "manifest.json").write_text(
            json.dumps({"generation_id": "other"}), encoding="utf-8"
        )
    elif mutation == "tampered":
        (generation / "receipt.json").chmod(0o644)
        (generation / "receipt.json").write_text("{}", encoding="utf-8")
    else:
        audit = tmp_path / "authority_audit.jsonl"
        rows = [
            r for r in audit.read_text().splitlines() if "GENESIS_COMMITTED" not in r
        ]
        audit.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ReaderBlocked):
        GenerationReader(tmp_path, signing_key=TEST_KEY).read()


def _live_artifact():
    gates = {
        g: {"status": "PASS", "evidence_refs": [g + ":e"], "evidence_hash": "a" * 64}
        for g in (
            "segment_cap_gate",
            "durable_result_gate",
            "result_archive_gate",
            "regeneration_gate",
            "dataset_purge_gate",
        )
    }
    snapshot = {"runtime_gate": "PASS", **gates}
    body = {
        "schema_id": "live-gate-verdict-set.v1",
        "classification": "LIVE_GATE_VERDICT_SET",
        "signer_role": "LiveGateVerifier",
        "signer_id": "fixture",
        "trust_epoch": "epoch-1",
        "source_snapshot": snapshot,
        "source_snapshot_hash": sha256_hex(canonical_bytes(snapshot)),
        "sealed_evidence_hash": "b" * 64,
        "segment_id": "seg-1",
        "manifest_hash": "c" * 64,
        "verdicts": gates,
        "issued_at": "2026-01-01T00:00:00+00:00",
    }
    return {
        **body,
        "signature": hmac.new(
            b"source", canonical_bytes(body), hashlib.sha256
        ).hexdigest(),
    }


def _broker(tmp_path: Path) -> tuple[CASPolicyBroker, dict]:
    import hashlib
    import hmac

    from rfb.authority.generation import canonical_hash
    from rfb.contracts.canonical_json import canonical_bytes

    class Dur:
        def fsync_file(self, path):
            pass

        def fsync_dir(self, path):
            pass

    genesis, _migrator, _legacy, _hashes, _freeze = strict_genesis(
        tmp_path, key=TEST_KEY
    )
    gid = genesis["generation_id"]
    submitter_key = b"submitter"
    source_key = b"source"
    broker = CASPolicyBroker(
        tmp_path,
        submitter_keys={
            "ChecklistCommitter": submitter_key,
            "LiveGateVerifier": {"key": source_key, "trust_epoch": "epoch-1"},
        },
        signing_key=TEST_KEY,
        durability_provider=Dur(),
        acl_attestation=sign_acl_attestation(
            key=b"acl",
            root=tmp_path,
            trust_epoch="acl-1",
            generation_id=gid,
            checklist_hash=canonical_hash({}),
            attester_id="acl-attester",
            key_id="acl-key-1",
            acl_entries=[{"principal": "broker", "access": "write"}],
        ),
        acl_attestation_key=b"acl",
        acl_attester_id="acl-attester",
        acl_attester_key_id="acl-key-1",
        acl_trust_epoch="acl-1",
    )
    artifact = _live_artifact()
    # The genesis fixture has no checklist.json, so its committed checklist
    # snapshot is the canonical empty mapping.  Bind the verdict artifact to
    # that actual predecessor rather than using an unrelated placeholder.
    artifact["source_snapshot"] = {}
    artifact["source_snapshot_hash"] = canonical_hash({})
    artifact_body = dict(artifact)
    artifact_body.pop("signature", None)
    artifact["signature"] = hmac.new(
        source_key, canonical_bytes(artifact_body), hashlib.sha256
    ).hexdigest()
    source_hash = canonical_hash(artifact)
    proof = {
        "source_artifact": artifact,
        "source_snapshot": "actual-checklist",
        "source_hash": source_hash,
        "source_schema_id": "live-gate-verdict-set.v1",
        "trust_epoch": "epoch-1",
    }
    source_signature = hmac.new(
        source_key, canonical_bytes(proof), hashlib.sha256
    ).hexdigest()
    envelope = ChecklistCommitter(submitter_key).envelope(
        source_artifact=artifact,
        source_snapshot="actual-checklist",
        source_hash=source_hash,
        source_signer_role="LiveGateVerifier",
        source_signature=source_signature,
        source_schema_id="live-gate-verdict-set.v1",
        trust_epoch="epoch-1",
        projection_policy_id="frozen-default",
        projection_policy_version="1",
        expected_current_generation_id=(tmp_path / "CURRENT").read_text().strip(),
        expected_checklist_hash=broker.current_authority()["checklist_hash"],
        patch={
            "checklist": {
                **{
                    g: artifact["verdicts"][g]
                    for g in (
                        "segment_cap_gate",
                        "durable_result_gate",
                        "result_archive_gate",
                        "regeneration_gate",
                        "dataset_purge_gate",
                    )
                },
            }
        },
    )
    return broker, envelope


def test_broker_rejects_stale_expected_pair(tmp_path: Path):
    broker, envelope = _broker(tmp_path)
    stale = replace(
        envelope, expected_current_generation_id="stale", submitter_signature=""
    )
    stale = envelope.__class__.sign(
        key=b"submitter",
        **{k: v for k, v in stale.__dict__.items() if k != "submitter_signature"},
    )
    with pytest.raises(BrokerBlocked):
        broker.submit(stale)


def test_broker_rejects_forged_projection_or_missing_proof(tmp_path: Path):
    broker, envelope = _broker(tmp_path)
    forged = replace(envelope, patch={"forged": 1}, submitter_signature="")
    forged = envelope.__class__.sign(
        key=b"submitter",
        **{k: v for k, v in forged.__dict__.items() if k != "submitter_signature"},
    )
    with pytest.raises(BrokerBlocked):
        broker.submit(forged)


def test_broker_after_cas_before_committed_blocks_then_recovers(tmp_path: Path):
    broker, envelope = _broker(tmp_path)
    with pytest.raises(RuntimeError, match="CAS"):
        broker.submit(envelope, crash_at="cas")
    with pytest.raises(ReaderBlocked):
        GenerationReader(tmp_path, signing_key=TEST_KEY).read()


@pytest.mark.parametrize(
    "key", ["prediction", "effect", "winner", "rank", "p", "CI", "raw_truth", "truth"]
)
def test_c2_rejects_forbidden_observation_keys(key):
    with pytest.raises(ValueError):
        C2ReportBuilder({"manifest_sha256": "m"}).build(
            {key: 1}, [{"sampled_at": 0}, {"sampled_at": 1}]
        )


def test_c2_rejects_telemetry_gap_and_segment_gap():
    builder = C2ReportBuilder({"manifest_sha256": "m"})
    states = [
        "PLANNED",
        "ADMITTED",
        "MATERIALIZING",
        "EXECUTING",
        "RESULT_SEALED_LOCAL",
    ]
    with pytest.raises(ValueError, match="gap"):
        builder.build(
            {},
            [
                {"state": states[i], "sampled_at": (0 if i < 4 else 31)}
                for i in range(5)
            ],
        )
    orch = C2SegmentOrchestrator(
        _manifest(Path(".")), Path("_g001-output"), project_root=Path(".")
    )
    with pytest.raises(ValueError, match="gap"):
        orch.transition("ADMITTED", sampled_at=0)
        orch.transition("MATERIALIZING", sampled_at=31)


def test_untrusted_probe_and_root_escape_are_rejected(tmp_path: Path):
    with pytest.raises(ProbeUnavailable):
        probe_capacity(tmp_path, owned_external_layers_bytes=None)
    with pytest.raises(ValueError):
        validate_trusted_probe({"probe_id": "x", "source": "bare"})
    with pytest.raises(ValueError):
        validate_output_target(tmp_path.parent / "outside", project_root=tmp_path)
    link = tmp_path / "link"
    target = tmp_path / "target"
    target.mkdir()
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink unavailable")
    with pytest.raises(ValueError):
        validate_output_target(link, project_root=tmp_path)


def test_sealed_report_cannot_be_overwritten(tmp_path: Path):
    path = tmp_path / "report.json"
    durability = Durability()
    atomic_write_report(path, {"x": 1}, durability_provider=durability)
    with pytest.raises(FileExistsError):
        atomic_write_report(path, {"x": 2}, durability_provider=durability)


@pytest.mark.parametrize("bad", [True, None, float("nan"), float("inf"), 1.5, -1, 0])
def test_c3_rejects_invalid_bounds_fail_closed(bad):
    report = plan_c3(
        c2_report=valid_c2_report(),
        frozen_planning_upper_bound_dataset_bytes=bad,
        frozen_planning_upper_bound_result_bytes=1,
        frozen_planning_upper_bound_total_peak_bytes=1,
        other_subbudget_bounds=OTHER,
    ).report
    assert report["planning_decision"] == "BLOCKED_NO_CAPACITY"
    assert report["c2_evidence_state"] == "SIZING_REPORTED"
    assert report["storage_disposition"] == "QUARANTINED_NO_DELETE"


def test_c3_zero_and_n_segment_orthogonality():
    zero = plan_c3(
        c2_report=valid_c2_report(),
        frozen_planning_upper_bound_dataset_bytes=20_000_000_000,
        frozen_planning_upper_bound_result_bytes=1,
        frozen_planning_upper_bound_total_peak_bytes=1,
        other_subbudget_bounds=OTHER,
    ).report
    assert zero["planning_decision"] == "BLOCKED_NO_CAPACITY"
    one = plan_c3(
        c2_report=valid_c2_report(),
        frozen_planning_upper_bound_dataset_bytes=16_000_000_000,
        frozen_planning_upper_bound_result_bytes=3_000_000_000,
        frozen_planning_upper_bound_total_peak_bytes=22_000_000_000,
        other_subbudget_bounds=OTHER,
    ).report
    assert (
        one["n_segment"] == 1
        and one["planning_decision"] == "BLOCKED_SEGMENT_TOO_SMALL_FOR_REGENERATION"
    )
    two = plan_c3(
        c2_report=valid_c2_report(),
        frozen_planning_upper_bound_dataset_bytes=8_000_000_000,
        frozen_planning_upper_bound_result_bytes=1_500_000_000,
        frozen_planning_upper_bound_total_peak_bytes=11_000_000_000,
        other_subbudget_bounds=OTHER_TWO,
    ).report
    assert two["n_segment"] == 2 and two["planning_decision"] != "BLOCKED_NO_CAPACITY"


@pytest.mark.parametrize(
    "field", ["manifest_sha256", "input_sha256", "allocation_commitment"]
)
def test_c2_manifest_required_commitments(field, tmp_path):
    m = _manifest(tmp_path)
    m.pop(field)
    with pytest.raises(ValueError):
        from rfb.orchestration.segment import validate_manifest

        validate_manifest(m)


def test_c2_report_rejects_unknown_terminal_row_and_bad_hash():
    from rfb.orchestration.segment import PANEL_METHODS

    rows = [
        {
            "method_id": m,
            "terminal_state": "SEALED",
            "panel_closed": True,
            "result_sha256": "0" * 64,
            "durable_manifest_sha256": "1" * 64,
        }
        for m in PANEL_METHODS
    ]
    body = {
        "terminal_rows": rows,
        "capacity_transitions": [{"capacity_bytes": 1}],
    }
    telemetry = [
        {
            "state": s,
            "sampled_at": i,
            "gpu_used": False,
            "gpu_not_used": True,
            "capacity_bytes": 1,
        }
        for i, s in enumerate(
            ["PLANNED", "ADMITTED", "MATERIALIZING", "EXECUTING", "RESULT_SEALED_LOCAL"]
        )
    ]
    m = {"manifest_sha256": "a" * 64}
    rows[0]["unexpected"] = 1
    with pytest.raises(ValueError, match="unknown field"):
        C2ReportBuilder(m).build(body, telemetry)
    rows[0].pop("unexpected")
    rows[0]["result_sha256"] = "bad"
    with pytest.raises(ValueError, match="result_sha256"):
        C2ReportBuilder(m).build(body, telemetry)


def test_c2_report_fsync_failure_is_not_live_evidence(tmp_path):
    class Broken:
        def fsync_dir(self, path):
            raise OSError("fsync failed")

    with pytest.raises(OSError, match="fsync"):
        atomic_write_report(
            tmp_path / "report.json", {"x": 1}, durability_provider=Broken()
        )
