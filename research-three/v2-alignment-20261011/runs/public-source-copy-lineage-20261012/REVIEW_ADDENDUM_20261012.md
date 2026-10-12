# Scope clarification after independent review

This addendum narrows the interpretation of `RESULT.json` and `SOURCE_COPY_SEQUENCE.svg`; the original pre-run inputs, runner, result, and their manifest hashes remain unchanged.

- The fourfold synthetic case repeats only the left claim's three node and two edge assertions with the exact same IDs and contents. The right claim is unchanged. It exercises exact-ID dictionary deduplication in `source_lineage_contract_v1`; it is not a four-source or real forwarding-chain experiment.
- The USGS row's `UNKNOWN` lineage value is copied from the prior read-only audit summary. That row was not passed to `assess_source_lineage` as a complete graph. No real replay, source lineage, or risk-confidence increase/decrease was measured.
- `NO_INCREMENT_FROM_EXACT_DUPLICATE_ASSERTIONS` is a narrow interpretation of unchanged graph-contract outputs. No risk-confidence function or numeric confidence score ran.
- The prior figure's `t+0s`, `t+1s`, and `t+2s` markers are illustrative synthetic copy markers only. The contract's fourfold case is repeated assertions inside one left-side graph; the two counts are not linked.

The follow-up [local controlled replay probe](../local-replay-lineage-20261012/REPORT.md) hashes the exact saved **normalized sample file bytes**, records a new local replay receipt time, and compares the same alias transform with lineage retained versus omitted. Those hashes and receipts do not recover the missing original USGS response bytes or historical collector receive time.
