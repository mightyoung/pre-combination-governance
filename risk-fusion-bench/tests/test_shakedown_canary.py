# -*- coding: utf-8 -*-
"""Contract tests for the non-confirmatory G0/G2 shakedown canary."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from experiments.shakedown_canary import (  # noqa: E402
    FORBIDDEN_PAYLOAD_KEY_FRAGMENTS,
    main,
    run_canary,
)


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _iter_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _iter_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_keys(child)


def test_rejects_any_output_path_containing_d_test(tmp_path: Path):
    rejected = tmp_path / "nested" / "D_test-canary"

    with pytest.raises(ValueError, match="D_test"):
        run_canary(rejected)

    assert not rejected.exists()


def test_cli_writes_nonconfirmatory_artifacts_and_preserves_seed_isolation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    output_dir = tmp_path / "g0-g2-canary"

    assert main(["--output-dir", str(output_dir), "--base-seed", "20260714"]) == 0
    cli_result = json.loads(capsys.readouterr().out)
    assert Path(cli_result["output_dir"]) == output_dir.resolve()
    assert cli_result["run_class"] == "G0_G2_SHAKEDOWN"
    assert cli_result["confirmatory"] is False
    assert cli_result["claim_support"] == "none"

    expected = {
        "NON_CONFIRMATORY_DO_NOT_PROMOTE",
        "manifest.json",
        "scorer_only_truth_store.jsonl",
        "method_visible_operational_payload.jsonl",
        "arrival_manifest.jsonl",
        "run_ledger.jsonl",
        "qa.json",
    }
    assert expected == {path.name for path in output_dir.iterdir()}

    marker = (output_dir / "NON_CONFIRMATORY_DO_NOT_PROMOTE").read_text(
        encoding="utf-8"
    )
    assert "NON_CONFIRMATORY_DO_NOT_PROMOTE" in marker

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    qa = json.loads((output_dir / "qa.json").read_text(encoding="utf-8"))
    truth_rows = _read_jsonl(output_dir / "scorer_only_truth_store.jsonl")
    payload_rows = _read_jsonl(output_dir / "method_visible_operational_payload.jsonl")
    arrival_rows = _read_jsonl(output_dir / "arrival_manifest.jsonl")
    ledger_rows = _read_jsonl(output_dir / "run_ledger.jsonl")

    for record in (manifest, qa, *ledger_rows):
        assert record["run_class"] == "G0_G2_SHAKEDOWN"
        assert record["confirmatory"] is False
        assert record["claim_support"] == "none"

    assert manifest["design"] == {
        "physical_bundles": 8,
        "noise_views_per_physical": 2,
        "arrival_views_per_noise": 2,
    }
    assert len(truth_rows) == 8
    assert len(payload_rows) == 16
    assert len(arrival_rows) == 32
    assert len(ledger_rows) == 32
    assert qa["status"] == "PASS"
    assert all(qa["checks"].values())

    truth_hashes = {row["truth_sha256"] for row in truth_rows}
    assert len(truth_hashes) == 8, (
        "each physical seed must produce a distinct truth hash"
    )
    for row in truth_rows:
        truth_content = json.dumps(
            {"trajectory": row["trajectory"]},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        assert row["truth_sha256"] == hashlib.sha256(truth_content).hexdigest()

    payload_hashes_by_physical = defaultdict(set)
    for row in payload_rows:
        semantic_observations = [
            {
                "source_id": observation["source_id"],
                "t_gen": observation["t_gen"],
                "mass": observation["mass"],
            }
            for observation in row["observations"]
        ]
        payload_content = json.dumps(
            {"observations": semantic_observations},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expected_payload_hash = hashlib.sha256(payload_content).hexdigest()
        assert row["operational_payload_sha256"] == expected_payload_hash
        payload_hashes_by_physical[row["physical_bundle_id"]].add(expected_payload_hash)
    assert all(len(hashes) == 2 for hashes in payload_hashes_by_physical.values())

    payload_by_id = {row["payload_id"]: row for row in payload_rows}
    for row in arrival_rows:
        observations_by_id = {
            observation["observation_id"]: observation
            for observation in payload_by_id[row["payload_id"]]["observations"]
        }
        semantic_arrivals = []
        for arrival in row["arrivals"]:
            observation = observations_by_id[arrival["observation_id"]]
            observation_content = json.dumps(
                {
                    "source_id": observation["source_id"],
                    "t_gen": observation["t_gen"],
                    "mass": observation["mass"],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            semantic_arrivals.append(
                {
                    "observation_sha256": hashlib.sha256(
                        observation_content
                    ).hexdigest(),
                    "t_arrive": arrival["t_arrive"],
                    "arrival_rank": arrival["arrival_rank"],
                }
            )
        arrival_content = json.dumps(
            {"arrivals": semantic_arrivals},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        assert (
            row["arrival_manifest_sha256"]
            == hashlib.sha256(arrival_content).hexdigest()
        )

    truth_by_physical = {
        row["physical_bundle_id"]: row["truth_sha256"] for row in truth_rows
    }
    ledger_by_physical = defaultdict(set)
    ledger_by_payload = defaultdict(list)
    for row in ledger_rows:
        ledger_by_physical[row["physical_bundle_id"]].add(row["truth_sha256"])
        ledger_by_payload[(row["physical_bundle_id"], row["noise_view"])].append(row)

    assert all(
        hashes == {truth_by_physical[bundle_id]}
        for bundle_id, hashes in ledger_by_physical.items()
    )
    for rows in ledger_by_payload.values():
        assert len(rows) == 2
        assert len({row["truth_sha256"] for row in rows}) == 1
        assert len({row["operational_payload_sha256"] for row in rows}) == 1
        assert len({row["arrival_manifest_sha256"] for row in rows}) == 2

    forbidden = tuple(
        fragment.casefold() for fragment in FORBIDDEN_PAYLOAD_KEY_FRAGMENTS
    )
    for payload in payload_rows:
        for key in _iter_keys(payload):
            folded = key.casefold()
            assert not any(fragment in folded for fragment in forbidden), key

    assert qa["checks"]["same_seed_replay_truth_identical"] is True
    assert qa["checks"]["same_seed_replay_payload_identical"] is True
    assert qa["checks"]["same_seed_replay_arrival_identical"] is True
    assert qa["checks"]["noise_changes_observation_semantics"] is True
    assert qa["checks"]["semantic_hash_contracts_valid"] is True

    replay_dir = tmp_path / "g0-g2-canary-replay"
    run_canary(replay_dir, base_seed=20260714)
    for name in (
        "scorer_only_truth_store.jsonl",
        "method_visible_operational_payload.jsonl",
        "arrival_manifest.jsonl",
    ):
        assert (output_dir / name).read_bytes() == (replay_dir / name).read_bytes()
