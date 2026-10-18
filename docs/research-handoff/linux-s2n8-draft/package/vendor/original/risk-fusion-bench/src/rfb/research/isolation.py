"""Structural isolation between method-visible events and scorer-only truth.

The two bundles share only an opaque, semantics-free join token.  A method
bundle cannot expose or accept scorer-only metadata, while the scorer bundle
cannot be converted into a method payload.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from rfb.contracts.canonical_json import canonical_bytes, sha256_hex


class MethodSideTruthAccessDenied(RuntimeError):
    """Raised when method-side code attempts to access scorer-only state."""


_DENIED_METHOD_ATTRIBUTES = frozenset(
    {
        "scorer_only_metadata",
        "scorer_only_sidecar",
        "scorer_truth_bundle",
        "truth_bundle",
        "truth_graph",
        "sidecar",
    }
)


def _opaque_join_token(bundle_id: str, observation_index: int) -> str:
    material = f"rfb-research-join-v1|{bundle_id}|{observation_index}".encode()
    return hashlib.sha256(material).hexdigest()


@dataclass(frozen=True)
class MethodEventBundle:
    bundle_id: str
    algorithm_seed: int
    events: tuple[Mapping[str, Any], ...]
    opaque_join_tokens: tuple[str, ...]

    def __getattr__(self, name: str) -> Any:
        if name in _DENIED_METHOD_ATTRIBUTES:
            raise MethodSideTruthAccessDenied(
                f"METHOD_SIDE_TRUTH_ACCESS_DENIED: {name}"
            )
        raise AttributeError(name)

    def to_run_all_payload(self) -> dict[str, Any]:
        """Return the exact, allowlisted payload accepted by the method panel."""
        return {
            "bundle_id": self.bundle_id,
            "algorithm_seed": self.algorithm_seed,
            "transaction_id": self.bundle_id,
            "events": [dict(event) for event in self.events],
        }


@dataclass(frozen=True)
class ScorerTruthBundle:
    bundle_id: str
    records: tuple[Mapping[str, Any], ...]
    complete: bool
    content_sha256: str

    def to_run_all_payload(self) -> dict[str, Any]:
        raise MethodSideTruthAccessDenied("SCORER_TRUTH_BUNDLE_NOT_METHOD_INPUT")

    def to_canonical_payload(self) -> dict[str, Any]:
        records = [_deep_thaw(record) for record in self.records]
        payload = {
            "bundle_id": self.bundle_id,
            "records": records,
            "complete": self.complete,
        }
        if sha256_hex(canonical_bytes(payload)) != self.content_sha256:
            raise ValueError("SCORER_TRUTH_BUNDLE_HASH_MISMATCH")
        return {**payload, "content_sha256": self.content_sha256}


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    return value


def _canonical_metadata(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        normalized = json.loads(canonical_bytes(dict(metadata)).decode("utf-8"))
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("SCORER_TRUTH_METADATA_NOT_CANONICAL_JSON") from exc
    if not isinstance(normalized, dict):
        raise TypeError("SCORER_TRUTH_METADATA_NOT_CANONICAL_JSON")
    return _deep_freeze(normalized)


def build_method_event_bundle(
    *,
    bundle_id: str,
    algorithm_seed: int,
    observations: Sequence[Any],
    bpa_mapper: Callable[[Any], Mapping[Any, Any]],
    prop_mask: int,
) -> MethodEventBundle:
    """Build method events exclusively from public observation fields.

    This function intentionally accepts neither a loader nor a sidecar.  The
    BPA mapper is the loader's public observation-to-BPA operation; reliability
    is read only from ``CanonicalObs.quality``.
    """
    events: list[Mapping[str, Any]] = []
    for index, observation in enumerate(observations):
        bpa = bpa_mapper(observation)
        if not isinstance(bpa, Mapping):
            raise TypeError("METHOD_VISIBLE_BPA_UNAVAILABLE")
        support = float(bpa.get(prop_mask, 0.0))
        quality = observation.quality
        if not isinstance(quality, Mapping):
            raise TypeError("METHOD_VISIBLE_QUALITY_UNAVAILABLE")
        reliability = float(quality.get("completeness", 1.0))
        if not math.isfinite(reliability) or not 0.0 <= reliability <= 1.0:
            raise ValueError("METHOD_VISIBLE_RELIABILITY_INVALID")
        event = MappingProxyType(
            {
                "message_id": f"tep-{index}",
                "version": 1,
                "root_id": f"tep-{index}",
                "support": support,
                "reliability": reliability,
                "lineage": [],
                "derived_from": [],
                "order": index,
            }
        )
        events.append(event)
    return MethodEventBundle(
        bundle_id=bundle_id,
        algorithm_seed=algorithm_seed,
        events=tuple(events),
        opaque_join_tokens=tuple(
            _opaque_join_token(bundle_id, index) for index in range(len(observations))
        ),
    )


def build_scorer_truth_bundle(
    *,
    bundle_id: str,
    sidecar: Sequence[Any],
    expected_count: int | None = None,
) -> ScorerTruthBundle:
    """Freeze scorer-only records without exposing a method-side capability."""
    if not sidecar:
        payload = {"bundle_id": bundle_id, "records": [], "complete": False}
        return ScorerTruthBundle(
            bundle_id=bundle_id,
            records=(),
            complete=False,
            content_sha256=sha256_hex(canonical_bytes(payload)),
        )
    if expected_count is not None and len(sidecar) != expected_count:
        raise ValueError("SCORER_TRUTH_BUNDLE_ALIGNMENT_INVALID")
    records: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    for fallback_index, record in enumerate(sidecar):
        index = getattr(record, "observation_index", fallback_index)
        metadata = getattr(record, "metadata", None)
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ValueError("SCORER_TRUTH_BUNDLE_INDEX_INVALID")
        if index in seen or (expected_count is not None and index >= expected_count):
            raise ValueError("SCORER_TRUTH_BUNDLE_ALIGNMENT_INVALID")
        if not isinstance(metadata, Mapping):
            raise TypeError("SCORER_TRUTH_BUNDLE_METADATA_INVALID")
        seen.add(index)
        records.append(
            MappingProxyType(
                {
                    "opaque_join_token": _opaque_join_token(bundle_id, index),
                    "metadata": _canonical_metadata(metadata),
                }
            )
        )
    complete = expected_count is None or len(records) == expected_count
    payload = {
        "bundle_id": bundle_id,
        "records": [_deep_thaw(record) for record in records],
        "complete": complete,
    }
    return ScorerTruthBundle(
        bundle_id=bundle_id,
        records=tuple(records),
        complete=complete,
        content_sha256=sha256_hex(canonical_bytes(payload)),
    )
