"""Immutable event model and categorical input rejection."""

from __future__ import annotations
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4
import re

CLASSIFICATION = {
    "execution_lane": "RESEARCH",
    "classification": "DEVELOPMENT_NONCONFIRMATORY",
    "formal_gate_effect": "NONE",
    "formal_admission_eligible": False,
    "shk001b_eligible": False,
    "contains_formal_claims": False,
}
CLASSIFICATION_KEYS = frozenset(CLASSIFICATION)
_FORBIDDEN = re.compile(
    r"(?:raw\s+dataset|truth\s+(?:label|data)|ssh[_ -]?password|(?:api|access|secret)[_ -]?key|(?:[A-Za-z]:[\\/]|/)(?:[^\s]+[\\/])+[^\s]+)",
    re.I,
)


def reject_categorical(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for k, v in value.items():
            reject_categorical(k, f"{path}.<key>")
            reject_categorical(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple, set)):
        for i, v in enumerate(value):
            reject_categorical(v, f"{path}[{i}]")
    elif isinstance(value, str) and _FORBIDDEN.search(value):
        raise ValueError(
            f"{path}: raw/truth/credential/source-path categorical value rejected"
        )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_freeze(v) for v in value)
    return value


def validate_classification(value: Mapping[str, Any], *, exact: bool = True) -> None:
    keys = set(value)
    if exact and keys != CLASSIFICATION_KEYS:
        raise ValueError("classification subset must contain exactly six fields")
    if not exact and not CLASSIFICATION_KEYS <= keys:
        raise ValueError("missing immutable classification field")
    for key, expected in CLASSIFICATION.items():
        if value.get(key) != expected:
            raise ValueError(f"immutable classification mismatch: {key}")


def emit_event(
    *, kind: str, payload: Mapping[str, Any] | None = None, event_id: str | None = None
) -> Mapping[str, Any]:
    if not isinstance(kind, str) or not kind:
        raise ValueError("kind must be non-empty")
    if payload is not None:
        reject_categorical(payload)
    body = {
        "event_id": event_id or str(uuid4()),
        "kind": kind,
        "payload": dict(payload or {}),
    }
    body.update(CLASSIFICATION)
    return _freeze(body)
