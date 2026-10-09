from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rfb.authority import GenesisMigrator, LegacyAuthorityFreeze, NoWriterTrustStore
from rfb.authority import sign_no_writer_attestation


TEST_KEY = b"g001-explicit-test-key"
ATTEST_KEY = b"g001-independent-attester-key"


class Durability:
    def fsync_file(self, path):
        return None

    def fsync_dir(self, path):
        return None


def strict_genesis(root: Path, *, key: bytes = TEST_KEY, checklist=None):
    """Create the v2, signed-authority fixture required by authoritative readers."""
    files = {
        "checklist": root / "GateChecklist.json",
        "plan": root / "ExecutionPlan.md",
    }
    files["checklist"].write_text(
        __import__("json").dumps(checklist or {}, sort_keys=True), encoding="utf-8"
    )
    files["plan"].write_text("{}", encoding="utf-8")
    legacy = {name: str(path) for name, path in files.items()}
    freeze = LegacyAuthorityFreeze(legacy)
    freeze.__enter__()
    hashes = {
        name: hashlib.sha256(freeze._read_bytes(name)).hexdigest() for name in legacy
    }
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
    attestation = sign_no_writer_attestation(body, signer_id="signer", key=ATTEST_KEY)
    migrator = GenesisMigrator(root, signing_key=key, freeze_verifier=freeze)
    migrator.builder.durability_provider = Durability()
    out = migrator.bootstrap(
        legacy,
        expected_hashes=hashes,
        freeze=freeze.proof(),
        no_writer_attestation=attestation,
        trust_store=NoWriterTrustStore({"signer": ATTEST_KEY}, trust_epoch="e1"),
    )
    return out, migrator, legacy, hashes, freeze
