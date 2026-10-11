"""Pure preview construction and field-presence audit for public V2 alerts.

The output is a synthetic content preview. It does not emit or deliver a
notification, establish evidence qualification, or validate real event truth.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .alert_action_experiment import ActionIntent
from .alert_governance_v2 import severity_for_risk_flag


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
