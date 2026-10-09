from __future__ import annotations

import math

import pytest

from rfb.methods import METHOD_IDS
from rfb.regeneration import (
    compare_full_panel_replay,
    freeze_regeneration_plan,
    panel_commitment,
    payload_commitment,
    select_frozen_samples,
    verify_regeneration,
)


def _panel():
    return {name: {"result_sha256": name} for name in METHOD_IDS}


@pytest.mark.parametrize(
    ("n", "expected"), [(2, 2), (199, 2), (200, 2), (201, 3), (1000, 10)]
)
def test_sample_size_uses_one_percent_ceiling_with_two_sample_floor(
    n: int, expected: int
):
    samples = select_frozen_samples([f"b-{i}" for i in range(n)], seed=17)
    assert len(samples) == max(2, math.ceil(0.01 * n))
    assert len(samples) == expected


@pytest.mark.parametrize("n", [0, 1])
def test_regeneration_rejects_segments_too_small_for_two_samples(n: int):
    with pytest.raises(ValueError, match="at least 2|N=0|N=1"):
        select_frozen_samples([f"b-{i}" for i in range(n)], seed=17)


def test_sample_selection_is_order_independent_and_has_no_replacement():
    bundles = [f"b-{index}" for index in range(1, 11)]
    assert select_frozen_samples(bundles, seed=17) == select_frozen_samples(
        list(reversed(bundles)), seed=17
    )
    selected = select_frozen_samples(bundles, seed=17)
    assert len(selected) == len(set(selected))


def test_duplicate_bundle_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        select_frozen_samples(["b-1", "b-1"], seed=17)


def test_payload_commitment_changes_for_single_byte_mutation():
    assert payload_commitment(b"payload") != payload_commitment(b"payloae")
    assert payload_commitment(b"payload") != payload_commitment(b"payload!")


def test_full_panel_requires_exactly_seven_methods():
    expected = _panel()
    assert compare_full_panel_replay(expected, expected) is True
    for changed in (
        {"B0": {"result_sha256": "x"}},
        {**expected, "extra": {"result_sha256": "x"}},
        {**expected, "B1": {"result_sha256": "changed"}},
    ):
        assert compare_full_panel_replay(expected, changed) is False


@pytest.mark.parametrize(
    "bad",
    [
        {"B0": {"result_sha256": "nan"}},
        {"B0": {"result_sha256": "x", "tolerance": 0.1}},
    ],
)
def test_unregistered_tolerance_or_malformed_panel_fails_closed(bad):
    expected = _panel()
    assert compare_full_panel_replay(expected, {**expected, **bad}) is False


def test_verify_regeneration_keeps_dataset_and_stops_next_segment_on_mismatch():
    bundles = ["b-1", "b-2"]
    plan = freeze_regeneration_plan(segment_id="seg-1", bundle_ids=bundles, seed=17)
    panel = _panel()
    result = verify_regeneration(
        plan=plan,
        current_bundle_ids=bundles,
        bundle_id=plan["selected_ids"][0],
        expected_payload_commitment_sha256=payload_commitment(b"payload"),
        regenerated_payload=b"payloae",
        original_payload=b"payload",
        original_panel=panel,
        expected_panel_commitment_sha256=panel_commitment(panel),
        regenerated_panel={name: dict(value) for name, value in panel.items()},
        method_registry_hash="",
    )
    assert result["status"] == "INVALID_RESULT_KEEP_DATASET_STOP_NEXT_SEGMENT"
    assert result["purge_authorized"] is False
    assert result["dataset_retained"] is True
    assert result["next_segment_allowed"] is False
