import json
import sys
from pathlib import Path

import pytest

from rfb.research.runtime_bundle import build_runtime_bundle
from rfb.research.transport import (
    FakeTransport,
    OpenSSHTransport,
    RunRootCreationEvidence,
    TransportError,
)


def test_openssh_argv_is_strict_and_not_shell(tmp_path):
    kh = tmp_path / "known_hosts"
    kh.write_text("fixture")
    t = OpenSSHTransport("user@host", kh)
    cmd = t.command(["python3", "-I", "-S", "/remote/runtime.pyz", "worker"])
    assert "-m" not in cmd and "rfb.research" not in cmd
    assert "StrictHostKeyChecking=yes" in cmd and "-o" in cmd
    assert "UserKnownHostsFile=" + str(kh) in cmd
    assert cmd[cmd.index("-p") + 1] == "22"
    assert "BatchMode=yes" in cmd
    assert "NumberOfPasswordPrompts=1" not in cmd


def test_password_askpass_auth_is_explicit_and_applies_to_scp(tmp_path, monkeypatch):
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("fixture", encoding="utf-8")
    transport = OpenSSHTransport("user@host", known_hosts, auth_mode="password_askpass")
    ssh = transport.command(["python3", "--version"])
    assert "BatchMode=no" in ssh
    assert "NumberOfPasswordPrompts=1" in ssh
    assert "SSH_ASKPASS" not in ssh and not any(
        "password=" in item.casefold() for item in ssh
    )
    calls = []
    monkeypatch.setattr(
        "rfb.research.transport.subprocess.run",
        lambda argv, **kwargs: (
            calls.append(argv)
            or type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        ),
    )
    bundle = build_runtime_bundle("tep_fixture", tmp_path / "cache")
    transport.stage_runtime(bundle=bundle, remote_root="/remote/run")
    scp_calls = [call for call in calls if call[0] == "scp"]
    assert len(scp_calls) == 2
    for call in scp_calls:
        assert "BatchMode=no" in call
        assert "NumberOfPasswordPrompts=1" in call
        assert "SSH_ASKPASS" not in call and not any(
            "password=" in item.casefold() for item in call
        )


def test_unknown_auth_mode_rejected(tmp_path):
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("fixture", encoding="utf-8")
    with pytest.raises(ValueError, match="auth_mode"):
        OpenSSHTransport("user@host", known_hosts, auth_mode="password")


def test_openssh_port_10022_is_used_for_ssh_and_scp(tmp_path, monkeypatch):
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("fixture", encoding="utf-8")
    transport = OpenSSHTransport("user@host", known_hosts, port=10022)
    command = transport.command(["python3", "--version"])
    assert command[command.index("-p") + 1] == "10022"
    calls = []
    monkeypatch.setattr(
        "rfb.research.transport.subprocess.run",
        lambda argv, **kwargs: (
            calls.append(argv)
            or type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        ),
    )
    bundle = build_runtime_bundle("tep_fixture", tmp_path / "cache")
    transport.stage_runtime(bundle=bundle, remote_root="/remote/run")
    scp_calls = [call for call in calls if call[0] == "scp"]
    assert len(scp_calls) == 2
    assert all(call[call.index("-P") + 1] == "10022" for call in scp_calls)


def test_fake_transport_records_pinned_zipapp_argv(tmp_path):
    t = FakeTransport(lambda p: {"terminal_state": "RESULT_SEALED_REMOTE"})
    bundle = build_runtime_bundle("tep_fixture", tmp_path / "cache")
    t.bootstrap_parent_preflight(approved_remote_parent=tmp_path)
    created = t.create_run_root(approved_remote_parent=tmp_path, run_id="run")
    runtime = t.stage_runtime(bundle=bundle, remote_run_root=created.remote_run_root)
    out = t.run([sys.executable, "-I", "-S", str(runtime), "--help"])
    assert t.calls and out["returncode"] == 0


