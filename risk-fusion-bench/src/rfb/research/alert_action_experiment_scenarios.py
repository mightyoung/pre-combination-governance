"""Build one synthetic event stream for the reminder-policy comparison."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import html
import json
from pathlib import Path
from typing import Any

from .alert_action_experiment import (
    ActionIntent,
    ActionKind,
    ApplyStatus,
    PolicyMode,
    ReminderActionLedger,
)
from .alert_governance import (
    AlertLedger,
    CandidateEvent,
    DeliveryStatus,
    RelationDecision,
)


_UTC = timezone.utc
_BASE = datetime(2026, 10, 11, 8, 0, 0, tzinfo=_UTC)
_BATCH_ID = "SYNTH-BATCH-1"
_ROOT = Path(__file__).resolve().parents[4]


def _stamp(seconds: float) -> str:
    return (_BASE + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _candidate(
    candidate_id: str,
    *,
    source_id: str,
    event_seconds: float,
    observed_seconds: float,
) -> CandidateEvent:
    candidate = CandidateEvent(
        candidate_id=candidate_id,
        event_time=_stamp(event_seconds),
        observed_at=_stamp(observed_seconds),
        summary=f"合成观测 {candidate_id}",
        source_id=source_id,
        evidence_refs=(f"synthetic://observation/{candidate_id}",),
        risk_flag="EXPOSURE",
    )
    return candidate


def _to_intent(
    alert: Any,
    *,
    kind: ActionKind,
    association_id: str | None,
    association_candidate_ids: tuple[str, ...] | None,
    candidates: dict[str, CandidateEvent],
) -> ActionIntent:
    candidate_ids = association_candidate_ids or alert.candidate_ids
    association_ids = (association_id,) if association_id else ()
    association_state = {
        ActionKind.ASSOCIATION_CONFIRMED: "SAME_CONFIRMED",
        ActionKind.COUNTER_EVIDENCE: "DIFFERENT_CONFIRMED",
        ActionKind.EVENT_SPLIT: "DIFFERENT_CONFIRMED",
    }.get(kind, "UNKNOWN_PENDING")
    return ActionIntent(
        intent_id=f"intent-{alert.alert_id}-{kind.value}",
        display_card_id=alert.card_id,
        kind=kind,
        risk_stage=alert.alert_level,
        received_at=alert.alerted_at,
        observation_ids=candidate_ids,
        source_ids=tuple(sorted({candidates[item].source_id for item in candidate_ids})),
        candidate_episode_ids=candidate_ids,
        association_ids=association_ids,
        evidence_refs=alert.evidence_refs,
        source_times=tuple(candidates[item].event_time for item in candidate_ids),
        observed_at_times=tuple(candidates[item].observed_at for item in candidate_ids),
        experiment_batch_id=_BATCH_ID,
        association_state=association_state,
        dedup_episode_interval_key=f"SYNTH-INTERVAL-{alert.card_id}-{association_state}",
        trigger_known_time=alert.alerted_at,
        detected_at=alert.alerted_at,
    )


def _add_candidate(
    ledger: AlertLedger,
    candidates: dict[str, CandidateEvent],
    candidate_id: str,
    *,
    source_id: str | None = None,
    event_seconds: float,
    observed_seconds: float,
    alerted_seconds: float,
) -> str:
    candidate = _candidate(
        candidate_id,
        source_id=source_id or f"device-{candidate_id}",
        event_seconds=event_seconds,
        observed_seconds=observed_seconds,
    )
    candidates[candidate_id] = candidate
    card = ledger.add_candidate(candidate, alerted_at=_stamp(alerted_seconds))
    return card.card_id


def _alert_intents(
    alerts: tuple[Any, ...],
    *,
    kind: ActionKind,
    association_id: str | None,
    association_candidate_ids: tuple[str, ...] | None = None,
    candidates: dict[str, CandidateEvent],
) -> list[ActionIntent]:
    return [
        _to_intent(
            alert,
            kind=kind,
            association_id=association_id,
            association_candidate_ids=association_candidate_ids,
            candidates=candidates,
        )
        for alert in alerts
    ]


def _synthetic_pending_intent(
    *,
    intent_id: str,
    display_card_id: str,
    received_seconds: float,
    observation_ids: tuple[str, ...],
    source_ids: tuple[str, ...],
    candidate_episode_ids: tuple[str, ...],
    association_id: str,
    evidence_ref: str,
    source_seconds: float,
    observed_seconds: float,
    trigger_known_seconds: float,
    detected_seconds: float,
    dedup_episode_interval_key: str,
    risk_stage: str = "PRECAUTIONARY",
    association_state: str = "UNKNOWN_PENDING",
) -> ActionIntent:
    """Create an explicit boundary probe without inventing an AlertLedger edge."""
    return ActionIntent(
        intent_id=intent_id,
        display_card_id=display_card_id,
        kind=ActionKind.ASSOCIATION_PENDING,
        risk_stage=risk_stage,
        received_at=_stamp(received_seconds),
        observation_ids=observation_ids,
        source_ids=source_ids,
        candidate_episode_ids=candidate_episode_ids,
        association_ids=(association_id,),
        evidence_refs=(evidence_ref,),
        source_times=(_stamp(source_seconds),),
        observed_at_times=(_stamp(observed_seconds),),
        experiment_batch_id=_BATCH_ID,
        association_state=association_state,
        dedup_episode_interval_key=dedup_episode_interval_key,
        trigger_known_time=_stamp(trigger_known_seconds),
        detected_at=_stamp(detected_seconds),
    )


def _add_pending_pair(
    ledger: AlertLedger,
    candidates: dict[str, CandidateEvent],
    intents: list[ActionIntent],
    *,
    left: str,
    right: str,
    received_seconds: float,
) -> str:
    before = len(ledger.alerts)
    association = ledger.propose_association(
        left,
        right,
        at=_stamp(received_seconds),
        rationale=f"合成待核关系 {left}-{right}。",
        evidence_refs=(f"synthetic://association/{left}-{right}",),
    )
    intents.extend(
        _alert_intents(
            ledger.alerts[before:],
            kind=ActionKind.ASSOCIATION_PENDING,
            association_id=association.association_id,
            association_candidate_ids=association.candidate_ids,
            candidates=candidates,
        )
    )
    return association.association_id


def _serialize_intent(intent: ActionIntent) -> dict[str, Any]:
    return {
        "intent_id": intent.intent_id,
        "display_card_id": intent.display_card_id,
        "kind": intent.kind.value,
        "risk_stage": intent.risk_stage,
        "received_at": intent.received_at,
        "observation_ids": list(intent.observation_ids),
        "source_ids": list(intent.source_ids),
        "candidate_episode_ids": list(intent.candidate_episode_ids),
        "association_ids": list(intent.association_ids),
        "evidence_refs": list(intent.evidence_refs),
        "source_times": list(intent.source_times),
        "observed_at_times": list(intent.observed_at_times),
        "experiment_batch_id": intent.experiment_batch_id,
        "association_state": intent.association_state,
        "dedup_episode_interval_key": intent.dedup_episode_interval_key,
        "trigger_known_time": intent.trigger_known_time,
        "detected_at": intent.detected_at,
    }


def _serialize_revision(revision: Any) -> dict[str, Any]:
    return {
        "revision": revision.revision,
        "intent_id": revision.intent_id,
        "display_card_id": revision.display_card_id,
        "kind": revision.kind.value,
        "risk_stage": revision.risk_stage,
        "received_at": revision.received_at,
        "observation_ids": list(revision.observation_ids),
        "source_ids": list(revision.source_ids),
        "candidate_episode_ids": list(revision.candidate_episode_ids),
        "association_ids": list(revision.association_ids),
        "evidence_refs": list(revision.evidence_refs),
        "source_times": list(revision.source_times),
        "observed_at_times": list(revision.observed_at_times),
        "experiment_batch_id": revision.experiment_batch_id,
        "association_state": revision.association_state,
        "dedup_episode_interval_key": revision.dedup_episode_interval_key,
        "trigger_known_time": revision.trigger_known_time,
        "detected_at": revision.detected_at,
        "simulated_card_update_delay_seconds": revision.simulated_card_update_delay_seconds,
    }


def _run_policy(
    intents: tuple[ActionIntent, ...], *, mode: PolicyMode, window_seconds: float
) -> dict[str, Any]:
    ledger = ReminderActionLedger(mode=mode, merge_window_seconds=window_seconds)
    decisions = [ledger.apply(intent) for intent in intents]

    def revision_count() -> int:
        return sum(
            len(ledger.card_revisions_for(card_id))
            for card_id in {intent.display_card_id for intent in intents}
        )

    exact_replay = replace(intents[0], received_at=_stamp(40))
    revisions_before_exact = revision_count()
    exact_replay_decision = ledger.apply(exact_replay)
    revisions_after_exact = revision_count()
    stale_replay = replace(
        intents[0],
        received_at=_stamp(41),
        observed_at_times=tuple(_stamp(41) for _ in intents[0].observed_at_times),
    )
    stale_replay_status = "NOT_RUN"
    stale_replay_error = ""
    revisions_before_stale = revision_count()
    try:
        ledger.apply(stale_replay)
    except ValueError as exc:
        stale_replay_status = "REJECTED_CONTENT_CONFLICT"
        stale_replay_error = str(exc)
    else:
        stale_replay_status = "ACCEPTED_UNEXPECTEDLY"
    revisions_after_stale = revision_count()

    notifications = [
        {
            "experiment_notification_id": item.experiment_notification_id,
            "display_card_id": item.display_card_id,
            "kind": item.kind.value,
            "risk_stage": item.risk_stage,
            "experiment_batch_id": item.experiment_batch_id,
            "association_state": item.association_state,
            "dedup_episode_interval_key": item.dedup_episode_interval_key,
            "first_received_at": item.first_received_at,
            "latest_received_at": item.latest_received_at,
            "content_revision_count": item.content_revision_count,
            "intent_ids": [update.intent_id for update in item.updates],
            "actual_visible_at": None,
            "delivery_status": "NOT_DELIVERED",
        }
        for item in ledger.notifications
    ]
    revisions = [
        _serialize_revision(revision)
        for card_id in sorted({intent.display_card_id for intent in intents})
        for revision in ledger.card_revisions_for(card_id)
    ]
    decision_rows = [
        {
            "intent_id": decision.intent_id,
            "status": decision.status.value,
            "experiment_notification_id": decision.experiment_notification_id,
            "card_revision": decision.card_revision,
            "simulated_card_update_delay_seconds": decision.simulated_card_update_delay_seconds,
            "actual_visible_at": decision.actual_visible_at,
            "decision_reason": decision.decision_reason,
            "coalescing_elapsed_seconds": decision.coalescing_elapsed_seconds,
            "coalescing_window_seconds": decision.coalescing_window_seconds,
        }
        for decision in decisions
    ]
    decision_rows.append(
        {
            "intent_id": exact_replay.intent_id,
            "status": exact_replay_decision.status.value,
            "experiment_notification_id": exact_replay_decision.experiment_notification_id,
            "card_revision": exact_replay_decision.card_revision,
            "simulated_card_update_delay_seconds": exact_replay_decision.simulated_card_update_delay_seconds,
            "actual_visible_at": exact_replay_decision.actual_visible_at,
            "decision_reason": exact_replay_decision.decision_reason,
            "coalescing_elapsed_seconds": exact_replay_decision.coalescing_elapsed_seconds,
            "coalescing_window_seconds": exact_replay_decision.coalescing_window_seconds,
        }
    )
    evidence_refs = sorted({ref for row in revisions for ref in row["evidence_refs"]})
    association_ids = sorted(
        {value for row in revisions for value in row["association_ids"]}
    )
    observation_ids = sorted(
        {value for row in revisions for value in row["observation_ids"]}
    )
    source_ids = sorted({value for row in revisions for value in row["source_ids"]})
    episode_ids = sorted(
        {value for row in revisions for value in row["candidate_episode_ids"]}
    )
    missing_intents = sorted(
        {intent.intent_id for intent in intents}
        - {row["intent_id"] for row in revisions}
    )
    return {
        "policy": mode.value,
        "window_seconds": window_seconds,
        "notification_action_count": ledger.notification_action_count,
        "coalesced_update_count": ledger.coalesced_update_count,
        "duplicate_replay_count": ledger.duplicate_replay_count,
        "semantic_card_revision_count": len(revisions),
        "missed_important_update_ids": list(ledger.missed_important_update_ids()),
        "unrepresented_semantic_update_ids": missing_intents,
        "evidence_refs_retained": evidence_refs,
        "association_ids_retained": association_ids,
        "observation_ids_retained": observation_ids,
        "source_ids_retained": source_ids,
        "candidate_episode_ids_retained": episode_ids,
        "card_revisions": revisions,
        "notifications": notifications,
        "decisions": decision_rows,
        "simulated_card_update_delay_seconds": {
            "min": 0.0,
            "max": 0.0,
            "basis": "In-memory revision is appended synchronously at synthetic received_at.",
        },
        "simulated_coalesced_update_ages_seconds": [
            decision["coalescing_elapsed_seconds"]
            for decision in decision_rows
            if decision["status"] == ApplyStatus.COALESCED.value
        ],
        "actual_visible_at": None,
        "exact_replay": {
            "status": exact_replay_decision.status.value,
            "received_at_on_original_revision": intents[0].received_at,
            "replay_received_at": exact_replay.received_at,
            "revision_count_before": revisions_before_exact,
            "revision_count_after": revisions_after_exact,
        },
        "stale_replay": {
            "status": stale_replay_status,
            "error": stale_replay_error,
            "revision_count_before": revisions_before_stale,
            "revision_count_after": revisions_after_stale,
        },
    }


def build_comparison() -> dict[str, Any]:
    """Return the same synthetic action stream evaluated by both policies."""
    source = AlertLedger(delivery_status=DeliveryStatus.NOT_DELIVERED)
    candidates: dict[str, CandidateEvent] = {}
    cards: dict[str, str] = {}
    intents: list[ActionIntent] = []

    for candidate_id, source_id in (
        ("candidate-A", "device-A"),
        ("candidate-B", "device-B"),
        ("candidate-C", "device-C"),
    ):
        cards[candidate_id] = _add_candidate(
            source,
            candidates,
            candidate_id,
            source_id=source_id,
            event_seconds=0,
            observed_seconds=2,
            alerted_seconds=3,
        )

    association_ab = _add_pending_pair(
        source,
        candidates,
        intents,
        left="candidate-A",
        right="candidate-B",
        received_seconds=10,
    )
    association_ac = _add_pending_pair(
        source,
        candidates,
        intents,
        left="candidate-A",
        right="candidate-C",
        received_seconds=10,
    )

    before = len(source.alerts)
    source.escalate_card(
        cards["candidate-A"],
        at=_stamp(11),
        rationale="合成风险证据达到既有 ESCALATED 阶段。",
        evidence_refs=("synthetic://risk/escalation-A",),
    )
    escalation_alert = source.alerts[before:]
    intents.extend(
        _alert_intents(
            escalation_alert,
            kind=ActionKind.RISK_ESCALATION,
            association_id=None,
            candidates=candidates,
        )
    )

    distinct_alert_record = _add_candidate(
        source,
        candidates,
        "candidate-Z-distinct-event",
        source_id="device-Z",
        event_seconds=-60,
        observed_seconds=11,
        alerted_seconds=11,
    )
    distinct_alert = source.alerts[-1]
    intents.extend(
        _alert_intents(
            (distinct_alert,),
            kind=ActionKind.DISTINCT_EVENT_ALERT,
            association_id=None,
            candidates=candidates,
        )
    )
    cards["candidate-Z-distinct-event"] = distinct_alert_record

    before = len(source.alerts)
    source.resolve_association(
        association_ab,
        decision=RelationDecision.SAME_EVENT,
        at=_stamp(12),
        evidence_refs=("synthetic://confirmation/A-B",),
    )
    intents.extend(
        _alert_intents(
            source.alerts[before:],
            kind=ActionKind.ASSOCIATION_CONFIRMED,
            association_id=association_ab,
            association_candidate_ids=source.association(association_ab).candidate_ids,
            candidates=candidates,
        )
    )

    before = len(source.alerts)
    source.resolve_association(
        association_ac,
        decision=RelationDecision.DISTINCT_EVENTS,
        at=_stamp(13),
        evidence_refs=("synthetic://counterevidence/A-C-distinct",),
    )
    intents.extend(
        _alert_intents(
            source.alerts[before:],
            kind=ActionKind.COUNTER_EVIDENCE,
            association_id=association_ac,
            association_candidate_ids=source.association(association_ac).candidate_ids,
            candidates=candidates,
        )
    )

    before = len(source.alerts)
    source.split_association(
        association_ab,
        at=_stamp(14),
        rationale="合成后续证据要求拆分先前 SAME_EVENT 关系。",
        evidence_refs=("synthetic://split/A-B",),
    )
    intents.extend(
        _alert_intents(
            source.alerts[before:],
            kind=ActionKind.EVENT_SPLIT,
            association_id=association_ab,
            association_candidate_ids=source.association(association_ab).candidate_ids,
            candidates=candidates,
        )
    )

    candidate_d = "candidate-D"
    cards[candidate_d] = _add_candidate(
        source,
        candidates,
        candidate_d,
        source_id="device-D",
        event_seconds=14,
        observed_seconds=14,
        alerted_seconds=14,
    )
    association_ad = _add_pending_pair(
        source,
        candidates,
        intents,
        left="candidate-A",
        right=candidate_d,
        received_seconds=15,
    )

    candidate_e = "candidate-E"
    cards[candidate_e] = _add_candidate(
        source,
        candidates,
        candidate_e,
        source_id="device-E",
        event_seconds=18,
        observed_seconds=18,
        alerted_seconds=18,
    )
    candidate_f = "candidate-F"
    cards[candidate_f] = _add_candidate(
        source,
        candidates,
        candidate_f,
        source_id="device-F",
        event_seconds=12,
        observed_seconds=19,
        alerted_seconds=19,
    )
    association_ae = _add_pending_pair(
        source,
        candidates,
        intents,
        left="candidate-A",
        right=candidate_e,
        received_seconds=20,
    )
    association_af = _add_pending_pair(
        source,
        candidates,
        intents,
        left="candidate-A",
        right=candidate_f,
        received_seconds=21,
    )

    pending_a_card = cards["candidate-A"]
    a_pending_ab = next(
        intent
        for intent in intents
        if intent.display_card_id == pending_a_card
        and association_ab in intent.association_ids
        and intent.kind is ActionKind.ASSOCIATION_PENDING
    )
    cross_episode_duplicate = _synthetic_pending_intent(
        intent_id="intent-cross-episode-same-card",
        display_card_id=pending_a_card,
        received_seconds=10.5,
        observation_ids=("observation-G", "observation-H"),
        source_ids=("device-G", "device-H"),
        candidate_episode_ids=("episode-G", "episode-H"),
        association_id="ASSOC-CROSS-EPISODE-G-H",
        evidence_ref="synthetic://association/cross-episode-G-H",
        source_seconds=2,
        observed_seconds=9,
        trigger_known_seconds=10,
        detected_seconds=10.25,
        dedup_episode_interval_key=a_pending_ab.dedup_episode_interval_key,
        risk_stage=a_pending_ab.risk_stage,
    )
    cross_card_duplicate = _synthetic_pending_intent(
        intent_id="intent-cross-card-same-episode",
        display_card_id="CARD-CROSS-CARD",
        received_seconds=10.5,
        observation_ids=a_pending_ab.observation_ids,
        source_ids=a_pending_ab.source_ids,
        candidate_episode_ids=a_pending_ab.candidate_episode_ids,
        association_id=association_ab,
        evidence_ref=a_pending_ab.evidence_refs[0],
        source_seconds=0,
        observed_seconds=2,
        trigger_known_seconds=10,
        detected_seconds=10.25,
        dedup_episode_interval_key=a_pending_ab.dedup_episode_interval_key,
        risk_stage=a_pending_ab.risk_stage,
    )
    conflict_pending_update = _synthetic_pending_intent(
        intent_id="intent-conflict-pending-same-card",
        display_card_id=pending_a_card,
        received_seconds=10.5,
        observation_ids=a_pending_ab.observation_ids,
        source_ids=a_pending_ab.source_ids,
        candidate_episode_ids=a_pending_ab.candidate_episode_ids,
        association_id="ASSOC-CONFLICT-AB",
        evidence_ref="synthetic://association/conflict-A-B",
        source_seconds=0,
        observed_seconds=9,
        trigger_known_seconds=10,
        detected_seconds=10.25,
        dedup_episode_interval_key=a_pending_ab.dedup_episode_interval_key,
        risk_stage=a_pending_ab.risk_stage,
        association_state="CONFLICT_PENDING",
    )
    late_old_observation = _synthetic_pending_intent(
        intent_id="intent-late-old-observation",
        display_card_id=pending_a_card,
        received_seconds=24,
        observation_ids=("observation-late-old",),
        source_ids=("device-late-old",),
        candidate_episode_ids=("episode-late-old",),
        association_id="ASSOC-LATE-OLD",
        evidence_ref="synthetic://observation/late-old-source",
        source_seconds=1,
        observed_seconds=18,
        trigger_known_seconds=20,
        detected_seconds=22,
        dedup_episode_interval_key="SYNTHETIC-INTERVAL-LATE-OLD",
        risk_stage="ESCALATED",
    )
    intents.extend(
        (
            cross_episode_duplicate,
            cross_card_duplicate,
            conflict_pending_update,
            late_old_observation,
        )
    )

    intents_tuple = tuple(intents)
    sorted_intents = tuple(
        sorted(
            intents_tuple,
            key=lambda intent: datetime.fromisoformat(
                intent.received_at.replace("Z", "+00:00")
            ),
        )
    )
    exact_replay = replace(sorted_intents[0], received_at=_stamp(40))
    stale_replay = replace(
        sorted_intents[0],
        received_at=_stamp(41),
        observed_at_times=tuple(
            _stamp(41) for _ in sorted_intents[0].observed_at_times
        ),
    )

    window_results = []
    for window_seconds in (0, 5):
        window_results.append(
            {
                "window_seconds": window_seconds,
                "per_association": _run_policy(
                    sorted_intents,
                    mode=PolicyMode.PER_ASSOCIATION,
                    window_seconds=window_seconds,
                ),
                "card_coalesce": _run_policy(
                    sorted_intents,
                    mode=PolicyMode.CARD_COALESCE,
                    window_seconds=window_seconds,
                ),
            }
        )

    a_pending_ae = next(
        intent
        for intent in sorted_intents
        if intent.display_card_id == pending_a_card
        and association_ae in intent.association_ids
        and intent.kind is ActionKind.ASSOCIATION_PENDING
    )
    a_pending_af = next(
        intent
        for intent in sorted_intents
        if intent.display_card_id == pending_a_card
        and association_af in intent.association_ids
        and intent.kind is ActionKind.ASSOCIATION_PENDING
    )
    a_pending_ac = next(
        intent
        for intent in sorted_intents
        if intent.display_card_id == pending_a_card
        and association_ac in intent.association_ids
        and intent.kind is ActionKind.ASSOCIATION_PENDING
    )
    a_escalation = next(
        intent
        for intent in sorted_intents
        if intent.display_card_id == pending_a_card
        and intent.kind is ActionKind.RISK_ESCALATION
    )
    a_counterevidence = next(
        intent
        for intent in sorted_intents
        if intent.display_card_id == pending_a_card
        and intent.kind is ActionKind.COUNTER_EVIDENCE
        and association_ac in intent.association_ids
    )
    a_split = next(
        intent
        for intent in sorted_intents
        if intent.display_card_id == pending_a_card
        and intent.kind is ActionKind.EVENT_SPLIT
        and association_ab in intent.association_ids
    )
    candidate_decisions = {
        row["intent_id"]: row
        for row in window_results[1]["card_coalesce"]["decisions"]
    }

    baseline_path = _ROOT / "research-three/alert-governance-v1/historical-baseline.json"
    history = json.loads(baseline_path.read_text(encoding="utf-8"))
    action_count = len(sorted_intents)
    all_revisions = window_results[-1]["card_coalesce"]["semantic_card_revision_count"]

    return {
        "scenario_id": "SYNTH-REMINDER-ACTION-COALESCING-001",
        "classification": "SYNTHETIC_POLICY_COMPARISON_ONLY",
        "experiment_parameters": {
            "window_values_seconds": [0, 5],
            "window_semantics": "Inclusive elapsed seconds from the first reminder action in the current notification group.",
            "coalescing_key": [
                "display_card_id",
                "action_kind",
                "existing_risk_stage",
                "association_state",
                "experiment_batch_id",
                "dedup_episode_interval_key",
                "overlap_with_first_update_candidate_episode_ids",
            ],
            "window_clock": "Synthetic processing/received_at; source_time and observed_at remain separate.",
            "batch_id": _BATCH_ID,
            "policy_approval_status": "EXPERIMENT_ONLY_NOT_FROZEN",
            "one_alert_per_association_policy": "One notification action for each association update on each affected display card.",
            "card_coalescing_policy": "Append each semantic update to the stable card revision immediately; coalesce only repeated ASSOCIATION_PENDING reminders with the same association state, explicit experiment interval key, and at least one shared candidate episode in the inclusive window.",
        },
        "input": {
            "producer": "19 action intents from in-memory AlertLedger synthetic transitions plus 4 explicit hand-constructed boundary probes.",
            "unique_action_count": action_count,
            "input_records_are_independent_samples": False,
            "input_interpretation": "Sequential synthetic action intents; action count is not a statistical sample size.",
            "synthetic_boundary_probe_intent_ids": [
                cross_episode_duplicate.intent_id,
                cross_card_duplicate.intent_id,
                conflict_pending_update.intent_id,
                late_old_observation.intent_id,
            ],
            "action_intents": [_serialize_intent(intent) for intent in sorted_intents],
            "source_candidate_ids": sorted(candidates),
            "stable_card_ids_by_candidate": dict(sorted(cards.items())),
            "exact_replay_attempt": _serialize_intent(exact_replay),
            "stale_replay_attempt": _serialize_intent(stale_replay),
        },
        "forced_cases": {
            "exact_replay": {
                "intent_id": exact_replay.intent_id,
                "status": window_results[1]["card_coalesce"]["exact_replay"]["status"],
                "replayed_received_at": exact_replay.received_at,
                "semantic_content_unchanged": True,
            },
            "stale_replay": {
                "intent_id": stale_replay.intent_id,
                "status": window_results[1]["card_coalesce"]["stale_replay"]["status"],
                "error": window_results[1]["card_coalesce"]["stale_replay"]["error"],
                "changed_field": "observed_at_times",
            },
            "complementary_sources": {
                "overlapping_associations": [association_ab, association_ac],
                "source_ids": sorted(
                    {
                        source
                        for intent in sorted_intents
                        if any(a in intent.association_ids for a in (association_ab, association_ac))
                        for source in intent.source_ids
                    }
                ),
                "evidence_refs": sorted(
                    {
                        ref
                        for intent in sorted_intents
                        if any(a in intent.association_ids for a in (association_ab, association_ac))
                        for ref in intent.evidence_refs
                    }
                ),
                "trust_or_independence_assessed": False,
            },
            "risk_escalation": {
                "action_kind": ActionKind.RISK_ESCALATION.value,
                "intent_ids": [
                    intent.intent_id
                    for intent in sorted_intents
                    if intent.kind is ActionKind.RISK_ESCALATION
                ],
                "risk_stage": "ESCALATED",
            },
            "risk_escalation_inside_window": {
                "intent_id": a_escalation.intent_id,
                "preceding_pending_intent_id": a_pending_ab.intent_id,
                "elapsed_processing_seconds": 1,
                "tested_windows_seconds": [0, 5],
                "candidate_status_at_5s": candidate_decisions[a_escalation.intent_id]["status"],
                "candidate_reason_at_5s": candidate_decisions[a_escalation.intent_id]["decision_reason"],
                "independent_action_required_by_candidate": True,
            },
            "conflict_pending_update": {
                "intent_id": conflict_pending_update.intent_id,
                "preceding_pending_intent_id": a_pending_ab.intent_id,
                "same_display_card": True,
                "same_candidate_episode_ids": True,
                "same_dedup_episode_interval_key": True,
                "association_state_change": "UNKNOWN_PENDING -> CONFLICT_PENDING",
                "candidate_status_at_5s": candidate_decisions[conflict_pending_update.intent_id]["status"],
                "candidate_reason_at_5s": candidate_decisions[conflict_pending_update.intent_id]["decision_reason"],
                "separate_conflict_update_required_by_candidate": True,
            },
            "counterevidence": {
                "action_kind": ActionKind.COUNTER_EVIDENCE.value,
                "association_id": association_ac,
                "decision": "DISTINCT_EVENTS",
            },
            "association_split": {
                "action_kind": ActionKind.EVENT_SPLIT.value,
                "association_id": association_ab,
                "transition": "CONFIRMED_SAME_EVENT -> SPLIT_TO_DISTINCT",
            },
            "pending_merge_then_counter_and_split": {
                "pending_intent_ids": [a_pending_ab.intent_id, a_pending_ac.intent_id],
                "pending_notification_ids_at_5s": [
                    candidate_decisions[a_pending_ab.intent_id]["experiment_notification_id"],
                    candidate_decisions[a_pending_ac.intent_id]["experiment_notification_id"],
                ],
                "counterevidence_intent_id": a_counterevidence.intent_id,
                "counterevidence_status": candidate_decisions[a_counterevidence.intent_id]["status"],
                "split_intent_id": a_split.intent_id,
                "split_status": candidate_decisions[a_split.intent_id]["status"],
                "all_semantic_revisions_retained": True,
            },
            "distinct_event": {
                "action_kind": ActionKind.DISTINCT_EVENT_ALERT.value,
                "candidate_id": "candidate-Z-distinct-event",
                "separate_display_card_id": cards["candidate-Z-distinct-event"],
                "truth_status": "SYNTHETIC_INPUT_LABEL_ONLY",
            },
            "cross_window": {
                "first_action_received_at": _stamp(15),
                "inclusive_boundary_received_at": _stamp(20),
                "outside_window_received_at": _stamp(21),
                "boundary_seconds": 5,
                "outside_elapsed_seconds_from_first": 6,
                "risk_stage": "ESCALATED",
                "same_display_card_kind_and_batch": True,
                "window_anchor": "first action; later in-place updates do not extend the window",
            },
            "cross_card_duplicate": {
                "intent_ids": [a_pending_ab.intent_id, cross_card_duplicate.intent_id],
                "display_card_ids": [a_pending_ab.display_card_id, cross_card_duplicate.display_card_id],
                "same_candidate_episode_ids": True,
                "same_dedup_episode_interval_key": True,
                "candidate_notification_ids": [
                    candidate_decisions[a_pending_ab.intent_id]["experiment_notification_id"],
                    candidate_decisions[cross_card_duplicate.intent_id]["experiment_notification_id"],
                ],
            },
            "cross_episode_duplicate": {
                "intent_id": cross_episode_duplicate.intent_id,
                "display_card_id": cross_episode_duplicate.display_card_id,
                "same_dedup_episode_interval_key_as_A_pending": True,
                "candidate_episode_ids": list(cross_episode_duplicate.candidate_episode_ids),
                "candidate_status_at_5s": candidate_decisions[cross_episode_duplicate.intent_id]["status"],
                "candidate_reason_at_5s": candidate_decisions[cross_episode_duplicate.intent_id]["decision_reason"],
                "separate_action_expected": True,
            },
            "out_of_order_source_time": {
                "processing_order_intent_ids": [
                    a_pending_ae.intent_id,
                    a_pending_af.intent_id,
                ],
                "processing_order_source_times": [
                    a_pending_ae.source_times[-1],
                    a_pending_af.source_times[-1],
                ],
                "source_time_moves_backward": True,
            },
            "late_old_observation": {
                "intent_id": late_old_observation.intent_id,
                "source_time": late_old_observation.source_times[0],
                "observed_at": late_old_observation.observed_at_times[0],
                "trigger_known_time": late_old_observation.trigger_known_time,
                "detected_at": late_old_observation.detected_at,
                "processing_received_at": late_old_observation.received_at,
                "card_revision_observed_at": late_old_observation.observed_at_times[0],
                "source_is_older_than_observation": True,
                "processing_time_used_as_observed_at": False,
                "candidate_status_at_5s": candidate_decisions[late_old_observation.intent_id]["status"],
            },
            "same_card_association_ids": {
                "candidate-A": sorted(
                    {
                        association_ab,
                        association_ac,
                        association_ad,
                        association_ae,
                        association_af,
                    }
                ),
            },
        },
        "window_results": window_results,
        "v2_contract_audit": {
            "source_spec_commit": "cc6d59b88bda73381fc09d9091a224ab4155891e",
            "status": "PARTIAL_SYNTHETIC_FIELD_TRACE_NOT_BUSINESS_PASS",
            "stable_display_card_id": "PRESENT_SYNTHETIC_CONTINUITY_ID",
            "same_card_is_event_equivalence": False,
            "candidate_episode_ids": "PRESENT_AS_SEPARATE_NODES; NEVER_UNIONED_BY_CARD_COALESCING",
            "association_state": "PRESENT_USING_PUBLIC_ENUM_VALUES",
            "dedup_episode_interval_key": "EXPERIMENT_INPUT_NOT_FROZEN",
            "notification_id": "EXPERIMENT_LOCAL_ID_ONLY",
            "kind": "PRESENT_AS_EXPERIMENT_ACTION_KIND",
            "severity": "NOT_MAPPED_FROM_RISK_STAGE",
            "risk_state": "NOT_FULLY_MAPPED",
            "risk_basis_ids": "SYNTHETIC_EVIDENCE_REFS_ONLY",
            "uncertainty_reason": "NOT_GENERATED_AS_USER_FACING_FIELD",
            "affected_observation_ids": "PRESENT_SYNTHETIC_IDS",
            "user_visible_message": "NOT_GENERATED",
            "suggested_verification_action": "NOT_GENERATED",
            "trigger_known_time": "SYNTHETIC_INPUT_PRESENT; NOT_EXTERNAL_RECEIPT",
            "detected_at": "SYNTHETIC_INPUT_PRESENT; NOT_RUNTIME_TRACE",
            "emitted_at": "NOT_ACTUALLY_EMITTED",
            "visible_at": "UNKNOWN_NOT_RUN",
            "content_revision": "PRESENT_AS_IN_MEMORY_CARD_REVISION",
        },
        "evaluation": {
            "reminder_action_timeliness": {
                "status": "SOFTWARE_SIMULATION_ONLY",
                "card_revision_delay_seconds": 0,
                "late_old_observation_processing_lag_seconds": 4,
                "actual_visible_or_delivery_time": "UNKNOWN_NOT_RUN",
                "deadline_threshold": "NOT_SET",
            },
            "content_completeness": {
                "status": "CHECKED_AGAINST_SYNTHETIC_INPUT",
                "all_unique_semantic_updates_have_card_revision": all_revisions == action_count,
                "evidence_refs_retained_count": len(
                    window_results[-1]["card_coalesce"]["evidence_refs_retained"]
                ),
                "association_ids_retained_count": len(
                    window_results[-1]["card_coalesce"]["association_ids_retained"]
                ),
                "candidate_episode_ids_retained_count": len(
                    window_results[-1]["card_coalesce"]["candidate_episode_ids_retained"]
                ),
                "model_calls_saved": "NOT_MEASURED",
            },
            "event_confirmation_accuracy": {
                "status": "NOT_EVALUATED",
                "basis": "Synthetic transition labels do not establish real-world event identity accuracy.",
            },
            "multi_flag_severity_priority": "UNDECIDED",
        },
        "execution_boundary": {
            "model_service_called": False,
            "network_service_called": False,
            "delivery_adapter_called": False,
            "delivery_status": "NOT_DELIVERED",
            "actual_delivery_or_visibility": "UNKNOWN_NOT_RUN",
            "independent_source_qualification": "NOT_EVALUATED",
            "multi_flag_priority_chosen": False,
            "old_1464_trial_rerun": False,
        },
        "historical_baseline": {
            "checks_executed": history["checks_executed"],
            "round_status": history["round_status"],
            "method_records": history["method_records"],
            "method_records_are_independent_samples": history[
                "method_records_are_independent_samples"
            ],
            "failure_summary": history["failure_summary"],
            "legacy_metric_status": history["legacy_metric"]["status"],
            "rerun_this_time": False,
        },
    }


def render_html(result: dict[str, Any]) -> str:
    """Render the comparison as a readable, offline HTML report."""
    def esc(value: Any) -> str:
        if isinstance(value, (list, tuple, set)):
            value = ", ".join(str(item) for item in value)
        return html.escape(str(value))

    summary_rows = []
    for window in result["window_results"]:
        base = window["per_association"]
        candidate = window["card_coalesce"]
        summary_rows.append(
            "<tr>"
            f"<th>{esc(window['window_seconds'])} s</th>"
            f"<td>{esc(base['notification_action_count'])}</td>"
            f"<td>{esc(candidate['notification_action_count'])}</td>"
            f"<td>{esc(base['semantic_card_revision_count'])} / {esc(candidate['semantic_card_revision_count'])}</td>"
            f"<td>{esc(candidate['coalesced_update_count'])}</td>"
            f"<td>{esc(len(candidate['missed_important_update_ids']))}</td>"
            "</tr>"
        )

    revision_by_intent = {
        row["intent_id"]: row["revision"]
        for row in result["window_results"][-1]["card_coalesce"]["card_revisions"]
    }
    action_rows = []
    for intent in result["input"]["action_intents"]:
        action_rows.append(
            "<tr>"
            f"<td>{esc(intent['received_at'])}</td>"
            f"<td><code>{esc(intent['display_card_id'])}</code><br><small>修订 {esc(revision_by_intent[intent['intent_id']])}</small></td>"
            f"<td>{esc(intent['kind'])}<br><small>{esc(intent['risk_stage'])} / {esc(intent['association_state'])}</small></td>"
            f"<td>{esc(intent['candidate_episode_ids'])}</td>"
            f"<td><code>{esc(intent['dedup_episode_interval_key'])}</code></td>"
            f"<td>{esc(intent['observation_ids'])}<br><small>{esc(intent['source_ids'])}</small></td>"
            f"<td>{esc(intent['evidence_refs'])}<br><small>source_time: {esc(intent['source_times'])}</small></td>"
            f"<td>{esc(intent['observed_at_times'])}</td>"
            f"<td>trigger_known_time: {esc(intent['trigger_known_time'])}<br>detected_at: {esc(intent['detected_at'])}<br>received_at: {esc(intent['received_at'])}</td>"
            "</tr>"
        )

    intent_by_id = {
        intent["intent_id"]: intent for intent in result["input"]["action_intents"]
    }
    intent_by_id[result["input"]["exact_replay_attempt"]["intent_id"]] = result[
        "input"
    ]["exact_replay_attempt"]
    decision_rows = []
    for decision in result["window_results"][1]["card_coalesce"]["decisions"]:
        intent = intent_by_id[decision["intent_id"]]
        elapsed = decision["coalescing_elapsed_seconds"]
        window = decision["coalescing_window_seconds"]
        decision_rows.append(
            "<tr>"
            f"<td>{esc(intent['received_at'])}</td>"
            f"<td><code>{esc(intent['display_card_id'])}</code></td>"
            f"<td>{esc(intent['kind'])}</td>"
            f"<td>{esc(decision['status'])}</td>"
            f"<td><code>{esc(decision['decision_reason'])}</code></td>"
            f"<td>{esc(elapsed) if elapsed is not None else '—'} / {esc(window) if window is not None else '—'} 秒</td>"
            "</tr>"
        )

    case_titles = {
        "exact_replay": "精确重放",
        "stale_replay": "旧内容改写时间后重放",
        "complementary_sources": "互补来源 A-B / A-C",
        "risk_escalation": "风险升级",
        "risk_escalation_inside_window": "窗口内风险升级",
        "conflict_pending_update": "待核状态升级为冲突",
        "counterevidence": "反证：A-C 确认不同事件",
        "association_split": "A-B 关系拆分",
        "pending_merge_then_counter_and_split": "待核更新后反证与拆分",
        "distinct_event": "独立事件卡 Z",
        "cross_window": "窗口边界与越窗",
        "cross_card_duplicate": "跨显示卡的相同候选",
        "cross_episode_duplicate": "同卡上的不同候选 episode",
        "out_of_order_source_time": "处理顺序与来源时间倒序",
        "late_old_observation": "迟到的旧观测与分立时间",
    }
    case_rows = []
    for name, title in case_titles.items():
        case = result["forced_cases"][name]
        case_rows.append(
            "<tr>"
            f"<th>{esc(title)}</th>"
            f"<td><code>{esc(name)}</code></td>"
            f"<td>{esc(json.dumps(case, ensure_ascii=False, sort_keys=True))}</td>"
            "</tr>"
        )

    v2_audit_rows = []
    for field, status in result["v2_contract_audit"].items():
        v2_audit_rows.append(
            "<tr>"
            f"<th><code>{esc(field)}</code></th>"
            f"<td>{esc(status)}</td>"
            "</tr>"
        )

    baseline = result["historical_baseline"]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>提醒动作合并策略合成对照</title>
<style>
:root {{ color-scheme: light; --ink:#182230; --muted:#5f6c7b; --line:#d7dee8; --blue:#155eef; --pale:#f4f7fb; --red:#8b1e16; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:#f6f8fb; color:var(--ink); font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1220px; margin:0 auto; padding:30px 22px 56px; }} h1 {{ font-size:30px; margin:0 0 8px; }} h2 {{ margin:34px 0 12px; font-size:21px; }} p {{ margin:8px 0; }} small,.muted {{ color:var(--muted); }}
.tag {{ display:inline-block; border:1px solid var(--line); border-radius:999px; padding:2px 9px; font-size:12px; color:var(--muted); background:white; }}
.banner {{ margin:20px 0; padding:16px 18px; border-left:5px solid var(--red); background:#fff0ed; border-radius:8px; }}
.panel {{ background:white; border:1px solid var(--line); border-radius:12px; padding:18px; margin-top:16px; box-shadow:0 2px 7px #1822300a; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:12px; }} .metric {{ padding:13px; background:var(--pale); border-radius:9px; }} .metric strong {{ display:block; font-size:17px; }}
.scroll {{ overflow:auto; border:1px solid var(--line); border-radius:9px; background:white; }} table {{ width:100%; border-collapse:collapse; min-width:780px; }} th,td {{ text-align:left; vertical-align:top; padding:10px 11px; border-bottom:1px solid var(--line); }} thead th {{ background:#eef3fa; position:sticky; top:0; }} tr:last-child th,tr:last-child td {{ border-bottom:0; }}
code {{ font-size:12px; overflow-wrap:anywhere; }} .boundary {{ background:#eff8ff; border:1px solid #b2ddff; padding:14px; border-radius:9px; }} .foot {{ margin-top:28px; font-size:13px; color:var(--muted); }}
</style>
</head>
<body><main>
<span class="tag">{esc(result['classification'])}</span>
<h1>待核提醒动作：逐关联动作 vs 同卡合并修订</h1>
<p>{esc(result['input']['unique_action_count'])} 条按处理顺序排列的合成动作输入分别运行两种策略：其中 19 条来自内存 AlertLedger 合成过渡，4 条是明示的边界探针。两种策略使用完全相同的输入；这些记录不是独立统计样本。窗口是实验参数，不构成业务批准。</p>
<div class="banner"><strong>历史失败保持原样：</strong>Mac V3-RSS 已完成 1,464 项检查，整轮 <b>{esc(baseline['round_status'])}</b>。五个合成场景中，四种方法的 20 条方法记录均缺少确证新事件首报；这 20 条不是独立样本。本次未重跑，也未重构旧指标。</div>
<section class="panel"><h2>对照结果</h2>
<div class="scroll"><table><thead><tr><th>窗口</th><th>PER_ASSOCIATION 提醒动作数</th><th>CARD_COALESCE 提醒动作数</th><th>语义卡片修订数（逐关联 / 合并）</th><th>合并进已有提醒的更新数</th><th>未表示的重要更新</th></tr></thead><tbody>{''.join(summary_rows)}</tbody></table></div>
<p class="muted">重要提醒类（确认、升级、反证、拆分、独立事件）始终生成单独动作。待核提醒只在相同显示卡、动作类型、风险阶段、批次、实验区间键，且与该提醒组首条修订至少共享一个候选 episode 时才可能合并；每条输入先写入独立卡片修订。</p></section>
<section class="panel"><h2>CARD_COALESCE / 5 秒：逐条决策与时间证据</h2>
<div class="scroll"><table><thead><tr><th>处理时间</th><th>卡片</th><th>动作</th><th>结果</th><th>解释码</th><th>已过窗口 / 窗口值</th></tr></thead><tbody>{''.join(decision_rows)}</tbody></table></div>
<p class="muted">窗口按合成 received_at 与该提醒组首次 received_at 计算，含边界等号；卡片更新不会延长窗口。source_time、observed_at、trigger_known_time、detected_at 与 received_at 分别列入输入记录。</p></section>
<section class="panel"><h2>窗口和身份规则</h2>
<div class="grid">
<div class="metric"><strong>窗口计算</strong><span>以合成处理时间 received_at 计时；采用首条提醒时间作为锚点，边界包含等号。窗口外的新提醒可开启下一条动作。</span></div>
<div class="metric"><strong>稳定卡与候选事件</strong><span>display_card_id 维持界面连续性；它本身不确立事件等价。候选 episode 独立保留，未知关联不会合并候选节点。冲突待核与一般待核作为不同状态处理。</span></div>
<div class="metric"><strong>送达与可见</strong><span>软件记录状态为 NOT_DELIVERED；动作及卡片修订仅在内存中模拟。实际送达时间与用户可见时间均为 UNKNOWN。模型调用节省量未测。</span></div>
</div></section>
<section class="panel"><h2>强制场景</h2><div class="scroll"><table><thead><tr><th>场景</th><th>键</th><th>输入和判定</th></tr></thead><tbody>{''.join(case_rows)}</tbody></table></div></section>
<section class="panel"><h2>被比较的同一提醒输入（{len(result['input']['action_intents'])} 条顺序动作，不作独立样本）</h2>
<div class="scroll"><table><thead><tr><th>处理 received_at</th><th>稳定显示卡 / 修订</th><th>动作 / 阶段 / 关联状态</th><th>候选 episode 节点</th><th>实验区间键</th><th>观测 / 来源</th><th>证据 / source_time</th><th>observed_at</th><th>trigger_known_time / detected_at / received_at</th></tr></thead><tbody>{''.join(action_rows)}</tbody></table></div></section>
<section class="panel"><h2>公开 V2 字段审计：部分合成跟踪</h2>
<p class="muted">逐字段对照固定公开规格提交 <code>{esc(result['v2_contract_audit']['source_spec_commit'])}</code>。这些状态表示字段跟踪，不代表业务通过。</p>
<div class="scroll"><table><thead><tr><th>V2 字段 / 边界</th><th>本次证据</th></tr></thead><tbody>{''.join(v2_audit_rows)}</tbody></table></div></section>
<section class="panel"><h2>三项评价分别报告</h2>
<div class="grid">
<div class="metric"><strong>提醒及时性：仅模拟</strong><span>卡片修订在代码内同步写入，模拟延迟为 0 秒；没有外部送达回执，也未设正式时限。</span></div>
<div class="metric"><strong>内容完整性：对输入核对</strong><span>所有唯一语义更新均有卡片修订；证据与关联引用按输入保留。完整性不等于用户界面显示成功。</span></div>
<div class="metric"><strong>事件确证准确性：未评估</strong><span>同/不同事件转换由合成场景指定，不能据此估计真实事件身份准确率。</span></div>
</div><p class="boundary"><b>尚未决定：</b>官方合并键、窗口长度、多 flag severity 优先级、来源可信阈值、提醒是否真实送达，以及 Mac 上的 ESRCH / EPERM 原因。</p></section>
<p class="foot">实验参数：窗口 {esc(result['experiment_parameters']['window_values_seconds'])} 秒；批次 {esc(result['experiment_parameters']['batch_id'])}。dedup_episode_interval_key 的正式语义未冻结。多 flag severity 保持未决；用户可见消息未生成。未调用模型、网络服务或投递适配器。关联证据/设备名称均为 synthetic:// 占位内容。生成修订 {esc(result.get('source_revision', 'not-recorded'))}。</p>
</main></body></html>
"""
