# Mac event development: verified synthetic runs and prepared identifiability trial

Published incrementally on the existing task/research-handoff-v1 branch. Source research commit: a21866022ba9ec08a1a5edf4a321718d633a2ab1. Publication base: a6c46e97b64e866f4a421a28409ced45e058694f; main read-only snapshot: 5874906ce19e836083b99954b4a7a972b8eec5bb. Existing remote edits remain intact; only this new directory is added.

These are manually executed, CPU-only synthetic development diagnostics under an explicitly degraded protocol without OS file/network isolation. They are not original isolation-protocol qualification, formal paper conclusions, MME preregistration v2 admission, D07, calibration, significance or deployment acceptance. MME v2 was not located and D07 was not executed. The earlier strict isolation startup failed before scientific calculation; failures remain in history. No re-execution occurred while preparing this publication.

| Version | Test bundles | Main slots | Reference bundles | Total | Actual assess calls including tests | CPU seconds | Wall before receipt seconds | Child exit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| degraded-v1 | 18 | 120 | 102 | 240 | 122 | 0.217948 | 0.233876 | 0 |
| notification-revision-v1 | 2 | 40 | 34 | 76 | 120 | 0.666999 | 2.796694 | 0 |
| notification-boundary-v1 | 5 | 100 | 85 | 190 | 106 | 0.293847 | 0.301430 | 0 |

Each run was separately authorized and had one attempt/no retries. 506 bundles across these runs is not one pooled experiment or a statistical sample size. Bundle counts include reference bundles and do not equal assess calls. See saved audits for inner reference assertions and denominators. Resource faults/cleanup under exhaustion remain unqualified; RSS was not measured. Timings are local diagnostics.

## Findings and limitations

The first run exposes uncertainty and repeated notification behavior, with rejected pairs kept in denominators. The notification revision separates new-event first alerts, risk escalation, handling follow-up and card updates; the uncertainty candidate retains e as possible, and does not prove continuing-event identity. N1 suppresses a repeat for M1–M3, N2 still reports escalation; M0 extra alerts remain. Fixed hand cases do not establish general safety or D-S business advantage.

The boundary run tests a distinct asset/task, recovery then recurrence, risk downgrade then upgrade, and an indistinguishable pair B4/B5. B4 continuing and B5 genuinely new hidden event have identical public inputs and result values. All four methods miss the B5 required physical alert at prefix 5. M1–M3 review metadata is not a physical-alert success; M0 extras remain. B2 prefix 2 stays UNKNOWN, not SAFE. The actual receipt has physical_notification_acceptance=false and DIAGNOSTIC_COMPLETED_WITH_PHYSICAL_ALERT_GAPS_NOT_SAFETY_ACCEPTANCE. Child exit 0 only means diagnostic computation completed. Reference contract matches do not override physical failures. All raw uncertainty, risks, coverage/rejection, notifications and metrics are retained in parsed JSON and audits.

## Next trial: prepared, NOT RUN

identifiability-v1-PREPARED-NOT-RUN retains the indistinguishable baseline and individually adds recovery evidence, explicit closed/open work rounds, and an independent source transition, plus invalid/contradictory records. All methods receive equal public information and a common gate. Hand physical labels are separated from algorithm input; AI-assisted non-author review is not independent blind ground truth. Qualified/independent flags, logical freshness and work-round semantics are synthetic assumptions, not verified reliability. Six gate bundles + 120 main + 102 reference = 228 planned bundles. It has no execution receipt. Final static review corrected the receipt so first-alert acceptance is independent, exact-prefix/no-extra/zero-delay, and cannot be offset by escalation or review.

## Provenance and redaction

Only approved synthetic UTF-8 input/output and code are included. No raw logs, secrets, private media or external datasets are uploaded. Each actual-output phase JSON is parsed from a saved local stdout phase, not a rerun or reconstructed metric. Publication-manifest.json binds original local source SHA-256 and public sanitized SHA-256 separately; raw stdout is only represented by its hash. Host/runtime/temp paths and private artifact references are redacted. Bindings are historical byte identities; redacted launcher/runtime paths are placeholders and public copies are not execution-ready. Do not treat these bindings as portability or execution authorization. Local originals remain unchanged; exact local command and runtime are retained privately. Source hashes do not grant access to local artifacts or redistribution rights beyond this expressly authorized synthetic batch.
