# Pre-combination alert governance: design and implementation plan

## Purpose and evidence boundary

Implement a small, pure-software event-to-alert path with deterministic synthetic
inputs. The supplied handoff says the frozen Mac V3-RSS trial executed 1,464
checks but failed its round-level first-report criterion: five synthetic scenes
by four methods left 20 method records without a confirmed new-event first
report. Those method records are not independent observations. This document
preserves that result as a supplied historical fact; it does not rerun or
re-score that trial.

The complete Mac V2 specification and its exact original metric definition were
not found in this checkout. Nothing here claims to reproduce them. The design
below is a new, result-driven software evaluation specification whose measured
outputs are kept separate from the historical result.

## Bounded design

- Give each candidate event its own immutable candidate ID and deterministic
  display-card ID. Mutable alert text and revisions do not change that ID.
- Emit a precautionary, user-readable risk alert as soon as a candidate arrives.
  Include the current `EXPOSURE` risk flag, reasons, evidence references, event
  time, observed time, alert time, and explicit `SIMULATED` or `NOT_DELIVERED`
  status. No transport or device is called and no delivered receipt is
  fabricated.
- A possible identity link starts as `PENDING`; both cards remain independent.
  Resolving it as the same event updates one canonical stable card and retains
  the other card as an alias. Resolving it as distinct leaves both cards
  separate. A later evidence-backed split restores the original two card IDs
  and records the transition history.
- Keep the three measures separate: delivery-based alert timeliness (with
  emission latency reported separately and delivery timeliness unavailable
  without a delivery receipt), alert-content completeness, and pairwise event
  confirmation accuracy (pending pairs are reported as undecided, not counted
  as correct).
- Do not invent safety thresholds or claim device, Mac, model-service, network,
  or end-to-end delivery validation.

## Planned files

- `risk-fusion-bench/src/rfb/research/alert_governance.py`: immutable records,
  deterministic card IDs, association lifecycle, alert history, and the three
  pure scoring functions.
- `risk-fusion-bench/tests/test_alert_governance.py`: synthetic behavior tests
  for initial alerts, independent pending cards, confirmed association,
  evidence-backed split, no-receipt handling, completeness, and confirmation
  accuracy.
- `research-three/alert-governance-v1/`: result-driven evaluation spec,
  synthetic test result summary, historical failure record, and a Mac
  persistence manifest containing repository-relative paths and SHA-256 values
  only.

## Implementation sequence

1. Write the tests and run only the new test module to confirm the expected
   missing-API failure.
2. Add the minimal module until the new tests pass. Do not change existing
   MME metrics, the frozen 1,464-check artifact, `main`, or the old
   `task/research-handoff-v1` publisher.
3. Write the new metric definitions and synthetic outcomes. Label all generated
   inputs as synthetic; preserve the supplied historical failure and its
   non-independent denominator separately.
4. Run only the isolated unit tests, inspect the changed-file list and manifest
   hashes, then push the public deliverables to the new research branch and read
   back its SHA. Do not merge the branch.

## Required Mac input for a later V2 alignment

Provide one complete, unabridged Mac V2 specification bundle: the canonical
specification file plus any referenced schema/metric-definition files it
depends on. It must define the existing event/alert output contract, the exact
original metric formula and denominator, and scenario ground-truth/identity
rules. Until that bundle is available, this implementation remains an
independent synthetic software path.
