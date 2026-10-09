from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

METHOD_IDS = ("Proposed", "B1", "B2", "ES-Rebuild", "B0", "B3", "B4", "B5")
PREFIX_IDS = ("X", "XD", "XI")
RUN_CLASSES = ("D_impl_unit", "D_development", "MME_v2")
_RUN_SEED_DOMAINS = {
    "D_impl_unit": "mme-v2-development-seed-domain-20260907",
    "D_development": "mme-v2-integration-seed-domain-20260907",
    "MME_v2": "mme-v2-actual-seed-domain-20260907",
}
_PREFIX_TIMES = (0, 1, 2, 3, 4)
_CORE_ROWS = (
    ("P01", "distinct_key_same_acquisition", "post_commit_long", "merge", "multiple_new_roots"),
    ("P02", "exact_retry", "post_commit_short", "merge", "zero_new_root"),
    ("P03", "derived_view", "post_commit_short", "retire", "one_new_root"),
    ("P04", "derived_view", "pre_commit", "replay", "zero_new_root"),
    ("P05", "exact_retry", "post_commit_long", "supersede", "one_new_root"),
    ("P06", "exact_retry", "pre_commit", "retire", "multiple_new_roots"),
    ("P07", "distinct_key_same_acquisition", "pre_commit", "supersede", "one_new_root"),
    ("P08", "distinct_key_same_acquisition", "post_commit_long", "retire", "zero_new_root"),
    ("P09", "derived_view", "post_commit_short", "supersede", "multiple_new_roots"),
    ("P10", "distinct_key_same_acquisition", "post_commit_short", "replay", "multiple_new_roots"),
    ("P11", "exact_retry", "post_commit_long", "replay", "one_new_root"),
    ("P12", "derived_view", "post_commit_long", "merge", "one_new_root"),
    ("P13", "exact_retry", "post_commit_long", "supersede", "zero_new_root"),
    ("P14", "exact_retry", "pre_commit", "merge", "one_new_root"),
    ("P15", "exact_retry", "post_commit_long", "retire", "multiple_new_roots"),
)
_BOUNDARY_ROWS = (
    ("E01", "registry_missing_edge", "distinct_key_same_acquisition", "post_commit_short", "merge", "zero_new_root", "missing_edge", "reference", "directional", "nominal"),
    ("E02", "registry_spurious_edge", "derived_view", "pre_commit", "supersede", "one_new_root", "spurious_edge", "reference", "low", "nominal"),
    ("E03", "registry_missing_hyperedge", "derived_view", "post_commit_long", "merge", "multiple_new_roots", "missing_hyperedge", "reference", "high", "nominal"),
    ("E04", "wrong_root_split", "distinct_key_same_acquisition", "post_commit_long", "replay", "zero_new_root", "wrong_root_split", "over_split", "directional", "nominal"),
    ("E05", "wrong_root_merge", "exact_retry", "pre_commit", "retire", "multiple_new_roots", "wrong_root_merge", "over_merge", "low", "nominal"),
    ("E06", "delayed_disclosure", "distinct_key_same_acquisition", "post_commit_long", "merge", "one_new_root", "delayed_disclosure", "reference", "high", "nominal"),
    ("E07", "expired_edge", "derived_view", "post_commit_short", "supersede", "one_new_root", "expired_edge", "reference", "directional", "nominal"),
    ("E08", "context_mismatch", "exact_retry", "post_commit_short", "replay", "multiple_new_roots", "context_mismatch", "reference", "high", "nominal"),
    ("E09", "eventifier_over_split", "distinct_key_same_acquisition", "post_commit_short", "merge", "zero_new_root", "none", "over_split", "directional", "cap_near"),
    ("E10", "eventifier_over_merge", "derived_view", "pre_commit", "retire", "multiple_new_roots", "none", "over_merge", "high", "cap_near"),
    ("E11", "cap_near_high_conflict", "distinct_key_same_acquisition", "post_commit_long", "supersede", "one_new_root", "none", "reference", "high", "cap_near"),
    ("E12", "overflow_fail_stop_and_replay", "exact_retry", "post_commit_short", "replay", "one_new_root", "none", "reference", "directional", "overflow"),
)


def _opaque(domain: str, seed: int, slot: str) -> str:
    return hashlib.sha256(f"mme-v2|{domain}|{seed}|{slot}".encode()).hexdigest()


