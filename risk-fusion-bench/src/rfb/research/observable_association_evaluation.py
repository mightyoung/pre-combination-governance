"""Finite, offline synthetic evaluation contracts for observable association.

Generated method inputs contain only timestamped observable records. World
grouping, pair labels, sufficient-evidence times, and alert opportunities live
in a separate scorer sidecar and are read only after method outputs are
frozen. This module does not run a formal evaluation at import time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import itertools
import json
import random
import re
from statistics import fmean
from typing import Mapping, Sequence

from . import observable_association as association


_UTC = timezone.utc
_BASE_TIME = datetime(2026, 10, 11, 12, 0, tzinfo=_UTC)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_OBSERVATIONS_PER_WORLD = 7
_MAX_CUTOFFS_PER_WORLD = 8
_MAX_PAIR_COUNT_PER_WORLD = 6
_EVALUATION_CUTOFF_SECONDS = 120
_REPLAY_RECEIVED_SECONDS = 100
_RISK_UPGRADE_SECONDS = 90


class SyntheticStratum(str, Enum):
    INDEPENDENT_SAME_EVENT = "independent_same_event"
    ADJACENT_DISTINCT_ASSETS = "adjacent_distinct_assets"
    RECOVERY_THEN_NEW_EVENT = "recovery_then_new_event"
    DEPENDENT_REPLAY_UNKNOWN = "dependent_replay_unknown"


class PairTruthLabel(str, Enum):
    SAME = "SAME"
    DIFFERENT = "DIFFERENT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SplitPlan:
    name: str
    seed: int
    world_budget: int
    worlds_per_stratum: int
    search_configs_per_method: int = 0

    def __post_init__(self) -> None:
        if self.name not in {"development", "heldout"}:
            raise ValueError("split name must be development or heldout")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("split seed must be a non-negative integer")
        if (
            isinstance(self.world_budget, bool)
            or not isinstance(self.world_budget, int)
            or self.world_budget < 1
        ):
            raise ValueError("world_budget must be a positive integer")
        if (
            isinstance(self.worlds_per_stratum, bool)
            or not isinstance(self.worlds_per_stratum, int)
            or self.worlds_per_stratum < 1
        ):
            raise ValueError("worlds_per_stratum must be a positive integer")
        if self.world_budget != len(SyntheticStratum) * self.worlds_per_stratum:
            raise ValueError("world budget must match the balanced stratum allocation")
        if self.search_configs_per_method != 0:
            raise ValueError("this protocol freezes one config and has zero search slots")


@dataclass(frozen=True, slots=True)
class ObservableTrajectory:
    """Method-side input only; contains no world or scorer labels."""

    records: tuple[association.ObservationRecord, ...]
    cutoffs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.records, tuple) or any(
            not isinstance(item, association.ObservationRecord) for item in self.records
        ):
            raise ValueError("records must be a tuple of ObservationRecord values")
        if not isinstance(self.cutoffs, tuple) or not self.cutoffs:
            raise ValueError("cutoffs must be a non-empty tuple")
        parsed = tuple(_parse_timestamp(item, "cutoff") for item in self.cutoffs)
        if parsed != tuple(sorted(set(parsed))):
            raise ValueError("cutoffs must be unique and sorted")
        if len(self.records) > _MAX_OBSERVATIONS_PER_WORLD:
            raise ValueError("world exceeds the registered record budget")
        abnormal_observation_ids = {
            record.observation_id
            for record in self.records
            if any(
                field.name == "risk_flag"
                and field.value in {"EXPOSURE", "EXPOSURE_HIGH"}
                for field in record.fields
            )
        }
        if len(abnormal_observation_ids) != 4:
            raise ValueError("world must contain exactly four unique abnormal observation IDs")
        if len(self.cutoffs) > _MAX_CUTOFFS_PER_WORLD:
            raise ValueError("world exceeds the registered cutoff budget")


@dataclass(frozen=True, slots=True)
class PairTruth:
    pair: association.CandidatePair
    label: PairTruthLabel
    first_sufficient_evidence_at: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.pair, association.CandidatePair):
            raise TypeError("pair must be a CandidatePair")
        try:
            object.__setattr__(self, "label", PairTruthLabel(self.label))
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported pair truth label") from exc
        if self.first_sufficient_evidence_at is not None:
            object.__setattr__(
                self,
                "first_sufficient_evidence_at",
                _format_timestamp(
                    _parse_timestamp(
                        self.first_sufficient_evidence_at,
                        "first_sufficient_evidence_at",
                    )
                ),
            )
        if self.label is PairTruthLabel.UNKNOWN and self.first_sufficient_evidence_at is not None:
            raise ValueError("UNKNOWN pair truth cannot have a sufficient-evidence time")


@dataclass(frozen=True, slots=True)
class AlertEscalationOpportunity:
    observation_id: str
    risk_flag_known_at: str
    evaluation_cutoff: str
    required_severity: str = "CRITICAL"

    def __post_init__(self) -> None:
        if not isinstance(self.observation_id, str) or not self.observation_id.strip():
            raise ValueError("observation_id must be a non-empty string")
        known = _parse_timestamp(self.risk_flag_known_at, "risk_flag_known_at")
        cutoff = _parse_timestamp(self.evaluation_cutoff, "evaluation_cutoff")
        if cutoff < known:
            raise ValueError("escalation cutoff cannot precede the risk flag")
        if self.required_severity != "CRITICAL":
            raise ValueError("synthetic escalation opportunities require CRITICAL")
        object.__setattr__(self, "risk_flag_known_at", _format_timestamp(known))
        object.__setattr__(self, "evaluation_cutoff", _format_timestamp(cutoff))


@dataclass(frozen=True, slots=True)
class AlertAction:
    observation_id: str
    severity: str
    decided_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.observation_id, str) or not self.observation_id.strip():
            raise ValueError("observation_id must be a non-empty string")
        if not isinstance(self.severity, str) or not self.severity.strip():
            raise ValueError("severity must be a non-empty string")
        object.__setattr__(
            self,
            "decided_at",
            _format_timestamp(_parse_timestamp(self.decided_at, "decided_at")),
        )


@dataclass(frozen=True, slots=True)
class ScorerSidecar:
    """Truth and grouping data that is never passed to an association rule."""

    world_group_id: str
    stratum: SyntheticStratum
    pair_truths: tuple[PairTruth, ...]
    evaluation_cutoff: str
    escalation_opportunities: tuple[AlertEscalationOpportunity, ...]
    split_name: str = "contract_test"

    def __post_init__(self) -> None:
        if not isinstance(self.world_group_id, str) or not self.world_group_id.strip():
            raise ValueError("world_group_id must be a non-empty string")
        try:
            object.__setattr__(self, "stratum", SyntheticStratum(self.stratum))
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported synthetic stratum") from exc
        if self.split_name not in {"development", "heldout", "contract_test"}:
            raise ValueError("unsupported split name")
        if not isinstance(self.pair_truths, tuple) or any(
            not isinstance(item, PairTruth) for item in self.pair_truths
        ):
            raise ValueError("pair_truths must be a tuple of PairTruth values")
        if not self.pair_truths:
            raise ValueError("pair_truths must define a fixed scoring universe")
        pairs = [item.pair for item in self.pair_truths]
        if len(pairs) != len(set(pairs)):
            raise ValueError("pair truth contains duplicate scoring pairs")
        if self.split_name in {"development", "heldout"}:
            observation_ids = sorted(
                {
                    observation_id
                    for pair in pairs
                    for observation_id in (
                        pair.left_observation_id,
                        pair.right_observation_id,
                    )
                }
            )
            if len(observation_ids) != 4:
                raise ValueError("formal split must score all pairs from four observations")
            expected_pairs = {
                association.CandidatePair(left, right)
                for left, right in itertools.combinations(observation_ids, 2)
            }
            if set(pairs) != expected_pairs:
                raise ValueError("formal split must include the complete fixed six-pair universe")
            unknown_count = sum(
                row.label is PairTruthLabel.UNKNOWN for row in self.pair_truths
            )
            expected_unknown_count = (
                1 if self.stratum is SyntheticStratum.DEPENDENT_REPLAY_UNKNOWN else 0
            )
            if unknown_count != expected_unknown_count:
                raise ValueError("formal split UNKNOWN pairs must match the registered stratum")
        cutoff = _parse_timestamp(self.evaluation_cutoff, "evaluation_cutoff")
        object.__setattr__(self, "evaluation_cutoff", _format_timestamp(cutoff))
        if not isinstance(self.escalation_opportunities, tuple) or any(
            not isinstance(item, AlertEscalationOpportunity)
            for item in self.escalation_opportunities
        ):
            raise ValueError("escalation_opportunities must be a tuple")
        for item in self.pair_truths:
            if item.first_sufficient_evidence_at is not None and _parse_timestamp(
                item.first_sufficient_evidence_at, "first_sufficient_evidence_at"
            ) > cutoff:
                raise ValueError("sufficient evidence cannot occur after evaluation cutoff")
        for opportunity in self.escalation_opportunities:
            if opportunity.evaluation_cutoff != self.evaluation_cutoff:
                raise ValueError("alert opportunity cutoff must match the world cutoff")


@dataclass(frozen=True, slots=True)
class GeneratedWorld:
    observable: ObservableTrajectory
    scorer_only: ScorerSidecar

    def __post_init__(self) -> None:
        if not isinstance(self.observable, ObservableTrajectory):
            raise TypeError("observable must be an ObservableTrajectory")
        if not isinstance(self.scorer_only, ScorerSidecar):
            raise TypeError("scorer_only must be a ScorerSidecar")


@dataclass(frozen=True, slots=True)
class FrozenArmStep:
    method: str
    cutoff: str
    candidate_pairs: tuple[association.CandidatePair, ...]
    input_prefix_sha256: str
    output: association.FrozenAssociationOutput

    def __post_init__(self) -> None:
        if self.method not in {"TIME_ASSET_RULE", "MULTI_EVIDENCE_RULE"}:
            raise ValueError("unsupported evaluation method")
        object.__setattr__(self, "cutoff", _format_timestamp(_parse_timestamp(self.cutoff, "cutoff")))
        if not isinstance(self.candidate_pairs, tuple) or any(
            not isinstance(item, association.CandidatePair) for item in self.candidate_pairs
        ):
            raise ValueError("candidate_pairs must be a tuple of CandidatePair values")
        if len(self.candidate_pairs) != len(set(self.candidate_pairs)):
            raise ValueError("candidate_pairs must not contain duplicates")
        if not isinstance(self.input_prefix_sha256, str) or not _SHA256_RE.fullmatch(
            self.input_prefix_sha256
        ):
            raise ValueError("input_prefix_sha256 must be lowercase SHA-256")
        if not isinstance(self.output, association.FrozenAssociationOutput):
            raise TypeError("output must be a FrozenAssociationOutput")


@dataclass(frozen=True, slots=True)
class _RecordSpec:
    observation_id: str
    event_slot: int
    asset_id: str
    modality: str
    source_seconds: int
    position: tuple[float, float]
    root_id: str
    value: float
    received_seconds: int | None = None


def get_split_plan(name: str) -> SplitPlan:
    if name == "development":
        return SplitPlan(
            name="development",
            seed=2026101101,
            world_budget=12,
            worlds_per_stratum=3,
        )
    if name == "heldout":
        return SplitPlan(
            name="heldout",
            seed=2026101102,
            world_budget=24,
            worlds_per_stratum=6,
        )
    raise ValueError("split must be development or heldout")


def generate_protocol_split(
    name: str, *, protocol_approved: bool = False
) -> tuple[GeneratedWorld, ...]:
    """Generate a registered finite split; held-out requires an explicit review gate."""
    plan = get_split_plan(name)
    if not isinstance(protocol_approved, bool):
        raise TypeError("protocol_approved must be a bool")
    if plan.name == "heldout" and protocol_approved is not True:
        raise PermissionError("held-out generation is blocked until protocol review")
    worlds: list[GeneratedWorld] = []
    world_index = 0
    for stratum in SyntheticStratum:
        for _ in range(plan.worlds_per_stratum):
            worlds.append(
                generate_synthetic_world(
                    seed=plan.seed,
                    world_index=world_index,
                    stratum=stratum,
                    split_name=plan.name,
                    protocol_approved=protocol_approved,
                )
            )
            world_index += 1
    return tuple(worlds)


def generate_synthetic_world(
    *,
    seed: int,
    world_index: int,
    stratum: SyntheticStratum | str,
    split_name: str = "contract_test",
    protocol_approved: bool = False,
) -> GeneratedWorld:
    """Generate one deterministic test/development world without running a method."""
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if isinstance(world_index, bool) or not isinstance(world_index, int) or world_index < 0:
        raise ValueError("world_index must be a non-negative integer")
    if split_name not in {"development", "heldout", "contract_test"}:
        raise ValueError("unsupported split name")
    if not isinstance(protocol_approved, bool):
        raise TypeError("protocol_approved must be a bool")
    if split_name == "heldout" and not protocol_approved:
        raise PermissionError("held-out generation is blocked until protocol review")
    try:
        selected_stratum = SyntheticStratum(stratum)
    except (TypeError, ValueError) as exc:
        raise ValueError("unsupported synthetic stratum") from exc

    material = f"observable-association-v1|{split_name}|{seed}|{world_index}|{selected_stratum.value}"
    token = hashlib.sha256(material.encode("utf-8")).hexdigest()
    rng = random.Random(int(token[:16], 16))
    world_group_id = f"WG-{token[:24]}"

    event_a_asset = f"ASSET-{_opaque_id(token, 'asset-a')}"
    event_b_asset = (
        event_a_asset
        if selected_stratum is SyntheticStratum.RECOVERY_THEN_NEW_EVENT
        else f"ASSET-{_opaque_id(token, 'asset-b')}"
    )
    observation_ids = tuple(
        f"OBS-{_opaque_id(token, f'observation-{index}')}" for index in range(4)
    )
    root_ids = tuple(f"ROOT-{_opaque_id(token, f'root-{index}')}" for index in range(4))

    event_a_second = 5 + rng.randrange(0, 3)
    if selected_stratum is SyntheticStratum.RECOVERY_THEN_NEW_EVENT:
        event_b_first = 60 + rng.randrange(0, 4)
    else:
        event_b_first = 20 + rng.randrange(0, 8)
    event_b_second = event_b_first + 5 + rng.randrange(0, 3)

    if selected_stratum in {
        SyntheticStratum.ADJACENT_DISTINCT_ASSETS,
        SyntheticStratum.DEPENDENT_REPLAY_UNKNOWN,
    }:
        event_b_positions = ((1.0, 0.0), (1.2, 0.1))
    elif selected_stratum is SyntheticStratum.RECOVERY_THEN_NEW_EVENT:
        event_b_positions = ((0.15, 0.0), (0.2, 0.1))
    else:
        event_b_positions = ((24.0, 0.0), (24.2, 0.1))

    event_a_roots = (
        (root_ids[0], root_ids[0])
        if selected_stratum is SyntheticStratum.DEPENDENT_REPLAY_UNKNOWN
        else (root_ids[0], root_ids[1])
    )
    specs = (
        _RecordSpec(observation_ids[0], 0, event_a_asset, "TEMPERATURE", 0, (0.0, 0.0), event_a_roots[0], 80.0 + rng.uniform(-0.25, 0.25)),
        _RecordSpec(observation_ids[1], 0, event_a_asset, "THERMAL_IMAGE", event_a_second, (0.1, 0.0), event_a_roots[1], 80.5 + rng.uniform(-0.25, 0.25), event_a_second + 8),
        _RecordSpec(observation_ids[2], 1, event_b_asset, "TEMPERATURE", event_b_first, event_b_positions[0], root_ids[2], 80.1 + rng.uniform(-0.25, 0.25), event_b_first + 4),
        _RecordSpec(observation_ids[3], 1, event_b_asset, "THERMAL_IMAGE", event_b_second, event_b_positions[1], root_ids[3], 80.6 + rng.uniform(-0.25, 0.25), event_b_second + 10),
    )
    records = [_build_observation_record(spec) for spec in specs]

    recovery_spec: _RecordSpec | None = None
    if selected_stratum is SyntheticStratum.RECOVERY_THEN_NEW_EVENT:
        recovery_spec = _RecordSpec(
            observation_id=f"OBS-{_opaque_id(token, 'recovery-marker')}",
            event_slot=-1,
            asset_id=event_a_asset,
            modality="RECOVERY_MARKER",
            source_seconds=30,
            position=(0.1, 0.0),
            root_id=f"ROOT-{_opaque_id(token, 'recovery-root')}",
            value=0.0,
        )
        records.append(_build_recovery_record(recovery_spec))

    records.append(_build_risk_update_record(records[0], _RISK_UPGRADE_SECONDS))
    if selected_stratum is SyntheticStratum.DEPENDENT_REPLAY_UNKNOWN:
        original = records[0]
        records.append(
            association.ObservationRecord(
                observation_id=original.observation_id,
                id_actual_available_at=original.id_actual_available_at,
                id_earliest_known_at=original.id_earliest_known_at,
                received_at=_stamp(_REPLAY_RECEIVED_SECONDS),
                fields=original.fields,
            )
        )

    evaluation_cutoff = _stamp(_EVALUATION_CUTOFF_SECONDS)
    cutoffs = tuple(
        sorted(
            {_format_timestamp(_parse_timestamp(item.received_at, "received_at")) for item in records}
            | {evaluation_cutoff},
            key=lambda value: _parse_timestamp(value, "cutoff"),
        )
    )
    observable = ObservableTrajectory(records=tuple(records), cutoffs=cutoffs)

    root_by_observation = {spec.observation_id: spec.root_id for spec in specs}
    event_by_observation = {spec.observation_id: spec.event_slot for spec in specs}
    received_by_observation = {
        spec.observation_id: _parse_timestamp(
            _stamp(_record_received_seconds(spec)), "received_at"
        )
        for spec in specs
    }
    recovery_received = (
        _parse_timestamp(_stamp(recovery_spec.source_seconds), "source_time")
        if recovery_spec is not None
        else None
    )
    pair_truths: list[PairTruth] = []
    for left_id, right_id in itertools.combinations(sorted(observation_ids), 2):
        pair = association.CandidatePair(left_id, right_id)
        same_event = event_by_observation[left_id] == event_by_observation[right_id]
        if (
            selected_stratum is SyntheticStratum.DEPENDENT_REPLAY_UNKNOWN
            and {left_id, right_id} == {observation_ids[0], observation_ids[2]}
        ):
            label = PairTruthLabel.UNKNOWN
            sufficient_at = None
        elif same_event:
            label = PairTruthLabel.SAME
            roots = {root_by_observation[left_id], root_by_observation[right_id]}
            sufficient_at = (
                _format_timestamp(max(received_by_observation[left_id], received_by_observation[right_id]))
                if len(roots) >= 2
                else None
            )
        else:
            label = PairTruthLabel.DIFFERENT
            required_times = [received_by_observation[left_id], received_by_observation[right_id]]
            if recovery_received is not None:
                required_times.append(recovery_received)
            sufficient_at = _format_timestamp(max(required_times))
        pair_truths.append(
            PairTruth(pair, label, sufficient_at)
        )

    escalation_opportunity = AlertEscalationOpportunity(
        observation_id=observation_ids[0],
        risk_flag_known_at=_stamp(_RISK_UPGRADE_SECONDS),
        evaluation_cutoff=evaluation_cutoff,
    )
    scorer_only = ScorerSidecar(
        world_group_id=world_group_id,
        stratum=selected_stratum,
        pair_truths=tuple(pair_truths),
        evaluation_cutoff=evaluation_cutoff,
        escalation_opportunities=(escalation_opportunity,),
        split_name=split_name,
    )
    return GeneratedWorld(observable=observable, scorer_only=scorer_only)


def serialize_observable_trajectory(trajectory: ObservableTrajectory) -> bytes:
    """Serialize only method-visible records/cutoffs; no sidecar is accepted."""
    if not isinstance(trajectory, ObservableTrajectory):
        raise TypeError("trajectory must be an ObservableTrajectory")
    rows = []
    for record in trajectory.records:
        rows.append(
            {
                "observation_id": record.observation_id,
                "id_actual_available_at": record.id_actual_available_at,
                "id_earliest_known_at": record.id_earliest_known_at,
                "received_at": record.received_at,
                "fields": [
                    {
                        "name": item.name,
                        "value": _json_value(item.value),
                        "actual_available_at": item.actual_available_at,
                        "earliest_known_at": item.earliest_known_at,
                    }
                    for item in sorted(record.fields, key=lambda field: field.name)
                ],
            }
        )
    rows.sort(key=lambda row: (row["observation_id"], row["received_at"]))
    return json.dumps(
        {"trajectory_version": "observable-association-synthetic-v1", "cutoffs": list(trajectory.cutoffs), "records": rows},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def run_two_methods(trajectory: ObservableTrajectory) -> tuple[FrozenArmStep, ...]:
    """Run both frozen rules on identical per-cutoff prefixes and pair inputs."""
    if not isinstance(trajectory, ObservableTrajectory):
        raise TypeError("trajectory must be an ObservableTrajectory, never a scorer sidecar")
    config = association.InferenceConfig()
    methods = (
        ("TIME_ASSET_RULE", association.time_asset_rule),
        ("MULTI_EVIDENCE_RULE", association.multi_evidence_rule),
    )
    steps: list[FrozenArmStep] = []
    for cutoff in trajectory.cutoffs:
        prefix = association.freeze_observable_prefix(trajectory.records, as_of=cutoff)
        prefix_hash = _prefix_sha256(prefix)
        candidate_pairs = association.build_candidate_universe(prefix, config=config)
        for method_name, method in methods:
            proposals = tuple(
                method(prefix, pair, config=config) for pair in candidate_pairs
            )
            steps.append(
                FrozenArmStep(
                    method=method_name,
                    cutoff=cutoff,
                    candidate_pairs=candidate_pairs,
                    input_prefix_sha256=prefix_hash,
                    output=association.freeze_proposals(proposals),
                )
            )
    return tuple(steps)


def score_world(
    steps: Sequence[FrozenArmStep],
    scorer_only: ScorerSidecar,
    *,
    alert_actions: Sequence[AlertAction] | None = None,
) -> dict[str, object]:
    """Score frozen pair proposals against a separate scorer-only sidecar."""
    if not isinstance(scorer_only, ScorerSidecar):
        raise TypeError("scorer_only must be a ScorerSidecar")
    validated_steps = _validate_steps(steps, scorer_only)
    truth_by_pair = {row.pair: row for row in scorer_only.pair_truths}
    methods = ("TIME_ASSET_RULE", "MULTI_EVIDENCE_RULE")
    final_cutoff = scorer_only.evaluation_cutoff
    method_scores: dict[str, object] = {}

    for method_name in methods:
        method_steps = [step for step in validated_steps if step.method == method_name]
        actions_by_pair: dict[association.CandidatePair, list[tuple[str, association.ProposalAction]]] = {}
        for step in method_steps:
            for pair, action in _step_actions(step).items():
                actions_by_pair.setdefault(pair, []).append((step.cutoff, action))
        final_step = next(step for step in method_steps if step.cutoff == final_cutoff)
        final_actions = _step_actions(final_step)

        same_rows = [row for row in scorer_only.pair_truths if row.label is PairTruthLabel.SAME]
        different_rows = [row for row in scorer_only.pair_truths if row.label is PairTruthLabel.DIFFERENT]
        unknown_rows = [row for row in scorer_only.pair_truths if row.label is PairTruthLabel.UNKNOWN]
        false_merge_count = sum(
            final_actions.get(row.pair, association.ProposalAction.ABSTAIN)
            is association.ProposalAction.LINK_CANDIDATES
            for row in different_rows
        )
        false_split_count = sum(
            final_actions.get(row.pair, association.ProposalAction.ABSTAIN)
            is association.ProposalAction.RETAIN_SEPARATELY
            for row in same_rows
        )
        coverage_count = sum(
            final_actions.get(pair, association.ProposalAction.ABSTAIN)
            is not association.ProposalAction.ABSTAIN
            for pair in truth_by_pair
        )
        non_abstaining_unknown_count = sum(
            final_actions.get(row.pair, association.ProposalAction.ABSTAIN)
            is not association.ProposalAction.ABSTAIN
            for row in unknown_rows
        )
        unknown_action_counts = {
            action.value: sum(
                final_actions.get(row.pair, association.ProposalAction.ABSTAIN) is action
                for row in unknown_rows
            )
            for action in association.ProposalAction
        }
        candidate_generation_recall_count = sum(
            any(row.pair in step.candidate_pairs for step in method_steps)
            for row in same_rows
        )
        decision_timing = tuple(
            _decision_timing_record(
                row,
                actions_by_pair.get(row.pair, []),
                evaluation_cutoff=final_cutoff,
            )
            for row in scorer_only.pair_truths
        )
        method_scores[method_name] = {
            "fixed_pair_denominator": len(scorer_only.pair_truths),
            "same_pair_denominator": len(same_rows),
            "different_pair_denominator": len(different_rows),
            "unknown_pair_count": len(unknown_rows),
            "false_merge_count": false_merge_count,
            "false_merge_rate": _safe_rate(false_merge_count, len(different_rows)),
            "false_split_count": false_split_count,
            "false_split_rate": _safe_rate(false_split_count, len(same_rows)),
            "coverage_count": coverage_count,
            "coverage_denominator": len(scorer_only.pair_truths),
            "coverage": _safe_rate(coverage_count, len(scorer_only.pair_truths)),
            "non_abstaining_unknown_count": non_abstaining_unknown_count,
            "unknown_action_counts": unknown_action_counts,
            "candidate_generation_recall_count": candidate_generation_recall_count,
            "candidate_generation_recall_denominator": len(same_rows),
            "candidate_generation_recall": _safe_rate(
                candidate_generation_recall_count, len(same_rows)
            ),
            "decision_timing": decision_timing,
            "timing_status_counts": _timing_status_counts(decision_timing),
            "metric_interpretation": "PENDING_PROPOSAL_PROXY_NOT_FINAL_EVENT_IDENTITY",
        }

    alert_score = score_alert_escalation_misses(
        scorer_only.escalation_opportunities, alert_actions
    )
    return {
        "score_version": "observable-association-finite-score-v1",
        "split_name": scorer_only.split_name,
        "world_group_id": scorer_only.world_group_id,
        "stratum": scorer_only.stratum.value,
        "evaluation_cutoff": final_cutoff,
        "independent_world_count": 1,
        "methods": method_scores,
        "alert_escalation": alert_score,
    }


def score_alert_escalation_misses(
    opportunities: Sequence[AlertEscalationOpportunity],
    actions: Sequence[AlertAction] | None,
) -> dict[str, object]:
    """Score escalation misses separately; absent alert output is not inferred."""
    if not isinstance(opportunities, (tuple, list)) or any(
        not isinstance(item, AlertEscalationOpportunity) for item in opportunities
    ):
        raise ValueError("opportunities must contain AlertEscalationOpportunity values")
    if actions is None:
        return {
            "status": "NOT_EVALUATED",
            "denominator": 0,
            "missed_count": None,
            "miss_rate": None,
            "delays_seconds": (),
        }
    if not isinstance(actions, (tuple, list)) or any(
        not isinstance(item, AlertAction) for item in actions
    ):
        raise ValueError("actions must contain AlertAction values")
    if not opportunities:
        return {
            "status": "NOT_APPLICABLE",
            "denominator": 0,
            "missed_count": 0,
            "miss_rate": None,
            "delays_seconds": (),
        }

    missed = 0
    delays: list[int] = []
    for opportunity in opportunities:
        start = _parse_timestamp(opportunity.risk_flag_known_at, "risk_flag_known_at")
        end = _parse_timestamp(opportunity.evaluation_cutoff, "evaluation_cutoff")
        matching = [
            _parse_timestamp(action.decided_at, "decided_at")
            for action in actions
            if action.observation_id == opportunity.observation_id
            and action.severity == opportunity.required_severity
            and start <= _parse_timestamp(action.decided_at, "decided_at") <= end
        ]
        if not matching:
            missed += 1
        else:
            delays.append(int((min(matching) - start).total_seconds()))
    return {
        "status": "EVALUATED",
        "denominator": len(opportunities),
        "missed_count": missed,
        "miss_rate": _safe_rate(missed, len(opportunities)),
        "delays_seconds": tuple(delays),
    }


def aggregate_world_scores(world_scores: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Aggregate equally weighted worlds without allowing partial formal splits."""
    if not isinstance(world_scores, (tuple, list)) or any(
        not isinstance(item, Mapping) for item in world_scores
    ):
        raise ValueError("world_scores must be a sequence of world score mappings")
    if not world_scores:
        raise ValueError("world_scores must not be empty")
    world_ids = [item.get("world_group_id") for item in world_scores]
    if any(not isinstance(item, str) or not item for item in world_ids):
        raise ValueError("each world score must carry a world_group_id")
    if len(world_ids) != len(set(world_ids)):
        raise ValueError("duplicate world_group_id would inflate the independent-world count")
    split_names = [item.get("split_name") for item in world_scores]
    if any(
        not isinstance(item, str)
        or item not in {"development", "heldout", "contract_test"}
        for item in split_names
    ):
        raise ValueError("each world score must carry a registered split_name")
    if len(set(split_names)) != 1:
        raise ValueError("development, held-out, and contract worlds cannot be aggregated together")
    split_name = split_names[0]
    if split_name in {"development", "heldout"}:
        plan = get_split_plan(split_name)
        if len(world_scores) != plan.world_budget:
            raise ValueError("formal aggregation requires the complete registered split budget")
        expected_strata = {
            stratum.value: plan.worlds_per_stratum for stratum in SyntheticStratum
        }
        observed_strata: dict[str, int] = {}
        for world in world_scores:
            stratum = world.get("stratum")
            if not isinstance(stratum, str) or stratum not in expected_strata:
                raise ValueError("formal world score must carry a registered stratum")
            observed_strata[stratum] = observed_strata.get(stratum, 0) + 1
            if world.get("evaluation_cutoff") != _stamp(_EVALUATION_CUTOFF_SECONDS):
                raise ValueError("formal worlds must share the registered evaluation cutoff")
        if observed_strata != expected_strata:
            raise ValueError("formal aggregation requires the registered balanced stratum allocation")

    methods = ("TIME_ASSET_RULE", "MULTI_EVIDENCE_RULE")
    aggregated: dict[str, object] = {}
    rate_fields = (
        ("false_merge_rate", "false_merge_count", "different_pair_denominator"),
        ("false_split_rate", "false_split_count", "same_pair_denominator"),
        ("coverage", "coverage_count", "coverage_denominator"),
        (
            "candidate_generation_recall",
            "candidate_generation_recall_count",
            "candidate_generation_recall_denominator",
        ),
    )
    for method_name in methods:
        method_rows = []
        for world in world_scores:
            methods_doc = world.get("methods")
            if not isinstance(methods_doc, Mapping) or not isinstance(
                methods_doc.get(method_name), Mapping
            ):
                raise ValueError(f"world score is missing {method_name}")
            method_rows.append(methods_doc[method_name])
        method_summary: dict[str, object] = {
            "independent_world_count": len(world_scores),
        }
        for rate_name, numerator_name, denominator_name in rate_fields:
            valid = [row for row in method_rows if isinstance(row.get(rate_name), (int, float))]
            numerator = sum(int(row.get(numerator_name, 0)) for row in method_rows)
            denominator = sum(int(row.get(denominator_name, 0)) for row in method_rows)
            method_summary[rate_name] = {
                "world_macro": fmean(float(row[rate_name]) for row in valid) if valid else None,
                "worlds_evaluable": len(valid),
                "pooled_numerator": numerator,
                "pooled_denominator": denominator,
                "pooled_descriptive_rate": _safe_rate(numerator, denominator),
            }
        aggregated[method_name] = method_summary

    alert_rows = [
        item.get("alert_escalation")
        for item in world_scores
        if isinstance(item.get("alert_escalation"), Mapping)
    ]
    evaluated_alert_rows = [
        row for row in alert_rows if row.get("status") == "EVALUATED"
    ]
    if evaluated_alert_rows:
        alert_denominator = sum(int(row.get("denominator", 0)) for row in evaluated_alert_rows)
        alert_missed = sum(int(row.get("missed_count", 0)) for row in evaluated_alert_rows)
        alert_summary: dict[str, object] = {
            "status": "EVALUATED",
            "evaluable_world_count": len(evaluated_alert_rows),
            "pooled_denominator": alert_denominator,
            "pooled_missed_count": alert_missed,
            "pooled_miss_rate": _safe_rate(alert_missed, alert_denominator),
            "world_macro_miss_rate": fmean(
                float(row["miss_rate"]) for row in evaluated_alert_rows
            ),
        }
    elif alert_rows and all(row.get("status") == "NOT_APPLICABLE" for row in alert_rows):
        alert_summary = {
            "status": "NOT_APPLICABLE",
            "evaluable_world_count": 0,
            "pooled_denominator": 0,
            "pooled_missed_count": 0,
            "pooled_miss_rate": None,
            "world_macro_miss_rate": None,
        }
    else:
        alert_summary = {
            "status": "NOT_EVALUATED",
            "evaluable_world_count": 0,
            "pooled_denominator": 0,
            "pooled_missed_count": None,
            "pooled_miss_rate": None,
            "world_macro_miss_rate": None,
        }

    return {
        "aggregation_version": "observable-association-world-macro-v1",
        "independent_world_count": len(world_scores),
        "methods": aggregated,
        "alert_escalation": alert_summary,
    }


