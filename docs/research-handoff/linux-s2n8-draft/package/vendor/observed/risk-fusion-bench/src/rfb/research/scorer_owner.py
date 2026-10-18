"""Scorer-only owner and immutable prediction-seal contract."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rfb.contracts.canonical_json import canonical_bytes, sha256_hex
from rfb.research.isolation import ScorerTruthBundle, build_scorer_truth_bundle


def audit_d_test_namespace(*paths: str | Path) -> bool:
    """Fail closed on D_test namespace variants in any path component."""
    for value in paths:
        for part in Path(value).parts:
            normalized = re.sub(r"[^a-z0-9]", "", part.casefold())
            if "dtest" in normalized:
                raise ValueError("D_TEST_NAMESPACE_FORBIDDEN")
    return False


@dataclass(frozen=True)
class PredictionSealReceipt:
    bundle_id: str
    method_result_sha256: str
    sealed_state: str
    self_hash: str

    def canonical_body(self) -> dict[str, str]:
        return {
            "bundle_id": self.bundle_id,
            "method_result_sha256": self.method_result_sha256,
            "sealed_state": self.sealed_state,
        }

    def to_canonical_payload(self) -> dict[str, str]:
        if sha256_hex(canonical_bytes(self.canonical_body())) != self.self_hash:
            raise ValueError("PREDICTION_SEAL_RECEIPT_INVALID")
        return {**self.canonical_body(), "self_hash": self.self_hash}

    def validate(self, method_result_path: str | Path) -> None:
        if self.sealed_state != "SEALED":
            raise ValueError("PREDICTION_NOT_SEALED")
        if sha256_hex(canonical_bytes(self.canonical_body())) != self.self_hash:
            raise ValueError("PREDICTION_SEAL_RECEIPT_INVALID")
        current = hashlib.sha256(Path(method_result_path).read_bytes()).hexdigest()
        if current != self.method_result_sha256:
            raise ValueError("PREDICTION_RESULT_CHANGED_AFTER_SEAL")


def seal_prediction_result(
    *, bundle_id: str, method_result_path: str | Path
) -> PredictionSealReceipt:
    path = Path(method_result_path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("PREDICTION_RESULT_UNAVAILABLE")
    body = {
        "bundle_id": bundle_id,
        "method_result_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "sealed_state": "SEALED",
    }
    return PredictionSealReceipt(
        **body,
        self_hash=sha256_hex(canonical_bytes(body)),
    )


class ScorerTruthOwner:
    """Own the loader capability used only after prediction sealing."""

    def __init__(self, loader: Any):
        sidecar_reader = getattr(loader, "scorer_only_sidecar", None)
        if not callable(sidecar_reader):
            raise TypeError("SCORER_ONLY_CAPABILITY_UNAVAILABLE")
        self._sidecar_reader = sidecar_reader

    def seal_after_prediction(
        self,
        *,
        prediction_receipt: PredictionSealReceipt,
        method_result_path: str | Path,
        expected_count: int,
    ) -> ScorerTruthBundle:
        prediction_receipt.validate(method_result_path)
        sidecar = self._sidecar_reader()
        if len(sidecar) != expected_count:
            raise ValueError("SCORER_TRUTH_BUNDLE_ALIGNMENT_INVALID")
        return build_scorer_truth_bundle(
            bundle_id=prediction_receipt.bundle_id,
            sidecar=sidecar,
            expected_count=expected_count,
        )


def tep_scorer_owner_from_manifest(manifest: Mapping[str, Any]) -> ScorerTruthOwner:
    """Re-load TEP inside the scorer capability boundary, never the adapter."""
    from rfb.loaders.tep import TEPLoader

    params = dict(manifest.get("adapter_params", {}))
    loader = TEPLoader()
    data_root = manifest.get("dataset_root")
    if data_root:
        loader.load(
            str(Path(data_root).resolve()),
            fault=int(params.get("fault", 0)),
            window=int(params.get("window", 4)),
        )
    else:
        rows = params.get("rows")
        if not rows or len(rows) < 12:
            raise ValueError("TEP_SCORER_DATA_UNAVAILABLE")
        loader.fit_normal(rows)
        loader.from_array(rows, window=int(params.get("window", 4)))
    return ScorerTruthOwner(loader)
