from __future__ import annotations

import pytest

from rfb.research.receipts import _validate_runtime_binding
from rfb.research.runtime_binding import runtime_binding_args


def _pinned(**updates):
    value = {
        "runtime_format": "python_pinned_venv_v1",
        "runtime_dependency_profile": "tep_nonconfirmatory_v1",
        "runtime_path": "/run/.runtime/python",
        "runtime_file_sha256": "a" * 64,
        "runtime_source_sha256": "b" * 64,
        "runtime_manifest_sha256": "c" * 64,
        "pinned_runtime_manifest_sha256": "d" * 64,
        "pinned_runtime_closure_fingerprint": "sha256:" + "e" * 64,
    }
    value.update(updates)
    return value


def test_pinned_receipt_binding_requires_both_closure_hashes():
    _validate_runtime_binding(_pinned())
    with pytest.raises(ValueError, match="manifest hash required"):
        _validate_runtime_binding(_pinned(pinned_runtime_manifest_sha256=None))
    with pytest.raises(ValueError, match="closure fingerprint required"):
        _validate_runtime_binding(_pinned(pinned_runtime_closure_fingerprint=None))


def test_runtime_binding_args_carries_pinned_hashes_without_downgrade():
    args = runtime_binding_args(_pinned())
    assert "--pinned-runtime-manifest-sha256" in args
    assert "--pinned-runtime-closure-fingerprint" in args
    assert args[args.index("--runtime-dependency-profile") + 1] == (
        "tep_nonconfirmatory_v1"
    )


def test_stdlib_binding_args_remains_unchanged():
    args = runtime_binding_args(
        {
            "runtime_file_sha256": "a" * 64,
            "runtime_source_sha256": "b" * 64,
            "runtime_manifest_sha256": "c" * 64,
            "runtime_dependency_profile": "stdlib_only",
            "runtime_path": "/run/.runtime/fixture.pyz",
        }
    )
    assert not any(item.startswith("--pinned-runtime-") for item in args)
