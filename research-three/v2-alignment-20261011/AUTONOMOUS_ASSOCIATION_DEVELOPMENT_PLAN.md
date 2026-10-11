# Observable-Only Association Development Plan

> **For agentic workers:** Implement this plan task by task with test-first changes. This plan records a small synthetic development check, not a blind efficacy study.

**Goal:** Add two deterministic, observable-only association proposal methods and test that they respect field availability, avoid replay reinforcement, keep nearby assets separate, and recognize an observed recovery boundary.

**Architecture:** A new research module accepts only timestamped observable field records, freezes a known prefix, builds one method-independent candidate-pair universe, and evaluates that universe with a time/asset baseline and a multi-evidence rule. Outputs are immutable candidate proposals; only `LINK_CANDIDATES` is adapted to the existing `AlertLedger.propose_association()`, which leaves identity pending. Truth and first-sufficient-evidence times stay in test-only scorer fixtures and are consulted only after the proposal bytes are frozen.

**Tech Stack:** Python 3.11+, dataclasses, standard-library JSON/hash/time helpers, existing `rfb.research.alert_governance.AlertLedger`, `unittest`.

**Spec:** User's 2026-10-11 follow-up requirements in the delegated task; this file is the saved implementation plan for that bounded development stage.

## Global Constraints

- Keep the work on `task/research-three-v2-alignment-20261011`; do not merge into `main`.
- Use only the two requested synthetic world families: persistent same-asset temperature/thermal observations, and adjacent abnormal assets plus recovery followed by reappearance.
- Synthetic numeric settings below are test fixtures only; they are not operating limits, safety thresholds, or production defaults.
- The algorithm input allowlist is record-level `observation_id` and `received_at`, plus field-level `asset_id`, `asset_binding_status`, `modality`, `value`, `unit`, `value_error`, `position_m`, `position_error_m`, `quality_status`, `calibration_status`, `source_time`, `risk_flag`, and `acquisition_lineage`. The observation ID and every field carry `actual_available_at` and `earliest_known_at` provenance; the receipt field's actual/known time is its own `received_at` value.
- For every field, reject `earliest_known_at < actual_available_at`; expose a field to an inference prefix only when `earliest_known_at <= as_of` and its record has arrived by `as_of`.
- The algorithm input must reject scenario/world labels, future endpoints, hidden truth, event/episode/card/association IDs, and identity labels. It must not import or call `frozen_prefix_adapter.py`.
- Rule outputs are limited to `LINK_CANDIDATES`, `RETAIN_SEPARATELY`, and `ABSTAIN`; none is a truth label. A rule result cannot resolve an identity or mark an alert confirmed.
- Candidate generation is shared by both rules. Exact transport replays collapse by observation ID and immutable measurement content; changed content under an existing observation ID fails closed, except a later `risk_flag` revision which remains one observation and one acquisition lineage.
- The multi-evidence rule only uses the same allowed fields and candidate pairs as the baseline. Unknown or conflicting dependencies abstain; nearby verified asset IDs that differ are retained separately; risk escalation within one lineage does not add independent-source support.
- Dempster-Shafer is represented only by the shared `AssociationMethod` protocol. Do not implement or run it in this stage.
- Test-only world truth and first-sufficient-evidence times are not reachable from inference functions. Serialize/hash algorithm output before scorer code receives its separate truth fixture.
- Scoring uses a fixed pre-inference universe of unique, non-replay candidate pairs. False-merge and false-split rates both use that full denominator; abstentions are reported separately and never count as correct. Report independent world count separately from pair count.
- Do not run a formal blind test, large sweep, paid service, real notification, old 1,464-check trial, Mac/device validation, or executor qualification probe. Do not alter reminder policy to favor either association rule.

## Review Focus

- A field whose source time predates its arrival must not become visible before its declared earliest-known time.
- A forwarded/replayed observation or a higher risk flag from one acquisition lineage must not manufacture independent-source support.
- A future suffix, including a late observation, must not affect a fixed `as_of` proposal output.
- Direct construction, `dataclasses.replace`, and rule/candidate consumers must reject a prefix containing an observation ID, record receipt, or field fact that was not available by `as_of`.
- Identifier spelling must not affect proposals when identifiers are changed by a consistent bijection.
- Spatial proximity between adjacent pumps must not override verified asset mismatch; missing/low-quality asset binding must abstain.
- A visible recovery between abnormal observations must prevent a cross-recovery link even when the same asset reappears within the synthetic candidate horizon.
- An all-abstain method must have zero coverage and nonzero unresolved count, not a perfect score.

---

## Interface Decisions

