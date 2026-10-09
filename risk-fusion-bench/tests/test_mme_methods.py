from __future__ import annotations

import copy
from typing import Any

import pytest

from rfb.methods.registry import METHOD_IDS
from rfb.research.mme_events import generate_block
from rfb.research.mme_methods import (
    RESEARCH_METHOD_IDS,
    evaluate_prefix,
    method_panel_document,
    run_panel,
)


def _prefix(*, controls: list[dict[str, object]] | None = None) -> dict[str, Any]:
    return {
        "block_id": "D_impl_unit-block-methods-001",
        "prefix_id": "XI",
        "bundle_id": "D_impl_unit-pair-methods-001",
        "algorithm_seed": 91007,
        "transaction_id": "D_impl_unit-methods-001:XI",
        "events": [
            {
                "event_id": "opaque-event-a",
                "message_id": "opaque-message-a",
                "version": 1,
                "root_id": "opaque-root-a",
                "support": 0.8,
                "reliability": 1.0,
                "order": 10,
            },
            {
                "event_id": "opaque-event-b",
                "message_id": "opaque-message-b",
                "version": 1,
                "root_id": "opaque-root-b",
                "support": 0.8,
                "reliability": 1.0,
                "order": 20,
            },
        ],
        "controls": controls or [],
    }


def test_research_panel_is_separate_from_formal_api() -> None:
    assert METHOD_IDS == ("B0", "B1", "B2", "B3", "B4", "B5", "Proposed")
    assert set(RESEARCH_METHOD_IDS) == {*METHOD_IDS, "ES-Rebuild"}
    result = run_panel(_prefix())
    assert tuple(result) == RESEARCH_METHOD_IDS
    assert all(row["status"] == "SUCCEEDED" for row in result.values())


def test_late_equivalence_rebuild_recovers_without_weakening_b0() -> None:
    public = _prefix(
        controls=[
            {
                "control_id": "opaque-control-equivalence",
                "kind": "EQUIVALENCE",
                "roots": ["opaque-root-a", "opaque-root-b"],
                "canonical_root": "opaque-root-a",
                "order": 30,
            }
        ]
    )
    b0 = evaluate_prefix("B0", public)
    rebuilt = evaluate_prefix("ES-Rebuild", public)
    proposed = evaluate_prefix("Proposed", public)

    assert b0["risk_interval"] == [0.96, 1.0]
    assert rebuilt["risk_interval"] == [0.8, 1.0]
    assert proposed["risk_interval"] == [0.8, 1.0]
    assert rebuilt["cost"]["recomputed_action_count"] == 3
    assert rebuilt["active_contribution_count"] == 1


def test_truth_sidecar_cannot_enter_any_method_and_external_truth_is_irrelevant() -> (
    None
):
    public = _prefix()
    first = run_panel(public)
    changed_truth = {
        "records": [{"event_id": "opaque-event-a", "physical_root_id": "changed"}]
    }
    second = run_panel(copy.deepcopy(public))
    for method_id in RESEARCH_METHOD_IDS:
        for field in ("status", "risk_interval", "action_state", "failure_code", "bpa"):
            assert first[method_id].get(field) == second[method_id].get(field)
    assert changed_truth

    leaked = copy.deepcopy(public)
    leaked["truth_sidecar"] = changed_truth
    for method_id in RESEARCH_METHOD_IDS:
        with pytest.raises(ValueError, match="private scorer field"):
            evaluate_prefix(method_id, leaked)


def test_supersede_and_retire_are_recomputed_from_public_controls() -> None:
    public = _prefix(
        controls=[
            {
                "control_id": "opaque-control-retire",
                "kind": "RETIRE",
                "roots": ["opaque-root-a"],
                "order": 30,
            }
        ]
    )
    rebuilt = evaluate_prefix("ES-Rebuild", public)
    proposed = evaluate_prefix("Proposed", public)
    assert rebuilt["risk_interval"] == proposed["risk_interval"] == [0.8, 1.0]
    assert (
        rebuilt["active_contribution_count"]
        == proposed["active_contribution_count"]
        == 1
    )


def test_bpa_is_emitted_only_for_legal_simple_support_outputs() -> None:
    panel = run_panel(_prefix())
    assert "bpa" not in panel["B5"]
    for method_id in set(RESEARCH_METHOD_IDS) - {"B5"}:
        row = panel[method_id]
        assert row["risk_interval"] == [row["bpa"]["masses"][0], 1.0]
        assert sum(row["bpa"]["masses"]) == pytest.approx(1.0)


def test_proxy_semantics_are_explicit_and_b4_is_fixed_before_results() -> None:
    rows = {row["method_id"]: row for row in method_panel_document()["methods"]}
    assert rows["B4"]["parameters"] == {"dependence": 0.7, "neighbor_weight": 0.3}
    assert "not complete PRIMEX-PEV" in rows["B2"]["proxy_scope"]
    assert rows["B5"]["output_type"] == "risk_interval_only"
    assert rows["ES-Rebuild"]["parameters"]["oracle_access"] is False


def test_common_cap_failure_keeps_named_slot_without_fabricated_output() -> None:
    public = _prefix()
    public["method_cap"] = 1
    panel = run_panel(public)
    assert tuple(panel) == RESEARCH_METHOD_IDS
    for method_id, row in panel.items():
        assert row["status"] == "FAILED"
        assert row["failure_code"] in {
            "ACTIVE_CONTRIBUTION_CAP",
            "CONTRIBUTION_BUDGET_CAP",
        }
        assert row["risk_interval"] is None
        assert row["action_state"] == "NO_ACTION"


def test_common_action_threshold_uses_lower_endpoint() -> None:
    public = _prefix()
    public["events"] = public["events"][:1]
    for event in public["events"]:
        event["support"] = 0.6
    panel = run_panel(public)
    assert all(row["action_state"] == "REVIEW" for row in panel.values())


def test_generated_d_impl_unit_actions_run_through_both_rebuild_paths() -> None:
    block = generate_block(
        {
            "block_id": "D_impl_unit-method-integration-003",
            "duplicate_class": "distinct_key_same_acquisition",
            "equivalence_timing": "post_commit_short",
            "lifecycle": "merge",
            "independent_information": "zero_new_root",
        },
        run_class="D_impl_unit",
    )
    recovered = next(
        prefix
        for prefix in block.prefixes
        if prefix.arm_id == "XD" and prefix.prefix_index == 2
    )
    public = recovered.method_payload()
    assert evaluate_prefix("ES-Rebuild", public)["risk_interval"] == [0.8, 1.0]
    assert evaluate_prefix("Proposed", public)["risk_interval"] == [0.8, 1.0]


@pytest.mark.parametrize("mutation", ["divergent_support", "future_action"])
def test_divergent_public_action_projections_are_rejected(mutation: str) -> None:
    block = generate_block(
        {
            "block_id": "D_impl_unit-method-projection-004",
            "duplicate_class": "distinct_key_same_acquisition",
            "equivalence_timing": "post_commit_short",
            "lifecycle": "merge",
            "independent_information": "zero_new_root",
        },
        run_class="D_impl_unit",
    )
    public = copy.deepcopy(block.prefix("XD", 2).method_payload())
    if mutation == "divergent_support":
        public["actions"][0]["support"] = 0.7
    else:
        future = copy.deepcopy(public["actions"][0])
        future["action_id"] = "f" * 64
        future["message_id"] = "e" * 64
        future["order"] = 10_000
        public["actions"].append(future)
    for method_id in RESEARCH_METHOD_IDS:
        with pytest.raises(ValueError, match="projection differs"):
            evaluate_prefix(method_id, public)
