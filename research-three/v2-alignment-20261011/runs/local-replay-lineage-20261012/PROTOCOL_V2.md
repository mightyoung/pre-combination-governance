# Local controlled replay, runner revision 2

**Status: `FROZEN_PRE_RUN`.** Revision 2 retains the same source bytes, alias projection, hypotheses, expected lineage states, and negative controls as V1. It fixes only the result-metadata key lookup and writes V2 outputs to new filenames so the V1 serialization failure and its local sidecars remain intact.

## Preserved V1 failure

V1 reached the lineage calls and local receipt creation, then stopped before writing `RESULT.json` with `KeyError: 'source_code_commit'`. The pre-run manifest field is `method_source_commit`. The failure and the three generated local files are preserved in `FAILURE_ATTEMPT_V1.json` and `FAILED_ATTEMPT_V1_*`. V1 method outputs were not persisted; this attempt is not treated as a completed result.

## Frozen V2 comparison

The new input file `INPUTS_V2.json` repeats the V1 source hash, exact alias projection/hash, expected lineage outcomes, receipt policy, and forged-parent/hash-mismatch negatives; only the run ID and `supersedes_input` metadata differ. The two main arms use byte-identical alias output: one validates a local parent/child receipt; the other omits it. The negative controls re-sign their local receipt envelope after mutating the parent ID or parent digest, so the validator tests the relation to the known local source bytes rather than a malformed receipt's self-hash alone.

At run start, the V2 runner records a fresh local UTC replay receipt time, then hashes and reads the saved normalized sample file. This timestamp is not the source event time or historic collector receipt. The parent/child receipts remain unsigned local runner assertions; a passing validation supports attribution to the saved local file only and does not authenticate USGS or prior transport.

The fixed measures remain: source and alias hashes/lengths, alias-hash equality across arms, receipt validation states, lineage contract outputs, and `statistical_independence_established=false`. No risk score, probability, D-S combination, event accuracy, or delivery claim is produced.

## Execution

V2 inputs, runner, protocol, V1 failure sidecars, saved sample, and existing contract code are bound in `PRE_RUN_MANIFEST_V2.json` before the V2 run. Reproduce with:

```sh
PYTHONPATH=risk-fusion-bench/src python research-three/v2-alignment-20261011/runs/local-replay-lineage-20261012/run_local_replay_v2.py
```

V2 outputs use `*_V2` / `RESULT_V2` names and do not overwrite V1 artifacts. No network, NWS, model, notification, or device path is used.
