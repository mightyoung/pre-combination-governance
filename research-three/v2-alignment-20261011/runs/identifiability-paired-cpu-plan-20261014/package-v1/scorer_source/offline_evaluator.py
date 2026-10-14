"""Static result/reference wiring. No workers, network, subprocess or method imports.

Consumes saved output after a future qualified worker. Not executed yet.
Identifiability: 102 reference bundles: 30 physical + 60 DS + 12 terminal.
With 6 gate tests and 120 method-prefix bundles: 228 total.
"""
from independent_reference import ds_reference, TERMINAL_REFERENCE, check_terminal
from scoring import score
import json
from pathlib import Path
BOUNDARY_TERMINAL = json.loads((Path(__file__).parent / "terminal-reference.json").read_text())


def public_motion_groups(prefix):
    # Independent input selection: each acquisition's latest received physical
    # instance, then only current physical time per asset and usable quality.
    current, rows = {}, {}
    for r in prefix:
        if r["target"] != "motion":
            continue
        current[r["asset"]] = max(current.get(r["asset"], -1), r["source_time"])
        key = (r["asset"], r["acquisition"])
        rank = (r["source_time"], r["confirmed_time"])
        if key not in rows or rank > rows[key][0]:
            rows[key] = (rank, r)
    groups = {}
    for _, r in rows.values():
        if r["source_time"] != current[r["asset"]] or r["quality"] != "GOOD":
            continue
        if not 0 <= len(prefix) - 1 - r["confirmed_time"] <= 2:
            continue
        groups.setdefault("%s@%s" % (r["asset"], r["source_time"]), []).append(r["value"])
    return groups


def evaluate_saved(public, oracle, output, prior_evaluations):
    if prior_evaluations != 126 or output["method_invocations"] != 120:
        raise ValueError("require receipts for exactly 6 tests and 120 methods")
    if len(output["rows"]) != 120:
        raise ValueError("incomplete output")
    by_key = {(r["trace"], r["prefix"], r["method"]): r["result"] for r in output["rows"]}
    if len(by_key) != 120:
        raise ValueError("duplicate output")
    reference_count, checks, ds_asset_groups = 0, [], 0
    for trace in public["traces"]:
        name = trace["id"]
        for n in range(1, 6):
            expected_ids = {r['id'] for r in trace['rows'][:n] if r['alarm']}
            for method in ('M0', 'M1', 'M2', 'M3'):
                if set(by_key[(name, n, method)]['cards']) != expected_ids:
                    raise ValueError('missing/extra public alarm cards: %s/%d/%s' % (name, n, method))
            for method in ("M2", "M3"):
                reference_count += 1
                expected = {}
                for key, values in public_motion_groups(trace["rows"][:n]).items():
                    ds_asset_groups += 1
                    expected[key] = ds_reference(values, method == "M2")
                actual = by_key[(name, n, method)]
                checks.append(dict(trace=name, prefix=n, method=method,
                                   ds_reference_match=actual["fused"] == expected,
                                   common_cards_match=actual["cards"] == by_key[(name, n, "M1")]["cards"]))
            if n == 5:
                for method in ("M0", "M1"):
                    reference_count += 1
                    checks.append(dict(trace=name, prefix=n, method=method,
                                       terminal_reference_match=check_terminal(by_key[(name, n, method)]["cards"], BOUNDARY_TERMINAL[name][method])))
    first_alert_checks = []
    for trace in public['traces']:
        name = trace['id']
        for method in ('M0', 'M1', 'M2', 'M3'):
            actual = [n for n in range(1, 6) if 'new_event_first_alert' in by_key[(name,n,method)]['notification_reasons']]
            required = oracle['traces'][name]['must_first_alert']
            first_alert_checks.append({'trace':name,'method':method,'required':required,'actual':actual,
                                       'missed_at_required_prefix': [n for n in required if n not in actual],
                                       'extra_at_nonrequired_prefix':[n for n in actual if n not in required],
                                       'logical_delays':[None if not any(n<=a<(required[i+1] if i+1<len(required) else 6) for a in actual)
                                                        else min(a-n for a in actual if n<=a<(required[i+1] if i+1<len(required) else 6))
                                                        for i,n in enumerate(required)]})
    # One oracle prefix bundle evaluates the four methods' metric records.
    reference_count += 30
    if reference_count != 102 or prior_evaluations + reference_count > 240:
        raise RuntimeError("reference budget")
    metrics = score(output, oracle)
    delay_checks = []
    for trace in public["traces"]:
        name = trace["id"]
        required = oracle["traces"][name]["must_notify"]
        for method in ("M0", "M1", "M2", "M3"):
            available = [n for n in range(1, 6) if any(x != "handling_follow_up_only" for x in by_key[(name, n, method)]["notification_reasons"])]
            matched = set()
            for index, start in enumerate(required):
                end = required[index + 1] if index + 1 < len(required) else 6
                hits = [n for n in available if start <= n < end]
                if hits:
                    matched.add(min(hits))
                delay_checks.append(dict(trace=name, method=method, required_prefix=start,
                                         receipt_prefix_delay=None if not hits else min(hits) - start,
                                         missed=not hits))
            delay_checks.append(dict(trace=name, method=method, unmatched_alert_prefixes=[n for n in available if n not in matched]))
    return dict(status="DEVELOPMENT_ONLY", reference_bundles=reference_count,
                ds_inner_asset_groups=ds_asset_groups, total_evaluations=228,
                checks=checks, metrics=metrics, delay_checks=delay_checks, first_alert_checks=first_alert_checks,
                first_alert_acceptance=all(not r['missed_at_required_prefix'] and not r['extra_at_nonrequired_prefix']
                                           and all(d == 0 for d in r['logical_delays']) for r in first_alert_checks),
                first_alert_acceptance_scope='exact required prefixes, no extras, zero logical delay; window delays are diagnostic only',
                physical_notification_acceptance=not any(
                    r.get('missed', False) or r.get('unmatched_alert_prefixes') for r in delay_checks),
                physical_misses=[r for r in delay_checks if r.get('missed', False)],
                review_notifications=[{'trace': r['trace'], 'prefix': r['prefix'], 'method': r['method'],
                                       'reasons': r['result']['review_notification_reasons']}
                                      for r in output['rows'] if r['result']['review_notification_reasons']],
                delay_scope="logical receipt-prefix delay only; no physical wall delay inference")


if __name__ == "__main__":
    raise SystemExit("STATIC ONLY: no qualified saved science output exists")
