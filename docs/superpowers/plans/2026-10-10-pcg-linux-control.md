# PCG Linux Fail-Closed Control Implementation Plan

> For agentic workers: use inline executing-plans; one fresh-context whole-branch static review. User authorization overrides test execution: write tests but do not run/import control code, probes or workers this round.

**Goal:** Implement an auditable Linux launcher/qualification/resource control candidate without changing scientific bytes or granting execution.

**Architecture:** A trusted platform provisions a reviewed Ed25519 approval public key and exact Linux runtime lock; defaults remain unresolved/blocked. A signed once-only grant binds package/control/runtime/profile/plan and a per-run session public key. Controller signs actual 16 receipts and worker capabilities with the corresponding private key supplied via FD. The only supported worker entry verifies the chain before installing a narrower seccomp policy and invoking unchanged scientific code; it replaces only the imported authorization gate, never science logic.

**Tech Stack:** Python3.12 standard library, existing cryptography/jsonschema/psutil, existing bubblewrap, Linux x86_64 seccomp BPF. No installation, sudo/sysctl changes or namespace fallback. Other architectures explicitly blocked pending reviewed syscall maps.

**Spec:** docs/research-handoff/linux-s2n8-draft/LINUX-ADAPTER-AND-QUALIFICATION-DRAFT.md and current user static-only instruction.

## Global Constraints
- Preserve all original/observed scientific source, input, reference and schedule bytes from PR2 0b766c963f2da8c1edeece167e3062a72ab5ad74.
- Add missing package/contracts/qualification.schema.json; refreeze package inventory, not science.
- 120wall/60CPU cumulative including preflight/probes/controller/workers/cleanup; 25wall worker; 512MiB single/2GiB RSS sum;10MiB output;45wall/8CPU/1MiB probe sublimit;2CPU fork reserve inside total.
- Fresh16 actors/max2 control children; exact ES→Proposed warmup,2ACK/6checkpoint; failure stop/no retry.
- Source/JSON/schema/AST/YAML checks only; tests written NOT RUN; do not install/dispatch/merge.
- No raw logs/permits/runtime/private keys/host paths published; unresolved trust key/runtime fingerprint explicitly blocks actual execution.

## Review Focus
1. An unsigned static permit/PASSED string must not bypass session signatures, receipt identities or required16 checks.
2. An unreadable owned procfs domain/reused PID/orphan group is UNKNOWN/FAILED, never cleanup PASS.
3. Actor reaping must not lose CPU; output buffers/pending frames/receipts included with cleanup reserve; CPU highwater no reset.
4. Namespace/seccomp/mount capability failure blocks, no bare launch; worker cannot access sidecar/reference/host home or spawn/write/network.
5. Preserved raw worker does not enforce qualification when manually run on a trusted host: only the qualified entry is supported; do not claim protection against an arbitrary host owner.

### Task1: Authorization, complete schemas and runtime lock
- Create auth.py/runtime.py/model.py; consume signed exact bindings, frozen trust/runtime policy; produce verified Approval and Runtime dataclasses.
- Write negative signature/replay/hash/schema/empty-lock tests; no execution this round.
- Add complete qualification schema at referenced package path; preserve original contracts.py; manifest update only.

### Task2: Profile and seccomp
- Create isolation.py/seccomp.py/entry.py; consume Runtime, Approval, session-signed capability; produce bwrap argv and sealed FD resources.
- Keep fixed allowlist mounts, no inputs/reference/sidecar mounts; readonly root plus write/fork/network/exec denial after bootstrap.
- Write argv/architecture/openflags/unsupported-capability tests; no probe launch.

### Task3: Cumulative supervision/cleanup
- Create budget.py; consume process registration and monotonic origin; produce highwater usage, soft-stop reasons, bounded receipts and cleanup evidence.
- Track owned tree identities, waited CPU, buffers, output bytes; lower-threshold stops use same reasons callbacks as production; any uncertainty blocks.
- Write CPU transition/access-denied/cleanup/deadline/output-reserve tests; no running suite.

### Task4: 16 actors and launcher
- Create actor.py/probes.py/launcher.py; exact16 frozen Linux slots and permitted control children; no research import in actors.
- Grant→runtime→profile→16 signatures→qualification→one sequential2-worker batch. Input checkpoints through supervised pipes; bounded response gates/science/reference/observer remain unchanged.
- Write case expectations, raw fake permit, stale qualification and missing runtime/root tests; no actors/workers run.

### Task5: Static review and draft publication
- AST/JSON/schema/YAML/bash syntax, file allowlist and scientific hash comparisons only.
- One independent fresh reviewer of whole control branch. Fix substantive issues statically, keep untested labels; no claims of test/qualification PASS.
- New task branch from PR2, draft PR against its branch; immutable receipts in future outputs only, not publication. No main/workflow dispatch.
