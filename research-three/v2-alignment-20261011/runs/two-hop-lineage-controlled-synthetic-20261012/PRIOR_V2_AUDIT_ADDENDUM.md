# Audit addendum: prior local replay V2

This addendum is appended on a new branch. The prior V2 runner, `RESULT_V2.json`, and `VISUALIZATION_V2.svg` remain unchanged.

## M1 — method-output hash ordering

The prior result field `method_outputs_sha256_before_expectation_checks` and the matching audit wording are inaccurate. In `run_local_replay_v2.py`, the runner constructs the `checks` dictionary and computes `all_passed` before it serializes and hashes `method_outputs`. That digest is therefore a post-check digest; it does not prove the method output was frozen before expectation comparison. This correction does not change the old result. The new two-hop runner below writes and hashes `METHOD_OUTPUTS.json` before evaluating frozen expectations, then records that sequence explicitly.

## M2 — derived display of historical and local time

The original V2 SVG draws an arrow from the saved-sample card to the local replay receipt beside the text `historical receive time: UNKNOWN`. This can blur the distinction between an unknown historical receiver time and the new local replay clock. The original SVG is preserved. [`VISUALIZATION_V2_AUDIT_CORRECTED.svg`](VISUALIZATION_V2_AUDIT_CORRECTED.svg) is a derived diagram that separates the saved-file record and the new local replay record and removes the connecting arrow. The local timestamp is not a substitute for the historical time.

## Receipt scope

The prior parent and child IDs, hashes, timestamps, and receipt digests were constructed by one local runner. Even when their consistency check returns `PASS`, that means only consistency under the trusted local-runner procedure; it does not authenticate the real USGS source, the publisher, or historic transport. A locally re-created or re-hashed receipt does not add independent provenance evidence.

## Available evidence boundary

The saved public sample does not contain a local receive record or two-sided forwarding receipts. The prior V2 local receipt files are same-runner assertions, not production logs. The existing `SHK-000-local-20260714T1655CST` artefacts are explicitly non-confirmatory generated shakedown data and concern synthetic risk trajectories, not executed source-lineage replay. No production source-lineage truth denominator is available in this checkout.
