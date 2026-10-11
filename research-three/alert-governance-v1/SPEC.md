# Alert governance v1: result-driven evaluation specification

**Status:** independent synthetic software specification; not a reconstruction
of Mac V2.
**Revision:** 1.2.0, updated after the audit of commit `d0b8ece`.

## Historical result retained

The supplied handoff reports one Mac V3-RSS trial with 1,464 checks executed
and a failed round-level result. Across five synthetic scenes and four methods,
all 20 method records lacked a confirmed new-event first report. Those 20
method records are not independent samples. The existing internal review had a
risk flag (`EXPOSURE`), but no user-facing alert level or text, delivery time,
or stable display-card ID. The summary is stored separately in
[`historical-baseline.json`](historical-baseline.json); the frozen run and its
original metric are not edited or rerun here.

The checkout contains no complete Mac V2 specification or exact legacy metric
definition. Therefore the exact old formula and value are marked unavailable
here rather than guessed. Aligning this specification later requires the
complete V2 specification bundle, including every referenced schema/metric
file and the event identity/ground-truth rules.

## Software contract

1. A candidate event gets an independent `candidate_id` and a deterministic
   `CARD-<sha256>` display-card ID. Replaying identical candidate input in the
   same ledger is idempotent. Changes in alert text or revisions do not change
   the card ID.
2. On receipt, the ledger emits a precautionary risk alert with the internal
   risk flag, user-readable text, rationale, reason codes, evidence references,
   event time, observation time, alert-generation time, and delivery status.
3. An uncertain identity link is `PENDING`. It does not merge or delete cards.
   The relationship stores its rationale, evidence references, times, and
   transition history.
4. A same-event decision requires evidence references. The ledger treats
   confirmed same-event relations as graph edges, recomputes connected
   components, and uses the earliest stable card as canonical. Alias lookups
   follow the full chain and fail closed on a cycle. Splitting an edge removes
   only that relation and recomputes components, so other confirmed links and
   all original card IDs remain. Confirmed-distinct and split relations are
   negative constraints: a distinct decision between already connected
   candidates, a same-event link that would bridge a negative constraint, or a
   split whose endpoints remain connected through another path is rejected
   before any ledger or alert mutation. A rejected relation remains at its
   previous status. `canonical_card_id` on each confirmed same-event relation
   names the current canonical card and is refreshed when component topology
   changes; other relation states have no canonical card.
5. Alert stage and event-identity status are independent. Identity proposals,
   confirmations, and splits do not confirm a risk alert. `confirm_risk_alert()`
   requires evidence references and rationale, advances the risk-alert stage
   to `CONFIRMED`, and creates a revision without changing event identity.
   Evidence-backed escalation can advance it to `ESCALATED`; stages remain
   monotonic (`PRECAUTIONARY` < `CONFIRMED` < `ESCALATED`). No hazard-severity
   threshold is inferred. References are recorded, but evidence sufficiency
   remains a caller/reviewer decision because the Mac V2 evidence policy is
   unavailable.
6. The ledger has no delivery adapter. It can report only `SIMULATED` or
   `NOT_DELIVERED`, always with `delivered_at = null`. It cannot create a
   delivered receipt.
7. Timestamps are ordered as parsed UTC instants, including sub-second
   precision. Association resolution and splitting preflight the transition
   time against both the association and every affected card before changing
   state. A stale transition fails without partial card, association, or alert
   updates.

`PRECAUTIONARY`, `CONFIRMED`, and `ESCALATED` describe alert workflow stages;
they are not a hazard-severity scale. Severity categories and thresholds remain
unspecified until the Mac V2 contract is available.

## Revised measures

The measures are separate output dimensions and are not combined into one
score.

### Alert timeliness

- Software emission latency is `alerted_at - observed_at` in seconds.
- A `deadline_seconds` value must be supplied by a future approved protocol to
  label that emission `TIMELY` or `LATE`; without it the result is
  `MEASURED_NO_THRESHOLD`.
- User delivery latency remains null and delivery timeliness is
  `UNSCORABLE_NO_DELIVERY_RECEIPT` for both `SIMULATED` and `NOT_DELIVERED`.
  Emission time must not be reported as receipt time.

### Content completeness

The denominator is the 12 fields `card_id`, `source_ids`, `alert_level`,
`verification_state`, `visible_text`, `rationale`, `reason_codes`,
`evidence_refs`, `event_time`, `observed_at`, `alerted_at`, and
`delivery_status`. A field counts as complete only when populated; source,
evidence, and reason lists must be non-empty. Null values count as missing. The
result returns the numerator, denominator, missing field names, and ratio.

### Event confirmation accuracy

For synthetic or later ground-truthed candidate pairs, predictions come from
the actual `AlertLedger.associations` state and candidate components; callers
provide only truth labels keyed by association IDs in that ledger. Unknown IDs
are rejected. Each pair reports both its component relation and its recorded
prediction. A terminal relation status that contradicts current components
fails closed. Pending pairs remain undecided even when a different path
currently connects their candidates. Accuracy is
`correct resolved relation decisions / all resolved relation decisions`.
`PENDING` pairs are reported as undecided and excluded from that accuracy
denominator. Pair count, decided/undecided counts, unlabeled count, ledger
status, component relation, and per-pair outcomes remain visible. This is
identity-link accuracy, not a claim of overall hazard detection accuracy.

## Development-only validation

All inputs in `risk-fusion-bench/tests/test_alert_governance.py` are synthetic.
The isolated command is:

```sh
cd risk-fusion-bench
PYTHONPATH=src python -m unittest -v tests.test_alert_governance
```

These unit checks validate state transitions and field calculations. They are
not independent observations, do not rerun the 1,464-check trial, do not
qualify an experiment executor, and do not validate delivery on a Mac or any
other device. See [`synthetic-evaluation.json`](synthetic-evaluation.json) for
the captured run and example metric outputs.

## Mac persistence and V2 alignment

[`MAC_PERSISTENCE_MANIFEST.json`](MAC_PERSISTENCE_MANIFEST.json) lists only
repository-relative public deliverables and their SHA-256 hashes. It contains
no cloud absolute path and no assumed Mac absolute path. On the Mac, choose a
local project root and join it with each listed relative path; do not copy a
cloud-container absolute path into the Mac workspace. The Mac V2 source files
are excluded from this branch and manifest.
