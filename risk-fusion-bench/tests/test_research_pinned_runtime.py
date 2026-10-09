from pathlib import Path
from types import SimpleNamespace

import pytest

from rfb.research import pinned_runtime
from rfb.research.pinned_runtime import (
    PinnedRuntimeError,
    build_pinned_manifest,
    verify_after_run,
    verify_before_launch,
    verify_controller_staging,
)


def _fixture(tmp_path: Path):
    root = tmp_path / "venv"
    source = root / "src" / "rfb"
    source.mkdir(parents=True)
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    interpreter = root / "bin" / "python"
    interpreter.parent.mkdir()
    interpreter.write_bytes(b"interpreter")
    return root, source, interpreter


def test_pinned_manifest_is_deterministic_and_verifies(tmp_path):
    root, source, interpreter = _fixture(tmp_path)
    first = build_pinned_manifest(
        root, source_root=source, interpreter=interpreter, fixture_only=True
    )
    second = build_pinned_manifest(
        root, source_root=source, interpreter=interpreter, fixture_only=True
    )
    assert first == second
    assert (
        verify_before_launch(first, root)["runtime_format"] == "python_pinned_venv_v1"
    )
    assert verify_after_run(first, root)["remote_materialization_verified"] is False


def test_cross_target_controller_staging_is_static_and_defers_interpreter_probe(
    tmp_path, monkeypatch
):
    root, source, interpreter = _fixture(tmp_path)
    manifest = build_pinned_manifest(
        root,
        source_root=source,
        interpreter=interpreter,
        target_platform="linux-x86_64",
        fixture_only=True,
    )

    def must_not_run(*args, **kwargs):
        raise AssertionError("foreign interpreter must not run on controller")

    monkeypatch.setattr(pinned_runtime, "_probe_interpreter", must_not_run)
    assert verify_controller_staging(manifest, root)["target_platform"] == (
        "linux-x86_64"
    )


def test_cross_target_controller_staging_rejects_static_source_drift(tmp_path):
    root, source, interpreter = _fixture(tmp_path)
    manifest = build_pinned_manifest(
        root,
        source_root=source,
        interpreter=interpreter,
        target_platform="linux-x86_64",
        fixture_only=True,
    )
    (source / "main.py").write_text("VALUE = 99\n", encoding="utf-8")
    with pytest.raises(PinnedRuntimeError, match="closure drift"):
        verify_controller_staging(manifest, root)


def test_profile_artifacts_hash_both_files_without_mutating_iteration(tmp_path):
    (tmp_path / "runtime_profiles").mkdir()
    (tmp_path / "requirements.txt").write_text("locked\n", encoding="utf-8")
    (tmp_path / "runtime_profiles" / "tep_nonconfirmatory_v1.lock.json").write_text(
        "{}\n", encoding="utf-8"
    )

    artifacts = pinned_runtime._profile_artifacts(tmp_path)

    assert artifacts["requirements_relative"] == "requirements.txt"
    assert artifacts["runtime_profile_relative"].endswith(".lock.json")
    assert len(artifacts["requirements_sha256"]) == 64
    assert len(artifacts["runtime_profile_sha256"]) == 64


@pytest.mark.parametrize("field", ["closure_fingerprint", "runtime_dependency_profile"])
def test_pinned_manifest_rejects_mutation(tmp_path, field):
    root, source, interpreter = _fixture(tmp_path)
    manifest = build_pinned_manifest(
        root, source_root=source, interpreter=interpreter, fixture_only=True
    )
    manifest[field] = "tampered"
    with pytest.raises(PinnedRuntimeError):
        verify_before_launch(manifest, root)


def test_pinned_manifest_reprobes_interpreter_metadata_and_sys_path(
    tmp_path, monkeypatch
):
    root, source, interpreter = _fixture(tmp_path)
    manifest = build_pinned_manifest(
        root, source_root=source, interpreter=interpreter, fixture_only=True
    )
    from rfb.research import pinned_runtime

    original = pinned_runtime._probe_interpreter

    def drift(*args, **kwargs):
        value = original(*args, **kwargs)
        value["version"] = "0.0.0"
        return value

    monkeypatch.setattr(pinned_runtime, "_probe_interpreter", drift)
    with pytest.raises(PinnedRuntimeError, match="metadata drift"):
        verify_before_launch(manifest, root)


