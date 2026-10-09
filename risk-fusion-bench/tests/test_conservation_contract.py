# -*- coding: utf-8 -*-
"""G2 canary tests for once-only contribution and fail-closed fusion.

This is an engineering qualification slice, not confirmatory evidence.
"""

from __future__ import annotations

import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rfb import dst, temporal
from rfb.runtime.state import Event, Root, Version
from rfb.runtime.transaction import RuntimeKernel, TransactionStatus, replay_events


def _identified_evidence(
    *,
    event_id: str,
    root_id: str,
    bundle_version: int,
    view_id: str,
    mass=None,
    t_gen: float = 1.0,
):
    return temporal.Evidence(
        m=mass or {16: 0.8, dst.THETA: 0.2},
        t_gen=t_gen,
        source_id="canary-source",
        reliability=1.0,
        event_id=event_id,
        root_id=root_id,
        bundle_version=bundle_version,
        view_id=view_id,
    )


def _runtime_event(
    event_id: str,
    *,
    version: int = 1,
    view_id: str = "view-a",
    mass=None,
    processing_cost: int = 1,
    contribution_amount: float = 1.0,
) -> Event:
    return Event.create(
        event_id=event_id,
        root=Root("runtime-root"),
        version=Version(version),
        mass=mass if mass is not None else {16: 0.8, dst.THETA: 0.2},
        view_id=view_id,
        processing_cost=processing_cost,
        contribution_amount=contribution_amount,
    )


def _state_snapshot(state: temporal.BeliefState):
    return {
        "belief": copy.deepcopy(state.B),
        "time": state.t,
        "history": copy.deepcopy(state.history),
    }


def test_exact_duplicate_is_audit_only():
    state = temporal.BeliefState(gamma=0.0)
    event = _identified_evidence(
        event_id="event-1", root_id="root-1", bundle_version=1, view_id="view-a"
    )
    state.step(event)
    before = _state_snapshot(state)

    state.step(event)

    assert _state_snapshot(state) == before
    assert state.audit[-1]["status"] == "DUPLICATE_AUDIT"


def test_same_root_alternate_view_is_audit_only():
    state = temporal.BeliefState(gamma=0.0)
    state.step(
        _identified_evidence(
            event_id="event-1", root_id="root-1", bundle_version=1, view_id="view-a"
        )
    )
    before = _state_snapshot(state)

    state.step(
        _identified_evidence(
            event_id="event-2",
            root_id="root-1",
            bundle_version=1,
            view_id="view-b",
            mass={16: 0.95, dst.THETA: 0.05},
        )
    )

    assert _state_snapshot(state) == before
    assert state.audit[-1]["status"] == "ALTERNATE_VIEW_AUDIT"


def test_higher_version_without_transaction_ledger_freezes_atomically():
    state = temporal.BeliefState(gamma=0.0)
    state.step(
        _identified_evidence(
            event_id="event-v1", root_id="root-1", bundle_version=1, view_id="view-a"
        )
    )
    before = _state_snapshot(state)

    with pytest.raises(
        temporal.FusionFailClosedError,
        match="HIGHER_VERSION_REQUIRES_TRANSACTION_LEDGER",
    ):
        state.step(
            _identified_evidence(
                event_id="event-v2",
                root_id="root-1",
                bundle_version=2,
                view_id="view-a",
            )
        )

    assert state.frozen is True
    assert state.freeze_reason == "HIGHER_VERSION_REQUIRES_TRANSACTION_LEDGER"
    assert _state_snapshot(state) == before
    assert state.audit[-1]["status"] == "HIGHER_VERSION_FAIL_CLOSED"


def test_complete_conflict_freezes_without_committing_vacuous_state():
    state = temporal.BeliefState(gamma=0.0)
    state.step(
        _identified_evidence(
            event_id="safe-event",
            root_id="safe-root",
            bundle_version=1,
            view_id="view-a",
            mass={1: 1.0},
        )
    )
    before = _state_snapshot(state)

    with pytest.raises(temporal.FusionFailClosedError, match="FULL_CONFLICT"):
        state.step(
            _identified_evidence(
                event_id="risk-event",
                root_id="risk-root",
                bundle_version=1,
                view_id="view-a",
                mass={16: 1.0},
            )
        )

    assert state.frozen is True
    assert state.freeze_reason == "FULL_CONFLICT"
    assert _state_snapshot(state) == before
    assert state.B == {1: 1.0}
    assert state.audit[-1]["status"] == "FULL_CONFLICT_FAIL_CLOSED"

    with pytest.raises(temporal.FusionFailClosedError, match="STATE_FROZEN"):
        state.coast(state.t + 1.0)


