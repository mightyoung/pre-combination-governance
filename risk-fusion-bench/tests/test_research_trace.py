import copy
import json
from pathlib import Path

import pytest
from jsonschema import validators

from rfb.research.trace import (
    EVENT_ACTOR_TABLE,
    LifecycleTraceRecorder,
    TraceValidationError,
    build_trace,
    make_record,
    validate_trace,
    validate_trace_prefix,
)


def _trace():
    recorder = LifecycleTraceRecorder(run_id="r005", approved_remote_parent="parent-a")
    for step in range(1, 21):
        recorder.append(
            input_hashes={f"input-{step}": "a" * 64},
            output_hashes={f"output-{step}": "b" * 64},
            monotonic_ns=step,
        )
    return recorder.seal()


def test_revision6_table_is_exact_and_successful_trace_validates():
    trace = _trace()
    assert [step for step, _, _ in EVENT_ACTOR_TABLE] == list(range(1, 21))
    assert validate_trace(trace) == trace
    assert (
        trace["records"][-1]["previous_trace_hash"]
        == trace["records"][-2]["trace_hash"]
    )


def test_cross_host_monotonic_clocks_are_compared_only_within_actor():
    recorder = LifecycleTraceRecorder(run_id="cross-host", approved_remote_parent="p")
    actor_clock = {
        "controller": 1_000,
        "bootstrap_transport": 10,
        "sealed_runtime": 100,
    }
    for step, _event, actor in EVENT_ACTOR_TABLE:
        actor_clock[actor] += 1
        recorder.append(
            input_hashes={f"i{step}": "a" * 64},
            output_hashes={f"o{step}": "b" * 64},
            monotonic_ns=actor_clock[actor],
        )
    assert validate_trace(recorder.seal())["terminal_status"] == "SUCCEEDED"

    broken = LifecycleTraceRecorder(run_id="same-actor", approved_remote_parent="p")
    broken.append(
        input_hashes={"i1": "a" * 64},
        output_hashes={"o1": "b" * 64},
        monotonic_ns=10,
    )
    broken.append(
        input_hashes={"i2": "a" * 64},
        output_hashes={"o2": "b" * 64},
        monotonic_ns=9,
    )
    with pytest.raises(TraceValidationError, match="actor monotonic"):
        validate_trace_prefix(
            broken.records,
            run_id="same-actor",
            approved_remote_parent="p",
        )


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "reordered", "actor", "aggregate"]
)
def test_validator_rejects_non_exact_lifecycle(mutation):
    trace = _trace()
    if mutation == "missing":
        trace["records"].pop(4)
    elif mutation == "duplicate":
        trace["records"][4] = copy.deepcopy(trace["records"][3])
    elif mutation == "reordered":
        trace["records"][0], trace["records"][1] = (
            trace["records"][1],
            trace["records"][0],
        )
    elif mutation == "actor":
        trace["records"][3]["actor"] = "controller"
    else:
        trace["records"] = [trace["records"][-1]]
    with pytest.raises(TraceValidationError):
        validate_trace(trace)


def test_validator_rejects_hash_chain_and_classification_tampering():
    trace = _trace()
    trace["records"][8]["previous_trace_hash"] = "f" * 64
    with pytest.raises(TraceValidationError, match="predecessor"):
        validate_trace(trace)
    trace = _trace()
    trace["records"][0]["classification"] = "LIVE_CLOSEOUT_EVIDENCE"
    with pytest.raises(TraceValidationError):
        validate_trace(trace)


def test_make_record_carries_parent_root_timestamps_and_hash_maps():
    record = make_record(
        run_id="r005",
        step_id=1,
        approved_remote_parent="parent-a",
        remote_run_root="/r",
        input_hashes={"manifest": "a" * 64},
        output_hashes={"runtime": "b" * 64},
        monotonic_ns=7,
    )
    assert record["remote_run_root"] == "/r"
    assert record["input_hashes"]["manifest"] == "a" * 64
    assert record["trace_hash"]


def test_synthetic_build_is_rejected_and_recorder_is_incremental():
    with pytest.raises(TraceValidationError, match="synthetic"):
        build_trace(run_id="r005", approved_remote_parent="parent-a")
    recorder = LifecycleTraceRecorder(run_id="r005", approved_remote_parent="parent-a")
    with pytest.raises(TraceValidationError):
        recorder.append(input_hashes={}, output_hashes={"x": "b" * 64})
    recorder.append(
        input_hashes={"x": "a" * 64}, output_hashes={"y": "b" * 64}, monotonic_ns=1
    )
    with pytest.raises(TraceValidationError, match="20"):
        recorder.seal()


def test_prefix_validation_and_resume_append_next_step():
    source = LifecycleTraceRecorder(run_id="r005", approved_remote_parent="parent-a")
    for step in range(1, 6):
        source.append(
            input_hashes={f"i{step}": "a" * 64},
            output_hashes={f"o{step}": "b" * 64},
            monotonic_ns=step,
        )
    prefix = source.records
    assert (
        validate_trace_prefix(prefix, run_id="r005", approved_remote_parent="parent-a")
        == prefix
    )
    resumed = LifecycleTraceRecorder.from_records(
        run_id="r005", approved_remote_parent="parent-a", records=prefix
    )
    assert resumed.next_step_id == 6
    resumed.append(
        input_hashes={"i6": "a" * 64}, output_hashes={"o6": "b" * 64}, monotonic_ns=6
    )
    assert resumed.records[-1]["previous_trace_hash"] == prefix[-1]["trace_hash"]


def test_prefix_resume_rejects_gap_and_parent_mismatch():
    source = LifecycleTraceRecorder(run_id="r005", approved_remote_parent="parent-a")
    for step in range(1, 4):
        source.append(
            input_hashes={f"i{step}": "a" * 64},
            output_hashes={f"o{step}": "b" * 64},
            monotonic_ns=step,
        )
    broken = copy.deepcopy(source.records)
    broken[1]["step_id"] = 3
    with pytest.raises(TraceValidationError):
        validate_trace_prefix(broken, run_id="r005", approved_remote_parent="parent-a")
    with pytest.raises(TraceValidationError):
        LifecycleTraceRecorder.from_records(
            run_id="r005", approved_remote_parent="other", records=source.records
        )


def test_schema_is_valid():
    schema_path = (
        Path(__file__).parents[1]
        / "src"
        / "rfb"
        / "contracts"
        / "research_lifecycle_trace.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validators.validator_for(schema).check_schema(schema)
