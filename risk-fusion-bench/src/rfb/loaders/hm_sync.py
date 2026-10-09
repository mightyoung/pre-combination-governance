# -*- coding: utf-8 -*-
"""HM-SYNC JSONL skeleton records -> human-stream canonical observations."""

from __future__ import annotations

import json
import math
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .base import BaseLoader, CanonicalObs


N_JOINTS = 32
J_PELVIS, J_NECK, J_HAND_L, J_HAND_R = 0, 3, 8, 15


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def parse_hm_sync_skeleton(value: Any) -> List[List[float]]:
    """Validate and convert one JSON skeleton to a numeric 32x3 matrix."""

    if not isinstance(value, list) or len(value) != N_JOINTS:
        raise ValueError(f"HM-SYNC skeleton must contain {N_JOINTS} joints")
    result = []
    for joint_index, joint in enumerate(value):
        if not isinstance(joint, list) or len(joint) != 3:
            raise ValueError(f"HM-SYNC joint {joint_index} must contain XYZ")
        try:
            xyz = [float(component) for component in joint]
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"HM-SYNC joint {joint_index} contains a non-numeric value"
            ) from exc
        if not all(math.isfinite(component) for component in xyz):
            raise ValueError(f"HM-SYNC joint {joint_index} contains a non-finite value")
        result.append(xyz)
    return result


def _normalise_frame(frame: Sequence[Sequence[float]]) -> List[List[float]]:
    pelvis = frame[J_PELVIS]
    torso_scale = max(_distance(frame[J_NECK], pelvis), 1e-9)
    return [
        [
            (float(component) - float(pelvis[axis])) / torso_scale
            for axis, component in enumerate(joint)
        ]
        for joint in frame
    ]


def _window_features(
    frames: Sequence[Sequence[Sequence[float]]],
    fps: float,
) -> List[float]:
    normalised = [_normalise_frame(frame) for frame in frames]
    inclines = []
    hand_speeds = []
    motion = []
    for frame in normalised:
        torso = [frame[J_NECK][axis] - frame[J_PELVIS][axis] for axis in range(3)]
        horizontal = math.sqrt(torso[0] ** 2 + torso[2] ** 2)
        inclines.append(math.degrees(math.atan2(horizontal, abs(torso[1]) + 1e-9)))
    for current, previous in zip(normalised[1:], normalised):
        hand_speeds.extend(
            [
                _distance(current[J_HAND_L], previous[J_HAND_L]) * fps,
                _distance(current[J_HAND_R], previous[J_HAND_R]) * fps,
            ]
        )
        motion.append(
            sum(_distance(a, b) for a, b in zip(current, previous)) / N_JOINTS * fps
        )
    return [
        max(hand_speeds, default=0.0),
        max(inclines, default=0.0),
        sum(motion) / len(motion) if motion else 0.0,
    ]


def _safe_image_path(metadata_path: Path, file_name: str) -> Path:
    relative = PurePosixPath(file_name)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or (relative.parts and ":" in relative.parts[0])
    ):
        raise ValueError(f"{metadata_path}: unsafe image path {file_name!r}")
    return metadata_path.parent.joinpath(*relative.parts)


