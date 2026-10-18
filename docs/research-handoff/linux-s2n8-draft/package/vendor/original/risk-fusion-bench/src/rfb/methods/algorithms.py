"""Frozen, deterministic algorithms for the seven-arm method panel."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .lifecycle_engine import action_sort_key, normalize_action, run_lifecycle
from .models import MethodInput, MethodInputError, PublicEvent


@dataclass(frozen=True, slots=True)
class AlgorithmResult:
    risk_score: float
    lower: float
    upper: float
    confidence: float
    evidence_count: int
    active_root_count: int
    rationale: str
    canonical_roots: tuple[str, ...]
    duplicate_count: int = 0
    eliminated_count: int = 0
    rebuild_count: int = 0
    admissible_actions: tuple[str, ...] = ()


def _effective(event: PublicEvent) -> float:
    return event.support * event.reliability


def _noisy_or(supports: list[float]) -> float:
    """Probabilistic sum ``1 - prod(1 - s)`` (noisy-OR).

    Renamed from the mathematically incorrect ``_conjunctive`` on 2026-07-23;
    numeric semantics and all frozen rationale strings are unchanged.
    """

    return 1.0 - math.prod(1.0 - value for value in supports)


def _actions(lower: float, upper: float) -> tuple[str, ...]:
    actions: list[str] = []
    if lower < 0.35:
        actions.append("SAFE")
    if lower < 0.65 and upper >= 0.35:
        actions.append("REVIEW")
    if upper >= 0.65:
        actions.append("UNSAFE")
    return tuple(actions or ["REVIEW"])


def _result(
    risk: float,
    events: list[PublicEvent],
    rationale: str,
    *,
    lower: float | None = None,
    upper: float | None = None,
    roots: tuple[str, ...] | None = None,
    duplicates: int = 0,
    eliminated: int = 0,
    rebuilds: int = 0,
) -> AlgorithmResult:
    lo = risk if lower is None else lower
    hi = risk if upper is None else upper
    canonical = (
        roots
        if roots is not None
        else tuple(sorted({event.root_id for event in events}))
    )
    confidence = max(0.0, min(1.0, 1.0 - (hi - lo)))
    return AlgorithmResult(
        round(risk, 12),
        round(lo, 12),
        round(hi, 12),
        round(confidence, 12),
        len(events),
        len(canonical),
        rationale,
        canonical,
        duplicates,
        eliminated,
        rebuilds,
        _actions(lo, hi),
    )


def normalized_noisy_or(data: MethodInput) -> AlgorithmResult:
    events = list(data.events)
    risk = _noisy_or([_effective(event) for event in events])
    return _result(risk, events, "naive_normalized_conjunctive_binary_simple_support")


def _event_signature(event: PublicEvent) -> tuple[object, ...]:
    return (
        event.message_id,
        event.version,
        event.root_id,
        event.support,
        event.reliability,
        event.lineage,
        event.derived_from,
    )


def _exactly_once(events: tuple[PublicEvent, ...]) -> tuple[list[PublicEvent], int]:
    seen: dict[tuple[str, int], tuple[object, ...]] = {}
    accepted: list[PublicEvent] = []
    duplicates = 0
    for event in sorted(
        events, key=lambda row: (row.order, row.message_id, row.version, row.root_id)
    ):
        key = (event.message_id, event.version)
        signature = _event_signature(event)
        previous = seen.get(key)
        if previous is None:
            seen[key] = signature
            accepted.append(event)
        elif previous == signature:
            duplicates += 1
        else:
            raise MethodInputError(
                "same message_id/version has different public content"
            )
    return accepted, duplicates


def transport_exactly_once(data: MethodInput) -> AlgorithmResult:
    events, duplicates = _exactly_once(data.events)
    risk = _noisy_or([_effective(event) for event in events])
    return _result(
        risk, events, "message_id_version_exactly_once", duplicates=duplicates
    )


def lineage_ancestor_elimination(data: MethodInput) -> AlgorithmResult:
    events, duplicates = _exactly_once(data.events)
    ancestors: set[str] = set()
    for event in events:
        ancestors.update(event.derived_from)
        ancestors.update(event.lineage[:-1] if event.lineage else ())
    retained = [event for event in events if event.root_id not in ancestors]
    if not retained:
        retained = events[-1:]
    risk = _noisy_or([_effective(event) for event in retained])
    return _result(
        risk,
        retained,
        "declared_lineage_transitive_ancestor_elimination",
        duplicates=duplicates,
        eliminated=len(events) - len(retained),
    )


def _max_event_by_root(events: tuple[PublicEvent, ...]) -> list[PublicEvent]:
    selected: dict[str, PublicEvent] = {}
    for event in sorted(
        events,
        key=lambda row: (
            row.root_id,
            -_effective(row),
            row.order,
            row.message_id,
            row.version,
        ),
    ):
        selected.setdefault(event.root_id, event)
    return [selected[root] for root in sorted(selected)]


def cautious_simple_support(data: MethodInput) -> AlgorithmResult:
    events = _max_event_by_root(data.events)
    risk = max(_effective(event) for event in events)
    return _result(risk, events, "denoeux_cautious_binary_simple_support_max_weight")


B4_DEPENDENCE = 0.70
B4_NEIGHBOR_WEIGHT = 1.0 - B4_DEPENDENCE


def partial_dependence_strong_neighbor(data: MethodInput) -> AlgorithmResult:
    events = list(data.events)
    supports = sorted((_effective(event) for event in events), reverse=True)
    adjusted = supports[:1] + [value * B4_NEIGHBOR_WEIGHT for value in supports[1:]]
    risk = _noisy_or(adjusted)
    rationale = (
        "er_tld_family_strong_neighbor_rho_0.70_endpoints_independent_to_cautious"
    )
    return _result(risk, events, rationale)


def unknown_correlation_interval(data: MethodInput) -> AlgorithmResult:
    events = _max_event_by_root(data.events)
    supports = [round(_effective(event), 12) for event in events]
    lower = max(supports)
    upper = min(1.0, sum(supports))
    return _result(
        upper,
        events,
        "frechet_unknown_correlation_public_interval_upper_action",
        lower=lower,
        upper=upper,
    )


def lifecycle_precombination(data: MethodInput) -> AlgorithmResult:
    events = sorted(
        data.events,
        key=lambda row: (row.order, row.message_id, row.version, row.root_id),
    )
    actions: list[dict[str, object]] = []
    # Declared derivation is an equivalence known before online contribution;
    # installing it first avoids counting it as a late mandatory rebuild.
    for index, event in enumerate(events):
        if event.derived_from:
            actions.append(
                {
                    "action_id": f"derived-{index}-{event.message_id}",
                    "op": "EQUIVALENCE",
                    "order": event.order,
                    "roots": [event.root_id, *event.derived_from],
                    "canonical_root": min((event.root_id, *event.derived_from)),
                }
            )
    for index, event in enumerate(events):
        actions.append(
            {
                "action_id": f"event-{index}-{event.message_id}-{event.version}",
                "op": "INITIALIZE",
                "order": event.order,
                "message_id": event.message_id,
                "version": event.version,
                "root_id": event.root_id,
                "support": event.support,
                "reliability": event.reliability,
            }
        )
    retired: set[str] = set()
    for index, control in enumerate(
        sorted(data.controls, key=lambda row: (row.order, row.kind.value, row.roots))
    ):
        action: dict[str, object] = {
            "action_id": f"control-{index}-{control.kind.value}",
            "op": control.kind.value,
            "order": control.order,
            "roots": list(control.roots),
        }
        if control.canonical_root is not None:
            action["canonical_root"] = control.canonical_root
        if control.replacement_root is not None:
            action["replacement_root"] = control.replacement_root
        actions.append(action)
        if control.kind.value == "RETIRE":
            retired.update(control.roots)
        elif control.kind.value == "SUPERSEDE":
            if control.replacement_root is None:
                raise MethodInputError("SUPERSEDE requires replacement_root")
            retired.update(
                root for root in control.roots if root != control.replacement_root
            )
    timeline = tuple(
        sorted((normalize_action(row) for row in actions), key=action_sort_key)
    )
    snapshot = run_lifecycle(timeline)
    if snapshot.status == "SAFE_HALT":
        raise MethodInputError(snapshot.reason or "SAFE_HALT")
    assert snapshot.risk_score is not None
    accepted, _ = _exactly_once(tuple(events))
    active = [event for event in accepted if event.root_id not in retired]
    return _result(
        snapshot.risk_score,
        active,
        "lifecycle_consistent_canonical_root_rebuild",
        roots=tuple(row.canonical_root for row in snapshot.classes),
        duplicates=snapshot.duplicate_count,
        eliminated=snapshot.eliminated_count,
        rebuilds=snapshot.rebuild_count,
    )
