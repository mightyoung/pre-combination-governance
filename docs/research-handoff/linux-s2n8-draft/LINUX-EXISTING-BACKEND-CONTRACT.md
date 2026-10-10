# Minimum contract for an existing approved Linux backend

This is a BLOCKED interface contract, not an environment qualification or backend implementation. No target Linux capability was inspected or changed in this static-only slice. No service/cgroup delegation, root key, runtime lock, watchdog or hard-resource backend is known to be available. Installing services, changing privileges/delegations or running qualification is outside this task.

## Pre-exec watchdog and ownership

The existing approved external supervisor must atomically acquire the one-attempt lease and start an independent deadline before it execs any Python controller/entry. The watchdog must cover interpreter/module startup, argument parsing, bootstrap/key FD reads, inventory/runtime hashing, actor/worker startup, response reads and cleanup. A controller-thread timer, a callback after inventory, PDEATHSIG, or an ordinary actor timeout does not satisfy this. A blocked bootstrap pipe or filesystem read must not prevent the supervisor terminating the complete owned scope and recording FAILED/UNKNOWN. If the platform cannot provide bounded termination/verified cleanup, it remains BLOCKED; a kill request alone is not cleanup proof.

Both current `main()` functions call the unconditional `require_hard_containment()` before parsing arguments or reading bootstrap/inventory. They exit with proposed code72. This prevents those reads in supported CLI startup while unprovisioned; it does not make Python/module startup independently time-bounded. The future external guardian must predate exec. The unconditional source block is retained and cannot be removed by metadata/signature.

`containment.ApprovedContainmentBackend` is an abstract interface only. `launch_under_existing_guard` belongs to an already-approved external service: it must establish watchdog and stable kernel ownership before controller exec. `verify_preexec_guard` verifies an authenticated ready receipt bound to the reviewed artifact digests, run identity, kernel scope identity, trusted origin/deadline and exact limits. The service must provide independently authenticated observations; actor JSON or the controller's own self-signed labels cannot establish guard readiness. No private key or delegation is provided here. `require_approved_backend()` always raises NOT_DELEGATED, and every abstract method raises if no implementation exists.

## Stable kernel containment and resource accounting

A target-specific backend may use an already delegated cgroup-v2 scope with an existing approved service guardian, or another already-approved kernel mechanism providing equivalent guarantees. None is assumed present. The backend must prove all conditions below before it is wired into a reviewed source change:

| Required condition | Minimum evidence / failure rule |
| --- | --- |
| Stable owned scope | Approved scope descriptor/identity is dedicated to one run and inherited across fork/reparent/reap. No unrelated process; descendants cannot migrate out. Process-group/tree scanning is diagnostic only. Unknown membership or reused identities blocks. |
| Complete cleanup | Kernel-owned membership covers escaped/orphaned descendants, with verified termination and emptiness within the cleanup deadline. Unknown enumeration, unkillable members, or unverifiable empty state is FAILED/UNKNOWN. |
| Single / aggregate memory | Already-approved kernel hard boundaries at or below512MiB single and2GiB complete cohort, including controller/guardian/startup/cleanup. Stricter kernel accounting may stop conservatively; RSS samples alone are insufficient. |
| Cumulative CPU | Enforce total60CPU seconds across guardian/controller/live/reaped/indirect descendants without resetting between phases. `cpu.max` limits bandwidth, not cumulative CPU, so alone is insufficient. State the actual existing mechanism, worst-case stop latency and reserve included in total; absent proof blocks. |
| Wall deadline | Independent supervisor enforces total120wall including pre-exec preparation/startup/probes/workers/cleanup; active114 and cleanup118 remain reserves within total, not separate allowances. Blocking reads cannot disable enforcement. |
| Data/output isolation | Existing namespace/seccomp capabilities must be qualified, no bare fallback. Readonly inputs/runtime/control; separate approved output, buffers and logs inside10MiB total. No network/fork/write escape or protected mount overlay. |
| Approved existing runtime | Exact binary/library/dependency hashes and architecture already available; no downloads/installs/sudo or permission changes. A differing namespace target layout needs a reviewed whitelist source change. |

No generic cgroup enable/setup commands are supplied, since permission and enforcement semantics must come from the target's existing approved service. Missing delegation or proof blocks; no writable OS state is manufactured by this code slice.

## Runtime mount target layout

Source-defined direct runtime roots are limited to `/opt/pcg-runtime/python`, `/opt/pcg-runtime/site`, `/opt/pcg-runtime/lib`. Runtime-only alias targets are exactly `/lib/x86_64-linux-gnu`, `/usr/lib/x86_64-linux-gnu`, `/lib64/ld-linux-x86-64.so.2`. Existing runtime installation is not presumed to match these paths. Normalized target ancestors/descendants conflict with fixed and prior mounts; protected `/control`, `/pkg`, `/run`, `/fixture`, `/proc`, `/dev`, `/home`, `/root`, `/tmp` cannot be shadowed. Noncanonical spelling, duplicates, unlisted targets and alias sources outside frozen roots reject. The runtime-lock cannot extend this whitelist. Source symlink/full-tree fingerprint enforcement remains in the existing runtime verifier.

## Slot13 evidence and remaining blocker

CPU increase alone has been removed as qualification logic. After observing the diagnostic CPU stop, slot13 requires `require_approved_backend`, then verifies a guardian-signed CPU receipt using the public key independently bound to the approved pre-exec grant. It uses trusted expected scope/child identities, the fresh run/fixture nonce (shared across slots), and the caller's already-approved run/artifact bindings; the signed body explicitly identifies slot12→13. A nonce alone is not slot freshness. No backend means BLOCKED, even with increasing CPU samples and a stop label.

`cpu_evidence.check_reaped_cpu_evidence` checks consistency of a controlled earlier reaped actor (expected slot12) and continuity through the next actor: stable kernel scope and fresh run/fixture nonce (shared by the16 slots); approved run and exact five artifact bindings; explicit reaped_slot12/current_slot13; PID/start ticks; positive measured wait4 CPU; confirmed child exit/cleanup and complete scope membership; chronological before-child/after-reap/after-next snapshots; monotonic kernel cumulative CPU, waited CPU/count and charged CPU; exact one-child wait credit; kernel and charged totals include at least that credit; credit persists across the next actor. The kernel counter and wait4 ledger have distinct declared provenance. Reaped-child cleanup refers to that controlled child, not emptiness of a scope that still includes controller/guardian.

These data consistency checks do not authenticate the source, implement a kernel collector or prove general hard CPU containment. Backend verification must independently authenticate real observations and expected identities; self-labelled JSON can satisfy arithmetic but never award qualification. The signed receipt and consistency summary are retained in the slot observation for audit; storing a summary alone is insufficient. The abstract backend key must derive from the authenticated pre-exec grant, not actor metadata or a caller-selected untrusted key. No actual collector/backend/watchdog is implemented, and no slot13 PASSED receipt can be produced by the supported draft. Slot11 also remains BLOCKED pending independent watchdog qualification.

## Scope and checks

Preserve all104 previous PR2 package artifacts and scientific/data bytes. Only control code/manifest and new review metadata change in this follow-up. New negative tests are WRITTEN NOT RUN. Static AST/JSON/schema/inventory/byte checks and independent review do not establish Linux execution success. No study, Action, key provisioning, permission change or installation occurred.
