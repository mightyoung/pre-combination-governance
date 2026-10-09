from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rfb import dst  # noqa: E402
from rfb.contracts.canonical_json import canonical_bytes, canonical_text, sha256_hex  # noqa: E402
from rfb.runtime.ledger import AppendOnlyLedger, LedgerRecord  # noqa: E402
from rfb.runtime.state import (  # noqa: E402
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
    processing_token_for,
)
from rfb.runtime.transaction import (  # noqa: E402
    CasConflictError,
    FailurePoint,
    InjectedFailure,
    PostCommitAckLost,
    RuntimeKernel,
    RuntimeSnapshot,
    RuntimeStore,
    TransactionStatus,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def event(
    event_id: str,
    root_id: str,
    *,
    root_type: str = "GENERIC",
    version: int = 1,
    mass=None,
    processing_cost: int = 1,
    contribution_amount: float = 1.0,
) -> Event:
    return Event.create(
        event_id=event_id,
        root=Root(root_id, root_type),
        version=Version(version),
        mass=mass if mass is not None else {16: 0.8, dst.THETA: 0.2},
        processing_cost=processing_cost,
        contribution_amount=contribution_amount,
    )


def accepted_details(*, token: str, scientific_state_changed: bool = True) -> dict:
    return {
        "belief_changed": True,
        "budget_used": 1.0,
        "charge_applied": True,
        "contribution_token": token,
        "processing_charge": 1,
        "processing_spend": 1,
        "scientific_state_changed": scientific_state_changed,
    }


def duplicate_details() -> dict:
    return {
        "charge_applied": False,
        "reason": "EXACT_EVENT_DUPLICATE",
        "scientific_state_changed": False,
    }


def forge_candidate_details(candidate, **updates):
    record = candidate.record
    details = {**record.details, **updates}
    forged_record = LedgerRecord.build(
        sequence=record.sequence,
        record_type=record.record_type,
        event_id=record.event_id,
        event_hash=record.event_hash,
        processing_token=record.processing_token,
        before_scientific_hash=record.before_scientific_hash,
        after_scientific_hash=record.after_scientific_hash,
        details=details,
        previous_hash=record.previous_hash,
    )
    forged_ledger = AppendOnlyLedger(
        candidate.next_ledger.records[:-1] + (forged_record,)
    )
    return replace(candidate, next_ledger=forged_ledger)


def test_candidate_metadata_is_bound_during_construction_and_rechecked_at_cas():
    kernel = RuntimeKernel(budget_total=10)
    candidate = kernel.prepare(event("event-1", "root-1"))

    with pytest.raises(ValueError, match="candidate status"):
        replace(candidate, status=TransactionStatus.DUPLICATE_AUDIT)
    with pytest.raises(ValueError, match="candidate event_hash"):
        replace(candidate, event_hash=HASH_A)
    with pytest.raises(ValueError, match="candidate processing_token"):
        replace(candidate, processing_token=HASH_B)

    forged = kernel.prepare(event("event-2", "root-2"))
    object.__setattr__(forged, "status", TransactionStatus.DUPLICATE_AUDIT)
    before = kernel.snapshot
    with pytest.raises(ValueError, match="candidate status"):
        kernel.commit(forged)
    assert kernel.snapshot is before


def test_ledger_closes_record_types_token_formats_and_scientific_continuity():
    token = processing_token_for("event-1")
    contribution_token = contribution_token_for("root-1")

    with pytest.raises(ValueError, match="record_type"):
        LedgerRecord.build(
            sequence=1,
            record_type="OUT_OF_SCHEMA",
            event_id="event-1",
            event_hash=HASH_A,
            processing_token=token,
            before_scientific_hash=HASH_A,
            after_scientific_hash=HASH_B,
            details=accepted_details(token=contribution_token),
            previous_hash="0" * 64,
        )
    with pytest.raises(ValueError, match="processing_token"):
        AppendOnlyLedger().append(
            record_type="ACCEPTED",
            event_id="event-1",
            event_hash=HASH_A,
            processing_token="not-a-token",
            before_scientific_hash=HASH_A,
            after_scientific_hash=HASH_B,
            details=accepted_details(token=contribution_token),
        )

    first = AppendOnlyLedger().append(
        record_type="ACCEPTED",
        event_id="event-1",
        event_hash=HASH_A,
        processing_token=token,
        before_scientific_hash=HASH_A,
        after_scientific_hash=HASH_B,
        details=accepted_details(token=contribution_token),
    )
    discontinuous = first.append(
        record_type="DUPLICATE_AUDIT",
        event_id="event-1",
        event_hash=HASH_A,
        processing_token=token,
        before_scientific_hash=HASH_C,
        after_scientific_hash=HASH_C,
        details=duplicate_details(),
    )
    assert not discontinuous.validate()


def test_snapshot_binds_genesis_and_ledger_tail_to_scientific_state():
    genesis = RuntimeSnapshot.genesis(budget_total=10)
    non_genesis_state = replace(
        genesis.state,
        gate=GateState("CLOSED", "TEST"),
        action=ActionState("FAIL_CLOSED", "event-0", "TEST"),
    )
    with pytest.raises(ValueError, match="genesis"):
        RuntimeSnapshot(non_genesis_state, AppendOnlyLedger(), 0)

    accepted = (
        RuntimeKernel(budget_total=10).process(event("event-1", "root-1")).snapshot
    )
    with pytest.raises(ValueError, match="tail"):
        RuntimeSnapshot(genesis.state, accepted.ledger, accepted.revision)

    wrong_genesis = AppendOnlyLedger().append(
        record_type="ACCEPTED",
        event_id="event-1",
        event_hash=HASH_A,
        processing_token=processing_token_for("event-1"),
        before_scientific_hash=HASH_A,
        after_scientific_hash=genesis.scientific_hash,
        details=accepted_details(token=contribution_token_for("root-1")),
    )
    with pytest.raises(ValueError, match="genesis"):
        RuntimeSnapshot(genesis.state, wrong_genesis, 1)


@pytest.mark.parametrize(
    "point",
    [FailurePoint.AVAILABILITY, FailurePoint.GATE, FailurePoint.ACTION],
)
def test_equivocation_control_state_injections_are_zero_commit(point):
    kernel = RuntimeKernel(budget_total=10)
    kernel.process(event("event-1", "root-1"))
    before = kernel.snapshot
    equivocation = event(
        "event-1",
        "root-1",
        mass={16: 0.95, dst.THETA: 0.05},
    )

    with pytest.raises(InjectedFailure, match=point.value):
        kernel.process(equivocation, failure_at=point)

    assert kernel.snapshot is before


def test_runtime_state_rejects_belief_token_version_and_derived_id_drift():
    ev = event("event-1", "root-1", processing_cost=2)
    processing_token = processing_token_for(ev.event_id)
    token = ContributionToken(
        token_id=contribution_token_for(ev.root.root_id),
        root_id=ev.root.root_id,
        first_event_id=ev.event_id,
        effective_event_id=ev.event_id,
        bundle_version=ev.version.bundle_version,
        amount=ev.contribution_amount,
        mass=ev.mass,
    )
    charge = ChargeFact(
        charge_id=charge_id_for(processing_token),
        processing_token=processing_token,
        event_id=ev.event_id,
        resource_type="PROCESSING",
        amount=ev.processing_cost,
    )
    kwargs = {
        "belief": ev.mass,
        "roots": (ev.root,),
        "versions": ((ev.root.root_id, ev.version),),
        "contribution_tokens": (token,),
        "charge_facts": (charge,),
        "event_hashes": ((ev.event_id, ev.event_hash),),
        "processing_tokens": (processing_token,),
        "budget_total": 10,
        "budget_used": ev.contribution_amount,
    }
    valid = RuntimeState(**kwargs)
    assert valid.processing_spend == ev.processing_cost

    with pytest.raises(ValueError, match="belief"):
        RuntimeState(**{**kwargs, "belief": ((1, 1.0),)})
    with pytest.raises(ValueError, match="token_id"):
        RuntimeState(
            **{
                **kwargs,
                "contribution_tokens": (replace(token, token_id=HASH_A),),
            }
        )
    with pytest.raises(ValueError, match="bundle_version"):
        RuntimeState(
            **{
                **kwargs,
                "contribution_tokens": (replace(token, bundle_version=2),),
            }
        )
    with pytest.raises(ValueError, match="charge_id"):
        RuntimeState(
            **{
                **kwargs,
                "charge_facts": (replace(charge, charge_id=HASH_A),),
            }
        )
    with pytest.raises(ValueError, match="resource_type"):
        RuntimeState(
            **{
                **kwargs,
                "charge_facts": (replace(charge, resource_type="GPU"),),
            }
        )
    with pytest.raises(ValueError, match="event hashes"):
        RuntimeState(
            **{
                **kwargs,
                "event_hashes": kwargs["event_hashes"] + (("uncharged-event", HASH_B),),
            }
        )


def test_budget_used_is_canonicalized_from_commitments_before_cap_check():
    canonical = (
        RuntimeKernel(budget_total=1).prepare(event("event-1", "root-1")).next_state
    )

    near_equal = replace(canonical, budget_used=canonical.budget_used + 5e-13)

    assert near_equal.budget_used == canonical.budget_used == 1.0
    assert near_equal.scientific_hash == canonical.scientific_hash

    over_cap_token = replace(
        canonical.contribution_tokens[0],
        amount=canonical.budget_total + 5e-13,
    )
    with pytest.raises(ValueError, match="budget_used cannot exceed budget_total"):
        replace(
            canonical,
            contribution_tokens=(over_cap_token,),
            budget_used=canonical.budget_total,
        )


def test_typed_details_are_closed_and_sensitive_fields_are_rejected_recursively():
    kwargs = {
        "record_type": "DUPLICATE_AUDIT",
        "event_id": "event-1",
        "event_hash": HASH_A,
        "processing_token": processing_token_for("event-1"),
        "before_scientific_hash": HASH_B,
        "after_scientific_hash": HASH_B,
    }
    AppendOnlyLedger().append(**kwargs, details=duplicate_details())

    with pytest.raises(ValueError, match="unexpected detail"):
        AppendOnlyLedger().append(
            **kwargs,
            details={**duplicate_details(), "benign_extra": "not-registered"},
        )
    with pytest.raises(ValueError, match="sensitive"):
        AppendOnlyLedger().append(
            **kwargs,
            details={**duplicate_details(), "diagnostic": {"nested": {"truth": 1}}},
        )
    with pytest.raises(ValueError, match="sensitive"):
        AppendOnlyLedger().append(
            **kwargs,
            details={**duplicate_details(), "raw_payload": "forbidden"},
        )
    with pytest.raises(ValueError, match="details for ACCEPTED"):
        AppendOnlyLedger().append(
            **{**kwargs, "record_type": "ACCEPTED"},
            details=duplicate_details(),
        )
    with pytest.raises(ValueError, match="HALTED_AUDIT.*reason"):
        AppendOnlyLedger().append(
            **{**kwargs, "record_type": "HALTED_AUDIT"},
            details={
                "charge_applied": False,
                "reason": "FULL_CONFLICT",
                "scientific_state_changed": False,
            },
        )


def test_object_mutated_ledger_record_cannot_bypass_closed_details_validation():
    ledger = (
        RuntimeKernel(budget_total=10)
        .process(event("event-1", "root-1"))
        .snapshot.ledger
    )
    forged_record = copy.copy(ledger.records[0])
    unsafe_details = dict(forged_record.details)
    unsafe_details["diagnostic"] = {"nested": {"raw_payload": "forbidden"}}
    object.__setattr__(forged_record, "details_json", canonical_text(unsafe_details))
    object.__setattr__(
        forged_record,
        "record_hash",
        sha256_hex(canonical_bytes(forged_record.body_dict())),
    )
    assert forged_record.hash_is_valid()
    assert not AppendOnlyLedger((forged_record,)).validate()


def test_halted_classification_precedes_duplicate_and_equivocation_after_unavailable():
    kernel = RuntimeKernel(budget_total=10)
    original = event("event-1", "root-1")
    kernel.process(original)
    kernel.process(event("event-1", "root-1", mass={16: 0.9, dst.THETA: 0.1}))
    halted = kernel.snapshot
    assert halted.state.availability == "UNAVAILABLE"

    exact_retry = kernel.process(original)
    another_equivocation = kernel.process(
        event("event-1", "root-1", mass={16: 0.95, dst.THETA: 0.05})
    )

    assert exact_retry.status is TransactionStatus.HALTED_AUDIT
    assert another_equivocation.status is TransactionStatus.HALTED_AUDIT
    assert exact_retry.snapshot.state is halted.state
    assert another_equivocation.snapshot.state is halted.state
    assert another_equivocation.snapshot.state.processing_spend == 1


def test_halted_reason_only_exposes_equivocation_or_runtime_unavailable():
    genesis = RuntimeSnapshot.genesis(budget_total=10)
    unavailable = replace(
        genesis.state,
        availability="UNAVAILABLE",
        gate=GateState("CLOSED", "FULL_CONFLICT"),
        action=ActionState("FAIL_CLOSED", "seed", "FULL_CONFLICT"),
    )
    ledger = AppendOnlyLedger().append(
        record_type="EVENT_ID_EQUIVOCATION",
        event_id="seed",
        event_hash=HASH_B,
        processing_token=processing_token_for("seed"),
        before_scientific_hash=genesis.scientific_hash,
        after_scientific_hash=unavailable.scientific_hash,
        details={
            "belief_changed": False,
            "budget_changed": False,
            "charge_applied": False,
            "committed_event_hash": HASH_A,
            "received_event_hash": HASH_B,
            "reason": "EVENT_ID_EQUIVOCATION",
            "scientific_state_changed": True,
        },
    )
    kernel = RuntimeKernel(
        store=RuntimeStore(snapshot=RuntimeSnapshot(unavailable, ledger, revision=1))
    )

    halted = kernel.process(event("event-2", "root-2"))

    assert halted.status is TransactionStatus.HALTED_AUDIT
    assert halted.record.details["reason"] == "RUNTIME_UNAVAILABLE"
    assert halted.snapshot.state is unavailable


def test_budget_rejection_keeps_contribution_cap_and_commits_processing_charge_once():
    kernel = RuntimeKernel(budget_total=1)
    rejected = event(
        "budget-event",
        "budget-root",
        processing_cost=3,
        contribution_amount=2,
    )

    result = kernel.process(rejected)

    assert result.status.value == "BUDGET_CAP_AUDIT"
    assert result.snapshot.state.budget_used == 0
    assert result.snapshot.state.budget_used <= result.snapshot.state.budget_total
    assert result.snapshot.state.processing_spend == 3
    assert len(result.snapshot.state.charge_facts) == 1
    assert result.snapshot.state.contribution_tokens == ()
    assert result.snapshot.state.contribution_for("budget-root") is None
    assert result.snapshot.state.version_for("budget-root") == Version(1)
    assert result.snapshot.state.gate.status == "CLOSED"
    assert result.snapshot.state.action.status == "FAIL_CLOSED"

    retry = kernel.process(rejected)
    assert retry.status is TransactionStatus.DUPLICATE_AUDIT
    assert retry.snapshot.state.processing_spend == 3
    assert len(retry.snapshot.state.charge_facts) == 1


def test_full_conflict_and_root_identity_failures_commit_typed_once_only_audits():
    conflict_kernel = RuntimeKernel(budget_total=10)
    conflict_kernel.process(
        event("safe", "safe-root", mass={1: 1.0}, processing_cost=2)
    )
    conflicting = event("risk", "risk-root", mass={16: 1.0}, processing_cost=5)

    conflict = conflict_kernel.process(conflicting)

    assert conflict.status.value == "FULL_CONFLICT_AUDIT"
    assert conflict.snapshot.state.processing_spend == 7
    assert len(conflict.snapshot.state.charge_facts) == 2
    assert len(conflict.snapshot.state.contribution_tokens) == 1
    assert conflict.snapshot.state.contribution_for("risk-root") is None
    assert conflict.snapshot.state.version_for("risk-root") == Version(1)
    assert conflict.snapshot.state.belief == conflict_kernel.snapshot.state.belief
    assert conflict.snapshot.state.action.status == "FAIL_CLOSED"

    conflict_retry = conflict_kernel.process(conflicting)
    assert conflict_retry.status is TransactionStatus.DUPLICATE_AUDIT
    assert conflict_retry.snapshot.state.processing_spend == 7

    identity_kernel = RuntimeKernel(budget_total=10)
    identity_kernel.process(event("first", "root-1", root_type="GENERIC"))
    conflicting_identity = event("second", "root-1", root_type="DIFFERENT")
    identity_result = identity_kernel.process(conflicting_identity)

    assert identity_result.status.value == "ROOT_IDENTITY_CONFLICT_AUDIT"
    assert identity_result.snapshot.state.processing_spend == 2
    assert len(identity_result.snapshot.state.charge_facts) == 2
    assert len(identity_result.snapshot.state.contribution_tokens) == 1
    assert identity_result.snapshot.state.action.status == "FAIL_CLOSED"


def test_tokenless_registered_root_is_a_supported_noncontributing_state():
    kernel = RuntimeKernel(budget_total=1)
    kernel.process(
        event(
            "rejected",
            "root-1",
            processing_cost=1,
            contribution_amount=2,
        )
    )
    assert kernel.snapshot.state.contribution_for("root-1") is None

    alternate = kernel.process(
        event(
            "alternate",
            "root-1",
            version=1,
            processing_cost=1,
            contribution_amount=0.5,
        )
    )
    assert alternate.status is TransactionStatus.ALTERNATE_VIEW_AUDIT
    assert alternate.record.details["contribution_token"] is None
    assert alternate.snapshot.state.contribution_for("root-1") is None
    assert alternate.snapshot.state.availability == "AVAILABLE"
    assert alternate.snapshot.state.gate == GateState("CLOSED", "NONCONTRIBUTING_ROOT")
    assert alternate.snapshot.state.action == ActionState("AUDIT_ONLY", "alternate")

    stale = kernel.process(
        event(
            "stale",
            "root-1",
            version=0,
            processing_cost=1,
            contribution_amount=0.5,
        )
    )
    assert stale.status is TransactionStatus.STALE_VERSION_AUDIT
    assert stale.record.details["contribution_token"] is None
    assert stale.snapshot.state.availability == "AVAILABLE"
    assert stale.snapshot.state.gate == GateState("CLOSED", "NONCONTRIBUTING_ROOT")
    assert stale.snapshot.state.action == ActionState("AUDIT_ONLY", "stale")

    initialized = kernel.process(
        event(
            "higher",
            "root-1",
            version=2,
            processing_cost=1,
            contribution_amount=0.5,
        )
    )
    assert initialized.status is TransactionStatus.SUPERSEDED
    assert initialized.snapshot.state.contribution_for("root-1") is not None
    assert initialized.snapshot.state.budget_used == 0.5
    assert initialized.snapshot.state.processing_spend == 4
    assert initialized.snapshot.state.availability == "AVAILABLE"
    assert initialized.snapshot.state.gate == GateState("OPEN")
    assert initialized.snapshot.state.action == ActionState(
        "SUPERSEDE_CONTRIBUTION", "higher"
    )


def test_cas_rejects_valid_hash_accepted_record_with_semantic_detail_lies():
    kernel = RuntimeKernel(budget_total=10)
    candidate = kernel.prepare(event("event-1", "root-1", processing_cost=2))
    forged = forge_candidate_details(
        candidate,
        belief_changed=False,
        budget_used=9.0,
        contribution_token=HASH_A,
        processing_charge=7,
        processing_spend=8,
    )
    before = kernel.snapshot

    assert forged.record.hash_is_valid()
    with pytest.raises(ValueError, match="semantic binding"):
        kernel.commit(forged)
    assert kernel.snapshot is before


def test_stale_cas_precedes_semantic_detail_binding():
    kernel = RuntimeKernel(budget_total=10)
    stale = forge_candidate_details(
        kernel.prepare(event("stale", "stale-root")),
        budget_used=9.0,
    )
    kernel.process(event("current", "current-root"))
    before = kernel.snapshot

    with pytest.raises(CasConflictError):
        kernel.commit(stale)
    assert kernel.snapshot is before


def test_cas_rejects_valid_hash_domain_failure_detail_lie():
    kernel = RuntimeKernel(budget_total=1)
    candidate = kernel.prepare(event("rejected", "root-1", contribution_amount=2))
    assert candidate.status is TransactionStatus.BUDGET_CAP_AUDIT
    forged = forge_candidate_details(candidate, processing_charge=9)
    before = kernel.snapshot

    assert forged.record.hash_is_valid()
    with pytest.raises(ValueError, match="semantic binding"):
        kernel.commit(forged)
    assert kernel.snapshot is before


def test_runtime_package_exposes_the_deliberate_stage2_api():
    import rfb.runtime as runtime

    required = {
        "AppendOnlyLedger",
        "CandidateTransaction",
        "Event",
        "FailurePoint",
        "LedgerRecord",
        "LegacyEvidenceAdapter",
        "RuntimeKernel",
        "RuntimeSnapshot",
        "RuntimeState",
        "RuntimeStore",
        "TransactionResult",
        "TransactionStatus",
        "replay_events",
    }
    assert required.issubset(set(runtime.__all__))
    for name in required:
        assert getattr(runtime, name) is not None


def test_domain_failure_paths_keep_injected_crashes_zero_commit():
    budget_kernel = RuntimeKernel(budget_total=1)
    before_budget = budget_kernel.snapshot
    with pytest.raises(InjectedFailure, match=FailurePoint.BUDGET.value):
        budget_kernel.process(
            event("budget", "budget-root", contribution_amount=2),
            failure_at=FailurePoint.BUDGET,
        )
    assert budget_kernel.snapshot is before_budget

    conflict_kernel = RuntimeKernel(budget_total=10)
    conflict_kernel.process(event("safe", "safe-root", mass={1: 1.0}))
    before_conflict = conflict_kernel.snapshot
    with pytest.raises(InjectedFailure, match=FailurePoint.BELIEF.value):
        conflict_kernel.process(
            event("risk", "risk-root", mass={16: 1.0}),
            failure_at=FailurePoint.BELIEF,
        )
    assert conflict_kernel.snapshot is before_conflict

    identity_kernel = RuntimeKernel(budget_total=10)
    identity_kernel.process(event("first", "root-1", root_type="GENERIC"))
    before_identity = identity_kernel.snapshot
    with pytest.raises(InjectedFailure, match=FailurePoint.ACTION.value):
        identity_kernel.process(
            event("second", "root-1", root_type="DIFFERENT"),
            failure_at=FailurePoint.ACTION,
        )
    assert identity_kernel.snapshot is before_identity


def test_domain_failure_ack_loss_commits_one_processing_charge_and_retry_does_not_refund():
    kernel = RuntimeKernel(budget_total=1)
    rejected = event(
        "budget-event",
        "budget-root",
        processing_cost=3,
        contribution_amount=2,
    )
    with pytest.raises(PostCommitAckLost):
        kernel.process(rejected, failure_at=FailurePoint.POST_CAS_ACK_LOSS)

    committed = kernel.snapshot
    assert committed.ledger.records[-1].record_type == "BUDGET_CAP_AUDIT"
    assert committed.state.processing_spend == 3
    assert len(committed.state.charge_facts) == 1
    retry = kernel.process(rejected)
    assert retry.status is TransactionStatus.DUPLICATE_AUDIT
    assert retry.snapshot.state.processing_spend == 3
    assert len(retry.snapshot.state.charge_facts) == 1
