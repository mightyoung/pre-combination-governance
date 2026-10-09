from __future__ import annotations

import ast
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import validate

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rfb.methods import algorithms  # noqa: E402
from rfb.methods.api import run_method  # noqa: E402
from rfb.methods.lifecycle_engine import (  # noqa: E402
    CasRevisionConflict,
    LifecycleEngine,
    PostCommitCrash,
    PreCommitCrash,
    project_snapshot,
)
from rfb.research.lifecycle_properties import (  # noqa: E402
    FROZEN_SEED,
    FROZEN_TRACE_IDS,
    PROPERTY_IDS,
    build_frozen_corpus,
    validate_frozen_corpus,
)
from rfb.research.lifecycle_reference import evaluate_prefix  # noqa: E402
from rfb.research.lifecycle_qualification import execute_l01_l24  # noqa: E402


def _clean(action):
    return {key: value for key, value in action.items() if key != "fault"}


def _neutral(snapshot):
    """Remove only implementation provenance, retaining every semantic field."""
    return {
        key: value
        for key, value in snapshot.items()
        if key
        not in {
            "runtime_scientific_hash",
            "runtime_ledger_head",
            "scientific_binding",
            "ledger_head",
        }
    }


def test_frozen_corpus_schema_hash_and_actual_l01_l24_checkpoint_map():
    first, second = build_frozen_corpus(), build_frozen_corpus()
    schema = json.loads(
        (ROOT / "src/rfb/contracts/lifecycle_property_corpus.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert first == second
    assert validate_frozen_corpus(first)
    validate(first, schema)
    assert first["seed"] == FROZEN_SEED
    assert tuple(row["trace_id"] for row in first["traces"]) == FROZEN_TRACE_IDS
    certificate = first["coverage_certificate"]
    assert tuple(sorted(certificate["properties"])) == PROPERTY_IDS
    assert certificate["complete"] is True
    assert first["invalid_traces"][0]["scenario"] == "invalid_control"
    assert all(
        rows and rows[0]["assertion_id"] and rows[0]["test_id"]
        for rows in certificate["properties"].values()
    )
    report = execute_l01_l24()
    assert report["complete"] is True
    assert tuple(sorted(report["results"])) == PROPERTY_IDS
    assert all(row["status"] == "PASS" for row in report["results"].values())


def test_every_committed_prefix_matches_reference_replay_and_checkpoint_recovery():
    for trace in build_frozen_corpus()["traces"]:
        engine = LifecycleEngine(
            max_active_contributions=trace["cap"],
            max_contribution_budget=trace["budget"],
        )
        committed: list[dict] = []
        for action in trace["actions"]:
            fault = action.get("fault")
            if fault == "PRE_COMMIT_CRASH":
                before = engine.snapshot
                with pytest.raises(PreCommitCrash):
                    engine.apply(action)
                assert engine.snapshot is before
                engine = LifecycleEngine.recover(before)
                engine.apply(_clean(action))
                committed.append(_clean(action))
            elif fault == "POST_COMMIT_CRASH":
                with pytest.raises(PostCommitCrash):
                    engine.apply(action)
                committed.append(_clean(action))
                engine = LifecycleEngine.recover(engine.snapshot)
                # Lost acknowledgement is retried with the identical action.
                engine.apply(_clean(action))
                committed.append(_clean(action))
            elif fault == "CAS_CONFLICT":
                before = engine.snapshot
                with pytest.raises(CasRevisionConflict):
                    engine.apply(action, expected_revision=before.revision + 1)
                assert engine.snapshot is before
                engine.apply(_clean(action), expected_revision=before.revision)
                committed.append(_clean(action))
            else:
                engine.apply(action)
                committed.append(dict(action))

            actual = project_snapshot(engine.snapshot)
            expected = evaluate_prefix(
                committed, cap=trace["cap"], budget=trace["budget"]
            )
            replayed = project_snapshot(
                LifecycleEngine.replay(
                    committed,
                    max_active_contributions=trace["cap"],
                    max_contribution_budget=trace["budget"],
                )
            )
            assert _neutral(actual) == _neutral(expected), (
                trace["trace_id"],
                action["action_id"],
            )
            assert actual == replayed, (trace["trace_id"], action["action_id"])
            assert LifecycleEngine.recover(engine.snapshot).snapshot == engine.snapshot
            assert all(
                row["contribution_count"] <= 1 for row in actual["audit_classes"]
            )


def test_ordered_control_interleaving_versions_nonminimum_canonical_and_rebuilds():
    traces = {row["scenario"]: row for row in build_frozen_corpus()["traces"]}

    pre = LifecycleEngine.replay(traces["precommit_equivalence"]["actions"])
    assert pre.rebuild_count == 0
    assert pre.classes[0].canonical_root == "pr2"

    merged = LifecycleEngine.replay(traces["post_commit_merge"]["actions"])
    assert merged.rebuild_count == 1
    assert len(merged.classes) == 1
    assert merged.risk_score == pytest.approx(0.8)

    versions = LifecycleEngine.replay(traces["out_of_order_versions"]["actions"])
    assert dict(versions.effective_versions) == {"vr": 3}
    assert versions.classes[0].effective_version == 3
    assert versions.classes[0].support == pytest.approx(0.2)
    assert versions.stale_count == 1

    non_min = LifecycleEngine.replay(traces["non_min_canonical"]["actions"])
    assert non_min.classes[0].canonical_root == "z-root"
    assert dict(non_min.root_lifecycle)["z-root"] == "ACTIVE"
    assert dict(non_min.root_lifecycle)["a-root"] == "MERGED"

    retired = LifecycleEngine.replay(traces["supersede_retire_replay"]["actions"][:4])
    assert not retired.effective_versions
    assert dict(retired.audit_effective_versions) == {"sr1": 1, "sr2": 1}


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"max_active_contributions": 1}, "ACTIVE_CONTRIBUTION_CAP"),
        ({"max_contribution_budget": 1.0}, "CONTRIBUTION_BUDGET_CAP"),
    ],
)
def test_cap_and_budget_plus_one_fail_closed_and_hide_old_public_risk(kwargs, expected):
    engine = LifecycleEngine(**kwargs)
    amount = 1.0 if "max_contribution_budget" in kwargs else 0.5
    engine.apply(
        {
            "action_id": "bound-1",
            "op": "INITIALIZE",
            "order": 0,
            "message_id": "m1",
            "version": 1,
            "root_id": "r1",
            "support": 0.4,
            "contribution_amount": amount,
        }
    )
    before = engine.snapshot
    result = engine.apply(
        {
            "action_id": "bound-2",
            "op": "INITIALIZE",
            "order": 1,
            "message_id": "m2",
            "version": 1,
            "root_id": "r2",
            "support": 0.5,
            "contribution_amount": 0.01,
        }
    )
    assert result.status == "SAFE_HALT"
    assert result.snapshot.failure_code == expected
    assert result.snapshot.availability == "UNAVAILABLE"
    assert result.snapshot.gate == "CLOSED"
    assert result.snapshot.action == "FAIL_CLOSED"
    assert result.snapshot.risk_score is None
    assert result.snapshot.classes == before.classes
    assert result.snapshot.scientific_binding != before.scientific_binding
    assert result.snapshot.ledger_head != before.ledger_head
    projected = project_snapshot(result.snapshot)
    assert projected["classes"] == []
    assert projected["audit_classes"]


