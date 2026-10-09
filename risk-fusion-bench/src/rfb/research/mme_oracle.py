from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .mme_events import MethodPrefix, PhysicalTruthSidecar, PublicControl, PublicEvent

ACTION_THRESHOLD = 0.70


@dataclass(frozen=True, slots=True)
class OracleView:
    simple_support: float
    risk_interval: tuple[float, float]
    action_state: str
    active_classes: int
    bpa: dict[str, Any]


@dataclass(frozen=True, slots=True)
class OracleAssessment:
    prefix_id: str
    full_information: OracleView
    publicly_knowable: OracleView


class _Partition:
    def __init__(self, roots: set[str]):
        self.roots = roots


def _part(parts: list[_Partition], root: str) -> _Partition:
    found = next((row for row in parts if root in row.roots), None)
    if found is None:
        found = _Partition({root})
        parts.append(found)
    return found


def _join(parts: list[_Partition], roots: tuple[str, ...]) -> None:
    touching = [row for row in parts if row.roots.intersection(roots)]
    joined = set(roots)
    for row in touching:
        joined.update(row.roots)
        parts.remove(row)
    parts.append(_Partition(joined))


def _apply_control(
    parts: list[_Partition], retired: set[str], control: PublicControl
) -> None:
    if control.op in {"EQUIVALENCE", "MERGE"}:
        _join(parts, control.roots)
    elif control.op == "SUPERSEDE":
        assert control.replacement_root is not None
        _join(parts, (*control.roots, control.replacement_root))
        retired.update(control.roots)
    elif control.op == "RETIRE":
        retiring = set(control.roots)
        for root in control.roots:
            retiring.update(_part(parts, root).roots)
        retired.update(retiring)
    elif control.op == "REPLAY":
        return
    else:
        raise ValueError(f"unsupported oracle control {control.op!r}")


def _view(
    prefix: MethodPrefix,
    sidecar: PhysicalTruthSidecar,
    *,
    full_information: bool,
) -> OracleView:
    records = {row.event_id: row.physical_root_id for row in sidecar.records}
    event_ids = {row.event_id for row in prefix.events}
    if not event_ids <= records.keys():
        raise ValueError("ORACLE_TRUTH_ALIGNMENT_INVALID")
    parts: list[_Partition] = []
    retired: set[str] = set()
    events: list[PublicEvent] = []
    events_by_id: dict[str, PublicEvent] = {}
    seen: set[tuple[str, int]] = set()
    roots_by_physical: dict[str, list[str]] = {}
    truth_controls = {row.control_id: row for row in sidecar.controls}
    timeline = sorted(
        [*prefix.events, *prefix.controls],
        key=lambda row: (row.order, row.event_id if isinstance(row, PublicEvent) else row.control_id),
    )
    for row in timeline:
        if isinstance(row, PublicEvent):
            key = (row.message_id, row.version)
            if key in seen:
                continue
            seen.add(key)
            events.append(row)
            events_by_id[row.event_id] = row
            _part(parts, row.root_id)
            if full_information:
                physical = records[row.event_id]
                roots = roots_by_physical.setdefault(physical, [])
                roots.append(row.root_id)
                if len(set(roots)) > 1:
                    _join(parts, tuple(roots))
        elif not full_information:
            _apply_control(parts, retired, row)
        elif row.control_id in truth_controls:
            truth_control = truth_controls[row.control_id]
            target_roots = tuple(
                events_by_id[event_id].root_id
                for event_id in truth_control.target_event_ids
                if event_id in events_by_id
            )
            replacement = (
                events_by_id[truth_control.replacement_event_id].root_id
                if truth_control.replacement_event_id in events_by_id
                else None
            )
            resolved = PublicControl(
                truth_control.control_id,
                truth_control.op,
                target_roots,
                row.public_at,
                row.order,
                replacement_root=replacement,
            )
            _apply_control(parts, retired, resolved)
    supports: list[float] = []
    for part in parts:
        active = [row for row in events if row.root_id in part.roots and row.root_id not in retired]
        if active:
            chosen = max(active, key=lambda row: (row.version, row.support, row.event_id))
            supports.append(chosen.support * chosen.reliability)
    support = round(1.0 - math.prod(1.0 - row for row in supports), 12)
    action = "ACT" if support >= ACTION_THRESHOLD else "REVIEW"
    bpa = {
        "frame": ["RISK", "NOT_RISK"],
        "focal_sets": [["RISK"], ["RISK", "NOT_RISK"]],
        "masses": [support, round(1.0 - support, 12)],
    }
    return OracleView(support, (support, 1.0), action, len(supports), bpa)


def evaluate_oracle(
    prefix: MethodPrefix, sidecar: PhysicalTruthSidecar
) -> OracleAssessment:
    if prefix.block_id != sidecar.block_id or prefix.pair_id != sidecar.pair_id:
        raise ValueError("ORACLE_PAIR_ALIGNMENT_INVALID")
    return OracleAssessment(
        prefix.prefix_id,
        _view(prefix, sidecar, full_information=True),
        _view(prefix, sidecar, full_information=False),
    )


__all__ = [
    "ACTION_THRESHOLD",
    "OracleAssessment",
    "OracleView",
    "evaluate_oracle",
]
