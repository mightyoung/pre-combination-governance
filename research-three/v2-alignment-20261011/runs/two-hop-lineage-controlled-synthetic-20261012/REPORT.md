# Two-hop controlled synthetic lineage replay

## Result class and denominator

This is one deterministic CPU-only synthetic replay rooted in the previously saved normalized public sample for USGS feature `ci41346535`. The original USGS response bytes, local collector time, and forwarding receipts are absent. The two aliases and both hop receipts were generated offline by the frozen local runner.

The repository audit found **zero eligible production source-lineage replay logs**. The saved USGS audit lacks receiver and hop records. The previous local V2 receipts were emitted by the same runner as the verifier. A read-only metadata inventory of all three in-repository `run_ledger.jsonl` candidates found: local `SHK-000` 32/32 rows `GENERATED_NOT_EXECUTED`, remote `SHK-000` 32/32, and restore-cache `SHK-001A` 112/112. All three manifests classify them as `G0_G2_SHAKEDOWN`, `NON_CONFIRMATORY_DO_NOT_PROMOTE`, with `claim_support=none`; their records are synthetic risk-trajectory material, not executed source-lineage replays. Payload files were not used. Production accuracy is therefore `NOT_COMPUTABLE`.

For a mechanics check, a separate scorer-only synthetic truth fixture labels `SOURCE`, `HOP1`, and `HOP2` as one generated parent chain. The method runner did not read the truth log. These results are counts from three pairwise rows within one synthetic world; those rows are dependent and are not three independent observations.

## Frozen replay and outcome

The protocol, transforms, split, expected output states, and count metrics were committed before the run at `c1212932e52ce1025c27d1168e68c1e310b7d387`. The method runner wrote and hashed the output before comparing it with expectations. Frozen method-output SHA-256: `a2feb4759acf9bc08a6f5bdb4d328954d46267d27012c441c3cef654719f4b11`. All 11 runner checks passed, including changed outer IDs, changed projection schemas, unique hashes, receipt-chain outcomes, missing-receipt `UNKNOWN`, and no independence assertion.

The normalized source sample hash was `9bfbd8a6600deb0c230fea2294f3673a2c726e5c8285687cb9531cd88a64d599`. Hop 1 has hash `228636e4fd7f1c9fc8d2c4b04043d16653aa3db8c4b005c93e4c5bcc2cc17893`; Hop 2 has hash `95fa65fe89464c2ec2034ecb3d5995f581a91bfc4be7fc61fa943e8a1323b195`. Each transformation changed the outer ID and projected key set.

| Condition | Correct attribution | Wrong separate bucket | `UNKNOWN` |
|---|---:|---:|---:|
| Both hop receipts present | 3 | 0 | 0 |
| Missing Hop 1 → Hop 2 receipt | 1 | 0 | 2 |
| Exact-hash-only dedup | 0 | 3 | 0 |

These counts follow the frozen synthetic scorer fixture. The hash-only baseline assigns distinct hashes to separate dedup buckets; it does **not** prove statistical independence. With the middle receipt missing, the verifier keeps the source/Hop 1 relationship and returns `UNKNOWN` for both comparisons that require Hop 2 ancestry.

Receipt status `PASS_LOCAL_RUNNER_CONSISTENCY` means the unsigned local receipts’ IDs, hashes, transform references, and generated chain agree under this runner. The receipts are created by the same local process; even a locally re-hashed or re-signed parent/child record cannot authenticate the real source, an external publisher, or historical transport. The lineage contract's `SHARED_KNOWN_ANCESTOR` here is a controlled synthetic graph outcome, not a real-world source claim.

## Prior V2 audit corrections

[PRIOR_V2_AUDIT_ADDENDUM.md](PRIOR_V2_AUDIT_ADDENDUM.md) corrects two prior V2 presentation/evidence claims without changing its historical files:

- M1: `method_outputs_sha256_before_expectation_checks` was computed **after** the V2 check dictionary and `all_passed` were evaluated. The old field name and audit wording are inaccurate; the old result remains unchanged. This run hashes method output before expectation checks.
- M2: the old V2 SVG arrow visually connected the saved sample and the local replay timestamp beside `historical receive time: UNKNOWN`. The old SVG is preserved. [VISUALIZATION_V2_AUDIT_CORRECTED.svg](VISUALIZATION_V2_AUDIT_CORRECTED.svg) is the derived rendering with separate time cards and no connecting arrow.

## Artifacts and reproduction

- [Frozen protocol](PROTOCOL.md), [method input](INPUTS.json), and [pre-run method manifest](PRE_RUN_MANIFEST.json) bind the method side without the scorer truth file.
- [Synthetic truth log](SYNTHETIC_TRUTH_LOG.json) and [scorer truth manifest](SCORER_TRUTH_MANIFEST.json) are separate scorer-side inputs frozen before execution.
- [Method runner](run_two_hop_lineage.py), [method output](METHOD_OUTPUTS.json), [pre-score output freeze](METHOD_OUTPUT_FREEZE.json), [runner checks](RUNNER_CHECKS.json), and [scored result](SCORED_RESULT.json) record the one synthetic replay.
- [Hop 1 alias](ALIAS_HOP1.json), [Hop 2 alias](ALIAS_HOP2.json), and [two-hop result diagram](VISUALIZATION_TWO_HOP.svg) expose the transformed payloads and comparison counts.
- [Run manifest](RUN_MANIFEST.json) and [Mac persistence manifest](MAC_PERSISTENCE_MANIFEST.json) provide repository-relative hashes. Mac root is `null`; no copy to Mac is claimed.

Run from repository root:

```sh
PYTHONPATH=risk-fusion-bench/src python research-three/v2-alignment-20261011/runs/two-hop-lineage-controlled-synthetic-20261012/run_two_hop_lineage.py
PYTHONPATH=risk-fusion-bench/src python research-three/v2-alignment-20261011/runs/two-hop-lineage-controlled-synthetic-20261012/score_two_hop_lineage.py
```

No network/NWS access, new collection, model/service, paid resource, notification, or Mac trial was used. Delivery is `NOT_DELIVERED`; event identity and production accuracy remain unevaluated.

## Next executable step

To replace this mechanics-only fixture with a production denominator, provide or identify an existing bounded replay export with: saved input and output payload hashes, outer/native IDs, both sender/receiver sides of each hop, parent/child receipt IDs, receive/transform timestamps, transform/config digests, and a completeness boundary such as sequence/offset coverage. Independent source grouping must be in a scorer-only log and supported by native record evidence. Without those materials, keep production attribution `UNKNOWN` and do not inflate the count by adding more synthetic assertions.
