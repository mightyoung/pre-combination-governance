from __future__ import annotations

import pytest
from rfb.methods import get_registry
from rfb.formal.lifecycle import FormalLifecycle, LifecycleError, LifecycleState
from rfb.formal.runner import FormalRunner, MethodEntry
from rfb.formal.truth import TruthIsolationError, sanitize_observations


def test_lifecycle_replay_is_identical_and_rejects_reorder():
    life = FormalLifecycle("tx", expected_rows=["r"])
    life.start()
    assert life.record_row("r", {"x": 1}) is True
    life.finish(LifecycleState.FAILED, error="boom").seal()
    replay = FormalLifecycle.replay("tx", life.events, ["r"])
    assert tuple(e.event_hash for e in replay.events) == tuple(
        e.event_hash for e in life.events
    )
    with pytest.raises(LifecycleError):
        FormalLifecycle.replay("tx", tuple(reversed(life.events)), ["r"])


@pytest.mark.parametrize(
    "bad",
    [b"raw", bytearray(b"raw"), memoryview(b"raw"), {"truth": 1}, {"raw": {"x": 1}}],
)
def test_truth_boundary_rejects_bytes_and_nested_aliases(bad):
    with pytest.raises(TruthIsolationError):
        sanitize_observations(bad)


def test_runner_does_not_mutate_caller_observations():
    def mutate(obs):
        obs["x"].append(9)
        return {"ok": True}

    source = {"x": [1]}
    FormalRunner({"B0": MethodEntry("B0", mutate)}, allow_partial_panel=True).run_all(
        transaction_id="tx", bundle_id="b", observations=source, seed=1
    )
    assert source == {"x": [1]}


def test_formal_runner_rejects_partial_panel_by_default():
    with pytest.raises(ValueError, match="closed B0-B5"):
        FormalRunner({"B0": get_registry()["B0"]})
    result = FormalRunner(
        {"B0": get_registry()["B0"]}, allow_partial_panel=True
    ).run_all(transaction_id="tx-partial", bundle_id="b", observations={"x": 1}, seed=1)
    assert result.lifecycle.events[-2].payload["panel_closed"] is False


def test_truth_boundary_rejects_adversarial_payloads_in_subprocess():
    import json
    import subprocess
    import sys

    payloads = [
        {"truth": 1},
        {"frame": {"object": {"alias": "truth"}}},
        {"blob": b"raw"},
    ]
    code = "import sys,json; from rfb.formal.truth import sanitize_observations; sanitize_observations(json.loads(sys.stdin.read()))"
    for payload in payloads[:2]:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
        )
        assert proc.returncode != 0
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "from rfb.formal.truth import sanitize_observations; sanitize_observations({'blob': b'raw'})",
        ],
        capture_output=True,
    )
    assert proc.returncode != 0


def test_lifecycle_replay_rejects_seal_without_terminal_even_with_valid_hash_chain():
    life = FormalLifecycle("tx", expected_rows=[])
    life.start()
    forged = list(life.events)
    forged.append(
        type(forged[0]).build(
            2, LifecycleState.SEALED, "tx", {"row_count": 0}, forged[-1].event_hash
        )
    )
    with pytest.raises(LifecycleError):
        FormalLifecycle.replay("tx", forged, [])


def test_formal_runner_rejects_unstructured_builtin_observations():
    result = FormalRunner(
        {"B0": get_registry()["B0"]}, allow_partial_panel=True
    ).run_all(transaction_id="tx", bundle_id="b", observations={"x": 1}, seed=1)
    assert result.lifecycle.events[-2].state is LifecycleState.FAILED
    assert result.lifecycle.events[-2].payload["failed_method_id"] == "B0"
    assert result.rows == {}
