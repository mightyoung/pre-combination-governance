"""Execute the frozen L01-L24 lifecycle qualification assertions."""

from __future__ import annotations

from typing import Any

from rfb.methods.lifecycle_engine import (
    CasRevisionConflict,
    LifecycleEngine,
    PostCommitCrash,
    PreCommitCrash,
)

from .lifecycle_properties import PROPERTY_IDS, build_frozen_corpus


def _clean(action: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in action.items() if key != "fault"}


def _execute_trace(trace: dict[str, Any]) -> dict[str, Any]:
    engine = LifecycleEngine(
        max_active_contributions=trace["cap"],
        max_contribution_budget=trace["budget"],
    )
    checkpoints = {}
    for action in trace["actions"]:
        fault = action.get("fault")
        before = engine.snapshot
        if fault == "PRE_COMMIT_CRASH":
            try:
                engine.apply(action)
            except PreCommitCrash:
                pass
            else:
                raise AssertionError("precommit crash did not fire")
            if engine.snapshot is not before:
                raise AssertionError("precommit crash committed state")
            engine.apply(_clean(action))
        elif fault == "POST_COMMIT_CRASH":
            try:
                engine.apply(action)
            except PostCommitCrash:
                pass
            else:
                raise AssertionError("postcommit crash did not fire")
            engine = LifecycleEngine.recover(engine.snapshot)
            engine.apply(_clean(action))
        elif fault == "CAS_CONFLICT":
            try:
                engine.apply(action, expected_revision=before.revision + 1)
            except CasRevisionConflict:
                pass
            else:
                raise AssertionError("CAS conflict did not fire")
            if engine.snapshot is not before:
                raise AssertionError("CAS loser committed state")
            engine.apply(_clean(action), expected_revision=before.revision)
        else:
            engine.apply(action)
        checkpoints[action["action_id"]] = engine.snapshot
    return checkpoints


def execute_l01_l24() -> dict[str, Any]:
    corpus = build_frozen_corpus()
    traces = {row["scenario"]: row for row in corpus["traces"]}
    states = {name: _execute_trace(trace) for name, trace in traces.items()}
    d, p, m = (
        states["duplicate_alias"],
        states["precommit_equivalence"],
        states["post_commit_merge"],
    )
    s, v = states["supersede_retire_replay"], states["out_of_order_versions"]
    n, c = states["non_min_canonical"], states["crash_cas"]
    h, b, x = (
        states["cap_boundary"],
        states["budget_boundary"],
        states["explicit_safe_halt"],
    )
    checks = {
        "L01": len(p["p-3"].classes) == 1,
        "L02": d["d-2"].duplicate_count == 1 and d["d-2"].processing_spend == 1,
        "L03": p["p-1"].rebuild_count == 0,
        "L04": m["m-3"].rebuild_count == 1 and len(m["m-3"].classes) == 1,
        "L05": dict(s["s-3"].root_lifecycle).get("sr1") == "SUPERSEDED",
        "L06": not s["s-4"].effective_versions and not s["s-4"].classes,
        "L07": s["s-5"].replay_current,
        "L08": x["x-2"].availability == "UNAVAILABLE" and x["x-2"].gate == "CLOSED",
        "L09": dict(v["v-2"].audit_effective_versions).get("vr") == 3,
        "L10": v["v-2"].stale_count >= 1,
        "L11": n["n-3"].classes[0].canonical_root == "z-root",
        "L12": c["c-1"].revision == 1,
        "L13": c["c-2"].duplicate_count == 1,
        "L14": c["c-3"].revision == 4,
        "L15": h["h-1"].status == "RUNNING",
        "L16": h["h-2"].failure_code == "ACTIVE_CONTRIBUTION_CAP",
        "L17": b["b-1"].contribution_budget == 1.0,
        "L18": b["b-2"].failure_code == "CONTRIBUTION_BUDGET_CAP",
        "L19": LifecycleEngine.recover(m["m-2"]).snapshot == m["m-2"],
        "L20": d["d-3"].processing_spend == 2.0,
        "L21": x["x-2"].risk_score is None,
        "L22": m["m-2"].scientific_binding != m["m-3"].scientific_binding,
        "L23": m["m-3"].ledger[-1].previous_hash == m["m-2"].ledger_head,
    }
    invalid = corpus["invalid_traces"][0]["actions"][0]
    invalid_engine = LifecycleEngine()
    try:
        invalid_engine.apply(invalid)
    except ValueError:
        checks["L24"] = invalid_engine.snapshot.revision == 0
    else:
        checks["L24"] = False
    if tuple(sorted(checks)) != PROPERTY_IDS:
        raise AssertionError("qualification assertion set is not L01-L24")
    results = {
        property_id: {
            "status": "PASS" if passed else "FAIL",
            "assertion_id": corpus["coverage_certificate"]["properties"][property_id][
                0
            ]["assertion_id"],
        }
        for property_id, passed in checks.items()
    }
    return {
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "results": results,
        "complete": all(row["status"] == "PASS" for row in results.values()),
    }


__all__ = ["execute_l01_l24"]
