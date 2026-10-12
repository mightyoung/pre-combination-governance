# Public-source replay and lineage boundary probe

**Status: `FROZEN_PRE_RUN`.** This bounded mechanism check uses the saved USGS public sample as a real-data anchor and separate synthetic lineage graphs as the controlled counterexamples. It does not fetch a new public payload, access the NWS endpoints that returned 403, run an association method, or score event truth.

## Why this gap

Research three's pre-combination governance depends on not treating a repeated/derived record as a new independent contribution. The current USGS snapshot exposes two catalog IDs and two source labels on one feature, but the audit has no raw response digest, exact collector receipt time, or forwarding receipts. Treating the listed IDs/source labels as independent evidence would overstate what is observed. A small, conditional probe of replay idempotence and fail-closed missing lineage is the narrowest useful continuation; it does not alter the D-S route, thresholds, or alert policy.

## Frozen hypothesis and controls

- **H1 — exact duplicate claim invariance:** when a synthetic, fully specified lineage graph receives four byte-equivalent node/edge assertions instead of one assertion, `assess_source_lineage` returns the same status, declared-root relation, shared ancestor IDs, unique edge count, and evidence references. Duplicate assertions add zero distinct lineage support.
- **H2 — public sample remains unknown:** the real USGS row's `ids`/`sources` lists and three source-provided timestamps are not directional lineage receipts. For this real row, source independence and any additional risk-confidence support remain `UNKNOWN` regardless of how many listed IDs/labels are counted.
- **Shared-ancestor positive control:** synthetic copies with different declared root strings but one explicit shared upstream graph must return `SHARED_KNOWN_ANCESTOR`; distinct root strings must not override the graph.
- **Disjoint-graph negative control:** synthetic complete graphs with no common node may return `NO_SHARED_KNOWN_ANCESTOR`, but `statistical_independence_established` must remain false. This is not a positive independence or confidence control.

The synthetic `VERIFIED` trust labels and graph-completeness claims are fixture assumptions only. They are not assertions about the actual USGS collection or transport path.

## Comparison and measures

The frozen method input is `INPUTS.json`; the only method called is the existing pure function `source_lineage_contract_v1.assess_source_lineage` on the three synthetic graph cases. The saved USGS row is summarized from its existing normalized extract and is not submitted as a complete lineage graph because that would require inventing missing acquisition times or edges.

Report these contract-conformance measures only:

1. Expected lineage-state and root-ID-relation matches for the shared, duplicate, and disjoint synthetic cases.
2. Exact duplicate-claim invariance of status, root relation, shared ancestor IDs, unique edge count, and deduplicated evidence-reference set.
3. `statistical_independence_established` remains false for every synthetic case.
4. The public sample's listed ID/source-label counts are descriptive metadata only; qualified lineage support and numeric risk-confidence change remain `UNKNOWN` / `NOT_COMPUTED`.

No probability, posterior risk score, event accuracy, false-merge rate, independence rate, efficacy effect, or notification-timeliness metric is defined. Test counts are reported only as software verification, never as evidence of risk improvement.

## Frozen source boundary and timestamps

Real public row: the already saved USGS past-day GeoJSON summary feature `ci41346535` (observed on 2026-10-11 UTC). The event-origin time (`2026-10-11T21:28:13.930Z`), catalog-update time (`2026-10-11T22:39:25.040Z`), and feed-generation time (`2026-10-11T23:44:47.000Z`) are source-provided chronology markers only. They do not form a transport or causal trace. `ids_raw` and `sources_raw` remain literal source metadata.

Synthetic message sequence: one hypothetical catalog-feature assertion is copied/replayed at offsets 0, 1, and 2 seconds. These are code-generated counterexamples, not observed deliveries. They carry no delivery receipt and create no notification.

The preserved source audit reports that the USGS detail endpoint was inaccessible through the available browser and network tunnel; it records a tunnel 403. This task does not retry through another route. The NWS CAP payload was likewise not acquired in the prior audit and is not fetched here.

## Reproduction

After this protocol, inputs, runner, and pre-run manifest are committed, run:

```sh
PYTHONPATH=risk-fusion-bench/src python research-three/v2-alignment-20261011/runs/public-source-copy-lineage-20261012/run_probe.py
```

The runner reads only `INPUTS.json`, the saved normalized USGS sample, and the local source-lineage contract. It writes the result and offline SVG to this run directory. Its assertions check the frozen contract behavior, not a product or field-effect claim.
