# -*- coding: utf-8 -*-
"""MIMII WAVE archives -> machine-stream canonical observations.

The verified valve archive stores 16-bit PCM in WAVE_FORMAT_EXTENSIBLE
containers. Python's standard :mod:`wave` module does not decode that tag on
every supported interpreter, so this loader parses RIFF directly and accepts
only ordinary PCM or extensible PCM.
"""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import numpy as np

from .base import BaseLoader, CanonicalObs


_MACHINE_ID_RE = re.compile(r"id_\d+")
_PCM_FORMAT = 0x0001
_EXTENSIBLE_FORMAT = 0xFFFE


@dataclass(frozen=True)
class PCMFile:
    """Decoded little-endian PCM samples and validated container metadata."""

    samples: np.ndarray
    sample_rate: int
    channels: int
    bits_per_sample: int


def read_pcm_wave(path: str | Path) -> PCMFile:
    """Read a RIFF PCM or WAVE_FORMAT_EXTENSIBLE PCM file."""

    source = Path(path)
    file_size = source.stat().st_size
    with source.open("rb") as handle:
        header = handle.read(12)
        if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE":
            raise ValueError(f"{source}: expected RIFF/WAVE")
        declared_size = struct.unpack("<I", header[4:8])[0] + 8
        if declared_size != file_size:
            raise ValueError(
                f"{source}: RIFF size {declared_size} does not match file size {file_size}"
            )

        fmt: Optional[tuple[int, int, int, int, int, int, Optional[int]]] = None
        data: Optional[bytes] = None
        while handle.tell() + 8 <= file_size:
            chunk_header = handle.read(8)
            chunk_id = chunk_header[:4]
            chunk_size = struct.unpack("<I", chunk_header[4:])[0]
            chunk_start = handle.tell()
            chunk_end = chunk_start + chunk_size
            if chunk_end > file_size:
                raise ValueError(f"{source}: chunk {chunk_id!r} exceeds file size")

            if chunk_id == b"fmt ":
                raw = handle.read(chunk_size)
                if len(raw) < 16:
                    raise ValueError(f"{source}: short fmt chunk")
                tag, channels, rate, byte_rate, block_align, bits = struct.unpack(
                    "<HHIIHH", raw[:16]
                )
                subformat = None
                if tag == _EXTENSIBLE_FORMAT:
                    if len(raw) < 40:
                        raise ValueError(f"{source}: short extensible fmt chunk")
                    subformat = struct.unpack("<H", raw[24:26])[0]
                fmt = (tag, channels, rate, byte_rate, block_align, bits, subformat)
            elif chunk_id == b"data":
                data = handle.read(chunk_size)

            handle.seek(chunk_end + (chunk_size & 1))

    if fmt is None or data is None:
        raise ValueError(f"{source}: missing fmt or data chunk")
    tag, channels, rate, byte_rate, block_align, bits, subformat = fmt
    if tag == _EXTENSIBLE_FORMAT:
        if subformat != _PCM_FORMAT:
            raise ValueError(f"{source}: unsupported extensible subformat {subformat}")
    elif tag != _PCM_FORMAT:
        raise ValueError(f"{source}: unsupported WAVE format tag {tag}")
    if channels <= 0 or rate <= 0:
        raise ValueError(f"{source}: invalid channels/sample rate")
    if bits != 16:
        raise ValueError(f"{source}: only 16-bit PCM is supported, found {bits}")
    expected_align = channels * bits // 8
    if block_align != expected_align or byte_rate != rate * block_align:
        raise ValueError(f"{source}: inconsistent PCM alignment or byte rate")
    if len(data) % block_align:
        raise ValueError(f"{source}: PCM payload is not frame aligned")

    samples = np.frombuffer(data, dtype="<i2").reshape(-1, channels).astype(np.float64)
    samples /= 32768.0
    return PCMFile(samples, rate, channels, bits)


def _window_features(samples: np.ndarray, window_frames: int) -> List[List[float]]:
    """Return per-channel log-RMS and zero-crossing rates."""

    features: List[List[float]] = []
    for start in range(0, len(samples) - window_frames + 1, window_frames):
        window = samples[start : start + window_frames]
        rms = np.sqrt(np.mean(window * window, axis=0))
        log_rms = np.log10(np.maximum(rms, 1e-12))
        signs = np.signbit(window)
        zcr = (
            np.mean(signs[1:] != signs[:-1], axis=0)
            if len(window) > 1
            else np.zeros(window.shape[1])
        )
        features.append(np.concatenate([log_rms, zcr]).astype(float).tolist())
    return features


def _machine_id(path: Path) -> str:
    return next(
        (part for part in path.parts if _MACHINE_ID_RE.fullmatch(part)), "unknown"
    )


def _label(path: Path) -> str:
    lowered = {part.lower() for part in path.parts}
    if "normal" in lowered:
        return "normal"
    if "abnormal" in lowered:
        return "abnormal"
    return "unknown"


