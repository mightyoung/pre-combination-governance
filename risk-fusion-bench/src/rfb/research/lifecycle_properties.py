"""Frozen deterministic G017 trace corpus and executable L01-L24 map."""

from __future__ import annotations

import hashlib
import json
import random
from copy import deepcopy
from typing import Any

FROZEN_SEED = 20260820
FROZEN_TRACE_IDS = tuple(f"g017-{index:02d}" for index in range(1, 11))
PROPERTY_IDS = tuple(f"L{index:02d}" for index in range(1, 25))


def _event(
    action_id: str, message: str, root: str, support: float, order: int, **extra: Any
) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "op": "INITIALIZE",
        "order": order,
        "message_id": message,
        "version": extra.pop("version", 1),
        "root_id": root,
        "support": support,
        "reliability": extra.pop("reliability", 1.0),
        **extra,
    }


def _control(
    action_id: str, op: str, order: int, roots: list[str] | None = None, **extra: Any
) -> dict[str, Any]:
    row = {"action_id": action_id, "op": op, "order": order, **extra}
    if roots is not None:
        row["roots"] = roots
    return row


def _trace(
    trace_id: str,
    scenario: str,
    actions: list[dict[str, Any]],
    *,
    cap: int = 8,
    budget: float = 8.0,
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "scenario": scenario,
        "cap": cap,
        "budget": budget,
        "actions": actions,
    }


