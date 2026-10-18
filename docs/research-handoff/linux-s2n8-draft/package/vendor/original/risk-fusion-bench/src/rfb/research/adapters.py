"""Closed, controller-owned research adapters.

Adapters are deliberately boring: a manifest selects a name and data-only
parameters; this module owns the implementation, command and environment.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rfb.research.isolation import (
    build_method_event_bundle,
)

PLANNED_BYTES = 22_000_000_000
DRAIN_BYTES = 24_000_000_000
HARD_HALT_BYTES = 25_000_000_000
SEGMENT_START_FREE_MIN_BYTES = 265_853_007_872
REMOTE_RESERVE_FLOOR_BYTES = 235_853_007_872
SUBBUDGETS = {
    "dataset": 16_000_000_000,
    "durable_result": 3_000_000_000,
    "scratch_partial": 2_000_000_000,
    "retry_quarantine_wal": 1_000_000_000,
    "emergency_reserve": 3_000_000_000,
}
METHOD_PANEL = ("B0", "B1", "B2", "B3", "B4", "B5", "Proposed")
CAPACITY_FIELDS = (
    "dataset",
    "durable_result",
    "scratch_partial",
    "retry_quarantine_wal",
    "emergency_reserve",
)
TELEMETRY_FIELDS = (
    "project_tree_allocated_bytes",
    "filesystem_used_delta_bytes",
    "owned_external_layers_bytes",
    "open_deleted_bytes",
)


@dataclass(frozen=True)
class AdapterSpec:
    adapter_id: str
    version: str = "1"
    fixture_only: bool = False

    @property
    def implementation_sha256(self) -> str:
        return hashlib.sha256(f"{self.adapter_id}:{self.version}".encode()).hexdigest()

    def fixed_argv(self, manifest_path: Path) -> list[str]:
        # Only this controller-owned template may launch the worker.
        return [
            sys.executable,
            "-m",
            "rfb.research",
            "worker",
            "--manifest",
            str(manifest_path),
        ]

    def minimal_environment(self, *, root: Path | None = None) -> dict[str, str]:
        env = {
            "CUDA_VISIBLE_DEVICES": "-1",
            "PATH": os.environ.get("PATH", ""),
            "PYTHONUTF8": "1",
            "PYTHONUNBUFFERED": "1",
        }
        if root is not None:
            env["RFB_RESEARCH_ROOT"] = str(root)
        return env

    def execute(self, manifest: Mapping[str, Any], output: Path) -> dict[str, Any]:
        validate_adapter_contract(manifest)
        output.mkdir(parents=True, exist_ok=True)
        payload = {
            "adapter_id": self.adapter_id,
            "run_id": manifest["run_id"],
            "panel": list(METHOD_PANEL),
            "bundle_complete": True,
            "effect_peeking": False,
            "segment_boundary_frozen": True,
            "capacity_state": capacity_state(manifest.get("capacity", {}))
            if not self.fixture_only
            else "FIXTURE_ONLY",
        }
        (output / "adapter_result.json").write_text(
            json.dumps(payload, sort_keys=True), encoding="utf-8"
        )
        return payload


class TEPNonconfirmatoryAdapter(AdapterSpec):
    """Bounded TEP loader + closed method panel; never emits formal claims."""

    def execute(self, manifest: Mapping[str, Any], output: Path) -> dict[str, Any]:
        validate_adapter_contract(manifest)
        from rfb.loaders.tep import TEPLoader
        from rfb.methods import run_all

        params = dict(manifest.get("adapter_params", {}))
        loader = TEPLoader()
        data_root = manifest.get("dataset_root")
        if data_root:
            observations = loader.load(
                str(Path(data_root).resolve()),
                fault=int(params.get("fault", 0)),
                window=int(params.get("window", 4)),
            )
        else:
            rows = params.get("rows")
            if not rows or len(rows) < 12:
                raise ValueError("TEP data unavailable")
            loader.fit_normal(rows)
            observations = loader.from_array(rows, window=int(params.get("window", 4)))
        if not observations:
            raise ValueError("TEP method-visible observations unavailable")
        method_bundle = build_method_event_bundle(
            bundle_id=manifest["run_id"],
            algorithm_seed=int(manifest.get("algorithm_seed", 0)),
            observations=observations,
            bpa_mapper=loader.to_bpa,
            prop_mask=loader.PROP_MASK,
        )
        outputs = run_all(method_bundle.to_run_all_payload())
        if tuple(outputs) != METHOD_PANEL or any(
            not isinstance(v, Mapping) for v in outputs.values()
        ):
            raise ValueError("TEP full method panel unavailable")
        output.mkdir(parents=True, exist_ok=True)
        result = {
            "adapter_id": self.adapter_id,
            "run_id": manifest["run_id"],
            "method_outputs": outputs,
            "method_panel": list(METHOD_PANEL),
            "method_event_count": len(method_bundle.events),
            "bundle_complete": True,
            "effect_peeking": False,
            "segment_boundary_frozen": True,
        }
        encoded = json.dumps(result, sort_keys=True, default=str).encode()
        result["durable_result_sha256"] = hashlib.sha256(encoded).hexdigest()
        (output / "tep_result.json").write_text(
            json.dumps(result, sort_keys=True, default=str), encoding="utf-8"
        )
        return result


_FIXTURE_REGISTRY = {
    "tep_fixture": AdapterSpec("tep_fixture", fixture_only=True),
    "local_fixture_nonconfirmatory": AdapterSpec(
        "local_fixture_nonconfirmatory", fixture_only=True
    ),
}
_PRODUCTION_REGISTRY = {
    "tep_nonconfirmatory_v1": TEPNonconfirmatoryAdapter("tep_nonconfirmatory_v1"),
}
_REGISTRY = {**_FIXTURE_REGISTRY, **_PRODUCTION_REGISTRY}


def registry() -> Mapping[str, AdapterSpec]:
    return dict(_REGISTRY)


def fixture_registry() -> Mapping[str, AdapterSpec]:
    return dict(_FIXTURE_REGISTRY)


def production_registry() -> Mapping[str, AdapterSpec]:
    return dict(_PRODUCTION_REGISTRY)


def resolve_adapter(adapter_id: str) -> AdapterSpec:
    try:
        return _REGISTRY[adapter_id]
    except KeyError as exc:
        raise ValueError("ADAPTER_DENIED: unknown adapter_id") from exc


def validate_adapter_contract(manifest: Mapping[str, Any]) -> None:
    adapter_id = manifest.get("adapter_id")
    spec = resolve_adapter(adapter_id)
    panel = manifest.get("method_panel", manifest.get("panel", list(METHOD_PANEL)))
    if tuple(panel) != METHOD_PANEL:
        raise ValueError("ADAPTER_DENIED: complete B0-B5+Proposed panel required")
    if manifest.get("effect_peeking", False) or manifest.get(
        "adaptive_segmentation", False
    ):
        raise ValueError(
            "ADAPTER_DENIED: effect peeking/adaptive segmentation forbidden"
        )
    if manifest.get("scientific_acceptance") and spec.fixture_only:
        raise ValueError("FIXTURE_ADAPTER_NOT_SCIENTIFIC")
    capacity = manifest.get("capacity")
    if spec.fixture_only and capacity is None:
        return
    if capacity is None:
        raise ValueError("CAPACITY_REQUIRED")
    capacity_state(capacity)
    if spec.fixture_only:
        return
    seed = manifest.get("algorithm_seed")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("ALGORITHM_SEED_REQUIRED")
    params = manifest.get("adapter_params", {})
    if not manifest.get("dataset_root") and not params.get("rows"):
        raise ValueError("TEP_DATA_CAPABILITY_REQUIRED")


def capacity_state(capacity: Mapping[str, Any]) -> str:
    if not isinstance(capacity, Mapping):
        raise ValueError("CAPACITY_REQUIRED")
    required = {"planned_bytes", "drain_bytes", *CAPACITY_FIELDS, "telemetry"}
    if set(capacity) != required:
        raise ValueError("SUBBUDGET_BORROWING")
    for key, value in capacity.items():
        if key == "telemetry":
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("CAPACITY_VALUE_INVALID")
    if capacity["planned_bytes"] != PLANNED_BYTES:
        raise ValueError("CAPACITY_PLANNING_INVALID")
    if capacity["drain_bytes"] != DRAIN_BYTES:
        raise ValueError("CAPACITY_DRAIN")
    if capacity["planned_bytes"] > HARD_HALT_BYTES:
        raise ValueError("CAPACITY_HARD_HALT")
    if capacity["drain_bytes"] > DRAIN_BYTES:
        raise ValueError("CAPACITY_DRAIN")
    if any(capacity[key] != limit for key, limit in SUBBUDGETS.items()):
        raise ValueError("SUBBUDGET_BORROWING")
    telemetry = capacity["telemetry"]
    if not isinstance(telemetry, Mapping):
        raise ValueError("CAPACITY_TELEMETRY_UNAVAILABLE")
    if "observed_peak_bytes" not in telemetry:
        raise ValueError("CAPACITY_TELEMETRY_UNAVAILABLE")
    telemetry_values = [telemetry[field] for field in TELEMETRY_FIELDS]
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in telemetry_values
    ):
        raise ValueError("CAPACITY_TELEMETRY_UNAVAILABLE")
    peak = max(
        telemetry["project_tree_allocated_bytes"],
        telemetry["filesystem_used_delta_bytes"]
        + telemetry["owned_external_layers_bytes"]
        + telemetry["open_deleted_bytes"],
    )
    reported_peak = telemetry.get("observed_peak_bytes")
    if reported_peak is not None and reported_peak != peak:
        raise ValueError("CAPACITY_TELEMETRY_MISMATCH")
    if peak > HARD_HALT_BYTES:
        raise ValueError("SAFE_HALT_CAP_BREACH")
    if peak >= DRAIN_BYTES:
        return "DRAIN_AND_SEAL"
    if peak > PLANNED_BYTES:
        raise ValueError("CAPACITY_PLANNING_INVALID")
    return "PLANNED"


def validate_remote_capacity(
    *,
    available_bytes: int,
    remaining_manifest_owned_growth_bytes: int,
    planned_active_peak_bytes: int = PLANNED_BYTES,
) -> str:
    """Apply the frozen Revision 6 decimal-byte start and reserve thresholds."""
    values = (
        available_bytes,
        remaining_manifest_owned_growth_bytes,
        planned_active_peak_bytes,
    )
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in values
    ):
        raise ValueError("CAPACITY_TELEMETRY_UNAVAILABLE")
    if available_bytes < SEGMENT_START_FREE_MIN_BYTES:
        raise ValueError("SEGMENT_START_FREE_BELOW_MINIMUM")
    if (
        available_bytes - remaining_manifest_owned_growth_bytes
        < REMOTE_RESERVE_FLOOR_BYTES
    ):
        raise ValueError("REMOTE_RESERVE_FLOOR_BREACH")
    if planned_active_peak_bytes > PLANNED_BYTES:
        raise ValueError("CAPACITY_PLANNING_INVALID")
    return "CAPACITY_ACCEPTED"
