from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rfb import dst  # noqa: E402
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


def event(*, event_id: str = "event-1", root_id: str = "root-1") -> Event:
    return Event.create(
        event_id=event_id,
        root=Root(root_id),
        version=Version(1),
        mass={16: 0.8, dst.THETA: 0.2},
        processing_cost=2,
    )


def test_stage2_value_objects_are_frozen_and_canonical():
    ev = event()
    with pytest.raises(FrozenInstanceError):
        ev.event_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        ev.root.root_id = "changed"  # type: ignore[misc]

    assert ev.mass == ((16, 0.8), (dst.THETA, 0.2))
    assert ev.event_hash == event().event_hash
    assert processing_token_for("event-1") != ev.event_hash
    assert contribution_token_for("root-1") != processing_token_for("root-1")


def test_stage2_state_scientific_projection_is_deterministic_and_deeply_immutable():
    ev = event()
    processing_token = processing_token_for(ev.event_id)
    token = ContributionToken(
        token_id=contribution_token_for(ev.root.root_id),
        root_id=ev.root.root_id,
        first_event_id=ev.event_id,
        effective_event_id=ev.event_id,
        bundle_version=ev.version.bundle_version,
        amount=1.0,
        mass=ev.mass,
    )
    charge = ChargeFact(
        charge_id=charge_id_for(processing_token),
        processing_token=processing_token,
        event_id=ev.event_id,
        resource_type="PROCESSING",
        amount=ev.processing_cost,
    )
    state = RuntimeState(
        belief=ev.mass,
        roots=(ev.root,),
        versions=((ev.root.root_id, ev.version),),
        contribution_tokens=(token,),
        charge_facts=(charge,),
        event_hashes=((ev.event_id, ev.event_hash),),
        processing_tokens=(processing_token,),
        budget_total=10,
        budget_used=1.0,
        availability="AVAILABLE",
        gate=GateState("OPEN"),
        action=ActionState("ACCEPT_CONTRIBUTION", event_id=ev.event_id),
    )

    assert (
        state.scientific_hash == RuntimeState.from_dict(state.to_dict()).scientific_hash
    )
    assert state.state_hash == state.scientific_hash
    assert state.belief_mass == {16: 0.8, dst.THETA: 0.2}
    assert state.processing_spend == 2
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        state.belief += ((1, 0.1),)  # type: ignore[misc]


def test_stage2_state_rejects_duplicate_identity_and_budget_inconsistency():
    root = Root("root-1")
    with pytest.raises(ValueError, match="duplicate root_id"):
        RuntimeState(roots=(root, root))
    with pytest.raises(ValueError, match="budget_used"):
        RuntimeState(budget_total=1, budget_used=2)
