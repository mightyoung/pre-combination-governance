"""Pure preview construction and field-presence audit for public V2 alerts.

The output is a synthetic content preview. It does not emit or deliver a
notification, establish evidence qualification, or validate real event truth.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .alert_action_experiment import (
    ActionIntent,
    ActionKind,
    ApplyStatus,
    CardRevision,
    ReminderActionLedger,
)
from .alert_governance_v2 import severity_for_risk_flag
from .event_card_resolution import (
    AssociationResolution,
    EventDisplayCard,
    PendingAssociation,
)


PUBLIC_V2_SPEC_COMMIT = "cc6d59b88bda73381fc09d9091a224ab4155891e"
PUBLIC_V2_NOTIFICATION_REQUIRED_FIELDS = (
    "notification_id",
    "kind",
    "severity",
    "risk_state",
    "risk_basis_ids",
    "uncertainty_reason",
    "affected_observation_ids",
    "display_card_id",
    "candidate_episode_ids",
    "association_state",
    "user_visible_message",
    "suggested_verification_action",
    "trigger_known_time",
    "detected_at",
    "emitted_at",
    "visible_at",
    "content_revision",
    "dedup_episode_interval_key",
)


def _parse_alignment_time(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be an ISO-8601 timestamp with UTC offset")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"{label} must be an ISO-8601 timestamp with UTC offset"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _format_alignment_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

_ASSOCIATION_REASON = {
    "UNKNOWN_PENDING": (
        "事件关联仍待核实；未知状态不代表风险消失，也不证明候选属于同一事件。"
    ),
    "CONFLICT_PENDING": "风险或事件身份相关证据冲突尚未解决。",
    "SAME_CONFIRMED": (
        "当前输入标记为 SAME_CONFIRMED；真实来源资格与事件确证真值未评估。"
    ),
    "DIFFERENT_CONFIRMED": (
        "当前输入标记为 DIFFERENT_CONFIRMED；真实确证真值未评估，需保留关系历史。"
    ),
}


def _severity_preview(risk_flags: tuple[str, ...]) -> tuple[str | None, str, str]:
    if not risk_flags:
        return None, "NO_RISK_FLAG_PROVIDED", "风险等级待定（输入未提供风险标记）"
    if len(risk_flags) > 1:
        return (
            None,
            "PENDING_MULTIFLAG_POLICY",
            "风险等级待定（多风险标记等级规则待定义）",
        )
    try:
        return severity_for_risk_flag(risk_flags[0]), "MAPPED_SINGLE_FLAG", ""
    except ValueError:
        return None, "UNMAPPED_RISK_FLAG", "风险等级待定（风险标记映射未定义）"


def _display_values(values: tuple[str, ...], missing_label: str) -> str:
    return "、".join(values) if values else missing_label


def build_notification_content_preview(
    intent: ActionIntent,
    *,
    notification_id: str,
    content_revision: int | None,
    decision_status: str,
    revision_trace: Mapping[str, Any],
) -> dict[str, Any]:
    """Build all public V2 notification fields as a non-delivered preview."""
    if not isinstance(intent, ActionIntent):
        raise TypeError("intent must be an ActionIntent")
    if not isinstance(notification_id, str) or not notification_id.strip():
        raise ValueError("notification_id must be a non-empty experiment-local ID")
    if content_revision is not None and (
        isinstance(content_revision, bool)
        or not isinstance(content_revision, int)
        or content_revision < 1
    ):
        raise ValueError("content_revision must be a positive integer or None")
    if not isinstance(decision_status, str) or not decision_status.strip():
        raise ValueError("decision_status must be a non-empty string")
    if not isinstance(revision_trace, Mapping):
        raise TypeError("revision_trace must be a mapping")

    severity, severity_status, severity_label = _severity_preview(intent.risk_flags)
    association_reason = _ASSOCIATION_REASON[intent.association_state]
    risk_flags = list(intent.risk_flags)
    risk_label = _display_values(intent.risk_flags, "未提供")
    source_label = _display_values(intent.source_ids, "未提供")
    observation_label = _display_values(intent.observation_ids, "未提供")
    candidate_label = _display_values(intent.candidate_episode_ids, "未提供")
    evidence_label = _display_values(intent.risk_basis_ids, "未提供")
    severity_text = severity or severity_label
    association_text = f"{intent.association_state}（本次输入状态）"
    user_message = (
        f"待核实风险提醒｜等级：{severity_text}。当前风险标记：{risk_label}；"
        f"关联状态：{association_text}。原因：{association_reason}"
        f"涉及设备/来源：{source_label}；任务：当前接口不支持绑定；观测：{observation_label}；"
        f"候选事件：{candidate_label}；风险依据：{evidence_label}。"
        f"显示卡：{intent.display_card_id}。"
    )
    if intent.kind.value == "EVENT_SPLIT":
        user_message += (
            "请按既定处置流程核查分拆依据；本次只是分拆预览，未实际创建事件卡。"
            "证据充分并通过门控后，应建立独立事件卡并保留到本卡的历史链接。"
        )
    else:
        user_message += (
            "请按既定处置流程核查；后续确认或升级会作为本卡修订。"
            "证据支持分拆时，应建立独立事件卡并保留到本卡的历史链接。"
        )
    if severity_status == "MAPPED_SINGLE_FLAG":
        user_message = user_message.replace(
            f"等级：{severity_text}。",
            f"等级：{severity_text}（单一风险标记映射预览）。",
            1,
        )

    field_statuses = {
        "notification_id": "EXPERIMENT_LOCAL_ID",
        "kind": "PUBLIC_V2_FIXED_KIND",
        "severity": severity_status,
        "risk_state": "SYNTHETIC_INPUT_FLAGS_AND_ACTION_STAGE",
        "risk_basis_ids": "SYNTHETIC_EVIDENCE_REFERENCES",
        "uncertainty_reason": "TEMPLATE_FROM_PUBLIC_ASSOCIATION_STATE",
        "affected_observation_ids": "SYNTHETIC_INPUT_IDS",
        "display_card_id": "SYNTHETIC_STABLE_DISPLAY_ID",
        "candidate_episode_ids": "SYNTHETIC_SEPARATE_NODES",
        "association_state": "SYNTHETIC_PUBLIC_ENUM_VALUE",
        "user_visible_message": "CONTENT_PREVIEW_ONLY_NOT_DELIVERED",
        "suggested_verification_action": "PUBLIC_TEMPLATE_PREVIEW_NOT_PROCEDURE_VALIDATION",
        "trigger_known_time": (
            "SYNTHETIC_INPUT_TIME"
            if intent.trigger_known_time is not None
            else "UNKNOWN_NOT_PROVIDED"
        ),
        "detected_at": (
            "SYNTHETIC_INPUT_TIME"
            if intent.detected_at is not None
            else "UNKNOWN_NOT_PROVIDED"
        ),
        "emitted_at": "NOT_EMITTED",
        "visible_at": "UNKNOWN_NOT_RUN",
        "content_revision": "IN_MEMORY_SYNTHETIC_CARD_REVISION",
        "dedup_episode_interval_key": "EXPERIMENT_INPUT_NOT_FROZEN",
    }
    if intent.kind.value == "EVENT_SPLIT":
        suggested_action = (
            "按既定处置流程核查分拆证据、设备/任务绑定和事件关联；"
            "若证据通过门控，应建立独立事件卡并以不可变历史引用链接此卡。"
            "本预览不代表分拆已确认或事件卡已创建。"
        )
    else:
        suggested_action = (
            "按既定处置流程核查相关风险依据、设备/任务绑定和事件关联；"
            "证据充分后确认或升级并保留本卡修订；若证据支持分拆，应建立独立事件卡并链接本卡历史。"
        )
    preview: dict[str, Any] = {
        "preview_id": (
            f"{notification_id}:revision:{content_revision}"
            if content_revision is not None
            else f"{notification_id}:revision:unknown"
        ),
        "preview_status": (
            "DUPLICATE_REPLAY_IGNORED"
            if decision_status == "DUPLICATE_REPLAY_IGNORED"
            else "PREVIEW_ONLY"
        ),
        "decision_status": decision_status,
        "delivery_status": "NOT_DELIVERED",
        "emission_status": "NOT_EMITTED_SIMULATION_ONLY",
        "notification_id": notification_id,
        "kind": "PENDING_VERIFICATION_RISK_ALERT",
        "severity": severity,
        "risk_state": {
            "risk_flags": risk_flags,
            "risk_stage": intent.risk_stage,
            "provenance": "SYNTHETIC_INPUT",
        },
        "risk_basis_ids": list(intent.risk_basis_ids),
        "uncertainty_reason": association_reason,
        "affected_observation_ids": list(intent.observation_ids),
        "display_card_id": intent.display_card_id,
        "candidate_episode_ids": list(intent.candidate_episode_ids),
        "association_state": intent.association_state,
        "user_visible_message": user_message,
        "suggested_verification_action": suggested_action,
        "trigger_known_time": intent.trigger_known_time,
        "detected_at": intent.detected_at,
        "emitted_at": None,
        "visible_at": None,
        "content_revision": content_revision,
        "dedup_episode_interval_key": intent.dedup_episode_interval_key,
        "risk_flags": risk_flags,
        "source_ids": list(intent.source_ids),
        "task_ids": [],
        "task_context_status": "UNSUPPORTED_BY_CURRENT_INTERFACE",
        "evidence_refs": list(intent.evidence_refs),
        "time_evidence": {
            "source_times": list(intent.source_times),
            "observed_at_times": list(intent.observed_at_times),
            "trigger_known_time": intent.trigger_known_time,
            "detected_at": intent.detected_at,
            "received_at_processing_time": intent.received_at,
            "provenance": "SYNTHETIC_EXPERIMENT_INPUT",
        },
        "revision_trace": dict(revision_trace),
        "field_statuses": field_statuses,
    }
    preview["field_audit"] = audit_notification_preview(preview)
    return preview


def _intent_from_card_revision(revision: CardRevision) -> ActionIntent:
    return ActionIntent(
        intent_id=revision.intent_id,
        display_card_id=revision.display_card_id,
        kind=revision.kind,
        risk_stage=revision.risk_stage,
        received_at=revision.received_at,
        observation_ids=revision.observation_ids,
        source_ids=revision.source_ids,
        candidate_episode_ids=revision.candidate_episode_ids,
        association_ids=revision.association_ids,
        evidence_refs=revision.evidence_refs,
        risk_flags=revision.risk_flags,
        risk_basis_ids=revision.risk_basis_ids,
        source_times=revision.source_times,
        observed_at_times=revision.observed_at_times,
        experiment_batch_id=revision.experiment_batch_id,
        association_state=revision.association_state,
        dedup_episode_interval_key=revision.dedup_episode_interval_key,
        trigger_known_time=revision.trigger_known_time,
        detected_at=revision.detected_at,
    )


def _identity_card_details(
    identity: PendingAssociation | AssociationResolution,
    card_id: str,
) -> tuple[list[str], list[str], list[str], str, dict[str, Any]]:
    if isinstance(identity, PendingAssociation):
        if card_id != identity.display_card_id:
            raise ValueError("pending association belongs to a different display card")
        return (
            [],
            list(identity.candidate_episode_ids),
            [],
            identity.association_state,
            {
                "association_id": identity.association_id,
                "association_state": identity.association_state,
                "state_source": "EXTERNALLY_SUPPLIED_PENDING_STATE",
                "pending_at": identity.pending_at,
                "evidence_refs": list(identity.evidence_refs),
                "identity_truth": "NOT_EVALUATED",
            },
        )

    if not isinstance(identity, AssociationResolution):
        raise TypeError("identity must be PendingAssociation or AssociationResolution")
    card = next(
        (item for item in identity.display_cards if item.card_id == card_id), None
    )
    if card is None:
        raise ValueError("display card is not part of the association resolution")
    pair_episode_ids = list(
        dict.fromkeys(
            episode_id
            for item in identity.display_cards
            for episode_id in item.episode_ids
        )
    )
    return (
        list(card.episode_ids),
        pair_episode_ids,
        list(card.history_link_card_ids),
        identity.association_state,
        {
            "association_id": identity.association_id,
            "association_state": identity.association_state,
            "reason_code": identity.reason_code,
            "state_source": "EXTERNALLY_SUPPLIED_RESOLUTION",
            "pending_at": identity.pending_at,
            "identity_evidence_known_at": identity.identity_evidence_known_at,
            "resolved_at": identity.resolved_at,
            "evidence_refs": list(identity.evidence_refs),
            "identity_truth": "NOT_EVALUATED",
        },
    )


def _validate_identity_ledger_alignment(
    identity_record: Mapping[str, Any],
    *,
    event_episode_ids: list[str],
    association_episode_ids: list[str],
    association_state: str,
    revisions: tuple[CardRevision, ...],
) -> dict[str, Any]:
    evidence_known_at = identity_record.get("identity_evidence_known_at")
    identity_resolved_at = identity_record.get("resolved_at")
    is_resolved_identity = association_state in {
        "SAME_CONFIRMED",
        "DIFFERENT_CONFIRMED",
    }
    evidence_known_time = (
        _parse_alignment_time(evidence_known_at, "identity_evidence_known_at")
        if is_resolved_identity
        else None
    )
    identity_resolved_time = (
        _parse_alignment_time(identity_resolved_at, "resolved_at")
        if is_resolved_identity
        else None
    )
    if (
        evidence_known_time is not None
        and identity_resolved_time is not None
        and identity_resolved_time < evidence_known_time
    ):
        raise ValueError("identity resolution precedes identity evidence availability")

    temporal_alignment = {
        "status": (
            "NO_RESOLVED_ACTION_TO_COMPARE"
            if is_resolved_identity
            else "NOT_APPLICABLE_TO_PENDING_IDENTITY"
        ),
        "identity_evidence_known_at": (
            _format_alignment_time(evidence_known_time)
            if evidence_known_time is not None
            else None
        ),
        "identity_resolved_at": (
            _format_alignment_time(identity_resolved_time)
            if identity_resolved_time is not None
            else None
        ),
        "earliest_resolved_revision_received_at": None,
        "earliest_identity_transition_detected_at": None,
    }
    if not revisions:
        return {
            "status": "NO_LEDGER_HISTORY_TO_COMPARE",
            "association_id": identity_record["association_id"],
            "matched_revision_count": 0,
            "latest_revision_association_state": None,
            "expected_event_episode_ids": list(event_episode_ids),
            "latest_revision_candidate_episode_ids": [],
            "temporal_alignment": temporal_alignment,
        }

    expected_episode_ids = set(association_episode_ids)
    expected_card_episode_ids = set(event_episode_ids)
    pending_states = {"UNKNOWN_PENDING", "CONFLICT_PENDING"}
    resolved_states = {"SAME_CONFIRMED", "DIFFERENT_CONFIRMED"}
    identity_transition_kinds = {
        ActionKind.ASSOCIATION_CONFIRMED,
        ActionKind.EVENT_SPLIT,
        ActionKind.DISTINCT_EVENT_ALERT,
    }
    resolved_revision_received_times: list[datetime] = []
    identity_transition_detected_times: list[datetime] = []
    for revision in revisions:
        unexpected_episode_ids = set(revision.candidate_episode_ids) - expected_episode_ids
        if unexpected_episode_ids:
            raise ValueError(
                "card ledger candidate episodes do not match the supplied identity association"
            )
        revision_candidate_ids = set(revision.candidate_episode_ids)
        if (
            revision.association_state in pending_states
            and revision.kind is ActionKind.ASSOCIATION_PENDING
            and revision_candidate_ids != expected_episode_ids
        ):
            raise ValueError(
                "pending candidate episodes do not match the supplied identity association"
            )
        if revision.association_state in resolved_states:
            if revision.association_state != association_state:
                raise ValueError(
                    "ledger revision contains a different resolved association state"
                )
            if not revision_candidate_ids.issubset(expected_card_episode_ids):
                raise ValueError(
                    "ledger revision candidate episodes do not match resolved card episodes"
                )
            if (
                revision.kind in identity_transition_kinds
                and revision_candidate_ids != expected_card_episode_ids
            ):
                raise ValueError(
                    "identity transition candidate episodes do not match resolved card episodes"
                )
            received_time = _parse_alignment_time(
                revision.received_at, "resolved_revision_received_at"
            )
            if received_time < identity_resolved_time:
                raise ValueError(
                    "resolved card revision precedes identity resolution"
                )
            resolved_revision_received_times.append(received_time)
            if (
                revision.kind in identity_transition_kinds
                and revision.detected_at is not None
            ):
                detected_time = _parse_alignment_time(
                    revision.detected_at, "identity_transition_detected_at"
                )
                if detected_time < evidence_known_time:
                    raise ValueError(
                        "identity transition detected before identity evidence was known"
                    )
                identity_transition_detected_times.append(detected_time)

    latest_revision = revisions[-1]
    association_id = identity_record["association_id"]
    if association_id not in latest_revision.association_ids:
        raise ValueError(
            "latest ledger revision does not reference the supplied identity association ID"
        )
    if latest_revision.association_state != association_state:
        raise ValueError(
            "latest ledger revision association state does not match the supplied identity state"
        )
    if is_resolved_identity:
        temporal_alignment["status"] = "ALIGNED"
        if resolved_revision_received_times:
            temporal_alignment["earliest_resolved_revision_received_at"] = (
                _format_alignment_time(min(resolved_revision_received_times))
            )
        if identity_transition_detected_times:
            temporal_alignment["earliest_identity_transition_detected_at"] = (
                _format_alignment_time(min(identity_transition_detected_times))
            )
    return {
        "status": "MATCHED_LEDGER_HISTORY",
        "association_id": association_id,
        "matched_revision_count": len(revisions),
        "latest_revision_association_state": latest_revision.association_state,
        "expected_event_episode_ids": list(event_episode_ids),
        "latest_revision_candidate_episode_ids": list(latest_revision.candidate_episode_ids),
        "temporal_alignment": temporal_alignment,
    }


def build_event_card_preview(
    identity: PendingAssociation | AssociationResolution,
    *,
    card_id: str,
    ledger: ReminderActionLedger,
) -> dict[str, Any]:
    """Aggregate a full synthetic card preview from identity and ledger history.

    The identity state is supplied by the caller. This function renders no real
    event truth or delivery receipt; each in-memory revision uses the public
    notification preview and remains marked NOT_DELIVERED.
    """
    if not isinstance(ledger, ReminderActionLedger):
        raise TypeError("ledger must be a ReminderActionLedger")
    event_episode_ids, association_episode_ids, history_links, association_state, identity_record = (
        _identity_card_details(identity, card_id)
    )

    revisions = ledger.card_revisions_for(card_id)
    identity_ledger_alignment = _validate_identity_ledger_alignment(
        identity_record,
        event_episode_ids=event_episode_ids,
        association_episode_ids=association_episode_ids,
        association_state=association_state,
        revisions=revisions,
    )
    notification_by_intent = {
        revision.intent_id: notification
        for notification in ledger.notifications
        for revision in notification.updates
    }
    decision_by_intent = {
        decision.intent_id: decision
        for decision in ledger.decisions
        if decision.status is not ApplyStatus.DUPLICATE_REPLAY
    }

    revision_previews: list[dict[str, Any]] = []
    for index, revision in enumerate(revisions):
        decision = decision_by_intent.get(revision.intent_id)
        notification = notification_by_intent.get(revision.intent_id)
        if decision is None or notification is None:
            raise ValueError("card revision is missing its action decision or notification")
        intent = _intent_from_card_revision(revision)
        previous = revisions[index - 1] if index else None
        trace = {
            "intent_id": revision.intent_id,
            "action_kind": revision.kind.value,
            "decision_status": decision.status.value,
            "decision_reason": decision.decision_reason,
            "notification_id": notification.experiment_notification_id,
            "display_card_id": card_id,
            "content_revision": revision.revision,
            "previous_content_revision": previous.revision if previous else None,
            "previous_intent_id": previous.intent_id if previous else None,
            "association_state": revision.association_state,
            "candidate_episode_ids": list(revision.candidate_episode_ids),
            "evidence_refs": list(revision.evidence_refs),
            "source_times": list(revision.source_times),
            "observed_at_times": list(revision.observed_at_times),
            "trigger_known_time": revision.trigger_known_time,
            "detected_at": revision.detected_at,
            "received_at_processing_time": revision.received_at,
            "provenance": "SYNTHETIC_ACTION_LEDGER_REVISION",
        }
        revision_previews.append(
            build_notification_content_preview(
                intent,
                notification_id=notification.experiment_notification_id,
                content_revision=revision.revision,
                decision_status=decision.status.value,
                revision_trace=trace,
            )
        )

    revision_intent_ids = {revision.intent_id for revision in revisions}
    replay_attempts = [
        {
            "intent_id": decision.intent_id,
            "status": decision.status.value,
            "decision_reason": decision.decision_reason,
            "notification_id": decision.experiment_notification_id,
            "new_revision_created": False,
            "new_notification_created": False,
            "delivery_status": "NOT_DELIVERED",
        }
        for decision in ledger.decisions
        if decision.status is ApplyStatus.DUPLICATE_REPLAY
        and decision.intent_id in revision_intent_ids
    ]

    current_content = revision_previews[-1] if revision_previews else None
    if not revisions:
        notice_lifecycle_status = "NO_NOTICE"
    elif revisions[-1].kind is ActionKind.NOTICE_CORRECTED:
        notice_lifecycle_status = "CORRECTED"
    elif revisions[-1].kind is ActionKind.NOTICE_CANCELLED:
        notice_lifecycle_status = "CANCELLED"
    else:
        notice_lifecycle_status = "ACTIVE"
    candidate_episode_ids = (
        association_episode_ids
        if association_state in {"UNKNOWN_PENDING", "CONFLICT_PENDING"}
        else []
    )
    card_notifications = tuple(
        notification
        for notification in ledger.notifications
        if notification.display_card_id == card_id
    )
    all_required_fields_present = bool(revision_previews) and all(
        preview["field_audit"]["all_required_fields_present"]
        for preview in revision_previews
    )
    return {
        "preview_status": "SYNTHETIC_FULL_EVENT_CARD_PREVIEW_ONLY",
        "card_content_scope": "ALL_LEDGER_REVISIONS_PLUS_IDENTITY_LINKS",
        "delivery_status": "NOT_DELIVERED",
        "emitted_at": None,
        "visible_at": None,
        "display_card_id": card_id,
        "event_episode_ids": event_episode_ids,
        "candidate_episode_ids": candidate_episode_ids,
        "association_context_episode_ids": association_episode_ids,
        "association_state": association_state,
        "notice_lifecycle_status": notice_lifecycle_status,
        "history_link_card_ids": history_links,
        "identity_resolution": identity_record,
        "identity_ledger_alignment": identity_ledger_alignment,
        "content_revision_count": len(revisions),
        "notification_action_count": len(card_notifications),
        "notification_ids": [
            notification.experiment_notification_id for notification in card_notifications
        ],
        "revision_history": revision_previews,
        "current_content": current_content,
        "replay_attempts": replay_attempts,
        "replay_attempt_count": len(replay_attempts),
        "card_preview_audit": {
            "all_required_fields_present": all_required_fields_present,
            "revision_count": len(revision_previews),
            "business_acceptance": "NOT_EVALUATED",
            "identity_truth": "NOT_EVALUATED",
            "delivery_evidence": "NOT_RUN",
        },
        "business_acceptance": "NOT_EVALUATED",
    }


def audit_notification_preview(preview: Mapping[str, Any]) -> dict[str, Any]:
    """Check required V2 field presence and report unresolved field semantics."""
    if not isinstance(preview, Mapping):
        raise TypeError("preview must be a mapping")
    declared_statuses = preview.get("field_statuses", {})
    if not isinstance(declared_statuses, Mapping):
        declared_statuses = {}
    fields: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for field in PUBLIC_V2_NOTIFICATION_REQUIRED_FIELDS:
        present = field in preview
        status = (
            declared_statuses.get(field, "PRESENT_UNCLASSIFIED")
            if present
            else "MISSING_REQUIRED_FIELD"
        )
        fields[field] = {"present": present, "status": status}
        if not present:
            missing.append(field)
    return {
        "schema_source_commit": PUBLIC_V2_SPEC_COMMIT,
        "schema_scope": "PARTIAL_FIELD_PRESENCE_ONLY",
        "required_field_count": len(PUBLIC_V2_NOTIFICATION_REQUIRED_FIELDS),
        "present_field_count": len(PUBLIC_V2_NOTIFICATION_REQUIRED_FIELDS) - len(missing),
        "missing_fields": missing,
        "all_required_fields_present": not missing,
        "business_acceptance": "NOT_EVALUATED",
        "fields": fields,
    }


def summarize_notification_preview_audits(
    previews: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize field presence without promoting it to V2 acceptance."""
    audits = [audit_notification_preview(preview) for preview in previews]
    field_status_counts: dict[str, dict[str, int]] = {}
    for field in PUBLIC_V2_NOTIFICATION_REQUIRED_FIELDS:
        counts: dict[str, int] = {}
        for audit in audits:
            status = audit["fields"][field]["status"]
            counts[status] = counts.get(status, 0) + 1
        field_status_counts[field] = counts
    return {
        "schema_source_commit": PUBLIC_V2_SPEC_COMMIT,
        "schema_scope": "PARTIAL_FIELD_PRESENCE_ONLY",
        "preview_count": len(previews),
        "all_required_fields_present": all(
            audit["all_required_fields_present"] for audit in audits
        ),
        "missing_field_counts": {
            field: sum(not audit["fields"][field]["present"] for audit in audits)
            for field in PUBLIC_V2_NOTIFICATION_REQUIRED_FIELDS
        },
        "field_status_counts": field_status_counts,
        "business_acceptance": "NOT_EVALUATED",
    }
