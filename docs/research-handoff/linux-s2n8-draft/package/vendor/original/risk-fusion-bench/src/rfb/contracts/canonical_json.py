"""Canonical JSON and SHA-256 helpers.

The canonical form is UTF-8 without BOM, insignificant whitespace, or trailing
newline. Mapping keys are sorted by their encoded UTF-8 bytes; JSON array order
and Unicode scalar values are preserved.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any


class CanonicalJsonError(ValueError):
    """Raised when a value cannot be represented as canonical JSON."""


def _reject_lone_surrogate(value: str, path: str) -> None:
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise CanonicalJsonError(f"{path}: lone surrogate is not canonical JSON")


def _quote_string(value: str, path: str) -> str:
    _reject_lone_surrogate(value, path)
    try:
        return json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
    except UnicodeEncodeError as exc:  # pragma: no cover - defensive normalization
        raise CanonicalJsonError(
            f"{path}: string is not valid Unicode scalar JSON"
        ) from exc


def _encode(value: Any, path: str) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _quote_string(value, path)
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalJsonError(f"{path}: NaN and Infinity are not canonical JSON")
        return json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
    if isinstance(value, Mapping):
        items: list[tuple[str, Any]] = []
        for key, child in value.items():
            if not isinstance(key, str):
                raise CanonicalJsonError(f"{path}: mapping key {key!r} is not a string")
            _reject_lone_surrogate(key, f"{path}.<key>")
            items.append((key, child))
        items.sort(key=lambda item: item[0].encode("utf-8"))
        return (
            "{"
            + ",".join(
                f"{_quote_string(key, f'{path}.{key}.<key>')}:{_encode(child, f'{path}.{key}')}"
                for key, child in items
            )
            + "}"
        )
    if isinstance(value, list):
        return (
            "["
            + ",".join(
                _encode(child, f"{path}[{idx}]") for idx, child in enumerate(value)
            )
            + "]"
        )
    raise CanonicalJsonError(
        f"{path}: unsupported non-JSON type {type(value).__name__}"
    )


def canonical_text(value: Any) -> str:
    """Return canonical JSON text for *value*."""

    try:
        return _encode(value, "$")
    except RecursionError as exc:
        raise CanonicalJsonError(
            "$: cyclic or too deeply nested JSON value is not canonical JSON"
        ) from exc


def canonical_bytes(value: Any) -> bytes:
    """Return canonical JSON encoded as UTF-8 bytes without BOM or newline."""

    try:
        return canonical_text(value).encode("utf-8")
    except UnicodeEncodeError as exc:  # pragma: no cover - defensive normalization
        raise CanonicalJsonError(
            "canonical JSON contains invalid Unicode scalar value"
        ) from exc


def sha256_hex(data: bytes | str) -> str:
    """Return the SHA-256 hex digest for bytes or UTF-8 text."""

    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha256_bytes(data: bytes | str) -> bytes:
    """Return the raw SHA-256 digest bytes for bytes or UTF-8 text."""

    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).digest()