def test_pinned_manifest_rejects_native_extension_appearance(tmp_path):
    root, source, interpreter = _fixture(tmp_path)
    site = root / "lib"
    site.mkdir()
    manifest = build_pinned_manifest(
        root,
        source_root=source,
        interpreter=interpreter,
        site_packages=site,
        fixture_only=True,
    )
    (site / "late.so").write_bytes(b"native")
    with pytest.raises(PinnedRuntimeError, match="native extension closure drift"):
        verify_before_launch(manifest, root)


def test_native_linux_closure_recursively_resolves_and_hashes(tmp_path, monkeypatch):
    site = tmp_path / "lib"
    site.mkdir()
    extension = site / "pkg" / "module.so"
    extension.parent.mkdir()
    extension.write_bytes(b"extension")
    lib_a = tmp_path / "liba.so"
    lib_b = tmp_path / "libb.so"
    lib_a.write_bytes(b"a")
    lib_b.write_bytes(b"b")
    outputs = {
        str(extension.resolve()): f"liba.so => {lib_a} (0x1)\n",
        str(lib_a.resolve()): f"libb.so => {lib_b} (0x2)\n",
        str(lib_b.resolve()): "statically linked\n",
    }

    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=outputs[argv[1]], stderr="")

    ldd = tmp_path / "ldd"
    ldd.write_bytes(b"ldd")
    monkeypatch.setattr(pinned_runtime.shutil, "which", lambda _: str(ldd))
    monkeypatch.setattr(pinned_runtime.subprocess, "run", fake_run)
    native, libraries = pinned_runtime._native_closure(site, "linux-x86_64")
    assert native[0]["path"] == "pkg/module.so"
    assert [row["path"] for row in libraries] == sorted(
        [lib_a.resolve().as_posix(), lib_b.resolve().as_posix()]
    )
    assert all(len(row["sha256"]) == 64 for row in libraries)


def test_native_seed_outside_site_is_linked_but_not_site_relative(
    tmp_path, monkeypatch
):
    site = tmp_path / "site"
    site.mkdir()
    seed = tmp_path / "stdlib" / "module.so"
    seed.parent.mkdir()
    seed.write_bytes(b"seed")
    library = tmp_path / "libc.so"
    library.write_bytes(b"library")
    outputs = {
        str(seed.resolve()): f"libc.so => {library} (0x1)\n",
        str(library.resolve()): "statically linked\n",
    }

    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=outputs[argv[1]], stderr="")

    ldd = tmp_path / "ldd"
    ldd.write_bytes(b"ldd")
    monkeypatch.setattr(pinned_runtime.shutil, "which", lambda _: str(ldd))
    monkeypatch.setattr(pinned_runtime.subprocess, "run", fake_run)

    native, libraries = pinned_runtime._native_closure(
        site, "linux-x86_64", seed_paths=[seed]
    )

    assert native == []
    assert [row["path"] for row in libraries] == [library.resolve().as_posix()]


def test_native_closure_rejects_library_outside_explicit_roots(tmp_path, monkeypatch):
    site = tmp_path / "site"
    approved = tmp_path / "approved"
    foreign = tmp_path / "foreign" / "lib.so"
    site.mkdir()
    approved.mkdir()
    foreign.parent.mkdir()
    extension = site / "module.so"
    extension.write_bytes(b"extension")
    foreign.write_bytes(b"foreign")
    ldd = tmp_path / "ldd"
    ldd.write_bytes(b"ldd")
    monkeypatch.setattr(pinned_runtime.shutil, "which", lambda _: str(ldd))
    monkeypatch.setattr(
        pinned_runtime.subprocess,
        "run",
        lambda argv, **kwargs: SimpleNamespace(
            returncode=0, stdout=f"lib.so => {foreign} (0x1)\n", stderr=""
        ),
    )

    with pytest.raises(PinnedRuntimeError, match="outside approved roots"):
        pinned_runtime._native_closure(
            site, "linux-x86_64", approved_roots=[site, approved]
        )