def seed_for(run_class: str, block_id: str) -> int:
    try:
        domain = _RUN_SEED_DOMAINS[run_class]
    except KeyError as exc:
        raise ValueError(f"unknown run_class {run_class!r}") from exc
    digest = hashlib.sha256(f"{domain}|{block_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


@dataclass(frozen=True, slots=True)
class PublicEvent:
    event_id: str
    message_id: str
    version: int
    root_id: str
    support: float
    reliability: float
    public_at: int
    order: int
    derived_from: tuple[str, ...] = ()

    def method_value(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "message_id": self.message_id,
            "version": self.version,
            "root_id": self.root_id,
            "support": self.support,
            "reliability": self.reliability,
            "order": self.order,
            "derived_from": list(self.derived_from),
        }

    def action_value(self) -> dict[str, Any]:
        return {
            "action_id": self.event_id,
            "op": "INITIALIZE",
            "order": self.order,
            "message_id": self.message_id,
            "version": self.version,
            "root_id": self.root_id,
            "support": self.support,
            "reliability": self.reliability,
        }


@dataclass(frozen=True, slots=True)
class PublicControl:
    control_id: str
    op: str
    roots: tuple[str, ...]
    public_at: int
    order: int
    canonical_root: str | None = None
    replacement_root: str | None = None

    def method_value(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "control_id": self.control_id,
            "kind": self.op,
            "roots": list(self.roots),
            "order": self.order,
        }
        if self.canonical_root is not None:
            value["canonical_root"] = self.canonical_root
        if self.replacement_root is not None:
            value["replacement_root"] = self.replacement_root
        return value

    def action_value(self) -> dict[str, Any]:
        value = self.method_value()
        value["action_id"] = value.pop("control_id")
        value["op"] = value.pop("kind")
        return value


@dataclass(frozen=True, slots=True)
class MethodPrefix:
    block_id: str
    pair_id: str
    arm_id: str
    prefix_index: int
    prefix_id: str
    method_prefix_token: str
    observation_time: int
    algorithm_seed: int
    method_cap: int
    events: tuple[PublicEvent, ...]
    controls: tuple[PublicControl, ...]

    def method_payload(self) -> dict[str, Any]:
        actions = sorted(
            [event.action_value() for event in self.events]
            + [control.action_value() for control in self.controls],
            key=lambda row: (row["order"], row["action_id"]),
        )
        return {
            "bundle_id": self.pair_id,
            "algorithm_seed": self.algorithm_seed,
            "method_cap": self.method_cap,
            "transaction_id": self.method_prefix_token,
            "actions": actions,
            "events": [event.method_value() for event in self.events],
            "controls": [control.method_value() for control in self.controls],
        }


@dataclass(frozen=True, slots=True)
class TruthRecord:
    event_id: str
    physical_root_id: str


@dataclass(frozen=True, slots=True)
class TruthControl:
    control_id: str
    op: str
    target_event_ids: tuple[str, ...]
    replacement_event_id: str | None = None


@dataclass(frozen=True, slots=True)
class PhysicalTruthSidecar:
    block_id: str
    pair_id: str
    records: tuple[TruthRecord, ...]
    controls: tuple[TruthControl, ...]


@dataclass(frozen=True, slots=True)
class MMEBlock:
    block_id: str
    run_class: str
    physical_seed: int
    generation_status: str
    method_cap: int
    prefixes: tuple[MethodPrefix, ...]
    truth_sidecar: PhysicalTruthSidecar

    def prefix(self, arm_id: str, prefix_index: int = 2) -> MethodPrefix:
        try:
            return next(
                row
                for row in self.prefixes
                if row.arm_id == arm_id and row.prefix_index == prefix_index
            )
        except StopIteration as exc:
            raise ValueError(f"unknown prefix {arm_id!r}@{prefix_index}") from exc


def _spec_text(spec: Mapping[str, Any], key: str, allowed: set[str]) -> str:
    value = spec.get(key)
    if value not in allowed:
        raise ValueError(f"invalid {key}: {value!r}")
    return str(value)


def _validate_support(value: float) -> float:
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError("support must be in [0, 1]")
    return result


def generate_block(
    spec: Mapping[str, Any],
    *,
    run_class: str,
    physical_seed: int | None = None,
    support: float = 0.8,
) -> MMEBlock:
    block_id = str(spec.get("block_id", ""))
    if not block_id:
        raise ValueError("block_id is required")
    duplicate = _spec_text(
        spec,
        "duplicate_class",
        {"exact_retry", "distinct_key_same_acquisition", "derived_view"},
    )
    timing = _spec_text(
        spec,
        "equivalence_timing",
        {"pre_commit", "post_commit_short", "post_commit_long"},
    )
    lifecycle = _spec_text(
        spec, "lifecycle", {"supersede", "merge", "retire", "replay"}
    )
    independent = _spec_text(
        spec,
        "independent_information",
        {"zero_new_root", "one_new_root", "multiple_new_roots"},
    )
    if run_class not in RUN_CLASSES:
        raise ValueError(f"unknown run_class {run_class!r}")
    seed = seed_for(run_class, block_id) if physical_seed is None else physical_seed
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("physical_seed must be a non-negative integer")
    support = _validate_support(support)
    pair_id = _opaque("pair", seed, "pair")

    def oid(domain: str, slot: str) -> str:
        return _opaque(domain, seed, slot)

    base_root = oid("root", "base")
    base_message = oid("message", "base")
    events = [
        PublicEvent(
            oid("event", "base"), base_message, 1, base_root, support, 1.0, 0, 10
        )
    ]
    truth = [TruthRecord(events[0].event_id, oid("physical", "base"))]

    if duplicate == "exact_retry":
        duplicate_root, duplicate_message = base_root, base_message
    else:
        duplicate_root = oid("root", "duplicate")
        duplicate_message = oid("message", "duplicate")
    duplicate_event = PublicEvent(
        oid("event", "duplicate"),
        duplicate_message,
        1,
        duplicate_root,
        support,
        1.0,
        1,
        30,
        (events[0].event_id,) if duplicate == "derived_view" else (),
    )
    events.append(duplicate_event)
    duplicate_physical = (
        oid("physical", "expired-independent")
        if str(spec.get("registry_error", "none")) == "expired_edge"
        else oid("physical", "base")
    )
    truth.append(TruthRecord(duplicate_event.event_id, duplicate_physical))

    count = {"zero_new_root": 0, "one_new_root": 1, "multiple_new_roots": 2}[
        independent
    ]
    independent_roots: list[str] = []
    for index in range(count):
        root = oid("root", f"independent-{index}")
        event = PublicEvent(
            oid("event", f"independent-{index}"),
            oid("message", f"independent-{index}"),
            1,
            root,
            support,
            1.0,
            2,
            60 + index,
        )
        events.append(event)
        truth.append(
            TruthRecord(event.event_id, oid("physical", f"independent-{index}"))
        )
        independent_roots.append(root)

    controls: list[PublicControl] = []
    truth_controls: list[TruthControl] = []
    registry_error = str(spec.get("registry_error", "none"))
    eventifier = str(spec.get("eventifier", "reference"))
    load = str(spec.get("load", "nominal"))
    method_cap = {"nominal": 1_000_000, "cap_near": 2, "overflow": 1}.get(load)
    if method_cap is None:
        raise ValueError(f"invalid load: {load!r}")
    if duplicate != "exact_retry" and registry_error not in {
        "missing_edge",
        "missing_hyperedge",
        "delayed_disclosure",
        "spurious_edge",
        "wrong_root_split",
        "expired_edge",
    } and eventifier != "over_split":
        public_at = {"pre_commit": 1, "post_commit_short": 1, "post_commit_long": 2}[
            timing
        ]
        order = 20 if timing == "pre_commit" else (40 if public_at == 1 else 70)
        control = PublicControl(
            oid("control", "equivalence"),
            "EQUIVALENCE",
            (base_root, duplicate_root),
            public_at,
            order,
            canonical_root=base_root,
        )
        controls.append(control)
        truth_controls.append(
            TruthControl(
                control.control_id,
                control.op,
                (events[0].event_id, duplicate_event.event_id),
            )
        )

    if duplicate != "exact_retry" and registry_error == "delayed_disclosure":
        control = PublicControl(
            oid("control", "equivalence"),
            "EQUIVALENCE",
            (base_root, duplicate_root),
            3,
            70,
            canonical_root=base_root,
        )
        controls.append(control)
        truth_controls.append(
            TruthControl(
                control.control_id,
                control.op,
                (events[0].event_id, duplicate_event.event_id),
            )
        )

    if registry_error in {"spurious_edge", "expired_edge"} and independent_roots:
        roots = (
            (base_root, independent_roots[0])
            if registry_error == "spurious_edge"
            else (base_root, duplicate_root)
        )
        control = PublicControl(
            oid("control", registry_error),
            "EQUIVALENCE",
            roots,
            2,
            72,
            canonical_root=base_root,
        )
        controls.append(control)

    if registry_error == "wrong_root_merge" or eventifier == "over_merge":
        if independent_roots:
            control = PublicControl(
                oid("control", "wrong-merge"),
                "MERGE",
                (base_root, independent_roots[0]),
                2,
                75,
                canonical_root=base_root,
            )
            controls.append(control)

    if lifecycle == "supersede":
        replacement_root = oid("root", "replacement")
        replacement_event = PublicEvent(
            oid("event", "replacement"),
            oid("message", "replacement"),
            3,
            replacement_root,
            support,
            1.0,
            3,
            80,
        )
        events.append(replacement_event)
        truth.append(TruthRecord(replacement_event.event_id, oid("physical", "base")))
        control = PublicControl(
            oid("control", "supersede"),
            "SUPERSEDE",
            (base_root,),
            3,
            90,
            replacement_root=replacement_root,
        )
        controls.append(control)
        truth_controls.append(
            TruthControl(
                control.control_id,
                control.op,
                (events[0].event_id,),
                replacement_event.event_id,
            )
        )
    elif lifecycle == "retire":
        control = PublicControl(
            oid("control", "retire"), "RETIRE", (base_root,), 3, 90
        )
        controls.append(control)
        truth_controls.append(
            TruthControl(control.control_id, control.op, (events[0].event_id,))
        )
    elif lifecycle == "replay":
        control = PublicControl(
            oid("control", "replay"), "REPLAY", (), 3, 90
        )
        controls.append(control)
        truth_controls.append(TruthControl(control.control_id, control.op, ()))

    replacement_events = {row.event_id for row in events if row.order == 80}
    arm_event_ids = {
        "X": {events[0].event_id, *replacement_events},
        "XD": {events[0].event_id, duplicate_event.event_id, *replacement_events},
        "XI": {
            events[0].event_id,
            *(row.event_id for row in events if row.root_id in independent_roots),
            *replacement_events,
        },
    }
    prefix_rows: list[MethodPrefix] = []
    for arm_id in PREFIX_IDS:
        for prefix_index, time in enumerate(_PREFIX_TIMES):
            visible_events = tuple(
                sorted(
                    (
                        row
                        for row in events
                        if row.event_id in arm_event_ids[arm_id]
                        and row.public_at <= time
                    ),
                    key=lambda row: row.order,
                )
            )
            visible_roots = {row.root_id for row in visible_events}
            visible_controls = tuple(
                sorted(
                    (
                        row
                        for row in controls
                        if row.public_at <= time
                        and set(row.roots) <= visible_roots
                        and (
                            row.replacement_root is None
                            or row.replacement_root in visible_roots
                        )
                    ),
                    key=lambda row: row.order,
                )
            )
            prefix_id = f"{arm_id}:{prefix_index}"
            prefix_rows.append(
                MethodPrefix(
                    block_id=block_id,
                    pair_id=pair_id,
                    arm_id=arm_id,
                    prefix_index=prefix_index,
                    prefix_id=prefix_id,
                    method_prefix_token=oid("prefix", prefix_id),
                    observation_time=time,
                    algorithm_seed=seed_for(run_class, f"{block_id}:{prefix_id}"),
                    method_cap=method_cap,
                    events=visible_events,
                    controls=visible_controls,
                )
            )
    prefixes = tuple(prefix_rows)
    sidecar = PhysicalTruthSidecar(
        block_id, pair_id, tuple(truth), tuple(truth_controls)
    )
    generation_status = (
        "NOT_IMPLEMENTED_SCOPE_BOUNDARY"
        if registry_error == "context_mismatch"
        else "SUPPORTED"
    )
    return MMEBlock(
        block_id,
        run_class,
        seed,
        generation_status,
        method_cap,
        prefixes,
        sidecar,
    )


def public_block_value(block: MMEBlock) -> dict[str, Any]:
    return {
        "block_id": block.block_id,
        "run_class": block.run_class,
        "physical_seed": block.physical_seed,
        "generation_status": block.generation_status,
        "method_cap": block.method_cap,
        "prefixes": [prefix.method_payload() for prefix in block.prefixes],
    }


def experiment_specs() -> tuple[dict[str, str], ...]:
    core = tuple(
        {
            "block_id": block_id,
            "duplicate_class": duplicate,
            "equivalence_timing": timing,
            "lifecycle": lifecycle,
            "independent_information": independent,
        }
        for block_id, duplicate, timing, lifecycle, independent in _CORE_ROWS
    )
    boundary = tuple(
        {
            "block_id": block_id,
            "boundary": boundary_name,
            "duplicate_class": duplicate,
            "equivalence_timing": timing,
            "lifecycle": lifecycle,
            "independent_information": independent,
            "registry_error": registry_error,
            "eventifier": eventifier,
            "conflict": conflict,
            "load": load,
        }
        for (
            block_id,
            boundary_name,
            duplicate,
            timing,
            lifecycle,
            independent,
            registry_error,
            eventifier,
            conflict,
            load,
        ) in _BOUNDARY_ROWS
    )
    return core + boundary


def generate_experiment(run_class: str) -> tuple[MMEBlock, ...]:
    return tuple(generate_block(spec, run_class=run_class) for spec in experiment_specs())


__all__ = [
    "METHOD_IDS",
    "PREFIX_IDS",
    "RUN_CLASSES",
    "MMEBlock",
    "MethodPrefix",
    "PhysicalTruthSidecar",
    "PublicControl",
    "PublicEvent",
    "TruthRecord",
    "TruthControl",
    "generate_block",
    "generate_experiment",
    "experiment_specs",
    "public_block_value",
    "seed_for",
]