def test_fake_transport_inner_worker_is_explicitly_cpu_only(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "rfb.research.transport.subprocess.run",
        lambda argv, **kwargs: (
            captured.update(kwargs)
            or type("P", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()
        ),
    )
    t = FakeTransport(lambda _: {})
    t._runtime_binding = {
        "runtime_format": "python_zipapp_stdlib_v1",
        "runtime_path": str(tmp_path / "runtime.pyz"),
    }
    t._invoke_runtime(["python3", "--version"])
    assert captured["env"]["CUDA_VISIBLE_DEVICES"] == "-1"


def test_fake_bootstrap_probes_parent_then_creates_absent_confined_run_root(tmp_path):
    transport = FakeTransport(lambda _: {})
    evidence = transport.bootstrap_parent_preflight(approved_remote_parent=tmp_path)
    assert evidence["approved_remote_parent"] == str(tmp_path)
    assert not (tmp_path / "absent").exists()
    created = transport.create_run_root(
        approved_remote_parent=tmp_path, run_id="absent"
    )
    assert created.remote_run_root == str(tmp_path / "absent")

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(TransportError, match="RUN_ROOT_COLLISION"):
        transport.create_run_root(approved_remote_parent=tmp_path, run_id="existing")

    escaped = tmp_path / "child" / ".." / "escaped"
    with pytest.raises(TransportError, match="RUN_ROOT_PARENT_INVALID"):
        transport.bootstrap_parent_preflight(approved_remote_parent=escaped)


def test_fake_bootstrap_rejects_symlink_root_and_parent(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    root_link = tmp_path / "root-link"
    parent_link = tmp_path / "parent-link"
    try:
        root_link.symlink_to(target, target_is_directory=True)
        parent_link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    transport = FakeTransport(lambda _: {})
    with pytest.raises(TransportError, match="BOOTSTRAP_PREFLIGHT_BLOCKED"):
        transport.bootstrap_parent_preflight(approved_remote_parent=root_link)
    with pytest.raises(TransportError, match="BOOTSTRAP_PREFLIGHT_BLOCKED"):
        transport.bootstrap_parent_preflight(approved_remote_parent=parent_link)


def test_remote_preflight_uses_linux_python3(tmp_path, monkeypatch):
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("host ssh-ed25519 AAAAfixture", encoding="utf-8")
    transport = OpenSSHTransport("host", known_hosts, "SHA256:fixture", port=10022)
    bundle = build_runtime_bundle("tep_fixture", tmp_path / "cache")
    transport._runtime_binding = {
        "runtime_format": bundle.format,
        "runtime_path": f"/remote/.runtime/{bundle.remote_name}",
        "runtime_file_sha256": bundle.file_sha256,
        "runtime_source_sha256": bundle.source_sha256,
        "runtime_manifest_sha256": bundle.manifest_sha256,
        "runtime_dependency_profile": "stdlib_only",
    }
    transport._capacity_filesystem_baseline_bytes = 123
    transport._capacity_owned_external_layers_bytes = 0
    remote_calls = []

    def fake_remote_run(argv):
        remote_calls.append(argv)
        return {
            "returncode": 0,
            "stdout": json.dumps({"capacity_available": True}),
        }

    monkeypatch.setattr(
        transport,
        "run",
        fake_remote_run,
    )
    transport.preflight(
        root=tmp_path,
        manifest_sha256="a" * 64,
        controller_nonce="b" * 32,
        formal_snapshot_sha256="c" * 64,
    )
    assert remote_calls[0][:4] == [
        "python3",
        "-I",
        "-S",
        transport._runtime_binding["runtime_path"],
    ]
    assert "--manifest-sha256" in remote_calls[0]
    assert "--filesystem-baseline-bytes" in remote_calls[0]
    assert "--owned-external-layers-bytes" in remote_calls[0]
    assert "-m" not in remote_calls[0]


def test_bootstrap_preflight_uses_fixed_stdin_script_without_rfb(tmp_path, monkeypatch):
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("host ssh-ed25519 AAAAfixture", encoding="utf-8")
    transport = OpenSSHTransport("host", known_hosts, "SHA256:fixture", port=10022)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[:2] == ["ssh-keygen", "-F"]:
            return type("P", (), {"returncode": 0, "stdout": known_hosts.read_text()})()
        if argv[:3] == ["ssh-keygen", "-lf", "-"]:
            return type(
                "P", (), {"returncode": 0, "stdout": "256 SHA256:fixture host"}
            )()
        return type(
            "P",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    {
                        "root": "/remote/run",
                        "runtime_root": "/remote/run/.runtime",
                        "capacity_available": True,
                    }
                ),
                "stderr": "",
            },
        )()

    monkeypatch.setattr("rfb.research.transport.subprocess.run", fake_run)
    evidence = transport.bootstrap_preflight(root="/remote/run")
    assert calls[0][0][2] == "[host]:10022"
    ssh_argv, ssh_kwargs = calls[-1]
    assert ssh_argv[-5:-1] == ["python3", "-I", "-S", "-"]
    assert "rfb" not in ssh_kwargs["input"]
    assert evidence["fingerprint_verified"] is True