def test_external_root_policy_uses_paths_not_fake_tree_hashes(tmp_path, monkeypatch):
    root, source, interpreter = _fixture(tmp_path)
    site = root / "lib"
    site.mkdir()
    monkeypatch.setattr(
        pinned_runtime,
        "_probe_interpreter",
        lambda *args, **kwargs: {
            "version": "3.11.11",
            "implementation": "CPython",
            "abi": "cpython-311-x86_64-linux-gnu",
            "build": "main",
            "sysconfig": {},
            "target_platform": "linux-x86_64",
            "sys_path": [],
            "sysconfig_paths": {},
            "stdlib_paths": [],
            "import_origins": {},
        },
    )
    monkeypatch.setattr(pinned_runtime, "_is_executable", lambda _: False)

    manifest = build_pinned_manifest(
        root,
        source_root=source,
        interpreter=interpreter,
        site_packages=site,
        target_platform="linux-x86_64",
        fixture_only=True,
    )

    assert all(set(item) == {"path"} for item in manifest["approved_external_roots"])


def test_root_bound_native_paths_are_portable_between_materializations(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    relative = Path("lib/python3.11/lib-dynload/module.so")
    (first / relative).parent.mkdir(parents=True)
    (second / relative).parent.mkdir(parents=True)
    (first / relative).write_bytes(b"same")
    (second / relative).write_bytes(b"same")

    bound = pinned_runtime._normalize_bound_path(first / relative, first)

    assert bound == "@ROOT/lib/python3.11/lib-dynload/module.so"
    assert (
        pinned_runtime._resolve_bound_path(bound, second)
        == (second / relative).resolve()
    )


def test_approved_native_roots_include_materialized_root_and_resolve_bound_paths(
    tmp_path,
):
    root = tmp_path / "runtime"
    stdlib = root / "lib" / "python3.11"
    stdlib.mkdir(parents=True)
    external = tmp_path / "system-lib"
    external.mkdir()
    manifest = {
        "approved_external_roots": [{"path": str(external)}],
        "stdlib_evidence": [{"path": "@ROOT/lib/python3.11"}],
    }

    assert pinned_runtime._approved_native_roots(manifest, root) == [
        root.resolve(),
        external.resolve(),
        stdlib.resolve(),
    ]


def test_distribution_lock_includes_runtime_root_console_script(tmp_path):
    root = tmp_path / "runtime"
    site = root / "lib" / "python3.11" / "site-packages"
    package = site / "demo" / "__init__.py"
    dist_info = site / "demo-1.0.dist-info"
    script = root / "bin" / "demo"
    package.parent.mkdir(parents=True)
    dist_info.mkdir()
    script.parent.mkdir()
    package.write_text("VALUE = 1\n", encoding="utf-8")
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: demo\nVersion: 1.0\n", encoding="utf-8"
    )
    (dist_info / "RECORD").write_text(
        "demo/__init__.py,,\n"
        "demo-1.0.dist-info/METADATA,,\n"
        "demo-1.0.dist-info/RECORD,,\n"
        "../../../bin/demo,,\n",
        encoding="utf-8",
    )

    distributions = pinned_runtime._distributions(site, root)

    assert distributions[0]["name"] == "demo"
    assert "bin/demo" in {item["path"] for item in distributions[0]["files"]}


def test_native_linux_closure_rejects_unresolved_dependency(tmp_path, monkeypatch):
    site = tmp_path / "lib"
    site.mkdir()
    extension = site / "module.so"
    extension.write_bytes(b"extension")
    ldd = tmp_path / "ldd"
    ldd.write_bytes(b"ldd")
    monkeypatch.setattr(pinned_runtime.shutil, "which", lambda _: str(ldd))
    monkeypatch.setattr(
        pinned_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="libmissing.so => not found\n", stderr=""
        ),
    )
    with pytest.raises(PinnedRuntimeError, match="unresolved"):
        pinned_runtime._native_closure(site, "linux-x86_64")


