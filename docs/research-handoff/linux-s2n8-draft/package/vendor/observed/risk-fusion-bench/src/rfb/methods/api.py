"""Compatibility-facing API layered over the closed registry implementation."""

from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping

from .models import MethodInput
from .registry import METHOD_IDS, MethodSpec, generate_registry_document as _document
from .registry import get_registry as _registry


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")


class _PublicSpec:
    def __init__(self, spec: MethodSpec) -> None:
        self._spec = spec

    def __getattr__(self, name: str) -> Any:
        return getattr(self._spec, name)

    def execute(self, observations: MethodInput | Mapping[str, Any]) -> dict[str, Any]:
        # 2026-07-23: the B2-only flat-mapping rewrite (which synthesized
        # lineage that was never in the input) has been removed; every method
        # receives the caller's observations unmodified.
        envelope = self._spec.execute(observations)
        envelope["scorer_binding"] = envelope["scorer_id"]
        envelope["result_sha256"] = hashlib.sha256(
            _canonical(
                {
                    key: value
                    for key, value in envelope.items()
                    if key != "result_sha256"
                }
            )
        ).hexdigest()
        return envelope


BUILTIN_REGISTRY: Mapping[str, _PublicSpec] = MappingProxyType(
    {method_id: _PublicSpec(spec) for method_id, spec in _registry().items()}
)


def get_registry() -> dict[str, _PublicSpec]:
    return dict(BUILTIN_REGISTRY)


def get_method(method_id: str) -> _PublicSpec:
    try:
        return BUILTIN_REGISTRY[method_id]
    except KeyError as exc:
        raise ValueError(f"unknown method_id: {method_id}") from exc


def run_method(
    method_id: str, observations: MethodInput | Mapping[str, Any]
) -> dict[str, Any]:
    return get_method(method_id).execute(observations)


def _validate(registry: Mapping[str, Any]) -> None:
    if tuple(registry) != METHOD_IDS or len(registry) != len(METHOD_IDS):
        raise ValueError("closed registry requires exactly B0-B5 and Proposed in order")


def run_all(
    observations: MethodInput | Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    selected = BUILTIN_REGISTRY if registry is None else registry
    _validate(selected)
    return {
        method_id: selected[method_id].execute(observations) for method_id in METHOD_IDS
    }


def generate_registry_document(
    registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    selected = BUILTIN_REGISTRY if registry is None else registry
    _validate(selected)
    return _document(
        {
            method_id: selected[method_id]._spec
            if isinstance(selected[method_id], _PublicSpec)
            else selected[method_id]
            for method_id in METHOD_IDS
        }
    )