def test_legacy_evidence_positional_interface_still_runs():
    event = temporal.Evidence({1: 0.6, dst.THETA: 0.4}, 0.0, "legacy", 0.8)
    state = temporal.BeliefState(gamma=0.0)

    state.step(event)

    assert state.frozen is False
    assert len(state.history) == 1


def test_runtime_unique_duplicate_and_equivocation_conserve_resources_atomically():
    kernel = RuntimeKernel(budget_total=20)
    event = _runtime_event("runtime-event-1", processing_cost=3)

    accepted = kernel.process(event)

    assert accepted.status is TransactionStatus.ACCEPTED
    assert len(accepted.snapshot.state.processing_tokens) == 1
    assert len(accepted.snapshot.state.charge_facts) == 1
    assert len(accepted.snapshot.state.contribution_tokens) == 1
    assert accepted.snapshot.state.budget_used == 1.0
    assert accepted.snapshot.state.processing_spend == 3

    before_duplicate = accepted.snapshot
    duplicate = kernel.process(event)

    assert duplicate.status is TransactionStatus.DUPLICATE_AUDIT
    assert duplicate.snapshot.scientific_hash == before_duplicate.scientific_hash
    assert duplicate.snapshot.state is before_duplicate.state

    before_equivocation = duplicate.snapshot
    equivocation = _runtime_event(
        "runtime-event-1",
        mass={16: 0.95, dst.THETA: 0.05},
        processing_cost=11,
    )
    failed_closed = kernel.process(equivocation)

    assert failed_closed.status is TransactionStatus.EVENT_ID_EQUIVOCATION
    assert (
        failed_closed.snapshot.state.processing_tokens
        == before_equivocation.state.processing_tokens
    )
    assert (
        failed_closed.snapshot.state.charge_facts
        == before_equivocation.state.charge_facts
    )
    assert (
        failed_closed.snapshot.state.budget_used
        == before_equivocation.state.budget_used
    )
    assert (
        failed_closed.snapshot.state.contribution_tokens
        == before_equivocation.state.contribution_tokens
    )
    assert failed_closed.snapshot.state.availability == "UNAVAILABLE"
    assert failed_closed.snapshot.state.gate.status == "CLOSED"
    assert failed_closed.snapshot.state.action.status == "FAIL_CLOSED"


def test_runtime_unique_event_conservation_and_replay_are_deterministic():
    events = (
        _runtime_event("accepted", processing_cost=2),
        _runtime_event(
            "alternate",
            view_id="view-b",
            mass={16: 0.9, dst.THETA: 0.1},
            processing_cost=3,
        ),
        _runtime_event(
            "superseded",
            version=2,
            mass={16: 0.7, dst.THETA: 0.3},
            processing_cost=5,
        ),
        _runtime_event("stale", version=1, view_id="view-c", processing_cost=7),
    )
    kernel = RuntimeKernel(budget_total=20)

    statuses = tuple(kernel.process(event).status for event in events)
    manual = kernel.snapshot

    assert statuses == (
        TransactionStatus.ACCEPTED,
        TransactionStatus.ALTERNATE_VIEW_AUDIT,
        TransactionStatus.SUPERSEDED,
        TransactionStatus.STALE_VERSION_AUDIT,
    )
    assert len(manual.state.contribution_tokens) == 1
    contribution = manual.state.contribution_for("runtime-root")
    assert contribution is not None
    assert contribution.bundle_version == 2
    assert contribution.effective_event_id == "superseded"
    assert manual.state.version_for("runtime-root") == Version(2)
    assert len(manual.state.processing_tokens) == len(events)
    assert len(set(manual.state.processing_tokens)) == len(events)
    assert len(manual.state.charge_facts) == len(events)
    assert {charge.event_id: charge.amount for charge in manual.state.charge_facts} == {
        "accepted": 2,
        "alternate": 3,
        "superseded": 5,
        "stale": 7,
    }
    assert manual.state.budget_used == sum(
        token.amount for token in manual.state.contribution_tokens
    )
    assert manual.state.processing_spend == sum(
        charge.amount for charge in manual.state.charge_facts
    )

    replayed_once = replay_events(events, budget_total=20)
    replayed_twice = replay_events(events, budget_total=20)

    assert (
        manual.scientific_hash
        == replayed_once.scientific_hash
        == replayed_twice.scientific_hash
    )
    assert (
        manual.snapshot_hash
        == replayed_once.snapshot_hash
        == replayed_twice.snapshot_hash
    )
    assert (
        manual.ledger.canonical_log_bytes
        == replayed_once.ledger.canonical_log_bytes
        == replayed_twice.ledger.canonical_log_bytes
    )
