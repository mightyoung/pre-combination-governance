import json
from pathlib import Path

import jsonschema
import pytest

from rfb.research.mme_methods import RESEARCH_METHOD_IDS, evaluate_prefix

SCHEMA = json.loads(
    (
        Path(__file__).parents[1]
        / "src/rfb/research/contracts/mme_v2_prediction.schema.json"
    ).read_text(encoding="utf-8")
)


@pytest.mark.parametrize("method_id", RESEARCH_METHOD_IDS)
def test_real_research_panel_obeys_common_json_output_contract(method_id):
    public = {
        "actions": [
            {
                "action_id": "impl-contract-event",
                "op": "INITIALIZE",
                "order": 1,
                "message_id": "impl-contract-message",
                "version": 1,
                "root_id": "impl-contract-root",
                "support": 0.8,
                "reliability": 1.0,
            }
        ],
        "algorithm_seed": 179031,
    }
    public["events"] = [
        {
            "event_id": row["action_id"],
            **{
                key: value
                for key, value in row.items()
                if key not in {"action_id", "op"}
            },
        }
        for row in public["actions"]
    ]
    public["controls"] = []
    output = evaluate_prefix(method_id, public, cap=10)
    jsonschema.Draft202012Validator(SCHEMA).validate(output)


def test_success_cannot_have_missing_interval_or_failure_code():
    output = {
        "method_id": "Proposed",
        "status": "SUCCEEDED",
        "risk_interval": None,
        "action_state": "ACT",
        "failure_code": "crash",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(SCHEMA).validate(output)