Create `risk-fusion-bench/src/rfb/research/observable_association.py` with these public types and functions:

- `KnownField(name: str, value: JSONScalarOrTuple, actual_available_at: str, earliest_known_at: str)` validates its allowlisted field name, value shape, UTC timestamps, and `earliest_known_at >= actual_available_at`.
- `ObservationRecord(observation_id: str, id_actual_available_at: str, id_earliest_known_at: str, received_at: str, fields: tuple[KnownField, ...])` contains no scenario or identity metadata. The same observation ID may have repeated identical records from forwarding/replay and a later `risk_flag` fact; incompatible immutable measurement content raises `ValueError`.
- `FrozenObservation(observation_id: str, received_at: str, fields: tuple[KnownField, ...], id_actual_available_at: str, id_earliest_known_at: str)` retains observation-ID availability provenance with the latest non-conflicting field values. Direct instances that omit the optional ID times conservatively set them to `received_at`.
- `FrozenObservablePrefix(as_of: str, observations: tuple[FrozenObservation, ...])` is the only inference input; direct construction, replacement, candidate generation, and rule lookup validate all retained availability times against `as_of`.
- `InferenceConfig` holds only clearly labeled synthetic-development values: `candidate_pair_window_seconds=120`, `same_asset_candidate_horizon_seconds=600`, `candidate_radius_m=8.0`, `position_margin_m=1.0`, and `value_tolerance_c=2.5`.
- `CandidatePair(left_observation_id: str, right_observation_id: str)` and `ProposalAction` (`LINK_CANDIDATES`, `RETAIN_SEPARATELY`, `ABSTAIN`) contain no event/episode/card/association identifier or truth field.
- `AssociationProposal(method: str, pair: CandidatePair, action: ProposalAction, reason_codes: tuple[str, ...], evidence_refs: tuple[str, ...], independent_lineage_root_count: int, decided_at: str)` is a frozen, explainable output.
- `AssociationMethod` protocol defines the callable contract `(prefix, pair, *, config) -> AssociationProposal`; the two rule functions implement this contract. The protocol is the only Dempster-Shafer deliverable.
- `freeze_observable_prefix(records, *, as_of) -> FrozenObservablePrefix` filters by ID/field earliest-known time and record receipt, merges later field facts by known time, deduplicates exact replay by observation ID/content, and rejects conflicting immutable content or ambiguous same-time values.
- `build_candidate_universe(prefix, *, config) -> tuple[CandidatePair, ...]` builds one deterministic pair set from known abnormal observations using time/position proximity or a common verified asset inside the synthetic horizon. It does not consult rule outputs or scorer truth.
- `time_asset_rule(prefix, pair, *, config) -> AssociationProposal` uses verified asset binding, source-time proximity, position/error compatibility, and visible recovery boundaries; missing dependencies return `ABSTAIN`.
- `multi_evidence_rule(prefix, pair, *, config) -> AssociationProposal` applies the same hard guards, then requires valid quality/calibration, compatible units and measurement errors, complementary temperature/thermal modalities, positive risk flags, and distinct acquisition roots before proposing a link.
- `freeze_proposals(proposals) -> FrozenAssociationOutput` canonicalizes and hashes method outputs without truth fields.
- `apply_proposal_to_alert_ledger(proposal, ledger) -> EventAssociation | None` calls only `propose_association()` for `LINK_CANDIDATES`; `RETAIN_SEPARATELY` and `ABSTAIN` return `None`. It never calls `resolve_association()`.

The rule baseline returns `RETAIN_SEPARATELY` for two verified but different assets, or for an observed recovery boundary. The multi-evidence rule follows those same guards and may link only when its distinct-source evidence conditions hold. The two arms receive the identical prefix and candidate universe.

## Synthetic Development Scenarios

1. **Persistent pump signal:** A temperature sensor and thermal imager observe one verified asset with compatible positions, units, quality, calibration, and source times. Include an exact forwarded replay, a delayed thermal record whose `received_at` is after an earlier cutoff, and a later `EXPOSURE_HIGH` risk-flag fact tied to the temperature lineage. Check replay count/source support, prefix invariance, a link proposal when complementary evidence is visible, and no extra lineage support from the flag escalation.
2. **Adjacent assets and recurrence:** Two verified neighboring assets produce simultaneous abnormal readings and enter the shared candidate universe; both rules must retain them separately. On one asset, a `RECOVERY` fact between two abnormal facts must cause a separate proposal rather than a cross-recovery link.

The unit fixtures contain complete synthetic worlds for scorer use, but inference receives only their observable records. The old notification-action count of 23 is not reused as a sample or denominator.

## Tasks

