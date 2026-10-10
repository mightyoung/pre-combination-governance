"""Immutable public method inputs and their closed JSON parser."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class MethodInputError(ValueError):
    """The method-visible input violates the public contract."""


class ControlKind(str, Enum):
    EQUIVALENCE = "EQUIVALENCE"
    SUPERSEDE = "SUPERSEDE"
    MERGE = "MERGE"
    RETIRE = "RETIRE"
    REPLAY = "REPLAY"


@dataclass(frozen=True, slots=True)
class PublicEvent:
    message_id: str
    version: int
    root_id: str
    support: float
    reliability: float = 1.0
    lineage: tuple[str, ...] = ()
    derived_from: tuple[str, ...] = ()
    order: int = 0


@dataclass(frozen=True, slots=True)
class PublicControl:
    kind: ControlKind
    roots: tuple[str, ...]
    canonical_root: str | None = None
    replacement_root: str | None = None
    order: int = 0


@dataclass(frozen=True, slots=True)
class MethodInput:
    bundle_id: str
    algorithm_seed: int
    transaction_id: str
    events: tuple[PublicEvent, ...]
    controls: tuple[PublicControl, ...] = ()


_FORBIDDEN = ("truth", "raw", "payload", "sidecar", "hash")


def _json_only(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not value == value or value in (float("inf"), float("-inf")):
            raise MethodInputError(f"{path}: non-finite number")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _json_only(child, f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise MethodInputError(f"{path}: keys must be strings")
            if any(part in key.casefold() for part in _FORBIDDEN):
                raise MethodInputError(f"{path}.{key}: forbidden field")
            _json_only(child, f"{path}.{key}")
        return
    raise MethodInputError(f"{path}: non-JSON value")


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise MethodInputError(f"{path}: non-empty string required")
    return value


def _texts(value: Any, path: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise MethodInputError(f"{path}: array required")
    return tuple(_text(item, f"{path}[{index}]") for index, item in enumerate(value))


def _probability(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MethodInputError(f"{path}: number required")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise MethodInputError(f"{path}: value must be in [0, 1]")
    return result


def _event(row: Mapping[str, Any], index: int) -> PublicEvent:
    allowed = {
        "message_id",
        "version",
        "root_id",
        "support",
        "reliability",
        "lineage",
        "derived_from",
        "order",
    }
    if set(row) - allowed:
        raise MethodInputError(f"$.events[{index}]: unknown fields")
    version, order = row.get("version", 1), row.get("order", index)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise MethodInputError("event version must be positive integer")
    if isinstance(order, bool) or not isinstance(order, int) or order < 0:
        raise MethodInputError("event order must be non-negative integer")
    return PublicEvent(
        _text(row.get("message_id"), "message_id"),
        version,
        _text(row.get("root_id"), "root_id"),
        _probability(row.get("support"), "support"),
        _probability(row.get("reliability", 1.0), "reliability"),
        _texts(row.get("lineage"), "lineage"),
        _texts(row.get("derived_from"), "derived_from"),
        order,
    )


def _control(row: Mapping[str, Any], index: int) -> PublicControl:
    allowed = {"kind", "roots", "canonical_root", "replacement_root", "order"}
    if set(row) - allowed:
        raise MethodInputError(f"$.controls[{index}]: unknown fields")
    try:
        kind = ControlKind(_text(row.get("kind"), "kind").upper())
    except ValueError as exc:
        raise MethodInputError("unknown control kind") from exc
    roots, order = _texts(row.get("roots"), "roots"), row.get("order", index)
    if not roots or isinstance(order, bool) or not isinstance(order, int) or order < 0:
        raise MethodInputError("control roots/order invalid")
    canonical, replacement = row.get("canonical_root"), row.get("replacement_root")
    return PublicControl(
        kind,
        roots,
        None if canonical is None else _text(canonical, "canonical_root"),
        None if replacement is None else _text(replacement, "replacement_root"),
        order,
    )


def parse_method_input(value: MethodInput | Mapping[str, Any]) -> MethodInput:
    if isinstance(value, MethodInput):
        return value
    _json_only(value)
    if not isinstance(value, Mapping):
        raise MethodInputError("input must be a JSON object")
    if "events" not in value:
        # 2026-07-23: the legacy flat-mapping path that silently synthesized a
        # "fixture-bundle" MethodInput has been closed; callers must provide
        # structured public events.
        raise MethodInputError("structured public events are required")
    allowed = {"bundle_id", "algorithm_seed", "transaction_id", "events", "controls"}
    if set(value) - allowed:
        raise MethodInputError("unknown top-level fields")
    rows, controls, seed = (
        value["events"],
        value.get("controls", []),
        value.get("algorithm_seed", 0),
    )
    if not isinstance(rows, list) or not rows or not isinstance(controls, list):
        raise MethodInputError("events/controls arrays invalid")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise MethodInputError("algorithm_seed invalid")
    return MethodInput(
        _text(value.get("bundle_id", "development-bundle"), "bundle_id"),
        seed,
        _text(value.get("transaction_id", "development-transaction"), "transaction_id"),
        tuple(_event(row, i) for i, row in enumerate(rows)),
        tuple(_control(row, i) for i, row in enumerate(controls)),
    )
