# PCG CPU replay handoff: V2 two-hop lineage

**Task ID:** `PCG-LINEAGE-CPU-REPLAY-001`  
**Status:** `READY_FOR_REPRODUCIBILITY_CHECK`  
**Evidence class:** software/mechanics reproducibility only; not a new experiment.

## Decision and limits

This task needs CPU only. The runner is deterministic Python/JSON/SHA-256 and
the local source-lineage contract; it loads no model, weights, GPU runtime,
notification adapter, or paid service. It does not expand the scientific
design: one existing synthetic world, the same three related pair rows, no
new pairs, no parameter search, and no production-accuracy estimate.

This is a repeatability check of V2, which has already run in the research
branch. It must not replace the historical V1 or V2 result. Run in a disposable
checkout and return the new run under a separate run ID. The previously failed
1,464-check Mac trial, real-device execution, and executor qualification are
out of scope.

## Pinned code and data

- Repository: `mightyoung/pre-combination-governance`.
- Runner base commit: `c969913eacb56cda1236009ffa9390bd6f62cd3c` on
  `task/research-three-two-hop-lineage-20261012`. This is the immutable commit
  containing the V2 runner and frozen inputs; record the full commit used.
- Existing entry points:
  - `PYTHONPATH=risk-fusion-bench/src python research-three/v2-alignment-20261011/runs/two-hop-lineage-controlled-synthetic-20261012-v2/run_two_hop_lineage_v2.py`
  - `PYTHONPATH=risk-fusion-bench/src python research-three/v2-alignment-20261011/runs/two-hop-lineage-controlled-synthetic-20261012-v2/score_two_hop_lineage_v2.py`
- After returning the files in a separate task-run folder, validate the bundle
  from the repository root with:
  `PYTHONPATH=risk-fusion-bench/src python -m rfb.research.user_cpu_replay_handoff --bundle-dir research-three/v2-alignment-20261011/runs/user-cpu-replay-<UTC timestamp>-<run-id>`
- The returned `TASK_RESULT.json` must follow
  [USER_CPU_REPLAY_RESULT_V1.schema.json](USER_CPU_REPLAY_RESULT_V1.schema.json).
  The validator checks the result artifact hashes, both frozen manifests, all
  16 runner checks, the fixed pair counts, and the explicit `NOT_COMPUTABLE`
  production-accuracy fields. It uses the Python standard library only.
- [MAC_PERSISTENCE_MANIFEST_USER_CPU_REPLAY_V1.json](MAC_PERSISTENCE_MANIFEST_USER_CPU_REPLAY_V1.json)
  lists the cloud-branch handoff files with repository-relative paths for a
  future Mac checkout. Its `copy_status` is `NOT_COPIED_BY_THIS_RUN` and its
  Mac project root is null; do not interpret cloud paths as Mac-local paths.
- Python: `>=3.11`, using the checkout and Python standard library; no package
  installation is required.
- Input: repository file
  `research-three/v2-alignment-20261011/source-audit/usgs-summary-20261011/REAL_PUBLIC_FEED_SAMPLE.json`,
  exactly 2,537 bytes, SHA-256
  `9bfbd8a6600deb0c230fea2294f3673a2c726e5c8285687cb9531cd88a64d599`.
  `PRE_RUN_MANIFEST_V2.json` pins the method code/protocol/input; the separate
  `SCORER_TRUTH_MANIFEST_V2.json` pins the scorer-side synthetic fixture.
- Download/license: no dataset download is needed for this replay. Use only
  the checked-in normalized extract; do not fetch a replacement USGS response
  or infer the missing historical response bytes/collector time. The audit
  records USGS-authored/produced material as public domain with attribution
  requested; contributor/product-specific terms were not individually
  verified. No raw feed response is included in this task. A future live-source
  collection must first document the exact product, source URL, applicable
  terms, and attribution before downloading or redistributing it.
- No model or model weights are used or downloaded.

## Isolated execution

