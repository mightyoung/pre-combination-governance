from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import shutil
import time
from pathlib import Path

from ..contracts.canonical_json import canonical_bytes, sha256_hex
from ..durable_package import seal_durable_package
from ..durable_results import row_result_sha256
from ..formal.runner import FormalRunner
from ..loaders.tep import TEPLoader
from ..methods import get_registry
from .segment import PANEL_METHODS, C2SegmentOrchestrator, validate_manifest


class _FixtureDurability:
    """Development-only durability stub; fixture reports have live_gate_effect=NONE."""

    def fsync_dir(self, _path: Path) -> None:
        return None


def _read_json(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _fixture_probe(manifest: dict) -> tuple[dict, dict]:
    unsigned = {
        "probe_id": "fixture",
        "source": "local-development-fixture",
        "signer": "fixture",
        "key_id": "fixture",
        "role": "capacity",
        "revocation_epoch": 0,
        "implementation_sha256": "0" * 64,
        "manifest_sha256": manifest["manifest_sha256"],
        "segment_id": manifest["segment_id"],
        "root": str(Path(manifest["segment_root_base"]) / manifest["segment_id"]),
        "mount": manifest["probe_mount"],
        "owner": manifest["probe_owner"],
        "mode": manifest["probe_mode"],
        "run_id": manifest["run_id"],
        "sampled_at": time.time(),
        "process_telemetry": {
            "owned_processes": [],
            "owned_gpu_processes": [],
        },
        "gpu_used": False,
        "project_tree_allocated_bytes": 1,
        "filesystem_used_delta_bytes": 1,
        "owned_external_layers_bytes": 0,
        "open_deleted_bytes": 0,
        "planning_peak_bytes": 1,
        "subbudget_usage": {
            "ephemeral_dataset": 0,
            "durable_result_staging": 0,
            "scratch_partial": 0,
            "retry_quarantine_wal": 0,
            "emergency_reserve": 0,
        },
    }
    unsigned["artifact_sha256"] = sha256_hex(canonical_bytes(unsigned))
    signature_body = {
        key: value for key, value in unsigned.items() if key != "artifact_sha256"
    }
    probe = {
        **unsigned,
        "signature": hmac.new(
            b"fixture", canonical_bytes(signature_body), hashlib.sha256
        ).hexdigest(),
    }
    trust = {"fixture": {"secret": "fixture", "role": "capacity", "epoch": 0}}
    return probe, trust


def _materializer(source: Path):
    source = source.resolve(strict=True)

    def materialize(_manifest: dict, partial: Path) -> None:
        if not source.is_dir():
            raise ValueError("TEP source must be a directory")
        shutil.copytree(source, partial)

    return materialize


def _durable_provider(
    _rows,
    *,
    manifest,
    segment_root,
    run_id,
    formal_rows,
):
    selected = []
    expected = []
    for key, formal in formal_rows.items():
        bundle_id, method_id, seed = key
        base = {
            "bundle_id": str(bundle_id),
            "method_id": str(method_id),
            "algorithm_seed": int(seed),
            "prediction_or_decision": dict(formal.get("output", {})),
            "scorer_metrics": dict(formal.get("metrics", {})),
            "validity_status": "VALID",
            "failure_or_timeout_code": None,
            "stratum_template_batch_superblock_keys": {},
            "resource_telemetry": {},
            "input_commitment": manifest["input_sha256"],
            "generator_candidate_method_scorer_schema_container_allocation_prereg_hashes": {
                "allocation_commitment": manifest["allocation_commitment"],
                "manifest_sha256": manifest["manifest_sha256"],
            },
            "transaction_id": "c2-" + run_id,
            "contains_raw_dataset": False,
        }
        selected.append({**base, "result_sha256": row_result_sha256(base)})
        expected.append((str(bundle_id), str(method_id), str(seed)))
    destination = Path(segment_root) / "durable-package"
    return seal_durable_package(
        destination,
        rows=selected,
        expected_keys=expected,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    segment = subparsers.add_parser("segment")
    segment.add_argument("--manifest", required=True)
    segment.add_argument("--output", required=True)
    segment.add_argument("--initial-probe")
    segment.add_argument("--final-probe")
    segment.add_argument("--trust-keys")
    segment.add_argument("--tep-source")
    args = parser.parse_args()
    if args.command != "segment":
        parser.print_help()
        return 2

    manifest = validate_manifest(_read_json(args.manifest))
    mode = manifest["execution_mode"]
    if mode == "LOCAL_FIXTURE_NONCONFIRMATORY":
        probe, trust = _fixture_probe(manifest)
        providers = {
            "trust_keys": trust,
            "durability_provider": _FixtureDurability(),
            "fixture_run_panel": lambda current: [
                {
                    "method_id": method_id,
                    "terminal_state": "SEALED",
                    "panel_closed": True,
                    "result_sha256": "0" * 64,
                    "durable_manifest_sha256": current["manifest_sha256"],
                }
                for method_id in PANEL_METHODS
            ],
        }
    else:
        required = {
            "--initial-probe": args.initial_probe,
            "--final-probe": args.final_probe,
            "--trust-keys": args.trust_keys,
            "--tep-source": args.tep_source,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise SystemExit("real C2 missing: " + ", ".join(missing))
        probe = _read_json(args.initial_probe)
        final_probe = _read_json(args.final_probe)
        providers = {
            "trust_keys": _read_json(args.trust_keys),
            "materialize": _materializer(Path(args.tep_source)),
            "loader": TEPLoader(),
            "formal_runner_instance": FormalRunner(get_registry()),
            "durable_package_provider": _durable_provider,
            "probe_producer": lambda *_: final_probe,
        }

    report = C2SegmentOrchestrator(
        manifest,
        args.output,
        providers=providers,
    ).run(probe)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
