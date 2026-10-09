# -*- coding: utf-8 -*-
"""Real-directory adapter for verified HA4M skeleton archives."""

from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .base import CanonicalObs
from .ha4m import HA4MLoader, HazardZone


N_JOINTS = 32
_FRAME_RE = re.compile(r"FrameID(\d+)_DeviceTimeStamp(\d+)us")


def parse_skeleton_file(
    path: str | Path,
    *,
    coordinate_scale: float = 0.001,
) -> Tuple[List[List[float]], float]:
    """Parse one HA4M TXT into 32 ordered XYZ joints in metres."""

    if coordinate_scale <= 0:
        raise ValueError("coordinate_scale must be positive")
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"JointID", "X", "Y", "Z"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(
                f"{source}: missing required skeleton columns {sorted(required)}"
            )
        joints: Dict[int, List[float]] = {}
        for row_number, row in enumerate(reader, 2):
            try:
                joint_id = int(row["JointID"])
                xyz = [float(row[axis]) * coordinate_scale for axis in ("X", "Y", "Z")]
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{source}:{row_number}: invalid skeleton value"
                ) from exc
            if not 0 <= joint_id < N_JOINTS:
                raise ValueError(
                    f"{source}:{row_number}: JointID {joint_id} out of range"
                )
            if joint_id in joints:
                raise ValueError(f"{source}:{row_number}: duplicate JointID {joint_id}")
            joints[joint_id] = xyz
    missing = sorted(set(range(N_JOINTS)) - set(joints))
    if missing:
        raise ValueError(f"{source}: missing JointID values {missing}")
    ordered = [joints[joint_id] for joint_id in range(N_JOINTS)]
    finite = sum(math.isfinite(value) for joint in ordered for value in joint)
    completeness = finite / (N_JOINTS * 3)
    return ordered, completeness


def _load_labels(path: Path) -> Dict[int, Tuple[int, int]]:
    labels: Dict[int, Tuple[int, int]] = {}
    if not path.is_file():
        return labels
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) != 3:
                raise ValueError(
                    f"{path}:{line_number}: expected three integer columns"
                )
            frame_id, action_label, auxiliary_label = (int(part) for part in parts)
            if frame_id in labels:
                raise ValueError(f"{path}:{line_number}: duplicate frame id {frame_id}")
            labels[frame_id] = (action_label, auxiliary_label)
    return labels


class HA4MDirectoryLoader(HA4MLoader):
    """Extend :class:`HA4MLoader` with verified archive directory parsing."""

    PROCEDURE = "ha4m-real-skeleton-rules/0.2"

    def __init__(
        self,
        zones: Optional[List[HazardZone]] = None,
        fps: float = 30.0,
        window_s: float = 2.0,
    ):
        if fps <= 0 or window_s <= 0:
            raise ValueError("fps and window_s must be positive")
        super().__init__(zones=zones, fps=fps, window_s=window_s)
        self.win = max(1, round(window_s * fps))

    def load(
        self,
        data_dir: str | Path,
        *,
        packages: Optional[Sequence[str]] = None,
        coordinate_scale: float = 0.001,
        max_frames_per_sequence: Optional[int] = None,
    ) -> List[CanonicalObs]:
        """Load HA4M ``Skeletons/*/*.txt`` without crossing sequences."""

        root = Path(data_dir).resolve(strict=True)
        package_filter = set(packages) if packages is not None else None
        skeleton_dirs = sorted(
            path for path in root.rglob("Skeletons") if path.is_dir()
        )
        observations: List[CanonicalObs] = []
        metadata_rows = []
        for skeleton_root in skeleton_dirs:
            package = next(
                (
                    part
                    for part in skeleton_root.relative_to(root).parts
                    if part.startswith("IDU")
                ),
                skeleton_root.parent.name,
            )
            if package_filter is not None and package not in package_filter:
                continue
            labels = _load_labels(skeleton_root.parent / "Labels.txt")
            device_dirs = sorted(
                path for path in skeleton_root.iterdir() if path.is_dir()
            )
            for device_dir in device_dirs:
                files = sorted(device_dir.glob("FrameID*_DeviceTimeStamp*us.txt"))
                if max_frames_per_sequence is not None:
                    if max_frames_per_sequence <= 0:
                        raise ValueError("max_frames_per_sequence must be positive")
                    files = files[:max_frames_per_sequence]
                if not files:
                    continue
                frames = []
                completeness = []
                frame_ids = []
                timestamps_us = []
                for path in files:
                    match = _FRAME_RE.fullmatch(path.stem)
                    if match is None:
                        raise ValueError(f"{path}: unexpected HA4M frame filename")
                    frame, quality = parse_skeleton_file(
                        path,
                        coordinate_scale=coordinate_scale,
                    )
                    frames.append(frame)
                    completeness.append(quality)
                    frame_ids.append(int(match.group(1)))
                    timestamps_us.append(int(match.group(2)))

                sequence_observations = self.from_array(
                    frames,
                    worker_id=f"HA4M:{package}:{device_dir.name}",
                    t0=timestamps_us[0] / 1_000_000.0,
                )
                for window_index, observation in enumerate(sequence_observations):
                    start = window_index * self.win
                    stop = start + self.win
                    observation.procedure = self.PROCEDURE
                    observation.quality["completeness"] = (
                        sum(completeness[start:stop]) / self.win
                    )
                    window_frame_ids = frame_ids[start:stop]
                    window_labels = {
                        labels[frame_id]
                        for frame_id in window_frame_ids
                        if frame_id in labels
                    }
                    observations.append(observation)
                    metadata_rows.append(
                        {
                            "package": package,
                            "device_id": device_dir.name,
                            "source_dir": str(device_dir),
                            "first_source_path": str(files[start]),
                            "last_source_path": str(files[stop - 1]),
                            "first_frame_id": window_frame_ids[0],
                            "last_frame_id": window_frame_ids[-1],
                            "labels": sorted(window_labels),
                        }
                    )
        if not observations:
            raise ValueError("no complete HA4M windows matched the requested selection")
        self._set_scorer_only_sidecar(observations, metadata_rows)
        return observations