### Task 1: Observable boundary and time-prefix tests

**Files:**
- Create: `risk-fusion-bench/tests/test_observable_association.py`
- Create later: `risk-fusion-bench/src/rfb/research/observable_association.py`

**Interfaces:**
- Consumes: no existing prefix adapter; tests construct only `KnownField` and `ObservationRecord` values.
- Produces: `freeze_observable_prefix(records, *, as_of)` and the immutable prefix types used by both inference arms.

- [x] Write `test_rejects_forbidden_fields_and_metadata`, `test_rejects_earliest_known_before_actual_availability`, and `test_late_source_fact_is_hidden_until_received` first.
- [x] Run those tests and confirm they fail because the new observable boundary is absent.
- [x] Implement only allowlist validation, timestamp checks, prefix filtering, replay deduplication, and conflict rejection.
- [x] Run the three tests; all pass.

### Task 2: Shared candidate universe and deterministic rule arms

**Files:**
- Modify: `risk-fusion-bench/tests/test_observable_association.py`
- Modify: `risk-fusion-bench/src/rfb/research/observable_association.py`

**Interfaces:**
- Consumes: `FrozenObservablePrefix` from Task 1.
- Produces: `InferenceConfig`, `CandidatePair`, `ProposalAction`, `AssociationProposal`, `AssociationMethod`, `build_candidate_universe`, `time_asset_rule`, and `multi_evidence_rule`.

- [x] Add failing tests `test_same_cutoff_output_is_independent_of_future_suffix`, `test_opaque_identifier_bijection_preserves_normalized_proposals`, `test_duplicate_forwarding_does_not_increase_lineage_support`, `test_persistent_cross_modal_same_asset_becomes_link_candidate`, `test_single_source_risk_flag_escalation_does_not_add_support`, `test_adjacent_verified_assets_are_retained_separately`, `test_recovery_boundary_retains_reappearing_anomaly_separately`, and `test_methods_share_exact_candidate_universe`.
- [x] Run each new behavior test and confirm the failure is due to missing inference behavior.
- [x] Implement one candidate universe shared by both rules; implement the baseline hard guards and the multi-evidence requirements from Interface Decisions. Keep synthetic values in `InferenceConfig` and label them non-production.
- [x] Run the new rule tests; identical prefixes/results at one cutoff, stable normalized results after identifier bijection, no replay reinforcement, no adjacent-asset link, and no link across recovery pass.

### Task 3: Frozen output, scoring boundary, and existing-ledger handoff

**Files:**
- Modify: `risk-fusion-bench/tests/test_observable_association.py`
- Modify: `risk-fusion-bench/src/rfb/research/observable_association.py`
- Test-only scorer remains inside `risk-fusion-bench/tests/test_observable_association.py`.

**Interfaces:**
- Consumes: immutable `AssociationProposal` values and the existing `AlertLedger` API.
- Produces: `freeze_proposals()` and `apply_proposal_to_alert_ledger()`; no production scorer and no reminder-policy changes.

- [x] Add failing tests `test_link_proposal_only_creates_pending_alert_ledger_association` and `test_frozen_output_scorer_uses_full_universe_denominators`.
- [x] In test-only scorer fixtures, keep `world_group`, pair truth, and `first_sufficient_evidence_at` separate from observable records. Freeze/hash rule output before calling the scorer.
- [x] Confirm both false-merge and false-split denominators use the full pre-fixed non-replay pair universe, unresolved count is separate, and an all-abstain output has zero coverage.
- [x] Implement the minimal ledger adapter; a link proposal may create a `PENDING` association only. Retain and abstain proposals do not mutate the ledger.
- [x] Run the new tests and the relevant existing ledger characterization tests; no confirmed identity state or reminder behavior changes are observed.

### Task 4: Documentation, bounded verification, and independent review

**Files:**
- Modify: `research-three/v2-alignment-20261011/README.md`
- Modify: `research-three/v2-alignment-20261011/MAC_PERSISTENCE_MANIFEST.json`
- Modify: this plan with actual execution evidence and artifact hashes.

- [x] Add the module, test command, synthetic-only limits, and no-formal-study boundary to the README.
- [x] Run only the new inference unit tests and directly relevant pure-software ledger tests; no executor probes or the complete unrelated research suite were run.
- [x] Record exact command, test count, actual failures observed during RED, final result, source/input hashes, and deviations here.
- [x] Verify every listed manifest file hash and `git diff --check`; commit only this independent research branch.
- [x] Initial independent research branch push was read back at `02d40d0f9583ffc0ca4da4066d208d4c6299627b`.
- [x] Push the I1 fix and refreshed evidence/manifest, then read back the final remote SHA.
- [x] Request an independent review of the plan, code, and test evidence before reporting completion. Fix important findings test-first.

