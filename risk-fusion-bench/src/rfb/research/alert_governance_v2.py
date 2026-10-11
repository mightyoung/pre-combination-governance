"""Small pure mappings fixed by the sanitized public V2 business spec.

This is not a V2 payload serializer or a complete implementation. In
particular, severity is mapped for one risk flag at a time; aggregation of
multiple simultaneous flags is intentionally left unresolved.
"""

from __future__ import annotations


_PENDING_RISK_ALERT_TRIGGERS = frozenset(
    {
        "ACTIVE_RISK_RELEVANT_EVIDENCE_CONFLICT",
        "UNCONFIRMED_EVENT_ASSOCIATION_WITH_ACTIVE_RISK",
        "MISSING_OR_REJECTED_BOUNDARY_WITH_ACTIVE_RISK",
    }
)

_SINGLE_FLAG_SEVERITY = {
    "EXPOSURE": "WARNING",
    "CONFLICT_REVIEW": "WARNING",
    "UNRESOLVED_RISK_RELEVANT_CONFLICT": "WARNING_RISK_UNRESOLVED",
    "EXPOSURE_HIGH": "CRITICAL",
}


def notification_kind_for_trigger(trigger_type: str) -> str:
    """Map a public V2 trigger to its specified notification kind."""
    if not isinstance(trigger_type, str) or trigger_type not in _PENDING_RISK_ALERT_TRIGGERS:
        raise ValueError(f"unsupported public V2 trigger: {trigger_type!r}")
    return "PENDING_VERIFICATION_RISK_ALERT"


def severity_for_risk_flag(risk_flag: str) -> str:
    """Return the public V2 severity for one known risk flag.

    Unknown flags and multi-flag inputs fail closed. The public spec does not
    define how simultaneous flags are aggregated.
    """
    if not isinstance(risk_flag, str) or risk_flag not in _SINGLE_FLAG_SEVERITY:
        raise ValueError(f"unsupported single public V2 risk flag: {risk_flag!r}")
    return _SINGLE_FLAG_SEVERITY[risk_flag]
