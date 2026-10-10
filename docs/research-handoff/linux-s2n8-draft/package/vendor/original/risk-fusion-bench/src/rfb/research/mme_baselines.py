"""Research-only MME baselines evaluated on public event prefixes.

These adapters deliberately do not use the formal method registry.  B0--B5
retain the frozen formulas of the formal panel while exposing a prefix-level
research contract.  ``ES-Rebuild`` is a separate, strong event-sourced
baseline: it reconstructs version, equivalence, supersede and retirement state
from the public actions on every call.  It does not import the production
lifecycle engine, its ledger, or any oracle implementation.

Proxy scope is explicit:

* B0 is naive noisy-OR over every public event.
* B1 adds exact ``(message_id, version)`` retry suppression only.
* B2 adds declared lineage/ancestry elimination only.  It is a transparent
  proxy, not a claim of a complete PRIMEX-PEV reproduction; when the public
  generator supplies no lineage declarations it has no extra equivalence
  information beyond B1.
* B3 is the cautious binary-simple-support proxy (maximum root support).
* B4 is the frozen strong-neighbour interpolation with rho=0.70; it is not
  tuned from MME outcomes.
* B5 is the Frechet unknown-correlation interval over one event per public
  root.  It is an interval proxy and therefore emits no fabricated BPA.
* ES-Rebuild applies only explicit public lifecycle controls and recomputes
  from scratch.  It makes no claim to cover undisclosed equivalence or general
  conflicting focal sets.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


BASELINE_METHOD_IDS = ("B0", "B1", "B2", "B3", "B4", "B5", "ES-Rebuild")
B4_DEPENDENCE = 0.70
B4_NEIGHBOR_WEIGHT = 0.30
_FORBIDDEN = ("truth", "sidecar", "oracle", "physical_root")


@dataclass(frozen=True, slots=True)
class BaselineSpec:
    method_id: str
    rule: str
    proxy_scope: str
    parameters: Mapping[str, Any]
    output_type: str


BASELINE_SPECS: Mapping[str, BaselineSpec] = {
    "B0": BaselineSpec(
        "B0",
        "naive_noisy_or",
        "all public events; no retry, lineage, or lifecycle correction",
        {},
        "binary_simple_support_belief_plausibility",
    ),
    "B1": BaselineSpec(
        "B1",
        "transport_exactly_once",
        "identical (message_id, version) retries only",
        {"dedupe_key": ["message_id", "version"]},
        "binary_simple_support_belief_plausibility",
    ),
    "B2": BaselineSpec(
        "B2",
        "declared_lineage_ancestor_elimination",
        "declared lineage only; proxy, not complete PRIMEX-PEV reproduction",
        {"undeclared_equivalence": "unavailable"},
        "binary_simple_support_belief_plausibility",
    ),
    "B3": BaselineSpec(
        "B3",
        "cautious_maximum_root_support",
        "binary simple-support cautious proxy",
        {},
        "binary_simple_support_belief_plausibility",
    ),
    "B4": BaselineSpec(
        "B4",
        "partial_dependence_strong_neighbour",
        "fixed ER/TLD-family interpolation proxy; no conflict-coverage claim",
        {"dependence": B4_DEPENDENCE, "neighbor_weight": B4_NEIGHBOR_WEIGHT},
        "binary_simple_support_belief_plausibility",
    ),
    "B5": BaselineSpec(
        "B5",
        "frechet_unknown_correlation",
        "one strongest public event per root; unknown-correlation bounds",
        {"lower": "max", "upper": "min(1,sum)"},
        "risk_interval_only",
    ),
    "ES-Rebuild": BaselineSpec(
        "ES-Rebuild",
        "public_event_sourced_full_rebuild",
        "explicit public versions/equivalence/supersede/retire; full replay",
        {"rebuild": "every_prefix", "oracle_access": False},
        "binary_simple_support_belief_plausibility",
    ),
}


@dataclass(frozen=True, slots=True)
class _Limits:
    active: int
    budget: float
    deadline_ns: int | None


def _limits(cap: int | Mapping[str, Any]) -> _Limits:
    if isinstance(cap, bool):
        raise ValueError("cap must be a positive integer or mapping")
    if isinstance(cap, int):
        active, budget, deadline = cap, float(cap), None
    elif isinstance(cap, Mapping):
        active = cap.get("max_active_contributions", cap.get("active", 1_000_000))
        budget = cap.get("max_contribution_budget", cap.get("budget", 1_000_000.0))
        deadline = cap.get("deadline_ns")
    else:
        raise TypeError("cap must be a positive integer or mapping")
    if isinstance(active, bool) or not isinstance(active, int) or active < 1:
        raise ValueError("max_active_contributions must be positive")
    if isinstance(budget, bool) or not isinstance(budget, (int, float)):
        raise ValueError("max_contribution_budget must be numeric")
    budget = float(budget)
    if not math.isfinite(budget) or budget < 0:
        raise ValueError("max_contribution_budget must be finite and non-negative")
    if deadline is not None and (
        isinstance(deadline, bool) or not isinstance(deadline, int) or deadline < 0
    ):
        raise ValueError("deadline_ns must be a non-negative monotonic timestamp")
    return _Limits(active, budget, deadline)


def _reject_private(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path}: JSON object keys must be strings")
            if any(token in key.casefold() for token in _FORBIDDEN):
                raise ValueError(f"{path}.{key}: private scorer field is forbidden")
            _reject_private(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_private(child, f"{path}[{index}]")
    elif value is not None and not isinstance(value, (str, bool, int, float)):
        raise ValueError(f"{path}: method prefix must contain JSON values only")


def validate_public_prefix(
    prefix: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(prefix, Mapping):
        raise TypeError("public_prefix must be a JSON object")
    _reject_private(prefix)
    events, controls = prefix.get("events"), prefix.get("controls")
    actions = prefix.get("actions")
    if actions is not None and not isinstance(actions, list):
        raise ValueError("public prefix actions must be an array")
    if events is None and isinstance(actions, list):
        events = [row for row in actions if row.get("op") == "INITIALIZE"]
    if controls is None and isinstance(actions, list):
        controls = [
            {**row, "kind": row["op"]}
            for row in actions
            if row.get("op") != "INITIALIZE"
        ]
    if controls is None:
        controls = []
    if not isinstance(events, list) or not events or not isinstance(controls, list):
        raise ValueError("public prefix requires non-empty events and controls arrays")
    if actions is not None and "events" in prefix and "controls" in prefix:
        projected: list[dict[str, Any]] = []
        for event in events:
            projected.append(
                {
                    "action_id": event["event_id"],
                    "op": "INITIALIZE",
                    "order": event["order"],
                    "message_id": event["message_id"],
                    "version": event["version"],
                    "root_id": event["root_id"],
                    "support": event["support"],
                    "reliability": event.get("reliability", 1.0),
                }
            )
        for control in controls:
            action: dict[str, Any] = {
                "action_id": control["control_id"],
                "op": control["kind"],
                "order": control["order"],
                "roots": control["roots"],
            }
            if control.get("canonical_root") is not None:
                action["canonical_root"] = control["canonical_root"]
            if control.get("replacement_root") is not None:
                action["replacement_root"] = control["replacement_root"]
            projected.append(action)
        projected.sort(
            key=lambda row: (
                int(row["order"]),
                1 if row["op"] == "INITIALIZE" else 0,
                str(row["action_id"]),
            )
        )
        if actions != projected:
            raise ValueError("public actions projection differs from events/controls")
    return [dict(row) for row in events], [dict(row) for row in controls]


def _probability(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")
    return result


def _support(row: Mapping[str, Any]) -> float:
    return _probability(row.get("support"), "support") * _probability(
        row.get("reliability", 1.0), "reliability"
    )


def _event_key(row: Mapping[str, Any]) -> tuple[int, str, int, str]:
    return (
        int(row.get("order", 0)),
        str(row.get("message_id", "")),
        int(row.get("version", 1)),
        str(row.get("root_id", "")),
    )


def _event_signature(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(row.get("root_id", "")),
        _support(row),
        tuple(row.get("lineage", ())),
        tuple(row.get("derived_from", ())),
    )


def _exactly_once(events: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    seen: dict[tuple[str, int], tuple[Any, ...]] = {}
    retained: list[dict[str, Any]] = []
    duplicates = 0
    for row in sorted(events, key=_event_key):
        message, version, root = (
            row.get("message_id"),
            row.get("version"),
            row.get("root_id"),
        )
        if (
            not isinstance(message, str)
            or not message
            or not isinstance(root, str)
            or not root
        ):
            raise ValueError("public event requires message_id and root_id")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError("public event version must be a positive integer")
        key = (message, version)
        signature = _event_signature(row)
        if key not in seen:
            seen[key] = signature
            retained.append(row)
        elif seen[key] == signature:
            duplicates += 1
        else:
            raise ValueError("same message_id/version has different public content")
    return retained, duplicates


def _noisy_or(values: Sequence[float]) -> float:
    return 1.0 - math.prod(1.0 - value for value in values)


def _strongest_per_root(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for row in sorted(events, key=_event_key):
        root = str(row["root_id"])
        previous = selected.get(root)
        if previous is None or (
            _support(row),
            int(row["version"]),
            str(row["message_id"]),
        ) > (_support(previous), int(previous["version"]), str(previous["message_id"])):
            selected[root] = row
    return [selected[root] for root in sorted(selected)]


def _action_state(lower: float) -> str:
    return "ACT" if lower >= 0.70 else "REVIEW"


def _simple_support_bpa(support: float) -> dict[str, Any]:
    support = round(support, 12)
    return {
        "frame": ["RISK", "NOT_RISK"],
        "focal_sets": [["RISK"], ["RISK", "NOT_RISK"]],
        "masses": [support, round(1.0 - support, 12)],
    }


def _result(
    method_id: str,
    lower: float,
    upper: float,
    *,
    evidence_count: int,
    active_count: int,
    duplicate_count: int,
    elapsed_ns: int,
    recomputed_actions: int = 0,
    bpa_support: float | None = None,
) -> dict[str, Any]:
    lower, upper = round(lower, 12), round(upper, 12)
    result: dict[str, Any] = {
        "method_id": method_id,
        "status": "SUCCEEDED",
        "risk_interval": [lower, upper],
        "action_state": _action_state(lower),
        "failure_code": None,
        "evidence_count": evidence_count,
        "active_contribution_count": active_count,
        "duplicate_count": duplicate_count,
        "cost": {
            "elapsed_ns": elapsed_ns,
            "recomputed_action_count": recomputed_actions,
        },
    }
    if bpa_support is not None:
        result["bpa"] = _simple_support_bpa(bpa_support)
    return result


def _failed(method_id: str, code: str, elapsed_ns: int, actions: int) -> dict[str, Any]:
    return {
        "method_id": method_id,
        "status": "FAILED",
        "risk_interval": None,
        "action_state": "NO_ACTION",
        "failure_code": code,
        "evidence_count": 0,
        "active_contribution_count": 0,
        "duplicate_count": 0,
        "cost": {"elapsed_ns": elapsed_ns, "recomputed_action_count": actions},
    }


def _ordinary(
    method_id: str,
    events: list[dict[str, Any]],
) -> tuple[float, float, int, int, int, float | None]:
    duplicates = 0
    if method_id == "B0":
        retained = sorted(events, key=_event_key)
        support = _noisy_or([_support(row) for row in retained])
        return support, 1.0, len(retained), len(retained), 0, support
    if method_id in {"B1", "B2"}:
        retained, duplicates = _exactly_once(events)
    else:
        retained = sorted(events, key=_event_key)
    if method_id == "B2":
        ancestors: set[str] = set()
        for row in retained:
            ancestors.update(str(item) for item in row.get("derived_from", ()))
            lineage = tuple(str(item) for item in row.get("lineage", ()))
            ancestors.update(lineage[:-1])
        pruned = [row for row in retained if str(row["root_id"]) not in ancestors]
        retained = pruned or retained[-1:]
    elif method_id in {"B3", "B5"}:
        retained = _strongest_per_root(retained)
    supports = [_support(row) for row in retained]
    if method_id in {"B1", "B2"}:
        support = _noisy_or(supports)
        return support, 1.0, len(retained), len(retained), duplicates, support
    if method_id == "B3":
        support = max(supports)
        return support, 1.0, len(retained), len(retained), duplicates, support
    if method_id == "B4":
        ranked = sorted(supports, reverse=True)
        support = _noisy_or(
            ranked[:1] + [value * B4_NEIGHBOR_WEIGHT for value in ranked[1:]]
        )
        return support, 1.0, len(retained), len(retained), duplicates, support
    if method_id == "B5":
        return (
            max(supports),
            min(1.0, sum(supports)),
            len(retained),
            len(retained),
            duplicates,
            None,
        )
    raise ValueError(f"unknown baseline method_id {method_id!r}")


def _es_rebuild(
    events: list[dict[str, Any]], controls: list[dict[str, Any]]
) -> tuple[float, int, int, int]:
    actions: list[tuple[int, int, dict[str, Any]]] = []
    actions.extend((int(row.get("order", 0)), 1, row) for row in events)
    actions.extend((int(row.get("order", 0)), 0, row) for row in controls)
    parents: dict[str, str] = {}
    canonical: dict[str, str] = {}
    retired: set[str] = set()
    contributions: dict[str, dict[str, Any]] = {}
    seen: dict[tuple[str, int], tuple[Any, ...]] = {}
    duplicates = 0

    def find(root: str) -> str:
        parents.setdefault(root, root)
        if parents[root] != root:
            parents[root] = find(parents[root])
        return parents[root]

    def join(roots: Sequence[str], chosen: str | None) -> None:
        members = {str(root) for root in roots}
        heads = {find(root) for root in members}
        target = (
            str(chosen)
            if chosen is not None
            else min(canonical.get(head, head) for head in heads)
        )
        find(target)
        for head in heads:
            parents[head] = target
        parents[target] = target
        canonical[target] = target

    for _, kind_order, row in sorted(
        actions,
        key=lambda item: (
            item[0],
            item[1],
            str(item[2].get("event_id", item[2].get("control_id", ""))),
        ),
    ):
        if kind_order == 1:
            message, version, root = (
                str(row["message_id"]),
                int(row["version"]),
                str(row["root_id"]),
            )
            signature = _event_signature(row)
            key = (message, version)
            if key in seen:
                if seen[key] != signature:
                    raise ValueError(
                        "same message_id/version has different public content"
                    )
                duplicates += 1
                continue
            seen[key] = signature
            find(root)
            previous = contributions.get(root)
            if previous is None or version > int(previous["version"]):
                contributions[root] = row
        else:
            op = str(row.get("kind", row.get("op", ""))).upper()
            roots = [str(item) for item in row.get("roots", [])]
            if op in {"EQUIVALENCE", "MERGE"}:
                if len(roots) < 2:
                    raise ValueError(f"{op} requires at least two roots")
                join(roots, row.get("canonical_root"))
            elif op == "SUPERSEDE":
                replacement = str(row.get("replacement_root", ""))
                if not replacement or not roots:
                    raise ValueError("SUPERSEDE requires roots and replacement_root")
                join([*roots, replacement], replacement)
                retired.update(roots)
                retired.discard(replacement)
            elif op == "RETIRE":
                retiring = {find(root) for root in roots}
                retired.update(root for root in parents if find(root) in retiring)
            elif op == "REPLAY":
                continue
            else:
                raise ValueError(f"unknown public control {op!r}")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for root, row in contributions.items():
        if root not in retired:
            grouped.setdefault(find(root), []).append(row)
    selected = [
        max(
            rows,
            key=lambda row: (
                int(row["version"]),
                _support(row),
                str(row["message_id"]),
            ),
        )
        for _, rows in sorted(grouped.items())
    ]
    return (
        _noisy_or([_support(row) for row in selected]),
        len(selected),
        duplicates,
        len(actions),
    )


def evaluate_baseline(
    method_id: str,
    public_prefix: Mapping[str, Any],
    cap: int | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if method_id not in BASELINE_SPECS:
        raise ValueError(f"unknown baseline method_id {method_id!r}")
    selected_cap = public_prefix.get("method_cap", 1_000_000) if cap is None else cap
    limits = _limits(selected_cap)
    started = time.perf_counter_ns()
    events, controls = validate_public_prefix(public_prefix)
    bpa: float | None
    try:
        if method_id == "ES-Rebuild":
            support, active, duplicates, rebuilt = _es_rebuild(events, controls)
            lower, upper, bpa = support, 1.0, support
            evidence_count = len(events)
        else:
            lower, upper, evidence_count, active, duplicates, bpa = _ordinary(
                method_id, events
            )
            rebuilt = 0
        elapsed = time.perf_counter_ns() - started
        if (
            limits.deadline_ns is not None
            and time.perf_counter_ns() > limits.deadline_ns
        ):
            return _failed(method_id, "DEADLINE_EXCEEDED", elapsed, rebuilt)
        if active > limits.active:
            return _failed(method_id, "ACTIVE_CONTRIBUTION_CAP", elapsed, rebuilt)
        if float(active) > limits.budget:
            return _failed(method_id, "CONTRIBUTION_BUDGET_CAP", elapsed, rebuilt)
        return _result(
            method_id,
            lower,
            upper,
            evidence_count=evidence_count,
            active_count=active,
            duplicate_count=duplicates,
            elapsed_ns=elapsed,
            recomputed_actions=rebuilt,
            bpa_support=bpa,
        )
    except (KeyError, TypeError, ValueError):
        raise


__all__ = [
    "B4_DEPENDENCE",
    "B4_NEIGHBOR_WEIGHT",
    "BASELINE_METHOD_IDS",
    "BASELINE_SPECS",
    "BaselineSpec",
    "evaluate_baseline",
    "validate_public_prefix",
]
