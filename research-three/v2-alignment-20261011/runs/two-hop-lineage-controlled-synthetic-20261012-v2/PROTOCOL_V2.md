# Two-hop lineage replay V2: conservative hash policy and declared inputs

**Status:** `FROZEN_PRE_RUN`. **Classification:** `CONTROLLED_SYNTHETIC_REPLAY_OF_SAVED_NORMALIZED_PUBLIC_SAMPLE`.

## Scope

This is the same one-world synthetic chain and the same three pair rows as V1, rooted in the already saved normalized USGS sample. It does not add observations or worlds. V2 corrects two implementation/scoring boundaries: (1) distinct hashes no longer count as wrong separate-source attribution; hash equality or inequality yields no lineage conclusion, and (2) Hop 2 must read only the persisted Hop 1 bytes. One deliberate undeclared-source-side-input negative control checks fail-closed behavior; it is a control, not a new pair or sample.

There are no eligible production source-lineage replay logs in this checkout. Production accuracy remains `NOT_COMPUTABLE`, with denominator `0`. All aliases and receipts below are synthetic local outputs; the normalized source sample is only an anchor. Its historical receive time and original response bytes remain unavailable.

## Frozen inputs, transform graph, and control

- Source sample: exact `REAL_PUBLIC_FEED_SAMPLE.json` bytes, pinned in `INPUTS_V2.json`.
- Hop 1: transforms the saved sample to a synthetic wrapper containing every field required by Hop 2, including `source_namespace` and `updated_epoch_ms`; writes the canonical bytes to `ALIAS_HOP1_V2.json`.
- Hop 2: a one-argument transform function receives only the bytes reread from the persisted Hop 1 file. It derives all output fields and the Hop 2 receipt's parent hash from those bytes. It does not receive the source sample object or any separate source property.
- Valid Hop 2 receipt: declares and records the observed input as exactly `HOP1` with the persisted Hop 1 SHA-256.
- Side-input negative: an intentionally defective control passes both Hop 1 bytes and a source property directly to a bad Hop 2 transform. Its receipt declares only Hop 1, while the local harness records both actual inputs. The receipt validator must return `UNDECLARED_SIDE_INPUT` and the lineage outcome must stay `UNKNOWN`. This row is excluded from the three-pair metric denominator.
- Conditions remain: full two-hop receipts; Hop 2 receipt omitted; hash-only dedup. The three unordered pair IDs remain `SOURCE/HOP1`, `SOURCE/HOP2`, and `HOP1/HOP2`.

## Frozen scoring policy and split

The scoring rules are in [SCORING_POLICY_V2.md](SCORING_POLICY_V2.md). Equal and different hashes are content observations only; hash-only source lineage is always `UNKNOWN`. Missing/incomplete/unreported provenance is `UNKNOWN`, never a wrong attribution or independence assertion.

The split is one fixed `SYNTHETIC-WORLD-001`, no random seed, no train/held-out division, no parameter search, and no repeated worlds. Report raw confirmed-ancestry and `UNKNOWN` counts, not rates. Production accuracy and wrong-attribution count remain `NOT_COMPUTABLE`/`NOT_EVALUATED` because there is no independent production truth denominator. The scorer-only synthetic relation fixture is not production truth and is not used for accuracy.

Expected controlled-mechanics outcomes:

| Condition | Supported shared-ancestor count | `UNKNOWN` count |
|---|---:|---:|
| Full receipts | 3 | 0 |
| Hop 2 receipt omitted | 1 | 2 |
| Hash-only, any hash relation | 0 | 3 |

All values are within the single synthetic chain. The side-input negative must separately fail closed and is not added to the table.

## Truth isolation and order

The method runner reads the frozen protocol/input/pre-run manifest, saved source file, and existing lineage contract. It does not read `SYNTHETIC_TRUTH_LOG_V2.json`, `SCORER_TRUTH_MANIFEST_V2.json`, or the scorer. It writes and hashes method outputs before checking the frozen expectations. After that hash is frozen, the scorer verifies the output digest and may read the separate synthetic fixture for audit, while retaining production accuracy as not computable.

The exact scorer truth sidecar is a public, predeclared synthetic fixture, not a blind or independently sourced truth log. The sidecar and scorer are frozen before execution so their role and exclusion are auditable.

## Exclusions

No NWS/network call, new collection, model, paid service, notification, Mac trial, or executor is involved. No production effect, source authenticity, historical transport, event identity, or statistical independence is inferred.
