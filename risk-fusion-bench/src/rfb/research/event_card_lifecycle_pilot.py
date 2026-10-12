"""Run one frozen synthetic notice lifecycle through the in-memory card ledger.

This pilot checks card revisions and notification-action bookkeeping only. It
does not contact a transport, infer source independence, or adjudicate event
identity, risk truth, delivery, or efficacy.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from .alert_action_experiment import (
    ActionIntent,
    ActionKind,
    ReminderActionLedger,
    PolicyMode,
)
from .alert_notification_preview import build_event_card_preview
from .event_card_resolution import PendingAssociation


def _timestamp(base: datetime, seconds: Any, label: str) -> str:
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise ValueError(f"{label} must be an integer offset in seconds")
    return (base + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _base_time(spec: dict[str, Any]) -> datetime:
    value = spec.get("base_time_utc")
    if not isinstance(value, str):
        raise ValueError("base_time_utc must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("base_time_utc must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("base_time_utc must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _intent_from_step(
    step: dict[str, Any],
    *,
    spec: dict[str, Any],
    base: datetime,
    prior_intents: dict[str, ActionIntent],
) -> ActionIntent:
    intent_id = step.get("intent_id")
    if not isinstance(intent_id, str) or not intent_id.strip():
        raise ValueError("each step needs a non-empty intent_id")
    replay_of = step.get("replay_of")
    received_at = _timestamp(base, step.get("received_seconds"), "received_seconds")
    if replay_of is not None:
        if replay_of not in prior_intents:
            raise ValueError("replay_of must reference an earlier step_id")
        original = prior_intents[replay_of]
        if original.intent_id != intent_id:
            raise ValueError("a replay must reuse the original intent_id")
        return replace(original, received_at=received_at)

    context = spec["context"]
    source_ids = tuple(context["source_ids"])
    observation_ids = tuple(context.get("observation_ids", ("SYNTH-OBSERVATION-ONE",)))
    source_time = _timestamp(base, step.get("source_seconds"), "source_seconds")
    observed_at = _timestamp(base, step.get("observed_seconds"), "observed_seconds")
    return ActionIntent(
        intent_id=intent_id,
        display_card_id=context["display_card_id"],
        kind=ActionKind(step["kind"]),
        risk_stage=step["risk_stage"],
        received_at=received_at,
        observation_ids=observation_ids,
        source_ids=source_ids,
        candidate_episode_ids=tuple(context["candidate_episode_ids"]),
        association_ids=(context["association_id"],),
        evidence_refs=tuple(step["evidence_refs"]),
        risk_flags=tuple(step["risk_flags"]),
        risk_basis_ids=tuple(step["risk_basis_ids"]),
        source_times=(source_time,),
        observed_at_times=(observed_at,),
        experiment_batch_id=context["experiment_batch_id"],
        association_state=context["association_state"],
        dedup_episode_interval_key=context["dedup_episode_interval_key"],
    )


def _new_ledger_and_identity(
    spec: dict[str, Any], *, base: datetime
) -> tuple[ReminderActionLedger, PendingAssociation]:
    context = spec["context"]
    settings = spec["settings"]
    card_id = context["display_card_id"]
    pending = PendingAssociation(
        association_id=context["association_id"],
        display_card_id=card_id,
        candidate_episode_ids=tuple(context["candidate_episode_ids"]),
        association_state=context["association_state"],
        pending_at=base.isoformat().replace("+00:00", "Z"),
        evidence_refs=("synthetic://lifecycle/pending-association",),
    )
    ledger = ReminderActionLedger(
        mode=PolicyMode(settings["policy_mode"]),
        merge_window_seconds=settings["merge_window_seconds"],
    )
    return ledger, pending


def _run_steps(
    steps: list[dict[str, Any]],
    *,
    spec: dict[str, Any],
    base: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    ledger, pending = _new_ledger_and_identity(spec, base=base)
    card_id = pending.display_card_id
    intents_by_step: dict[str, ActionIntent] = {}
    timeline: list[dict[str, Any]] = []

    for step in steps:
        intent = _intent_from_step(
            step,
            spec=spec,
            base=base,
            prior_intents=intents_by_step,
        )
        decision = ledger.apply(intent)
        if "replay_of" not in step:
            intents_by_step[step["step_id"]] = intent
        preview = build_event_card_preview(pending, card_id=card_id, ledger=ledger)
        timeline.append(
            {
                "step_id": step["step_id"],
                "intent_id": intent.intent_id,
                "action_kind": intent.kind.value,
                "decision_status": decision.status.value,
                "decision_reason": decision.decision_reason,
                "display_card_id": card_id,
                "association_state": preview["association_state"],
                "notice_lifecycle_status": preview["notice_lifecycle_status"],
                "notification_action_count": preview["notification_action_count"],
                "card_revision_count": preview["content_revision_count"],
                "notification_id": decision.experiment_notification_id,
                "delivery_status": preview["delivery_status"],
                "time_evidence": {
                    "source_times": list(intent.source_times),
                    "observed_at_times": list(intent.observed_at_times),
                    "trigger_known_time": intent.trigger_known_time,
                    "detected_at": intent.detected_at,
                    "received_at_processing_time": intent.received_at,
                    "actual_emitted_at": None,
                    "actual_visible_at": None,
                    "time_status": "SYNTHETIC_INPUT; TRANSPORT TIMES NOT RUN",
                },
                "risk_flags": list(intent.risk_flags),
                "source_ids": list(intent.source_ids),
            }
        )

    final_card = build_event_card_preview(pending, card_id=card_id, ledger=ledger)
    protected_reasons = [
        decision.decision_reason
        for decision in ledger.decisions
        if decision.intent_id in {
            step["intent_id"]
            for step in steps
            if step.get("kind") in {
                ActionKind.NOTICE_CORRECTED.value,
                ActionKind.NOTICE_CANCELLED.value,
            }
        }
    ]
    return timeline, final_card, protected_reasons


def run_synthetic_card_lifecycle_pilot(spec: dict[str, Any]) -> dict[str, Any]:
    """Run a frozen JSON fixture and return a JSON-serializable mechanism trace."""
    if not isinstance(spec, dict):
        raise TypeError("spec must be a JSON object")
    if spec.get("status") != "FROZEN_PRE_RUN":
        raise ValueError("pilot input must be frozen before execution")
    if spec.get("classification") != "SYNTHETIC_MECHANISM_CHECK_ONLY":
        raise ValueError("pilot is restricted to explicitly synthetic inputs")
    if spec.get("synthetic_only") is not True:
        raise ValueError("pilot requires synthetic_only=true")
    if not isinstance(spec.get("steps"), list) or not spec["steps"]:
        raise ValueError("steps must be a non-empty ordered list")
    counterexample_spec = spec.get("counterexample")
    if not isinstance(counterexample_spec, dict) or not isinstance(
        counterexample_spec.get("steps"), list
    ):
        raise ValueError("a frozen counterexample step list is required")

    base = _base_time(spec)
    timeline, final_card, protected_reasons = _run_steps(
        spec["steps"], spec=spec, base=base
    )
    counterexample_timeline, counterexample_card, _ = _run_steps(
        counterexample_spec["steps"], spec=spec, base=base
    )
    return {
        "pilot_id": spec["pilot_id"],
        "status": "SYNTHETIC_MECHANISM_CHECK_COMPLETED",
        "classification": spec["classification"],
        "synthetic_only": True,
        "source_independence": spec["source_independence"],
        "real_delivery_tested": False,
        "efficacy_status": "NOT_ASSESSED",
        "timeline": timeline,
        "final_card": final_card,
        "protected_action_reasons": protected_reasons,
        "counterexample": {
            "description": counterexample_spec["description"],
            "decision_statuses": [
                row["decision_status"] for row in counterexample_timeline
            ],
            "notification_action_counts": [
                row["notification_action_count"] for row in counterexample_timeline
            ],
            "card_revision_counts": [
                row["card_revision_count"] for row in counterexample_timeline
            ],
            "notice_lifecycle_status": counterexample_card[
                "notice_lifecycle_status"
            ],
            "timeline": counterexample_timeline,
            "final_card": counterexample_card,
            "interpretation": counterexample_spec["expected"]["interpretation"],
        },
    }
