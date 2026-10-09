from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any


class MetricInputError(ValueError):
    pass


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MetricInputError(f"{name}: finite number required")
    result = float(value)
    if not math.isfinite(result):
        raise MetricInputError(f"{name}: finite number required")
    return result


def _unit(value: Any, name: str) -> float:
    result = _finite(value, name)
    if not 0.0 <= result <= 1.0:
        raise MetricInputError(f"{name}: value must be in [0, 1]")
    return result


def _frame(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MetricInputError("frame: non-empty sequence required")
    result = tuple(value)
    if not result or any(not isinstance(item, str) or not item for item in result):
        raise MetricInputError("frame: non-empty string atoms required")
    if len(set(result)) != len(result):
        raise MetricInputError("frame: atoms must be unique")
    return result


def validate_bpa(
    value: Mapping[str, Any],
) -> tuple[tuple[str, ...], dict[frozenset[str], float]]:
    if not isinstance(value, Mapping):
        raise MetricInputError("bpa: mapping required")
    frame = _frame(value["frame"])
    masses = value.get("masses")
    if (
        not isinstance(masses, Sequence)
        or isinstance(masses, (str, bytes))
        or not masses
    ):
        raise MetricInputError("bpa.masses: non-empty sequence required")
    if set(value) == {"frame", "masses"}:
        rows = masses
    elif set(value) == {"frame", "focal_sets", "masses"}:
        focal_sets = value["focal_sets"]
        if (
            not isinstance(focal_sets, Sequence)
            or isinstance(focal_sets, (str, bytes))
            or len(focal_sets) != len(masses)
        ):
            raise MetricInputError("bpa: focal_sets and masses must align")
        rows = [
            {"focal_set": focal_set, "mass": mass}
            for focal_set, mass in zip(focal_sets, masses, strict=True)
        ]
    else:
        raise MetricInputError("bpa: unknown or missing fields")
    known = set(frame)
    canonical: dict[frozenset[str], float] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != {"focal_set", "mass"}:
            raise MetricInputError(f"bpa.masses[{index}]: invalid row")
        focal = row["focal_set"]
        if not isinstance(focal, Sequence) or isinstance(focal, (str, bytes)):
            raise MetricInputError(f"bpa.masses[{index}].focal_set: sequence required")
        if any(not isinstance(atom, str) or atom not in known for atom in focal):
            raise MetricInputError(f"bpa.masses[{index}].focal_set: atom outside frame")
        focal_set = frozenset(focal)
        if len(focal_set) != len(focal):
            raise MetricInputError(f"bpa.masses[{index}].focal_set: duplicate atom")
        if focal_set in canonical:
            raise MetricInputError(f"bpa.masses[{index}]: duplicate focal set")
        canonical[focal_set] = _unit(row["mass"], f"bpa.masses[{index}].mass")
    if not math.isclose(sum(canonical.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise MetricInputError("bpa: masses must sum to one")
    return frame, canonical


def _paired_bpas(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> tuple[tuple[str, ...], dict[frozenset[str], float], dict[frozenset[str], float]]:
    left_frame, left_mass = validate_bpa(left)
    right_frame, right_mass = validate_bpa(right)
    if left_frame != right_frame:
        raise MetricInputError("bpa: ordered frames differ")
    return left_frame, left_mass, right_mass


def belief_l1(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    _, first, second = _paired_bpas(left, right)
    return sum(
        abs(first.get(key, 0.0) - second.get(key, 0.0)) for key in first | second
    )


def jousselme_distance(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    _, first, second = _paired_bpas(left, right)
    focal_sets = sorted(
        first | second, key=lambda item: (len(item), tuple(sorted(item)))
    )
    delta = [first.get(item, 0.0) - second.get(item, 0.0) for item in focal_sets]
    quadratic = 0.0
    for row, first_set in enumerate(focal_sets):
        for column, second_set in enumerate(focal_sets):
            union = first_set | second_set
            similarity = 1.0 if not union else len(first_set & second_set) / len(union)
            quadratic += delta[row] * similarity * delta[column]
    return math.sqrt(max(0.0, 0.5 * quadratic))


def validate_interval(value: Any, name: str = "risk_interval") -> tuple[float, float]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 2
    ):
        raise MetricInputError(f"{name}: two endpoints required")
    lower, upper = _unit(value[0], f"{name}[0]"), _unit(value[1], f"{name}[1]")
    if lower > upper:
        raise MetricInputError(f"{name}: lower endpoint exceeds upper endpoint")
    return lower, upper


def interval_endpoint_error(predicted: Any, oracle: Any) -> dict[str, float]:
    pred_lower, pred_upper = validate_interval(predicted, "predicted_interval")
    oracle_lower, oracle_upper = validate_interval(oracle, "oracle_interval")
    lower_error = abs(pred_lower - oracle_lower)
    upper_error = abs(pred_upper - oracle_upper)
    return {
        "lower_absolute_error": lower_error,
        "upper_absolute_error": upper_error,
        "endpoint_l1": lower_error + upper_error,
        "endpoint_mean_absolute_error": (lower_error + upper_error) / 2.0,
    }


def score_response_pair(
    *,
    pair_kind: str,
    base_interval: Any,
    variant_interval: Any,
    oracle_base_interval: Any,
    oracle_variant_interval: Any,
) -> dict[str, Any]:
    kind = pair_kind.upper()
    if kind not in {"XD", "XI"}:
        raise MetricInputError("pair_kind: XD or XI required")
    base = validate_interval(base_interval, "base_interval")
    variant = validate_interval(variant_interval, "variant_interval")
    oracle_base = validate_interval(oracle_base_interval, "oracle_base_interval")
    oracle_variant = validate_interval(
        oracle_variant_interval, "oracle_variant_interval"
    )
    response = tuple(variant[index] - base[index] for index in range(2))
    oracle_response = tuple(
        oracle_variant[index] - oracle_base[index] for index in range(2)
    )
    amplitude = sum(abs(value) for value in response)
    oracle_amplitude = sum(abs(value) for value in oracle_response)
    dot = sum(response[index] * oracle_response[index] for index in range(2))
    if amplitude == 0.0 and oracle_amplitude == 0.0:
        direction = "BOTH_STABLE"
        direction_matches = True
    elif amplitude == 0.0:
        direction = "NO_RESPONSE"
        direction_matches = False
    elif oracle_amplitude == 0.0:
        direction = "SPURIOUS_RESPONSE"
        direction_matches = False
    elif dot > 0.0:
        direction = "SAME_DIRECTION"
        direction_matches = True
    elif dot < 0.0:
        direction = "OPPOSITE_DIRECTION"
        direction_matches = False
    else:
        direction = "ORTHOGONAL_DIRECTION"
        direction_matches = False
    return {
        "pair_kind": kind,
        "metric_family": "DRI" if kind == "XD" else "SRI",
        "method_endpoint_response": list(response),
        "oracle_endpoint_response": list(oracle_response),
        "method_response_amplitude_l1": amplitude,
        "oracle_response_amplitude_l1": oracle_amplitude,
        "response_amplitude_error": abs(amplitude - oracle_amplitude),
        "response_vector_error_l1": sum(
            abs(response[index] - oracle_response[index]) for index in range(2)
        ),
        "response_direction": direction,
        "response_direction_matches_oracle": direction_matches,
    }


def score_actions(
    *,
    predicted_actions: Any,
    oracle_actions: Any,
    available: Any,
    decision_opportunity: bool = True,
) -> dict[str, Any]:
    if not isinstance(available, bool):
        raise MetricInputError("available: boolean required")
    if not isinstance(decision_opportunity, bool):
        raise MetricInputError("decision_opportunity: boolean required")

    def action_set(value: Any, name: str) -> set[str]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise MetricInputError(f"{name}: sequence required")
        result = set(value)
        if (
            len(result) != len(value)
            or not result
            or any(not isinstance(item, str) or not item for item in result)
        ):
            raise MetricInputError(f"{name}: invalid action set")
        return result

    oracle = action_set(oracle_actions, "oracle_actions")
    predicted = (
        action_set(predicted_actions, "predicted_actions") if available else set()
    )
    disagreement = predicted != oracle if decision_opportunity and available else None
    return {
        "decision_opportunity": decision_opportunity,
        "available": available,
        "false_block": bool(decision_opportunity and not available),
        "action_set_disagreement": disagreement,
        "predicted_action_count": len(predicted) if available else None,
        "oracle_action_count": len(oracle),
    }


def recovery_curve(
    prefixes: Sequence[Mapping[str, Any]], *, disclosure_prefix: int
) -> dict[str, Any]:
    if (
        isinstance(disclosure_prefix, bool)
        or not isinstance(disclosure_prefix, int)
        or disclosure_prefix < 0
    ):
        raise MetricInputError("disclosure_prefix: non-negative integer required")
    rows: list[dict[str, Any]] = []
    for raw in prefixes:
        prefix = raw.get("prefix")
        if (
            isinstance(prefix, bool)
            or not isinstance(prefix, int)
            or prefix < disclosure_prefix
        ):
            continue
        row: dict[str, Any] = {
            "prefix": prefix,
            "status": "SCORED",
            "endpoint_l1": None,
        }
        try:
            row.update(
                interval_endpoint_error(raw["method_interval"], raw["oracle_interval"])
            )
        except (KeyError, MetricInputError) as exc:
            row.update(
                status="UNAVAILABLE",
                failure_code=f"RECOVERY_{type(exc).__name__.upper()}",
            )
        rows.append(row)
    if not rows:
        raise MetricInputError("recovery: no prefix at or after disclosure")
    scored = [row["endpoint_l1"] for row in rows if row["status"] == "SCORED"]
    return {
        "disclosure_prefix": disclosure_prefix,
        "prefixes": rows,
        "applicable_prefixes": len(rows),
        "scored_prefixes": len(scored),
        "unavailable_prefixes": len(rows) - len(scored),
        "mean_endpoint_l1": sum(scored) / len(scored) if scored else None,
        "final_endpoint_l1": rows[-1]["endpoint_l1"]
        if rows[-1]["status"] == "SCORED"
        else None,
    }


def score_method_prefix(
    method_result: Mapping[str, Any], oracle: Mapping[str, Any]
) -> dict[str, Any]:
    status = str(method_result.get("status", "SUCCEEDED"))
    base = {
        "status": status,
        "failure_code": method_result.get("failure_code"),
        "scored": False,
        "belief_l1": None,
        "jousselme": None,
        "belief_applicable": None,
        "lower_absolute_error": None,
        "upper_absolute_error": None,
        "endpoint_l1": None,
        "endpoint_mean_absolute_error": None,
        "action_set_disagreement": None,
        "false_block": None,
    }
    if status != "SUCCEEDED" or method_result.get("valid", True) is not True:
        base["failure_code"] = base["failure_code"] or f"METHOD_{status}"
        return base
    try:
        prediction = method_result.get("prediction", method_result)
        decision = method_result.get("decision", method_result)
        base.update(
            interval_endpoint_error(
                prediction["risk_interval"], oracle["risk_interval"]
            )
        )
        method_bpa = prediction.get("belief", prediction.get("bpa"))
        oracle_bpa = oracle.get("belief", oracle.get("bpa"))
        if method_bpa is not None:
            if oracle_bpa is None:
                raise MetricInputError("belief: oracle BPA required")
            base["belief_l1"] = belief_l1(method_bpa, oracle_bpa)
            base["jousselme"] = jousselme_distance(method_bpa, oracle_bpa)
            base["belief_applicable"] = True
        else:
            base["belief_applicable"] = False
        action_state = decision.get("action_state")
        predicted_actions = (
            [action_state] if isinstance(action_state, str) else action_state
        ) or decision.get("admissible_actions", [])
        action = score_actions(
            predicted_actions=predicted_actions,
            oracle_actions=oracle.get("admissible_actions")
            or [oracle.get("action_state")],
            available=method_result.get("available", True),
            decision_opportunity=oracle.get("decision_opportunity", True),
        )
        base.update(action)
        base["scored"] = True
    except (KeyError, MetricInputError, TypeError) as exc:
        base["status"] = "INVALID_OUTPUT"
        base["failure_code"] = f"METRIC_{type(exc).__name__.upper()}"
    return base


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value):
        return asdict(value)
    raise MetricInputError("mapping or dataclass required")


def score_block_prefixes(
    oracle_prefixes: Sequence[Mapping[str, Any]],
    method_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    oracle_by_prefix = {row["prefix"]: row for row in oracle_prefixes}
    output: list[dict[str, Any]] = []
    for method_row in method_rows:
        prefix = method_row.get("prefix")
        identity = {
            key: method_row.get(key)
            for key in ("physical_block_id", "method_id", "prefix")
            if key in method_row
        }
        oracle = oracle_by_prefix.get(prefix)
        if oracle is None:
            output.append(
                {
                    **identity,
                    "status": "ORACLE_UNAVAILABLE",
                    "failure_code": "ORACLE_PREFIX_MISSING",
                    "scored": False,
                    "endpoint_l1": None,
                }
            )
            continue
        output.append({**identity, **score_method_prefix(method_row, oracle)})
    return output


def make_runner_scorer(public_prefixes: Sequence[Any] | None = None):
    from .mme_oracle import evaluate_oracle

    def scorer(
        truth_sidecar: Any, block_method_rows: Mapping[str, Any]
    ) -> dict[str, Any]:
        available_prefixes = public_prefixes
        if available_prefixes is None:
            available_prefixes = next(
                (
                    row.get("_method_prefixes")
                    for row in block_method_rows.values()
                    if isinstance(row, Mapping) and row.get("_method_prefixes")
                ),
                None,
            )
        if not available_prefixes:
            raise MetricInputError("runner scorer requires public method prefixes")
        prefixes = {prefix.prefix_id: prefix for prefix in available_prefixes}
        oracle_rows: dict[str, dict[str, Any]] = {}
        for prefix_id, prefix in prefixes.items():
            view = evaluate_oracle(prefix, truth_sidecar).full_information
            oracle_rows[prefix_id] = {
                "risk_interval": list(view.risk_interval),
                "bpa": _mapping(view)["bpa"] if "bpa" in _mapping(view) else None,
                "action_state": view.action_state,
                "admissible_actions": [view.action_state],
                "decision_opportunity": True,
            }
        methods: dict[str, Any] = {}
        for method_id, raw_method in block_method_rows.items():
            method = _mapping(raw_method)
            scored_prefixes: list[dict[str, Any]] = []
            outputs: dict[str, Mapping[str, Any]] = {}
            supplied = {
                str(_mapping(row).get("prefix_id", "")): _mapping(row)
                for row in method.get("prefixes", [])
            }
            for prefix_id in prefixes:
                prefix_row = supplied.get(prefix_id, {})
                output = prefix_row.get("output")
                if isinstance(output, Mapping):
                    combined = {
                        **output,
                        "status": prefix_row.get("status", "SUCCEEDED"),
                        "failure_code": prefix_row.get("failure_code"),
                        "available": prefix_row.get("available", True),
                    }
                    outputs[prefix_id] = combined
                else:
                    combined = {
                        "status": prefix_row.get("status", "MISSING"),
                        "failure_code": prefix_row.get(
                            "failure_code", "METHOD_OUTPUT_MISSING"
                        ),
                    }
                oracle = oracle_rows.get(prefix_id)
                if oracle is None:
                    score = {
                        "status": "ORACLE_UNAVAILABLE",
                        "failure_code": "ORACLE_PREFIX_MISSING",
                        "scored": False,
                        "endpoint_l1": None,
                    }
                else:
                    score = score_method_prefix(combined, oracle)
                scored_prefixes.append({"prefix_id": prefix_id, **score})
            pairs: list[dict[str, Any]] = []
            prefix_coordinates = {
                (prefix.arm_id, prefix.prefix_index): prefix.prefix_id
                for prefix in prefixes.values()
            }
            indices = sorted({prefix.prefix_index for prefix in prefixes.values()})
            for prefix_index in indices:
                base_id = prefix_coordinates.get(("X", prefix_index))
                for variant in ("XD", "XI"):
                    variant_id = prefix_coordinates.get((variant, prefix_index))
                    if base_id not in outputs or variant_id not in outputs:
                        pairs.append(
                            {
                                "pair_kind": variant,
                                "metric_family": "DRI" if variant == "XD" else "SRI",
                                "prefix_index": prefix_index,
                                "status": "UNAVAILABLE",
                                "failure_code": "PAIR_METHOD_PREFIX_MISSING",
                            }
                        )
                        continue
                    try:
                        pairs.append(
                            score_response_pair(
                                pair_kind=variant,
                                base_interval=outputs[base_id].get(
                                    "risk_interval",
                                    outputs[base_id]
                                    .get("prediction", {})
                                    .get("risk_interval"),
                                ),
                                variant_interval=outputs[variant_id].get(
                                    "risk_interval",
                                    outputs[variant_id]
                                    .get("prediction", {})
                                    .get("risk_interval"),
                                ),
                                oracle_base_interval=oracle_rows[base_id][
                                    "risk_interval"
                                ],
                                oracle_variant_interval=oracle_rows[variant_id][
                                    "risk_interval"
                                ],
                            )
                        )
                        pairs[-1]["prefix_index"] = prefix_index
                    except (KeyError, MetricInputError, TypeError) as exc:
                        pairs.append(
                            {
                                "pair_kind": variant,
                                "metric_family": "DRI" if variant == "XD" else "SRI",
                                "status": "UNAVAILABLE",
                                "failure_code": f"PAIR_{type(exc).__name__.upper()}",
                            }
                        )
            truth_controls = {
                control.control_id: control.op for control in truth_sidecar.controls
            }
            disclosure_ops = {"EQUIVALENCE", "MERGE", "SUPERSEDE", "RETIRE"}
            disclosed = sorted(
                (
                    prefix
                    for prefix in prefixes.values()
                    if prefix.arm_id == "XD"
                    and any(
                        truth_controls.get(control.control_id) == control.op
                        and control.op in disclosure_ops
                        for control in prefix.controls
                    )
                ),
                key=lambda prefix: prefix.prefix_index,
            )
            recovery: dict[str, Any] = {
                "applicable": False,
                "reason": "NO_TRUTH_VALID_EFFECTIVE_DISCLOSURE",
                "prefixes": [],
            }
            if disclosed:
                disclosure_index = disclosed[0].prefix_index
                recovery_rows = []
                for prefix_index in indices:
                    if prefix_index < disclosure_index:
                        continue
                    prefix_id = prefix_coordinates.get(("XD", prefix_index))
                    method_output = outputs.get(prefix_id or "", {})
                    recovery_rows.append(
                        {
                            "prefix": prefix_index,
                            "method_interval": method_output.get(
                                "risk_interval",
                                method_output.get("prediction", {}).get(
                                    "risk_interval"
                                ),
                            ),
                            "oracle_interval": oracle_rows.get(prefix_id or "", {}).get(
                                "risk_interval"
                            ),
                        }
                    )
                recovery = {
                    "applicable": True,
                    **recovery_curve(
                        recovery_rows,
                        disclosure_prefix=disclosure_index,
                    ),
                }
            methods[str(method_id)] = {
                "terminal_state": method.get("terminal_state"),
                "prefix_scores": scored_prefixes,
                "response_pairs": pairs,
                "recovery": recovery,
                "resource_measurements": [
                    {
                        "prefix_id": str(_mapping(row).get("prefix_id", "")),
                        **dict(_mapping(row).get("measurements", {})),
                    }
                    for row in method.get("prefixes", [])
                    if isinstance(_mapping(row).get("measurements"), Mapping)
                ],
            }
        return {
            "schema_version": "1.0.0",
            "block_id": truth_sidecar.block_id,
            "scorer_truth_access": "AFTER_METHOD_TERMINALS",
            "methods": methods,
        }

    return scorer


__all__ = [
    "MetricInputError",
    "belief_l1",
    "interval_endpoint_error",
    "jousselme_distance",
    "recovery_curve",
    "score_actions",
    "make_runner_scorer",
    "score_block_prefixes",
    "score_method_prefix",
    "score_response_pair",
    "validate_bpa",
    "validate_interval",
]
