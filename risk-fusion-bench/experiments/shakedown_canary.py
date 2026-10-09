#!/usr/bin/env python3
"""Generate a strictly non-confirmatory G0/G2 shakedown canary package.

The canary exercises physical/noise/arrival seed separation and artifact
isolation.  It is not an empirical evaluation and cannot support paper claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


try:
    from rfb.benchmark.generator import Scenario
except (
    ModuleNotFoundError
):  # Allow `python -m experiments.shakedown_canary` from the repo root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from rfb.benchmark.generator import Scenario


RUN_CLASS = "G0_G2_SHAKEDOWN"
CONFIRMATORY = False
CLAIM_SUPPORT = "none"
MARKER_NAME = "NON_CONFIRMATORY_DO_NOT_PROMOTE"
FORBIDDEN_PAYLOAD_KEY_FRAGMENTS = (
    "label",
    "fault",
    "path",
    "filename",
    "simulationrun",
    "attack",
    "truth",
    "future",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _derive_seed(base_seed: int, *parts: object) -> int:
    material = "|".join(
        ["rfb-shakedown-canary-v1", str(int(base_seed)), *(str(part) for part in parts)]
    )
    return int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:8], "big")


def _metadata() -> dict[str, object]:
    return {
        "run_class": RUN_CLASS,
        "confirmatory": CONFIRMATORY,
        "claim_support": CLAIM_SUPPORT,
    }


def _validate_output_dir(output_dir: str | Path) -> Path:
    candidate = Path(output_dir).expanduser()
    raw = str(candidate).casefold()
    resolved = candidate.resolve(strict=False)
    if "d_test" in raw or "d_test" in str(resolved).casefold():
        raise ValueError(
            "output path containing D_test is forbidden for a shakedown canary"
        )
    if resolved.exists():
        if not resolved.is_dir():
            raise NotADirectoryError(resolved)
        if any(resolved.iterdir()):
            raise FileExistsError(f"output directory must be empty: {resolved}")
    else:
        resolved.mkdir(parents=True)
    return resolved


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(_canonical_json(record) + "\n")


def _artifact(path: Path, records: int) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "file": path.name,
        "records": records,
        "bytes": len(payload),
        "sha256": _sha256_bytes(payload),
    }


def _iter_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _iter_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_keys(child)


def _payload_has_forbidden_key(payload: dict[str, Any]) -> bool:
    forbidden = tuple(
        fragment.casefold() for fragment in FORBIDDEN_PAYLOAD_KEY_FRAGMENTS
    )
    return any(
        any(fragment in key.casefold() for fragment in forbidden)
        for key in _iter_keys(payload)
    )


def _semantic_observation(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": observation["source_id"],
        "t_gen": observation["t_gen"],
        "mass": observation["mass"],
    }


def _payload_semantic_hash(observations: Sequence[dict[str, Any]]) -> str:
    return _sha256_json(
        {
            "observations": [
                _semantic_observation(observation) for observation in observations
            ]
        }
    )


def _arrival_semantic_hash(
    payload: dict[str, Any], arrivals: Sequence[dict[str, Any]]
) -> str:
    observations_by_id = {
        observation["observation_id"]: observation
        for observation in payload["observations"]
    }
    semantic_arrivals = []
    for arrival in arrivals:
        observation = observations_by_id[arrival["observation_id"]]
        semantic_arrivals.append(
            {
                "observation_sha256": _sha256_json(_semantic_observation(observation)),
                "t_arrive": arrival["t_arrive"],
                "arrival_rank": arrival["arrival_rank"],
            }
        )
    return _sha256_json({"arrivals": semantic_arrivals})


def _truth_record(
    physical_index: int, physical_seed: int
) -> tuple[dict[str, Any], str]:
    physical_bundle_id = f"PB-{physical_index:04d}"
    scenario = Scenario(physical_seed=physical_seed, noise_seed=0)
    trajectory = [
        {"t": float(t), "risk": round(scenario.truth(float(t)), 12)}
        for t in range(0, int(scenario.duration) + 1, 5)
    ]
    truth_content = {"trajectory": trajectory}
    truth_sha256 = _sha256_json(truth_content)
    record = {
        **_metadata(),
        "physical_bundle_id": physical_bundle_id,
        "physical_seed": physical_seed,
        **truth_content,
        "truth_sha256": truth_sha256,
    }
    return record, truth_sha256


def _operational_payload(
    physical_index: int,
    physical_seed: int,
    noise_view: int,
    noise_seed: int,
) -> tuple[dict[str, Any], str]:
    physical_bundle_id = f"PB-{physical_index:04d}"
    payload_id = f"{physical_bundle_id}-N{noise_view:02d}"
    scenario = Scenario(physical_seed=physical_seed, noise_seed=noise_seed)
    observations = []
    for event_index, evidence in enumerate(scenario.emit(adversarial_rate=0.0)):
        observations.append(
            {
                "observation_id": f"{payload_id}-O{event_index:05d}",
                "source_id": evidence.source_id,
                "t_gen": round(float(evidence.t_gen), 9),
                "mass": {
                    str(key): round(float(value), 12)
                    for key, value in sorted(evidence.m.items())
                },
            }
        )
    hash_material = {
        **_metadata(),
        "payload_id": payload_id,
        "physical_bundle_id": physical_bundle_id,
        "noise_view": noise_view,
        "observations": observations,
    }
    if _payload_has_forbidden_key(hash_material):
        raise RuntimeError(
            "method-visible operational payload contains a forbidden field"
        )
    operational_payload_sha256 = _payload_semantic_hash(observations)
    record = {**hash_material, "operational_payload_sha256": operational_payload_sha256}
    return record, operational_payload_sha256


def _arrival_record(
    payload: dict[str, Any],
    arrival_view: int,
    arrival_seed: int,
) -> tuple[dict[str, Any], str]:
    rng = random.Random(arrival_seed)
    arrivals = []
    for observation in payload["observations"]:
        if arrival_view == 0:
            delay = 0.01
        else:
            delay = rng.uniform(0.05, 3.0)
            if rng.random() < 0.08:
                delay += rng.uniform(3.0, 8.0)
        arrivals.append(
            {
                "observation_id": observation["observation_id"],
                "t_arrive": round(float(observation["t_gen"]) + delay, 9),
            }
        )
    arrivals.sort(key=lambda row: (row["t_arrive"], row["observation_id"]))
    for rank, row in enumerate(arrivals):
        row["arrival_rank"] = rank
    hash_material = {
        **_metadata(),
        "payload_id": payload["payload_id"],
        "physical_bundle_id": payload["physical_bundle_id"],
        "noise_view": payload["noise_view"],
        "arrival_view": arrival_view,
        "arrivals": arrivals,
    }
    arrival_manifest_sha256 = _arrival_semantic_hash(payload, arrivals)
    return {
        **hash_material,
        "arrival_manifest_sha256": arrival_manifest_sha256,
    }, arrival_manifest_sha256


def _qa_report(
    truth_rows: Sequence[dict[str, Any]],
    payload_rows: Sequence[dict[str, Any]],
    arrival_rows: Sequence[dict[str, Any]],
    ledger_rows: Sequence[dict[str, Any]],
    physical_bundles: int,
    noise_views: int,
    arrival_views: int,
    replay_checks: dict[str, bool],
) -> dict[str, Any]:
    truth_hashes = {row["truth_sha256"] for row in truth_rows}
    truth_by_physical = {
        row["physical_bundle_id"]: row["truth_sha256"] for row in truth_rows
    }
    ledger_truth = defaultdict(set)
    ledger_groups = defaultdict(list)
    for row in ledger_rows:
        ledger_truth[row["physical_bundle_id"]].add(row["truth_sha256"])
        ledger_groups[(row["physical_bundle_id"], row["noise_view"])].append(row)

    payload_hashes_by_physical = defaultdict(set)
    for row in payload_rows:
        payload_hashes_by_physical[row["physical_bundle_id"]].add(
            row["operational_payload_sha256"]
        )
    noise_changes_observation_semantics = all(
        len(hashes) == noise_views for hashes in payload_hashes_by_physical.values()
    )

    payload_by_id = {row["payload_id"]: row for row in payload_rows}
    truth_hash_contract_valid = all(
        row["truth_sha256"] == _sha256_json({"trajectory": row["trajectory"]})
        for row in truth_rows
    )
    payload_hash_contract_valid = all(
        row["operational_payload_sha256"] == _payload_semantic_hash(row["observations"])
        for row in payload_rows
    )
    arrival_hash_contract_valid = all(
        row["arrival_manifest_sha256"]
        == _arrival_semantic_hash(payload_by_id[row["payload_id"]], row["arrivals"])
        for row in arrival_rows
    )
    semantic_hash_contracts_valid = (
        truth_hash_contract_valid
        and payload_hash_contract_valid
        and arrival_hash_contract_valid
    )

    exact_groups = all(len(rows) == arrival_views for rows in ledger_groups.values())
    stable_truth = all(
        hashes == {truth_by_physical[physical_id]}
        for physical_id, hashes in ledger_truth.items()
    )
    arrival_only = exact_groups and all(
        len({row["truth_sha256"] for row in rows}) == 1
        and len({row["operational_payload_sha256"] for row in rows}) == 1
        and len({row["arrival_manifest_sha256"] for row in rows}) == arrival_views
        for rows in ledger_groups.values()
    )
    checks = {
        "minimum_8_physical_bundles": physical_bundles >= 8,
        "minimum_2_noise_views": noise_views >= 2,
        "minimum_2_arrival_views": arrival_views >= 2,
        "truth_row_count": len(truth_rows) == physical_bundles,
        "payload_row_count": len(payload_rows) == physical_bundles * noise_views,
        "arrival_row_count": len(arrival_rows)
        == physical_bundles * noise_views * arrival_views,
        "ledger_row_count": len(ledger_rows)
        == physical_bundles * noise_views * arrival_views,
        "physical_seed_changes_truth_hash": len(truth_hashes) == physical_bundles,
        "noise_and_arrival_do_not_change_truth_hash": stable_truth,
        "noise_changes_observation_semantics": noise_changes_observation_semantics,
        "semantic_hash_contracts_valid": semantic_hash_contracts_valid,
        "arrival_only_changes_arrival_manifest": arrival_only,
        "same_seed_replay_truth_identical": replay_checks["truth"],
        "same_seed_replay_payload_identical": replay_checks["payload"],
        "same_seed_replay_arrival_identical": replay_checks["arrival"],
        "method_visible_payload_forbidden_fields_absent": not any(
            _payload_has_forbidden_key(payload) for payload in payload_rows
        ),
    }
    return {
        **_metadata(),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "counts": {
            "truth_rows": len(truth_rows),
            "operational_payload_rows": len(payload_rows),
            "arrival_manifest_rows": len(arrival_rows),
            "run_ledger_rows": len(ledger_rows),
        },
    }


def run_canary(
    output_dir: str | Path,
    *,
    base_seed: int = 20260714,
    physical_bundles: int = 8,
    noise_views: int = 2,
    arrival_views: int = 2,
) -> dict[str, Any]:
    """Write one isolated, non-confirmatory canary package."""
    if physical_bundles < 8 or noise_views < 2 or arrival_views < 2:
        raise ValueError(
            "canary design requires at least 8 physical bundles x 2 noise x 2 arrival views"
        )
    output = _validate_output_dir(output_dir)

    marker_path = output / MARKER_NAME
    marker_path.write_text(
        "NON_CONFIRMATORY_DO_NOT_PROMOTE\n"
        f"run_class={RUN_CLASS}\n"
        "confirmatory=false\n"
        "claim_support=none\n",
        encoding="utf-8",
    )

    truth_rows: list[dict[str, Any]] = []
    payload_rows: list[dict[str, Any]] = []
    arrival_rows: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    replay_checks = {"truth": True, "payload": True, "arrival": True}

    for physical_index in range(physical_bundles):
        physical_seed = _derive_seed(base_seed, "physical", physical_index)
        truth_record, truth_sha256 = _truth_record(physical_index, physical_seed)
        replay_truth, replay_truth_sha256 = _truth_record(physical_index, physical_seed)
        replay_checks["truth"] = replay_checks["truth"] and (
            truth_sha256 == replay_truth_sha256
            and _canonical_json(truth_record) == _canonical_json(replay_truth)
        )
        truth_rows.append(truth_record)
        for noise_view in range(noise_views):
            noise_seed = _derive_seed(base_seed, "noise", physical_index, noise_view)
            payload, payload_sha256 = _operational_payload(
                physical_index, physical_seed, noise_view, noise_seed
            )
            replay_payload, replay_payload_sha256 = _operational_payload(
                physical_index, physical_seed, noise_view, noise_seed
            )
            replay_checks["payload"] = replay_checks["payload"] and (
                payload_sha256 == replay_payload_sha256
                and _canonical_json(payload) == _canonical_json(replay_payload)
            )
            payload_rows.append(payload)
            for arrival_view in range(arrival_views):
                arrival_seed = _derive_seed(
                    base_seed, "arrival", physical_index, noise_view, arrival_view
                )
                arrival, arrival_sha256 = _arrival_record(
                    payload, arrival_view, arrival_seed
                )
                replay_arrival, replay_arrival_sha256 = _arrival_record(
                    payload, arrival_view, arrival_seed
                )
                replay_checks["arrival"] = replay_checks["arrival"] and (
                    arrival_sha256 == replay_arrival_sha256
                    and _canonical_json(arrival) == _canonical_json(replay_arrival)
                )
                arrival_rows.append(arrival)
                ledger_rows.append(
                    {
                        **_metadata(),
                        "run_id": f"{payload['payload_id']}-A{arrival_view:02d}",
                        "physical_bundle_id": payload["physical_bundle_id"],
                        "noise_view": noise_view,
                        "arrival_view": arrival_view,
                        "truth_sha256": truth_sha256,
                        "operational_payload_sha256": payload_sha256,
                        "arrival_manifest_sha256": arrival_sha256,
                        "status": "GENERATED_NOT_EXECUTED",
                    }
                )

    truth_path = output / "scorer_only_truth_store.jsonl"
    payload_path = output / "method_visible_operational_payload.jsonl"
    arrival_path = output / "arrival_manifest.jsonl"
    ledger_path = output / "run_ledger.jsonl"
    qa_path = output / "qa.json"
    manifest_path = output / "manifest.json"

    _write_jsonl(truth_path, truth_rows)
    _write_jsonl(payload_path, payload_rows)
    _write_jsonl(arrival_path, arrival_rows)
    _write_jsonl(ledger_path, ledger_rows)

    qa = _qa_report(
        truth_rows,
        payload_rows,
        arrival_rows,
        ledger_rows,
        physical_bundles,
        noise_views,
        arrival_views,
        replay_checks,
    )
    _write_json(qa_path, qa)
    if qa["status"] != "PASS":
        raise RuntimeError(f"shakedown QA failed; inspect {qa_path}")

    manifest = {
        **_metadata(),
        "schema_version": "rfb-shakedown-canary-1.0",
        "status": "NON_CONFIRMATORY_DO_NOT_PROMOTE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_seed": int(base_seed),
        "design": {
            "physical_bundles": physical_bundles,
            "noise_views_per_physical": noise_views,
            "arrival_views_per_noise": arrival_views,
        },
        "isolation_contract": {
            "truth_store_role": "scorer_only",
            "operational_payload_role": "method_visible",
            "arrival_changes_only": "arrival_manifest",
            "truth_hash_basis": ["trajectory"],
            "operational_payload_hash_basis": ["source_id", "t_gen", "mass"],
            "arrival_manifest_hash_basis": [
                "observation_semantic_sha256",
                "t_arrive",
                "arrival_rank",
            ],
            "forbidden_operational_payload_key_fragments": list(
                FORBIDDEN_PAYLOAD_KEY_FRAGMENTS
            ),
        },
        "artifacts": [
            _artifact(marker_path, 1),
            _artifact(truth_path, len(truth_rows)),
            _artifact(payload_path, len(payload_rows)),
            _artifact(arrival_path, len(arrival_rows)),
            _artifact(ledger_path, len(ledger_rows)),
            _artifact(qa_path, 1),
        ],
    }
    _write_json(manifest_path, manifest)
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-seed", type=int, default=20260714)
    parser.add_argument("--physical-bundles", type=int, default=8)
    parser.add_argument("--noise-views", type=int, default=2)
    parser.add_argument("--arrival-views", type=int, default=2)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manifest = run_canary(
        args.output_dir,
        base_seed=args.base_seed,
        physical_bundles=args.physical_bundles,
        noise_views=args.noise_views,
        arrival_views=args.arrival_views,
    )
    print(
        json.dumps(
            {
                **_metadata(),
                "output_dir": str(args.output_dir.expanduser().resolve()),
                "manifest_sha256": _sha256_json(manifest),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
