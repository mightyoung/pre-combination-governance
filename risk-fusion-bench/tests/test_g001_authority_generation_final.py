import json
from pathlib import Path

import pytest
from rfb.authority import (
    AuthorityGenerationBuilder,
    GenerationReader,
    ReaderBlocked,
    canonical_hash,
)


class Durability:
    def fsync_file(self, path):
        return None

    def fsync_dir(self, path):
        return None


def make(tmp_path):
    b = AuthorityGenerationBuilder(
        tmp_path, signing_key=b"explicit-test-key", durability_provider=Durability()
    )
    out = b.build(
        {"checklist.json": {"rules": [1]}, "nested/policy.json": {"p": True}},
        checklist_hash=canonical_hash({"rules": [1]}),
    )
    binding = {
        "operation_id": out["generation_id"],
        "generation_id": out["generation_id"],
        "receipt_hash": canonical_hash(out["receipt"]),
        "manifest_hash": out["manifest"]["manifest_sha256"],
        "business_state_delta": 0,
    }
    b.append_audit("GENESIS_PREPARED", **binding)
    b.append_audit("GENESIS_COMMITTED", **binding)
    assert b.create_current_absent(out["generation_id"])
    return b, out


def test_generation_closed_and_readable(tmp_path):
    _, out = make(tmp_path)
    got = GenerationReader(
        tmp_path, signing_key=b"explicit-test-key", authoritative=False
    ).read()
    assert got["generation_id"] == out["generation_id"]
    assert set(got["receipt"]["files"]) == {
        "checklist.json",
        "nested/policy.json",
        "manifest.json",
    }


def test_path_escape_rejected(tmp_path):
    b = AuthorityGenerationBuilder(
        tmp_path, signing_key=b"k", durability_provider=Durability()
    )
    with pytest.raises(ValueError):
        b.build({"../escape.json": {}})
    with pytest.raises(ValueError):
        b.build({"C:/escape.json": {}})


def test_audit_tamper_and_receipt_mismatch_blocked(tmp_path):
    make(tmp_path)
    ap = tmp_path / "authority_audit.jsonl"
    row = json.loads(ap.read_text().splitlines()[-1])
    row["binding"]["receipt_hash"] = "0" * 64
    ap.write_text(json.dumps(row) + "\n")
    with pytest.raises(ReaderBlocked):
        GenerationReader(
            tmp_path, signing_key=b"explicit-test-key", authoritative=False
        ).read()


def test_receipt_signature_tamper_blocked(tmp_path):
    _, out = make(tmp_path)
    rp = Path(out["directory"]) / "receipt.json"
    obj = json.loads(rp.read_text())
    obj["checklist_hash"] = "f" * 64
    rp.chmod(0o644)
    rp.write_text(json.dumps(obj))
    with pytest.raises(ReaderBlocked):
        GenerationReader(
            tmp_path, signing_key=b"explicit-test-key", authoritative=False
        ).read()


def test_schema_runtime_validation(tmp_path):
    b = AuthorityGenerationBuilder(
        tmp_path, signing_key=b"k", durability_provider=Durability()
    )
    with pytest.raises(ValueError):
        b.build({"checklist.json": {}}, checklist_hash="bad")
