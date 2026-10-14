"""Prepared scorer. Physical oracle is never passed to the worker.

No science execution or independent recomputation has taken place.
"""
from independent_reference import event_errors


def score(output, oracle):
    summary = {}
    seen_keys = set()
    for row in output["rows"]:
        key = (row["trace"], row["prefix"], row["method"])
        if key in seen_keys:
            raise ValueError("duplicate result")
        seen_keys.add(key)
        truth = oracle["traces"][row["trace"]]
        result = row["result"]
        metrics = event_errors(result["cards"], result["possible"], truth["alarm_episodes"])
        # Alert requirement labels are not inferred from candidate risk output.
        physical_alert = any(reason != "handling_follow_up_only" for reason in result["notification_reasons"])
        metrics["missed_must_notify"] = row["prefix"] in truth["must_notify"] and not physical_alert
        metrics["physical_alert"] = physical_alert
        metrics["handling_only"] = "handling_follow_up_only" in result["notification_reasons"]
        metrics["unsafe_clear"] = result["risk"] == "SAFE"
        physical_danger = truth['risk'][row['prefix'] - 1] in ('EXPOSURE', 'EXPOSURE_HIGH')
        observable = row['prefix'] not in truth.get('unobservable_danger_prefixes', [])
        metrics['danger_truth_evaluable'] = observable
        metrics['danger_underassessment'] = observable and physical_danger and result['risk'] not in ('EXPOSURE', 'EXPOSURE_HIGH', 'CONFLICT_REVIEW')
        metrics['high_danger_missed'] = truth['risk'][row['prefix'] - 1] == 'EXPOSURE_HIGH' and result['risk'] != 'EXPOSURE_HIGH'
        metrics['unsupported_exposure'] = not truth['current_presence'][row['prefix'] - 1] and result['risk'] in ('EXPOSURE', 'EXPOSURE_HIGH')
        expected_conflict = truth.get('observed_same_target_conflict', [False] * 5)[row['prefix'] - 1]
        metrics['conflict_misresolved'] = expected_conflict and result['risk'] != 'CONFLICT_REVIEW'
        metrics['spurious_conflict'] = not expected_conflict and result['risk'] == 'CONFLICT_REVIEW'
        # Window matching in offline_evaluator determines true unmatched alerts.
        metrics['alert_outside_exact_required_prefix'] = physical_alert and row['prefix'] not in truth['must_notify']
        summary["%s/%d/%s" % key] = metrics
    if len(seen_keys) != 120:
        raise ValueError("incomplete 120-slot output")
    return {"status": "DEVELOPMENT_ONLY", "prefix_metrics": summary,
            "warning": "DS fusion has common event rules; no separate clustering superiority claim; no calibration or significance claim"}