### Execution Evidence (2026-10-11)

- Initial loader invocation from the repository root used module-qualified `tests.*` names and failed with `ModuleNotFoundError: No module named 'tests'` (three unittest loader errors). The commands were corrected to run with working directory `risk-fusion-bench/`; all final commands below use that directory.
- Test-first RED evidence before `observable_association.py` existed: the three boundary tests failed at the guard assertion because the observable API was absent. Before inference implementation was complete, one inference API test failed at the corresponding missing-API guard. These were expected development failures; the full traceback was not preserved in the handoff. No RED result is claimed for the two audit-only characterization tests added after implementation: `test_uncertain_asset_binding_and_degraded_quality_abstain` and `test_changed_measurement_under_same_observation_id_fails_closed`.
- Final command `PYTHONPATH=src python -m unittest -v tests.test_observable_association` from `risk-fusion-bench/`: **16 passed** in the prior implementation commit. It covered both synthetic world families, prefix/ID invariants, exact forwarding replay, late arrival, same-lineage risk escalation, adjacent verified assets, unverified asset abstention, degraded-quality abstention, recovery/reappearance, immutable-content conflict rejection, shared candidate set, output freeze/scorer contract, and pending-only ledger handoff.
- Final command `PYTHONPATH=src python -m unittest -v tests.test_alert_governance tests.test_alert_governance_idempotency` from `risk-fusion-bench/`: **29 passed**. Existing stable-card, pending identity, resolution/split, escalation, idempotency, and emission-versus-delivery characterization tests pass unchanged.
- `git diff --check`: passed. No formal/blinded scoring run, broad suite, old 1,464-check trial, Mac/device test, transport or executor probe, model/network call, payment, install, or credential access was used.
- Synthetic test inputs are constructed in `risk-fusion-bench/tests/test_observable_association.py`; they are not measurements or production thresholds. Source/test SHA-256 values and the exact persisted artifact list are bound in `MAC_PERSISTENCE_MANIFEST.json` after final code review.
- Deviation: the two extra boundary characterization tests were added after the original implementation was green to make unknown dependencies and changed-content replay rejection explicit. They passed without code changes; they are not part of the recorded RED stage.
- Independent review of code commit `27ceb16110d31c1e194c4328b684cb65dd0ab681` found no important implementation correctness issue. It identified that the baseline lacked a positive-link assertion; commit `72944b6fcbb57719b32f3377de12f1f2bdb7574c` adds that assertion to the existing cross-modal test, and the focused 16-test suite passes. The review also noted that the manifest was absent from the reviewed code commit; the separate manifest commit `fc9d6e31af40783248ba9b15805137516fbdeda9` added it and verified all 38 listed file hashes. This review scope does not claim efficacy; the scorer remains a fixed-pair denominator/abstention contract check only.
- Follow-up I1 reproduction: from a valid `as_of=12:00:20` prefix, `dataclasses.replace(prefix, as_of=12:00:00)` retained records received/known at 12:00:10 and 12:00:11; the candidate builder returned a pair and both rules returned `LINK_CANDIDATES`. Root cause: `FrozenObservablePrefix` had no construction invariant or consumption revalidation, and `FrozenObservation` did not retain ID availability times.
- I1 RED command ran four targeted tests. It failed with seven expected failures: two direct-prefix cases did not raise `ValueError`, the ID-time test showed `FrozenObservation` lacked ID availability fields, `replace` did not raise, and candidate generation plus both rules accepted the invalid prefix. No unrelated test or trial was run.
- I1 fix retains ID actual/earliest-known times in `FrozenObservation` (legacy manual construction defaults them conservatively to receipt time), validates ID/receipt/field visibility when prefixes are constructed or replaced, and revalidates on `observation()`, candidate generation, and rule consumption. The targeted four tests then passed; final `tests.test_observable_association` run: **20 passed**; existing ledger regression command: **29 passed**; `git diff --check` passed.
- Independent review found no important implementation issue and noted one nonblocking positive-path coverage gap. Commit `4ae8a475cd0dd0462406c8f2fd6582b110ccf5fd` closes it: `test_late_source_fact_is_hidden_until_received` now asserts that the factory preserves both ID availability times and that a later valid `as_of` replacement keeps the same observations and ID-known time. The targeted test passed; the full focused commands still pass at 20 association tests and 29 ledger tests.
- The I1 RED command and root-cause reproduction are recorded above; implementation and regression tests are committed as `29095d8e127c99dd9d397a3e70b3a85a1325d0d5`, with the positive-path assertions in `4ae8a475cd0dd0462406c8f2fd6582b110ccf5fd`. The exact `replace(..., as_of=12:00:00)` reproduction now raises `ValueError: observation ID was not known by prefix as_of` instead of returning linked proposals.
- I1 validation remains synthetic-only. It did not run the 1,464-check trial, Mac/device validation, blind evaluation, broad suite, transport, model/network, or executor paths.

