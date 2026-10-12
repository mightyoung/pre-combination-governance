# Local controlled replay: lineage retained vs omitted

**Status: `FROZEN_PRE_RUN`.** This probe reuses the existing saved USGS normalized sample. It does not acquire new public data, read a network endpoint, or access NWS. Its local receipt timestamps describe this controlled replay only; they are not the original source or historical collector receive times.

## Choice and relationship to research three

The previous synthetic probe exposed a narrow contract behavior: exact repeated graph IDs are dictionary-deduplicated. The next useful step is to test whether the existing lineage contract can attribute a *local format alias* to the exact saved input bytes when a parent/child receipt is retained, and whether the same output becomes `UNKNOWN` when lineage is omitted or a receipt is inconsistent. This tests the evidence-provenance boundary required before combination. It does not add sources, score risk, change association rules, or alter the D-S route.

## Frozen hypothesis and comparison

- **H1 — lineage retained:** project the same fixed fields from the saved normalized sample into an alias JSON object. Record a locally generated parent receipt for the exact saved file bytes and a child receipt for the exact alias bytes. If receipt IDs, hashes, transform digest, and local times validate, the local lineage contract should find the saved file as a shared ancestor of the alias. This establishes only local replay attribution to that saved file.
- **H2 — same transform, lineage omitted:** produce byte-identical alias JSON, but omit the parent/child receipt and claim the trace is incomplete. The lineage result must be `UNKNOWN`, not independent and not an additional source.
- **Negative control — forged parent:** the receipt names a parent record ID absent from the local receipt set. The validator must reject the edge and the lineage result must remain `UNKNOWN`.
- **Negative control — hash mismatch:** the receipt contains a parent digest different from the hash recomputed from the saved sample file. The validator must reject the edge and the lineage result must remain `UNKNOWN`.

The parent and child payloads are stored locally as the normalized sample JSON and a deterministic alias JSON. The child transformation is identical in both main arms; only receipt/provenance metadata differs. The source sample's ID and source lists are not treated as separate evidence sources.

## Hash and receipt semantics

- `parent_sha256` is computed over the exact local bytes of `REAL_PUBLIC_FEED_SAMPLE.json`. That file is a normalized audit extract, **not** the original USGS response payload.
- `child_sha256` is computed over the canonical UTF-8 JSON bytes produced by the fixed field-projection transform.
- `local_replay_received_at` is generated from this run's local UTC system clock before reading and transforming the file. It is not backdated and does not replace missing historical receive time.
- Parent and child receipts are created locally by this runner and include record IDs, content hashes, transform code hash, and local timestamp. They are not signed or anchored to an external trusted clock. A digest match proves only that this runner saw matching local bytes within this run; it does not prove source authenticity, historical receipt, transport integrity before local save, or source independence.
- The lineage contract uses `VERIFIED` only after local IDs, hashes, and receipt links pass this run's validator. This is a local controlled assumption, not a cryptographic trust grant for USGS or an external sender.

## Measures and expected outcomes

1. The preserved and omitted-lineage alias payload hashes must be identical.
2. Preserved receipt validation must pass parent-ID, parent-hash, child-hash, transform-hash, and time checks; the pairwise lineage output is expected to be `SHARED_KNOWN_ANCESTOR` with the local saved-file node as shared ancestor.
3. Omitted, forged-parent, and hash-mismatch cases must fail closed as incomplete/invalid receipt chains and return `UNKNOWN` from the lineage contract.
4. `statistical_independence_established` must remain false in all cases. No numeric risk confidence, probability, event accuracy, delivery timing, or D-S effect is computed.
5. Record raw/canonical byte lengths, SHA-256 values, and local replay receipt time as process evidence, not as historical source evidence.

The receipt-validation booleans and lineage states are deterministic contract checks, not efficacy measures or independent samples. No test-count-derived effect claim is allowed.

## Inputs and execution boundary

`INPUTS.json` pins the normalized sample path/hash, exact field projection, receipt policy, fixed expected cases, and the negative fixtures. `PRE_RUN_MANIFEST.json` binds the protocol, input, runner, saved sample/audit, existing lineage code, and relevant tests before execution.

After that freeze commit, run only:

```sh
PYTHONPATH=risk-fusion-bench/src python research-three/v2-alignment-20261011/runs/local-replay-lineage-20261012/run_local_replay.py
```

No network, model, notification adapter, device, runner qualification probe, or paid service is used. The output is a local controlled replay with `NOT_DELIVERED` delivery status.
