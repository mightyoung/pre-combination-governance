# Post-run wording corrections — 2026-10-11

This record supplements the hash-bound development report without rewriting it. The historical [`comparison_attempt_02/REPORT.md`](../comparison_attempt_02/REPORT.md), its run scripts, input data, method outputs, metrics, and parameters remain unchanged.

## Corrections

1. **Method outputs were not identical.** The two arms have the same delay summary and censoring counts, but their saved outputs differ on three `SAME` pairs in `dependent_replay_unknown`: `TIME_ASSET_RULE` returns `LINK_CANDIDATES` while `MULTI_EVIDENCE_RULE` returns `ABSTAIN` with `NO_INDEPENDENT_ACQUISITION_ROOTS`. The exact records and traces are in [`REPORT_V2.md`](REPORT_V2.md) and [`case_analysis_data.json`](case_analysis_data.json). The old sentence “Identical outputs, errors and censored observations are reported as generated” is superseded by this correction.
2. **The first preflight flagged nine worlds, not nine strata.** Those nine worlds were the three worlds in each of the three non-UNKNOWN strata. The check expected an explicit `UNKNOWN: 0` key, while the sparse counter omitted zero-valued keys. No method ran in that attempt; its saved inputs and failure record remain intact.

The frozen report-generation scripts retain the historical wording because they are part of the hash-bound run record. Do not reuse that sentence in a future report; use the corrected distinction above and in `REPORT_V2.md`.

## Provenance and scope

- Historical attempt-02 report SHA-256 before this correction: `78952f10eb9e77e477d1cfaed4a414c0d304fc1459695043dcc67a38d34da79f`.
- Attempt-02 run-manifest SHA-256 used as the analysis source: `ff5411c0c498e1316255e673f2bbe9c5684a05c844ecff353f812b42f124b60d`.
- This is a read-only analysis of saved development inputs, sidecars, traces, and outputs. No generator, method, or scorer was invoked; no metric, configuration, or original artifact was changed.
- The run-level manifest and first-attempt failure remain the source records for the original execution. This correction is an appended version, not a replacement result.
