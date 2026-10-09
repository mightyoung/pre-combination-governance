from __future__ import annotations

import ast
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from rfb.research.mme_events import (
    METHOD_IDS,
    RUN_CLASSES,
    PhysicalTruthSidecar,
    PublicControl,
    TruthRecord,
    experiment_specs,
    generate_block,
    generate_experiment,
    public_block_value,
    seed_for,
)
from rfb.research.mme_oracle import ACTION_THRESHOLD, evaluate_oracle

ROOT = Path(__file__).resolve().parents[1]
PREREG = ROOT.parent / ".omx" / "plans" / "MMEPreregistration-v2.json"


def spec(**changes):
    value = {
        "block_id": "ANCHOR",
        "duplicate_class": "distinct_key_same_acquisition",
        "equivalence_timing": "post_commit_long",
        "lifecycle": "merge",
        "independent_information": "one_new_root",
    }
    value.update(changes)
    return value


def test_preregistration_and_generator_freeze_27_blocks_and_8_methods():
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    specs = experiment_specs()
    assert prereg["status"] == "PREREGISTERED_IMPLEMENTATION_PENDING_D07_NO_EXPERIMENT"
    assert tuple(prereg["method_order"]) == METHOD_IDS
    assert len(METHOD_IDS) == 8
    assert len(specs) == 27
    assert len({row["block_id"] for row in specs}) == 27
    assert specs == tuple(prereg["factor_blocks"])
    blocks = generate_experiment("D_impl_unit")
    assert len(blocks) == 27
    assert all(len(block.prefixes) == 15 for block in blocks)
    assert next(row for row in blocks if row.block_id == "E08").generation_status == "NOT_IMPLEMENTED_SCOPE_BOUNDARY"


def test_run_classes_have_distinct_reproducible_seed_domains():
    assert RUN_CLASSES == ("D_impl_unit", "D_development", "MME_v2")
    seeds = [seed_for(run_class, "P01") for run_class in RUN_CLASSES]
    assert len(set(seeds)) == 3
    assert seeds == [seed_for(run_class, "P01") for run_class in RUN_CLASSES]
    with pytest.raises(ValueError):
        seed_for("D_test", "P01")


def test_every_arm_has_a_complete_cumulative_timeline_without_future_references():
    block = generate_block(spec(), run_class="D_impl_unit", physical_seed=11)
    assert [(row.arm_id, row.prefix_index) for row in block.prefixes] == [
        (arm, index) for arm in ("X", "XD", "XI") for index in range(5)
    ]
    opaque = re.compile(r"^[0-9a-f]{64}$")
    for arm in ("X", "XD", "XI"):
        counts = [len(block.prefix(arm, index).events) for index in range(5)]
        assert counts == sorted(counts)
        for index in range(5):
            prefix = block.prefix(arm, index)
            roots = {event.root_id for event in prefix.events}
            assert all(opaque.fullmatch(event.event_id) for event in prefix.events)
            assert all(set(control.roots) <= roots for control in prefix.controls)
            assert all(
                control.replacement_root is None or control.replacement_root in roots
                for control in prefix.controls
            )
            payload = prefix.method_payload()
            assert not {"block_id", "arm_id", "prefix_index", "prefix_id"} & payload.keys()
            assert opaque.fullmatch(payload["transaction_id"])


def test_truth_sidecar_mutation_cannot_change_method_payload():
    block = generate_block(spec(), run_class="D_impl_unit", physical_seed=12)
    before = public_block_value(block)
    changed_records = tuple(
        TruthRecord(row.event_id, "f" * 64) for row in block.truth_sidecar.records
    )
    changed = replace(
        block,
        truth_sidecar=PhysicalTruthSidecar(
            block.block_id,
            block.truth_sidecar.pair_id,
            changed_records,
            (),
        ),
    )
    assert public_block_value(changed) == before
    assert "truth" not in json.dumps(before).casefold()


def test_full_oracle_uses_sidecar_lifecycle_targets_not_public_operands():
    block = generate_block(
        spec(lifecycle="retire"), run_class="D_impl_unit", physical_seed=121
    )
    raw_prefix = block.prefix("XI", 3)
    prefix = replace(
        raw_prefix,
        events=tuple(
            replace(row, support=0.3) if row is raw_prefix.events[-1] else row
            for row in raw_prefix.events
        ),
    )
    original = evaluate_oracle(prefix, block.truth_sidecar)
    independent_root = prefix.events[-1].root_id
    altered_controls = tuple(
        PublicControl(
            row.control_id,
            row.op,
            (independent_root,) if row.op == "RETIRE" else row.roots,
            row.public_at,
            row.order,
            row.canonical_root,
            row.replacement_root,
        )
        for row in prefix.controls
    )
    altered = replace(prefix, controls=altered_controls)
    rescored = evaluate_oracle(altered, block.truth_sidecar)
    assert rescored.full_information == original.full_information
    assert rescored.publicly_knowable != original.publicly_knowable


