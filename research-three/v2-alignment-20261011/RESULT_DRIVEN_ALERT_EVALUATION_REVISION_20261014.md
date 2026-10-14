# Result-driven alert-evaluation revision — 2026-10-14

**Status:** revised from the failed Mac V3-RSS trial; exact Mac V2 contract is still required before a new metric run.

## Preserved result

The earlier Mac V3-RSS attempt remains **1,464 checks executed, whole attempt FAILED**. Its five synthetic scenarios crossed with four methods yield 20 method records, not 20 independent samples. All 20 records lacked a confirmed new-event first report. Internal review data included an `EXPOSURE` risk flag, but the record did not establish a reminder level, user-visible message, delivery time, or stable display-card ID. This revision does not rewrite those outcomes or infer missing values.

## Requirements derived from that failure

1. A newly observed candidate event can receive a risk-first notice while identity is `UNKNOWN_PENDING` or `CONFLICT_PENDING`; unresolved identity does not suppress the risk review.
2. Each candidate episode remains independently addressable. A stable display-card ID preserves the review thread, while that display ID does not itself prove event equivalence.
3. A later same-event confirmation updates the existing card. A different-event decision creates a distinct card and reciprocal history links. Both transitions require explicit evidence and non-retroactive evidence/resolution times; uncertain identity never triggers a blind merge.
4. Each notice exposes its level, user-visible text, stable card ID, risk and identity state, evidence references, and the available source/observed/trigger-known/detected/received/emitted/visible times. A preview or software emission cannot stand in for transport delivery or user visibility.
5. Report the three requested dimensions separately: alert timeliness, content completeness, and event-confirmation accuracy. Keep `SIMULATED` and `NOT_DELIVERED` distinct from measured delivery. Pending identity pairs do not count as correct confirmations.
6. Preserve the old failed run and its original metric values. Any revised scenario set, sample unit, denominator, deadline, or completeness rule must be versioned as a new evaluation specification and must cite this failure as its motivation.

The repository already contains a software-only mechanism for stable candidate cards, risk-first synthetic notices, pending associations, evidence-backed confirmation/split, and separate timing/content/confirmation scorers. Its tests establish those code contracts only; they do not establish that the failed Mac V3-RSS path emitted the missing first reports or that real users received notices.

## Metric freeze boundary

The complete Mac V2 specification and its referenced definitions are not present in this cloud checkout. Therefore this revision does **not** invent or freeze a deadline, field denominator, adjudication rule, statistical unit, or aggregation formula. Before implementing a Mac V2 adapter or computing new scores, provide the exact unabridged V2 specification (including version/revision and a byte hash), its referenced alert/schema/data-dictionary and severity-map files, and the metric definitions or scoring code it cites. Keep any private originals in the Mac/private location; they are not part of this public branch.

For the already documented 1,464-check failure, an additional private payload is not needed to preserve the result above. If a later audit must map individual checks to the 20 method rows, the minimum extra artifact is a redacted index with stable row IDs and failure reasons, not the private source records.

## Next executable work

- Keep the old failure report and metrics unchanged; treat this file as an additive, result-driven specification revision.
- Once the exact Mac V2 contract is available, map its required fields and metric definitions onto the existing software-only card and scoring APIs, then add synthetic contract tests before any new run.
- Keep delivery marked `NOT_DELIVERED` until a real transport receipt and visible-time evidence exist.
- Separately, the paired-CPU execution package still blocks because its wall, memory, PID, and output caps are unprovided. Fill those values from an approved cloud profile before considering its fixed host qualification gate; no Docker probe or 80-slot run was performed for this revision.
