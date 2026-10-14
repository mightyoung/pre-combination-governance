"""Shared schema-level checks for one frozen method result."""


ALLOWED_FIELDS = {
    "cards", "possible", "risk", "priority", "notify", "fused",
    "independent_evidence", "role", "context_evidence",
    "notification_reasons", "card_updates", "risk_state_update",
    "review_notification_reasons",
}
RISKS = {"UNKNOWN", "EXPOSURE", "EXPOSURE_HIGH", "CONFLICT_REVIEW"}
PRIORITIES = {"REVIEW", "FOLLOW_UP"}
NOTIFICATION_REASONS = {
    "new_event_first_alert", "risk_escalation", "handling_follow_up_only",
}
REVIEW_REASONS = {"uncertain_new_alarm_requires_review"}
CONTEXT_STATUSES = {"ABSENT", "UNKNOWN_REVIEW", "NEW_BOUNDARY"}
ROLE = "event rules shared; DS motion fusion diagnostic only"
PROHIBITED_LABELS = {
    "I1_NO_INFO_CONTINUING", "I2_NO_INFO_NEW", "I3_RECOVERY",
    "I4_WORK_ROUND", "I5_SOURCE_TRANSITION", "I6_BOUNDARY_CONFLICT",
}


class ResultContractError(ValueError):
    pass


def _no_hidden_fields(value, path="result"):
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(term in lowered for term in ("oracle", "truth", "case", "arm", "trace", "future")):
                raise ResultContractError(path + " contains a scorer-only field")
            _no_hidden_fields(item, path + "." + str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _no_hidden_fields(item, path + "[" + str(index) + "]")
    elif isinstance(value, str) and value in PROHIBITED_LABELS:
        raise ResultContractError(path + " contains a scorer-only case label")


def validate_result(result: dict, expected_alarm_ids: set[str]) -> None:
    if not isinstance(result, dict) or set(result) != ALLOWED_FIELDS:
        raise ResultContractError("method result fields differ from the frozen worker contract")
    _no_hidden_fields(result)
    if not isinstance(result.get("cards"), dict) or set(result["cards"]) != expected_alarm_ids:
        raise ResultContractError("method result card IDs do not match the visible prefix")
    if any(not isinstance(value, str) or not value for value in result["cards"].values()):
        raise ResultContractError("method result contains an invalid card ID")
    possible = result.get("possible")
    if not isinstance(possible, list) or any(
            not isinstance(item, str) or item not in expected_alarm_ids
            for item in possible):
        raise ResultContractError("possible/review IDs must be visible alarm IDs")
    if len(set(possible)) != len(possible):
        raise ResultContractError("possible/review IDs must be unique")
    risk = result.get("risk")
    priority = result.get("priority")
    if (not isinstance(risk, str) or risk not in RISKS
            or not isinstance(priority, str) or priority not in PRIORITIES):
        raise ResultContractError("risk or priority differs from the frozen method contract")
    if not isinstance(result.get("notify"), bool):
        raise ResultContractError("notify must be a boolean")
    evidence_count = result.get("independent_evidence")
    if isinstance(evidence_count, bool) or not isinstance(evidence_count, int) or evidence_count < 0:
        raise ResultContractError("independent_evidence must be a nonnegative integer")
    if result.get("role") != ROLE:
        raise ResultContractError("method role differs from the pinned diagnostic label")

    fused = result.get("fused")
    if not isinstance(fused, dict):
        raise ResultContractError("fused output must be an object")
    for key, mass in fused.items():
        if not isinstance(key, str) or not key:
            raise ResultContractError("fused output keys must be nonempty strings")
        if mass is not None and (not isinstance(mass, dict)
                                 or set(mass) != {"RUN", "STOP", "U", "conflict"}
                                 or any(not isinstance(item, str) for item in mass.values())):
            raise ResultContractError("fused mass must retain the frozen four-field representation")

    context = result.get("context_evidence")
    if (not isinstance(context, dict)
            or set(context) != {"status", "accepted", "rejected"}
            or not isinstance(context.get("status"), str)
            or context.get("status") not in CONTEXT_STATUSES
            or not isinstance(context.get("accepted"), list)
            or not isinstance(context.get("rejected"), list)
            or any(not isinstance(item, dict) for item in context["accepted"])):
        raise ResultContractError("context_evidence differs from the frozen gate output")
    if any(not isinstance(item, dict) or set(item) != {"kind", "reason"}
           or not all(isinstance(item.get(field), str) for field in ("kind", "reason"))
           for item in context["rejected"]):
        raise ResultContractError("rejected gate evidence must include kind and reason")

    for field, choices in (("notification_reasons", NOTIFICATION_REASONS),
                           ("review_notification_reasons", REVIEW_REASONS)):
        reasons = result.get(field)
        if (not isinstance(reasons, list)
                or any(not isinstance(item, str) or item not in choices for item in reasons)
                or len(reasons) != len(set(reasons))):
            raise ResultContractError(field + " contains an unknown or duplicate reason")

    updates = result.get("card_updates")
    if not isinstance(updates, list):
        raise ResultContractError("card_updates must be a list")
    for update in updates:
        if (not isinstance(update, dict)
                or set(update) != {"id", "kind", "association_established", "review_required"}
                or not isinstance(update.get("id"), str)
                or update.get("id") not in expected_alarm_ids
                or update.get("kind") != "possible_existing_event_update"
                or update.get("association_established") is not False
                or update.get("review_required") is not True):
            raise ResultContractError("card update must reference a visible alarm ID and remain unconfirmed")

    state_update = result.get("risk_state_update")
    if state_update is not None and (
            not isinstance(state_update, dict) or set(state_update) != {"from", "to"}
            or not isinstance(state_update.get("to"), str)
            or state_update.get("to") not in RISKS
            or state_update.get("from") is not None
            and (not isinstance(state_update.get("from"), str)
                 or state_update.get("from") not in RISKS)):
        raise ResultContractError("risk_state_update differs from the frozen risk transition")
