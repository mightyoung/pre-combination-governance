from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rfb.runtime.ledger import AppendOnlyLedger  # noqa: E402
from rfb.runtime.state import contribution_token_for, processing_token_for  # noqa: E402


HASH_A = "a" * 64
HASH_B = "b" * 64
EVENT_HASH = "c" * 64
PROCESSING_TOKEN = processing_token_for("event-1")
CONTRIBUTION_TOKEN = contribution_token_for("root-1")


def append_accept(ledger: AppendOnlyLedger) -> AppendOnlyLedger:
    return ledger.append(
        record_type="ACCEPTED",
        event_id="event-1",
        event_hash=EVENT_HASH,
        processing_token=PROCESSING_TOKEN,
        before_scientific_hash=HASH_A,
        after_scientific_hash=HASH_B,
        details={
            "belief_changed": True,
            "budget_used": 1.0,
            "charge_applied": True,
            "contribution_token": CONTRIBUTION_TOKEN,
            "processing_charge": 1,
            "processing_spend": 1,
            "scientific_state_changed": True,
        },
    )


def test_append_only_ledger_is_canonical_deterministic_and_persistent():
    empty = AppendOnlyLedger()
    first = append_accept(empty)
    same = append_accept(empty)

    assert empty.records == ()
    assert first.head_hash == same.head_hash
    assert first.canonical_log_bytes == same.canonical_log_bytes
    assert b'"charge_applied":true' in first.canonical_log_bytes
    assert not first.canonical_log_bytes.endswith(b"\n")
    assert first.validate()


def test_ledger_chain_detects_tampering_and_records_are_frozen():
    ledger = append_accept(AppendOnlyLedger()).append(
        record_type="DUPLICATE_AUDIT",
        event_id="event-1",
        event_hash=EVENT_HASH,
        processing_token=PROCESSING_TOKEN,
        before_scientific_hash=HASH_B,
        after_scientific_hash=HASH_B,
        details={
            "charge_applied": False,
            "reason": "EXACT_EVENT_DUPLICATE",
            "scientific_state_changed": False,
        },
    )
    assert ledger.validate()
    with pytest.raises(FrozenInstanceError):
        ledger.records[0].record_type = "CHANGED"  # type: ignore[misc]

    tampered_record = copy.copy(ledger.records[0])
    object.__setattr__(tampered_record, "record_hash", "d" * 64)
    tampered = AppendOnlyLedger((tampered_record, ledger.records[1]))
    assert not tampered.validate()


def test_ledger_round_trip_preserves_head_and_hash_chain():
    ledger = append_accept(AppendOnlyLedger())
    restored = AppendOnlyLedger.from_list(ledger.to_list())
    assert restored == ledger
    assert restored.head_hash == ledger.head_hash
    assert restored.validate()
