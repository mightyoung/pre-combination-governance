"""R001 contract tests for the non-confirmatory research manifest.

These tests intentionally run before the research package exists.  Missing
schemas/API are reported as ordinary pytest failures (rather than collection
errors) so implementation work has an explicit RED signal.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_HOST_FINGERPRINT = "SHA256:eDfwLjrpTces2mQp4d+gKdg2i/4t7k7sLfF/nLtx1oA"


def _minimal_manifest(**updates: object) -> dict[str, object]:
    manifest: dict[str, object] = {
        "run_id": "r005-test",
        "execution_protocol_id": "RFB_RESEARCH_LEGACY_R006",
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
        "adapter_id": "tep_fixture",
    }
    manifest.update(updates)
    return manifest


def test_expected_host_fingerprint_is_validated_by_field_not_path_heuristic():
    from rfb.research.manifest import validate_manifest

    accepted = validate_manifest(
        _minimal_manifest(expected_fingerprint=EXPECTED_HOST_FINGERPRINT)
    )
    assert accepted["expected_fingerprint"] == EXPECTED_HOST_FINGERPRINT


@pytest.mark.parametrize("protocol", [None, "UNKNOWN_PROTOCOL"])
def test_manifest_protocol_is_explicit_and_closed(protocol):
    from rfb.research.manifest import validate_manifest

    manifest = _minimal_manifest()
    if protocol is None:
        manifest.pop("execution_protocol_id")
    else:
        manifest["execution_protocol_id"] = protocol
    with pytest.raises(ValueError):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    "updates",
    [
        {"expected_fingerprint": "SHA256:short/looks/pathlike"},
        {"experiment_name": "/home/operator/private/source.py"},
        {"experiment_name": "ssh_password=not-for-artifacts"},
    ],
)
def test_fingerprint_exception_does_not_weaken_categorical_guards(
    updates: dict[str, object],
):
    from rfb.research.manifest import validate_manifest

    with pytest.raises(ValueError):
        validate_manifest(_minimal_manifest(**updates))


def _schema(name: str) -> dict:
    path = ROOT / "src" / "rfb" / "contracts" / name
    if not path.is_file():
        pytest.fail(f"R001 contract missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def test_research_manifest_schema_declares_immutable_nonconfirmatory_classification():
    schema = _schema("research_run_manifest.schema.json")
    props = schema.get("properties", {})
    expected = {
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
    }
    for field, value in expected.items():
        assert field in props, f"manifest schema must require {field}"
        if isinstance(value, bool):
            assert props[field].get("const") is value
        else:
            assert props[field].get("const") == value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("execution_lane", "FORMAL"),
        ("classification", "LIVE_CLOSEOUT_EVIDENCE"),
        ("formal_gate_effect", "PASS"),
        ("formal_admission_eligible", True),
        ("shk001b_eligible", True),
        ("contains_formal_claims", True),
    ],
)
def test_manifest_validator_rejects_mutated_classification(field: str, value: object):
    # The implementation owns fixture details; this assertion establishes the
    # required callable and lets its schema/model validation report the reason.
    from rfb.research.manifest import validate_manifest  # noqa: PLC0415

    manifest = {
        "run_id": "r001-test",
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
    }
    manifest[field] = value
    with pytest.raises((ValueError, TypeError, KeyError)):
        validate_manifest(manifest)


def test_schema_valid_production_capacity_passes_adapter_contract():
    from rfb.research.adapters import validate_adapter_contract
    from rfb.research.manifest import validate_manifest

    manifest = {
        "run_id": "production-contract",
        "execution_protocol_id": "RFB_RESEARCH_LEGACY_R006",
        "execution_lane": "RESEARCH",
        "classification": "DEVELOPMENT_NONCONFIRMATORY",
        "formal_gate_effect": "NONE",
        "formal_admission_eligible": False,
        "shk001b_eligible": False,
        "contains_formal_claims": False,
        "adapter_id": "tep_nonconfirmatory_v1",
        "algorithm_seed": 0,
        "method_panel": ["B0", "B1", "B2", "B3", "B4", "B5", "Proposed"],
        "adapter_params": {
            "rows": [[float(i + j) for j in range(3)] for i in range(12)]
        },
        "capacity": {
            "planned_bytes": 22_000_000_000,
            "drain_bytes": 24_000_000_000,
            "dataset": 16_000_000_000,
            "durable_result": 3_000_000_000,
            "scratch_partial": 2_000_000_000,
            "retry_quarantine_wal": 1_000_000_000,
            "emergency_reserve": 3_000_000_000,
            "telemetry": {
                "project_tree_allocated_bytes": 1,
                "filesystem_used_delta_bytes": 1,
                "owned_external_layers_bytes": 0,
                "open_deleted_bytes": 0,
                "observed_peak_bytes": 1,
            },
        },
    }

    validated = validate_manifest(manifest)
    validate_adapter_contract(validated)