def test_ssh_rejects_metacharacters_and_option_hosts(tmp_path):
    kh = tmp_path / "known_hosts"
    kh.write_text("fixture")
    with pytest.raises(ValueError):
        OpenSSHTransport("host;rm", kh).command(["python"])
    with pytest.raises(ValueError):
        OpenSSHTransport("host", kh).command(["python", "x;echo"])


def test_ssh_fingerprint_mismatch_fails_closed(tmp_path):
    kh = tmp_path / "known_hosts"
    kh.write_text("fixture")
    t = OpenSSHTransport("host", kh, fingerprint="SHA256:expected")
    with pytest.raises(Exception, match="fingerprint"):
        t.validate_fingerprint("SHA256:other")


def test_fixed_parent_creation_is_atomic_and_returns_identity_evidence(tmp_path):
    transport = FakeTransport(lambda _: {})
    parent = tmp_path / "runs"
    parent.mkdir()
    preflight = transport.bootstrap_parent_preflight(approved_remote_parent=parent)
    assert preflight["approved_remote_parent"] == str(parent)
    assert preflight["parent_inode"] == parent.stat().st_ino
    evidence = transport.create_run_root(
        approved_remote_parent=parent, run_id="run-001"
    )
    assert isinstance(evidence, RunRootCreationEvidence)
    assert Path(evidence.remote_run_root).is_dir()
    assert (Path(evidence.remote_run_root) / ".runtime").is_dir()
    assert evidence.run_root_inode == Path(evidence.remote_run_root).stat().st_ino
    with pytest.raises(TransportError, match="RUN_ROOT_COLLISION"):
        transport.create_run_root(approved_remote_parent=parent, run_id="run-001")


def test_fixed_parent_rejects_escape_and_symlink(tmp_path):
    transport = FakeTransport(lambda _: {})
    with pytest.raises(TransportError, match="RUN_ROOT_PARENT_INVALID"):
        transport.bootstrap_parent_preflight(
            approved_remote_parent=tmp_path / "missing" / ".." / "escape"
        )
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    with pytest.raises(TransportError, match="BOOTSTRAP_PREFLIGHT_BLOCKED"):
        transport.bootstrap_parent_preflight(approved_remote_parent=link)


def test_fixed_parent_creation_fsync_failure_fails_closed(tmp_path, monkeypatch):
    transport = FakeTransport(lambda _: {})
    parent = tmp_path / "runs"
    parent.mkdir()
    monkeypatch.setattr(
        "rfb.research.transport._fsync_dir",
        lambda _: (_ for _ in ()).throw(OSError("fsync failed")),
    )
    with pytest.raises(TransportError, match="RUN_ROOT_DURABILITY_FAILED"):
        transport.create_run_root(approved_remote_parent=parent, run_id="run-001")