def test_explicit_safe_halt_and_invalid_controls_are_real_fail_closed_boundaries():
    engine = LifecycleEngine()
    engine.apply(
        {
            "action_id": "x1",
            "op": "INITIALIZE",
            "order": 0,
            "message_id": "m",
            "version": 1,
            "root_id": "r",
            "support": 0.4,
        }
    )
    before = engine.snapshot
    result = engine.apply({"action_id": "x2", "op": "SAFE_HALT", "order": 1})
    assert result.snapshot.failure_code == "EXPLICIT_SAFE_HALT"
    assert result.snapshot.risk_score is None
    assert result.snapshot.scientific_binding != before.scientific_binding

    for invalid in (
        {"action_id": "i1", "op": "MERGE", "order": 0, "roots": ["r"]},
        {
            "action_id": "i2",
            "op": "MERGE",
            "order": 0,
            "roots": ["r1", "r2"],
            "canonical_root": "outside",
        },
        {"action_id": "i3", "op": "SUPERSEDE", "order": 0, "roots": ["r"]},
    ):
        isolated = LifecycleEngine()
        before = isolated.snapshot
        with pytest.raises(ValueError):
            isolated.apply(invalid)
        assert isolated.snapshot is before


def test_controls_change_single_authority_binding_and_real_replay_validates_history():
    engine = LifecycleEngine()
    engine.apply(
        {
            "action_id": "a1",
            "op": "INITIALIZE",
            "order": 0,
            "message_id": "m1",
            "version": 1,
            "root_id": "r1",
            "support": 0.4,
        }
    )
    engine.apply(
        {
            "action_id": "a2",
            "op": "INITIALIZE",
            "order": 1,
            "message_id": "m2",
            "version": 1,
            "root_id": "r2",
            "support": 0.5,
        }
    )
    before_merge = engine.snapshot
    engine.apply(
        {
            "action_id": "a3",
            "op": "MERGE",
            "order": 2,
            "roots": ["r1", "r2"],
            "canonical_root": "r2",
        }
    )
    merged = engine.snapshot
    assert merged.runtime_scientific_hash == before_merge.runtime_scientific_hash
    assert merged.scientific_binding != before_merge.scientific_binding
    assert merged.ledger_head != before_merge.ledger_head
    assert dict(merged.root_lifecycle) == {"r1": "MERGED", "r2": "ACTIVE"}

    engine.apply({"action_id": "a4", "op": "RETIRE", "order": 3, "roots": ["r2"]})
    retired = engine.snapshot
    assert retired.scientific_binding != merged.scientific_binding
    assert retired.ledger_head != merged.ledger_head
    assert retired.effective_versions == ()
    assert retired.audit_effective_versions

    spend = retired.processing_spend
    engine.apply({"action_id": "a5", "op": "REPLAY", "order": 4})
    replayed = engine.snapshot
    assert replayed.replay_current is True
    assert replayed.processing_spend == spend
    assert LifecycleEngine.replay(replayed.history) == replayed