def _validate_steps(
    steps: Sequence[FrozenArmStep], scorer_only: ScorerSidecar
) -> tuple[FrozenArmStep, ...]:
    if not isinstance(steps, (tuple, list)) or any(
        not isinstance(item, FrozenArmStep) for item in steps
    ):
        raise ValueError("steps must contain FrozenArmStep values")
    if not steps:
        raise ValueError("steps must not be empty")
    step_rows = tuple(steps)
    method_names = {step.method for step in step_rows}
    expected_methods = {"TIME_ASSET_RULE", "MULTI_EVIDENCE_RULE"}
    if method_names != expected_methods:
        raise ValueError("both fixed rule arms must be present exactly")
    cutoffs_by_method = {
        method: tuple(step.cutoff for step in step_rows if step.method == method)
        for method in expected_methods
    }
    if cutoffs_by_method["TIME_ASSET_RULE"] != cutoffs_by_method["MULTI_EVIDENCE_RULE"]:
        raise ValueError("method arms must share the same cutoff sequence")
    if len(cutoffs_by_method["TIME_ASSET_RULE"]) != len(set(cutoffs_by_method["TIME_ASSET_RULE"])):
        raise ValueError("each method must have one output per cutoff")
    time_asset_cutoffs = cutoffs_by_method["TIME_ASSET_RULE"]
    if tuple(
        sorted(time_asset_cutoffs, key=lambda value: _parse_timestamp(value, "cutoff"))
    ) != time_asset_cutoffs:
        raise ValueError("method cutoffs must be chronological")
    if cutoffs_by_method["TIME_ASSET_RULE"][-1] != scorer_only.evaluation_cutoff:
        raise ValueError("last method cutoff must match scorer evaluation cutoff")

    fixed_pairs = {row.pair for row in scorer_only.pair_truths}
    for cutoff in cutoffs_by_method["TIME_ASSET_RULE"]:
        same_cutoff = [step for step in step_rows if step.cutoff == cutoff]
        if len(same_cutoff) != 2:
            raise ValueError("each cutoff must have exactly two method outputs")
        if same_cutoff[0].input_prefix_sha256 != same_cutoff[1].input_prefix_sha256:
            raise ValueError("method arms received different prefix inputs")
        if same_cutoff[0].candidate_pairs != same_cutoff[1].candidate_pairs:
            raise ValueError("method arms received different candidate pairs")
        for step in same_cutoff:
            if not set(step.candidate_pairs).issubset(fixed_pairs):
                raise ValueError("candidate input contains a pair outside the fixed scoring universe")
            _step_actions(step)
    for method in expected_methods:
        previous_candidates: set[association.CandidatePair] = set()
        for cutoff in time_asset_cutoffs:
            current = next(
                step for step in step_rows if step.method == method and step.cutoff == cutoff
            )
            current_candidates = set(current.candidate_pairs)
            if not previous_candidates.issubset(current_candidates):
                raise ValueError("shared observable candidate set must be monotonic across prefixes")
            previous_candidates = current_candidates
    if len(scorer_only.pair_truths) > _MAX_PAIR_COUNT_PER_WORLD:
        raise ValueError("scorer sidecar exceeds registered pair budget")
    return step_rows