def _property_map(traces: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    by_scenario = {row["scenario"]: row for row in traces}

    def hit(
        prop: str, scenario: str, action_id: str, assertion: str
    ) -> tuple[str, list[dict[str, str]]]:
        trace = by_scenario[scenario]
        if action_id not in {row["action_id"] for row in trace["actions"]}:
            raise ValueError(f"{prop} references a missing checkpoint")
        return prop, [
            {
                "trace_id": trace["trace_id"],
                "checkpoint": action_id,
                "assertion_id": assertion,
                "test_id": "rfb.research.lifecycle_qualification.execute_l01_l24",
            }
        ]

    return dict(
        [
            hit("L01", "precommit_equivalence", "p-3", "initialize_commits_one_class"),
            hit("L02", "duplicate_alias", "d-2", "exact_retry_no_second_charge"),
            hit(
                "L03",
                "precommit_equivalence",
                "p-1",
                "precommit_equivalence_zero_rebuild",
            ),
            hit(
                "L04",
                "post_commit_merge",
                "m-3",
                "postcommit_merge_rebuilds_unique_root",
            ),
            hit(
                "L05",
                "supersede_retire_replay",
                "s-3",
                "supersede_changes_root_lifecycle",
            ),
            hit(
                "L06",
                "supersede_retire_replay",
                "s-4",
                "retire_removes_public_contribution",
            ),
            hit("L07", "supersede_retire_replay", "s-5", "replay_is_current"),
            hit(
                "L08",
                "explicit_safe_halt",
                "x-2",
                "explicit_halt_is_unavailable_closed",
            ),
            hit(
                "L09",
                "out_of_order_versions",
                "v-2",
                "higher_version_wins_out_of_order",
            ),
            hit("L10", "out_of_order_versions", "v-2", "stale_version_is_audit_only"),
            hit(
                "L11",
                "non_min_canonical",
                "n-3",
                "declared_nonminimum_canonical_is_preserved",
            ),
            hit("L12", "crash_cas", "c-1", "precommit_crash_zero_commit"),
            hit("L13", "crash_cas", "c-2", "postcommit_crash_recovery"),
            hit("L14", "crash_cas", "c-3", "cas_conflict_zero_commit_then_retry"),
            hit("L15", "cap_boundary", "h-1", "active_cap_exact_boundary_allowed"),
            hit("L16", "cap_boundary", "h-2", "active_cap_plus_one_fail_closed"),
            hit("L17", "budget_boundary", "b-1", "budget_exact_boundary_allowed"),
            hit("L18", "budget_boundary", "b-2", "budget_plus_epsilon_fail_closed"),
            hit(
                "L19",
                "post_commit_merge",
                "m-2",
                "every_commit_is_checkpoint_recoverable",
            ),
            hit("L20", "duplicate_alias", "d-3", "processing_spend_is_immutable"),
            hit("L21", "explicit_safe_halt", "x-2", "public_risk_null_on_halt"),
            hit("L22", "post_commit_merge", "m-3", "scientific_binding_covers_control"),
            hit(
                "L23", "post_commit_merge", "m-3", "ledger_hash_chain_binds_transition"
            ),
            hit(
                "L24",
                "invalid_control",
                "i-1",
                "invalid_control_rejected_before_commit",
            ),
        ]
    )


def build_frozen_corpus() -> dict[str, Any]:
    rng = random.Random(FROZEN_SEED)
    shuffled = [
        _event("v-1", "vm", "vr", 0.9, 20, version=1),
        _event("v-2", "vm", "vr", 0.2, 10, version=3),
        _event("v-3", "vm", "vr", 0.99, 30, version=2),
    ]
    rng.shuffle(shuffled)
    traces = [
        _trace(
            FROZEN_TRACE_IDS[0],
            "duplicate_alias",
            [
                _event("d-1", "dm1", "dr1", 0.7, 0),
                _event("d-2", "dm1", "dr1", 0.7, 1),
                _event("d-3", "dm2", "dr2", 0.6, 2),
                _control("d-4", "EQUIVALENCE", 3, ["dr1", "dr2"], canonical_root="dr1"),
            ],
        ),
        _trace(
            FROZEN_TRACE_IDS[1],
            "precommit_equivalence",
            [
                _control("p-1", "EQUIVALENCE", 0, ["pr1", "pr2"], canonical_root="pr2"),
                _event("p-2", "pm1", "pr1", 0.4, 1),
                _event("p-3", "pm2", "pr2", 0.8, 2),
            ],
        ),
        _trace(
            FROZEN_TRACE_IDS[2],
            "post_commit_merge",
            [
                _event("m-1", "mm1", "mr1", 0.8, 0),
                _event("m-2", "mm2", "mr2", 0.8, 1),
                _control("m-3", "MERGE", 2, ["mr1", "mr2"], canonical_root="mr1"),
            ],
        ),
        _trace(
            FROZEN_TRACE_IDS[3],
            "supersede_retire_replay",
            [
                _event("s-1", "sm1", "sr1", 0.4, 0),
                _event("s-2", "sm2", "sr2", 0.9, 1),
                _control("s-3", "SUPERSEDE", 2, ["sr1"], replacement_root="sr2"),
                _control("s-4", "RETIRE", 3, ["sr2"]),
                _control("s-5", "REPLAY", 4),
            ],
        ),
        _trace(FROZEN_TRACE_IDS[4], "out_of_order_versions", shuffled),
        _trace(
            FROZEN_TRACE_IDS[5],
            "non_min_canonical",
            [
                _event("n-1", "nm1", "a-root", 0.3, 0),
                _event("n-2", "nm2", "z-root", 0.6, 1),
                _control(
                    "n-3", "MERGE", 2, ["a-root", "z-root"], canonical_root="z-root"
                ),
            ],
        ),
        _trace(
            FROZEN_TRACE_IDS[6],
            "crash_cas",
            [
                _event("c-1", "cm1", "cr1", 0.2, 0, fault="PRE_COMMIT_CRASH"),
                _event("c-2", "cm2", "cr2", 0.3, 1, fault="POST_COMMIT_CRASH"),
                _event("c-3", "cm3", "cr3", 0.4, 2, fault="CAS_CONFLICT"),
            ],
        ),
        _trace(
            FROZEN_TRACE_IDS[7],
            "cap_boundary",
            [
                _event("h-1", "hm1", "hr1", 0.4, 0),
                _event("h-2", "hm2", "hr2", 0.5, 1),
            ],
            cap=1,
        ),
        _trace(
            FROZEN_TRACE_IDS[8],
            "budget_boundary",
            [
                _event("b-1", "bm1", "br1", 0.4, 0, contribution_amount=1.0),
                _event("b-2", "bm2", "br2", 0.5, 1, contribution_amount=0.01),
            ],
            budget=1.0,
        ),
        _trace(
            FROZEN_TRACE_IDS[9],
            "explicit_safe_halt",
            [
                _event("x-1", "xm1", "xr1", 0.4, 0),
                _control("x-2", "SAFE_HALT", 1),
            ],
        ),
    ]
    # L24 is a negative checkpoint and therefore isolated in the executable
    # invalid corpus rather than mixed into the valid trace stream.
    invalid = _trace(
        "g017-invalid", "invalid_control", [_control("i-1", "MERGE", 0, ["only-one"])]
    )
    property_coverage = _property_map([*traces, invalid])
    body = {
        "operations": sorted(
            {action["op"] for trace in traces for action in trace["actions"]}
        ),
        "faults": sorted(
            {
                action["fault"]
                for trace in traces
                for action in trace["actions"]
                if "fault" in action
            }
        ),
        "trace_ids": list(FROZEN_TRACE_IDS),
        "properties": property_coverage,
        "complete": tuple(sorted(property_coverage)) == PROPERTY_IDS,
    }
    body["sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return deepcopy(
        {
            "schema_version": "2.0.0",
            "classification": "DEVELOPMENT_NONCONFIRMATORY",
            "formal_gate_effect": "NONE",
            "seed": FROZEN_SEED,
            "coverage_certificate": body,
            "traces": traces,
            "invalid_traces": [invalid],
        }
    )


def validate_frozen_corpus(document: dict[str, Any]) -> bool:
    if document.get("seed") != FROZEN_SEED:
        raise ValueError("frozen lifecycle seed mismatch")
    if (
        tuple(row.get("trace_id") for row in document.get("traces", ()))
        != FROZEN_TRACE_IDS
    ):
        raise ValueError("frozen lifecycle trace IDs mismatch")
    certificate = dict(document.get("coverage_certificate", {}))
    received = certificate.pop("sha256", None)
    expected = hashlib.sha256(
        json.dumps(certificate, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    if (
        received != expected
        or tuple(sorted(certificate.get("properties", {}))) != PROPERTY_IDS
    ):
        raise ValueError("coverage certificate mismatch")
    return True


__all__ = [
    "FROZEN_SEED",
    "FROZEN_TRACE_IDS",
    "PROPERTY_IDS",
    "build_frozen_corpus",
    "validate_frozen_corpus",
]