@pytest.mark.parametrize(
    "tamper",
    [
        lambda row: replace(row, scientific_binding="e" * 64),
        lambda row: replace(row, root_lifecycle=(("r", "RETIRED"),)),
        lambda row: replace(row, processing_spend=999.0),
        lambda row: replace(row, ledger_head="f" * 64),
    ],
    ids=["scientific-binding", "root-lifecycle", "processing-spend", "ledger-head"],
)
def test_tampered_checkpoint_replay_reanchors_a_recoverable_fail_closed_chain(tamper):
    engine = LifecycleEngine()
    engine.apply(
        {
            "action_id": "t1",
            "op": "INITIALIZE",
            "order": 0,
            "message_id": "m",
            "version": 1,
            "root_id": "r",
            "support": 0.4,
        }
    )
    clean = engine.snapshot
    corrupted = tamper(clean)
    with pytest.raises(Exception, match="CHECKPOINT"):
        LifecycleEngine.recover(corrupted)

    engine._snapshot = corrupted
    result = engine.apply({"action_id": "t2", "op": "REPLAY", "order": 1})
    failed = result.snapshot
    assert failed.status == "SAFE_HALT"
    assert failed.failure_code == "REPLAY_VALIDATION_FAILED"
    assert failed.replay_current is False
    assert failed.risk_score is None
    assert failed.history[-1].op == "REPLAY_VALIDATION_FAILED"
    assert failed.ledger[-1].previous_hash == clean.ledger_head
    assert failed.ledger[-1].before_scientific_binding == clean.scientific_binding
    assert LifecycleEngine.replay(failed.history) == failed
    assert LifecycleEngine.recover(failed).snapshot == failed


def test_proposed_behaviorally_calls_production_engine_and_uses_one_timeline(
    monkeypatch,
):
    calls = []
    real = algorithms.run_lifecycle

    def observed(actions, **kwargs):
        rows = tuple(actions)
        calls.append(rows)
        return real(rows, **kwargs)

    monkeypatch.setattr(algorithms, "run_lifecycle", observed)
    result = run_method(
        "Proposed",
        {
            "bundle_id": "g017-binding",
            "algorithm_seed": FROZEN_SEED,
            "transaction_id": "g017-tx",
            "events": [
                {
                    "message_id": "m1",
                    "version": 1,
                    "root_id": "r1",
                    "support": 0.8,
                    "order": 2,
                },
                {
                    "message_id": "m2",
                    "version": 1,
                    "root_id": "r2",
                    "support": 0.8,
                    "order": 3,
                },
            ],
            "controls": [
                {
                    "kind": "MERGE",
                    "roots": ["r1", "r2"],
                    "canonical_root": "r2",
                    "order": 1,
                }
            ],
        },
    )
    assert len(calls) == 1
    assert [row.op for row in calls[0]] == ["MERGE", "INITIALIZE", "INITIALIZE"]
    assert result["prediction"]["risk_score"] == pytest.approx(0.8)
    assert result["audit"]["rebuild_count"] == 0


def test_reference_import_isolation_is_structural():
    path = ROOT / "src/rfb/research/lifecycle_reference.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    forbidden = (
        "rfb.runtime",
        "rfb.methods",
        "rfb.dst",
        "rfb.contracts.canonical_json",
    )
    assert not any(name.startswith(forbidden) for name in imported)
    source = path.read_text(encoding="utf-8").casefold()
    assert "unionfind" not in source and "union_find" not in source