class MIMIILoader(BaseLoader):
    """Deterministic MIMII audio feature loader with a normal baseline."""

    STREAM = "machine"
    PROP_MASK = 4
    PROCEDURE = "mimii-wave-logrms-zcr/0.1"

    def __init__(self, window_seconds: float = 1.0):
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.window_seconds = float(window_seconds)
        self.mu: Optional[List[float]] = None
        self.sd: Optional[List[float]] = None
        self.channels: Optional[int] = None

    def _features_from_file(self, path: Path) -> tuple[PCMFile, List[List[float]]]:
        audio = read_pcm_wave(path)
        if self.channels is not None and audio.channels != self.channels:
            raise ValueError(
                f"{path}: channel count {audio.channels} differs from baseline {self.channels}"
            )
        window_frames = max(1, round(self.window_seconds * audio.sample_rate))
        features = _window_features(audio.samples, window_frames)
        if not features:
            raise ValueError(f"{path}: audio is shorter than one configured window")
        return audio, features

    def fit_normal_files(
        self,
        paths: Iterable[str | Path],
        *,
        max_files: Optional[int] = None,
    ) -> None:
        """Fit feature-wise mean and standard deviation on sorted normal files."""

        selected = sorted(Path(path) for path in paths)
        if max_files is not None:
            if max_files <= 0:
                raise ValueError("max_files must be positive")
            selected = selected[:max_files]
        if not selected:
            raise ValueError("no normal MIMII files selected for baseline fitting")

        rows: List[List[float]] = []
        for path in selected:
            audio = read_pcm_wave(path)
            if self.channels is None:
                self.channels = audio.channels
            elif audio.channels != self.channels:
                raise ValueError(f"{path}: inconsistent channel count")
            window_frames = max(1, round(self.window_seconds * audio.sample_rate))
            rows.extend(_window_features(audio.samples, window_frames))
        if len(rows) < 2:
            raise ValueError("MIMII baseline requires at least two audio windows")

        matrix = np.asarray(rows, dtype=float)
        self.mu = np.mean(matrix, axis=0).astype(float).tolist()
        self.sd = (
            np.maximum(np.std(matrix, axis=0, ddof=1), 1e-9).astype(float).tolist()
        )

    def load(
        self,
        data_dir: str | Path,
        *,
        machine_ids: Optional[Sequence[str]] = None,
        labels: Optional[Sequence[str]] = None,
        max_files: Optional[int] = None,
        baseline_max_files: Optional[int] = None,
    ) -> List[CanonicalObs]:
        """Load sorted WAV files and keep labels in the scorer-only sidecar."""

        root = Path(data_dir).resolve(strict=True)
        all_paths = sorted(path for path in root.rglob("*.wav") if path.is_file())
        machine_filter = set(machine_ids) if machine_ids is not None else None
        label_filter = set(labels) if labels is not None else None

        def selected(path: Path, *, apply_label: bool = True) -> bool:
            if machine_filter is not None and _machine_id(path) not in machine_filter:
                return False
            return (
                not apply_label or label_filter is None or _label(path) in label_filter
            )

        target_paths = [path for path in all_paths if selected(path)]
        if max_files is not None:
            if max_files <= 0:
                raise ValueError("max_files must be positive")
            target_paths = target_paths[:max_files]
        if not target_paths:
            raise ValueError("no MIMII WAV files matched the requested selection")

        if self.mu is None:
            normal_paths = [
                path
                for path in all_paths
                if selected(path, apply_label=False) and _label(path) == "normal"
            ]
            self.fit_normal_files(normal_paths, max_files=baseline_max_files)

        observations: List[CanonicalObs] = []
        sidecar = []
        time_offset = 0.0
        for file_index, path in enumerate(target_paths):
            audio, rows = self._features_from_file(path)
            duration = len(audio.samples) / audio.sample_rate
            machine_id = _machine_id(path)
            label = _label(path)
            for window_index, values in enumerate(rows):
                observations.append(
                    CanonicalObs(
                        value=values,
                        unit="log10(full-scale-rms),zero-crossing-rate",
                        t_gen=time_offset + (window_index + 1) * self.window_seconds,
                        feature_of_interest=f"MIMII:{machine_id}",
                        procedure=self.PROCEDURE,
                        quality={
                            "completeness": 1.0,
                            "sample_rate_hz": float(audio.sample_rate),
                            "channels": float(audio.channels),
                        },
                    )
                )
                sidecar.append(
                    {
                        "source_path": str(path),
                        "source_filename": path.name,
                        "machine_id": machine_id,
                        "label": label,
                        "file_index": file_index,
                        "window_index": window_index,
                    }
                )
            time_offset += duration
        self._set_scorer_only_sidecar(observations, sidecar)
        return observations

    def window_score(self, values: Sequence[float]) -> float:
        if self.mu is None or self.sd is None:
            raise RuntimeError("fit a normal MIMII baseline before scoring")
        if len(values) != len(self.mu):
            raise ValueError("feature vector length differs from MIMII baseline")
        zscores = sorted(
            (
                abs((float(value) - mean) / deviation)
                for value, mean, deviation in zip(values, self.mu, self.sd)
            ),
            reverse=True,
        )
        top = zscores[: max(1, math.ceil(len(zscores) / 4))]
        return sum(top) / len(top)
