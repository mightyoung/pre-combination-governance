"""Lifecycle governance integrated with the production ``RuntimeKernel``."""

from __future__ import annotations

import hashlib
import json
import math
import pcg_observer as _pcg_observer
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from .. import dst
from ..runtime import Event, Root, RuntimeKernel, TransactionStatus, Version

OPS = frozenset(
    {
        "INITIALIZE",
        "EQUIVALENCE",
        "SUPERSEDE",
        "MERGE",
        "RETIRE",
        "REPLAY",
        "SAFE_HALT",
        "REPLAY_VALIDATION_FAILED",
    }
)


class LifecycleEngineError(RuntimeError):
    pass


class CasRevisionConflict(LifecycleEngineError):
    pass


class PreCommitCrash(LifecycleEngineError):
    pass


class PostCommitCrash(LifecycleEngineError):
    pass


@dataclass(frozen=True, slots=True)
class LifecycleAction:
    action_id: str
    op: str
    order: int
    message_id: str | None = None
    version: int | None = None
    root_id: str | None = None
    support: float | None = None
    reliability: float = 1.0
    contribution_amount: float = 1.0
    processing_cost: float = 1.0
    roots: tuple[str, ...] = ()
    canonical_root: str | None = None
    replacement_root: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalClass:
    canonical_root: str
    roots: tuple[str, ...]
    lifecycle: str
    effective_version: int | None
    contribution_count: int
    selected_event_id: str | None
    contribution_amount: float
    support: float


@dataclass(frozen=True, slots=True)
class LifecycleLedgerRecord:
    revision: int
    action_id: str
    op: str
    before_scientific_binding: str
    after_scientific_binding: str
    previous_hash: str
    record_hash: str


@dataclass(frozen=True, slots=True)
class LifecycleSnapshot:
    authority: str = "LIFECYCLE_ENGINE"
    revision: int = 0
    max_active_contributions: int = 1_000_000
    max_contribution_budget: float = 1_000_000.0
    status: str = "RUNNING"
    reason: str | None = None
    failure_code: str | None = None
    availability: str = "AVAILABLE"
    gate: str = "OPEN"
    action: str = "IDLE"
    replay_current: bool = True
    history: tuple[LifecycleAction, ...] = ()
    classes: tuple[CanonicalClass, ...] = ()
    root_lifecycle: tuple[tuple[str, str], ...] = ()
    effective_versions: tuple[tuple[str, int], ...] = ()
    audit_effective_versions: tuple[tuple[str, int], ...] = ()
    risk_score: float | None = 0.0
    contribution_budget: float = 0.0
    processing_spend: float = 0.0
    duplicate_count: int = 0
    stale_count: int = 0
    eliminated_count: int = 0
    rebuild_count: int = 0
    runtime_scientific_hash: str = "0" * 64
    runtime_ledger_head: str = "0" * 64
    scientific_binding: str = "0" * 64
    ledger: tuple[LifecycleLedgerRecord, ...] = ()
    ledger_head: str = "0" * 64


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    status: str
    snapshot: LifecycleSnapshot


