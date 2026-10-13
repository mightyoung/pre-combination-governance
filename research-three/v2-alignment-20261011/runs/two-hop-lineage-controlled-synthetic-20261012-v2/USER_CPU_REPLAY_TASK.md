# PCG CPU replay handoff: V2 two-hop lineage

**Task ID:** `PCG-LINEAGE-CPU-REPLAY-001`  
**Status:** `LOCAL_HANDOFF_PENDING_PUBLICATION`
**Evidence class:** software/mechanics reproducibility only; not a new experiment.

The complete task card, result generator, validator, and revised schema are
present in this local research branch. The last read-only check of the remote
branch found it at `f8fac06b769b1ba5c3f54e497e94c7eff0135518`, which does not
contain this complete increment. Do not start the user-server replay until the
handoff files are published on the branch and every file in the persistence
manifest passes its byte/hash check.

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
- Runner code pin: `c969913eacb56cda1236009ffa9390bd6f62cd3c` on
  `task/research-three-two-hop-lineage-20261012`. It is the immutable commit
  containing the V2 runner and frozen inputs. The runner pin is separate from
  the handoff tool checkout and must be recorded as `target_runner_commit` and
  `observed_runner_commit` in the result.
- Handoff tool pin: acquire the published task branch and verify the files in
  [MAC_PERSISTENCE_MANIFEST_USER_CPU_REPLAY_V1.json](MAC_PERSISTENCE_MANIFEST_USER_CPU_REPLAY_V1.json).
  The result generator records the exact handoff checkout SHA in
  `handoff_code_commit`; the validator verifies that commit is an ancestor of
  the checkout used for validation. The result also records schema SHA-256
  `1077cebe6ae18dd4c0218c11789ef9160592ee5c8cdf79c03f041607ff1c6bd0`.
- The generator runs the existing runner and scorer in the disposable pinned
  runner worktree, captures their output and resource measurements, copies the
  resulting files into a separate result folder, and writes `TASK_RESULT.json`.
  It first verifies the runner commit and clean worktree, removes only the
  runner's generated outputs in that disposable worktree to avoid stale files,
  and never edits the preserved handoff checkout's V1/V2 results.
  A zero command exit code means the bundle was written; read `task_status` to
  see whether the replay was `PASS`, `FAIL`, or `BLOCKED`.
  Before leaving a result as `PASS`, the generator also applies the frozen
  mechanics checks; the separate validator command below remains the final
  explicit bundle check.
- The result validator command from the handoff checkout root is:
  `PYTHONPATH=risk-fusion-bench/src python -m rfb.research.user_cpu_replay_handoff --bundle-dir research-three/v2-alignment-20261011/runs/user-cpu-replay-<UTC timestamp>-<run-id>`
- The returned `TASK_RESULT.json` follows
  [USER_CPU_REPLAY_RESULT_V1.schema.json](USER_CPU_REPLAY_RESULT_V1.schema.json).
  The validator checks handoff and runner pins, schema digest, result artifact
  hashes, both frozen manifests, all 16 runner checks, fixed pair counts, and
  the explicit `NOT_COMPUTABLE` production-accuracy fields for PASS results.
  FAIL/BLOCKED bundles retain mismatched input artifacts for review and do not
  claim frozen-mechanics checks passed. It uses the Python standard library
  only. FAIL/BLOCKED records retain measured values above the 300-second or
  1,024-MiB ceiling; only PASS is constrained by those ceilings.
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

Run this only on the user's CPU server after the complete handoff files have
been published and their manifest verifies. Use a handoff checkout and a
separate disposable runner worktree; do not run the V2 entry points in the
working checkout containing the preserved V2 result:

```sh
git clone https://github.com/mightyoung/pre-combination-governance.git pcg-handoff
cd pcg-handoff
git fetch origin task/research-three-two-hop-lineage-20261012
git switch --detach origin/task/research-three-two-hop-lineage-20261012
git rev-parse HEAD
python - <<'PY'
import hashlib, json
from pathlib import Path
manifest = json.loads(Path("research-three/v2-alignment-20261011/runs/two-hop-lineage-controlled-synthetic-20261012-v2/MAC_PERSISTENCE_MANIFEST_USER_CPU_REPLAY_V1.json").read_text(encoding="utf-8"))
bad = []
for entry in manifest["files"]:
    data = Path(entry["path"]).read_bytes()
    if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        bad.append(entry["path"])
if bad:
    raise SystemExit("handoff manifest mismatch: " + ", ".join(bad))
print("handoff manifest verified", len(manifest["files"]), "files")
PY
git worktree add --detach ../pcg-v2-runner c969913eacb56cda1236009ffa9390bd6f62cd3c
git -C ../pcg-v2-runner rev-parse HEAD
git -C ../pcg-v2-runner status --short
RUN_ID="user-cpu-replay-$(date -u +%Y%m%dT%H%M%SZ)-srv01"
PYTHONPATH=risk-fusion-bench/src python -m rfb.research.user_cpu_replay_runner \
  --runner-root ../pcg-v2-runner \
  --bundle-dir "research-three/v2-alignment-20261011/runs/${RUN_ID}" \
  --run-id "${RUN_ID}"
PYTHONPATH=risk-fusion-bench/src python -m rfb.research.user_cpu_replay_handoff \
  --bundle-dir "research-three/v2-alignment-20261011/runs/${RUN_ID}"
```

The `date -u` expression creates a UTC timestamp; use a different safe suffix
if multiple runs could start within the same second. The generated bundle
includes `TASK_RESULT.json`, frozen
inputs, aliases and scorer/runner output where available, environment facts,
exact commands, stdout/stderr, timestamps, measured wall time and peak memory,
exit codes, and SHA-256/byte-length entries with bundle-relative artifact
paths. If runner checkout inspection is blocked, observed runner/input pins are
null; if a wrong checkout is readable, the result retains its observed SHA. If
any precondition fails, the generator writes a `BLOCKED` bundle with its reason
and does not launch the runner. Nonzero exit, output mismatch, or a measured
ceiling breach is recorded as `FAIL`; over-limit values are retained. A valid
`FAIL`/`BLOCKED` bundle is not a passing replay. The wrapper uses only the Python standard library after
checkout, installs no packages, and performs no network, model, or notification
calls. Memory is sampled after each child process; an over-limit runner result
stops the scorer. Do not publish credentials, private Mac files/logs, or
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
