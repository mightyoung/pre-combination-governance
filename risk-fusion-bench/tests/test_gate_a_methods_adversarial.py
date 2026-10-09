from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfb.methods import (
    METHOD_IDS,
    generate_registry_document,
    get_registry,
    parse_method_input,
    run_all,
)
from rfb.methods.models import MethodInputError


def _obs(events, controls=None):
    return {
        "bundle_id": "adversarial-bundle",
        "algorithm_seed": 3,
        "transaction_id": "adversarial-tx",
        "events": events,
        "controls": controls or [],
    }


def test_registry_is_exactly_seven_ids_without_resolvable_paper_alias():
    registry = get_registry()
    assert (
        tuple(registry)
        == METHOD_IDS
        == ("B0", "B1", "B2", "B3", "B4", "B5", "Proposed")
    )
    document = generate_registry_document(registry)
    assert len(document["methods"]) == 7
    assert all(
        row["formal_eligible"] is (row["qualification_evidence_sha256"] is not None)
        for row in document["methods"]
    )
    assert sum(row["paper_alias"] == "A" for row in document["methods"]) == 1
    assert all(row["method_id"] != "A" for row in document["methods"])
    assert len({row["implementation_sha256"] for row in document["methods"]}) == 7


def test_registry_rejects_extra_or_missing_method_ids():
    registry = get_registry()
    registry.pop("B5")
    with pytest.raises(ValueError):
        generate_registry_document(registry)
    registry = get_registry()
    registry["A"] = registry["Proposed"]
    with pytest.raises(ValueError):
        run_all({"x": 1}, registry=registry)


def test_all_methods_return_closed_provenance_and_unique_method_outputs():
    outputs = run_all(
        _obs(
            [
                {"message_id": "m1", "version": 1, "root_id": "r1", "support": 0.2},
                {"message_id": "m2", "version": 1, "root_id": "r2", "support": 0.8},
            ]
        )
    )
    assert set(outputs) == set(METHOD_IDS)
    required = {
        "schema_version",
        "transaction_id",
        "bundle_id",
        "algorithm_seed",
        "method_id",
        "implementation_version",
        "implementation_sha256",
        "input_commitment_sha256",
        "scorer_id",
        "formal_eligible",
        "valid",
        "prediction",
        "decision",
        "audit",
        "result",
        "result_sha256",
    }
    assert all(required <= set(v) for v in outputs.values())
    assert len({json.dumps(v["result"], sort_keys=True) for v in outputs.values()}) == 7


@pytest.mark.parametrize("method_id", METHOD_IDS)
def test_method_rejects_truth_and_raw_fields_even_when_nested_or_serialized(method_id):
    method = get_registry()[method_id]
    for bad in (
        {"nested": {"truth": 1}},
        {"raw_payload": "x"},
        {"blob": b"raw"},
        {"nested": {"raw": "x"}},
    ):
        with pytest.raises(ValueError):
            method.execute(bad)


def test_semantic_fixture_covers_retry_lineage_caution_endpoints_and_proposed_replay():
    registry = get_registry()
    event_a = {"message_id": "m1", "version": 1, "root_id": "a", "support": 0.2}
    event_b = {"message_id": "m2", "version": 1, "root_id": "b", "support": 0.8}
    base = _obs([event_a, event_b])
    extended = _obs(
        [
            event_a,
            event_b,
            {"message_id": "m3", "version": 1, "root_id": "c", "support": 0.5},
        ]
    )
    permuted = _obs([event_b, event_a])
    assert (
        registry["B0"].execute(base)["result"]
        != registry["B0"].execute(extended)["result"]
    )
    assert (
        registry["B1"].execute(base)["result"]
        == registry["B1"].execute(permuted)["result"]
    )
    declared = _obs(
        [
            event_a,
            {
                "message_id": "m2",
                "version": 1,
                "root_id": "b",
                "support": 0.8,
                "lineage": ["a", "b"],
                "derived_from": ["a"],
            },
        ]
    )
    assert (
        registry["B2"].execute(base)["prediction"]
        != registry["B2"].execute(declared)["prediction"]
    )
    assert (
        registry["B3"].execute(base)["result"]
        == registry["B3"].execute(permuted)["result"]
    )
    assert (
        0
        <= registry["B4"].execute(
            _obs([{"message_id": "m1", "version": 1, "root_id": "a", "support": 0}])
        )["result"]["risk_score"]
        <= 1
    )
    assert (
        0
        <= registry["B4"].execute(
            _obs([{"message_id": "m1", "version": 1, "root_id": "a", "support": 1}])
        )["result"]["risk_score"]
        <= 1
    )
    low = registry["B5"].execute(
        _obs([{"message_id": "m1", "version": 1, "root_id": "a", "support": 0.1}])
    )["result"]["risk_score"]
    double = _obs(
        [
            {"message_id": "m1", "version": 1, "root_id": "a", "support": 0.1},
            {"message_id": "m2", "version": 1, "root_id": "b", "support": 0.1},
        ]
    )
    assert low <= registry["B5"].execute(double)["result"]["risk_score"]
    assert (
        registry["Proposed"].execute(base)["result"]
        == registry["Proposed"].execute(permuted)["result"]
    )


def test_flat_mapping_inputs_are_rejected_for_all_public_surfaces():
    with pytest.raises(MethodInputError):
        parse_method_input({"a": 0.5})
    with pytest.raises(MethodInputError):
        run_all({"a": 0.2, "b": 0.8})
    with pytest.raises(MethodInputError):
        get_registry()["B2"].execute({"a": 0.2, "b": 0.8, "lineage": "declared"})


def test_method_output_schema_is_closed_and_excludes_recursive_truth_raw_properties():
    schema = json.loads(
        (
            Path(__file__).parents[1] / "src/rfb/contracts/method_output.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert schema.get("additionalProperties") is False
    serialized = json.dumps(schema).casefold()
    assert "truth" not in serialized and "raw_payload" not in serialized
