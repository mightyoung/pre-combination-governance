# -*- coding: utf-8 -*-
"""G1 shakedown contracts for physical and observation-noise seeds.

These tests qualify generator mechanics only.  They do not create or inspect
confirmatory data.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rfb.benchmark.generator import Scenario


def _truth_trace(scenario: Scenario) -> list[float]:
    return [scenario.truth(float(t)) for t in range(0, int(scenario.duration) + 1)]


def _truth_hash(scenario: Scenario) -> str:
    payload = json.dumps(_truth_trace(scenario), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _evidence_trace(scenario: Scenario) -> list[tuple]:
    return [
        (
            event.t_gen,
            event.source_id,
            event.reliability,
            tuple(sorted(event.m.items())),
        )
        for event in scenario.emit(adversarial_rate=0.2)
    ]


def test_physical_seed_changes_truth_hash():
    first = Scenario(seed=11, physical_seed=101, noise_seed=7)
    second = Scenario(seed=11, physical_seed=202, noise_seed=7)

    assert _truth_hash(first) != _truth_hash(second)


def test_noise_seed_changes_evidence_but_not_truth():
    first = Scenario(seed=11, physical_seed=101, noise_seed=7)
    second = Scenario(seed=11, physical_seed=101, noise_seed=8)

    assert _truth_hash(first) == _truth_hash(second)
    assert _evidence_trace(first) != _evidence_trace(second)


def test_same_configuration_replays_bitwise_identically():
    kwargs = {"seed": 11, "physical_seed": 101, "noise_seed": 7}
    first = Scenario(**kwargs)
    second = Scenario(**kwargs)

    assert _truth_trace(first) == _truth_trace(second)
    assert _evidence_trace(first) == _evidence_trace(second)


def test_legacy_seed_interface_remains_deterministic():
    first = Scenario(seed=42)
    second = Scenario(seed=42)

    assert _truth_trace(first) == _truth_trace(second)
    assert _evidence_trace(first) == _evidence_trace(second)