def test_native_linux_closure_resolves_unique_runtime_bundled_dependency(
    tmp_path, monkeypatch
):
    runtime = tmp_path / "runtime"
    site = runtime / "site"
    bundled = runtime / "vendor.libs" / "libbundled.so.1"
    extension = site / "module.so"
    bundled.parent.mkdir(parents=True)
    site.mkdir()
    extension.write_bytes(b"extension")
    bundled.write_bytes(b"bundled")
    outputs = {
        str(extension.resolve()): "libbundled.so.1 => not found\n",
        str(bundled.resolve()): "statically linked\n",
    }

    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=outputs[argv[1]], stderr="")

    ldd = tmp_path / "ldd"
    ldd.write_bytes(b"ldd")
    monkeypatch.setattr(pinned_runtime.shutil, "which", lambda _: str(ldd))
    monkeypatch.setattr(pinned_runtime.subprocess, "run", fake_run)

    _, libraries = pinned_runtime._native_closure(
        site, "linux-x86_64", approved_roots=[runtime]
    )

    assert [row["path"] for row in libraries] == [bundled.resolve().as_posix()]


def test_pinned_manifest_rejects_source_drift(tmp_path):
    root, source, interpreter = _fixture(tmp_path)
    manifest = build_pinned_manifest(
        root, source_root=source, interpreter=interpreter, fixture_only=True
    )
    (source / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(PinnedRuntimeError, match="closure drift"):
        verify_before_launch(manifest, root)


def test_pinned_manifest_rejects_interpreter_symlink(tmp_path):
    root, source, interpreter = _fixture(tmp_path)
    manifest = build_pinned_manifest(
        root, source_root=source, interpreter=interpreter, fixture_only=True
    )
    interpreter.unlink()
    try:
        interpreter.symlink_to(source / "main.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable")
    with pytest.raises(PinnedRuntimeError):
        verify_before_launch(manifest, root)


def test_executable_probe_injects_site_without_running_site_hooks(
    monkeypatch, tmp_path
):
    root, _, interpreter = _fixture(tmp_path)
    interpreter.chmod(0o755)
    monkeypatch.setattr(pinned_runtime, "_is_executable", lambda _: True)
    monkeypatch.setattr(pinned_runtime.os, "name", "posix")
    monkeypatch.setenv("RFB_EPHEMERAL_PASSWORD", "must-not-reach-probe")
    monkeypatch.setenv("SSH_ASKPASS", "/credential/helper")
    monkeypatch.setenv("SSH_ASKPASS_REQUIRE", "force")
    monkeypatch.setenv("DISPLAY", "credential-scope")
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["env"] = kwargs["env"]
        return SimpleNamespace(
            stdout='{"version":"3.11.0","implementation":"CPython","abi":"none","build":"build","sysconfig":{"SOABI":"none","MULTIARCH":"","CONFIG_ARGS":""},"target_platform":"linux-x86_64","sys_path":[],"sysconfig_paths":{},"stdlib_paths":[],"import_origins":{"numpy":"/venv/lib/numpy/__init__.py","scipy":"/venv/lib/scipy/__init__.py","rfb":"/venv/src/rfb/__init__.py"}}',
            stderr="",
            returncode=0,
        )

    monkeypatch.setattr(pinned_runtime.subprocess, "run", fake_run)
    site = root / "lib" / "python3.11" / "site-packages"
    pinned_runtime._probe_interpreter(interpreter, root, site)
    assert seen["argv"][1:7] == ["-X", "utf8", "-B", "-I", "-S", "-c"]
    assert seen["argv"][-1] == str(site)
    assert seen["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert "RFB_EPHEMERAL_PASSWORD" not in seen["env"]
    assert "SSH_ASKPASS" not in seen["env"]
    assert "SSH_ASKPASS_REQUIRE" not in seen["env"]
    assert "DISPLAY" not in seen["env"]
