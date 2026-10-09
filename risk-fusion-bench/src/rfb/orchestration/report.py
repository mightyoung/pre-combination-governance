from __future__ import annotations

import json
import os
from collections.abc import Mapping
from itertools import pairwise
from pathlib import Path

from jsonschema import Draft202012Validator

from ..contracts.canonical_json import canonical_bytes, sha256_hex

TERMINAL_ALLOWED = {
    "method_id",
    "terminal_state",
    "panel_closed",
    "result_sha256",
    "durable_manifest_sha256",
}
FORBIDDEN = {
    "prediction",
    "predictions",
    "effect",
    "winner",
    "rank",
    "p",
    "p_value",
    "ci",
    "confidence_interval",
    "raw_truth",
    "truth",
    "metrics",
    "observed_outputs",
    "method_outputs",
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "api_key",
    "apikey",
    "authorization",
    "access_token",
}


def _scan(value, path="$"):
    if isinstance(value, Mapping):
        for k, v in value.items():
            if str(k).lower() in FORBIDDEN:
                raise ValueError(f"forbidden C2 field: {path}.{k}")
            _scan(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _scan(v, f"{path}[{i}]")


class C2ReportBuilder:
    def __init__(self, manifest):
        self.manifest = dict(manifest)

    def build(self, observed, telemetry):
        _scan(observed)
        if (
            not telemetry
            or telemetry[0].get("state") != "PLANNED"
            or telemetry[-1].get("state") != "RESULT_SEALED_LOCAL"
        ):
            raise ValueError("telemetry must cover lifecycle")
        if len(telemetry) != 5 or {x.get("state") for x in telemetry} != {
            "PLANNED",
            "ADMITTED",
            "MATERIALIZING",
            "EXECUTING",
            "RESULT_SEALED_LOCAL",
        }:
            raise ValueError("telemetry must cover all states")
        for a, b in pairwise(telemetry):
            if float(b["sampled_at"]) - float(a["sampled_at"]) > 30:
                raise ValueError("telemetry gap exceeds 30 seconds")
        if (
            not isinstance(self.manifest.get("manifest_sha256"), str)
            or len(self.manifest["manifest_sha256"]) != 64
            or any(
                c not in "0123456789abcdef" for c in self.manifest["manifest_sha256"]
            )
        ):
            raise ValueError("manifest_sha256 must be 64hex")
        rows = observed.get("terminal_rows", [])
        if any(set(r) - TERMINAL_ALLOWED for r in rows):
            raise ValueError("terminal row contains unknown field")
        if (
            len(rows) != 7
            or {r.get("method_id") for r in rows}
            != {"B0", "B1", "B2", "B3", "B4", "B5", "Proposed"}
            or any(
                r.get("terminal_state") != "SEALED" or r.get("panel_closed") is not True
                for r in rows
            )
        ):
            raise ValueError("terminal rows must be the complete SEALED panel")
        for row in rows:
            for field in ("result_sha256", "durable_manifest_sha256"):
                if (
                    not isinstance(row.get(field), str)
                    or len(row[field]) != 64
                    or any(c not in "0123456789abcdef" for c in row[field])
                ):
                    raise ValueError(f"{field} must be 64hex")
        final = telemetry[-1]
        if final.get("gpu_used") is not False or final.get("gpu_not_used") is not True:
            raise ValueError("gpu_not_used requires trusted telemetry")
        transitions = observed.get("capacity_transitions")
        if (
            not isinstance(transitions, list)
            or not transitions
            or transitions != [t for t in telemetry if "capacity_bytes" in t]
        ):
            raise ValueError("capacity transitions must come from lifecycle telemetry")
        body = {
            "schema_version": "c2-sizing-report.v1",
            "classification": "NONCONFIRMATORY_SIZING_ONLY",
            "terminal_state": "SIZING_REPORTED",
            "live_gate_effect": "NONE",
            "regeneration_eligible": False,
            "purge_eligible": False,
            "method_ranking_emitted": False,
            "panel_closed": True,
            "contains_raw_dataset": False,
            "gpu_not_used": True,
            "c2_evidence_state": "SIZING_REPORTED",
            "storage_disposition": "QUARANTINED_NO_DELETE",
            "planning_decision": observed.get(
                "planning_decision", "PENDING_C3_CALCULATION"
            ),
            "manifest_sha256": self.manifest["manifest_sha256"],
            "telemetry": telemetry,
            "terminal_rows": observed.get("terminal_rows", []),
            "capacity_transitions": transitions,
        }
        body["report_sha256"] = sha256_hex(canonical_bytes(body))
        Draft202012Validator(_schema()).validate(body)
        return body


def _schema():
    return json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "contracts"
            / "c2_sizing_report.schema.json"
        ).read_text(encoding="utf-8")
    )


def atomic_write_report(path, report, *, durability_provider=None):
    p = Path(path)
    if p.exists():
        raise FileExistsError("sealed output cannot be overwritten")
    tmp = p.with_name(p.name + ".partial")
    with tmp.open("wb") as fh:
        fh.write(canonical_bytes(report))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)
    try:
        if durability_provider is not None:
            durability_provider.fsync_dir(p.parent)
        else:
            d = os.open(str(p.parent), os.O_RDONLY)
            os.fsync(d)
            os.close(d)
    except OSError as exc:
        raise OSError("report parent directory fsync failed") from exc
    return p
