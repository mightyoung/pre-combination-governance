import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath

import pytest

from rfb.contracts.canonical_json import canonical_bytes
from rfb.research.controller import (
    execute_remote,
    prepare_legacy_r006 as prepare_run,
)
from rfb.research.manifest import _check_manifest_paths
from rfb.research.pinned_runtime import build_pinned_manifest
from rfb.research.runtime_bundle import build_pinned_runtime_bundle
from rfb.research.transport import FakeTransport, OpenSSHTransport, TransportError


def _fixture_runtime(tmp_path: Path):
    root = tmp_path / "approved-runtime"
    source = root / "src" / "rfb"
    source.mkdir(parents=True)
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    interpreter = root / "bin" / "python"
    interpreter.parent.mkdir()
    interpreter.write_bytes(b"fixture-interpreter")
    manifest = build_pinned_manifest(
        root,
        source_root=source,
        interpreter=interpreter,
        fixture_only=True,
    )
    bundle = build_pinned_runtime_bundle(root, manifest, tmp_path / "bundle")
    return root, manifest, bundle


def _created_remote_root(tmp_path: Path, transport: FakeTransport) -> Path:
    parent = tmp_path / "remote-parent"
    parent.mkdir()
    evidence = transport.create_run_root(
        approved_remote_parent=parent, run_id="pinned-local"
    )
    return Path(evidence.remote_run_root)


def test_fake_transport_materializes_pinned_bundle_and_binds_interpreter(tmp_path):
    _, manifest, bundle = _fixture_runtime(tmp_path)
    transport = FakeTransport(lambda _: {})
    remote_root = _created_remote_root(tmp_path, transport)

    interpreter = transport.stage_runtime(bundle=bundle, remote_run_root=remote_root)

    expected_root = remote_root / ".runtime" / f"{bundle.file_sha256}.pinned"
    assert interpreter == expected_root / Path(bundle.interpreter_relative_path)
    assert interpreter.read_bytes() == b"fixture-interpreter"
    assert transport._runtime_binding["runtime_format"] == "python_pinned_venv_v1"
    assert transport._runtime_binding["runtime_dependency_profile"] == (
        "tep_nonconfirmatory_v1"
    )
    assert (
        transport._runtime_binding["pinned_runtime_closure_fingerprint"]
        == (manifest["closure_fingerprint"])
    )


def test_pinned_runtime_command_uses_materialized_interpreter_without_site_disable(
    tmp_path,
):
    _, _, bundle = _fixture_runtime(tmp_path)
    transport = FakeTransport(lambda _: {})
    remote_root = _created_remote_root(tmp_path, transport)
    interpreter = transport.stage_runtime(bundle=bundle, remote_run_root=remote_root)

    command = transport._runtime_command("worker")

    assert command == [
        str(interpreter),
        "-X",
        "utf8",
        "-B",
        "-I",
        "-m",
        "rfb.research",
        "worker",
    ]
    assert "-S" not in command
    assert not any(str(item).endswith(".pyz") for item in command)


def test_pinned_materialization_preserves_interpreter_executable_bit(tmp_path):
    root, manifest, bundle = _fixture_runtime(tmp_path)
    interpreter = root / "bin" / "python"
    interpreter.chmod(0o755)
    # Rebuild after changing the source mode so the archive carries 0755.
    manifest = build_pinned_manifest(
        root,
        source_root=root / "src" / "rfb",
        interpreter=interpreter,
        fixture_only=True,
    )
    bundle = build_pinned_runtime_bundle(root, manifest, tmp_path / "bundle-exec")
    from rfb.research.runtime_bundle import materialize_pinned_runtime_bundle

    destination = tmp_path / "materialized"
    materialize_pinned_runtime_bundle(bundle, destination)
    # Windows does not expose POSIX mode bits after chmod; inspect the
    # transport archive metadata, which is what the Linux materializer uses.
    import zipfile

    with zipfile.ZipFile(bundle.path) as archive:
        info = archive.getinfo("bin/python")
        assert ((info.external_attr >> 16) & 0o111) == 0o111


