from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import os

import pytest
from rfb.research.files import publish_bytes, publish_json_new
from rfb.research.receipts import scan_closed_result
from rfb.research.worker import durable_tree_sync


def test_publish_is_atomic_and_no_partial_exposed(tmp_path):
    dest = tmp_path / "result.bin"
    digest = publish_bytes(dest, b"payload")
    assert dest.read_bytes() == b"payload" and len(digest) == 64
    assert not list(tmp_path.glob("*.partial"))


def test_closed_result_rejects_undecodable_binary(tmp_path):
    (tmp_path / "result.bin").write_bytes(b"\x00truth\xff")
    with pytest.raises(ValueError, match="binary|undecodable"):
        scan_closed_result(tmp_path)


def test_create_only_json_publication_has_one_concurrent_winner(tmp_path):
    destination = tmp_path / "receipt.json"

    def publish(value):
        try:
            publish_json_new(destination, {"writer": value})
            return "published"
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(publish, (1, 2)))

    assert outcomes.count("published") == 1
    assert outcomes.count("IMMUTABLE_RECEIPT_EXISTS") == 1
    assert destination.read_text(encoding="utf-8") in {
        '{"writer":1}',
        '{"writer":2}',
    }
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.skipif(os.name == "nt", reason="Windows file fsync is unavailable")
def test_durable_tree_sync_fsyncs_regular_tree(tmp_path):
    root = tmp_path / "tree"
    (root / "nested").mkdir(parents=True)
    (root / "a.bin").write_bytes(b"a")
    (root / "nested" / "b.bin").write_bytes(b"b")
    durable_tree_sync(root)


def test_durable_tree_sync_fails_closed_on_file_fsync_error(tmp_path, monkeypatch):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "result.json").write_text("{}", encoding="utf-8")

    def fail(_fd):
        raise OSError("injected file fsync failure")

    monkeypatch.setattr("rfb.research.worker._fsync_regular_file", fail)
    with pytest.raises(RuntimeError, match="TREE_DURABILITY_UNPROVEN"):
        durable_tree_sync(root)


@pytest.mark.skipif(os.name == "nt", reason="Windows file fsync is unavailable")
def test_durable_tree_sync_fails_closed_on_directory_fsync_error(tmp_path, monkeypatch):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "result.json").write_text("{}", encoding="utf-8")

    def fail(_path):
        raise RuntimeError("injected directory fsync failure")

    monkeypatch.setattr("rfb.research.worker._fsync_dir", fail)
    with pytest.raises(RuntimeError, match="TREE_DURABILITY_UNPROVEN"):
        durable_tree_sync(root)
