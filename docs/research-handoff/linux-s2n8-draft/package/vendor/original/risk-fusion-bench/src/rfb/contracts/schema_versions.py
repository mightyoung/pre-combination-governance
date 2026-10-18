"""Frozen semantic schema-version parsing and explicit compatibility."""

from __future__ import annotations

import re
from dataclasses import dataclass


_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


@dataclass(frozen=True, order=True)
class SemanticVersion:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_semantic_version(text: str) -> SemanticVersion:
    """Parse the frozen ``MAJOR.MINOR.PATCH`` syntax without prerelease/build."""

    if not isinstance(text, str):
        raise ValueError("semantic version must be a string")
    match = _SEMVER_RE.fullmatch(text)
    if not match:
        raise ValueError(f"invalid semantic version: {text!r}")
    return SemanticVersion(*(int(part) for part in match.groups()))


@dataclass(frozen=True)
class CompatibilityRegistry:
    """Explicit compatibility table.

    Compatibility is exact by default.  Non-exact compatibility is granted only
    by entries in ``compatible_references`` as
    ``(schema_name, expected_version, referenced_version)`` strings.
    """

    compatible_references: frozenset[tuple[str, str, str]] = frozenset()

    def is_compatible(
        self, schema_name: str, expected_version: str, referenced_version: str
    ) -> bool:
        parse_semantic_version(expected_version)
        parse_semantic_version(referenced_version)
        if expected_version == referenced_version:
            return True
        return (
            schema_name,
            expected_version,
            referenced_version,
        ) in self.compatible_references

    def with_reference(
        self, schema_name: str, expected_version: str, referenced_version: str
    ) -> "CompatibilityRegistry":
        parse_semantic_version(expected_version)
        parse_semantic_version(referenced_version)
        return CompatibilityRegistry(
            self.compatible_references
            | frozenset({(schema_name, expected_version, referenced_version)})
        )


EXACT_COMPATIBILITY = CompatibilityRegistry()
