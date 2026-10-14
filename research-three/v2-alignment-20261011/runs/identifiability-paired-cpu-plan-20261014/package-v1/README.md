# Paired CPU package v1

This is the software package for `PCG-IDENTIFIABILITY-PAIRED-CPU-001`. It
implements the fixed A/B/C/D input transformation, a one-prefix method adapter,
an inspected local Docker runner, append-only slot output, an oracle-blind
freeze step, a separate scorer, and a returned-bundle validator.

## Status

`TASK_MANIFEST.json` is intentionally `BLOCKED_MISSING_VALUES`. The plan fixes
one serial CPU (`cpu_quota_millis=1000`), but it does not specify the maximum
wall time, memory, PID count, or cumulative method stdout/stderr bytes. Those
four values must be preregistered before any method starts. The runner ignores
environment variables and fails before reserving a run directory when a value
is missing or invalid. Do not copy the limits used by any earlier Docker smoke
check into the study manifest.

This package has not executed the 80 planned method-prefix slots. The only
method-runner tests inject a test-only callable into the adapter. The old
1,464-check Mac V3-RSS failure and its original metrics are not modified or
re-evaluated here. A completed software execution would still be a synthetic
mechanism diagnostic, not production accuracy or safety evidence.

The complete private Mac V2 contract is not present in this checkout. To claim
that private-contract alignment, provide the exact-version unabridged main
specification, every referenced field/schema and metric-definition file, and
the version/revision manifest or authority record. Together they must define
the exact output contract, metric formulas and denominators, and scenario
identity/truth rules. This package does not infer those missing terms.

## Fixed inputs and oracle boundary

The method-visible rows are generated from the pinned public input and the
opaque IDs in `CASE_BINDINGS.json`. A and B are required to be byte-identical;
C and D change only the boundary evidence on row `e`. The runtime receives
only `{method, prefix, old}` for its current prefix. It has no case ID, arm
label, future row, scorer import, truth map, or oracle mount. The private
`scorer_source/ORACLE_CASE_MAP.json` and `oracle.physical.json` are read only by
the separate scorer after `OUTPUT_FREEZE.json` and every slot hash verify.
The runner stops and preserves a partial bundle on the first A/B input or output
mismatch. The scorer independently checks all corresponding A/B slots and
requires the exact A→I1, B/C/D→I2 mapping pinned by the review plan.
The retained `independent_reference.py`, `scoring.py`, and
`offline_evaluator.py` files in `scorer_source/` are pinned public provenance
snapshots only; the new scorer does not import them, and the method container
never mounts that directory.

The plan is fixed at four opaque cases, five prefixes, and methods M0–M3:
80 method-prefix invocations total. Cases, prefixes, and invocations are
repeated software observations, not independent statistical samples. M0 and
its expected behavior remain unchanged.

## Isolation and resource enforcement

The runner uses only a preinstalled Docker CLI and a local Unix Docker socket.
It blocks unless the daemon reports Linux cgroup v2, builtin/default seccomp,
CPU quota, memory, swap, and PID controls. It builds an offline `FROM scratch`
image from the checked-in empty root filesystem. For each slot, it creates a fresh container,
inspects its configuration before start, and rejects any mismatch in the
pre-registered CPU/memory/PID caps, network mode, read-only root, capabilities,
user, command, environment, cgroup namespace, UTS namespace, or read-only bind
allowlist. It requests private cgroup namespace mode and verifies that UTS is
not shared with the host. It never mounts the
task manifest, pair-input file, case bindings, oracle, or scorer into the method
container.

Daemon `info` and stopped-container inspection are only preliminary checks.
Before `--preflight-only` can return `READY`, or before `run_task` can reserve a
run directory or start a method, the runner also executes the fixed
`fixed-network-cgroup-oom-v1` qualification probe in separate disposable
containers. Its diagnostic container checks that a random `/tmp` canary is
unreadable, a TEST-NET connection is unavailable, and the effective cgroup CPU,
memory and PID limits match the registered values. Since Docker's registered
memory-plus-swap value equals the memory cap, cgroup v2 must report
`memory.swap.max=0` (swap disabled). A second container
uses a fixed 64 MiB memory cap, emits a start marker, then deliberately exceeds
that cap; the runner requires Docker to report an OOM kill and a stopped
container. Both probe containers must pass the same inspected security config,
be removed, and be absent on a follow-up inspect. Any missing, malformed,
unrun, or failed check blocks readiness. The diagnostic Python runtime requires
at least 64 MiB in the task's memory limit.

The qualification code binds only the active Python prefix, the exact host
library directories used by that interpreter, and (for method slots) the exact
frozen method runtime directory. Resolved ancestor/descendant overlaps with the
package are rejected, so placing this package under `sys.prefix`, `/lib`, or
`/usr/lib` blocks before a container starts. A `VERIFIED` report records the
probe ID, script SHA-256, image ID, resource values, container states, kill
result, and cleanup confirmation. No probe was run in this development
environment; unit tests use synthetic reports and mocks.

