# Correction to V1 hash-only score interpretation

V1's [scored result](../two-hop-lineage-controlled-synthetic-20261012/SCORED_RESULT.json) is preserved byte-for-byte as the historical output. Its hash-only arm reported three `DISTINCT_HASH_BUCKETS` rows and counted them as `wrong_separate_attribution`. That interpretation is too strong: byte-different payloads do not establish different sources, and byte-identical payloads do not establish a shared source.

Under the conservative V2 policy, each of those three hash-only lineage outcomes is `UNKNOWN` / no provenance attribution. They are not errors. V2 reports raw confirmed ancestry and `UNKNOWN` counts, and leaves production accuracy and wrong-attribution counts `NOT_COMPUTABLE` / `NOT_EVALUATED` because the production truth denominator is zero. No V1 file or score is rewritten.