def test_late_equivalence_and_independent_information_match_point_eight_anchors():
    block = generate_block(spec(), run_class="D_impl_unit", physical_seed=13)
    before = evaluate_oracle(block.prefix("XD", 1), block.truth_sidecar)
    disclosed = evaluate_oracle(block.prefix("XD", 2), block.truth_sidecar)
    independent = evaluate_oracle(block.prefix("XI", 2), block.truth_sidecar)
    assert before.full_information.simple_support == pytest.approx(0.8)
    assert before.publicly_knowable.simple_support == pytest.approx(0.96)
    assert disclosed.full_information.simple_support == pytest.approx(0.8)
    assert disclosed.publicly_knowable.simple_support == pytest.approx(0.8)
    assert independent.full_information.simple_support == pytest.approx(0.96)
    assert independent.publicly_knowable.simple_support == pytest.approx(0.96)
    assert disclosed.publicly_knowable.risk_interval == (0.8, 1.0)
    assert disclosed.publicly_knowable.action_state == "ACT"
    assert ACTION_THRESHOLD == 0.70
    assert disclosed.publicly_knowable.bpa == {
        "frame": ["RISK", "NOT_RISK"],
        "focal_sets": [["RISK"], ["RISK", "NOT_RISK"]],
        "masses": [0.8, 0.2],
    }


def test_delayed_disclosure_has_pre_disclosure_and_post_recovery_prefixes():
    block = generate_block(
        spec(block_id="E06", registry_error="delayed_disclosure"),
        run_class="D_impl_unit",
        physical_seed=14,
    )
    assert not block.prefix("XD", 2).controls
    assert len(block.prefix("XD", 3).controls) == 1
    assert block.prefix("XD", 4).controls == block.prefix("XD", 3).controls
    assert evaluate_oracle(block.prefix("XD", 2), block.truth_sidecar).publicly_knowable.simple_support == pytest.approx(0.96)
    assert evaluate_oracle(block.prefix("XD", 3), block.truth_sidecar).publicly_knowable.simple_support == pytest.approx(0.8)
    assert evaluate_oracle(block.prefix("XD", 4), block.truth_sidecar).publicly_knowable.simple_support == pytest.approx(0.8)


def test_supersede_retire_wrong_merge_and_capacity_anchors_are_distinct():
    supersede = generate_block(
        spec(lifecycle="supersede"), run_class="D_impl_unit", physical_seed=15
    )
    retired = generate_block(
        spec(lifecycle="retire"), run_class="D_impl_unit", physical_seed=16
    )
    wrong_merge = generate_block(
        spec(
            block_id="E05",
            duplicate_class="exact_retry",
            lifecycle="retire",
            independent_information="multiple_new_roots",
            registry_error="wrong_root_merge",
            eventifier="over_merge",
        ),
        run_class="D_impl_unit",
        physical_seed=17,
    )
    assert evaluate_oracle(supersede.prefix("X", 3), supersede.truth_sidecar).full_information.simple_support == pytest.approx(0.8)
    assert evaluate_oracle(retired.prefix("X", 3), retired.truth_sidecar).full_information.simple_support == pytest.approx(0.0)
    wrong = evaluate_oracle(wrong_merge.prefix("XI", 3), wrong_merge.truth_sidecar)
    assert wrong.full_information.simple_support == pytest.approx(0.96)
    assert wrong.publicly_knowable.simple_support == pytest.approx(0.8)
    e09 = generate_experiment("D_impl_unit")[23]
    e12 = generate_experiment("D_impl_unit")[26]
    assert e09.block_id == "E09" and e09.method_cap == 2
    assert e12.block_id == "E12" and e12.method_cap == 1


def test_method_payload_actions_match_lifecycle_json_boundary():
    block = generate_block(spec(), run_class="D_impl_unit", physical_seed=18)
    payload = block.prefix("XD", 2).method_payload()
    assert payload["method_cap"] == 1_000_000
    assert [row["op"] for row in payload["actions"]] == [
        "INITIALIZE",
        "INITIALIZE",
        "EQUIVALENCE",
    ]
    assert all("action_id" in row and "order" in row for row in payload["actions"])


def test_oracle_has_no_production_algorithm_imports():
    path = ROOT / "src" / "rfb" / "research" / "mme_oracle.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    forbidden = ("rfb.methods", "rfb.runtime", "rfb.dst", "lifecycle_engine")
    assert not any(any(part in name for part in forbidden) for name in imports)
