"""Synthetic boundary check for notice version, occurrence, and arrival order.

The version rule in this pilot is an explicit fixture assumption. It is not a
production default, a private V2 interpretation, or a claim about source clocks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .alert_action_experiment import (
    ActionIntent,
    ActionKind,
    ApplyStatus,
    PolicyMode,
    ReminderActionLedger,
)
from .alert_notification_preview import build_event_card_preview
from .event_card_resolution import PendingAssociation


_IGNORED_VERSION_STATUSES = frozenset(
    {
        ApplyStatus.DUPLICATE_NOTICE_VERSION,
        ApplyStatus.STALE_NOTICE_VERSION,
    }
)


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
    spec: dict[str, Any],
    base: datetime,
    use_notice_version: bool,
) -> ActionIntent:
    context = spec["context"]
    occurred_at = _timestamp(
        base, step["event_occurred_seconds"], "event_occurred_seconds"
    )
    return ActionIntent(
        intent_id=step["intent_id"],
        display_card_id=context["display_card_id"],
        kind=ActionKind(step["kind"]),
        risk_stage=step["risk_stage"],
        received_at=_timestamp(base, step["received_seconds"], "received_seconds"),
        observation_ids=tuple(context["observation_ids"]),
        source_ids=tuple(context["source_ids"]),
        candidate_episode_ids=tuple(context["candidate_episode_ids"]),
        association_ids=(context["association_id"],),
        evidence_refs=tuple(step["evidence_refs"]),
        risk_flags=tuple(step["risk_flags"]),
        risk_basis_ids=tuple(step["risk_basis_ids"]),
        source_times=(occurred_at,),
        observed_at_times=(occurred_at,),
        experiment_batch_id=context["experiment_batch_id"],
        association_state=context["association_state"],
        dedup_episode_interval_key=context["dedup_episode_interval_key"],
        notice_version=(step["notice_version"] if use_notice_version else None),
    )


def _new_ledger_and_identity(
    spec: dict[str, Any], *, base: datetime
) -> tuple[ReminderActionLedger, PendingAssociation]:
    context = spec["context"]
    pending = PendingAssociation(
        association_id=context["association_id"],
        display_card_id=context["display_card_id"],
        candidate_episode_ids=tuple(context["candidate_episode_ids"]),
        association_state=context["association_state"],
        pending_at=base.isoformat().replace("+00:00", "Z"),
        evidence_refs=("synthetic://ordering/pending",),
    )
    ledger = ReminderActionLedger(
        mode=PolicyMode(spec["settings"]["policy_mode"]),
        merge_window_seconds=spec["settings"]["merge_window_seconds"],
    )
    return ledger, pending


def _run_sequence(
    spec: dict[str, Any], *, base: datetime, use_notice_version: bool
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
    list[int | None],
    list[str],
]:
    ledger, pending = _new_ledger_and_identity(spec, base=base)
    timeline: list[dict[str, Any]] = []
    for step in spec["steps"]:
        intent = _intent_from_step(
            step,
            spec=spec,
            base=base,
            use_notice_version=use_notice_version,
        )
        decision = ledger.apply(intent)
        preview = build_event_card_preview(
            pending, card_id=pending.display_card_id, ledger=ledger
        )
        timeline.append(
            {
                "step_id": step["step_id"],
                "intent_id": intent.intent_id,
                "transport_receipt_id": step["transport_receipt_id"],
                "notice_version": intent.notice_version,
                "action_kind": intent.kind.value,
                "event_occurred_at": intent.source_times[0],
                "received_at_processing_time": intent.received_at,
                "decision_status": decision.status.value,
                "decision_reason": decision.decision_reason,
                "display_card_id": intent.display_card_id,
                "notice_lifecycle_status": preview["notice_lifecycle_status"],
                "notification_action_count": preview["notification_action_count"],
                "card_revision_count": preview["content_revision_count"],
                "notification_id": decision.experiment_notification_id,
                "delivery_status": preview["delivery_status"],
                "source_ids": list(intent.source_ids),
            }
        )

    final_card = build_event_card_preview(
        pending, card_id=pending.display_card_id, ledger=ledger
    )
    ignored_attempts = [
        {
            "step_id": row["step_id"],
            "intent_id": row["intent_id"],
            "notice_version": row["notice_version"],
            "event_occurred_at": row["event_occurred_at"],
            "received_at_processing_time": row["received_at_processing_time"],
            "decision_status": row["decision_status"],
            "decision_reason": row["decision_reason"],
            "delivery_status": "NOT_DELIVERED",
        }
        for row in timeline
        if row["decision_status"]
        in {status.value for status in _IGNORED_VERSION_STATUSES}
    ]
    accepted_versions = [
        revision["revision_trace"]["notice_version"]
        for revision in final_card["revision_history"]
    ]
    return timeline, final_card, ignored_attempts, accepted_versions, list(
        ledger.missed_important_update_ids()
    )


def _summary(
    timeline: list[dict[str, Any]],
    final_card: dict[str, Any],
    *,
    accepted_versions: list[int | None],
    ignored_attempts: list[dict[str, Any]],
    missed_important_update_ids: list[str],
) -> dict[str, Any]:
    return {
        "decision_statuses": [row["decision_status"] for row in timeline],
        "notification_action_counts": [
            row["notification_action_count"] for row in timeline
        ],
        "card_revision_counts": [row["card_revision_count"] for row in timeline],
        "notice_lifecycle_states": [
            row["notice_lifecycle_status"] for row in timeline
        ],
        "accepted_notice_versions": accepted_versions,
        "final_history_intent_ids": [
            revision["revision_trace"]["intent_id"]
            for revision in final_card["revision_history"]
        ],
        "ignored_attempts": ignored_attempts,
        "missed_important_update_ids": missed_important_update_ids,
        "final_notice_lifecycle_status": final_card["notice_lifecycle_status"],
        "final_notification_action_count": final_card["notification_action_count"],
        "final_card_revision_count": final_card["content_revision_count"],
        "delivery_status": final_card["delivery_status"],
        "timeline": timeline,
        "final_card": final_card,
    }


def run_synthetic_lifecycle_ordering_pilot(
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Compare the frozen synthetic version rule with the legacy arrival-order path."""
    if not isinstance(spec, dict):
        raise TypeError("spec must be a JSON object")
    if spec.get("status") != "FROZEN_PRE_RUN":
        raise ValueError("pilot input must be frozen before execution")
    if spec.get("classification") != "SYNTHETIC_MECHANISM_BOUNDARY_ONLY":
        raise ValueError("pilot is restricted to explicitly synthetic inputs")
    if spec.get("synthetic_only") is not True:
        raise ValueError("pilot requires synthetic_only=true")
    if not isinstance(spec.get("steps"), list) or not spec["steps"]:
        raise ValueError("steps must be a non-empty ordered list")
    if spec.get("source_independence") != (
        "NOT_ASSERTED; all messages use one synthetic source label."
    ):
        raise ValueError("source independence must remain explicitly unasserted")
    if len(spec.get("context", {}).get("source_ids", [])) != 1:
        raise ValueError("this fixture requires exactly one synthetic source label")

    base = _base_time(spec)
    versioned_timeline, versioned_card, ignored, versions, missed = _run_sequence(
        spec, base=base, use_notice_version=True
    )
    legacy_timeline, legacy_card, _, legacy_versions, legacy_missed = _run_sequence(
        spec, base=base, use_notice_version=False
    )
    return {
        "pilot_id": spec["pilot_id"],
        "status": "SYNTHETIC_MECHANISM_BOUNDARY_CHECK_COMPLETED",
        "classification": spec["classification"],
        "synthetic_only": True,
        "spec_revision_type": spec["spec_revision_type"],
        "ordering_contract_assumption": spec["ordering_contract_assumption"],
        "source_independence": spec["source_independence"],
        "real_delivery_tested": False,
        "efficacy_status": "NOT_ASSESSED",
        "versioned": _summary(
            versioned_timeline,
            versioned_card,
            accepted_versions=versions,
            ignored_attempts=ignored,
            missed_important_update_ids=missed,
        ),
        "arrival_order_only_baseline": _summary(
            legacy_timeline,
            legacy_card,
            accepted_versions=legacy_versions,
            ignored_attempts=[],
            missed_important_update_ids=legacy_missed,
        ),
        "unsupported_items": list(spec["unsupported_items"]),
    }
