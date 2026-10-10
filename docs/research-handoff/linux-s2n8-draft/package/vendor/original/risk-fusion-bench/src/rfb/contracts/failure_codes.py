"""Closed failure-code registry for stage-1 package validation."""

from __future__ import annotations

from enum import Enum
from types import MappingProxyType
from typing import Iterable


class FailureCode(str, Enum):
    FILE_MISSING = "FILE_MISSING"
    HASH_MISMATCH = "HASH_MISMATCH"
    STALE_VERSION_REFERENCE = "STALE_VERSION_REFERENCE"
    SCHEMA_INCOMPATIBLE = "SCHEMA_INCOMPATIBLE"
    DEPENDENCY_CYCLE = "DEPENDENCY_CYCLE"
    MISSING_DEPENDENCY_ENDPOINT = "MISSING_DEPENDENCY_ENDPOINT"
    CONFIRMATION_PENDING_HASH = "CONFIRMATION_PENDING_HASH"
    MANIFEST_SCHEMA_INVALID = "MANIFEST_SCHEMA_INVALID"
    D_TEST_FORBIDDEN = "D_TEST_FORBIDDEN"
    OUTPUT_ALREADY_EXISTS = "OUTPUT_ALREADY_EXISTS"
    PACKAGE_CONSISTENCY_INVALID = "PACKAGE_CONSISTENCY_INVALID"


PRIMARY_ORDER: tuple[FailureCode, ...] = (
    FailureCode.D_TEST_FORBIDDEN,
    FailureCode.OUTPUT_ALREADY_EXISTS,
    FailureCode.MANIFEST_SCHEMA_INVALID,
    FailureCode.FILE_MISSING,
    FailureCode.HASH_MISMATCH,
    FailureCode.SCHEMA_INCOMPATIBLE,
    FailureCode.STALE_VERSION_REFERENCE,
    FailureCode.MISSING_DEPENDENCY_ENDPOINT,
    FailureCode.DEPENDENCY_CYCLE,
    FailureCode.CONFIRMATION_PENDING_HASH,
    FailureCode.PACKAGE_CONSISTENCY_INVALID,
)

FAILURE_CODE_REGISTRY = MappingProxyType({code.value: code for code in FailureCode})


def enumerate_failure_codes() -> tuple[str, ...]:
    """Return stable, duplicate-free code strings."""

    return tuple(code.value for code in FailureCode)


def primary_failure_code(codes: Iterable[FailureCode | str]) -> FailureCode | None:
    """Choose the deterministic primary code from an unordered failure set."""

    normalized = {
        code if isinstance(code, FailureCode) else FailureCode(code) for code in codes
    }
    for code in PRIMARY_ORDER:
        if code in normalized:
            return code
    return None


PACKAGE_CONFLICT_CODE = FailureCode.PACKAGE_CONSISTENCY_INVALID
