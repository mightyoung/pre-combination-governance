"""Fail-closed validation for the paired CPU task's preregistered limits."""

from dataclasses import dataclass


REQUIRED_RESOURCE_FIELDS = (
    "cpu_quota_millis",
    "wall_seconds",
    "memory_bytes",
    "pids_limit",
    "max_method_output_bytes",
)

# Keep this cleanup reserve inside the registered wall budget. It bounds the
# Docker stop/remove requests after the method execution deadline has expired.
CLEANUP_RESERVE_SECONDS = 9


@dataclass(frozen=True)
class ResourceProfile:
    status: str
    missing_fields: tuple[str, ...]
    invalid_fields: tuple[str, ...]


def validate_resource_profile(manifest: dict) -> ResourceProfile:
    """Accept only explicit positive integer manifest values; never read env vars."""
    resources = manifest.get("resources")
    if not isinstance(resources, dict):
        return ResourceProfile("BLOCKED", REQUIRED_RESOURCE_FIELDS, ())

    missing = tuple(name for name in REQUIRED_RESOURCE_FIELDS if resources.get(name) is None)
    invalid = tuple(
        name for name in REQUIRED_RESOURCE_FIELDS
        if resources.get(name) is not None
        and (isinstance(resources[name], bool)
             or not isinstance(resources[name], int)
             or resources[name] <= 0)
    )
    if ("wall_seconds" not in missing and "wall_seconds" not in invalid
            and resources["wall_seconds"] <= CLEANUP_RESERVE_SECONDS):
        invalid = (*invalid, "wall_seconds")
    status = "BLOCKED" if missing or invalid else "READY"
    if status == "READY" and resources.get("cpu_quota_millis") != 1000:
        invalid = (*invalid, "cpu_quota_millis")
        status = "BLOCKED"
    return ResourceProfile(status, missing, invalid)