class HMSYNCLoader(BaseLoader):
    """Stream HM-SYNC data without crossing action/view sequence boundaries."""

    STREAM = "human"
    PROP_MASK = 2
    PROCEDURE = "hm-sync-normalised-skeleton-motion/0.1"

    def __init__(self, fps: float = 30.0, window_frames: int = 30):
        if fps <= 0 or window_frames <= 1:
            raise ValueError("fps must be positive and window_frames must exceed one")
        self.fps = float(fps)
        self.window_frames = int(window_frames)
        self.mu: Optional[List[float]] = None
        self.sd: Optional[List[float]] = None

    def fit_feature_baseline(self, feature_rows: Sequence[Sequence[float]]) -> None:
        if len(feature_rows) < 2:
            raise ValueError("HM-SYNC baseline requires at least two windows")
        if any(len(row) != 3 for row in feature_rows):
            raise ValueError("HM-SYNC feature rows must have width three")
        self.mu = [
            sum(float(row[index]) for row in feature_rows) / len(feature_rows)
            for index in range(3)
        ]
        self.sd = []
        for index, mean in enumerate(self.mu):
            variance = sum((float(row[index]) - mean) ** 2 for row in feature_rows) / (
                len(feature_rows) - 1
            )
            self.sd.append(max(math.sqrt(variance), 1e-9))

    def _sequence_observations(
        self,
        records: Sequence[Tuple[dict, Path, int]],
    ) -> tuple[List[CanonicalObs], List[Dict[str, Any]]]:
        if len(records) < self.window_frames:
            return [], []
        frames = [
            parse_hm_sync_skeleton(record["skeleton"]) for record, _, _ in records
        ]
        observations = []
        metadata_rows = []
        first_record = records[0][0]
        subject = int(first_record["user_label"])
        view = int(first_record["view_label"])
        action_number = int(first_record["action_number"])
        for start in range(
            0,
            len(frames) - self.window_frames + 1,
            self.window_frames,
        ):
            stop = start + self.window_frames
            values = _window_features(frames[start:stop], self.fps)
            observations.append(
                CanonicalObs(
                    value=values,
                    unit="torso-length/s,deg,torso-length/s",
                    t_gen=(float(records[start][0]["frame"]) + self.window_frames)
                    / self.fps,
                    feature_of_interest=f"HM-SYNC:user={subject}:view={view}",
                    procedure=self.PROCEDURE,
                    quality={"completeness": 1.0, "fps": self.fps},
                )
            )
            labels = sorted(
                {str(item[0]["action_label"]) for item in records[start:stop]}
            )
            locations = sorted(
                {int(item[0]["location_label"]) for item in records[start:stop]}
            )
            metadata_rows.append(
                {
                    "metadata_path": str(records[start][1]),
                    "first_line": records[start][2],
                    "last_line": records[stop - 1][2],
                    "first_image": str(records[start][0]["file_name"]),
                    "last_image": str(records[stop - 1][0]["file_name"]),
                    "user_label": subject,
                    "view_label": view,
                    "action_number": action_number,
                    "action_labels": labels,
                    "location_labels": locations,
                }
            )
        return observations, metadata_rows

    def load(
        self,
        data_dir: str | Path,
        *,
        shards: Optional[Sequence[str]] = None,
        users: Optional[Sequence[int]] = None,
        views: Optional[Sequence[int]] = None,
        actions: Optional[Sequence[str]] = None,
        max_records: Optional[int] = None,
        verify_images: bool = True,
    ) -> List[CanonicalObs]:
        """Load JSONL records and group contiguous action/user/view sequences."""

        root = Path(data_dir).resolve(strict=True)
        shard_filter = set(shards) if shards is not None else None
        user_filter = set(users) if users is not None else None
        view_filter = set(views) if views is not None else None
        action_filter = set(actions) if actions is not None else None
        if max_records is not None and max_records <= 0:
            raise ValueError("max_records must be positive")

        metadata_files = sorted(root.rglob("metadata.jsonl"))
        observations: List[CanonicalObs] = []
        metadata_rows: List[Dict[str, Any]] = []
        consumed = 0
        for metadata_path in metadata_files:
            shard = next(
                (
                    part
                    for part in metadata_path.relative_to(root).parts
                    if part.startswith("train-")
                ),
                metadata_path.parent.name,
            )
            if shard_filter is not None and shard not in shard_filter:
                continue
            current_key = None
            sequence: List[Tuple[dict, Path, int]] = []

            def flush() -> None:
                nonlocal sequence
                sequence_observations, sequence_metadata = self._sequence_observations(
                    sequence
                )
                observations.extend(sequence_observations)
                metadata_rows.extend(sequence_metadata)
                sequence = []

            with metadata_path.open("r", encoding="utf-8-sig") as handle:
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    required = {
                        "action_label",
                        "action_number",
                        "file_name",
                        "frame",
                        "location_label",
                        "skeleton",
                        "user_label",
                        "view_label",
                    }
                    missing = sorted(required - set(record))
                    if missing:
                        raise ValueError(
                            f"{metadata_path}:{line_number}: missing fields {missing}"
                        )
                    subject = int(record["user_label"])
                    view = int(record["view_label"])
                    action = str(record["action_label"])
                    if user_filter is not None and subject not in user_filter:
                        continue
                    if view_filter is not None and view not in view_filter:
                        continue
                    if action_filter is not None and action not in action_filter:
                        continue

                    image_path = _safe_image_path(
                        metadata_path,
                        str(record["file_name"]),
                    )
                    if verify_images and not image_path.is_file():
                        raise ValueError(
                            f"{metadata_path}:{line_number}: "
                            f"referenced image does not exist: {image_path}"
                        )
                    parse_hm_sync_skeleton(record["skeleton"])
                    key = (int(record["action_number"]), subject, view)
                    if current_key is not None and key != current_key:
                        flush()
                    current_key = key
                    sequence.append((record, metadata_path, line_number))
                    consumed += 1
                    if max_records is not None and consumed >= max_records:
                        break
            flush()
            if max_records is not None and consumed >= max_records:
                break

        if not observations:
            raise ValueError(
                "no complete HM-SYNC windows matched the requested selection"
            )
        if self.mu is None:
            self.fit_feature_baseline(
                [observation.value for observation in observations]
            )
        self._set_scorer_only_sidecar(observations, metadata_rows)
        return observations

    def window_score(self, values: Sequence[float]) -> float:
        if self.mu is None or self.sd is None:
            raise RuntimeError("fit an HM-SYNC feature baseline before scoring")
        if len(values) != 3:
            raise ValueError("HM-SYNC feature vectors must have length three")
        weights = (0.45, 0.30, 0.25)
        return sum(
            abs((float(value) - mean) / deviation) * weight
            for value, mean, deviation, weight in zip(
                values,
                self.mu,
                self.sd,
                weights,
            )
        )
