# Real-dataset loader adapters

The adapters below parse the verified on-disk layouts and emit
`CanonicalObs`. Dataset labels, action identifiers, source paths, and other
evaluation metadata are stored only in `scorer_only_sidecar()`.

## MIMII

```python
from rfb.loaders.mimii import MIMIILoader

loader = MIMIILoader(window_seconds=1.0)
observations = loader.load(
    "/path/to/MIMII",
    machine_ids=["id_00"],
    labels=["abnormal"],
    max_files=1,
    baseline_max_files=8,
)
```

The loader validates RIFF sizes, `fmt`/`data` chunks, PCM subformat,
byte-rate, block alignment, and frame alignment. It supports ordinary 16-bit
PCM and the `WAVE_FORMAT_EXTENSIBLE` PCM used by the verified valve archive.

Normal files are used only to fit the feature baseline. Formal runs must
preregister the normal-training tree and `baseline_max_files`; evaluation
labels remain scorer-only.

## HA4M

```python
from rfb.loaders.ha4m import HazardZone
from rfb.loaders.ha4m_real import HA4MDirectoryLoader

loader = HA4MDirectoryLoader(
    zones=[HazardZone(center=(0.0, 0.9, 0.0), radius=0.5)],
)
observations = loader.load(
    "/path/to/HA4M",
    packages=["IDU001V001"],
    max_frames_per_sequence=120,
)
```

`HA4MDirectoryLoader` reads the real tab-separated skeleton files, validates
all 32 JointIDs, selects X/Y/Z, converts millimetres to metres, and prevents
windows from crossing package/device sequence boundaries. `Labels.txt`
contents remain scorer-only.

## HM-SYNC

```python
from rfb.loaders.hm_sync import HMSYNCLoader

loader = HMSYNCLoader(fps=30.0, window_frames=30)
observations = loader.load(
    "/path/to/HM-SYNC",
    shards=["train-000"],
    max_records=600,
)
```

The loader streams `metadata.jsonl`, validates the required fields, enforces
root-confined image paths, optionally verifies referenced images, validates
numeric `32x3` skeletons, and does not cross
`action_number × user_label × view_label` boundaries.

If scores/BPAs are required, formal code should fit a preregistered baseline
before evaluation:

```python
training = loader.load("/path/to/preregistered/training-subset")
loader.fit_feature_baseline([observation.value for observation in training])
evaluation = loader.load("/path/to/frozen/evaluation-subset")
```

Without an explicit prior baseline, `load()` fits a development-only baseline
from the loaded observations. That convenience path must not be used for
confirmatory scoring.

## Evidence boundary

Passing loader tests proves parser, validation, truth-sidecar, and
`CanonicalObs` integration behavior. It does not change v6.13 formal gate
status, prove representative coverage, or authorize SHK-001B.
