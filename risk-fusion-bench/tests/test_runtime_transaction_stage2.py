from __future__ import annotations

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rfb import dst, temporal  # noqa: E402
from rfb.runtime.state import Event, Root, Version  # noqa: E402
from rfb.runtime.transaction import (  # noqa: E402
    CasConflictError,
    FailurePoint,
    FormalRunnerRejected,
    InjectedFailure,
    LegacyEvidenceAdapter,
    PostCommitAckLost,
    RuntimeKernel,
    TransactionStatus,
    replay_events,
)


def event(
    event_id: str,
    root_id: str,
    *,
    version: int = 1,
    mass=None,
    processing_cost: int = 1,
) -> Event:
    return Event.create(
        event_id=event_id,
        root=Root(root_id),
        version=Version(version),
        mass=mass if mass is not None else {16: 0.8, dst.THETA: 0.2},
        processing_cost=processing_cost,
    )


def test_exact_duplicate_appends_audit_only_without_scientific_change():
    kernel = RuntimeKernel(budget_total=10)
    ev = event("event-1", "root-1", processing_cost=2)
    accepted = kernel.process(ev)
    before_duplicate = accepted.snapshot

    duplicate = kernel.process(ev)

    assert duplicate.status is TransactionStatus.DUPLICATE_AUDIT
    assert duplicate.snapshot.state is before_duplicate.state
    assert duplicate.snapshot.scientific_hash == before_duplicate.scientific_hash
    assert duplicate.snapshot.state.budget_used == 1.0
    assert duplicate.snapshot.state.processing_spend == 2
    assert duplicate.snapshot.state.charge_facts == before_duplicate.state.charge_facts
    assert (
        duplicate.snapshot.state.contribution_tokens
        == before_duplicate.state.contribution_tokens
    )
    assert (
        len(duplicate.snapshot.ledger.records)
        == len(before_duplicate.ledger.records) + 1
    )
    assert duplicate.snapshot.snapshot_hash != before_duplicate.snapshot_hash
    assert (
        duplicate.snapshot.ledger.records[-1].before_scientific_hash
        == duplicate.snapshot.ledger.records[-1].after_scientific_hash
    )


def test_event_id_equivocation_commits_atomic_fail_closed_without_second_charge():
    kernel = RuntimeKernel(budget_total=10)
    original = event("event-1", "root-1", processing_cost=2)
    kernel.process(original)
    before = kernel.snapshot
    equivocation = event(
        "event-1",
        "root-1",
        mass={16: 0.95, dst.THETA: 0.05},
        processing_cost=9,
    )

    result = kernel.process(equivocation)

    assert result.status is TransactionStatus.EVENT_ID_EQUIVOCATION
    assert result.snapshot.state.belief == before.state.belief
    assert result.snapshot.state.contribution_tokens == before.state.contribution_tokens
    assert result.snapshot.state.charge_facts == before.state.charge_facts
    assert result.snapshot.state.processing_tokens == before.state.processing_tokens
    assert result.snapshot.state.budget_used == before.state.budget_used
    assert result.snapshot.state.availability == "UNAVAILABLE"
    assert result.snapshot.state.gate.status == "CLOSED"
    assert result.snapshot.state.action.status == "FAIL_CLOSED"
    assert result.snapshot.ledger.records[-1].record_type == "EVENT_ID_EQUIVOCATION"


@pytest.mark.parametrize(
    "point",
    [
        FailurePoint.READ,
        FailurePoint.PROCESSING_TOKEN,
        FailurePoint.BELIEF,
        FailurePoint.BUDGET,
        FailurePoint.AVAILABILITY,
        FailurePoint.GATE,
        FailurePoint.ACTION,
        FailurePoint.LEDGER_SEAL,
        FailurePoint.PRE_CAS,
    ],
)
def test_precommit_failure_injection_has_no_partial_state_or_ledger(point):
    kernel = RuntimeKernel(budget_total=10)
    before = kernel.snapshot

    with pytest.raises(InjectedFailure, match=point.value):
        kernel.process(event("event-1", "root-1"), failure_at=point)

    assert kernel.snapshot is before
    assert kernel.snapshot.snapshot_hash == before.snapshot_hash


def test_post_cas_ack_loss_is_fully_committed_and_retry_is_duplicate_audit():
    kernel = RuntimeKernel(budget_total=10)
    ev = event("event-1", "root-1")

    with pytest.raises(PostCommitAckLost):
        kernel.process(ev, failure_at=FailurePoint.POST_CAS_ACK_LOSS)

    committed = kernel.snapshot
    assert committed.revision == 1
    assert committed.state.budget_used == 1
    assert len(committed.state.contribution_tokens) == 1
    assert committed.ledger.records[-1].record_type == "ACCEPTED"

    retry = kernel.process(ev)
    assert retry.status is TransactionStatus.DUPLICATE_AUDIT
    assert retry.snapshot.state is committed.state
    assert retry.snapshot.state.budget_used == 1


def test_stale_candidate_cas_rejects_revision_scientific_hash_and_ledger_head_as_one_guard():
    kernel = RuntimeKernel(budget_total=10)
    stale = kernel.prepare(event("event-stale", "root-stale"))
    kernel.process(event("event-current", "root-current"))
    before_rejected_commit = kernel.snapshot

    with pytest.raises(CasConflictError):
        kernel.commit(stale)

    assert kernel.snapshot is before_rejected_commit


def test_repeated_identical_event_log_has_identical_scientific_and_snapshot_hashes():
    log = (
        event("event-1", "root-1"),
        event("event-2", "root-2", mass={8: 0.7, dst.THETA: 0.3}),
        event("event-1", "root-1"),
    )
    first = replay_events(log, budget_total=10)
    second = replay_events(log, budget_total=10)

    assert first.scientific_hash == second.scientific_hash
    assert first.snapshot_hash == second.snapshot_hash
    assert first.ledger.canonical_log_bytes == second.ledger.canonical_log_bytes


def test_legacy_adapter_is_mechanically_excluded_from_formal_mode_without_side_effects():
    kernel = RuntimeKernel(budget_total=10)
    adapter = LegacyEvidenceAdapter()
    legacy = temporal.Evidence({16: 0.8, dst.THETA: 0.2}, 1.0, "legacy", 1.0)
    before = kernel.snapshot

    assert adapter.formal_eligible is False
    with pytest.raises(FormalRunnerRejected, match="LEGACY_ADAPTER_FORMAL_FORBIDDEN"):
        adapter.submit(
            kernel, legacy, mode="FORMAL", event_id="legacy-1", root_id="legacy-root"
        )
    assert kernel.snapshot is before

    accepted = adapter.submit(
        kernel,
        legacy,
        mode="NON_FORMAL",
        event_id="legacy-1",
        root_id="legacy-root",
    )
    assert accepted.status is TransactionStatus.ACCEPTED