The `wall_seconds` deadline starts before Docker setup and ends after sandbox
image cleanup. It caps the sandbox lifecycle; frozen-bundle finalization runs
after that boundary. The attempt receipt records this value as
`wall_seconds_elapsed` with scope `sandbox_lifecycle_through_image_cleanup`;
its `finished_at_utc` is the same sandbox-cleanup boundary.
The CLI summary also reports `attempt_wall_seconds_elapsed`, which includes
bundle finalization and the runner's final session cleanup; it does not change
the task's wall-cap decision. Docker CLI call timeouts are clamped to the
applicable deadline. Method execution stops 9 seconds before
the registered wall limit, reserving that time for bounded container kill and
forced removal and sandbox image cleanup; `wall_seconds` must therefore be at least 10. A timed-out slot
is always `FAIL`, with start status marked unknown if it could not be inspected.
The receipt records cleanup failures; a stopped container cannot be claimed if
the local daemon did not confirm removal.
The output cap bounds retained method stdout/stderr and
stops a slot when the cumulative cap is crossed; the receipt separately records
bytes captured and bytes observed while stopping the process. Docker enforces
the requested CPU, memory/swap, and PID cgroup limits. Peak RSS and CPU seconds
remain `UNKNOWN` because this runner does not claim a per-container sampler.
Missing kernel controls or an inspected-container mismatch block execution.

## Commands

Run the preflight on the intended Linux compute host after the resource profile
has been completed and reviewed:

```sh
python3 -I runner.py --task-manifest TASK_MANIFEST.json --preflight-only
```

`--preflight-only` creates and removes the offline scratch image and starts only
the fixed qualification containers; it does not create a run directory or start
a research method. The current manifest is expected to return `BLOCKED` until
the four resource values are supplied. To run the plan later, use a new unique run ID and a fresh output
directory; one run ID gets one attempt and cannot be retried or overwritten:

```sh
python3 -I runner.py \
  --task-manifest TASK_MANIFEST.json \
  --run-id <unique-run-id> \
  --output-root ./returns
```

The execution command leaves the oracle untouched. After `task_status=PASS` and
an output freeze exist, a separate scorer invocation can open the oracle:

```sh
python3 -I scorer.py \
  --bundle ./returns/<unique-run-id> \
  --task-manifest TASK_MANIFEST.json \
  --oracle scorer_source/oracle.physical.json \
  --oracle-case-map scorer_source/ORACLE_CASE_MAP.json \
  --score-output ./returns/<unique-run-id>/score.json

python3 -I return_validator.py \
  --bundle ./returns/<unique-run-id> \
  --score ./returns/<unique-run-id>/score.json
```

Before scoring, `return_validator.py` validates the typed attempt schema,
registered resource values and usage, qualification evidence, every child
start/exit/cleanup state, and the exact path/byte-count/SHA-256 of all declared
artifacts. Started slots must have both log files. It rejects unknown starts,
failed cleanup, missing caps, over-limit complete runs, and boolean values in
integer fields. For a complete return, `return_validator.py` reruns the deterministic scorer
against the frozen bundle and the supplied/default pinned manifest, oracle, and
case map, then compares the full score receipt. Matching copied IDs and hashes
alone cannot certify a score.

The scorer preserves first-alert and physical-notification results separately,
reports pending/rejected event pairs instead of counting them as correct,
keeps production truth denominator at zero, and marks delivery `NOT_DELIVERED`.
An execution `PASS` remains independent of research acceptance `TRUE` or
`FALSE`. An interrupted attempt is preserved with actual counts and a stop
reason and remains `NOT_EVALUATED`.

## Development tests

From the repository root, run only this package's isolated standard-library
tests:

```sh
python3 -I -B -m unittest discover \
  -s research-three/v2-alignment-20261011/runs/identifiability-paired-cpu-plan-20261014/package-v1/tests \
  -v
```

The tests use generated dictionaries, opaque IDs, fake oracle fixtures, and a
test-only method callable. They do not run the original trial, any frozen
research method, a new 80-slot run, model/network service, Mac workload, or
executor-qualification probe.

The 2026-10-14 isolated test counts and supplemental regression-harness limits
are recorded in [QUALIFICATION_RETURN_TEST_RESULTS_20261014.json](QUALIFICATION_RETURN_TEST_RESULTS_20261014.json).
The result-driven alert-evaluation revision, including the preserved Mac trial
failure and the missing V2-spec freeze boundary, is recorded in
[`RESULT_DRIVEN_ALERT_EVALUATION_REVISION_20261014.md`](../../../RESULT_DRIVEN_ALERT_EVALUATION_REVISION_20261014.md).
