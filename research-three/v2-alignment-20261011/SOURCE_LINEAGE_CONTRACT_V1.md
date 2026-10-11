# Observable Source-Lineage Contract v1

- **Status:** implemented as a pure CPU contract; contract tests passed.
- **Classification:** `C0/I0/M0`; synthetic/software boundary only.
- **Module:** `risk-fusion-bench/src/rfb/research/source_lineage_contract_v1.py`.
- **Compatibility:** additive. It does not edit or replace `TIME_ASSET_RULE`, `MULTI_EVIDENCE_RULE`, or the frozen 2×2 pilot outputs.

## Purpose and boundary

This contract distinguishes a declared acquisition-root string from an evidence-backed provenance graph. It can report a shared ancestor for evidence grouping or discounting. A complete graph with no common node returns `NO_SHARED_KNOWN_ANCESTOR`; that means only that no common ancestor appears in the supplied complete graph. It does not establish statistical independence, event identity, or event equivalence. The module chooses no numerical discount and emits no alert or association proposal.

Hidden `source_family`, event, episode, card, and scorer labels are not contract fields. Event identity remains outside this module.

## Versioned input fields

| Type | Fields | Meaning |
|---|---|---|
| `LineageEvidence` | `source_ref`, `actual_available_at`, `earliest_known_at`, `trust_status`, optional `valid_until` | Evidence provenance and time boundary. Earliest-known cannot precede actual availability. Trust is `VERIFIED`, `UNVERIFIED`, or `CONFLICTING`. |
| `LineageNode` | `node_id`, `node_type`, `evidence` | An observed source, acquisition step, transform, relay, or observation node. Node IDs identify graph nodes; they do not encode hidden scorer families. |
| `LineageEdge` | `edge_id`, `upstream_node_id`, `downstream_node_id`, `evidence` | A directed, evidence-backed upstream-to-downstream assertion. |
| `ObservationLineage` | `observation_id`, optional `declared_root_id`, `terminal_node_id`, `trace_complete`, `completeness_evidence`, `nodes`, `edges` | One observation's declared root string and its separately evidenced graph claim. |

`declared_root_id` is only compared as a string and reported as `SAME_DECLARED_ID`, `DISTINCT_DECLARED_IDS`, or `ROOT_ID_UNKNOWN`. It does not produce an independence count or relation status.

## Output states and handling

`assess_source_lineage(left, right, as_of=...)` returns `SourceLineageAssessment`:

- `SHARED_KNOWN_ANCESTOR`: the verified, current, complete graph closures overlap. Return the shared node IDs and evidence references so a caller may group or discount correlated evidence.
- `NO_SHARED_KNOWN_ANCESTOR`: both traces are complete and all supplied evidence is verified and current, but their graph closures do not overlap. The output always has `statistical_independence_established=false` and includes `NO_STATISTICAL_INDEPENDENCE_CLAIM`.
- `UNKNOWN`: incomplete trace, missing node, future evidence, stale evidence, unverified assertion, conflicting trust, or conflicting reuse of a node/edge ID. Reasons are explicit.
- `INVALID_CYCLE`: the asserted directed graph contains a cycle. It is not silently truncated or treated as a valid lineage.

Exact duplicate node and edge assertions with the same IDs and contents are idempotently collapsed. Conflicting contents under one ID fail closed. The contract rejects malformed timestamps and missing evidence source references. Evidence known after `as_of` is not used; expired evidence is reported stale.

Timestamp ordering compares parsed, timezone-aware instants normalized to UTC, not ISO timestamp strings. Evidence known exactly at `as_of` is eligible; sub-second evidence after the cutoff remains unknown even when both values fall in the same displayed second. Equivalent offset spellings of the same instant compare equal. `valid_until` is inclusive at equality and is stale only when it precedes `as_of`.

## Pure CPU verification

Run from `risk-fusion-bench/`:

```sh
PYTHONPATH=src python -m unittest -v tests.test_source_lineage_contract_v1
```

The tests cover root-ID-only unknowns, a shared multi-hop ancestor, complete observed graphs with no shared ancestor, same-root declarations without event claims, exact replay deduplication, conflicting edge IDs, stale/future/unverified/conflicting evidence, cycles, missing nodes, timestamp ordering including sub-second boundaries and equivalent offsets, and rejection of scorer-only `source_family` input. The current focused suite has 19 tests; its precision-fix red/green record is `SOURCE_LINEAGE_TEMPORAL_PRECISION_FIX_RESULTS.json`.

This module is a contract prototype. It does not claim that provenance graph completeness or source assertions are reliable in production, and it does not demonstrate improved association accuracy.
