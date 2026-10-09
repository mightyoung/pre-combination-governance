"""R001 immutable six-field event contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "execution_lane": "RESEARCH",
    "classification": "DEVELOPMENT_NONCONFIRMATORY",
    "formal_gate_effect": "NONE",
    "formal_admission_eligible": False,
    "shk001b_eligible": False,
    "contains_formal_claims": False,
}


def test_event_schema_requires_exact_immutable_six_field_subset():
    path = (
        ROOT / "src" / "rfb" / "research" / "contracts" / "research_event.schema.json"
    )
    if not path.is_file():
        pytest.fail(f"R001 canonical event schema missing: {path}")
    schema = json.loads(path.read_text(encoding="utf-8"))
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    assert set(EXPECTED) <= required
    for key, value in EXPECTED.items():
        assert props[key].get("const") == value
    assert set(props) >= set(EXPECTED)


@pytest.mark.parametrize("kind", ["state", "telemetry"])
def test_emitter_cannot_be_overridden_or_mutated(kind: str):
    from rfb.research.models import emit_event  # noqa: PLC0415

    event = emit_event(kind=kind, payload={"state": "PLANNED"})
    assert {key: event[key] for key in EXPECTED} == EXPECTED
    with pytest.raises((TypeError, AttributeError, ValueError)):
        event["classification"] = "LIVE_CLOSEOUT_EVIDENCE"
