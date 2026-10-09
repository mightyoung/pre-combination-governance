from __future__ import annotations

import hashlib
import hmac
import math
import os
import time
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Any

from ..capacity import (
    CAPACITY_DRAIN_BYTES,
    CAPACITY_HARD_LIMIT_BYTES,
    PLANNING_PEAK_LIMIT_BYTES,
    SUBBUDGETS,
    capacity_state,
    observed_capacity_bytes,
)
from ..contracts.canonical_json import canonical_bytes, sha256_hex

PANEL_METHODS = ("B0", "B1", "B2", "B3", "B4", "B5", "Proposed")


def HEX64(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _safe_basename(value: object) -> bool:
    """Accept only a single, relative basename on both POSIX and Windows."""
    if not isinstance(value, str) or not value or value in {".", ".."}:
        return False
    if "/" in value or "\\" in value:
        return False
    return (
        not Path(value).is_absolute()
        and not PureWindowsPath(value).is_absolute()
        and not PureWindowsPath(value).drive
    )


class SegmentState(StrEnum):
    PLANNED = "PLANNED"
    ADMITTED = "ADMITTED"
    MATERIALIZING = "MATERIALIZING"
    EXECUTING = "EXECUTING"
    RESULT_SEALED_LOCAL = "RESULT_SEALED_LOCAL"
    SIZING_REPORTED = "SIZING_REPORTED"


def validate_manifest(manifest: Mapping[str, Any], *, expected_domain="TEP"):
    if not isinstance(manifest, Mapping):
        raise TypeError("manifest must be an object")
    if manifest.get("dataset_domain") != expected_domain:
        raise ValueError("dataset_domain must be TEP")
    if (
        manifest.get("bundle_count") != 1
        or tuple(manifest.get("panel", ())) != PANEL_METHODS
    ):
        raise ValueError("complete single bundle panel required")
    if manifest.get("D_test") not in (None, False):
        raise ValueError("D_test is forbidden for C2")
    for k in ("manifest_sha256", "input_sha256", "allocation_commitment"):
        if not HEX64(manifest.get(k)):
            raise ValueError(f"{k} must be 64hex")
    for k in (
        "segment_id",
        "segment_root_base",
        "run_id",
        "probe_mount",
        "probe_owner",
        "probe_mode",
        "execution_mode",
    ):
        if not isinstance(manifest.get(k), str) or not manifest[k]:
            raise ValueError(f"{k} is required")
    if not _safe_basename(manifest["segment_id"]):
        raise ValueError("segment_id must be a safe basename")
    if manifest["execution_mode"] not in (
        "LOCAL_FIXTURE_NONCONFIRMATORY",
        "REAL_TEP_NONCONFIRMATORY",
    ):
        raise ValueError("invalid C2 execution_mode")

    x = dict(manifest)
    supplied = x.pop("manifest_sha256")
    x.pop("commitment", None)
    if supplied != sha256_hex(canonical_bytes(x)):
        raise ValueError("manifest commitment mismatch")
    return dict(manifest)


def validate_output_target(target, *, project_root):
    p, root = Path(target), Path(project_root).resolve(strict=True)
    if p.exists() and (
        p.is_symlink() or any(q.is_symlink() for q in [p] + list(p.parents))
    ):
        raise ValueError("output target may not be symlink")
    rp = p.resolve(strict=False)
    if rp == root or root not in rp.parents:
        raise ValueError("output target must be root-confined")
    if p.exists() and any(p.iterdir()):
        raise ValueError("output target must be empty")
    p.mkdir(parents=True, exist_ok=True)
    return p


def validate_trusted_probe(
    probe, *, manifest_sha256=None, trust_keys=None, manifest=None
):
    if not isinstance(probe, Mapping):
        raise ValueError("trusted probe artifact required")
    req = (
        "artifact_sha256",
        "probe_id",
        "source",
        "signer",
        "key_id",
        "role",
        "revocation_epoch",
        "implementation_sha256",
        "manifest_sha256",
        "segment_id",
        "root",
        "mount",
        "owner",
        "mode",
        "run_id",
        "sampled_at",
        "process_telemetry",
        "gpu_used",
        "project_tree_allocated_bytes",
        "filesystem_used_delta_bytes",
        "owned_external_layers_bytes",
        "open_deleted_bytes",
        "planning_peak_bytes",
        "subbudget_usage",
        "signature",
    )
    if any(k not in probe for k in req):
        raise ValueError("unbound trusted probe")
    if manifest_sha256 and probe["manifest_sha256"] != manifest_sha256:
        raise ValueError("probe binding mismatch")
    if manifest is not None:
        expected_root = (
            Path(manifest["segment_root_base"]).resolve(strict=True)
            / manifest["segment_id"]
        ).resolve()
        if (
            probe["segment_id"] != manifest["segment_id"]
            or Path(probe["root"]).resolve() != expected_root
            or probe["run_id"] != manifest["run_id"]
        ):
            raise ValueError("probe segment/root/run binding mismatch")
        for field in ("mount", "owner", "mode"):
            if str(probe[field]) != str(manifest["probe_" + field]):
                raise ValueError(f"probe {field} binding mismatch")
    for k in ("artifact_sha256", "implementation_sha256", "manifest_sha256"):
        if not HEX64(probe[k]):
            raise ValueError(f"{k} must be 64hex")
    for k in (
        "project_tree_allocated_bytes",
        "filesystem_used_delta_bytes",
        "owned_external_layers_bytes",
        "open_deleted_bytes",
        "planning_peak_bytes",
    ):
        if isinstance(probe[k], bool) or not isinstance(probe[k], int) or probe[k] < 0:
            raise ValueError(f"{k} must be non-negative integer")
    if (
        isinstance(probe["sampled_at"], bool)
        or not isinstance(probe["sampled_at"], (int, float))
        or not math.isfinite(probe["sampled_at"])
    ):
        raise ValueError("sampled_at must be finite")
    if not isinstance(probe["subbudget_usage"], Mapping) or set(
        probe["subbudget_usage"]
    ) != set(SUBBUDGETS):
        raise ValueError("all subbudget fields are required")
    for k, v in probe["subbudget_usage"].items():
        if (
            isinstance(v, bool)
            or not isinstance(v, int)
            or v < 0
            or v > SUBBUDGETS[k]
            or (k == "emergency_reserve" and v != 0)
        ):
            raise ValueError(f"invalid subbudget {k}")
    process = probe["process_telemetry"]
    if (
        not isinstance(process, Mapping)
        or not isinstance(process.get("owned_processes"), list)
        or not isinstance(process.get("owned_gpu_processes"), list)
    ):
        raise TypeError("complete process telemetry required")
    if not isinstance(probe["gpu_used"], bool) or probe["gpu_used"] != bool(
        process["owned_gpu_processes"]
    ):
        raise ValueError("gpu/process telemetry mismatch")
    entry = (trust_keys or {}).get(probe["key_id"])
    if not isinstance(entry, Mapping):
        raise ValueError("structured probe trust record required")
    required_trust = ("secret", "role", "epoch")
    if any(field not in entry for field in required_trust):
        raise ValueError("incomplete probe trust record")
    if not isinstance(entry["role"], str) or not entry["role"]:
        raise ValueError("probe trust role required")
    if (
        isinstance(entry["epoch"], bool)
        or not isinstance(entry["epoch"], int)
        or entry["epoch"] < 0
    ):
        raise ValueError("probe trust epoch must be non-negative integer")
    key, role, epoch = entry["secret"], entry["role"], entry["epoch"]
    if not isinstance(key, (str, bytes)) or not key:
        raise ValueError("probe key must be bytes or string")
    key_bytes = key if isinstance(key, bytes) else key.encode()
    if (
        role
        and probe["role"] != role
        or epoch is not None
        and probe["revocation_epoch"] != epoch
    ):
        raise ValueError("probe trust metadata mismatch")
    unsigned = dict(probe)
    sig = unsigned.pop("signature")
    supplied = unsigned.pop("artifact_sha256")
    if sha256_hex(canonical_bytes(unsigned)) != supplied:
        raise ValueError("probe artifact hash mismatch")
    if not hmac.compare_digest(
        sig,
        hmac.new(key_bytes, canonical_bytes(unsigned), hashlib.sha256).hexdigest(),
    ):
        raise ValueError("probe signature invalid")
    return dict(probe)


class C2SegmentOrchestrator:
    def __init__(self, manifest, output_root, *, project_root=None, providers=None):
        self.manifest = validate_manifest(manifest)
        if (
            not isinstance(self.manifest.get("segment_id"), str)
            or not self.manifest["segment_id"]
            or not _safe_basename(self.manifest["segment_id"])
        ):
            raise ValueError("segment_id must be a safe basename")
        if not isinstance(self.manifest.get("segment_root_base"), str):
            raise TypeError("segment_root_base is required")
        base = Path(self.manifest["segment_root_base"]).resolve(strict=True)
        if project_root is not None and base != Path(project_root).resolve(strict=True):
            raise ValueError("root binding mismatch")
        if (
            Path(output_root).resolve(strict=False)
            != base / self.manifest["segment_id"]
        ):
            raise ValueError("output must be manifest-bound segment root")
        self.output = validate_output_target(output_root, project_root=base)
        self.state = SegmentState.PLANNED
        self.telemetry = [{"state": "PLANNED", "sampled_at": time.time()}]
        self.providers = providers or {}

    def transition(self, state, *, sampled_at=None, telemetry=None):
        nxt = SegmentState(state)
        order = list(SegmentState)
        if order.index(nxt) != order.index(self.state) + 1:
            raise ValueError("non-adjacent state transition")
        now = time.time() if sampled_at is None else float(sampled_at)
        if self.telemetry and now - self.telemetry[-1]["sampled_at"] > 30:
            raise ValueError("telemetry gap exceeds 30 seconds")
        self.state = nxt
        self.telemetry.append(
            {"state": nxt.value, "sampled_at": now, **dict(telemetry or {})}
        )
        return self.state

    def _materialize(self):
        partial = self.output / "dataset.partial"
        final = self.output / "dataset"
        fn = self.providers.get("materialize")
        if fn:
            fn(self.manifest, partial)
        else:
            partial.write_bytes(
                canonical_bytes(
                    {"fixture": True, "segment_id": self.manifest["segment_id"]}
                )
            )
        if not partial.exists() or partial.is_symlink():
            raise ValueError("materializer did not produce safe partial")
        if self.providers.get("validate_materialized") and not self.providers[
            "validate_materialized"
        ](partial):
            raise ValueError("materialized validation failed")
        os.replace(partial, final)

    def run(self, probe):
        initial = validate_trusted_probe(
            probe,
            manifest_sha256=self.manifest["manifest_sha256"],
            trust_keys=self.providers.get("trust_keys"),
            manifest=self.manifest,
        )
        initial_cap = observed_capacity_bytes(
            initial["project_tree_allocated_bytes"],
            initial["filesystem_used_delta_bytes"],
            initial["owned_external_layers_bytes"] + initial["open_deleted_bytes"],
        )
        if initial_cap > CAPACITY_HARD_LIMIT_BYTES:
            raise ValueError("SAFE_HALT_CAP_BREACH")
        if initial["planning_peak_bytes"] > PLANNING_PEAK_LIMIT_BYTES:
            raise ValueError("planning peak exceeds fixed 22 GB limit")
        if initial["gpu_used"]:
            raise ValueError("C2 must remain CPU-only")
        self.transition(SegmentState.ADMITTED)
        self.transition(SegmentState.MATERIALIZING)
        self._materialize()
        initial_telemetry = {
            "capacity_bytes": initial_cap,
            "project_tree_allocated_bytes": initial["project_tree_allocated_bytes"],
            "filesystem_used_delta_bytes": initial["filesystem_used_delta_bytes"],
            "owned_external_layers_bytes": initial["owned_external_layers_bytes"],
            "open_deleted_bytes": initial["open_deleted_bytes"],
            "planning_peak_bytes": initial["planning_peak_bytes"],
            "subbudget_usage": initial["subbudget_usage"],
            "gpu_used": False,
            "gpu_not_used": True,
            "process_telemetry": initial["process_telemetry"],
            "probe_id": initial["probe_id"],
        }
        self.transition(SegmentState.EXECUTING, telemetry=initial_telemetry)
        mode = self.manifest["execution_mode"]
        run_panel = self.providers.get("run_panel") or self.providers.get(
            "formal_runner"
        )
        if mode == "REAL_TEP_NONCONFIRMATORY":
            if run_panel is not None:
                raise ValueError("real TEP rejects injected panel providers")
            required = ("loader", "formal_runner_instance", "durable_package_provider")
            if any(not self.providers.get(key) for key in required):
                raise ValueError("real TEP providers are required")

            def run_panel(manifest):
                return real_tep_panel_provider(
                    manifest,
                    loader=self.providers["loader"],
                    formal_runner=self.providers["formal_runner_instance"],
                    durable_package_provider=self.providers["durable_package_provider"],
                )

        elif run_panel is None:
            run_panel = (
                self.providers.get("fixture_run_panel")
                if mode == "LOCAL_FIXTURE_NONCONFIRMATORY"
                else None
            )
        if run_panel is None:
            raise ValueError("closed panel provider is required (fail-closed)")
        rows = run_panel(self.manifest)
        if (
            len(rows) != 7
            or {r.get("method_id") for r in rows} != set(PANEL_METHODS)
            or any(
                r.get("terminal_state") != "SEALED" or r.get("panel_closed") is not True
                for r in rows
            )
        ):
            raise ValueError("closed panel requires 7 SEALED rows")
        for row in rows:
            if not HEX64(row.get("result_sha256")):
                raise ValueError("result_sha256 must be 64hex")
            if row.get("durable_manifest_sha256") != self.manifest["manifest_sha256"]:
                raise ValueError(
                    "durable manifest is not bound to frozen segment manifest"
                )
            if not HEX64(row.get("durable_manifest_sha256")):
                raise ValueError("durable_manifest_sha256 must be 64hex")
        producer = self.providers.get("probe_producer")
        if mode == "REAL_TEP_NONCONFIRMATORY" and not callable(producer):
            raise ValueError("real C2 requires a final trusted probe producer")
        final = (
            initial
            if not callable(producer)
            else validate_trusted_probe(
                producer(self.manifest, self.output, "RESULT_SEALED_LOCAL"),
                manifest_sha256=self.manifest["manifest_sha256"],
                trust_keys=self.providers.get("trust_keys"),
                manifest=self.manifest,
            )
        )
        if (
            final["sampled_at"] < initial["sampled_at"]
            or final["sampled_at"] - initial["sampled_at"] > 30
        ):
            raise ValueError("capacity sampling gap exceeds 30 seconds")
        if final["gpu_used"]:
            raise ValueError("C2 must remain CPU-only")
        final_cap = observed_capacity_bytes(
            final["project_tree_allocated_bytes"],
            final["filesystem_used_delta_bytes"],
            final["owned_external_layers_bytes"] + final["open_deleted_bytes"],
        )
        cap = max(initial_cap, final_cap)
        if cap > CAPACITY_HARD_LIMIT_BYTES:
            raise ValueError("SAFE_HALT_CAP_BREACH")
        planning_peak = max(
            initial["planning_peak_bytes"], final["planning_peak_bytes"]
        )
        if planning_peak > PLANNING_PEAK_LIMIT_BYTES:
            raise ValueError("planning peak exceeds fixed 22 GB limit")
        usage = {
            k: max(initial["subbudget_usage"][k], final["subbudget_usage"][k])
            for k in SUBBUDGETS
        }
        final_telemetry = {
            "panel_closed": True,
            "capacity_bytes": cap,
            "capacity_state": capacity_state(cap).value,
            "project_tree_allocated_bytes": final["project_tree_allocated_bytes"],
            "filesystem_used_delta_bytes": final["filesystem_used_delta_bytes"],
            "owned_external_layers_bytes": final["owned_external_layers_bytes"],
            "open_deleted_bytes": final["open_deleted_bytes"],
            "planning_peak_bytes": planning_peak,
            "subbudget_usage": usage,
            "gpu_used": False,
            "gpu_not_used": True,
            "process_telemetry": final["process_telemetry"],
            "probe_id": final["probe_id"],
            "drain": cap >= CAPACITY_DRAIN_BYTES,
        }
        self.transition(SegmentState.RESULT_SEALED_LOCAL, telemetry=final_telemetry)
        if len([t for t in self.telemetry if "capacity_bytes" in t]) < 2:
            raise ValueError("capacity requires multiple lifecycle samples")
        from .report import C2ReportBuilder, atomic_write_report

        report = C2ReportBuilder(self.manifest).build(
            {
                "terminal_rows": rows,
                "capacity_transitions": [
                    t for t in self.telemetry if "capacity_bytes" in t
                ],
            },
            self.telemetry,
        )
        atomic_write_report(
            self.output / "single_bundle_sizing_report.json",
            report,
            durability_provider=self.providers.get("durability_provider"),
        )
        marker = self.output / "completion.marker"
        if marker.exists():
            raise FileExistsError("sealed output cannot be overwritten")
        with marker.open("w", encoding="utf-8") as f:
            f.write(report["report_sha256"])
            f.flush()
            os.fsync(f.fileno())
        self.state = SegmentState.SIZING_REPORTED
        return report


def real_tep_panel_provider(
    manifest, *, loader, formal_runner, durable_package_provider
):
    """Run a real TEP loader through FormalRunner and seal durable rows.
    This provider is injectable for local tests and never fabricates SEALED rows."""
    data_dir = str(
        (
            Path(manifest["segment_root_base"]).resolve(strict=True)
            / manifest["segment_id"]
            / "dataset"
        ).resolve()
    )
    if (
        Path(data_dir).parent
        != (
            Path(manifest["segment_root_base"]).resolve(strict=True)
            / manifest["segment_id"]
        ).resolve()
    ):
        raise ValueError("real TEP dataset escaped segment root")
    observations = loader.load(
        data_dir,
        fault=int(manifest.get("tep_fault", 0)),
        window=int(manifest.get("tep_window", 4)),
    )
    if not observations:
        raise ValueError("TEP loader produced no observations")
    events = [
        {
            "value": o.value,
            "unit": o.unit,
            "t_gen": o.t_gen,
            "feature_of_interest": o.feature_of_interest,
            "procedure": o.procedure,
            "quality": o.quality,
            "metadata": o.metadata,
        }
        for o in observations
    ]
    result = formal_runner.run_all(
        transaction_id="c2-" + str(manifest.get("run_id", manifest["segment_id"])),
        bundle_id=str(manifest.get("bundle_id", manifest["segment_id"])),
        observations={"events": events},
        truth=None,
        seed=int(manifest.get("algorithm_seed", 0)),
    )
    rows = []
    for method_id in PANEL_METHODS:
        key = next(
            (
                k
                for k in result.rows
                if (k[1] if isinstance(k, tuple) else result.rows[k].get("method_id"))
                == method_id
            ),
            None,
        )
        payload = result.rows[key] if key is not None else None
        if not isinstance(payload, Mapping):
            raise TypeError(f"formal runner missing {method_id}")
        rows.append(
            {
                "method_id": method_id,
                "terminal_state": "SEALED",
                "panel_closed": True,
                "result_sha256": sha256_hex(canonical_bytes(payload)),
            }
        )
    package = durable_package_provider(
        rows,
        manifest=manifest,
        segment_root=str(Path(data_dir).resolve().parent),
        run_id=str(manifest.get("run_id", manifest.get("segment_id"))),
        formal_rows=result.rows,
    )
    if not isinstance(package, Mapping) or not HEX64(package.get("manifest_sha256")):
        raise ValueError("durable package provider did not return hash-bound seal")
    if package["manifest_sha256"] != manifest["manifest_sha256"]:
        raise ValueError(
            "durable package manifest is not bound to frozen segment manifest"
        )
    for row in rows:
        row["durable_manifest_sha256"] = package["manifest_sha256"]
    return rows
