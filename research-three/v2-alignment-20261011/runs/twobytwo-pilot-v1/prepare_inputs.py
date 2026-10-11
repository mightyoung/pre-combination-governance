#!/usr/bin/env python3
"""Materialize the two literal, method-visible inputs for the 2x2 pilot."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
INPUT_DIR = HERE / "method_inputs"
PROTOCOL_FREEZE = HERE / "PROTOCOL_FREEZE_RECORD.json"
PROTOCOL_PATH = HERE / "PROTOCOL.md"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_pretty_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def field(name: str, value: object, available_at: str) -> dict[str, object]:
    return {
        "name": name,
        "value": value,
        "actual_available_at": available_at,
        "earliest_known_at": available_at,
    }


def observation(
    observation_id: str,
    *,
    source_time: str,
    modality: str,
    position: list[float],
    value: float,
    root_id: str,
    node_id: str,
) -> dict[str, object]:
    fields = [
        field("acquisition_lineage", [root_id, node_id], source_time),
        field("asset_binding_status", "VERIFIED", source_time),
        field("asset_id", "ASSET-PILOT-01", source_time),
        field("calibration_status", "CURRENT", source_time),
        field("modality", modality, source_time),
        field("position_error_m", 0.25, source_time),
        field("position_m", position, source_time),
        field("quality_status", "GOOD", source_time),
        field("risk_flag", "EXPOSURE", source_time),
        field("source_time", source_time, source_time),
        field("unit", "degC", source_time),
        field("value", value, source_time),
        field("value_error", 0.5, source_time),
    ]
    return {
        "observation_id": observation_id,
        "id_actual_available_at": source_time,
        "id_earliest_known_at": source_time,
        "received_at": source_time,
        "fields": fields,
    }


def template(*, two_roots: bool) -> dict[str, object]:
    time_a = "2026-10-11T12:00:00Z"
    time_b = "2026-10-11T12:00:05Z"
    root_a = "ROOT-TWO-A-01" if two_roots else "ROOT-ONE-01"
    root_b = "ROOT-TWO-B-01" if two_roots else "ROOT-ONE-01"
    return {
        "as_of": "2026-10-11T12:02:00Z",
        "observations": [
            observation(
                "OBS-PILOT-A",
                source_time=time_a,
                modality="TEMPERATURE",
                position=[0.0, 0.0],
                value=79.95,
                root_id=root_a,
                node_id="NODE-A",
            ),
            observation(
                "OBS-PILOT-B",
                source_time=time_b,
                modality="THERMAL_IMAGE",
                position=[0.1, 0.0],
                value=80.20,
                root_id=root_b,
                node_id="NODE-B",
            ),
        ],
    }


def main() -> None:
    if (HERE / "INPUT_FREEZE_RECORD.json").exists():
        raise SystemExit("INPUT_FREEZE_RECORD.json already exists; refusing to overwrite frozen inputs")
    freeze = json.loads(PROTOCOL_FREEZE.read_text(encoding="utf-8"))
    if freeze.get("freeze_status") != "FROZEN_BEFORE_EXECUTION":
        raise SystemExit("the 2x2 protocol is not frozen")
    if freeze.get("execution_started") or freeze.get("method_calls_made") != 0:
        raise SystemExit("protocol freeze record already indicates execution")

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    templates = {
        "V1_ONE_ROOT": template(two_roots=False),
        "V2_TWO_ROOT_IDS": template(two_roots=True),
    }
    records = []
    for name, payload in templates.items():
        raw = canonical_pretty_json(payload)
        path = INPUT_DIR / f"{name}.json"
        path.write_bytes(raw)
        records.append(
            {
                "template": name,
                "path": path.relative_to(HERE).as_posix(),
                "bytes": len(raw),
                "sha256": sha256(raw),
            }
        )

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    record = {
        "artifact_version": "2x2-method-input-freeze-v1",
        "protocol_id": freeze["protocol_id"],
        "protocol_sha256": freeze["protocol_sha256"],
        "scorer_only_predeclaration_sha256_from_protocol_freeze": freeze[
            "scorer_only_predeclaration_sha256"
        ],
        "method_source_path": freeze["method_source_path"],
        "method_source_sha256": freeze["method_source_sha256"],
        "original_configuration_sha256": freeze["frozen_original_configuration_sha256"],
        "generated_at_utc": now,
        "execution_started": False,
        "method_calls_made": 0,
        "template_count": len(records),
        "templates": records,
        "template_clone_pairs": [
            {"cases": ["R1-SAME", "R1-DIFF"], "template": "V1_ONE_ROOT"},
            {"cases": ["R2-SAME", "R2-DIFF"], "template": "V2_TWO_ROOT_IDS"},
        ],
        "hidden_fields_excluded": [
            "case_id",
            "event_key",
            "event_relation",
            "source_family",
            "source_dependence",
            "root_relation_label",
            "identifiability_label",
        ],
        "method_input_schema": "as_of plus ObservationRecord values and allowlisted KnownField values only",
    }
    out = HERE / "INPUT_FREEZE_RECORD.json"
    out.write_bytes(canonical_pretty_json(record))
    print(f"wrote {len(records)} visible input templates")
    for item in records:
        print(f"{item['template']} sha256={item['sha256']} bytes={item['bytes']}")
    print(f"freeze record: {out.relative_to(HERE)}")


if __name__ == "__main__":
    main()
