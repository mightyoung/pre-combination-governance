"""Truth-isolation guards for formal method execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


class TruthIsolationError(ValueError):
    """A method-visible object contains forbidden oracle/raw material."""


_TOKENS = ("truth", "payload", "raw", "sidecar", "bytes", "oracle")


def _sensitive_text(value: str) -> bool:
    folded = value.casefold()
    return any(token in folded for token in _TOKENS)


def sanitize_observations(value: Any, path: str = "observations") -> Any:
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise TruthIsolationError(f"non-string key at {path}")
            if _sensitive_text(key):
                raise TruthIsolationError(f"sensitive key: {path}.{key}")
            out[key] = sanitize_observations(child, f"{path}.{key}")
        return out
    if isinstance(value, list | tuple):
        return [
            sanitize_observations(child, f"{path}[{index}]")
            for index, child in enumerate(value)
        ]
    if isinstance(value, bytes | bytearray | memoryview):
        raise TruthIsolationError(f"raw bytes at {path}")
    if isinstance(value, str) and _sensitive_text(value):
        raise TruthIsolationError(f"sensitive string at {path}")
    return value


@dataclass(frozen=True, slots=True)
class ScorerBinding:
    scorer_id: str
    score: Callable[[Any, Mapping[str, Any]], Mapping[str, Any]]

    def evaluate(self, truth: Any, output: Mapping[str, Any]) -> dict[str, Any]:
        if not self.scorer_id:
            raise TruthIsolationError("unregistered scorer")
        return dict(self.score(truth, dict(output)))
