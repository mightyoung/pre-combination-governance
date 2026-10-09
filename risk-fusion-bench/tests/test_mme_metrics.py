from __future__ import annotations

import math

import pytest

from rfb.research.mme_metrics import (
    MetricInputError,
    belief_l1,
    interval_endpoint_error,
    jousselme_distance,
    make_runner_scorer,
    recovery_curve,
    score_actions,
    score_block_prefixes,
    score_method_prefix,
    score_response_pair,
    validate_bpa,
)


def bpa(single_a: float, single_b: float, ignorance: float = 0.0):
    return {
        "frame": ["a", "b"],
        "masses": [
            {"focal_set": ["a"], "mass": single_a},
            {"focal_set": ["b"], "mass": single_b},
            {"focal_set": ["a", "b"], "mass": ignorance},
        ],
    }


def test_belief_distances_match_independent_binary_anchor():
    left, right = bpa(1.0, 0.0), bpa(0.0, 1.0)
    assert belief_l1(left, right) == 2.0
    assert jousselme_distance(left, right) == 1.0
    mixed = bpa(0.5, 0.5)
    assert math.isclose(jousselme_distance(left, mixed), 0.5)
    compact = {
        "frame": ["a", "b"],
        "focal_sets": [["a"], ["b"]],
        "masses": [1.0, 0.0],
    }
    assert belief_l1(left, compact) == 0.0


@pytest.mark.parametrize(
    "document",
    [
        {"frame": ["a"], "masses": [{"focal_set": ["a"], "mass": float("nan")}]},
        {"frame": ["a"], "masses": [{"focal_set": ["a"], "mass": 0.5}]},
        {"frame": ["a"], "masses": [{"focal_set": ["b"], "mass": 1.0}]},
    ],
)
def test_bpa_validation_rejects_nan_non_normalization_and_wrong_frame(document):
    with pytest.raises(MetricInputError):
        validate_bpa(document)


def test_interval_endpoint_anchor_and_nan_rejection():
    result = interval_endpoint_error([0.2, 0.8], [0.3, 0.6])
    assert result == {
        "lower_absolute_error": pytest.approx(0.1),
        "upper_absolute_error": pytest.approx(0.2),
        "endpoint_l1": pytest.approx(0.3),
        "endpoint_mean_absolute_error": pytest.approx(0.15),
    }
    with pytest.raises(MetricInputError):
        interval_endpoint_error([float("nan"), 0.8], [0.3, 0.6])


def test_recovery_scores_every_prefix_from_effective_disclosure_and_keeps_missing():
    curve = recovery_curve(
        [
            {"prefix": 1, "method_interval": [0.8, 0.9], "oracle_interval": [0.2, 0.3]},
            {"prefix": 2, "method_interval": [0.4, 0.6], "oracle_interval": [0.3, 0.5]},
            {"prefix": 3, "oracle_interval": [0.4, 0.6]},
            {"prefix": 4, "method_interval": [0.4, 0.6], "oracle_interval": [0.4, 0.6]},
        ],
        disclosure_prefix=2,
    )
    assert [row["prefix"] for row in curve["prefixes"]] == [2, 3, 4]
    assert curve["scored_prefixes"] == 2
    assert curve["unavailable_prefixes"] == 1
    assert curve["prefixes"][1]["status"] == "UNAVAILABLE"


def test_availability_false_is_a_false_block_and_not_a_correct_decision():
    result = score_actions(
        predicted_actions=[], oracle_actions=["SAFE"], available=False
    )
    assert result["false_block"] is True
    assert result["action_set_disagreement"] is None
    assert result["predicted_action_count"] is None