def _step_actions(
    step: FrozenArmStep,
) -> dict[association.CandidatePair, association.ProposalAction]:
    output = step.output
    if hashlib.sha256(output.canonical_json).hexdigest() != output.sha256:
        raise ValueError("frozen method output SHA-256 mismatch")
    try:
        document = json.loads(output.canonical_json.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("frozen method output is not canonical JSON") from exc
    if not isinstance(document, dict) or set(document) != {"output_version", "proposals"}:
        raise ValueError("frozen method output schema mismatch")
    if document["output_version"] != "observable-association-v1" or not isinstance(
        document["proposals"], list
    ):
        raise ValueError("frozen method output version mismatch")
    forbidden = {
        "world_group",
        "world_group_id",
        "stratum",
        "split",
        "seed",
        "truth",
        "truth_label",
        "first_sufficient_evidence_at",
        "evaluation_cutoff",
        "alert_escalation_opportunities",
    }
    if _contains_forbidden_key(document, forbidden):
        raise ValueError("scorer-only data leaked into method output")
    actions: dict[association.CandidatePair, association.ProposalAction] = {}
    for row in document["proposals"]:
        if not isinstance(row, dict) or set(row) != {
            "method",
            "pair",
            "action",
            "reason_codes",
            "evidence_refs",
            "independent_lineage_root_count",
            "decided_at",
        }:
            raise ValueError("proposal output schema mismatch")
        if row["method"] != step.method or row["decided_at"] != step.cutoff:
            raise ValueError("proposal does not match its arm step")
        pair_doc = row["pair"]
        if not isinstance(pair_doc, dict) or set(pair_doc) != {
            "left_observation_id",
            "right_observation_id",
        }:
            raise ValueError("proposal pair schema mismatch")
        pair = association.CandidatePair(
            pair_doc["left_observation_id"], pair_doc["right_observation_id"]
        )
        try:
            action = association.ProposalAction(row["action"])
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported proposal action in frozen output") from exc
        if pair in actions:
            raise ValueError("method output contains duplicate pair proposals")
        actions[pair] = action
    if set(actions) != set(step.candidate_pairs):
        raise ValueError("method outputs must cover exactly the shared candidates")
    return actions


def _decision_timing_record(
    truth: PairTruth,
    actions: Sequence[tuple[str, association.ProposalAction]],
    *,
    evaluation_cutoff: str,
) -> dict[str, object]:
    if truth.label is PairTruthLabel.UNKNOWN:
        return {
            "pair": _pair_document(truth.pair),
            "label": truth.label.value,
            "status": "UNKNOWN_EXCLUDED",
            "event_observed": None,
            "duration_seconds": None,
            "first_candidate_at": _first_time(actions),
            "first_decision_at": _first_non_abstaining_time(actions),
            "valid_decision_at": None,
            "censor_stage": None,
        }
    cutoff = _parse_timestamp(evaluation_cutoff, "evaluation_cutoff")
    first_candidate_at = _first_time(actions)
    first_decision_at = _first_non_abstaining_time(actions)
    sufficient = (
        _parse_timestamp(truth.first_sufficient_evidence_at, "first_sufficient_evidence_at")
        if truth.first_sufficient_evidence_at is not None
        else None
    )
    if sufficient is None:
        start = (
            _parse_timestamp(first_candidate_at, "first_candidate_at")
            if first_candidate_at is not None
            else cutoff
        )
        return {
            "pair": _pair_document(truth.pair),
            "label": truth.label.value,
            "status": "RIGHT_CENSORED_BEFORE_SUFFICIENT_EVIDENCE",
            "event_observed": False,
            "duration_seconds": max(0, int((cutoff - start).total_seconds())),
            "first_candidate_at": first_candidate_at,
            "first_decision_at": first_decision_at,
            "valid_decision_at": None,
            "censor_stage": "BEFORE_SUFFICIENT_EVIDENCE",
        }

    correct_action = (
        association.ProposalAction.LINK_CANDIDATES
        if truth.label is PairTruthLabel.SAME
        else association.ProposalAction.RETAIN_SEPARATELY
    )
    valid_decisions = [
        _parse_timestamp(at, "decided_at")
        for at, action in actions
        if action is correct_action and _parse_timestamp(at, "decided_at") >= sufficient
    ]
    if valid_decisions:
        valid_at = min(valid_decisions)
        return {
            "pair": _pair_document(truth.pair),
            "label": truth.label.value,
            "status": "VALID_DECISION_OBSERVED",
            "event_observed": True,
            "duration_seconds": int((valid_at - sufficient).total_seconds()),
            "first_candidate_at": first_candidate_at,
            "first_decision_at": first_decision_at,
            "valid_decision_at": _format_timestamp(valid_at),
            "censor_stage": None,
        }
    return {
        "pair": _pair_document(truth.pair),
        "label": truth.label.value,
        "status": "RIGHT_CENSORED_AFTER_SUFFICIENT_EVIDENCE",
        "event_observed": False,
        "duration_seconds": max(0, int((cutoff - sufficient).total_seconds())),
        "first_candidate_at": first_candidate_at,
        "first_decision_at": first_decision_at,
        "valid_decision_at": None,
        "censor_stage": "AFTER_SUFFICIENT_EVIDENCE",
    }


def _timing_status_counts(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = row.get("status")
        if isinstance(status, str):
            counts[status] = counts.get(status, 0) + 1
    return counts


def _first_time(actions: Sequence[tuple[str, association.ProposalAction]]) -> str | None:
    return (
        min((at for at, _ in actions), key=lambda value: _parse_timestamp(value, "cutoff"))
        if actions
        else None
    )


def _first_non_abstaining_time(
    actions: Sequence[tuple[str, association.ProposalAction]],
) -> str | None:
    eligible = [
        at for at, action in actions if action is not association.ProposalAction.ABSTAIN
    ]
    return (
        min(eligible, key=lambda value: _parse_timestamp(value, "cutoff"))
        if eligible
        else None
    )


def _prefix_sha256(prefix: association.FrozenObservablePrefix) -> str:
    rows = []
    for observation in sorted(prefix.observations, key=lambda item: item.observation_id):
        rows.append(
            {
                "observation_id": observation.observation_id,
                "received_at": observation.received_at,
                "id_actual_available_at": observation.id_actual_available_at,
                "id_earliest_known_at": observation.id_earliest_known_at,
                "fields": [
                    {
                        "name": field.name,
                        "value": _json_value(field.value),
                        "actual_available_at": field.actual_available_at,
                        "earliest_known_at": field.earliest_known_at,
                    }
                    for field in sorted(observation.fields, key=lambda item: item.name)
                ],
            }
        )
    payload = json.dumps(
        {"as_of": prefix.as_of, "observations": rows},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _build_observation_record(spec: _RecordSpec) -> association.ObservationRecord:
    actual_at = _stamp(spec.source_seconds)
    known_at = _stamp(_record_received_seconds(spec))
    fields = (
        association.KnownField("asset_id", spec.asset_id, actual_at, known_at),
        association.KnownField("asset_binding_status", "VERIFIED", actual_at, known_at),
        association.KnownField("modality", spec.modality, actual_at, known_at),
        association.KnownField("value", spec.value, actual_at, known_at),
        association.KnownField("unit", "degC", actual_at, known_at),
        association.KnownField("value_error", 0.5, actual_at, known_at),
        association.KnownField("position_m", spec.position, actual_at, known_at),
        association.KnownField("position_error_m", 0.25, actual_at, known_at),
        association.KnownField("quality_status", "GOOD", actual_at, known_at),
        association.KnownField("calibration_status", "CURRENT", actual_at, known_at),
        association.KnownField("source_time", actual_at, actual_at, known_at),
        association.KnownField("risk_flag", "EXPOSURE", actual_at, known_at),
        association.KnownField("acquisition_lineage", (spec.root_id, "EDGE"), actual_at, known_at),
    )
    return association.ObservationRecord(
        observation_id=spec.observation_id,
        id_actual_available_at=actual_at,
        id_earliest_known_at=known_at,
        received_at=known_at,
        fields=fields,
    )


def _build_recovery_record(spec: _RecordSpec) -> association.ObservationRecord:
    actual_at = _stamp(spec.source_seconds)
    fields = (
        association.KnownField("asset_id", spec.asset_id, actual_at, actual_at),
        association.KnownField("asset_binding_status", "VERIFIED", actual_at, actual_at),
        association.KnownField("source_time", actual_at, actual_at, actual_at),
        association.KnownField("risk_flag", "RECOVERY", actual_at, actual_at),
        association.KnownField("acquisition_lineage", (spec.root_id, "EDGE"), actual_at, actual_at),
    )
    return association.ObservationRecord(
        observation_id=spec.observation_id,
        id_actual_available_at=actual_at,
        id_earliest_known_at=actual_at,
        received_at=actual_at,
        fields=fields,
    )


def _record_received_seconds(spec: _RecordSpec) -> int:
    return spec.source_seconds if spec.received_seconds is None else spec.received_seconds


def _build_risk_update_record(
    original: association.ObservationRecord, source_seconds: int
) -> association.ObservationRecord:
    actual_at = _stamp(source_seconds)
    return association.ObservationRecord(
        observation_id=original.observation_id,
        id_actual_available_at=original.id_actual_available_at,
        id_earliest_known_at=original.id_earliest_known_at,
        received_at=actual_at,
        fields=(
            association.KnownField(
                "risk_flag", "EXPOSURE_HIGH", actual_at, actual_at
            ),
        ),
    )


def _opaque_id(token: str, role: str) -> str:
    return hashlib.sha256(f"{token}|{role}".encode("utf-8")).hexdigest()[:20]


def _stamp(seconds: int) -> str:
    return _format_timestamp(_BASE_TIME + timedelta(seconds=seconds))


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(_UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty timestamp string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(_UTC)


def _json_value(value: object) -> object:
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported observable JSON value type: {type(value).__name__}")


def _contains_forbidden_key(value: object, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            str(key) in forbidden or _contains_forbidden_key(item, forbidden)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item, forbidden) for item in value)
    return False


def _pair_document(pair: association.CandidatePair) -> dict[str, str]:
    return {
        "left_observation_id": pair.left_observation_id,
        "right_observation_id": pair.right_observation_id,
    }


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


__all__ = [
    "AlertAction",
    "AlertEscalationOpportunity",
    "FrozenArmStep",
    "GeneratedWorld",
    "ObservableTrajectory",
    "PairTruth",
    "PairTruthLabel",
    "ScorerSidecar",
    "SplitPlan",
    "SyntheticStratum",
    "aggregate_world_scores",
    "generate_protocol_split",
    "generate_synthetic_world",
    "get_split_plan",
    "run_two_methods",
    "score_alert_escalation_misses",
    "score_world",
    "serialize_observable_trajectory",
]