The runner writes outputs into its own run directory, so do not execute it in
the working checkout containing the preserved V2 result. Clone the pinned
commit into a disposable directory (or use an equivalent isolated worktree),
then run from that repository root:

```sh
git clone https://github.com/mightyoung/pre-combination-governance.git pcg-cpu-replay
cd pcg-cpu-replay
git checkout --detach c969913eacb56cda1236009ffa9390bd6f62cd3c
git rev-parse HEAD
PYTHONPATH=risk-fusion-bench/src python research-three/v2-alignment-20261011/runs/two-hop-lineage-controlled-synthetic-20261012-v2/run_two_hop_lineage_v2.py
PYTHONPATH=risk-fusion-bench/src python research-three/v2-alignment-20261011/runs/two-hop-lineage-controlled-synthetic-20261012-v2/score_two_hop_lineage_v2.py
```

This requires GitHub access to clone the repository. After checkout, the
runner and scorer make no network calls. Suggested resource ceiling (not a
measured runtime claim): one CPU, 1 GiB RAM, 1 GiB scratch, and five minutes;
stop and report if any ceiling is exceeded. There is no added compute or data
service cost.

Before publishing, copy the generated result files into a **new** directory
named `runs/user-cpu-replay-<UTC timestamp>-<run-id>/` on a task branch. Do not
commit over V1/V2 files. Include `METHOD_OUTPUTS_V2.json`,
`METHOD_OUTPUT_FREEZE_V2.json`, `RUNNER_CHECKS_V2.json`, `SCORED_RESULT_V2.json`,
the generated aliases and side-input negative-control record, both frozen
input manifests, the exact command/stdout/stderr/exit codes, and a task-result
JSON recording target and observed runner commits, expected and observed input
pins, Python/platform/CPU facts, exact commands, timestamps, exit codes,
checks passed/total, task status (`PASS`, `FAIL`, or `BLOCKED`), failure reasons,
and repository-relative artifact paths, byte lengths and SHA-256 values. If
execution is blocked before checkout, set observed runner/input pins to `null`,
include the command and logs, and explain the blocker. Run the validator above
before pushing the task-run folder. It reports a valid evidence bundle and task
outcome separately; a structurally valid `FAIL` or `BLOCKED` bundle is not a
passing experiment. Do not publish credentials, private Mac files/logs, or
unreviewed source payloads.

## Expected result and stop conditions

Expected repeatability result: method-output SHA-256
`15ee4c362160bfb1381da9a2e304f09224e73c265dc95fba949135d5694c66cb`; all 16
frozen runner checks true; scorer counts of full receipts `3 confirmed / 0
UNKNOWN`, missing Hop 2 receipt `1 confirmed / 2 UNKNOWN`, and hash-only `0
confirmed / 3 UNKNOWN`; side-input control `UNDECLARED_SIDE_INPUT` and
`UNKNOWN`. Execution timestamp in `RUNNER_CHECKS_V2.json` may differ. Any
manifest mismatch, output-hash mismatch, failed frozen check, unexpected pair
count, or scorer failure is `FAIL`/`BLOCKED`: preserve logs and outputs, stop,
and do not edit inputs or retry under this task ID.

Production truth denominator remains `0`; production accuracy is
`NOT_COMPUTABLE`, and wrong confirmed-attribution accuracy is `NOT_EVALUATED`.
The three pair rows share one synthetic world and are not independent samples.
Passing structural checks does not establish production accuracy, source
authenticity, transport history, statistical independence, or real alert
delivery.

## Separate scientific blocker

The next real-source lineage evidence task is **not runnable yet**. The
checkout lacks the exact original response bytes and collector receipt time,
two-sided forwarding/broker receipts with bounded cursor/offset evidence,
verified source/product terms for a new collection, and independent event
adjudication. No source-acquisition script currently captures those artifacts.
Do not substitute catalog IDs/source labels or the synthetic receipts for
these missing facts. Once the source and terms are specified, add a separately
versioned CPU protocol/collector and frozen input manifest before collecting
or scoring anything.
