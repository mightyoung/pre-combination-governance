from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import pytest

from rfb.loaders.ha4m import HazardZone
from rfb.loaders.ha4m_real import HA4MDirectoryLoader, parse_skeleton_file
from rfb.loaders.hm_sync import HMSYNCLoader, parse_hm_sync_skeleton
from rfb.loaders.mimii import MIMIILoader, read_pcm_wave


def _write_extensible_pcm(
    path: Path,
    *,
    amplitude: float,
    frequency: float,
    sample_rate: int = 800,
    channels: int = 2,
    seconds: int = 1,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for index in range(sample_rate * seconds):
        value = int(
            max(
                -32767,
                min(
                    32767,
                    amplitude
                    * 32767
                    * math.sin(2.0 * math.pi * frequency * index / sample_rate),
                ),
            )
        )
        frames.extend(value for _ in range(channels))
    data = struct.pack(f"<{len(frames)}h", *frames)
    block_align = channels * 2
    pcm_guid = struct.pack(
        "<IHH8s",
        1,
        0,
        0x0010,
        b"\x80\x00\x00\xaa\x00\x38\x9b\x71",
    )
    fmt = (
        struct.pack(
            "<HHIIHH",
            0xFFFE,
            channels,
            sample_rate,
            sample_rate * block_align,
            block_align,
            16,
        )
        + struct.pack("<HHI", 22, 16, (1 << channels) - 1)
        + pcm_guid
    )
    body = (
        b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)


def test_mimii_real_wave_loader_and_truth_sidecar(tmp_path: Path) -> None:
    root = tmp_path / "MIMII" / "6_dB_valve" / "valve" / "id_00"
    _write_extensible_pcm(
        root / "normal" / "00000000.wav",
        amplitude=0.10,
        frequency=20.0,
    )
    _write_extensible_pcm(
        root / "normal" / "00000001.wav",
        amplitude=0.12,
        frequency=22.0,
    )
    abnormal = root / "abnormal" / "00000000.wav"
    _write_extensible_pcm(abnormal, amplitude=0.80, frequency=100.0)

    parsed = read_pcm_wave(abnormal)
    assert parsed.samples.shape == (800, 2)
    assert parsed.sample_rate == 800

    loader = MIMIILoader(window_seconds=1.0)
    observations = loader.load(root.parents[3], labels=["abnormal"])
    assert len(observations) == 1
    assert loader.window_score(observations[0].value) > 2.0
    metadata = loader.scorer_only_metadata(observations[0])
    assert metadata["label"] == "abnormal"
    assert "abnormal" not in observations[0].procedure
    assert "abnormal" not in observations[0].feature_of_interest


def test_mimii_rejects_non_pcm_extensible_subformat(tmp_path: Path) -> None:
    path = tmp_path / "bad.wav"
    _write_extensible_pcm(path, amplitude=0.1, frequency=20.0)
    payload = bytearray(path.read_bytes())
    payload[44:46] = struct.pack("<H", 3)
    path.write_bytes(payload)
    with pytest.raises(ValueError, match="unsupported extensible subformat"):
        read_pcm_wave(path)


_HA4M_HEADER = [
    "BodyID",
    "JointID",
    "Confidance",
    "X",
    "Y",
    "Z",
    "Qw",
    "Qx",
    "Qy",
    "Qz",
    "X2DColor",
    "Y2DColor",
    "X2DDepth",
    "Y2DDepth",
]


def _write_ha4m_frame(path: Path, frame_index: int, joints: int = 32) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["\t".join(_HA4M_HEADER)]
    for joint_id in range(joints):
        x = 1000.0 - frame_index * 50.0
        y = 900.0 + (600.0 if joint_id == 3 else 0.0)
        z = 1000.0 - frame_index * 50.0
        if joint_id == 15:
            x += frame_index * 100.0
        row = [
            "1",
            str(joint_id),
            "1.0",
            f"{x:.3f}",
            f"{y:.3f}",
            f"{z:.3f}",
            "1",
            "0",
            "0",
            "0",
            "0",
            "0",
            "0",
            "0",
        ]
        lines.append("\t".join(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_ha4m_fixture(root: Path) -> Path:
    package = root / "IDU001V001" / "IDU001V001"
    skeleton_dir = package / "Skeletons" / "000124702712"
    for frame_id in range(4):
        _write_ha4m_frame(
            skeleton_dir
            / f"FrameID{frame_id:06d}_DeviceTimeStamp{450000000 + frame_id * 500000}us.txt",
            frame_id,
        )
    (package / "Labels.txt").write_text(
        "\n".join(f"{frame_id} {frame_id % 2} 0" for frame_id in range(4)) + "\n",
        encoding="utf-8",
    )
    return root


def test_ha4m_real_directory_loader(tmp_path: Path) -> None:
    root = _make_ha4m_fixture(tmp_path / "HA4M")
    first = next(root.rglob("FrameID*.txt"))
    frame, completeness = parse_skeleton_file(first)
    assert len(frame) == 32
    assert frame[0] == pytest.approx([1.0, 0.9, 1.0])
    assert completeness == 1.0

    loader = HA4MDirectoryLoader(
        zones=[HazardZone(center=(0.0, 0.9, 0.0), radius=0.2)],
        fps=2.0,
        window_s=1.0,
    )
    observations = loader.load(root)
    assert len(observations) == 2
    assert observations[0].feature_of_interest.startswith("HA4M:IDU001V001")
    metadata = loader.scorer_only_metadata(observations[0])
    assert metadata["first_frame_id"] == 0
    assert metadata["last_frame_id"] == 1
    assert metadata["labels"] == [(0, 0), (1, 0)]
    assert "labels" not in observations[0].quality


def test_ha4m_rejects_incomplete_joint_set(tmp_path: Path) -> None:
    path = tmp_path / "bad.txt"
    _write_ha4m_frame(path, 0, joints=31)
    with pytest.raises(ValueError, match="missing JointID"):
        parse_skeleton_file(path)


def _hm_skeleton(frame_index: int) -> list[list[str]]:
    skeleton = []
    for joint_id in range(32):
        x = float(joint_id) * 0.01
        y = 1.0
        z = 0.0
        if joint_id == 3:
            y = 1.5
        if joint_id in {8, 15}:
            x += frame_index * 0.02
        skeleton.append([f"{x:.4f}", f"{y:.4f}", f"{z:.4f}"])
    return skeleton


def _make_hm_sync_fixture(root: Path, *, unsafe: bool = False) -> Path:
    shard = root / "train-000" / "train-000"
    image_dir = shard / "inner_depths"
    image_dir.mkdir(parents=True)
    metadata = []
    for frame in range(8):
        file_name = (
            "../escape.png"
            if unsafe and frame == 0
            else f"inner_depths/{frame:06d}.png"
        )
        if not unsafe or frame != 0:
            (image_dir / f"{frame:06d}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        metadata.append(
            {
                "action_label": "walking",
                "action_number": 7,
                "datetime": "2026-01-01T00:00:00",
                "file_name": file_name,
                "frame": frame,
                "location_label": 2,
                "skeleton": _hm_skeleton(frame),
                "user_label": 1,
                "view_label": 1,
            }
        )
    (shard / "metadata.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in metadata),
        encoding="utf-8",
    )
    return root


def test_hm_sync_real_jsonl_loader_and_truth_sidecar(tmp_path: Path) -> None:
    root = _make_hm_sync_fixture(tmp_path / "HM-SYNC")
    assert len(parse_hm_sync_skeleton(_hm_skeleton(0))) == 32
    loader = HMSYNCLoader(fps=4.0, window_frames=4)
    observations = loader.load(root)
    assert len(observations) == 2
    assert len(observations[0].value) == 3
    assert math.isfinite(loader.window_score(observations[0].value))
    metadata = loader.scorer_only_metadata(observations[0])
    assert metadata["action_labels"] == ["walking"]
    assert metadata["view_label"] == 1
    assert "walking" not in observations[0].procedure
    assert "walking" not in observations[0].feature_of_interest


def test_hm_sync_rejects_unsafe_image_path(tmp_path: Path) -> None:
    root = _make_hm_sync_fixture(tmp_path / "HM-SYNC", unsafe=True)
    loader = HMSYNCLoader(fps=4.0, window_frames=4)
    with pytest.raises(ValueError, match="unsafe image path"):
        loader.load(root)
