import copy

from rfb.research.mme_conclusion import evaluate_conclusion


def _inputs():
    panel = ["Proposed", "B1", "B2", "ES-Rebuild", "B0", "B3", "B4", "B5"]
    blocks = [f"P{x:02d}" for x in range(1, 7)]
    metrics = ["endpoint_l1", "recovery_mean_endpoint_l1"]
    protocol = {
        "method_order": panel,
        "analysis_policy": {
            "eligible_primary_block_ids": blocks,
            "primary_comparators": ["B1", "B2"],
            "primary_metric_keys": metrics,
            "minimum_improved_blocks": 4,
            "equality_tolerance": 1e-12,
        },
    }
    rows = [
        {
            "physical_block_id": block,
            "method_id": method,
            "status": "SUCCEEDED",
            **{
                metric: (0.1 if method in {"Proposed", "ES-Rebuild"} else 0.2)
                for metric in metrics
            },
        }
        for block in blocks
        for method in panel
    ]
    return {"method_rows": rows}, protocol


def test_support_does_not_imply_unique_gain_over_equal_strong_baseline():
    report, protocol = _inputs()
    result = evaluate_conclusion(report, protocol)
    assert result["status"] == "MECHANISM_SUPPORTED"
    assert result["unique_increment_over_es_rebuild"] == "NOT_ESTABLISHED_TIE"
    assert result["confirmatory"] is False


def test_missing_failed_or_nan_primary_evidence_is_not_dropped():
    report, protocol = _inputs()
    for mutate in (
        lambda rows: rows.pop(0),
        lambda rows: rows[0].update(status="FAILED"),
        lambda rows: rows[0].update(endpoint_l1=float("nan")),
    ):
        changed = copy.deepcopy(report)
        mutate(changed["method_rows"])
        assert (
            evaluate_conclusion(changed, protocol)["status"] == "EVIDENCE_INSUFFICIENT"
        )


def test_ties_and_worse_results_are_valid_unsupported_findings():
    report, protocol = _inputs()
    for row in report["method_rows"]:
        if row["method_id"] == "Proposed":
            row["endpoint_l1"] = 0.3
    assert evaluate_conclusion(report, protocol)["status"] == "MECHANISM_UNSUPPORTED"
