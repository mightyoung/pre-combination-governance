"""Stage-1 contract utilities for non-formal package validation.

This package is intentionally small and standard-library only.  It does not
open any formal experiment gate and it never creates formal admission artifacts.
"""

from .canonical_json import canonical_bytes, canonical_text, sha256_bytes, sha256_hex
from .failure_codes import FailureCode, primary_failure_code
from .package_validator import PackageValidationResult, validate_and_commit_package
from .schema_versions import (
    SemanticVersion,
    CompatibilityRegistry,
    parse_semantic_version,
)
from .schemas import SchemaValidationResult, validate_schema

__all__ = [
    "CompatibilityRegistry",
    "FailureCode",
    "PackageValidationResult",
    "SchemaValidationResult",
    "SemanticVersion",
    "canonical_bytes",
    "canonical_text",
    "parse_semantic_version",
    "primary_failure_code",
    "sha256_bytes",
    "sha256_hex",
    "validate_and_commit_package",
    "validate_schema",
]
