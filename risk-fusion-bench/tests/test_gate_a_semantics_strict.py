from __future__ import annotations

import pytest

from rfb.methods import run_method
from rfb.methods.models import MethodInputError


def _input(events, controls=None):
    return {
        "bundle_id": "strict-bundle",
        "algorithm_seed": 7,
        "transaction_id": "strict-tx",
        "events": events,
        "controls": controls or [],
    }


def test_b0_normalized_conjunctive_has_frozen_binary_support_semantics():
    out = run_method(
        "B0",
        _input(
            [
                {"message_id": "m1", "version": 1, "root_id": "r1", "support": 0.8},
                {"message_id": "m2", "version": 1, "root_id": "r2", "support": 0.8},
            ]
        ),
    )
    assert out["prediction"]["risk_score"] == pytest.approx(0.96)


def test_b1_exact_retry_is_invariant_but_conflicting_same_message_version_fails():
    base = _input(
        [
            {"message_id": "m1", "version": 1, "root_id": "r1", "support": 0.4},
        ]
    )
    retry = _input(
        [
            {"message_id": "m1", "version": 1, "root_id": "r1", "support": 0.4},
            {"message_id": "m1", "version": 1, "root_id": "r1", "support": 0.4},
        ]
    )
    assert run_method("B1", base)["prediction"] == run_method("B1", retry)["prediction"]
    conflict = _input(
        [
            {"message_id": "m1", "version": 1, "root_id": "r1", "support": 0.4},
            {"message_id": "m1", "version": 1, "root_id": "r2", "support": 0.4},
        ]
    )
    with pytest.raises(MethodInputError):
        run_method("B1", conflict)


def test_b2_declared_lineage_eliminates_ancestors_without_latent_equivalence():
    lineage = _input(
        [
            {"message_id": "m1", "version": 1, "root_id": "ancestor", "support": 0.8},
            {
                "message_id": "m2",
                "version": 1,
                "root_id": "derived",
                "support": 0.2,
                "derived_from": ["ancestor"],
            },
        ]
    )
    derived_only = _input(
        [
            {"message_id": "m2", "version": 1, "root_id": "derived", "support": 0.2},
        ]
    )
    assert (
        run_method("B2", lineage)["prediction"]
        == run_method("B2", derived_only)["prediction"]
    )
    same_values_no_declaration = _input(
        [
            {"message_id": "m1", "version": 1, "root_id": "x", "support": 0.5},
            {"message_id": "m2", "version": 1, "root_id": "y", "support": 0.5},
        ]
    )
    assert run_method("B2", same_values_no_declaration)["prediction"][
        "risk_score"
    ] == pytest.approx(0.75)


def test_b3_and_b5_are_duplicate_invariant_and_permutation_invariant():
    base = _input(
        [
            {"message_id": "m1", "version": 1, "root_id": "r1", "support": 0.6},
            {"message_id": "m2", "version": 1, "root_id": "r2", "support": 0.2},
        ]
    )
    duplicate_permuted = _input(
        [
            {"message_id": "m2", "version": 1, "root_id": "r2", "support": 0.2},
            {"message_id": "m3", "version": 1, "root_id": "r1", "support": 0.6},
            {"message_id": "m1", "version": 1, "root_id": "r1", "support": 0.6},
        ]
    )
    for method_id in ("B3", "B5"):
        assert (
            run_method(method_id, base)["prediction"]
            == run_method(method_id, duplicate_permuted)["prediction"]
        )
        assert (
            run_method(method_id, base)["decision"]
            == run_method(method_id, duplicate_permuted)["decision"]
        )


def test_proposed_control_rebuild_merges_equivalent_roots_and_retirement():
    uncontrolled = _input(
        [
            {"message_id": "m1", "version": 1, "root_id": "r1", "support": 0.8},
            {"message_id": "m2", "version": 1, "root_id": "r2", "support": 0.8},
        ]
    )
    equivalent = _input(
        [
            {"message_id": "m1", "version": 1, "root_id": "r1", "support": 0.8},
            {"message_id": "m2", "version": 1, "root_id": "r2", "support": 0.8},
        ],
        [
            {
                "kind": "EQUIVALENCE",
                "roots": ["r1", "r2"],
                "canonical_root": "r1",
                "order": 3,
            }
        ],
    )
    retired = _input(
        [
            {"message_id": "m1", "version": 1, "root_id": "r1", "support": 0.8},
            {"message_id": "m2", "version": 1, "root_id": "r2", "support": 0.8},
        ],
        [{"kind": "RETIRE", "roots": ["r2"], "order": 3}],
    )
    assert run_method("Proposed", uncontrolled)["prediction"][
        "risk_score"
    ] == pytest.approx(0.96)
    assert run_method("Proposed", equivalent)["prediction"][
        "risk_score"
    ] == pytest.approx(0.8)
    assert run_method("Proposed", retired)["prediction"]["risk_score"] == pytest.approx(
        0.8
    )
