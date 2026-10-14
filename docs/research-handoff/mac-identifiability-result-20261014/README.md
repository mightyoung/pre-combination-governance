# Identifiability: saved synthetic diagnostic, discovered 2026-10-14

This increment follows [the original reviewed code/design snapshot](../mac-event-development-20261010/README.md), published at commit ed463fa208d3fcadf5c8cb1e0c4505f64d4e7ca2. That snapshot preserved the prepared state; this directory adds the subsequently discovered saved outputs and a read-only consistency audit without overwriting prior evidence. Algorithm/shared-gate/test/evaluator/launcher source is pinned under that commit's identifiability-v1-PREPARED-NOT-RUN directory. Input and code binding identities match; publication path redaction has separate public hashes and is not execution-ready portability.

Execution source and terminal top-level exit confirmation are PENDING. We only establish internally consistent saved child receipts/logs; no research was run while auditing or publishing. Child receipt records exit0, error null, CPU0.542084seconds and wall-before-receipt0.857483seconds. One consumed attempt, no retry. 6 pure gate test bundles +120 main +102 reference bundles=228; direct assess120. The saved test phase passes6 tests; 60DS+60 common-card+12 terminal assertion flags match (72 reference records,72DS inner groups). Reference matches are implementation contracts, not physical acceptance.

| Public evidence arm | First alert at prefix5 | Extra first alerts | Remaining failure |
|---|---|---|---|
| I1 continuing, no added information | not required | M0 prefix3 | M0 extra |
| I2 hidden new event, no added information | missed by all four | M0 prefix3 | four physical/first-alert misses |
| I3 qualified recovery | all four | M0 prefix3 | M0 extra |
| I4 explicit closed/open work rounds | all four | M0 prefix3 | M0 extra |
| I5 independent STOP→RUN transition | all four | M0 prefix3 | M0 extra |
| I6 invalid/stale/contradictory context | missed by all four | M0 prefix3 | four physical/first-alert misses; UNKNOWN_REVIEW |

I1/I2 input and full result values are identical for every method/prefix. I6 retains possible e and review, which does not count as successful physical/new-event alert. Exact first-alert acceptance and physical-notification acceptance are BOTH false; status DIAGNOSTIC_COMPLETED_WITH_ALERT_GAPS_NOT_SAFETY_ACCEPTANCE. Risk escalation cannot offset missing first alerts. Observed successful required alerts have zero logical-prefix delay; missed ones have null delay, never zero. No physical wall-latency inference.

Accumulated pair-record denominators are 120 per method: M0 decided116/rejected4, false_merge2/false_split62; M1/M2/M3 each decided108/rejected12, false_merge0/false_split0. These are sums across prefixes, containing repeated pairs; not independent samples or statistical superiority. Rejections do not disappear. All methods receive identical public evidence and the same gate; added synthetic external qualification/lineage/timing assumptions do not demonstrate realistic source reliability or D-S business benefit. Work-instance boundaries do not prove machine SAFE.

Bindings, prior raw four-file outputs for three runs, and frozen362 files match their retained hashes. Audit/CSV/parsed phases contain exact failures, uncertainty and denominators. No raw logs, host execution paths, credentials, private identifiers, private media or external datasets are uploaded. Original/raw source hashes and sanitized public hashes remain distinct. No OS file/network isolation; resource exhaustion/cleanup fault qualification and RSS unavailable. MME preregistration v2 NOT_LOCATED; D07 NOT_EXECUTED. Not a formal paper conclusion, original isolation protocol admission, safe deployment or calibration/significance claim. Do not rerun the consumed command.
