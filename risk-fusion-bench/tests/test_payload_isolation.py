"""Method-visible loader output must not contain scorer-only truth metadata."""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import asdict, fields

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rfb.loaders.base import CanonicalObs
from rfb.loaders.cwru import CWRULoader
from rfb.loaders.mvtec import MVTecLoader
from rfb.loaders.tep import N_VARS, TEPLoader

FORBIDDEN_FIELD_TOKENS = (
    "label",
    "path",
    "filename",
    "simulationrun",
    "simulation_run",
    "category",
    "attack",
    "truth",
)


def _visible_json(obs: CanonicalObs) -> str:
    return json.dumps(asdict(obs), ensure_ascii=False, sort_keys=True)


def _assert_markers_hidden(obs: CanonicalObs, *markers: object) -> None:
    visible = _visible_json(obs)
    for marker in markers:
        assert str(marker) not in visible


def test_canonical_obs_schema_has_no_truth_metadata_fields():
    field_names = {field.name.lower() for field in fields(CanonicalObs)}
    for token in FORBIDDEN_FIELD_TOKENS:
        assert all(token not in name for name in field_names)


def test_tep_truth_is_sidecar_only():
    loader = TEPLoader()
    normal = [[10.0 + j * 0.01 + i * 0.001 for j in range(N_VARS)] for i in range(12)]
    target = [[20.0 + j * 0.01 + i * 0.001 for j in range(N_VARS)] for i in range(8)]
    loader.fit_normal(normal)

    fault_marker = 913
    run_marker = "SIMULATION_RUN_SECRET_77"
    obs = loader.from_array(
        target,
        window=4,
        fault_label=fault_marker,
        simulation_run_id=run_marker,
    )

    assert obs[0].procedure == loader.PROCEDURE
    _assert_markers_hidden(obs[0], fault_marker, run_marker)
    sidecar = loader.scorer_only_metadata(obs[0])
    assert sidecar["fault_label"] == fault_marker
    assert sidecar["simulation_run_id"] == run_marker


def test_cwru_label_and_file_path_are_sidecar_only(monkeypatch, tmp_path):
    loader = CWRULoader(window=8)
    normal = [math.sin(i / 7.0) + (i % 5) * 0.01 for i in range(96)]
    target = [math.sin(i / 7.0) + (2.0 if i % 8 == 0 else 0.0) for i in range(96)]
    normal_path = tmp_path / "NORMAL_PRIVATE_SOURCE.mat"
    target_path = tmp_path / "IR007_SECRET_TARGET.mat"

    def fake_read_mat_signal(path, channel="DE"):
        return normal if os.fspath(path) == os.fspath(normal_path) else target

    monkeypatch.setattr("rfb.loaders.cwru.read_mat_signal", fake_read_mat_signal)
    obs = loader.load(os.fspath(normal_path), os.fspath(target_path))

    assert obs[0].procedure == loader.PROCEDURE
    _assert_markers_hidden(obs[0], target_path.name, os.fspath(target_path))
    sidecar = loader.scorer_only_metadata(obs[0])
    assert sidecar["label"] == target_path.name
    assert sidecar["source_filename"] == target_path.name
    assert sidecar["source_path"] == os.fspath(target_path)


def test_mvtec_category_and_image_path_are_sidecar_only(tmp_path):
    good_csv = tmp_path / "good.csv"
    scores_csv = tmp_path / "scores.csv"
    category_marker = "SECRET_CATEGORY_BOTTLE"
    image_marker = "SECRET_DEFECT_IMAGE_01.png"
    good_csv.write_text(
        "\n".join(f"good_{i}.png,{0.1 + i * 0.001},GOOD_PRIVATE" for i in range(12)),
        encoding="utf-8",
    )
    scores_csv.write_text(
        f"/private/source/{image_marker},0.91,{category_marker},SECRET_DEFECT_TYPE\n",
        encoding="utf-8",
    )

    loader = MVTecLoader(detector_name="patchcore")
    obs = loader.load(
        os.fspath(scores_csv), good_csv=os.fspath(good_csv), batch_id="lot-1"
    )

    assert obs[0].feature_of_interest == "lot-1"
    assert obs[0].procedure == f"{loader.PROCEDURE}|patchcore"
    _assert_markers_hidden(obs[0], category_marker, image_marker, "/private/source/")
    sidecar = loader.scorer_only_metadata(obs[0])
    assert sidecar["category"] == category_marker
    assert sidecar["source_filename"] == image_marker
    assert sidecar["source_path"] == f"/private/source/{image_marker}"


def test_sidecar_batch_api_is_explicit_and_separate():
    loader = TEPLoader()
    normal = [[10.0 + j * 0.01 + i * 0.001 for j in range(N_VARS)] for i in range(12)]
    loader.fit_normal(normal)
    obs = loader.from_array(normal[:8], window=4, fault_label=7)

    sidecar = loader.scorer_only_sidecar()
    assert len(sidecar) == len(obs)
    assert sidecar[0].observation_index == 0
    assert sidecar[0].metadata["fault_label"] == 7
    assert "fault_label" not in _visible_json(obs[0])
