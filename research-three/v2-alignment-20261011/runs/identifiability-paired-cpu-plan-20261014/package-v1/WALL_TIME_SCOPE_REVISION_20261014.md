# Wall-time scope revision (2026-10-14)

This result-driven specification note clarifies the existing `wall_seconds`
resource without changing the reviewed slot plan, inputs, methods, or prior
experiment results.

`wall_seconds_elapsed` in the attempt receipt is the sandbox lifecycle duration:
it starts before Docker setup and ends after the runner attempts sandbox image
cleanup. The receipt's `started_at_utc` and `finished_at_utc` mark those same
boundaries. This is the interval enforced by the parent deadline and used to
decide whether the sandbox task exceeded its registered wall limit. Image
cleanup is attempted once so an outer `finally` block cannot silently retry it
after the receipt's sandbox timing has been sampled.

Bundle finalization (renaming the slot stream, writing the terminal progress
record, freezing and hashing output, and writing the receipt) occurs after the
sandbox lifecycle boundary. Its duration is reported separately as
`attempt_wall_seconds_elapsed` in the CLI summary, including the runner's final
session cleanup. It is observational and does not change task status or the
registered sandbox wall-limit decision. The receipt cannot include a timing
value measured after the receipt itself is frozen.

This is a reporting-boundary clarification, not a change to historical metrics.
The earlier Mac V3-RSS run remains failed under its original metrics and is not
recomputed by this package.
