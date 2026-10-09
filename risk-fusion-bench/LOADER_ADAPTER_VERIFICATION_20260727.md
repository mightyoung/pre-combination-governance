# Loader adapter verification — 2026-07-27

## Engineering result

Implemented three real-layout adapters:

- `src/rfb/loaders/mimii.py`
  - validates RIFF/WAVE chunk bounds and declared size;
  - accepts 16-bit PCM and WAVE_FORMAT_EXTENSIBLE PCM;
  - extracts deterministic per-channel log-RMS and zero-crossing features;
  - keeps normal/abnormal labels and paths in the scorer-only sidecar.
- `src/rfb/loaders/ha4m_real.py`
  - parses verified tab-separated skeleton files;
  - requires exactly 32 unique JointIDs;
  - selects X/Y/Z and converts millimetres to metres;
  - prevents windows from crossing package/device sequences;
  - keeps `Labels.txt` values and paths in the scorer-only sidecar.
- `src/rfb/loaders/hm_sync.py`
  - streams `metadata.jsonl`;
  - validates required fields, root-confined image paths, referenced images,
    and numeric `32x3` skeletons;
  - prevents windows from crossing
    `action_number × user_label × view_label` boundaries;
  - keeps action/user/view/location metadata scorer-only.

## Fresh verification

- New real-layout tests: `6 passed`.
- Loader compatibility set: `12 passed`.
- Full repository regression: `369 passed, 13 skipped`.
- `python -m compileall -q src tests`: PASS.
- Ruff 0.15.0 scoped check: PASS.
- Ruff scoped format check: 4 files already formatted.
- Mypy: NOT RUN. The installed mypy 1.19.1 Python 3.13 compiled extension
  failed to load its DLL.

The tests cover:

- WAVE_FORMAT_EXTENSIBLE decoding and rejection of a non-PCM subformat;
- HA4M real header/32-joint parsing and rejection of a missing joint;
- HM-SYNC JSONL/image/skeleton integration and rejection of path traversal;
- scorer-only exclusion of labels/actions from method-visible observations.

## Source-freeze boundary

The authoritative freeze was not rewritten in this task.

- Frozen source tree:
  `25f603608e93d02c238ef56d741bd66aabdb7c58b8e02395c9930157e38fd583`
  with 85 files.
- Current source tree:
  `adb3bb946b70ba605d044f53785aefefad75e97d66918bf49faa3dab5c77ed0b`
  with 89 files.
- Missing: 0.
- Mismatched frozen files: 0.
- New files:
  - `src/rfb/loaders/ha4m_real.py`
  - `src/rfb/loaders/hm_sync.py`
  - `src/rfb/loaders/mimii.py`
  - `tests/test_real_dataset_loaders.py`

Therefore the existing runtime baseline is stale relative to the current
source tree even though all fresh tests passed. `GateChecklist-v6.13.json`
was deliberately not modified, and formal status remains
`FORMAL_EXPERIMENT_BLOCKED`.

## Remaining live validation

This batch used fixtures matching the audited real schemas. It did not run the
new code against the remote extracted trees because that requires a new,
explicit credentialed remote-access authorization.

After that authorization, the next loader-specific validation is a bounded,
CPU-only real-data smoke:

- MIMII: one normal baseline file plus one abnormal valve file;
- HA4M: one 60-frame skeleton window from one package;
- HM-SYNC: one frozen shard and a bounded record count.

That smoke would establish real-disk readability only. It would not restore
the runtime freeze or advance any formal gate.