@dataclass(slots=True)
class _Partition:
    roots: set[str]
    canonical: str


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _texts(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{name} must be an array")
    result = tuple(_text(item, name) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} contains duplicates")
    return result


def _number(value: Any, name: str, *, probability: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (probability and result > 1):
        raise ValueError(f"{name} is outside its closed range")
    return result


def normalize_action(value: Mapping[str, Any] | LifecycleAction) -> LifecycleAction:
    if isinstance(value, LifecycleAction):
        return value
    allowed = {
        "action_id",
        "op",
        "order",
        "message_id",
        "version",
        "root_id",
        "support",
        "reliability",
        "contribution_amount",
        "processing_cost",
        "roots",
        "canonical_root",
        "replacement_root",
        "fault",
    }
    if set(value) - allowed:
        raise ValueError("unknown lifecycle action fields")
    op = _text(value.get("op"), "op").upper()
    if op not in OPS:
        raise ValueError(f"unknown lifecycle op {op!r}")
    order = value.get("order", 0)
    if isinstance(order, bool) or not isinstance(order, int) or order < 0:
        raise ValueError("order must be a non-negative integer")
    action = LifecycleAction(
        action_id=_text(value.get("action_id"), "action_id"),
        op=op,
        order=order,
        message_id=value.get("message_id"),
        version=value.get("version"),
        root_id=value.get("root_id"),
        support=value.get("support"),
        reliability=_number(
            value.get("reliability", 1.0), "reliability", probability=True
        ),
        contribution_amount=_number(
            value.get("contribution_amount", 1.0), "contribution_amount"
        ),
        processing_cost=_number(value.get("processing_cost", 1.0), "processing_cost"),
        roots=_texts(value.get("roots"), "roots"),
        canonical_root=value.get("canonical_root"),
        replacement_root=value.get("replacement_root"),
    )
    if op == "INITIALIZE":
        _text(action.message_id, "message_id")
        _text(action.root_id, "root_id")
        if (
            isinstance(action.version, bool)
            or not isinstance(action.version, int)
            or action.version < 1
        ):
            raise ValueError("version must be a positive integer")
        _number(action.support, "support", probability=True)
    elif op in {"EQUIVALENCE", "MERGE"} and len(action.roots) < 2:
        raise ValueError(f"{op} requires at least two roots")
    elif op in {"RETIRE", "SUPERSEDE"} and not action.roots:
        raise ValueError(f"{op} requires roots")
    if op == "SUPERSEDE":
        replacement = _text(action.replacement_root, "replacement_root")
        if replacement in action.roots:
            raise ValueError("replacement_root must differ from superseded roots")
    if action.canonical_root is not None:
        canonical = _text(action.canonical_root, "canonical_root")
        if op not in {"EQUIVALENCE", "MERGE"} or canonical not in action.roots:
            raise ValueError("canonical_root must be one of the controlled roots")
    if op in {"SAFE_HALT", "REPLAY_VALIDATION_FAILED"} and action.roots:
        raise ValueError(f"{op} does not accept roots")
    return action


def action_sort_key(action: LifecycleAction) -> tuple[int, int, str]:
    return action.order, 1 if action.op == "INITIALIZE" else 0, action.action_id


def _part(partitions: list[_Partition], root: str) -> _Partition | None:
    return next((item for item in partitions if root in item.roots), None)


def _ensure(partitions: list[_Partition], root: str) -> _Partition:
    existing = _part(partitions, root)
    if existing is not None:
        return existing
    created = _Partition({root}, root)
    partitions.append(created)
    return created


def _merge(
    partitions: list[_Partition], roots: Iterable[str], canonical: str | None
) -> None:
    names = set(roots)
    touching = [item for item in partitions if item.roots & names]
    joined = set(names)
    for item in touching:
        joined.update(item.roots)
        partitions.remove(item)
    chosen = canonical or min(
        (item.canonical for item in touching), default=min(joined)
    )
    if chosen not in joined:
        raise ValueError("canonical root is outside merged class")
    partitions.append(_Partition(joined, chosen))


def _event(action: LifecycleAction) -> Event:
    assert (
        action.message_id
        and action.version
        and action.root_id
        and action.support is not None
    )
    support = float(action.support) * action.reliability
    return Event.create(
        event_id=f"{action.message_id}@{action.version}",
        root=Root(action.root_id, "PUBLIC_METHOD_EVENT"),
        version=Version(action.version),
        mass={16: support, dst.THETA: 1.0 - support},
        occurred_at=0.0,
        view_id=action.message_id,
        processing_cost=action.processing_cost,
        contribution_amount=action.contribution_amount,
    )


def _classes(
    runtime: RuntimeKernel, partitions: list[_Partition], retired: set[str]
) -> tuple[CanonicalClass, ...]:
    grouped: dict[str, list[Any]] = {}
    for token in runtime.snapshot.state.contribution_tokens:
        if token.root_id not in retired:
            grouped.setdefault(_ensure(partitions, token.root_id).canonical, []).append(
                token
            )
    output = []
    for canonical in sorted(grouped):
        selected = max(
            grouped[canonical],
            key=lambda token: (
                token.bundle_version,
                dict(token.mass).get(16, 0.0),
                token.effective_event_id,
            ),
        )
        partition = _part(partitions, canonical)
        assert partition is not None
        output.append(
            CanonicalClass(
                canonical,
                tuple(sorted(partition.roots)),
                "ACTIVE",
                selected.bundle_version,
                1,
                selected.effective_event_id.rsplit("@", 1)[0],
                float(selected.amount),
                round(dict(selected.mass).get(16, 0.0), 12),
            )
        )
    return tuple(output)


def _evaluate(
    history: tuple[LifecycleAction, ...], *, active_cap: int, budget_cap: float
) -> dict[str, Any]:
    runtime = RuntimeKernel(budget_total=1_000_000_000)
    partitions: list[_Partition] = []
    retired: set[str] = set()
    roots: dict[str, str] = {}
    duplicates = stale = rebuilds = 0
    status, reason, failure = "RUNNING", None, None
    last_legal: dict[str, Any] | None = None
    for action in history:
        _pcg_observer.count("history_evaluation_visits")
        if status == "SAFE_HALT":
            continue
        if action.op in {"SAFE_HALT", "REPLAY_VALIDATION_FAILED"}:
            status = "SAFE_HALT"
            reason = failure = (
                "REPLAY_VALIDATION_FAILED"
                if action.op == "REPLAY_VALIDATION_FAILED"
                else "EXPLICIT_SAFE_HALT"
            )
        elif action.op == "INITIALIZE":
            result = runtime.process(_event(action))
            assert action.root_id
            _ensure(partitions, action.root_id)
            roots.setdefault(action.root_id, "ACTIVE")
            if result.status is TransactionStatus.DUPLICATE_AUDIT:
                duplicates += 1
            elif result.status in {
                TransactionStatus.STALE_VERSION_AUDIT,
                TransactionStatus.ALTERNATE_VIEW_AUDIT,
            }:
                stale += 1
            elif result.snapshot.state.availability == "UNAVAILABLE":
                status = "SAFE_HALT"
                reason = failure = result.snapshot.state.gate.reason
        elif action.op in {"EQUIVALENCE", "MERGE"}:
            occupied = {
                row.canonical_root
                for row in _classes(runtime, partitions, retired)
                if set(row.roots) & set(action.roots)
            }
            rebuilds += int(len(occupied) > 1)
            _merge(partitions, action.roots, action.canonical_root)
            merged = _part(partitions, action.canonical_root or action.roots[0])
            assert merged is not None
            for root in merged.roots:
                roots[root] = "ACTIVE" if root == merged.canonical else "MERGED"
        elif action.op == "SUPERSEDE":
            assert action.replacement_root
            rebuilds += int(
                any(
                    set(row.roots) & set(action.roots)
                    for row in _classes(runtime, partitions, retired)
                )
            )
            _merge(
                partitions,
                (*action.roots, action.replacement_root),
                action.replacement_root,
            )
            for root in action.roots:
                retired.add(root)
                roots[root] = "SUPERSEDED"
            roots[action.replacement_root] = "ACTIVE"
        elif action.op == "RETIRE":
            rebuilds += int(
                any(
                    set(row.roots) & set(action.roots)
                    for row in _classes(runtime, partitions, retired)
                )
            )
            retiring = set(action.roots)
            for root in action.roots:
                partition = _part(partitions, root)
                if partition is not None:
                    retiring.update(partition.roots)
            retired.update(retiring)
            roots.update({root: "RETIRED" for root in retiring})
        classes = _classes(runtime, partitions, retired)
        budget = sum(row.contribution_amount for row in classes)
        if status != "SAFE_HALT" and len(classes) > active_cap:
            status = "SAFE_HALT"
            reason = failure = "ACTIVE_CONTRIBUTION_CAP"
        if status != "SAFE_HALT" and budget > budget_cap:
            status = "SAFE_HALT"
            reason = failure = "CONTRIBUTION_BUDGET_CAP"
        state = runtime.snapshot.state
        audit_versions = tuple(
            sorted(
                (token.root_id, token.bundle_version)
                for token in state.contribution_tokens
            )
        )
        public_versions = tuple(
            (row.canonical_root, row.effective_version)
            for row in classes
            if row.effective_version is not None
        )
        current = {
            "status": status,
            "reason": reason,
            "failure_code": failure,
            "action": "FAIL_CLOSED" if status == "SAFE_HALT" else action.op,
            "classes": classes,
            "root_lifecycle": tuple(sorted(roots.items())),
            "effective_versions": public_versions,
            "audit_effective_versions": audit_versions,
            "risk_score": None
            if status == "SAFE_HALT"
            else round(1.0 - math.prod(1.0 - row.support for row in classes), 12),
            "contribution_budget": float(budget),
            "processing_spend": float(state.processing_spend),
            "duplicate_count": duplicates,
            "stale_count": stale,
            "eliminated_count": max(0, len(state.contribution_tokens) - len(classes)),
            "rebuild_count": rebuilds,
            "runtime_scientific_hash": runtime.snapshot.scientific_hash,
            "runtime_ledger_head": runtime.snapshot.ledger.head_hash,
            "replay_current": action.op == "REPLAY",
        }
        if status == "SAFE_HALT" and last_legal is not None:
            for key in (
                "classes",
                "root_lifecycle",
                "effective_versions",
                "audit_effective_versions",
                "contribution_budget",
                "runtime_scientific_hash",
                "runtime_ledger_head",
            ):
                current[key] = last_legal[key]
            current["risk_score"] = None
        if status != "SAFE_HALT":
            last_legal = current
    if history:
        return current
    return {
        "authority": "LIFECYCLE_ENGINE",
        "status": "RUNNING",
        "reason": None,
        "failure_code": None,
        "action": "IDLE",
        "classes": (),
        "root_lifecycle": (),
        "effective_versions": (),
        "audit_effective_versions": (),
        "risk_score": 0.0,
        "contribution_budget": 0.0,
        "processing_spend": 0.0,
        "duplicate_count": 0,
        "stale_count": 0,
        "eliminated_count": 0,
        "rebuild_count": 0,
        "runtime_scientific_hash": runtime.snapshot.scientific_hash,
        "runtime_ledger_head": runtime.snapshot.ledger.head_hash,
        "replay_current": False,
    }


def _binding(state: Mapping[str, Any]) -> str:
    return _sha(
        {
            "authority": "LIFECYCLE_ENGINE",
            "status": state["status"],
            "reason": state["reason"],
            "failure_code": state["failure_code"],
            "availability": "UNAVAILABLE"
            if state["status"] == "SAFE_HALT"
            else "AVAILABLE",
            "gate": "CLOSED" if state["status"] == "SAFE_HALT" else "OPEN",
            "action": state["action"],
            "replay_current": state["replay_current"],
            "classes": [asdict(row) for row in state["classes"]],
            "root_lifecycle": state["root_lifecycle"],
            "effective_versions": state["effective_versions"],
            "audit_effective_versions": state["audit_effective_versions"],
            "risk_score": state["risk_score"],
            "contribution_budget": state["contribution_budget"],
            "processing_spend": state["processing_spend"],
            "duplicate_count": state["duplicate_count"],
            "stale_count": state["stale_count"],
            "eliminated_count": state["eliminated_count"],
            "rebuild_count": state["rebuild_count"],
            "runtime_scientific_hash": state["runtime_scientific_hash"],
            "runtime_ledger_head": state["runtime_ledger_head"],
        }
    )


class LifecycleEngine:
    def __init__(
        self,
        *,
        max_active_contributions: int = 1_000_000,
        max_contribution_budget: float = 1_000_000.0,
    ) -> None:
        if (
            isinstance(max_active_contributions, bool)
            or not isinstance(max_active_contributions, int)
            or max_active_contributions < 1
        ):
            raise ValueError("max_active_contributions must be positive")
        self.max_active_contributions = max_active_contributions
        self.max_contribution_budget = _number(
            max_contribution_budget, "max_contribution_budget"
        )
        self._snapshot = LifecycleSnapshot(
            max_active_contributions=max_active_contributions,
            max_contribution_budget=self.max_contribution_budget,
        )

    @property
    def snapshot(self) -> LifecycleSnapshot:
        return self._snapshot

    def apply(
        self,
        value: Mapping[str, Any] | LifecycleAction,
        *,
        expected_revision: int | None = None,
    ) -> LifecycleResult:
        if (
            expected_revision is not None
            and expected_revision != self._snapshot.revision
        ):
            raise CasRevisionConflict("CAS_REVISION_CONFLICT")
        fault = value.get("fault") if isinstance(value, Mapping) else None
        action = normalize_action(value)
        if fault == "PRE_COMMIT_CRASH":
            raise PreCommitCrash("PRE_COMMIT_CRASH")
        if action.op == "REPLAY":
            rebuilt = type(self).replay(
                self._snapshot.history,
                max_active_contributions=self.max_active_contributions,
                max_contribution_budget=self.max_contribution_budget,
            )
            if rebuilt != self._snapshot:
                # A corrupted checkpoint cannot be the predecessor of new
                # authority evidence. Re-anchor at the history-derived state.
                self._snapshot = rebuilt
                action = LifecycleAction(
                    action.action_id, "REPLAY_VALIDATION_FAILED", action.order
                )
        existing = next(
            (
                row
                for row in self._snapshot.history
                if row.action_id == action.action_id
            ),
            None,
        )
        if existing is not None and existing != action:
            action = LifecycleAction(
                f"{action.action_id}:equivocation", "SAFE_HALT", action.order
            )
        history = self._snapshot.history + (action,)
        state = _evaluate(
            history,
            active_cap=self.max_active_contributions,
            budget_cap=self.max_contribution_budget,
        )
        _pcg_observer.start("outer_audit_binding_record")
        before_binding = self._snapshot.scientific_binding
        after_binding = _binding(state)
        body = {
            "revision": self._snapshot.revision + 1,
            "action_id": action.action_id,
            "op": action.op,
            "before_scientific_binding": before_binding,
            "after_scientific_binding": after_binding,
            "previous_hash": self._snapshot.ledger_head,
        }
        record = LifecycleLedgerRecord(**body, record_hash=_sha(body))
        _pcg_observer.end("outer_audit_binding_record")
        halted = state["status"] == "SAFE_HALT"
        self._snapshot = LifecycleSnapshot(
            revision=self._snapshot.revision + 1,
            max_active_contributions=self.max_active_contributions,
            max_contribution_budget=self.max_contribution_budget,
            status=state["status"],
            reason=state["reason"],
            failure_code=state["failure_code"],
            availability="UNAVAILABLE" if halted else "AVAILABLE",
            gate="CLOSED" if halted else "OPEN",
            action=state["action"],
            replay_current=state["replay_current"],
            history=history,
            classes=state["classes"],
            root_lifecycle=state["root_lifecycle"],
            effective_versions=state["effective_versions"],
            audit_effective_versions=state["audit_effective_versions"],
            risk_score=state["risk_score"],
            contribution_budget=state["contribution_budget"],
            processing_spend=state["processing_spend"],
            duplicate_count=state["duplicate_count"],
            stale_count=state["stale_count"],
            eliminated_count=state["eliminated_count"],
            rebuild_count=state["rebuild_count"],
            runtime_scientific_hash=state["runtime_scientific_hash"],
            runtime_ledger_head=state["runtime_ledger_head"],
            scientific_binding=after_binding,
            ledger=self._snapshot.ledger + (record,),
            ledger_head=record.record_hash,
        )
        if fault == "POST_COMMIT_CRASH":
            raise PostCommitCrash("POST_COMMIT_CRASH")
        return LifecycleResult(self._snapshot.status, self._snapshot)

    @classmethod
    def recover(cls, snapshot: LifecycleSnapshot) -> LifecycleEngine:
        replayed = cls.replay(
            snapshot.history,
            max_active_contributions=snapshot.max_active_contributions,
            max_contribution_budget=snapshot.max_contribution_budget,
        )
        if replayed.scientific_binding != snapshot.scientific_binding:
            raise LifecycleEngineError("CHECKPOINT_SCIENTIFIC_BINDING_MISMATCH")
        if (
            replayed.ledger_head != snapshot.ledger_head
            or replayed.runtime_scientific_hash != snapshot.runtime_scientific_hash
            or replayed.runtime_ledger_head != snapshot.runtime_ledger_head
        ):
            raise LifecycleEngineError("CHECKPOINT_LEDGER_BINDING_MISMATCH")
        if replayed != snapshot:
            raise LifecycleEngineError("CHECKPOINT_SEMANTIC_STATE_MISMATCH")
        engine = cls(
            max_active_contributions=snapshot.max_active_contributions,
            max_contribution_budget=snapshot.max_contribution_budget,
        )
        engine._snapshot = snapshot
        return engine

    @classmethod
    def replay(
        cls,
        actions: Iterable[Mapping[str, Any] | LifecycleAction],
        *,
        max_active_contributions: int = 1_000_000,
        max_contribution_budget: float = 1_000_000.0,
    ) -> LifecycleSnapshot:
        engine = cls(
            max_active_contributions=max_active_contributions,
            max_contribution_budget=max_contribution_budget,
        )
        for action in actions:
            cleaned = (
                {key: item for key, item in action.items() if key != "fault"}
                if isinstance(action, Mapping)
                else action
            )
            engine.apply(cleaned)
        return engine.snapshot


def project_snapshot(snapshot: LifecycleSnapshot) -> dict[str, Any]:
    halted = snapshot.status == "SAFE_HALT"
    audit_classes = [
        {**asdict(row), "roots": list(row.roots)} for row in snapshot.classes
    ]
    return {
        "authority": snapshot.authority,
        "status": snapshot.status,
        "reason": snapshot.reason,
        "failure_code": snapshot.failure_code,
        "availability": snapshot.availability,
        "gate": snapshot.gate,
        "action": snapshot.action,
        "replay_current": snapshot.replay_current,
        "risk_score": snapshot.risk_score,
        "contribution_budget": snapshot.contribution_budget,
        "processing_spend": snapshot.processing_spend,
        "duplicate_count": snapshot.duplicate_count,
        "stale_count": snapshot.stale_count,
        "eliminated_count": snapshot.eliminated_count,
        "rebuild_count": snapshot.rebuild_count,
        "root_lifecycle": [list(row) for row in snapshot.root_lifecycle],
        "effective_versions": [list(row) for row in snapshot.effective_versions],
        "audit_effective_versions": [
            list(row) for row in snapshot.audit_effective_versions
        ],
        "runtime_scientific_hash": snapshot.runtime_scientific_hash,
        "runtime_ledger_head": snapshot.runtime_ledger_head,
        "scientific_binding": snapshot.scientific_binding,
        "ledger_head": snapshot.ledger_head,
        "audit_classes": audit_classes,
        "classes": [] if halted else audit_classes,
    }


def run_lifecycle(
    actions: Iterable[Mapping[str, Any] | LifecycleAction],
    *,
    max_active_contributions: int = 1_000_000,
    max_contribution_budget: float = 1_000_000.0,
) -> LifecycleSnapshot:
    return LifecycleEngine.replay(
        actions,
        max_active_contributions=max_active_contributions,
        max_contribution_budget=max_contribution_budget,
    )


__all__ = [
    "OPS",
    "CanonicalClass",
    "CasRevisionConflict",
    "LifecycleAction",
    "LifecycleEngine",
    "LifecycleEngineError",
    "LifecycleLedgerRecord",
    "LifecycleResult",
    "LifecycleSnapshot",
    "PostCommitCrash",
    "PreCommitCrash",
    "action_sort_key",
    "normalize_action",
    "project_snapshot",
    "run_lifecycle",
]
