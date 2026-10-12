# Synthetic mixed-stream gate result

## Scope

This is a pure-software boundary check of unversioned messages arriving after a versioned notice has been accepted for a stable display card. Inputs are explicitly synthetic, use one source label per scenario, and do not assert source independence or physical event truth. The code commit is `cb3468e4842ea4cab29246ee2c36b2348efad2ec`.

The policy records every unversioned arrival in an audit trail without changing the versioned card's content, revision history, lifecycle, or notification action count. A higher known risk signal creates a separate `PENDING_VERIFICATION` review record. That review is unconfirmed, does not emit a notification, and does not restore a cancelled card. Exact and semantic duplicates add audit traceability without creating another pending review. A missing risk-grade claim is recorded as `UNKNOWN`; a separately mapped single risk flag is retained as a distinct risk signal and can only open an unconfirmed review.

## Results

The new run matched all frozen V2 expectations and both saved legacy negative controls. The legacy values below are read from `LEGACY_MIXED_BASELINE.json`; the gate values come from `RESULT.json`.

| Synthetic scenario | Legacy actions / revisions / lifecycle | Gate actions / revisions / lifecycle | Audit records | Pending reviews |
|---|---:|---:|---:|---:|
| Active versioned card | 2 / 6 / ACTIVE | 1 / 1 / ACTIVE | 6 | 2 |
| Cancelled versioned card | 3 / 3 / ACTIVE | 2 / 2 / CANCELLED | 1 | 1 |

The active-card stream included lower, equal, and higher synthetic grades, an exact replay, a semantic alias, and a missing explicit grade with a mapped high-risk flag. The missing claim remains `reported_risk_grade: UNKNOWN`; the separate single-flag signal is `CRITICAL` and remains pending review. The cancelled-card case retained `CANCELLED` after an unversioned high-risk message. In both cases, no unversioned message created a card revision or notification. Delivery is `NOT_DELIVERED`; `emitted_at` and `visible_at` remain null.

The pre-run V1 fixture failure remains preserved in `FIXTURE_VALIDATION_FAILURE_V1.json`: the synthetic low-claim case supplied an empty `risk_flags` tuple, and `ActionIntent` rejected it before the mechanism produced a result. `INPUT_AND_EXPECTATIONS_V2.json` changes only that input shape to a non-empty unmapped synthetic flag (plus revision metadata); its expected arrays and direct-apply negative-control arrays are unchanged from V1. The frozen V1 file and failure record were not edited.

The 1,464-check Mac V3-RSS trial remains a failed historical run, with 20 method records lacking a confirmed new-event first alert. This work did not rerun it, treat the 20 records as independent samples, or validate the Mac's `ESRCH` / `EPERM` exit. The prior direct-apply baseline was executed on the corrected synthetic fixture and is preserved separately; it is not a rerun of the Mac trial.

## Verification

Ran only these isolated development tests after the code change:

```sh
cd risk-fusion-bench
PYTHONPATH=src python -m unittest -v tests.test_alert_action_experiment tests.test_event_card_integration
```

Result: 28 tests passed. The focused suite checked card history, audit receipt IDs and processing times, risk-grade semantics, review status, and non-overwrite behavior. `git diff --check` also passed before the implementation commit. The pilot runner consumed only the frozen `INPUT_AND_EXPECTATIONS_V2.json` and compared each expected status/count/risk field, lifecycle, pending review state, non-delivery, and saved negative-control arrays. No model, network service, external application, notification adapter, device, executor, or credentials were used.

## Limits and next work

- The fixture treats versioned notices as trusted by construction. Producer authorization, version authenticity, and real monotonic ordering have not been verified.
- `LOW`, `WARNING`, and `CRITICAL` are fixture-only comparison labels. They do not define production risk semantics or a multi-flag aggregation rule.
- Pending review is only an internal software record. Its later evidence gate, user-visible behavior, and confirmation/escalation path are not evaluated here.
- This run does not measure reminder timeliness, content completeness, or event-confirmation accuracy. No delivery or visibility timestamp exists, so real timeliness is unknown. Those three outcomes must be evaluated separately in a later protocol.
- The full private Mac V2 package is not present. To reconcile private rules, the minimum required materials are the exact-version main specification, field/schema definitions, metric definitions, and version/revision manifest or authority contract. The public sanitized V2 contract remains sufficient for this bounded synthetic work; missing private files were not guessed.

Next executable chunk: freeze the producer version-authority contract and the pending-review resolution rule, then add synthetic tests for unknown comparison state, review resolution without identity auto-confirmation, and a subsequent DIFFERENT split retaining bidirectional card-history links. Keep reminder timeliness, content completeness, and event-confirmation accuracy in separate scorers; if a run has no visibility receipt, report timeliness as unknown/censored rather than substituting simulated processing time.

## Artifacts

- `INPUT_AND_EXPECTATIONS.json`: frozen V1 fixture, retained with its observed validation failure.
- `INPUT_AND_EXPECTATIONS_V2.json`: corrected input shape with unchanged expected arrays.
- `LEGACY_MIXED_BASELINE.json`: saved pre-gate direct-apply result.
- `RESULT.json`: current synthetic run, saved baseline comparison, and frozen expectation checks.
- `MIXED_STREAM_COMPARISON.svg`: offline, synthetic before/after visualization.
- `RUN_MANIFEST.json`: run artifacts and source hashes.
- `MAC_PERSISTENCE_MANIFEST.json`: repository-relative persistence list; Mac checkout root is unspecified (`null`).
