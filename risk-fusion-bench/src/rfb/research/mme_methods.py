"""MME v2 research method panel over public JSON prefixes.

The panel is intentionally distinct from :mod:`rfb.methods.registry`: adding
``ES-Rebuild`` here cannot alter the closed formal seven-arm API.  Proposed is
the real production :class:`LifecycleEngine`; the remaining methods are the
documented research adapters in :mod:`rfb.research.mme_baselines`.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from rfb.methods.lifecycle_engine import LifecycleEngine, project_snapshot

from .mme_baselines import BASELINE_SPECS, evaluate_baseline, validate_public_prefix


RESEARCH_METHOD_IDS = (
    "Proposed",
    "B1",
    "B2",
    "ES-Rebuild",
    "B0",
    "B3",
    "B4",
    "B5",
)


def _production_actions(public_prefix: Mapping[str, Any]) -> list[dict[str, Any]]:
    public_actions = public_prefix.get("actions")
    if public_actions is not None:
        if not isinstance(public_actions, list) or not public_actions:
            raise ValueError("public prefix actions must be a non-empty array")
        return [dict(row) for row in public_actions]
    events = public_prefix.get("events")
    controls = public_prefix.get("controls", [])
    if not isinstance(events, list) or not events or not isinstance(controls, list):
        raise ValueError("public prefix requires non-empty events and controls arrays")
    actions: list[dict[str, Any]] = []
    for index, row in enumerate(events):
        if not isinstance(row, Mapping):
            raise ValueError("event rows must be JSON objects")
        actions.append(
            {
                "action_id": str(row.get("event_id", f"event-{index}")),
                "op": "INITIALIZE",
                "order": row.get("order", index),
                "message_id": row.get("message_id"),
                "version": row.get("version"),
                "root_id": row.get("root_id"),
                "support": row.get("support"),
                "reliability": row.get("reliability", 1.0),
            }
        )
    for index, row in enumerate(controls):
        if not isinstance(row, Mapping):
            raise ValueError("control rows must be JSON objects")
        action: dict[str, Any] = {
            "action_id": str(row.get("control_id", f"control-{index}")),
            "op": str(row.get("kind", row.get("op", ""))).upper(),
            "order": row.get("order", index),
            "roots": list(row.get("roots", [])),
        }
        if row.get("canonical_root") is not None:
            action["canonical_root"] = row["canonical_root"]
        if row.get("replacement_root") is not None:
            action["replacement_root"] = row["replacement_root"]
        actions.append(action)
    return sorted(
        actions,
        key=lambda row: (
            int(row["order"]),
            1 if row["op"] == "INITIALIZE" else 0,
            str(row["action_id"]),
        ),
    )


def _action_state(lower: float) -> str:
    return "ACT" if lower >= 0.70 else "REVIEW"


def _proposed(
    public_prefix: Mapping[str, Any], cap: int | Mapping[str, Any] | None
) -> dict[str, Any]:
    if cap is None:
        cap = public_prefix.get("method_cap", 1_000_000)
    if isinstance(cap, bool):
        raise ValueError("cap must be positive")
    if isinstance(cap, int):
        active, budget, deadline = cap, float(cap), None
    elif isinstance(cap, Mapping):
        active = cap.get("max_active_contributions", cap.get("active", 1_000_000))
        budget = cap.get("max_contribution_budget", cap.get("budget", 1_000_000.0))
        deadline = cap.get("deadline_ns")
    else:
        raise TypeError("cap must be an integer or mapping")
    engine = LifecycleEngine(
        max_active_contributions=int(active), max_contribution_budget=float(budget)
    )
    actions = _production_actions(public_prefix)
    started = time.perf_counter_ns()
    for action in actions:
        engine.apply(action)
    elapsed = time.perf_counter_ns() - started
    snapshot = project_snapshot(engine.snapshot)
    if deadline is not None and time.perf_counter_ns() > int(deadline):
        status, failure, interval, action_state = (
            "FAILED",
            "DEADLINE_EXCEEDED",
            None,
            "NO_ACTION",
        )
    elif snapshot["status"] == "SAFE_HALT":
        status, failure, interval, action_state = (
            "FAILED",
            snapshot["failure_code"],
            None,
            "NO_ACTION",
        )
    else:
        support = round(float(snapshot["risk_score"]), 12)
        status, failure, interval, action_state = (
            "SUCCEEDED",
            None,
            [support, 1.0],
            _action_state(support),
        )
    result: dict[str, Any] = {
        "method_id": "Proposed",
        "status": status,
        "risk_interval": interval,
        "action_state": action_state,
        "failure_code": failure,
        "evidence_count": len(public_prefix.get("events", [])),
        "active_contribution_count": len(snapshot["audit_classes"]),
        "duplicate_count": snapshot["duplicate_count"],
        "cost": {
            "elapsed_ns": elapsed,
            "recomputed_action_count": snapshot["rebuild_count"],
        },
    }
    if interval is not None:
        support = interval[0]
        result["bpa"] = {
            "frame": ["RISK", "NOT_RISK"],
            "focal_sets": [["RISK"], ["RISK", "NOT_RISK"]],
            "masses": [support, round(1.0 - support, 12)],
        }
    return result


def evaluate_prefix(
    method_id: str,
    public_prefix: Mapping[str, Any],
    cap: int | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if method_id == "Proposed":
        validate_public_prefix(public_prefix)
        return _proposed(public_prefix, cap)
    if method_id not in BASELINE_SPECS:
        raise ValueError(f"unknown research method_id {method_id!r}")
    return evaluate_baseline(method_id, public_prefix, cap)


def run_panel(
    public_prefix: Mapping[str, Any],
    cap: int | Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        method_id: evaluate_prefix(method_id, public_prefix, cap)
        for method_id in RESEARCH_METHOD_IDS
    }


def method_panel_document() -> dict[str, Any]:
    methods = []
    for method_id in RESEARCH_METHOD_IDS:
        if method_id == "Proposed":
            methods.append(
                {
                    "method_id": method_id,
                    "rule": "production_lifecycle_engine",
                    "proxy_scope": "real LifecycleEngine over public actions",
                    "parameters": {},
                    "output_type": "binary_simple_support_belief_plausibility",
                }
            )
        else:
            spec = BASELINE_SPECS[method_id]
            methods.append(
                {
                    "method_id": spec.method_id,
                    "rule": spec.rule,
                    "proxy_scope": spec.proxy_scope,
                    "parameters": dict(spec.parameters),
                    "output_type": spec.output_type,
                }
            )
    return {"schema_version": "mme-method-panel.v2", "closed": True, "methods": methods}


def run_mme_method(
    method_id: str,
    public_prefix: Mapping[str, Any],
    cap: int | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return evaluate_prefix(method_id, public_prefix, cap)


__all__ = [
    "RESEARCH_METHOD_IDS",
    "evaluate_prefix",
    "method_panel_document",
    "run_mme_method",
    "run_panel",
]
