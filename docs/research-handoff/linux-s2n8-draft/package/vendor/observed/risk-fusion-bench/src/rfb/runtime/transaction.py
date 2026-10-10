"""Atomic candidate/CAS transactions over immutable runtime snapshots."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from threading import RLock
from typing import ClassVar, Iterable, Mapping

from .. import dst, temporal
from ..contracts.canonical_json import canonical_bytes, sha256_hex
from .ledger import AppendOnlyLedger, LedgerRecord
from .state import (
    ActionState,
    ChargeFact,
    ContributionToken,
    Event,
    GateState,
    Root,
    RuntimeState,
    Version,
    charge_id_for,
    contribution_token_for,
    freeze_mass,
    mass_dict,
    processing_token_for,
)


class TransactionStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    ALTERNATE_VIEW_AUDIT = "ALTERNATE_VIEW_AUDIT"
    STALE_VERSION_AUDIT = "STALE_VERSION_AUDIT"
    DUPLICATE_AUDIT = "DUPLICATE_AUDIT"
    EVENT_ID_EQUIVOCATION = "EVENT_ID_EQUIVOCATION"
    HALTED_AUDIT = "HALTED_AUDIT"
    BUDGET_CAP_AUDIT = "BUDGET_CAP_AUDIT"
    FULL_CONFLICT_AUDIT = "FULL_CONFLICT_AUDIT"
    ROOT_IDENTITY_CONFLICT_AUDIT = "ROOT_IDENTITY_CONFLICT_AUDIT"


class FailurePoint(str, Enum):
    READ = "read"
    PROCESSING_TOKEN = "processing_token"
    BELIEF = "belief"
    BUDGET = "budget"
    AVAILABILITY = "availability"
    GATE = "gate"
    ACTION = "action"
    LEDGER_SEAL = "ledger_seal"
    PRE_CAS = "pre_cas"
    POST_CAS_ACK_LOSS = "post_cas_ack_loss"


class TransactionError(RuntimeError):
    """Base error for candidate construction and commit failures."""


class InjectedFailure(TransactionError):
    def __init__(self, point: FailurePoint):
        self.point = point
        super().__init__(f"INJECTED_FAILURE:{point.value}")


class PostCommitAckLost(TransactionError):
    def __init__(self):
        super().__init__("POST_CAS_ACK_LOSS")


class CasConflictError(TransactionError):
    def __init__(self):
        super().__init__("CAS_CONFLICT")


class BudgetExceededError(TransactionError):
    def __init__(self):
        super().__init__("BUDGET_CAP")


class RootIdentityConflictError(TransactionError):
    def __init__(self):
        super().__init__("ROOT_IDENTITY_CONFLICT")


class FullConflictError(TransactionError):
    def __init__(self):
        super().__init__("FULL_CONFLICT")


class FormalRunnerRejected(TransactionError):
    pass


def _normalize_failure_point(value: FailurePoint | str | None) -> FailurePoint | None:
    if value is None or isinstance(value, FailurePoint):
        return value
    return FailurePoint(value)


def _inject(selected: FailurePoint | None, point: FailurePoint) -> None:
    if selected is point:
        raise InjectedFailure(point)


def _combine_without_full_conflict(tokens: Iterable[ContributionToken]):
    belief = dst.vacuous()
    for token in sorted(tokens, key=lambda item: (item.root_id, item.token_id)):
        candidate = mass_dict(token.mass)
        if dst.conflict_coefficient(belief, candidate) >= 1.0 - 1e-12:
            raise FullConflictError()
        belief = dst.dempster_combine(belief, candidate)
    return freeze_mass(belief)


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    state: RuntimeState
    ledger: AppendOnlyLedger
    revision: int = 0

    def __post_init__(self) -> None:
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise ValueError("revision must be a non-negative integer")
        if self.revision != len(self.ledger.records):
            raise ValueError("revision must equal the committed ledger length")
        if not self.ledger.validate():
            raise ValueError("ledger hash chain is invalid")
        genesis_hash = RuntimeState.initial(
            budget_total=self.state.budget_total
        ).scientific_hash
        if self.revision == 0:
            if self.state.scientific_hash != genesis_hash:
                raise ValueError(
                    "revision-zero snapshot must bind the canonical genesis state"
                )
        else:
            if self.ledger.records[0].before_scientific_hash != genesis_hash:
                raise ValueError("ledger does not bind the canonical snapshot genesis")
            if (
                self.ledger.records[-1].after_scientific_hash
                != self.state.scientific_hash
            ):
                raise ValueError(
                    "ledger tail does not bind the snapshot scientific state"
                )

    @classmethod
    def genesis(cls, *, budget_total: float | int = 1_000_000) -> "RuntimeSnapshot":
        return cls(
            RuntimeState.initial(budget_total=budget_total), AppendOnlyLedger(), 0
        )

    @property
    def scientific_hash(self) -> str:
        return self.state.scientific_hash

    @property
    def snapshot_hash(self) -> str:
        return sha256_hex(
            canonical_bytes(
                {
                    "revision": self.revision,
                    "scientific_hash": self.scientific_hash,
                    "ledger_head": self.ledger.head_hash,
                }
            )
        )

    @property
    def state_hash(self) -> str:
        """Aggregate replay hash, distinct from ``scientific_hash``."""

        return self.snapshot_hash


@dataclass(frozen=True, slots=True)
class CandidateTransaction:
    event: Event
    event_hash: str
    processing_token: str
    status: TransactionStatus
    expected_revision: int
    expected_scientific_hash: str
    expected_ledger_head: str
    next_state: RuntimeState
    next_ledger: AppendOnlyLedger

    def __post_init__(self) -> None:
        self.assert_record_binding()

    def assert_record_binding(self) -> None:
        if not isinstance(self.event, Event):
            raise ValueError("candidate event must be an Event")
        if not isinstance(self.status, TransactionStatus):
            raise ValueError("candidate status must be a TransactionStatus")
        if (
            not isinstance(self.expected_revision, int)
            or isinstance(self.expected_revision, bool)
            or self.expected_revision < 0
        ):
            raise ValueError(
                "candidate expected_revision must be a non-negative integer"
            )
        if self.event_hash != self.event.event_hash:
            raise ValueError("candidate event_hash does not bind the event")
        if self.processing_token != processing_token_for(self.event.event_id):
            raise ValueError("candidate processing_token does not bind the event")
        if len(self.next_ledger.records) != self.expected_revision + 1:
            raise ValueError("candidate ledger length does not bind expected_revision")
        if not self.next_ledger.validate():
            raise ValueError("candidate ledger hash/scientific chain is invalid")
        record = self.record
        if record.sequence != self.expected_revision + 1:
            raise ValueError(
                "candidate record sequence does not bind expected_revision"
            )
        if record.record_type != self.status.value:
            raise ValueError("candidate status does not bind the ledger record")
        if record.event_id != self.event.event_id:
            raise ValueError("candidate event does not bind the ledger record")
        if record.event_hash != self.event_hash:
            raise ValueError("candidate event_hash does not bind the ledger record")
        if record.processing_token != self.processing_token:
            raise ValueError(
                "candidate processing_token does not bind the ledger record"
            )
        if record.before_scientific_hash != self.expected_scientific_hash:
            raise ValueError(
                "candidate expected scientific hash does not bind the ledger record"
            )
        if record.after_scientific_hash != self.next_state.scientific_hash:
            raise ValueError("candidate next state does not bind the ledger record")
        if record.previous_hash != self.expected_ledger_head:
            raise ValueError(
                "candidate expected ledger head does not bind the ledger record"
            )

    @property
    def record(self) -> LedgerRecord:
        return self.next_ledger.records[-1]


def _require_semantic_binding(condition: bool, label: str) -> None:
    if not condition:
        raise ValueError(f"candidate semantic binding failed: {label}")


def _require_detail_binding(
    candidate: CandidateTransaction,
    expected: Mapping[str, object],
) -> None:
    _require_semantic_binding(
        canonical_bytes(dict(candidate.record.details)) == canonical_bytes(expected),
        "ledger details do not bind the event/current/next state",
    )


def _assert_candidate_semantics(
    current: RuntimeSnapshot,
    candidate: CandidateTransaction,
) -> None:
    state = current.state
    event = candidate.event
    next_state = candidate.next_state
    status = candidate.status

    if state.availability == "UNAVAILABLE":
        _require_semantic_binding(
            status is TransactionStatus.HALTED_AUDIT,
            "unavailable runtime must emit HALTED_AUDIT",
        )
        _require_semantic_binding(
            next_state == state,
            "HALTED_AUDIT must preserve complete state",
        )
        halt_reason = (
            "EVENT_ID_EQUIVOCATION"
            if state.gate.reason == "EVENT_ID_EQUIVOCATION"
            else "RUNTIME_UNAVAILABLE"
        )
        _require_detail_binding(
            candidate,
            {
                "charge_applied": False,
                "reason": halt_reason,
                "scientific_state_changed": False,
            },
        )
        return

    _require_semantic_binding(
        state.availability == "AVAILABLE",
        "current availability is not classifiable",
    )
    committed_hash = state.event_hash_for(event.event_id)
    if committed_hash == candidate.event_hash:
        _require_semantic_binding(
            status is TransactionStatus.DUPLICATE_AUDIT,
            "exact event duplicate must emit DUPLICATE_AUDIT",
        )
        _require_semantic_binding(
            next_state == state,
            "DUPLICATE_AUDIT must preserve complete state",
        )
        _require_detail_binding(
            candidate,
            {
                "charge_applied": False,
                "reason": "EXACT_EVENT_DUPLICATE",
                "scientific_state_changed": False,
            },
        )
        return

    if committed_hash is not None:
        _require_semantic_binding(
            status is TransactionStatus.EVENT_ID_EQUIVOCATION,
            "event-id hash conflict must emit EVENT_ID_EQUIVOCATION",
        )
        expected_state = replace(
            state,
            availability="UNAVAILABLE",
            gate=GateState("CLOSED", "EVENT_ID_EQUIVOCATION"),
            action=ActionState(
                "FAIL_CLOSED",
                event.event_id,
                "EVENT_ID_EQUIVOCATION",
            ),
        )
        _require_semantic_binding(
            next_state == expected_state,
            "EVENT_ID_EQUIVOCATION must preserve contributions and fail closed atomically",
        )
        _require_detail_binding(
            candidate,
            {
                "belief_changed": False,
                "budget_changed": False,
                "charge_applied": False,
                "committed_event_hash": committed_hash,
                "received_event_hash": candidate.event_hash,
                "reason": "EVENT_ID_EQUIVOCATION",
                "scientific_state_changed": (
                    expected_state.scientific_hash != state.scientific_hash
                ),
            },
        )
        return

    _require_semantic_binding(
        candidate.processing_token not in state.processing_tokens,
        "new event reuses a committed processing token",
    )
    next_event_hashes = state.event_hashes + ((event.event_id, candidate.event_hash),)
    next_processing_tokens = state.processing_tokens + (candidate.processing_token,)
    charge = ChargeFact(
        charge_id=charge_id_for(candidate.processing_token),
        processing_token=candidate.processing_token,
        event_id=event.event_id,
        resource_type="PROCESSING",
        amount=event.processing_cost,
    )
    next_charges = state.charge_facts + (charge,)

    roots = {item.root_id: item for item in state.roots}
    versions = dict(state.versions)
    tokens = {item.root_id: item for item in state.contribution_tokens}
    existing_root = roots.get(event.root.root_id)
    expected_status: TransactionStatus
    reason: str | None = None

    if existing_root is not None and existing_root != event.root:
        expected_status = TransactionStatus.ROOT_IDENTITY_CONFLICT_AUDIT
        reason = "ROOT_IDENTITY_CONFLICT"
        failure_roots = roots
        failure_versions = versions
    else:
        current_version = versions.get(event.root.root_id)
        if current_version is None:
            roots[event.root.root_id] = event.root
            versions[event.root.root_id] = event.version
        failure_roots = dict(roots)
        failure_versions = dict(versions)

        if current_version is None:
            tokens[event.root.root_id] = ContributionToken(
                token_id=contribution_token_for(event.root.root_id),
                root_id=event.root.root_id,
                first_event_id=event.event_id,
                effective_event_id=event.event_id,
                bundle_version=event.version.bundle_version,
                amount=event.contribution_amount,
                mass=event.mass,
            )
            expected_status = TransactionStatus.ACCEPTED
            action_status = "ACCEPT_CONTRIBUTION"
        elif event.version.bundle_version > current_version.bundle_version:
            previous = tokens.get(event.root.root_id)
            tokens[event.root.root_id] = ContributionToken(
                token_id=(
                    previous.token_id
                    if previous is not None
                    else contribution_token_for(event.root.root_id)
                ),
                root_id=event.root.root_id,
                first_event_id=(
                    previous.first_event_id if previous is not None else event.event_id
                ),
                effective_event_id=event.event_id,
                bundle_version=event.version.bundle_version,
                amount=(
                    previous.amount
                    if previous is not None
                    else event.contribution_amount
                ),
                mass=event.mass,
            )
            versions[event.root.root_id] = event.version
            expected_status = TransactionStatus.SUPERSEDED
            action_status = "SUPERSEDE_CONTRIBUTION"
        elif event.version.bundle_version == current_version.bundle_version:
            expected_status = TransactionStatus.ALTERNATE_VIEW_AUDIT
            action_status = "AUDIT_ONLY"
        else:
            expected_status = TransactionStatus.STALE_VERSION_AUDIT
            action_status = "AUDIT_ONLY"

        try:
            next_belief = _combine_without_full_conflict(tokens.values())
        except FullConflictError:
            expected_status = TransactionStatus.FULL_CONFLICT_AUDIT
            reason = "FULL_CONFLICT"
        else:
            next_budget_used = sum(token.amount for token in tokens.values())
            if next_budget_used > state.budget_total:
                expected_status = TransactionStatus.BUDGET_CAP_AUDIT
                reason = "BUDGET_CAP"

    if reason is not None:
        expected_state = RuntimeState(
            belief=state.belief,
            roots=tuple(failure_roots.values()),
            versions=tuple(failure_versions.items()),
            contribution_tokens=state.contribution_tokens,
            charge_facts=next_charges,
            event_hashes=next_event_hashes,
            processing_tokens=next_processing_tokens,
            budget_total=state.budget_total,
            budget_used=state.budget_used,
            availability=state.availability,
            gate=GateState("CLOSED", reason),
            action=ActionState("FAIL_CLOSED", event.event_id, reason),
        )
        expected_details = {
            "belief_changed": False,
            "budget_changed": False,
            "budget_used": expected_state.budget_used,
            "charge_applied": True,
            "contribution_token": None,
            "processing_charge": event.processing_cost,
            "processing_spend": expected_state.processing_spend,
            "reason": reason,
            "scientific_state_changed": (
                expected_state.scientific_hash != state.scientific_hash
            ),
        }
    else:
        effective_token = tokens.get(event.root.root_id)
        if (
            expected_status
            in {
                TransactionStatus.ALTERNATE_VIEW_AUDIT,
                TransactionStatus.STALE_VERSION_AUDIT,
            }
            and effective_token is None
        ):
            next_gate = GateState("CLOSED", "NONCONTRIBUTING_ROOT")
        else:
            next_gate = GateState("OPEN")
        expected_state = RuntimeState(
            belief=next_belief,
            roots=tuple(roots.values()),
            versions=tuple(versions.items()),
            contribution_tokens=tuple(tokens.values()),
            charge_facts=next_charges,
            event_hashes=next_event_hashes,
            processing_tokens=next_processing_tokens,
            budget_total=state.budget_total,
            budget_used=next_budget_used,
            availability="AVAILABLE",
            gate=next_gate,
            action=ActionState(action_status, event.event_id),
        )
        expected_details = {
            "belief_changed": expected_state.belief != state.belief,
            "budget_used": expected_state.budget_used,
            "charge_applied": True,
            "contribution_token": (
                effective_token.token_id if effective_token is not None else None
            ),
            "processing_charge": event.processing_cost,
            "processing_spend": expected_state.processing_spend,
            "scientific_state_changed": (
                expected_state.scientific_hash != state.scientific_hash
            ),
        }

    _require_semantic_binding(
        status is expected_status,
        "candidate status does not match event/root/version/domain semantics",
    )
    _require_semantic_binding(
        next_state == expected_state,
        "next state does not bind exact resource, contribution, version, and control deltas",
    )
    _require_detail_binding(candidate, expected_details)


@dataclass(frozen=True, slots=True)
class TransactionResult:
    status: TransactionStatus
    snapshot: RuntimeSnapshot
    record: LedgerRecord

    @property
    def scientific_state_changed(self) -> bool:
        return self.record.before_scientific_hash != self.record.after_scientific_hash


class RuntimeStore:
    """One aggregate pointer protected by a three-part compare-and-swap guard."""

    def __init__(
        self,
        snapshot: RuntimeSnapshot | None = None,
        *,
        budget_total: float | int = 1_000_000,
    ):
        self._snapshot = snapshot or RuntimeSnapshot.genesis(budget_total=budget_total)
        self._lock = RLock()

    def read(self) -> RuntimeSnapshot:
        with self._lock:
            return self._snapshot

    def compare_and_swap(self, candidate: CandidateTransaction) -> RuntimeSnapshot:
        with self._lock:
            candidate.assert_record_binding()
            current = self._snapshot
            if (
                current.revision != candidate.expected_revision
                or current.scientific_hash != candidate.expected_scientific_hash
                or current.ledger.head_hash != candidate.expected_ledger_head
            ):
                raise CasConflictError()
            if candidate.next_ledger.records[:-1] != current.ledger.records:
                raise ValueError("candidate ledger is not an append-only extension")
            if not candidate.next_ledger.validate():
                raise ValueError("candidate ledger hash chain is invalid")
            record = candidate.record
            if record.before_scientific_hash != current.scientific_hash:
                raise ValueError(
                    "candidate record does not bind the current scientific hash"
                )
            if record.after_scientific_hash != candidate.next_state.scientific_hash:
                raise ValueError(
                    "candidate record does not bind the next scientific hash"
                )
            _assert_candidate_semantics(current, candidate)
            committed = RuntimeSnapshot(
                state=candidate.next_state,
                ledger=candidate.next_ledger,
                revision=current.revision + 1,
            )
            self._snapshot = committed
            return committed


class RuntimeKernel:
    """Prepare complete candidates locally, then commit by a single CAS swap."""

    def __init__(
        self,
        *,
        budget_total: float | int = 1_000_000,
        store: RuntimeStore | None = None,
        max_cas_retries: int = 3,
    ):
        if max_cas_retries < 0:
            raise ValueError("max_cas_retries must be non-negative")
        self.store = store or RuntimeStore(budget_total=budget_total)
        self.max_cas_retries = max_cas_retries

    @property
    def snapshot(self) -> RuntimeSnapshot:
        return self.store.read()

    @staticmethod
    def _candidate(
        *,
        base: RuntimeSnapshot,
        event: Event,
        event_hash: str,
        processing_token: str,
        status: TransactionStatus,
        next_state: RuntimeState,
        details: dict,
    ) -> CandidateTransaction:
        next_ledger = base.ledger.append(
            record_type=status.value,
            event_id=event.event_id,
            event_hash=event_hash,
            processing_token=processing_token,
            before_scientific_hash=base.scientific_hash,
            after_scientific_hash=next_state.scientific_hash,
            details=details,
        )
        return CandidateTransaction(
            event=event,
            event_hash=event_hash,
            processing_token=processing_token,
            status=status,
            expected_revision=base.revision,
            expected_scientific_hash=base.scientific_hash,
            expected_ledger_head=base.ledger.head_hash,
            next_state=next_state,
            next_ledger=next_ledger,
        )

    def _domain_failure_candidate(
        self,
        *,
        base: RuntimeSnapshot,
        event: Event,
        event_hash: str,
        processing_token: str,
        status: TransactionStatus,
        reason: str,
        roots: dict[str, Root],
        versions: dict[str, Version],
        next_event_hashes: tuple[tuple[str, str], ...],
        next_processing_tokens: tuple[str, ...],
        next_charges: tuple[ChargeFact, ...],
        selected: FailurePoint | None,
    ) -> CandidateTransaction:
        state = base.state
        _inject(selected, FailurePoint.BELIEF)
        _inject(selected, FailurePoint.BUDGET)
        next_availability = state.availability
        _inject(selected, FailurePoint.AVAILABILITY)
        next_gate = GateState("CLOSED", reason)
        _inject(selected, FailurePoint.GATE)
        next_action = ActionState("FAIL_CLOSED", event.event_id, reason)
        _inject(selected, FailurePoint.ACTION)
        next_state = RuntimeState(
            belief=state.belief,
            roots=tuple(roots.values()),
            versions=tuple(versions.items()),
            contribution_tokens=state.contribution_tokens,
            charge_facts=next_charges,
            event_hashes=next_event_hashes,
            processing_tokens=next_processing_tokens,
            budget_total=state.budget_total,
            budget_used=state.budget_used,
            availability=next_availability,
            gate=next_gate,
            action=next_action,
        )
        candidate = self._candidate(
            base=base,
            event=event,
            event_hash=event_hash,
            processing_token=processing_token,
            status=status,
            next_state=next_state,
            details={
                "belief_changed": False,
                "budget_changed": False,
                "budget_used": state.budget_used,
                "charge_applied": True,
                "contribution_token": None,
                "processing_charge": event.processing_cost,
                "processing_spend": next_state.processing_spend,
                "reason": reason,
                "scientific_state_changed": (
                    next_state.scientific_hash != state.scientific_hash
                ),
            },
        )
        _inject(selected, FailurePoint.LEDGER_SEAL)
        _inject(selected, FailurePoint.PRE_CAS)
        return candidate

    def prepare(
        self,
        event: Event,
        *,
        failure_at: FailurePoint | str | None = None,
    ) -> CandidateTransaction:
        selected = _normalize_failure_point(failure_at)
        base = self.store.read()
        _inject(selected, FailurePoint.READ)
        state = base.state
        event_hash = event.event_hash
        processing_token = processing_token_for(event.event_id)

        if state.availability == "UNAVAILABLE":
            halted_reason = (
                "EVENT_ID_EQUIVOCATION"
                if state.gate.reason == "EVENT_ID_EQUIVOCATION"
                else "RUNTIME_UNAVAILABLE"
            )
            candidate = self._candidate(
                base=base,
                event=event,
                event_hash=event_hash,
                processing_token=processing_token,
                status=TransactionStatus.HALTED_AUDIT,
                next_state=state,
                details={
                    "charge_applied": False,
                    "scientific_state_changed": False,
                    "reason": halted_reason,
                },
            )
            _inject(selected, FailurePoint.LEDGER_SEAL)
            _inject(selected, FailurePoint.PRE_CAS)
            return candidate

        committed_hash = state.event_hash_for(event.event_id)

        if committed_hash == event_hash:
            candidate = self._candidate(
                base=base,
                event=event,
                event_hash=event_hash,
                processing_token=processing_token,
                status=TransactionStatus.DUPLICATE_AUDIT,
                next_state=state,
                details={
                    "charge_applied": False,
                    "scientific_state_changed": False,
                    "reason": "EXACT_EVENT_DUPLICATE",
                },
            )
            _inject(selected, FailurePoint.LEDGER_SEAL)
            _inject(selected, FailurePoint.PRE_CAS)
            return candidate

        if committed_hash is not None:
            reason = "EVENT_ID_EQUIVOCATION"
            next_availability = "UNAVAILABLE"
            _inject(selected, FailurePoint.AVAILABILITY)
            next_gate = GateState("CLOSED", reason)
            _inject(selected, FailurePoint.GATE)
            next_action = ActionState("FAIL_CLOSED", event.event_id, reason)
            _inject(selected, FailurePoint.ACTION)
            next_state = replace(
                state,
                availability=next_availability,
                gate=next_gate,
                action=next_action,
            )
            candidate = self._candidate(
                base=base,
                event=event,
                event_hash=event_hash,
                processing_token=processing_token,
                status=TransactionStatus.EVENT_ID_EQUIVOCATION,
                next_state=next_state,
                details={
                    "belief_changed": False,
                    "budget_changed": False,
                    "charge_applied": False,
                    "committed_event_hash": committed_hash,
                    "received_event_hash": event_hash,
                    "reason": reason,
                    "scientific_state_changed": True,
                },
            )
            _inject(selected, FailurePoint.LEDGER_SEAL)
            _inject(selected, FailurePoint.PRE_CAS)
            return candidate

        if processing_token in state.processing_tokens:
            raise ValueError("processing token exists without its event-id binding")

        next_event_hashes = state.event_hashes + ((event.event_id, event_hash),)
        next_processing_tokens = state.processing_tokens + (processing_token,)
        charge = ChargeFact(
            charge_id=charge_id_for(processing_token),
            processing_token=processing_token,
            event_id=event.event_id,
            resource_type="PROCESSING",
            amount=event.processing_cost,
        )
        next_charges = state.charge_facts + (charge,)
        _inject(selected, FailurePoint.PROCESSING_TOKEN)

        roots = {item.root_id: item for item in state.roots}
        versions = dict(state.versions)
        tokens = {item.root_id: item for item in state.contribution_tokens}
        existing_root = roots.get(event.root.root_id)
        if existing_root is not None and existing_root != event.root:
            return self._domain_failure_candidate(
                base=base,
                event=event,
                event_hash=event_hash,
                processing_token=processing_token,
                status=TransactionStatus.ROOT_IDENTITY_CONFLICT_AUDIT,
                reason="ROOT_IDENTITY_CONFLICT",
                roots=roots,
                versions=versions,
                next_event_hashes=next_event_hashes,
                next_processing_tokens=next_processing_tokens,
                next_charges=next_charges,
                selected=selected,
            )

        current_version = versions.get(event.root.root_id)
        if current_version is None:
            roots[event.root.root_id] = event.root
            versions[event.root.root_id] = event.version
        failure_roots = dict(roots)
        failure_versions = dict(versions)

        if current_version is None:
            tokens[event.root.root_id] = ContributionToken(
                token_id=contribution_token_for(event.root.root_id),
                root_id=event.root.root_id,
                first_event_id=event.event_id,
                effective_event_id=event.event_id,
                bundle_version=event.version.bundle_version,
                amount=event.contribution_amount,
                mass=event.mass,
            )
            status = TransactionStatus.ACCEPTED
            action_status = "ACCEPT_CONTRIBUTION"
        elif event.version.bundle_version > current_version.bundle_version:
            previous = tokens.get(event.root.root_id)
            tokens[event.root.root_id] = ContributionToken(
                token_id=(
                    previous.token_id
                    if previous is not None
                    else contribution_token_for(event.root.root_id)
                ),
                root_id=event.root.root_id,
                first_event_id=(
                    previous.first_event_id if previous is not None else event.event_id
                ),
                effective_event_id=event.event_id,
                bundle_version=event.version.bundle_version,
                amount=(
                    previous.amount
                    if previous is not None
                    else event.contribution_amount
                ),
                mass=event.mass,
            )
            versions[event.root.root_id] = event.version
            status = TransactionStatus.SUPERSEDED
            action_status = "SUPERSEDE_CONTRIBUTION"
        elif event.version.bundle_version == current_version.bundle_version:
            status = TransactionStatus.ALTERNATE_VIEW_AUDIT
            action_status = "AUDIT_ONLY"
        else:
            status = TransactionStatus.STALE_VERSION_AUDIT
            action_status = "AUDIT_ONLY"

        try:
            next_belief = _combine_without_full_conflict(tokens.values())
        except FullConflictError:
            return self._domain_failure_candidate(
                base=base,
                event=event,
                event_hash=event_hash,
                processing_token=processing_token,
                status=TransactionStatus.FULL_CONFLICT_AUDIT,
                reason="FULL_CONFLICT",
                roots=failure_roots,
                versions=failure_versions,
                next_event_hashes=next_event_hashes,
                next_processing_tokens=next_processing_tokens,
                next_charges=next_charges,
                selected=selected,
            )
        _inject(selected, FailurePoint.BELIEF)

        next_budget_used = sum(token.amount for token in tokens.values())
        if next_budget_used > state.budget_total:
            return self._domain_failure_candidate(
                base=base,
                event=event,
                event_hash=event_hash,
                processing_token=processing_token,
                status=TransactionStatus.BUDGET_CAP_AUDIT,
                reason="BUDGET_CAP",
                roots=failure_roots,
                versions=failure_versions,
                next_event_hashes=next_event_hashes,
                next_processing_tokens=next_processing_tokens,
                next_charges=next_charges,
                selected=selected,
            )
        _inject(selected, FailurePoint.BUDGET)

        next_availability = "AVAILABLE"
        _inject(selected, FailurePoint.AVAILABILITY)
        effective_token = tokens.get(event.root.root_id)
        if (
            status
            in {
                TransactionStatus.ALTERNATE_VIEW_AUDIT,
                TransactionStatus.STALE_VERSION_AUDIT,
            }
            and effective_token is None
        ):
            next_gate = GateState("CLOSED", "NONCONTRIBUTING_ROOT")
        else:
            next_gate = GateState("OPEN")
        _inject(selected, FailurePoint.GATE)
        next_action = ActionState(action_status, event.event_id)
        _inject(selected, FailurePoint.ACTION)

        next_state = RuntimeState(
            belief=next_belief,
            roots=tuple(roots.values()),
            versions=tuple(versions.items()),
            contribution_tokens=tuple(tokens.values()),
            charge_facts=next_charges,
            event_hashes=next_event_hashes,
            processing_tokens=next_processing_tokens,
            budget_total=state.budget_total,
            budget_used=next_budget_used,
            availability=next_availability,
            gate=next_gate,
            action=next_action,
        )
        candidate = self._candidate(
            base=base,
            event=event,
            event_hash=event_hash,
            processing_token=processing_token,
            status=status,
            next_state=next_state,
            details={
                "belief_changed": next_belief != state.belief,
                "budget_used": next_budget_used,
                "charge_applied": True,
                "contribution_token": (
                    effective_token.token_id if effective_token is not None else None
                ),
                "processing_charge": event.processing_cost,
                "processing_spend": next_state.processing_spend,
                "scientific_state_changed": next_state.scientific_hash
                != state.scientific_hash,
            },
        )
        _inject(selected, FailurePoint.LEDGER_SEAL)
        _inject(selected, FailurePoint.PRE_CAS)
        return candidate

    def commit(self, candidate: CandidateTransaction) -> TransactionResult:
        snapshot = self.store.compare_and_swap(candidate)
        return TransactionResult(candidate.status, snapshot, candidate.record)

    def process(
        self,
        event: Event,
        *,
        failure_at: FailurePoint | str | None = None,
    ) -> TransactionResult:
        selected = _normalize_failure_point(failure_at)
        for attempt in range(self.max_cas_retries + 1):
            candidate = self.prepare(event, failure_at=selected)
            try:
                result = self.commit(candidate)
                break
            except CasConflictError:
                if attempt >= self.max_cas_retries:
                    raise
        if selected is FailurePoint.POST_CAS_ACK_LOSS:
            raise PostCommitAckLost()
        return result


@dataclass(frozen=True, slots=True)
class LegacyEvidenceAdapter:
    """Compatibility adapter that is mechanically ineligible for formal runners."""

    formal_eligible: ClassVar[bool] = False

    def to_event(
        self,
        evidence: temporal.Evidence,
        *,
        event_id: str | None = None,
        root_id: str | None = None,
        bundle_version: int | None = None,
    ) -> Event:
        resolved_event_id = event_id or evidence.event_id
        if resolved_event_id is None:
            resolved_event_id = sha256_hex(
                canonical_bytes(
                    {
                        "mass": [list(item) for item in sorted(evidence.m.items())],
                        "source_id": evidence.source_id,
                        "t_gen": evidence.t_gen,
                    }
                )
            )
        resolved_root_id = root_id or evidence.root_id or evidence.source_id
        resolved_version = (
            bundle_version
            if bundle_version is not None
            else (evidence.bundle_version if evidence.bundle_version is not None else 0)
        )
        discounted = dst.discount(evidence.m, evidence.reliability)
        return Event.create(
            event_id=resolved_event_id,
            root=Root(resolved_root_id, "LEGACY"),
            version=Version(int(resolved_version)),
            mass=discounted,
            occurred_at=evidence.t_gen,
            view_id=evidence.view_id or "LEGACY",
        )

    def submit(
        self,
        kernel: RuntimeKernel,
        evidence: temporal.Evidence,
        *,
        mode: str = "NON_FORMAL",
        event_id: str | None = None,
        root_id: str | None = None,
        bundle_version: int | None = None,
    ) -> TransactionResult:
        normalized_mode = mode.upper()
        if normalized_mode == "FORMAL":
            raise FormalRunnerRejected("LEGACY_ADAPTER_FORMAL_FORBIDDEN")
        if normalized_mode not in {"CANARY", "NON_FORMAL"}:
            raise ValueError(f"unsupported legacy adapter mode {mode!r}")
        event = self.to_event(
            evidence,
            event_id=event_id,
            root_id=root_id,
            bundle_version=bundle_version,
        )
        return kernel.process(event)


def replay_events(
    events: Iterable[Event],
    *,
    budget_total: float | int = 1_000_000,
) -> RuntimeSnapshot:
    """Replay a canonical event sequence into a new deterministic aggregate."""

    kernel = RuntimeKernel(budget_total=budget_total)
    for event in events:
        kernel.process(event)
    return kernel.snapshot
