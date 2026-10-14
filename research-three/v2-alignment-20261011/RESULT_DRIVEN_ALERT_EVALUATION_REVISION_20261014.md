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

## Follow-up regression hardening (2026-10-14)

A Library-provided synthetic regression harness (`review_fixed_regressions.py`, SHA-256 `a818a4c1deec6d30f42c1715a9f08a807be3afa0104d074c495debf00cd9d2ab`) exposed two receipt-validation gaps and false-positive qualification cases. Before the fix, empty execution-environment provenance, an empty command, and a PASS receipt with its progress/event journals and 80 container-ID files removed were accepted. The mocked connection-refused, timeout, and unreachable cases also exited zero when a canary exception had no errno and the fake socket could not establish a positive control.

The follow-up adds a same-identity host-canary read baseline without permission changes, explicit canary errno/reason evidence, a loopback network positive control, and accepts external unavailability only for `ENETUNREACH`/`EHOSTUNREACH`. Complete PASS receipt validation now binds nonempty Linux/Python/Docker provenance and the run ID in the command, and independently requires progress, the ordered 320-event journal, and all 80 container-ID artifacts with matching slot IDs and configuration/completion evidence. The harness's old fake socket cannot execute `bind`/`listen`; its network cases therefore report `CONTROL_SETUP_FAILED` and exit 41, which is correct `NOT_VERIFIED` behavior. Its synthetic canary `PermissionError` has no numeric errno, so it is recorded as `FILE_PROBE_ERROR`; a dedicated unit case separately exercises errno 13 (`EACCES`) and verifies it is not treated as path isolation.

The post-fix CPU package suite passes 50 isolated unit tests, all seven Draft 2020-12 schema definitions pass meta-validation, and a complete synthetic receipt validates against `attempt.schema.json`. A follow-up producer/validator seam check first reproduced a missing `output_bytes_captured` field in the real `_execute_task` terminal progress path, then passed after adding the runner's captured-byte counter; the complete synthetic return fixture now writes progress through `_write_progress` before validation. The harness reports a valid synthetic complete PASS, a valid partial FAIL, rejects all 22 receipt corruption cases, accepts the normal mount positive control, rejects five protected-path overlap mounts, and returns diagnostic exit 41 for all three old fake-socket network cases. These are software/mocked results only. They do not qualify a real Docker host, a Mac repair, a user-visible delivery path, or the blocked 80-slot task. The pre-fix red baseline, final review report, and follow-up summary are stored beside the package as `QUALIFICATION_RETURN_REVIEW_20261014_PRE_FIX.json`, `QUALIFICATION_RETURN_REVIEW_20261014_R3.json`, and `FOLLOWUP_FIX_RESULTS_20261014.json`.
