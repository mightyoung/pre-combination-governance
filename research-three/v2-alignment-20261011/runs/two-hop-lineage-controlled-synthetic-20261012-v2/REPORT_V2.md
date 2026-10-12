# Two-hop controlled synthetic replay V2

## Status and scope

V2 preserves the original V1 files and applies the conservative scoring policy in a new run directory. It reuses the same saved normalized public sample, single synthetic world, and three related pair rows; it adds no source sample, world, or scored pair. The new side-input control is a boundary check and is excluded from the pair denominator.

No eligible production source-lineage replay log is available in this checkout. The historical source receive time and original USGS response bytes remain unknown. Production truth denominator is `0`, production accuracy is `NOT_COMPUTABLE`, and wrong confirmed-attribution count is `NOT_EVALUATED` (not zero).

## V2 outcome

| Condition | Eligible pair rows | Confirmed shared ancestor | `UNKNOWN` | Production accuracy |
|---|---:|---:|---:|---|
| Two receipts present | 3 | 3 | 0 | Not evaluated |
| Hop 1 → Hop 2 receipt missing | 3 | 1 | 2 | Not evaluated |
| Hash-only dedup | 3 | 0 | 3 | Not evaluated |

All 16 frozen runner checks passed. Equal and different digest policy branches both return lineage `UNKNOWN`; the hash-only arm reports only byte relations. The three different hashes in this fixture are not counted as three wrong source attributions.

The side-input negative control deliberately reads persisted Hop 1 bytes plus a direct `SOURCE` property while its receipt declares only Hop 1. The local harness's function-argument record—not process-level side-effect tracing—shows both inputs; the comparison returns `UNDECLARED_SIDE_INPUT` and lineage stays `UNKNOWN`. This control is not included in the three-pair metric denominator.

Hop 2 in the valid path receives exactly one argument: bytes reread from `ALIAS_HOP1_V2.json`. Hop 1 contains the fields Hop 2 needs, including namespace and update time. The Hop 2 receipt's declared input hash matches the persisted Hop 1 bytes. Receipt results remain `PASS_LOCAL_RUNNER_CONSISTENCY` only; they do not authenticate a publisher, original source, historical transport, or real collection chain.

The method output SHA-256 `15ee4c362160bfb1381da9a2e304f09224e73c265dc95fba949135d5694c66cb` was written to `METHOD_OUTPUT_FREEZE_V2.json` before the runner evaluated the frozen expectations. The method runner did not read the synthetic truth sidecar. The scorer verified the output freeze before reading the separate synthetic fixture, which it used only for fixture audit—not accuracy.

## Correction to V1

[V1_SCORE_CORRECTION.md](V1_SCORE_CORRECTION.md) records the scoring limitation without editing the V1 result. V1's `DISTINCT_HASH_BUCKETS` rows established only byte inequality. Its three `wrong_separate_attribution` counts must not be interpreted as errors under the new policy; for new scoring they are `UNKNOWN` because no lineage evidence was provided. The old V1 result remains available as an immutable historical artifact.

## Artifacts

- [Frozen V2 scoring policy](SCORING_POLICY_V2.md), [protocol](PROTOCOL_V2.md), [inputs](INPUTS_V2.json), and [pre-run method manifest](PRE_RUN_MANIFEST_V2.json).
- [Synthetic truth fixture](SYNTHETIC_TRUTH_LOG_V2.json) and [scorer manifest](SCORER_TRUTH_MANIFEST_V2.json), separate from method-visible inputs.
- [V2 runner](run_two_hop_lineage_v2.py), [scorer](score_two_hop_lineage_v2.py), [method output](METHOD_OUTPUTS_V2.json), [pre-check output freeze](METHOD_OUTPUT_FREEZE_V2.json), [runner checks](RUNNER_CHECKS_V2.json), and [coverage result](SCORED_RESULT_V2.json).
- [Persisted Hop 1](ALIAS_HOP1_V2.json), [Hop 2](ALIAS_HOP2_V2.json), [side-input negative output](SIDEINPUT_NEGATIVE_HOP2_V2.json), and [offline comparison diagram](VISUALIZATION_TWO_HOP_V2.svg).
- [Run manifest](RUN_MANIFEST_V2.json) and [Mac persistence manifest](MAC_PERSISTENCE_MANIFEST_V2.json); the Mac checkout root is unspecified and no copy to Mac is claimed.

Reproduce from repository root after the pre-run freeze commit:

```sh
PYTHONPATH=risk-fusion-bench/src python research-three/v2-alignment-20261011/runs/two-hop-lineage-controlled-synthetic-20261012-v2/run_two_hop_lineage_v2.py
PYTHONPATH=risk-fusion-bench/src python research-three/v2-alignment-20261011/runs/two-hop-lineage-controlled-synthetic-20261012-v2/score_two_hop_lineage_v2.py
```

No NWS/network request, new collection, model, paid resource, notification, or Mac trial was used. This one synthetic chain does not establish real-world source accuracy, event identity, statistical independence, delivery behavior, or an industrial effect.