## Verification Commands

Run from `risk-fusion-bench/`:

```sh
PYTHONPATH=src python -m unittest -v tests.test_observable_association
PYTHONPATH=src python -m unittest -v tests.test_alert_governance tests.test_alert_governance_idempotency
```

The second command is the existing reminder/association characterization boundary; it does not run the old frozen experiment or any device/transport path.

## Formal Evaluation Gate

This stage does not estimate efficacy. Before a blinded evaluation, submit the independent-world generation procedure, seed policy, sample/budget, candidate-universe rules, rule parameters, scorer contract, and stopping/holdout split to the parent for review. Keep scorer truth and first-sufficient-evidence records sealed until each method's canonical output is hashed. Do not change the existing reminder policy after observing new rule outputs.

## Subsequent task: finite synthetic evaluation contract (2026-10-11)

### Outcome

- Added [`FINITE_SYNTHETIC_EVALUATION_PROTOCOL_DRAFT.md`](FINITE_SYNTHETIC_EVALUATION_PROTOCOL_DRAFT.md) as `REVIEW_DRAFT`; it freezes four strata, 12 development worlds, 24 reserved held-out worlds, public deterministic seeds, zero hyperparameter-search slots per arm, a fixed six-pair universe, UNKNOWN treatment, time-to-correct-decision/right-censoring, separate alert escalation scoring, and whole-run stop conditions.
- Added `risk-fusion-bench/src/rfb/research/observable_association_evaluation.py`, a standard-library-only generator/scorer contract. Each cutoff materializes one visible prefix and candidate set shared by both fixed rule arms; outputs are frozen before the scorer sidecar is read. Formal split sidecars must include all six pairs among four abnormal observation IDs and the registered UNKNOWN count. World aggregation rejects duplicate world groups and mixed splits.
- Added `risk-fusion-bench/tests/test_observable_association_evaluation.py` with seven test methods. Tests use only single-world `contract_test` fixtures and assert deterministic generation, label isolation, late-known facts, replay/root behavior, fixed denominators, timing/censoring, separate alert escalation, split gates, and the formal scorer/aggregation guards.
- Linked the protocol and implementation from the research README. The Mac persistence manifest is refreshed after code review and commit, with local-relative paths and SHA-256/byte-size entries; it intentionally does not conflate cloud paths with a Mac checkout root.

### Test-first evidence and execution boundary

- Initial RED: six evaluation tests failed because the requested module did not exist. Adding the late-known-fact contract produced its expected RED before implementation; the separate alert-action input assertion also first failed because `score_world` did not yet accept an alert trace.
- After the first implementation, two additional negative assertions exposed missing fail-closed checks: a manually incomplete formal split could shrink the fixed pair denominator, and aggregation could mix development with held-out scores. Both failed before the guards were added and passed afterward.
- Final focused command from `risk-fusion-bench/`: `PYTHONPATH=src python -m unittest -v tests.test_observable_association_evaluation` — **7 test methods passed**.
- Final combined command: `PYTHONPATH=src python -m unittest -v tests.test_observable_association tests.test_observable_association_evaluation` — **27 tests passed** (20 existing association tests + 7 evaluation contract tests).
- `tests.test_alert_governance tests.test_alert_governance_idempotency` were not rerun in this stage because no ledger code changed; the prior 29-test pass remains historical evidence. The user-provided independent retest summary for commit `dadffcd…` (20 association + 29 ledger, plus 10 negative cases) remains labeled as a handoff summary, not a current-session run.
- No registered 12-world development or 24-world held-out split was generated or scored; no parameter search, Mac/device/real-delivery validation, original 1,464-check trial, model/network call, or untrusted payload/runner qualification occurred. Public seeds mean the reserved held-out split is procedural rather than cryptographically blind. The earlier Mac V3-RSS whole-trial failure and its denominator limitation remain unchanged in the protocol's historical evidence section.

### Review gate

Submit this protocol and implementation for independent review before any formal split generation. Review must address scorer denominators, truth isolation, candidate parity, world independence, timing/censoring, stop conditions, and whether the declared budgets match the code. Any fix requires a focused RED-to-GREEN test and a new reviewed protocol/code SHA before held-out data is generated or scored.
