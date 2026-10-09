"""R001 tests for static and runtime separation from the formal lane."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from rfb.live_gate import LiveGateBlocked, LiveGateVerifier, canonical_hash


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_MODULES = {
    "rfb.authority",
    "rfb.broker",
    "rfb.live_gate",
    "rfb.admission",
    "rfb.purge",
    "rfb.live_purge",
}


def test_research_package_has_no_formal_import_or_dynamic_execution_surface():
    package = ROOT / "src" / "rfb" / "research"
    if not package.is_dir():
        pytest.fail(f"R001 research package missing: {package}")
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
                assert not names & FORBIDDEN_MODULES, (path, names & FORBIDDEN_MODULES)
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in FORBIDDEN_MODULES, (path, node.module)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"eval", "exec", "__import__"}, (
                    path,
                    node.func.id,
                )


def test_live_gate_rejects_a_research_receipt_before_promotion():
    verifier = LiveGateVerifier(
        signer_id="test", signing_key=b"k" * 32, trust_epoch="e1"
    )
    snapshot = {}
    with pytest.raises(LiveGateBlocked, match="development|promot"):
        verifier.verify_and_sign(
            {"classification": "DEVELOPMENT_NONCONFIRMATORY"},
            source_snapshot=snapshot,
            expected_snapshot_hash=canonical_hash(snapshot),
        )


def test_formal_admission_guard_rejects_research_receipt():
    from rfb.research.formal_boundary import reject_research_receipt  # noqa: PLC0415

    with pytest.raises((ValueError, PermissionError), match="research|non-promotable"):
        reject_research_receipt(
            {
                "classification": "DEVELOPMENT_NONCONFIRMATORY",
                "formal_gate_effect": "NONE",
            }
        )


def test_shk001b_guard_rejects_without_formal_admission():
    from rfb.research.formal_boundary import assert_shk001b_blocked  # noqa: PLC0415

    with pytest.raises(
        (ValueError, PermissionError), match="SHK-001B|admission|blocked"
    ):
        assert_shk001b_blocked({"classification": "DEVELOPMENT_NONCONFIRMATORY"})