def test_pinned_materialization_collision_fails_closed(tmp_path):
    _, _, bundle = _fixture_runtime(tmp_path)
    transport = FakeTransport(lambda _: {})
    remote_root = _created_remote_root(tmp_path, transport)
    transport.stage_runtime(bundle=bundle, remote_run_root=remote_root)

    with pytest.raises(TransportError, match="PINNED_RUNTIME_MATERIALIZATION_FAILED"):
        transport.stage_runtime(bundle=bundle, remote_run_root=remote_root)


def test_pinned_bundle_streams_members_and_is_deterministic(tmp_path, monkeypatch):
    root = tmp_path / "large-runtime"
    source = root / "src" / "rfb"
    source.mkdir(parents=True)
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "bin").mkdir()
    (root / "bin" / "python").write_bytes(b"fixture-interpreter")
    (root / "large.bin").write_bytes(b"x" * (4 * 1024 * 1024))
    manifest = build_pinned_manifest(
        root, source_root=source, interpreter=root / "bin" / "python", fixture_only=True
    )

    def no_read_bytes(_path):
        raise AssertionError("bundle construction must stream source files")

    monkeypatch.setattr(Path, "read_bytes", no_read_bytes)
    first = build_pinned_runtime_bundle(root, manifest, tmp_path / "bundle-a")
    second = build_pinned_runtime_bundle(root, manifest, tmp_path / "bundle-b")

    assert first.file_sha256 == second.file_sha256
    assert first.path.stat().st_size > 4 * 1024 * 1024
    with zipfile.ZipFile(first.path) as archive:
        assert archive.namelist() == sorted(archive.namelist())
        assert archive.getinfo("large.bin").file_size == 4 * 1024 * 1024


def test_pinned_bundle_stream_failure_cleans_partial_and_final(tmp_path, monkeypatch):
    root, manifest, _ = _fixture_runtime(tmp_path)
    output = tmp_path / "bundle-failure"

    def fail_open(self, *args, **kwargs):
        raise OSError("injected stream failure")

    monkeypatch.setattr(zipfile.ZipFile, "open", fail_open)
    with pytest.raises(OSError, match="injected stream failure"):
        build_pinned_runtime_bundle(root, manifest, output)

    assert not list(output.glob("*.partial"))
    assert not list(output.glob("*.pinned.tar"))


