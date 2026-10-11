# 2×2 Counterexample CPU Pilot — Results

Classification: synthetic development pilot only. This is not a held-out run, formal effect evaluation, device trial, or real notification test.

## Frozen inputs, code, and execution

- Protocol: `same-root-vs-event-identity-2x2-v1.0.0`; SHA-256 `694b002cc7073b867bdd01982be94cb020c53d5ed576a83592e4dfaec64ae97c`.
- Scorer-only predeclaration: SHA-256 `7bb7476ff568dfee1de55144f7130c717286a983a273830ff56ed3a8b91eaa60`; opened after outputs were frozen.
- Method calls: 4 (two rules × two unique inputs); candidate pairs: one per input.
- Input hashes: `{"V1_ONE_ROOT": "abdbee07e9589958df142748d7d40d5d15c220b341c68784aa4a845f976fa8f0", "V2_TWO_ROOT_IDS": "c49917eceea9b15b406a070e7c323ff5143dc3acc60fa846b9ac4bab5f46ebad"}`.
- Output hashes: `{"V1_ONE_ROOT": {"MULTI_EVIDENCE_RULE": "d882e5e5cc93b10f41e6699ceb2f11de0773cda7f7f4f28d1c076659d1b8c4ae", "TIME_ASSET_RULE": "c1560272c8bb8f07c38accf887d360c24230337f70b54113411ff1b654bd3fdf"}, "V2_TWO_ROOT_IDS": {"MULTI_EVIDENCE_RULE": "d5c014186fc6e68f49796956367a415316ce05f3d1640adf5245ac971a63a033", "TIME_ASSET_RULE": "9c43686b018624d51a63b6eeb112a9e29b167e0d0dc89e7cef4d91be63396ba6"}}`.
- Frozen parameters were inherited from the original development run; no tuning or held-out access occurred.
- No model, network, device, notification, or paid service was used.

## Case decisions

| Case | Hidden event relation | Scorer-only source relation | Visible roots | Input clone equal | TIME_ASSET_RULE | MULTI_EVIDENCE_RULE | Truth score |
|---|---|---|---:|---|---|---|---|
| R1-DIFF | DIFFERENT | SHARED_SOURCE_FAMILY | 1 | yes | LINK_CANDIDATES / VERIFIED_ASSET_MATCH, TIME_AND_POSITION_COMPATIBLE | ABSTAIN / NO_INDEPENDENT_ACQUISITION_ROOTS (root count 1) | NOT_SCORED_UNIDENTIFIABLE |
| R1-SAME | SAME | SHARED_SOURCE_FAMILY | 1 | yes | LINK_CANDIDATES / VERIFIED_ASSET_MATCH, TIME_AND_POSITION_COMPATIBLE | ABSTAIN / NO_INDEPENDENT_ACQUISITION_ROOTS (root count 1) | NOT_SCORED_UNIDENTIFIABLE |
| R2-DIFF | DIFFERENT | SHARED_UPSTREAM_SOURCE_FAMILY | 2 | yes | LINK_CANDIDATES / VERIFIED_ASSET_MATCH, TIME_AND_POSITION_COMPATIBLE | LINK_CANDIDATES / VERIFIED_ASSET_MATCH, TIME_AND_POSITION_COMPATIBLE, CROSS_MODAL_SUPPORT, QUALITY_CALIBRATION_VALID, INDEPENDENT_ACQUISITION_ROOTS (root count 2) | NOT_SCORED_UNIDENTIFIABLE |
| R2-SAME | SAME | DISJOINT_SOURCE_FAMILIES | 2 | yes | LINK_CANDIDATES / VERIFIED_ASSET_MATCH, TIME_AND_POSITION_COMPATIBLE | LINK_CANDIDATES / VERIFIED_ASSET_MATCH, TIME_AND_POSITION_COMPATIBLE, CROSS_MODAL_SUPPORT, QUALITY_CALIBRATION_VALID, INDEPENDENT_ACQUISITION_ROOTS (root count 2) | NOT_SCORED_UNIDENTIFIABLE |

The event labels were generated from the predeclared scorer-only event registry, not derived from the method rules or visible measurements. Source dependence was assigned separately from the scorer-only family graph.

## Input-clone and identifiability check

- R1 opposite-label inputs byte-identical: `True`.
- R2 opposite-label inputs byte-identical: `True`.
- All four cases are marked `NOT_SCORED_UNIDENTIFIABLE`; no accuracy, false-merge, false-split, or superiority rate is reported.

## Findings and failure analysis

- R1-SAME and R1-DIFF have identical method-visible bytes, so the same-root input cannot distinguish event identity.
- With one root ID, MULTI_EVIDENCE_RULE abstains because it counts root strings; this does not establish that the two observations are the same event.
- R2-SAME and R2-DIFF also have identical method-visible bytes. Both rules link candidates from that input, including the scorer-only shared-upstream-family assignment.
- MULTI_EVIDENCE_RULE reports two independent acquisition roots for R2 based on distinct root IDs. The scorer-only graph shows that this does not authenticate independent source evidence.
- The hidden labels were generated from a predeclared event registry and source-family graph independent of rule code. Because opposite labels are byte-identical per root-count row, no truth-accuracy, false-merge, false-split, or superiority rate is computed.

The predeclared path expectations were checked against outputs (see `case_results.json`). A `LINK_CANDIDATES` proposal is a candidate association only; it does not confirm an event identity.

## Prior-run preservation and limits

- Original `comparison_attempt_02` manifest SHA-256: `ff5411c0c498e1316255e673f2bbe9c5684a05c844ecff353f812b42f124b60d`.
- Historical files rechecked against that manifest: 219; integrity status: `PASS`.
- These four synthetic assignments are counterexamples to treating acquisition-root IDs as either event identity or source-independence proof. They do not estimate real-world error rates or establish general rule performance.
- Real-world source provenance, event confirmation, reminder delivery and user-visible timing remain untested.