def test_sri_compares_independent_response_direction_and_amplitude_to_oracle():
    aligned = score_response_pair(
        pair_kind="XI",
        base_interval=[0.2, 0.3],
        variant_interval=[0.5, 0.6],
        oracle_base_interval=[0.1, 0.2],
        oracle_variant_interval=[0.4, 0.5],
    )
    assert aligned["metric_family"] == "SRI"
    assert aligned["response_direction_matches_oracle"] is True
    assert aligned["response_vector_error_l1"] == pytest.approx(0.0)
    wrong = score_response_pair(
        pair_kind="XI",
        base_interval=[0.5, 0.6],
        variant_interval=[0.2, 0.3],
        oracle_base_interval=[0.1, 0.2],
        oracle_variant_interval=[0.4, 0.5],
    )
    assert wrong["response_direction"] == "OPPOSITE_DIRECTION"
    assert wrong["response_direction_matches_oracle"] is False


def test_dri_uses_explicit_x_xd_pair_and_detects_spurious_duplicate_response():
    result = score_response_pair(
        pair_kind="XD",
        base_interval=[0.2, 0.4],
        variant_interval=[0.3, 0.5],
        oracle_base_interval=[0.2, 0.4],
        oracle_variant_interval=[0.2, 0.4],
    )
    assert result["metric_family"] == "DRI"
    assert result["response_direction"] == "SPURIOUS_RESPONSE"
    assert result["response_amplitude_error"] == pytest.approx(0.2)


def test_failed_and_missing_method_outputs_remain_unscored_not_zero():
    failed = score_method_prefix(
        {"status": "TIMEOUT", "failure_code": "DEADLINE"},
        {"risk_interval": [0.2, 0.3], "admissible_actions": ["SAFE"]},
    )
    assert failed["scored"] is False
    assert failed["endpoint_l1"] is None
    invalid = score_method_prefix(
        {
            "status": "SUCCEEDED",
            "prediction": {"risk_interval": [float("nan"), 0.5]},
            "decision": {"admissible_actions": ["SAFE"]},
        },
        {"risk_interval": [0.2, 0.3], "admissible_actions": ["SAFE"]},
    )
    assert invalid["status"] == "INVALID_OUTPUT"
    assert invalid["endpoint_l1"] is None


def test_block_prefix_scorer_joins_only_on_prefix_and_keeps_missing_oracle_row():
    rows = score_block_prefixes(
        [{"prefix": 1, "risk_interval": [0.2, 0.3], "admissible_actions": ["SAFE"]}],
        [
            {
                "physical_block_id": "p1",
                "method_id": "B1",
                "prefix": 1,
                "status": "SUCCEEDED",
                "prediction": {"risk_interval": [0.2, 0.3]},
                "decision": {"admissible_actions": ["SAFE"]},
            },
            {
                "physical_block_id": "p1",
                "method_id": "B1",
                "prefix": 2,
                "status": "TIMEOUT",
            },
        ],
    )
    assert rows[0]["scored"] is True
    assert rows[1]["status"] == "ORACLE_UNAVAILABLE"
    assert rows[1]["endpoint_l1"] is None


def test_runner_scorer_reads_truth_only_after_outputs_and_scores_x_xd_xi():
    from rfb.research.mme_events import generate_block

    block = generate_block(
        {
            "block_id": "D_impl_unit_metrics",
            "duplicate_class": "distinct_key_same_acquisition",
            "equivalence_timing": "post_commit_short",
            "lifecycle": "merge",
            "independent_information": "one_new_root",
        },
        run_class="D_impl_unit",
    )
    oracle_intervals = {
        prefix.prefix_id: list(
            __import__("rfb.research.mme_oracle", fromlist=["evaluate_oracle"])
            .evaluate_oracle(prefix, block.truth_sidecar)
            .full_information.risk_interval
        )
        for prefix in block.prefixes
    }
    method_rows = {
        "M": {
            "terminal_state": "SUCCEEDED",
            "prefixes": [
                {
                    "prefix_id": prefix_id,
                    "status": "SUCCEEDED",
                    "output": {
                        "prediction": {"risk_interval": interval},
                        "decision": {"admissible_actions": ["ACT"]},
                    },
                }
                for prefix_id, interval in oracle_intervals.items()
            ],
            "resource_measurements": {"wall_time_seconds": 0.1},
        }
    }
    method_rows["M"]["_method_prefixes"] = list(block.prefixes)
    result = make_runner_scorer()(block.truth_sidecar, method_rows)
    assert result["block_id"] == "D_impl_unit_metrics"
    assert len(result["methods"]["M"]["prefix_scores"]) == len(block.prefixes)
    pairs = result["methods"]["M"]["response_pairs"]
    prefix_indices = len({prefix.prefix_index for prefix in block.prefixes})
    assert [row["metric_family"] for row in pairs] == ["DRI", "SRI"] * prefix_indices
    assert all(row["response_vector_error_l1"] == pytest.approx(0.0) for row in pairs)
    assert result["methods"]["M"]["recovery"]["applicable"] is True


