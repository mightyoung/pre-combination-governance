"""Non-confirmatory research execution primitives (R002).

This package deliberately has no dependency on the formal/admission lanes.
"""

from .models import CLASSIFICATION, emit_event
from .lock import ResearchLock, LockBusy, LockTombstoneError
from .adapters import registry, resolve_adapter
from .controller import (
    prepare_run,
    execute_remote,
    bind_downloaded_result,
    verify_remote_receipt,
    verify_final_receipt,
)
from .pinned_runtime import (
    PinnedRuntimeError,
    build_pinned_manifest,
    verify_pinned_manifest,
    verify_before_launch,
    verify_after_run,
)

__all__ = [
    "CLASSIFICATION",
    "emit_event",
    "ResearchLock",
    "LockBusy",
    "LockTombstoneError",
    "registry",
    "resolve_adapter",
    "prepare_run",
    "execute_remote",
    "bind_downloaded_result",
    "verify_remote_receipt",
    "verify_final_receipt",
    "PinnedRuntimeError",
    "build_pinned_manifest",
    "verify_pinned_manifest",
    "verify_before_launch",
    "verify_after_run",
]
