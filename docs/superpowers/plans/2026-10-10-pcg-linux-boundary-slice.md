# PR3 follow-up boundary slice (static only)

Baseline: d8b4eeee960207ac25777d62fb21bd2669e538b8. Preserve all104 PR2 package rows/scientific/data bytes. Separate branch/draft PR; no main/Actions/install/runtime changes. Tests NOT RUN.

1. Whitelist runtime-only mount targets; normalize before ancestor/descendant conflict checks; refuse protected-path overlays from aliases and direct roots. Write negative cases for entry/worker/runtime-lock, normalized aliases, duplicates and ancestor/descendant conflicts.
2. Reject entry startup before bootstrap FD/argument/inventory reads. Keep unconditional require_hard_containment. Specify existing approved external watchdog that starts before process exec and covers startup/blocking reads; no controller-thread timer presented as independent watchdog.
3. Replace slot13 CPU-increase heuristic with strict evidence checks: stable same kernel scope, identified reaped actor, measured child wait CPU, chronological cumulative kernel snapshots, retained credit, complete membership/cleanup, authenticated backend prerequisite. Missing evidence BLOCKED. Do not call this full kernel accounting qualification.
4. Describe minimum existing approved Linux containment interface; no delegated backend/guard means BLOCKED. Stable process ownership and kernel hard memory/aggregate CPU enforcement required, psutil scanning and cpu.max alone insufficient. Do not manufacture backend.
5. Static AST/JSON/schema/source-order and preserved-byte comparisons; one fresh independent whole-slice reviewer. Publish separate commit/draft and read back remote blobs. All tests/probes/science remain unexecuted.
