import json

import pytest

from rfb.research.controller import (
    _load_remote_receipt,
    execute_remote,
    prepare_legacy_r006 as prepare_run,
)
from rfb.research.transport import FakeTransport


def test_remote_receipt_loader_requires_stdout_to_match_durable_file(
    tmp_path,
):
    receipt_path = tmp_path / "run.REMOTE_EXECUTION_RECEIPT.json"
    published = {"terminal_state": "RESULT_SEALED_REMOTE", "source": "file"}
    receipt_path.write_text(json.dumps(published))

    stdout_receipt = {"terminal_state": "RESULT_SEALED_REMOTE", "source": "stdout"}
    with pytest.raises(ValueError, match="REMOTE_RECEIPT_STDOUT_MISMATCH"):
        _load_remote_receipt({"stdout": json.dumps(stdout_receipt)}, receipt_path)
    assert (
        _load_remote_receipt({"stdout": json.dumps(published)}, receipt_path)
        == published
    )
    assert _load_remote_receipt({"stdout": "{not-json"}, receipt_path) == published
    assert _load_remote_receipt({"stdout": ""}, receipt_path) == published


def test_prepare_accepts_closed_adapter_and_writes_prepared(tmp_path):
    m = {
        "run_id": "r1",
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
        "adapter_id": "tep_fixture",
    }
    src = tmp_path / "m.json"
    src.write_text(json.dumps(m))
    out = tmp_path / "prepared.json"
    p = prepare_run(src, out)
    assert (
        p.manifest_sha256 and json.loads(out.read_text())["adapter_id"] == "tep_fixture"
    )


def test_prepare_injects_controller_owned_expected_fingerprint(tmp_path):
    source = tmp_path / "fingerprint.json"
    source.write_text(
        json.dumps(
            {
                "run_id": "fingerprint",
                "execution_lane": "RESEARCH",
                "classification": "DEVELOPMENT_NONCONFIRMATORY",
                "formal_gate_effect": "NONE",
                "formal_admission_eligible": False,
                "shk001b_eligible": False,
                "contains_formal_claims": False,
                "adapter_id": "tep_fixture",
            }
        ),
        encoding="utf-8",
    )
    expected = "SHA256:" + "A" * 43
    prepared = prepare_run(source, approved_expected_fingerprint=expected)
    assert prepared.manifest["expected_fingerprint"] == expected


def test_prepare_rejects_user_authored_expected_fingerprint(tmp_path):
    source = tmp_path / "user-fingerprint.json"
    source.write_text(
        json.dumps(
            {
                "run_id": "fingerprint",
                "execution_lane": "RESEARCH",
                "classification": "DEVELOPMENT_NONCONFIRMATORY",
                "formal_gate_effect": "NONE",
                "formal_admission_eligible": False,
                "shk001b_eligible": False,
                "contains_formal_claims": False,
                "adapter_id": "tep_fixture",
                "expected_fingerprint": "SHA256:" + "A" * 43,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="CONTROLLER_CAPABILITY_FIELD_FORBIDDEN"):
        prepare_run(source)


def test_prepare_preserves_confined_linux_remote_capabilities_on_windows(tmp_path):
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("host ssh-ed25519 AAAAfixture", encoding="utf-8")
    manifest = {
        "run_id": "linux-paths",
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
        "adapter_id": "tep_fixture",
        "dataset_root": "/home/r4900g3/yhh/datasets/TEP",
        "known_hosts": str(known_hosts.resolve()),
    }
    source = tmp_path / "linux-manifest.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")

    prepared = prepare_run(
        source,
        approved_remote_parent="/share/data4/yhh-rfb",
        approved_dataset_root="/home/r4900g3/yhh/datasets",
    )

    assert prepared.manifest["approved_remote_parent"] == "/share/data4/yhh-rfb"
    assert prepared.manifest["remote_run_root"] == "/share/data4/yhh-rfb/linux-paths"
    assert prepared.manifest["dataset_root"] == "/home/r4900g3/yhh/datasets/TEP"


@pytest.mark.parametrize("foreign", ["C:/outside", "C:\\outside", "\\\\server\\share"])
def test_prepare_rejects_windows_absolute_capability_under_posix_root(
    tmp_path, foreign
):
    source = tmp_path / "foreign.json"
    source.write_text(
        json.dumps(
            {
                "run_id": "foreign-capability",
                "execution_lane": "RESEARCH",
                "classification": "DEVELOPMENT_NONCONFIRMATORY",
                "formal_gate_effect": "NONE",
                "formal_admission_eligible": False,
                "shk001b_eligible": False,
                "contains_formal_claims": False,
                "adapter_id": "tep_fixture",
                "remote_run_root": foreign,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="CONTROLLER_CAPABILITY_FIELD_FORBIDDEN"):
        prepare_run(source, approved_remote_parent="/share/data4/yhh-rfb")


def test_execute_rejects_formal_snapshot_drift_before_preflight(tmp_path, monkeypatch):
    remote_root = tmp_path / "remote"
    remote_root.mkdir()
    source = tmp_path / "manifest.json"
    source.write_text(
        json.dumps(
            {
                "run_id": "formal-drift",
                "execution_lane": "RESEARCH",
                "classification": "DEVELOPMENT_NONCONFIRMATORY",
                "formal_gate_effect": "NONE",
                "formal_admission_eligible": False,
                "shk001b_eligible": False,
                "contains_formal_claims": False,
                "adapter_id": "tep_fixture",
            }
        ),
        encoding="utf-8",
    )
    prepared = prepare_run(
        source,
        approved_remote_parent=tmp_path,
        approved_local_root=tmp_path,
    )
    monkeypatch.setattr(
        "rfb.research.controller._formal_snapshot",
        lambda: {"GateChecklist-v6.13.json:sha256": "changed"},
    )
    transport = FakeTransport(lambda _: {})
    with pytest.raises(RuntimeError, match="FORMAL_SNAPSHOT_DRIFT"):
        execute_remote(prepared, transport)
    assert transport.lifecycle == []