def test_missing_base_prefix_keeps_every_dri_sri_opportunity_unavailable():
    from rfb.research.mme_events import generate_block

    block = generate_block(
        {
            "block_id": "D_impl_unit_missing_pair",
            "duplicate_class": "exact_retry",
            "equivalence_timing": "post_commit_short",
            "lifecycle": "merge",
            "independent_information": "one_new_root",
        },
        run_class="D_impl_unit",
    )
    rows = {
        "M": {
            "terminal_state": "FAILED",
            "prefixes": [],
            "_method_prefixes": list(block.prefixes),
        }
    }
    result = make_runner_scorer()(block.truth_sidecar, rows)["methods"]["M"]
    indices = len({prefix.prefix_index for prefix in block.prefixes})
    assert len(result["response_pairs"]) == indices * 2
    assert all(row["status"] == "UNAVAILABLE" for row in result["response_pairs"])
    assert len(result["prefix_scores"]) == len(block.prefixes)


def test_replay_control_does_not_start_recovery_obligation():
    from rfb.research.mme_events import generate_block

    block = generate_block(
        {
            "block_id": "D_impl_unit_replay_only",
            "duplicate_class": "exact_retry",
            "equivalence_timing": "pre_commit",
            "lifecycle": "replay",
            "independent_information": "zero_new_root",
        },
        run_class="D_impl_unit",
    )
    rows = {
        "M": {
            "terminal_state": "FAILED",
            "prefixes": [],
            "_method_prefixes": list(block.prefixes),
        }
    }
    recovery = make_runner_scorer()(block.truth_sidecar, rows)["methods"]["M"][
        "recovery"
    ]
    assert recovery["applicable"] is False
    assert recovery["reason"] == "NO_TRUTH_VALID_EFFECTIVE_DISCLOSURE"


def test_real_generated_block_all_methods_and_independent_oracle_score_cleanly():
    from rfb.research.mme_events import generate_block
    from rfb.research.mme_methods import RESEARCH_METHOD_IDS, evaluate_prefix

    block = generate_block(
        {
            "block_id": "D_impl_unit_real_panel",
            "duplicate_class": "distinct_key_same_acquisition",
            "equivalence_timing": "post_commit_short",
            "lifecycle": "merge",
            "independent_information": "one_new_root",
        },
        run_class="D_impl_unit",
    )
    method_rows = {
        method_id: {
            "terminal_state": "SUCCEEDED",
            "prefixes": [
                {
                    "prefix_id": prefix.prefix_id,
                    "status": "SUCCEEDED",
                    "output": evaluate_prefix(method_id, prefix.method_payload(), 20),
                }
                for prefix in block.prefixes
            ],
            "_method_prefixes": list(block.prefixes),
        }
        for method_id in RESEARCH_METHOD_IDS
    }
    result = make_runner_scorer()(block.truth_sidecar, method_rows)
    assert set(result["methods"]) == set(RESEARCH_METHOD_IDS)
    assert all(
        prefix_score["scored"] is True
        for method in result["methods"].values()
        for prefix_score in method["prefix_scores"]
    )
    for method_id, method in result["methods"].items():
        for prefix_score in method["prefix_scores"]:
            if method_id == "B5":
                assert prefix_score["belief_applicable"] is False
                assert prefix_score["belief_l1"] is None
            else:
                assert prefix_score["belief_applicable"] is True
                assert prefix_score["belief_l1"] is not None
