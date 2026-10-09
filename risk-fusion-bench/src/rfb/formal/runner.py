"""Formal method runner with subprocess method isolation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ..contracts.canonical_json import canonical_bytes, sha256_hex
from ..methods import METHOD_IDS
from .lifecycle import FormalLifecycle, LifecycleState
from .truth import ScorerBinding, sanitize_observations


@dataclass(frozen=True, slots=True)
class MethodEntry:
    method_id: str
    execute: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None
    scorer: ScorerBinding | None = None


@dataclass(frozen=True, slots=True)
class RunResult:
    transaction_id: str
    rows: Mapping[str, Mapping[str, Any]]
    lifecycle: FormalLifecycle


def _canonical_public_json(value: Mapping[str, Any]) -> str:
    return canonical_bytes(value).decode("utf-8")


class FormalRunner:
    """Run a closed method panel without exposing oracle truth to methods."""

    def __init__(
        self,
        registry: Mapping[str, Any],
        *,
        allow_partial_panel: bool = False,
    ) -> None:
        selected = dict(registry)
        if not allow_partial_panel and tuple(selected) != METHOD_IDS:
            raise ValueError(
                "formal runner requires the closed B0-B5+Proposed panel in canonical order"
            )
        # allow_partial_panel is a development-only escape hatch for isolation
        # tests; every terminal payload records panel_closed so partial panels
        # self-identify in evidence and can never masquerade as formal runs.
        self._registry = selected
        self._allow_partial_panel = allow_partial_panel

    def get_registry(self) -> dict[str, Any]:
        return dict(self._registry)

    def _entry_parts(
        self, method_id: str, entry: Any
    ) -> tuple[
        Callable[[Mapping[str, Any]], Mapping[str, Any]] | None, ScorerBinding | None
    ]:
        if isinstance(entry, MethodEntry):
            return entry.execute, entry.scorer
        execute = getattr(entry, "execute", None)
        scorer = getattr(entry, "scorer", None)
        return execute, scorer

    def _run_method_child(
        self,
        method_id: str,
        observations: Mapping[str, Any],
        execute: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        public_text = _canonical_public_json(observations)
        if method_id in METHOD_IDS:
            if "events" not in observations:
                raise RuntimeError("formal methods require structured public events")
            src_root = str(Path(__file__).parents[2])
            env = {
                "PYTHONPATH": src_root,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
            }
            for key in ("SYSTEMROOT", "WINDIR"):
                if os.environ.get(key):
                    env[key] = os.environ[key]
            with tempfile.TemporaryDirectory(prefix="rfb-method-") as child_cwd:
                proc = subprocess.run(
                    [
                        sys.executable,
                        "-X",
                        "utf8",
                        "-m",
                        "rfb.methods",
                        method_id,
                    ],
                    input=public_text,
                    text=True,
                    capture_output=True,
                    timeout=timeout_seconds,
                    check=False,
                    env=env,
                    cwd=child_cwd,
                )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or f"method {method_id} failed")
            return sanitize_observations(json.loads(proc.stdout))
        if execute is None:
            raise RuntimeError(f"method {method_id} has no executable binding")
        # Non-built-in tests and local fixtures cannot be import-addressed safely;
        # keep the same public immutable JSON boundary before direct invocation.
        return sanitize_observations(dict(execute(json.loads(public_text))))

    def run_all(
        self,
        *,
        transaction_id: str,
        bundle_id: str,
        observations: Mapping[str, Any],
        truth: Any = None,
        seed: int | None = None,
        timeout_seconds: float = 30.0,
    ) -> RunResult:
        if seed is None:
            seed = 0
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        safe_observations = sanitize_observations(observations)
        method_ids = tuple(self._registry)
        expected_rows = tuple((bundle_id, method_id, seed) for method_id in method_ids)
        lifecycle = FormalLifecycle(transaction_id, expected_rows)
        lifecycle.start()
        terminal = LifecycleState.SUCCEEDED
        terminal_payload: dict[str, Any] = {}
        current_method_id: str | None = None
        try:
            for method_id in method_ids:
                current_method_id = method_id
                execute, scorer = self._entry_parts(
                    method_id, self._registry[method_id]
                )
                output = self._run_method_child(
                    method_id, safe_observations, execute, timeout_seconds
                )
                output = sanitize_observations(output)
                metrics = scorer.evaluate(truth, output) if scorer else {}
                row = {
                    "bundle_id": bundle_id,
                    "method_id": method_id,
                    "algorithm_seed": seed,
                    "output": output,
                    "output_sha256": sha256_hex(canonical_bytes(output)),
                    "metrics": sanitize_observations(metrics),
                }
                lifecycle.record_row((bundle_id, method_id, seed), row)
        except subprocess.TimeoutExpired as exc:
            terminal = LifecycleState.TIMEOUT
            terminal_payload = {
                "error": str(exc),
                "failed_method_id": current_method_id,
            }
        except PermissionError as exc:
            terminal = LifecycleState.SKIPPED_POLICY
            terminal_payload = {
                "error": str(exc),
                "failed_method_id": current_method_id,
            }
        except Exception as exc:
            terminal = LifecycleState.FAILED
            terminal_payload = {
                "error": type(exc).__name__,
                "message": str(exc),
                "failed_method_id": current_method_id,
            }
        terminal_payload["panel_closed"] = tuple(self._registry) == METHOD_IDS
        lifecycle.finish(terminal, **terminal_payload)
        lifecycle.seal()
        return RunResult(transaction_id, lifecycle.rows, lifecycle)
