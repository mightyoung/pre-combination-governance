from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from rfb.contracts.canonical_json import canonical_bytes, sha256_hex
from rfb.formal.runner import FormalRunner
from rfb.methods import get_registry


def test_formal_transaction_ledger_schema_is_closed_and_validates_sealed_runner_output():
    schema_path = (
        Path(__file__).parents[1]
        / "src/rfb/contracts/formal_transaction_ledger.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert "SEALED" in schema["$defs"]["event"]["properties"]["state"]["enum"]
    observations = {
        "bundle_id": "schema-bundle",
        "algorithm_seed": 11,
        "transaction_id": "schema-tx",
        "events": [
            {"message_id": "m1", "version": 1, "root_id": "r1", "support": 0.8},
            {"message_id": "m2", "version": 1, "root_id": "r2", "support": 0.2},
        ],
    }
    result = FormalRunner(get_registry()).run_all(
        transaction_id="schema-tx",
        bundle_id="schema-bundle",
        observations=observations,
        seed=11,
    )
    document = {
        "schema_version": "1.0.0",
        "transaction_id": result.transaction_id,
        "expected_rows": sorted(result.rows),
        "events": [
            event.body() | {"event_hash": event.event_hash}
            for event in result.lifecycle.events
        ],
        "rows": result.rows,
        "head_hash": result.lifecycle.head_hash,
    }
    document["ledger_sha256"] = sha256_hex(canonical_bytes(document))
    Draft202012Validator(schema).validate(document)
    assert result.lifecycle.validate()
    assert len(result.rows) == 7
