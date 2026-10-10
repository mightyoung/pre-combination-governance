"""Mandatory source-level block until independent kernel containment is implemented.

Neither signed approvals nor mutable metadata can override this draft boundary.
The sampling ledger is diagnostic only: it cannot establish a hard RSS bound,
complete escaped/orphan ownership, or an independently enforced wall deadline.
"""
from model import Blocked

UNIMPLEMENTED_BOUNDARIES=(
    'kernel_enforced_single_and_aggregate_memory_containment',
    'stable_descendant_membership_and_complete_cleanup',
    'independent_wall_and_cumulative_CPU_watchdog',
)

def require_hard_containment():
    raise Blocked('UNIMPLEMENTED_HARD_CONTAINMENT_BOUNDARY:'+','.join(UNIMPLEMENTED_BOUNDARIES))
