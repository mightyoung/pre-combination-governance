# Conservative source-lineage scoring policy V2

**Status:** `FROZEN_PRE_RUN`. This policy supersedes the interpretation used by V1 scoring only for new V2 outputs. V1's original result remains unchanged and is corrected by a separate addendum.

## Hash-only evidence

- Equal SHA-256 values establish byte equality for the compared saved payloads, subject to the usual hash assumptions. They do **not** establish a shared upstream source, common collection path, or common event.
- Different SHA-256 values establish byte inequality. They do **not** establish different sources, different events, or statistical independence; transformations can change bytes while preserving a lineage.
- The hash-only baseline may report `BYTE_IDENTICAL_ONLY` or `BYTE_DIFFERENT_ONLY` as a content observation. Its source-lineage outcome is `UNKNOWN` in either case, with a reason that says no provenance edge was supplied.
- Missing capability to infer lineage is not scored as a wrong source attribution.

## Receipt-supported evidence

- A complete, locally consistent chain can return `SHARED_KNOWN_ANCESTOR` for the explicit ancestor represented in the supplied graph. For this controlled run, receipt status means only consistency under the local runner and its input-read ledger; it does not authenticate a publisher, original source, or historic transport.
- A missing receipt, invalid receipt, or input read not listed in a receipt returns `UNKNOWN`. It is never converted to an independent-source claim.
- `NO_SHARED_KNOWN_ANCESTOR`, if encountered later, remains a bounded statement about the supplied complete graph; it is not `DIFFERENT_SOURCE` or statistical independence.

## Measures and accuracy gate

For the fixed three pair rows in this one chain, report raw counts of supported shared-ancestry results and `UNKNOWN` results per condition. These are coverage/abstention counts within one synthetic world, not independent observations, rates, or effect estimates. Record byte equality/inequality separately from lineage status.

Only call an attribution wrong when an evidence-backed method claim conflicts with an independently adjudicated truth record. A production verifiable-accuracy result requires a bounded production replay log, an independent truth denominator, and evidence that the log's pair mapping was not supplied to the method. If any of those are missing, report `NOT_COMPUTABLE`/`NOT_EVALUATED`, not zero errors. The current production truth denominator is zero.

The scorer-side synthetic fixture documents the constructed parent relationship but is not an independent production truth source. It may be read after method-output freeze for fixture audit only; it must not be used to claim production accuracy.
