# Public-source replay and lineage boundary probe

## Choice and mainline relevance

This task chose the source-correlation/duplicate-evidence gap. It is directly tied to pre-combination governance: a repeated or transformed copy must not masquerade as another independent contribution before evidence fusion. It reuses the existing source-lineage contract and the already audited USGS public sample. It does not change the association rules, D-S route, risk thresholds, or alert policy.

## Real public sample and synthetic cases

The real-data anchor is the saved USGS summary-feed feature `ci41346535`, not synthetic. The source row lists two catalog IDs (`ci41346535`, `us6000u1mg`) and two source labels (`ci`, `us`); the existing audit established that these are metadata on one row and do not prove separate acquisition paths. The source-provided event-origin, catalog-update, and feed-generation times are shown as chronology only. The sample has no exact local receiver time, saved raw response/hash, or directional forwarding receipts. Its lineage status therefore remains `UNKNOWN`, and it was deliberately not submitted to the contract as if it had a complete graph. The saved audit records USGS-authored/produced material as U.S. public domain with attribution requested; individual contributor-product terms were not separately verified, and no raw response is redistributed.

All graph probes and hypothetical copies are synthetic. The graph trust and completeness flags are assumptions used to exercise the contract, not evidence about USGS transport. The three `t+0s`, `t+1s`, and `t+2s` copy markers in the visual are an illustrative synthetic message sequence; separately, the exact-duplicate contract probe repeats graph assertions four times (one base assertion plus three repeats). These are not observed deliveries or independent event samples.

## Frozen outcome

All predeclared contract checks matched:

| Case | Contract output | Duplicate effect / interpretation |
|---|---|---|
| Synthetic shared graph, 1 assertion set | `SHARED_KNOWN_ANCESTOR`; distinct declared root strings; 1 shared ancestor; 4 unique edges | Synthetic baseline only |
| Same graph, 4 identical assertion sets | Same status, root relation, ancestor, edge count, and evidence-reference set | 0 additional lineage support from exact duplicate claims |
| Synthetic complete disjoint graph | `NO_SHARED_KNOWN_ANCESTOR` | `statistical_independence_established=false`; no confidence update permitted |
| Real USGS row | Existing read-only audit says lineage `UNKNOWN` | The ID/source-label count does not authorize a confidence update |

No numeric risk-confidence value was computed. The existing contract can group shared ancestry and collapse exact duplicate node/edge assertions; it does not calculate risk confidence, prove statistical independence, or decide event identity. This probe supports only the boundary conclusion that exact duplicate claims add no distinct lineage support and missing provenance stays unknown. It does not establish an empirical risk reduction or improved event detection.

## Verification and execution limits

- Frozen pre-run inputs and source hashes were checked by `run_probe.py`; method outputs were hashed before comparison with the expected contract fields.
- The hypothesis and literal inputs were committed before execution at `2eef5d97c901fb03676b72c4279209fb63419c22`; the unchanged lineage-contract source came from `bdbed0bc0e5415a39a790583e3550baf0b68ff18`.
- The source-lineage contract suite plus the existing `test_duplicate_forwarding_does_not_increase_lineage_support` regression passed: 20 tests total (19 contract cases + 1 focused association regression). This is software contract verification, not 20 observations, samples, or an effect estimate.
- The only network/model/notification status for this run is: no network call, model call, notification creation, or delivery. `delivery_status=NOT_DELIVERED`; event identity is `NOT_EVALUATED`.
- No new endpoint was queried. The saved audit's NWS CAP access failure remains unchanged; this run did not retry or bypass the 403/502 path.
- The prior 1,464-check Mac V3-RSS trial and its 20 non-independent method records remain unchanged and were not rerun.

Reproduce from the repository root:

```sh
PYTHONPATH=risk-fusion-bench/src python research-three/v2-alignment-20261011/runs/public-source-copy-lineage-20261012/run_probe.py
```

Re-run the focused software checks from `risk-fusion-bench/`:

```sh
PYTHONPATH=src python -m unittest -v tests.test_source_lineage_contract_v1 tests.test_observable_association.ObservableAssociationTests.test_duplicate_forwarding_does_not_increase_lineage_support
```

## Remaining blocker and next step

The public sample cannot validate real duplicate forwarding or source independence because the raw response, local receive record, and two-sided hop receipts are absent. Keep those claims `UNKNOWN`. The next bounded executable step is to use already authorized local collector records, if they exist, to bind one saved public payload to its receiver receipt and any parent/child forwarding references. If those records are unavailable, no further live-source experiment is justified; retain this result as a synthetic boundary check. NWS remains untouched.

## Files

- `PROTOCOL.md` and `INPUTS.json`: pre-run hypothesis, controls, measures, public-row reference, and synthetic contract graphs.
- `PRE_RUN_MANIFEST.json`: hashes bound before the contract calls.
- `run_probe.py`: standard-library runner using the existing contract only.
- `RESULT.json`: public-row summary, method outputs, hash and contract checks.
- `SOURCE_COPY_SEQUENCE.svg`: offline visual separating the real public row from synthetic copies and controls.
- `RUN_MANIFEST.json`: run outputs, source hashes, and focused verification command.
- `MAC_PERSISTENCE_MANIFEST.json`: repository-relative files and hashes; Mac project root remains `null`, and no copy to Mac is claimed.
