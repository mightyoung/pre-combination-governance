"""Build the fixed A/B/C/D method-visible inputs from the pinned public source."""

import json


TRACE_IDS = {
    "A": "I1_NO_INFO_CONTINUING",
    "B": "I2_NO_INFO_NEW",
    "C": "I3_RECOVERY",
    "D": "I2_NO_INFO_NEW",
}


def canonical_json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _copy(value):
    return json.loads(canonical_json_bytes(value))


def build_pair_cases(public_input: dict, case_ids: dict) -> dict:
    if set(case_ids) != {"A", "B", "C", "D"}:
        raise ValueError("case IDs must bind exactly A/B/C/D")
    if any(not isinstance(value, str) or not value for value in case_ids.values()):
        raise ValueError("case IDs must be nonempty strings")
    if len(set(case_ids.values())) != 4:
        raise ValueError("case IDs must be unique and opaque per case")

    traces = {item.get("id"): item for item in public_input.get("traces", [])}
    if len(traces) != len(public_input.get("traces", [])):
        raise ValueError("duplicate source trace ID")
    if any(name not in traces for name in set(TRACE_IDS.values())):
        raise ValueError("pinned source is missing a required trace")
    for name in set(TRACE_IDS.values()):
        if len(traces[name].get("rows", [])) != 5:
            raise ValueError("each paired source trace must have exactly five rows")

    rows_a = _copy(traces[TRACE_IDS["A"]]["rows"])
    rows_b = _copy(traces[TRACE_IDS["B"]]["rows"])
    if canonical_json_bytes(rows_a) != canonical_json_bytes(rows_b):
        raise ValueError("A/B method-visible input mismatch")

    rows_c = _copy(traces[TRACE_IDS["C"]]["rows"])
    rows_c_without_boundary = _copy(rows_c)
    rows_c_without_boundary[4].pop("boundary_evidence", None)
    rows_b_without_boundary = _copy(rows_b)
    rows_b_without_boundary[4].pop("boundary_evidence", None)
    if rows_c_without_boundary != rows_b_without_boundary:
        raise ValueError("C must differ from B only at e.boundary_evidence")
    records = rows_c[4].get("boundary_evidence", [])
    if len(records) != 1:
        raise ValueError("C must add exactly one valid boundary record")
    recovery = records[0]
    expected_recovery = {
        "kind": "RECOVERY",
        "previous_value": "ACTIVE",
        "value": "RECOVERED",
        "previous_time": 2,
        "physical_time": 3.5,
        "known_time": 3.5,
        "quality": "GOOD",
        "reliability": "QUALIFIED",
        "independent_lineage": True,
    }
    if any(recovery.get(key) != value for key, value in expected_recovery.items()):
        raise ValueError("C recovery does not match the frozen plan")

    rows_d = _copy(rows_b)
    stale = _copy(recovery)
    stale.update(previous_time=0, physical_time=1, known_time=4)
    rows_d[4]["boundary_evidence"] = [stale]
    return {
        "schema_version": 1,
        "cases": [
            {"case_id": case_ids[key], "rows": rows}
            for key, rows in (("A", rows_a), ("B", rows_b),
                              ("C", rows_c), ("D", rows_d))
        ],
    }
