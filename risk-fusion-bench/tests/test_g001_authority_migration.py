from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from rfb.authority import (
    GenerationReader,
    GenesisMigrator,
    LegacyAuthorityFreeze,
    ReaderBlocked,
)

TEST_KEY = b"g001-explicit-test-key"
ATTEST_KEY = b"g001-independent-attester-key"


class Durability:
    def fsync_file(self, path):
        return None

    def fsync_dir(self, path):
        return None


def files(tmp_path: Path):
    a, b = tmp_path / "gate.json", tmp_path / "plan.json"
    a.write_text('{"a":1}', encoding="utf-8")
    b.write_text('{"b":2}', encoding="utf-8")
    return {"gate": a, "plan": b}


def authority_input(paths):
    legacy = {name: str(path) for name, path in paths.items()}
    freeze = LegacyAuthorityFreeze(legacy)
    freeze.__enter__()
    hashes = {
        name: hashlib.sha256(freeze._read_bytes(name)).hexdigest()
        for name, path in paths.items()
    }
    return legacy, hashes, freeze.proof(), freeze


def attestation(tmp_path, legacy, hashes, freeze):
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
        "root": str(tmp_path.resolve()),
        "planned_hashes": hashes,
        "identities": identities,
        "issued": now.isoformat(),
        "expires": (now + timedelta(hours=1)).isoformat(),
    }
    from rfb.authority import sign_no_writer_attestation

    return sign_no_writer_attestation(body, signer_id="signer", key=ATTEST_KEY)


def migrator(tmp_path, freeze=None):
    m = GenesisMigrator(tmp_path, signing_key=TEST_KEY, freeze_verifier=freeze)
    m.builder.durability_provider = Durability()
    return m


def test_absent_success(tmp_path):
    paths = files(tmp_path)
    legacy, hashes, proof, freeze = authority_input(paths)
    out = migrator(tmp_path, freeze).bootstrap_legacy(
        legacy, expected_hashes=hashes, freeze=proof
    )
    assert out["audit_status"] == "GENESIS_COMMITTED"


def test_pointer_unexpectedly_exists(tmp_path):
    paths = files(tmp_path)
    legacy, hashes, proof, freeze = authority_input(paths)
    (tmp_path / "CURRENT").write_text("old", encoding="utf-8")
    with pytest.raises(ReaderBlocked):
        migrator(tmp_path, freeze).bootstrap_legacy(
            legacy, expected_hashes=hashes, freeze=proof
        )


def test_legacy_drift_after_prepared(tmp_path):
    paths = files(tmp_path)
    legacy, hashes, proof, freeze = authority_input(paths)
    m = migrator(tmp_path, freeze)
    with pytest.raises(RuntimeError):
        m.bootstrap_legacy(
            legacy, expected_hashes=hashes, freeze=proof, crash_at="prepared"
        )
    fh = freeze.handles["gate"]
    fh.seek(0)
    fh.truncate()
    fh.write(b'{"a":2}')
    fh.flush()
    with pytest.raises(ReaderBlocked):
        m.bootstrap_legacy(legacy, expected_hashes=hashes, freeze=proof)
    assert not (tmp_path / "CURRENT").exists()


def test_crash_before_create_leaves_absent(tmp_path):
    paths = files(tmp_path)
    legacy, hashes, proof, freeze = authority_input(paths)
    with pytest.raises(RuntimeError):
        migrator(tmp_path, freeze).bootstrap_legacy(
            legacy, expected_hashes=hashes, freeze=proof, crash_at="before_create"
        )
    assert not (tmp_path / "CURRENT").exists()


def test_crash_after_create_reader_blocked_then_recover(tmp_path):
    paths = files(tmp_path)
    legacy, hashes, proof, freeze = authority_input(paths)
    m = migrator(tmp_path, freeze)
    with pytest.raises(RuntimeError):
        m.bootstrap_legacy(
            legacy, expected_hashes=hashes, freeze=proof, crash_at="after_create"
        )
    with pytest.raises(ReaderBlocked):
        GenerationReader(tmp_path, signing_key=TEST_KEY, authoritative=False).read()
    gid = (tmp_path / "CURRENT").read_text().strip()
    assert m.recover_commit(gid, legacy=legacy)["audit_status"] == "GENESIS_COMMITTED"


def test_no_audited_rollback_target_blocked(tmp_path):
    with pytest.raises(ReaderBlocked):
        GenerationReader(tmp_path, signing_key=TEST_KEY, authoritative=False).read()


def test_authoritative_bootstrap_requires_signed_attestation(tmp_path):
    paths = files(tmp_path)
    legacy, hashes, proof, freeze = authority_input(paths)
    trust = __import__(
        "rfb.authority", fromlist=["NoWriterTrustStore"]
    ).NoWriterTrustStore({"signer": ATTEST_KEY}, trust_epoch="e1")
    with pytest.raises(ReaderBlocked):
        migrator(tmp_path, freeze).bootstrap(
            legacy, expected_hashes=hashes, freeze=proof, trust_store=trust
        )
    out = migrator(tmp_path, freeze).bootstrap(
        legacy,
        expected_hashes=hashes,
        freeze=proof,
        no_writer_attestation=attestation(tmp_path, legacy, hashes, freeze),
        trust_store=trust,
    )
    assert {
        "runtime_authority.json",
        "checklist_authority.json",
        "genesis_metadata.json",
    }.issubset(out["receipt"]["files"])


def test_tampered_attestation_is_rejected(tmp_path):
    paths = files(tmp_path)
    legacy, hashes, proof, freeze = authority_input(paths)
    trust = __import__(
        "rfb.authority", fromlist=["NoWriterTrustStore"]
    ).NoWriterTrustStore({"signer": ATTEST_KEY}, trust_epoch="e1")
    bad = attestation(tmp_path, legacy, hashes, freeze)
    bad["planned_hashes"] = {**hashes, "gate": "0" * 64}
    with pytest.raises(ReaderBlocked):
        migrator(tmp_path, freeze).bootstrap(
            legacy,
            expected_hashes=hashes,
            freeze=proof,
            no_writer_attestation=bad,
            trust_store=trust,
        )


def test_no_writer_attester_key_reuse_rejected(tmp_path):
    paths = files(tmp_path)
    legacy, hashes, proof, freeze = authority_input(paths)
    trust = __import__(
        "rfb.authority", fromlist=["NoWriterTrustStore"]
    ).NoWriterTrustStore({"signer": TEST_KEY}, trust_epoch="e1")
    bad = attestation(tmp_path, legacy, hashes, freeze)
    from rfb.authority import sign_no_writer_attestation

    body = {k: v for k, v in bad.items() if k != "signature"}
    bad = sign_no_writer_attestation(body, signer_id="signer", key=TEST_KEY)
    with pytest.raises(ReaderBlocked, match="independent"):
        migrator(tmp_path, freeze).bootstrap(
            legacy,
            expected_hashes=hashes,
            freeze=proof,
            no_writer_attestation=bad,
            trust_store=trust,
        )
