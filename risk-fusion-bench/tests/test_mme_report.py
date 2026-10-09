from __future__ import annotations

import csv
import json

import pytest

from rfb.research.mme_report import (
    build_mme_report,
    build_report_from_run_result,
    write_mme_report,
)


def sample_rows():
    return [
        {
            "physical_block_id": "p1",
            "method_id": "B1",
            "status": "SUCCEEDED",
            "endpoint_l1": 0.4,
            "prefix": 2,
            "curve_kind": "recovery",
            "curve_value": 0.4,
            "wall_time_seconds": 2.0,
            "peak_memory_bytes": 100,
            "platform": "test",
            "resource_samples": 3,
        },
        {
            "physical_block_id": "p1",
            "method_id": "Proposed",
            "status": "SUCCEEDED",
            "endpoint_l1": 0.2,
            "prefix": 2,
            "curve_kind": "recovery",
            "curve_value": 0.2,
            "wall_time_seconds": 3.0,
            "peak_memory_bytes": 120,
            "platform": "test",
            "resource_samples": 3,
        },
        {
            "physical_block_id": "p2",
            "method_id": "B1",
            "status": "TIMEOUT",
            "failure_code": "DEADLINE",
            "endpoint_l1": None,
            "wall_time_seconds": 5.0,
            "peak_memory_bytes": 110,
        },
        {
            "physical_block_id": "p2",
            "method_id": "Proposed",
            "status": "SUCCEEDED",
            "endpoint_l1": 0.3,
            "wall_time_seconds": 4.0,
            "peak_memory_bytes": 130,
        },
    ]


def test_report_counts_physical_blocks_and_keeps_all_terminal_rows_and_failures():
    report = build_mme_report(sample_rows(), expected_methods=("B1", "Proposed"))
    assert report["independent_physical_blocks_n"] == 2
    assert report["method_rows_n"] == 4
    assert report["significance_testing_performed"] is False
    assert report["superiority_claim_permitted"] is False
    assert report["boundary_failures"] == [
        {
            "physical_block_id": "p2",
            "method_id": "B1",
            "status": "TIMEOUT",
            "failure_code": "DEADLINE",
            "failure_kind": "IMPLEMENTATION_FAILURE",
        }
    ]
    endpoint_pairs = [
        row for row in report["paired_effects"] if row["metric"] == "endpoint_l1"
    ]
    assert endpoint_pairs[0]["paired_difference"] == pytest.approx(-0.2)
    assert endpoint_pairs[1]["pair_status"] == "UNAVAILABLE"
    counts = next(
        row
        for row in report["effect_direction_counts"]
        if row["metric"] == "endpoint_l1"
    )
    assert counts["physical_blocks_total"] == 2
    assert counts["paired_blocks"] == 1
    assert counts["proposed_lower"] == 1
    assert counts["unavailable"] == 1


def test_report_rejects_pseudoreplication_and_more_than_27_blocks():
    duplicate = sample_rows() + [dict(sample_rows()[0])]
    with pytest.raises(ValueError, match="duplicate"):
        build_mme_report(duplicate, expected_methods=("B1", "Proposed"))
    rows = [
        {
            "physical_block_id": f"p{index}",
            "method_id": "Proposed",
            "status": "SUCCEEDED",
        }
        for index in range(28)
    ]
    with pytest.raises(ValueError, match="exceeds"):
        build_mme_report(rows)


def test_report_writes_full_csv_tables_including_resources_and_denominators(tmp_path):
    report = build_mme_report(sample_rows(), expected_methods=("B1", "Proposed"))
    paths = write_mme_report(report, tmp_path)
    assert set(paths) == {
        "report",
        "method_rows",
        "paired_effects",
        "effect_direction_counts",
        "mechanism_curves",
        "boundary_failures",
        "resources",
        "applicability_denominators",
    }
    loaded = json.loads(paths["report"].read_text(encoding="utf-8"))
    assert loaded["independent_physical_blocks_n"] == 2
    with paths["resources"].open(encoding="utf-8", newline="") as handle:
        resources = list(csv.DictReader(handle))
    assert len(resources) == 4
    with paths["applicability_denominators"].open(
        encoding="utf-8", newline=""
    ) as handle:
        denominators = list(csv.DictReader(handle))
    assert any(
        row["metric"] == "endpoint_l1" and row["method_id"] == "B1"
        for row in denominators
    )
    with pytest.raises(FileExistsError):
        write_mme_report(report, tmp_path)


def test_report_assembles_directly_from_runner_result_without_counting_prefixes_as_n():
    run_result = {
        "run_id": "run-1",
        "attempt_id": "attempt-0001",
        "run_class": "D_impl_unit",
        "blocks": [
            {
                "block_id": "p1",
                "scoring": {
                    "methods": {
                        method_id: {
                            "terminal_state": "SUCCEEDED",
                            "prefix_scores": [
                                {
                                    "prefix_id": "X:0",
                                    "status": "SUCCEEDED",
                                    "scored": True,
                                    "endpoint_l1": value,
                                    "false_block": False,
                                    "available": True,
                                    "action_set_disagreement": False,
                                },
                                {
                                    "prefix_id": "X:1",
                                    "status": "SUCCEEDED",
                                    "scored": True,
                                    "endpoint_l1": value,
                                    "false_block": False,
                                    "available": True,
                                    "action_set_disagreement": False,
                                },
                            ],
                            "response_pairs": [
                                {
                                    "metric_family": "DRI",
                                    "response_vector_error_l1": value,
                                    "response_direction_matches_oracle": True,
                                }
                            ],
                            "recovery": {
                                "applicable": True,
                                "mean_endpoint_l1": value,
                            },
                            "resource_measurements": [
                                {
                                    "prefix_id": "X:0",
                                    "wall_seconds": 0.1,
                                    "peak_rss_bytes": 100,
                                    "platform": "test",
                                }
                            ],
                        }
                        for method_id, value in (("B1", 0.4), ("Proposed", 0.2))
                    }
                },
            }
        ],
    }
    report = build_report_from_run_result(run_result)
    assert report["independent_physical_blocks_n"] == 1
    assert report["method_rows_n"] == 8
    assert len(report["mechanism_curves"]) == 4
    assert report["method_rows"][0]["resource_samples"] == 1
    assert report["method_rows"][0]["scored_prefixes"] == 2
    assert report["method_rows"][0]["partial_prefixes"] is False
    assert report["method_rows"][0]["recovery_endpoint_l1"] == pytest.approx(0.4)
    assert sum(row["status"] == "MISSING" for row in report["method_rows"]) == 6
