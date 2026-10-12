"""Synthetic pilot for unversioned updates after a versioned card notice.

The policy keeps unversioned input out of card revisions after a versioned
notice has been accepted. Higher risk signals become separate pending reviews;
they are not confirmed and do not emit notifications.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from .alert_action_experiment import (
    ActionIntent,
    ActionKind,
    PolicyMode,
    ReminderActionLedger,
)
from .alert_notification_preview import build_event_card_preview
from .event_card_resolution import PendingAssociation


_RISK_GRADE_RANK = {"LOW": 0, "WARNING": 1, "CRITICAL": 2}


def _timestamp(base: datetime, seconds: Any, field_name: str) -> str:
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise ValueError(f"{field_name} must be an integer offset in seconds")
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
    context: dict[str, Any],
    base: datetime,
    prior_intents: dict[str, ActionIntent],
) -> ActionIntent:
    received_at = _timestamp(base, step["received_seconds"], "received_seconds")
    if step.get("replay_of") is not None:
        original = prior_intents[step["replay_of"]]
        return replace(original, received_at=received_at)
    if step.get("duplicate_of") is not None:
        original = prior_intents[step["duplicate_of"]]
        return replace(
            original,
            intent_id=step["intent_id"],
            received_at=received_at,
        )

    source_time = _timestamp(base, step["source_seconds"], "source_seconds")
    observed_at = _timestamp(
        base,
        step.get("observed_seconds", step["source_seconds"]),
        "observed_seconds",
    )
    return ActionIntent(
        intent_id=step["intent_id"],
        display_card_id=context["display_card_id"],
        kind=ActionKind(step["kind"]),
        risk_stage=step["risk_stage"],
        received_at=received_at,
        observation_ids=tuple(context["observation_ids"]),
        source_ids=tuple(context["source_ids"]),
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
        notice_version=step.get("notice_version"),
        risk_level_claim=step.get("risk_level_claim"),
    )


def _pending_identity(
    context: dict[str, Any], *, base: datetime, scenario_id: str
) -> PendingAssociation:
    return PendingAssociation(
        association_id=context["association_id"],
        display_card_id=context["display_card_id"],
        candidate_episode_ids=tuple(context["candidate_episode_ids"]),
        association_state=context["association_state"],
        pending_at=base.isoformat().replace("+00:00", "Z"),
        evidence_refs=(f"synthetic://mixed/{scenario_id}/pending",),
    )


def _summarize_scenario(
    scenario: dict[str, Any], *, base: datetime, settings: dict[str, Any]
) -> dict[str, Any]:
    scenario_id = scenario["scenario_id"]
    context = scenario["context"]
    pending = _pending_identity(context, base=base, scenario_id=scenario_id)
    ledger = ReminderActionLedger(
        mode=PolicyMode(settings["policy_mode"]),
        merge_window_seconds=settings["merge_window_seconds"],
    )
    prior_intents: dict[str, ActionIntent] = {}
    step_by_intent_id: dict[str, dict[str, Any]] = {}
    timeline: list[dict[str, Any]] = []
    audit_trace: list[dict[str, object]] = []

    for step in scenario["steps"]:
        intent = _intent_from_step(
            step,
            context=context,
            base=base,
            prior_intents=prior_intents,
        )
        audit_count_before = len(
            ledger.unversioned_audit_records_for(intent.display_card_id)
        )
        decision = ledger.apply(intent)
        if not step.get("replay_of") and not step.get("duplicate_of"):
            prior_intents[step["step_id"]] = intent
        step_by_intent_id.setdefault(intent.intent_id, step)

        preview = build_event_card_preview(
            pending, card_id=intent.display_card_id, ledger=ledger
        )
        audit_records = ledger.unversioned_audit_records_for(intent.display_card_id)
        if len(audit_records) > audit_count_before:
            audit_entry = audit_records[-1]
            audit_entry["step_id"] = step["step_id"]
            audit_entry["transport_receipt_id"] = step["transport_receipt_id"]
            audit_trace.append(audit_entry)

        current_content = preview["current_content"] or {}
        current_severity = current_content.get("severity") or "UNKNOWN"
        if audit_entry_for_step := next(
            (record for record in audit_trace if record["step_id"] == step["step_id"]),
            None,
        ):
            reported_status = audit_entry_for_step["reported_risk_grade_status"]
            risk_signal_grade = audit_entry_for_step["risk_signal_grade"]
        elif intent.notice_version is not None:
            reported_status = (
                f"{current_severity}_FROM_VERSIONED_FLAG"
                if current_severity != "UNKNOWN"
                else "UNKNOWN_VERSIONED_RISK"
            )
            risk_signal_grade = current_severity
        else:
            reported_status = "UNKNOWN_MISSING_CLAIM"
            risk_signal_grade = "UNKNOWN"

        timeline.append(
            {
                "step_id": step["step_id"],
                "intent_id": intent.intent_id,
                "transport_receipt_id": step["transport_receipt_id"],
                "notice_version": intent.notice_version,
                "action_kind": intent.kind.value,
                "source_times": list(intent.source_times),
                "observed_at_times": list(intent.observed_at_times),
                "received_at_processing_time": intent.received_at,
                "risk_level_claim": intent.risk_level_claim,
                "reported_risk_grade_status": reported_status,
                "risk_signal_grade": risk_signal_grade,
                "current_card_risk_grade": current_severity,
                "decision_status": decision.status.value,
                "decision_reason": decision.decision_reason,
                "display_card_id": intent.display_card_id,
                "notice_lifecycle_status": preview["notice_lifecycle_status"],
                "notification_action_count": preview["notification_action_count"],
                "card_revision_count": preview["content_revision_count"],
                "audit_record_count": len(audit_records),
                "pending_risk_review_count": len(
                    ledger.pending_risk_reviews_for(intent.display_card_id)
                ),
                "notification_id": decision.experiment_notification_id,
                "delivery_status": preview["delivery_status"],
            }
        )

    final_card = build_event_card_preview(
        pending, card_id=context["display_card_id"], ledger=ledger
    )
    reviews = [
        dict(review)
        for review in ledger.pending_risk_reviews_for(context["display_card_id"])
    ]
    for review in reviews:
        source_step = step_by_intent_id.get(str(review["source_intent_id"]))
        if source_step is not None:
            review["source_step_id"] = source_step["step_id"]
            review["transport_receipt_id"] = source_step["transport_receipt_id"]

    return {
        "scenario_id": scenario_id,
        "decision_statuses": [row["decision_status"] for row in timeline],
        "notification_action_counts": [
            row["notification_action_count"] for row in timeline
        ],
        "card_revision_counts": [row["card_revision_count"] for row in timeline],
        "notice_lifecycle_states": [
            row["notice_lifecycle_status"] for row in timeline
        ],
        "audit_record_counts": [row["audit_record_count"] for row in timeline],
        "pending_risk_review_counts": [
            row["pending_risk_review_count"] for row in timeline
        ],
        "reported_risk_grade_statuses": [
            row["reported_risk_grade_status"] for row in timeline
        ],
        "risk_signal_grades": [row["risk_signal_grade"] for row in timeline],
        "current_card_risk_grades": [
            row["current_card_risk_grade"] for row in timeline
        ],
        "audit_records": audit_trace,
        "pending_risk_reviews": reviews,
        "final_card": final_card,
        "missed_important_update_ids": list(ledger.missed_important_update_ids()),
        "timeline": timeline,
    }


def run_synthetic_unversioned_mixed_stream_pilot(
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Run the frozen mixed-stream boundary contract without external effects."""
    if not isinstance(spec, dict):
        raise TypeError("spec must be a JSON object")
    if spec.get("status") != "FROZEN_PRE_RUN":
        raise ValueError("pilot input must be frozen before execution")
    if spec.get("classification") != "SYNTHETIC_MECHANISM_BOUNDARY_ONLY":
        raise ValueError("pilot is restricted to explicitly synthetic inputs")
    if spec.get("synthetic_only") is not True:
        raise ValueError("pilot requires synthetic_only=true")
    if not isinstance(spec.get("scenarios"), list) or not spec["scenarios"]:
        raise ValueError("scenarios must be a non-empty ordered list")
    if not all(
        len(scenario.get("context", {}).get("source_ids", [])) == 1
        for scenario in spec["scenarios"]
    ):
        raise ValueError("each scenario requires one synthetic source label")

    base = _base_time(spec)
    return {
        "pilot_id": spec["pilot_id"],
        "status": "SYNTHETIC_MIXED_STREAM_CHECK_COMPLETED",
        "classification": spec["classification"],
        "synthetic_only": True,
        "spec_revision_type": spec["spec_revision_type"],
        "source_independence": spec["source_independence"],
        "real_delivery_tested": False,
        "efficacy_status": "NOT_ASSESSED",
        "scenarios": {
            scenario["scenario_id"]: _summarize_scenario(
                scenario, base=base, settings=spec["settings"]
            )
            for scenario in spec["scenarios"]
        },
        "unsupported_items": list(spec["unsupported_items"]),
    }