def test_prepare_injects_controller_owned_pinned_manifest_and_hashes(tmp_path):
    root, manifest, _ = _fixture_runtime(tmp_path)
    pinned_path = tmp_path / "approved-pinned.json"
    pinned_path.write_text(json.dumps(manifest), encoding="utf-8")
    user_path = tmp_path / "user.json"
    user_path.write_text(
        json.dumps(
            {
                "run_id": "pinned-prepare",
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
        user_path,
        approved_pinned_runtime_root=root,
        approved_pinned_runtime_manifest=pinned_path,
    )

    assert prepared.manifest["pinned_runtime_manifest"] == manifest
    assert prepared.manifest["runtime_format"] == "python_pinned_venv_v1"
    assert prepared.manifest["runtime_dependency_profile"] == ("tep_nonconfirmatory_v1")
    assert (
        prepared.manifest["pinned_runtime_closure_fingerprint"]
        == manifest["closure_fingerprint"]
    )


def test_controller_pinned_inventory_is_not_misread_as_user_write_path():
    _check_manifest_paths(
        {
            "pinned_runtime_manifest": {
                "locked_distributions": [
                    {
                        "files": [
                            {"path": "lib/site-packages/rfb/authority/generation.py"}
                        ]
                    }
                ]
            }
        }
    )
    with pytest.raises(ValueError, match="forbidden or non-confined path"):
        _check_manifest_paths({"dataset_root": "/tmp/authority/data"})


def test_prepare_requires_pinned_root_and_manifest_as_one_capability(tmp_path):
    root, _, _ = _fixture_runtime(tmp_path)
    user_path = tmp_path / "user.json"
    user_path.write_text(
        json.dumps(
            {
                "run_id": "pinned-pair",
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

    with pytest.raises(ValueError, match="must be supplied together"):
        prepare_run(user_path, approved_pinned_runtime_root=root)


def test_controller_reaches_pinned_preflight_without_zipapp_downgrade(tmp_path):
    root, manifest, _ = _fixture_runtime(tmp_path)
    pinned_path = tmp_path / "approved-pinned.json"
    pinned_path.write_text(json.dumps(manifest), encoding="utf-8")
    user_path = tmp_path / "user.json"
    user_path.write_text(
        json.dumps(
            {
                "run_id": "pinned-controller",
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
    remote_parent = tmp_path / "remote-parent"
    remote_parent.mkdir()
    prepared = prepare_run(
        user_path,
        approved_remote_parent=remote_parent,
        approved_local_root=tmp_path,
        approved_pinned_runtime_root=root,
        approved_pinned_runtime_manifest=pinned_path,
    )

    class PinnedPreflightObserved(RuntimeError):
        pass

    class ProbeTransport(FakeTransport):
        def preflight(self, **kwargs):
            raise PinnedPreflightObserved

    transport = ProbeTransport(lambda _: {})
    with pytest.raises(PinnedPreflightObserved):
        execute_remote(prepared, transport)

    assert transport._runtime_binding["runtime_format"] == "python_pinned_venv_v1"
    assert transport._runtime_binding["runtime_path"].endswith(
        str(Path("bin") / "python")
    )
    assert not transport._runtime_binding["runtime_path"].endswith(".pyz")


def test_execution_manifest_rebinds_pinned_root_to_materialization(
    tmp_path, monkeypatch
):
    root, manifest, _ = _fixture_runtime(tmp_path)
    pinned_path = tmp_path / "approved-pinned.json"
    pinned_path.write_text(json.dumps(manifest), encoding="utf-8")
    user_path = tmp_path / "user.json"
    user_path.write_text(
        json.dumps(
            {
                "run_id": "pinned-rebind",
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
    remote_parent = tmp_path / "remote-parent"
    remote_parent.mkdir()
    prepared = prepare_run(
        user_path,
        approved_remote_parent=remote_parent,
        approved_local_root=tmp_path,
        approved_pinned_runtime_root=root,
        approved_pinned_runtime_manifest=pinned_path,
    )

    class ExecutionManifestObserved(RuntimeError):
        pass

    observed = {"rebound": False}

    class ObserveStage(FakeTransport):
        def preflight(
            self,
            *,
            root,
            manifest_sha256,
            controller_nonce,
            formal_snapshot_sha256,
            **kwargs,
        ):
            return {
                "root": str(root),
                "prepared_manifest_sha256": manifest_sha256,
                "controller_nonce": controller_nonce,
                "formal_snapshot_sha256": formal_snapshot_sha256,
                "gpu_policy": "cpu_only",
                "approved_remote_parent": str(Path(root).parent),
                "remote_run_root": str(root),
                "capacity_available": True,
                "remote_reserve_available": True,
                "fingerprint_verified": True,
                **self._runtime_binding,
            }

        def stage(self, *, manifest, remote_root):
            payload = json.loads(Path(manifest).read_text(encoding="utf-8"))
            expected = Path(self._runtime_binding["runtime_path"]).parents[1]
            assert Path(payload["pinned_runtime_root"]) == expected
            observed["rebound"] = True
            raise ExecutionManifestObserved

    monkeypatch.setattr(
        "rfb.research.controller.validate_manifest", lambda value, **kwargs: value
    )
    with pytest.raises(RuntimeError, match="EXECUTION_FAILED"):
        execute_remote(prepared, ObserveStage(lambda _: {}))
    assert observed["rebound"] is True


def test_pinned_preflight_reports_controller_root_bindings(tmp_path):
    from rfb.research.preflight import collect_preflight

    remote_parent = tmp_path / "remote-parent"
    run_root = remote_parent / "pinned-root-binding"
    run_root.mkdir(parents=True)

    evidence = collect_preflight(run_root, fixture_only=True)

    assert evidence["root"] == str(run_root.resolve())
    assert evidence["approved_remote_parent"] == str(remote_parent.resolve())
    assert evidence["remote_run_root"] == str(run_root.resolve())
    assert evidence["filesystem_baseline_bytes"] == evidence["filesystem_used_bytes"]
    assert evidence["capacity_measurement_status"] == "UNAVAILABLE"
    assert evidence["capacity_peak_bytes"] is None
    assert evidence["capacity_available"] is False
    assert set(evidence["capacity_unavailable_fields"]) >= {
        "filesystem_used_delta_bytes",
        "owned_external_layers_bytes",
    }


def test_preflight_capacity_is_measured_only_with_explicit_inputs(tmp_path):
    from rfb.capacity_probe import filesystem_used_bytes
    from rfb.research.preflight import collect_preflight

    run_root = tmp_path / "measured-preflight"
    run_root.mkdir()
    baseline = filesystem_used_bytes(run_root)

    evidence = collect_preflight(
        run_root,
        fixture_only=True,
        filesystem_baseline_bytes=baseline,
        owned_external_layers_bytes=0,
        trusted_open_deleted_bytes=0,
    )

    assert evidence["capacity_measurement_status"] == "MEASURED"
    assert evidence["capacity_unavailable_fields"] == []
    assert evidence["filesystem_used_delta_bytes"] == 0
    assert evidence["owned_external_layers_bytes"] == 0
    assert evidence["open_deleted_bytes"] == 0
    assert evidence["capacity_peak_bytes"] >= evidence["project_tree_allocated_bytes"]


def test_openssh_stage_materializes_pinned_runtime_without_preinstalled_rfb(
    tmp_path, monkeypatch
):
    _, manifest, bundle = _fixture_runtime(tmp_path)
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("fixture", encoding="utf-8")
    transport = OpenSSHTransport("host", known_hosts)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("rfb.research.transport.subprocess.run", fake_run)
    materialized = PurePosixPath(
        "/remote/run/.runtime/" + bundle.file_sha256 + ".pinned"
    )
    order = []

    def fake_script(script, argv):
        order.append("materialize")
        return {
            "returncode": 0,
            "stdout": str(materialized / bundle.interpreter_relative_path),
            "stderr": "",
        }

    monkeypatch.setattr(transport, "_run_script", fake_script)
    verifier_calls = []
    verifier_hash = hashlib.sha256(canonical_bytes(manifest)).hexdigest()

    def verify(**kwargs):
        order.append("verify")
        verifier_calls.append(kwargs)
        return {"manifest": manifest, "manifest_sha256": verifier_hash}

    monkeypatch.setattr(transport, "_run_pinned_verify", verify)
    result = transport.stage_runtime(bundle=bundle, remote_run_root="/remote/run")
    assert result == materialized / bundle.interpreter_relative_path
    assert transport._runtime_binding["runtime_format"] == "python_pinned_venv_v1"
    assert len(verifier_calls) == 1
    assert order == ["materialize", "materialize", "verify"]
    assert transport._runtime_binding["pinned_runtime_manifest_sha256"] == verifier_hash
    assert len([call for call in calls if call[0] == "scp"]) == 2


def test_openssh_pinned_verifier_failure_precedes_runtime_binding(
    tmp_path, monkeypatch
):
    _, _manifest, bundle = _fixture_runtime(tmp_path)
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("fixture", encoding="utf-8")
    transport = OpenSSHTransport("host", known_hosts)
    monkeypatch.setattr(
        "rfb.research.transport.subprocess.run",
        lambda *args, **kwargs: type(
            "P", (), {"returncode": 0, "stdout": "", "stderr": ""}
        )(),
    )
    materialized = PurePosixPath(
        "/remote/run/.runtime/" + bundle.file_sha256 + ".pinned"
    )
    monkeypatch.setattr(
        transport,
        "_run_script",
        lambda script, argv: {
            "returncode": 0,
            "stdout": str(materialized / bundle.interpreter_relative_path),
            "stderr": "",
        },
    )

    def fail_verify(**kwargs):
        raise TransportError("PINNED_RUNTIME_VERIFY_FAILED")

    monkeypatch.setattr(transport, "_run_pinned_verify", fail_verify)
    with pytest.raises(TransportError, match="PINNED_RUNTIME_VERIFY_FAILED"):
        transport.stage_runtime(bundle=bundle, remote_run_root="/remote/run")
    assert not hasattr(transport, "_runtime_binding")


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [
        (1, "", "PINNED_RUNTIME_VERIFY_FAILED"),
        (0, "not-json", "PINNED_RUNTIME_VERIFY_FAILED"),
    ],
)
def test_openssh_pinned_verifier_process_failures_are_fail_closed(
    tmp_path, monkeypatch, returncode, stdout, expected
):
    _, manifest, _ = _fixture_runtime(tmp_path)
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("fixture", encoding="utf-8")
    transport = OpenSSHTransport("host", known_hosts)
    monkeypatch.setattr(
        "rfb.research.transport.subprocess.run",
        lambda *args, **kwargs: type(
            "P", (), {"returncode": returncode, "stdout": stdout, "stderr": ""}
        )(),
    )
    with pytest.raises(TransportError, match=expected):
        transport._run_pinned_verify(
            interpreter=PurePosixPath("/remote/bin/python"),
            root=PurePosixPath("/remote/root"),
            manifest=manifest,
        )
    assert not hasattr(transport, "_runtime_binding")


def test_openssh_pinned_verifier_hash_mismatch_is_fail_closed(tmp_path, monkeypatch):
    _, manifest, _ = _fixture_runtime(tmp_path)
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("fixture", encoding="utf-8")
    transport = OpenSSHTransport("host", known_hosts)
    monkeypatch.setattr(
        "rfb.research.transport.subprocess.run",
        lambda *args, **kwargs: type(
            "P",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    {"manifest": manifest, "manifest_sha256": "0" * 64}
                ),
                "stderr": "",
            },
        )(),
    )
    with pytest.raises(TransportError, match="PINNED_RUNTIME_VERIFY_BINDING_MISMATCH"):
        transport._run_pinned_verify(
            interpreter=PurePosixPath("/remote/bin/python"),
            root=PurePosixPath("/remote/root"),
            manifest=manifest,
        )
    assert not hasattr(transport, "_runtime_binding")


def test_openssh_pinned_verifier_replaced_manifest_with_input_hash_is_rejected(
    tmp_path, monkeypatch
):
    _, manifest, _ = _fixture_runtime(tmp_path)
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("fixture", encoding="utf-8")
    transport = OpenSSHTransport("host", known_hosts)
    replaced = {**manifest, "closure_fingerprint": "sha256:" + "0" * 64}
    input_hash = hashlib.sha256(canonical_bytes(manifest)).hexdigest()
    monkeypatch.setattr(
        "rfb.research.transport.subprocess.run",
        lambda *args, **kwargs: type(
            "P",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    {"manifest": replaced, "manifest_sha256": input_hash}
                ),
                "stderr": "",
            },
        )(),
    )
    with pytest.raises(TransportError, match="PINNED_RUNTIME_VERIFY_BINDING_MISMATCH"):
        transport._run_pinned_verify(
            interpreter=PurePosixPath("/remote/bin/python"),
            root=PurePosixPath("/remote/root"),
            manifest=manifest,
        )
    assert not hasattr(transport, "_runtime_binding")


def test_openssh_pinned_verifier_closure_mismatch_precedes_binding(
    tmp_path, monkeypatch
):
    _, manifest, bundle = _fixture_runtime(tmp_path)
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("fixture", encoding="utf-8")
    transport = OpenSSHTransport("host", known_hosts)
    monkeypatch.setattr(
        "rfb.research.transport.subprocess.run",
        lambda *args, **kwargs: type(
            "P", (), {"returncode": 0, "stdout": "", "stderr": ""}
        )(),
    )
    materialized = PurePosixPath(
        "/remote/run/.runtime/" + bundle.file_sha256 + ".pinned"
    )
    monkeypatch.setattr(
        transport,
        "_run_script",
        lambda script, argv: {
            "returncode": 0,
            "stdout": str(materialized / bundle.interpreter_relative_path),
            "stderr": "",
        },
    )
    bad_manifest = {**manifest, "closure_fingerprint": "sha256:" + "0" * 64}
    verifier_hash = hashlib.sha256(canonical_bytes(bad_manifest)).hexdigest()
    monkeypatch.setattr(
        transport,
        "_run_pinned_verify",
        lambda **kwargs: {
            "manifest": bad_manifest,
            "manifest_sha256": verifier_hash,
        },
    )
    with pytest.raises(TransportError, match="PINNED_RUNTIME_VERIFY_BINDING_MISMATCH"):
        transport.stage_runtime(bundle=bundle, remote_run_root="/remote/run")
    assert not hasattr(transport, "_runtime_binding")
