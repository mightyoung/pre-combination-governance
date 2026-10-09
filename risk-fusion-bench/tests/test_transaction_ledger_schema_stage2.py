from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rfb.contracts.schemas import SCHEMA_DEFINITIONS  # noqa: E402
from rfb.runtime.ledger import AppendOnlyLedger  # noqa: E402
from rfb.runtime.transaction import TransactionStatus  # noqa: E402


SCHEMA_PATH = ROOT / "src" / "rfb" / "contracts" / "transaction_ledger.schema.json"


def test_transaction_ledger_schema_is_standalone_closed_and_does_not_mutate_stage1_registry():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert len(SCHEMA_DEFINITIONS) == 9
    assert "TransactionLedger" not in SCHEMA_DEFINITIONS
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "schema_version",
        "contains_raw_dataset",
        "records",
        "head_hash",
    }
    assert schema["properties"]["contains_raw_dataset"]["const"] is False
    record = schema["$defs"]["record"]
    assert record["additionalProperties"] is False
    assert {
        "sequence",
        "record_type",
        "event_id",
        "event_hash",
        "processing_token",
        "before_scientific_hash",
        "after_scientific_hash",
        "details",
        "previous_hash",
        "record_hash",
    } == set(record["required"])


def test_empty_ledger_document_is_raw_dataset_free_and_head_closed():
    ledger = AppendOnlyLedger()
    document = {
        "schema_version": "1.0.0",
        "contains_raw_dataset": False,
        "records": ledger.to_list(),
        "head_hash": ledger.head_hash,
    }

    assert document["contains_raw_dataset"] is False
    assert document["records"] == []
    assert document["head_hash"] == "0" * 64
    assert "truth" not in json.dumps(document).casefold()
    assert "payload" not in json.dumps(document).casefold()


def test_schema_closes_record_types_tokens_and_all_details_channels():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    record = schema["$defs"]["record"]
    statuses = {status.value for status in TransactionStatus}

    assert set(record["properties"]["record_type"]["enum"]) == statuses
    assert record["properties"]["processing_token"] == {"$ref": "#/$defs/sha256"}
    assert schema["$defs"]["halted_details"]["properties"]["reason"] == {
        "enum": ["EVENT_ID_EQUIVOCATION", "RUNTIME_UNAVAILABLE"]
    }

    bound_statuses: set[str] = set()
    for clause in record["allOf"]:
        selector = clause["if"]["properties"]["record_type"]
        if "const" in selector:
            bound_statuses.add(selector["const"])
        else:
            bound_statuses.update(selector["enum"])
    assert bound_statuses == statuses

    detail_names = {
        "contribution_details",
        "audit_contribution_details",
        "duplicate_details",
        "halted_details",
        "equivocation_details",
        "domain_failure_details",
    }
    for name in detail_names:
        detail_schema = schema["$defs"][name]
        assert detail_schema["type"] == "object"
        assert detail_schema["additionalProperties"] is False
        assert set(detail_schema["required"]) == set(detail_schema["properties"])
        for field, field_schema in detail_schema["properties"].items():
            folded = field.casefold()
            assert "truth" not in folded
            assert "payload" not in folded
            assert not folded.startswith("raw")
            assert field_schema.get("type") not in {"object", "array"}
