from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from rfb.research.preflight import _dataset_manifest_evidence


def _make_tep(root: Path) -> tuple[Path, Path]:
    root.mkdir(exist_ok=True)
    archive = root / "tep-profbraatz-master.zip"
    archive.write_bytes(b"archive")
    payload = root / "d01_te.dat"
    payload.write_bytes(b"payload")
    archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    payload_sha = hashlib.sha256(payload.read_bytes()).hexdigest()
    source = root / "SOURCE-MANIFEST.txt"
    source.write_text(f"archive_sha256: {archive_sha}\n", encoding="utf-8")
    checksums = root / "profbraatz-data-sha256.txt"
    checksums.write_text(f"{payload_sha}  {payload.name}\n", encoding="utf-8")
    return source, checksums


def test_tep_pair_verifies_archive_and_extracted_hashes(tmp_path: Path) -> None:
    _source, checksums = _make_tep(tmp_path)
    digest, verified, status, reason = _dataset_manifest_evidence(
        tmp_path, fixture_only=False
    )
    assert len(digest) == 64
    assert (verified, status, reason) == (True, "OBSERVED", None)
    # Reordering and line-ending changes do not alter the canonical evidence.
    checksums.write_text(
        checksums.read_text(encoding="utf-8").replace("\n", "\r\n"),
        encoding="utf-8",
    )
    assert _dataset_manifest_evidence(tmp_path, fixture_only=False)[0] == digest


def test_tep_nested_data_root_uses_bounded_authority_ancestor(tmp_path: Path) -> None:
    data = tmp_path / "profbraatz-master" / "data"
    data.mkdir(parents=True)
    archive = tmp_path / "tep-profbraatz-master.zip"
    archive.write_bytes(b"archive")
    payload = data / "d01_te.dat"
    payload.write_bytes(b"payload")
    (tmp_path / "SOURCE-MANIFEST.txt").write_text(
        f"archive_sha256: {hashlib.sha256(archive.read_bytes()).hexdigest()}\n",
        encoding="utf-8",
    )
    (tmp_path / "profbraatz-data-sha256.txt").write_text(
        f"{hashlib.sha256(payload.read_bytes()).hexdigest()}  "
        "profbraatz-master/data/d01_te.dat\n",
        encoding="utf-8",
    )
    _, verified, status, reason = _dataset_manifest_evidence(data, fixture_only=False)
    assert (verified, status, reason) == (True, "OBSERVED", None)


def test_non_data_root_does_not_search_unbounded_ancestors(tmp_path: Path) -> None:
    _make_tep(tmp_path)
    nested = tmp_path / "unrelated" / "leaf"
    nested.mkdir(parents=True)
    _, verified, status, reason = _dataset_manifest_evidence(nested, fixture_only=False)
    assert (verified, status, reason) == (False, "OBSERVED", None)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("tamper", "TEP_CHECKSUM_FILE_SHA256_MISMATCH"),
        ("escape", "TEP_CHECKSUM_PATH_INVALID"),
        ("duplicate", "TEP_CHECKSUM_DUPLICATE"),
        ("missing", "TEP_CHECKSUM_FILE_MISSING"),
    ],
)
def test_tep_manifest_fail_closed(tmp_path: Path, mutation: str, reason: str) -> None:
    _make_tep(tmp_path)
    checksums = tmp_path / "profbraatz-data-sha256.txt"
    payload_sha = hashlib.sha256(b"payload").hexdigest()
    if mutation == "tamper":
        (tmp_path / "d01_te.dat").write_bytes(b"tampered")
    elif mutation == "escape":
        checksums.write_text(f"{payload_sha}  ../outside.dat\n", encoding="utf-8")
    elif mutation == "duplicate":
        checksums.write_text(
            f"{payload_sha}  d01_te.dat\n{payload_sha}  ./d01_te.dat\n",
            encoding="utf-8",
        )
    else:
        checksums.write_text(f"{payload_sha}  missing.dat\n", encoding="utf-8")
    _, verified, status, detail = _dataset_manifest_evidence(
        tmp_path, fixture_only=False
    )
    assert not verified
    assert status == "ERROR"
    assert detail and detail.startswith(reason)
