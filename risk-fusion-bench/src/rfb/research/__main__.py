from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from collections.abc import Sequence

from .controller import (
    guard_mme_controller_entry,
    prepare_legacy_r006,
    execute_remote,
    verify_remote_receipt,
    verify_final_receipt,
    release_stale_lock,
)
from .worker import run_worker
from .files import _fsync_dir
from .preflight import collect_preflight
from rfb.contracts.canonical_json import canonical_bytes, sha256_hex

EXIT = {
    "ok": 0,
    "invalid": 2,
    "adapter": 3,
    "host": 4,
    "lock": 5,
    "execution": 6,
    "receipt": 7,
    "copy": 8,
}


def _add_runtime_binding_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--runtime-file-sha256", required=True)
    parser.add_argument("--runtime-source-sha256", required=True)
    parser.add_argument("--runtime-manifest-sha256", required=True)
    parser.add_argument("--runtime-dependency-profile", required=True)
    parser.add_argument("--runtime-path", required=True)
    parser.add_argument("--pinned-runtime-manifest-sha256")
    parser.add_argument("--pinned-runtime-closure-fingerprint")


def _runtime_binding_from_args(args: argparse.Namespace) -> dict[str, str]:
    binding = {
        "runtime_file_sha256": args.runtime_file_sha256,
        "runtime_source_sha256": args.runtime_source_sha256,
        "runtime_manifest_sha256": args.runtime_manifest_sha256,
        "runtime_dependency_profile": args.runtime_dependency_profile,
        "runtime_path": args.runtime_path,
    }
    if args.pinned_runtime_manifest_sha256 is not None:
        binding["pinned_runtime_manifest_sha256"] = args.pinned_runtime_manifest_sha256
    if args.pinned_runtime_closure_fingerprint is not None:
        binding["pinned_runtime_closure_fingerprint"] = (
            args.pinned_runtime_closure_fingerprint
        )
    if ("pinned_runtime_manifest_sha256" in binding) != (
        "pinned_runtime_closure_fingerprint" in binding
    ):
        raise ValueError("incomplete pinned runtime launch binding")
    return binding


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rfb.research")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--manifest")
    prepare_parser.add_argument("--output")
    prepare_parser.add_argument("--approved-local-root")
    prepare_parser.add_argument("--approved-remote-root")
    prepare_parser.add_argument("--approved-dataset-root")
    prepare_parser.add_argument("--approved-pinned-runtime-root")
    prepare_parser.add_argument("--approved-pinned-runtime-manifest")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--prepared")
    run_parser.add_argument("--approved-local-root")
    run_parser.add_argument("--approved-remote-root")
    run_parser.add_argument("--approved-dataset-root")
    run_parser.add_argument("--approved-pinned-runtime-root")
    run_parser.add_argument("--approved-pinned-runtime-manifest")
    package_parser = subparsers.add_parser("legacy-mme-signing-package")
    package_parser.add_argument("--workspace", required=True)
    package_parser.add_argument("--output")
    mme_parser = subparsers.add_parser("mme-run")
    mme_parser.add_argument("--workspace", required=True)
    mme_parser.add_argument("--config")
    mme_parser.add_argument("--output")
    mme_parser.add_argument("--run-id")
    mme_parser.add_argument(
        "--run-class", choices=("D_impl_unit", "D_development", "MME_v2")
    )
    mme_parser.add_argument("--smoke", action="store_true")
    mme_parser.add_argument("--resume", action="store_true")
    worker_parser = subparsers.add_parser("worker")
    worker_parser.add_argument("--manifest")
    worker_parser.add_argument("--execution-manifest-sha256", required=True)
    worker_parser.add_argument("--trace-prefix", required=True)
    worker_parser.add_argument("--trace-prefix-sha256", required=True)
    _add_runtime_binding_args(worker_parser)
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--root", required=True)
    preflight_parser.add_argument("--manifest-sha256", required=True)
    preflight_parser.add_argument("--controller-nonce", required=True)
    preflight_parser.add_argument("--formal-snapshot-sha256", required=True)
    preflight_parser.add_argument("--dataset-root")
    preflight_parser.add_argument("--fixture-only", action="store_true")
    preflight_parser.add_argument("--filesystem-baseline-bytes", type=int)
    preflight_parser.add_argument("--owned-external-layers-bytes", type=int)
    preflight_parser.add_argument("--trusted-open-deleted-bytes", type=int)
    _add_runtime_binding_args(preflight_parser)
    stage_parser = subparsers.add_parser("stage-seal")
    stage_parser.add_argument("--partial", required=True)
    stage_parser.add_argument("--final", required=True)
    stage_parser.add_argument("--sha256", required=True)
    verify_remote_parser = subparsers.add_parser("verify-remote")
    verify_remote_parser.add_argument("--receipt")
    _add_runtime_binding_args(verify_remote_parser)
    verify_final_parser = subparsers.add_parser("verify-final")
    verify_final_parser.add_argument("--receipt")
    verify_final_parser.add_argument("--local-copy")
    for name in ("unlock", "guarded-unlock"):
        unlock_parser = subparsers.add_parser(name)
        unlock_parser.add_argument("--root")
        unlock_parser.add_argument("--if-dead", action="store_true")
        unlock_parser.add_argument("--run-id")
        unlock_parser.add_argument("--manifest-sha256")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "legacy-mme-signing-package":
            from .mme_authorization import write_offline_signing_package

            paths = write_offline_signing_package(args.workspace, args.output)
            print(
                json.dumps(
                    {key: str(value) for key, value in paths.items()}, sort_keys=True
                )
            )
            return 0
        if args.cmd == "mme-run":
            from .mme_runner import run_mme

            workspace = Path(args.workspace).resolve(strict=True)
            config = {}
            if args.config:
                config_path = Path(args.config).resolve(strict=True)
                if not config_path.is_relative_to(workspace):
                    raise ValueError("MME_CONFIG_PATH_OUTSIDE_WORKSPACE")
                config = json.loads(config_path.read_text(encoding="utf-8"))
                if not isinstance(config, dict):
                    raise ValueError("MME_CONFIG_NOT_OBJECT")
            if (
                "workspace_root" in config
                and Path(config["workspace_root"]).resolve() != workspace
            ):
                raise ValueError("MME_CONFIG_WORKSPACE_MISMATCH")
            config["workspace_root"] = str(workspace)
            config.setdefault("output_root", str(workspace / "outputs" / "mme-v2"))
            config.setdefault("run_class", "MME_v2")
            if args.output:
                config["output_root"] = str(Path(args.output).absolute())
            if args.run_id:
                config["run_id"] = args.run_id
            if args.run_class:
                config["run_class"] = args.run_class
            if args.smoke:
                if args.run_class == "MME_v2":
                    raise ValueError("MME_SMOKE_IS_DEVELOPMENT_ONLY")
                config["run_class"] = "D_development"
                config["block_limit"] = 1
            independent_blocks = config.get("block_limit")
            if independent_blocks is None:
                independent_blocks = len(config.get("block_specs", [])) or 27
            guard_mme_controller_entry(
                workspace,
                operation="LOCAL_MME_V2",
                independent_blocks=independent_blocks,
                dataset_split=config["run_class"],
            )
            result = run_mme(config, resume=args.resume)
            print(json.dumps(result, sort_keys=True, ensure_ascii=False))
            return (
                0 if result.get("terminal_state") == "SUCCEEDED" else EXIT["execution"]
            )
        if args.cmd == "prepare":
            prepare_legacy_r006(
                args.manifest,
                args.output,
                approved_local_root=args.approved_local_root,
                approved_remote_root=args.approved_remote_root,
                approved_dataset_root=args.approved_dataset_root,
                approved_pinned_runtime_root=args.approved_pinned_runtime_root,
                approved_pinned_runtime_manifest=args.approved_pinned_runtime_manifest,
            )
            return 0
        if args.cmd == "worker":
            print(
                json.dumps(
                    run_worker(
                        args.manifest,
                        expected_manifest_sha256=args.execution_manifest_sha256,
                        expected_runtime_binding=_runtime_binding_from_args(args),
                        trace_prefix=args.trace_prefix,
                        trace_prefix_sha256=args.trace_prefix_sha256,
                    ),
                    sort_keys=True,
                )
            )
            return 0
        if args.cmd == "preflight":
            evidence = collect_preflight(
                args.root,
                dataset_root=args.dataset_root,
                fixture_only=args.fixture_only,
                filesystem_baseline_bytes=args.filesystem_baseline_bytes,
                owned_external_layers_bytes=args.owned_external_layers_bytes,
                trusted_open_deleted_bytes=args.trusted_open_deleted_bytes,
            )
            evidence.update(
                {
                    "config_sha256": sha256_hex(
                        canonical_bytes(
                            {"runtime_manifest": args.runtime_manifest_sha256}
                        )
                    ),
                    "input_manifest_sha256": args.manifest_sha256,
                    "prepared_manifest_sha256": args.manifest_sha256,
                    "controller_nonce": args.controller_nonce,
                    "formal_snapshot_sha256": args.formal_snapshot_sha256,
                    "fingerprint_verified": True,
                    **_runtime_binding_from_args(args),
                }
            )
            print(json.dumps(evidence, sort_keys=True))
            return 0
        if args.cmd == "stage-seal":
            partial = Path(args.partial).absolute()
            final = Path(args.final).absolute()
            if partial.parent != final.parent or final.exists() or partial.is_symlink():
                raise ValueError("STAGE_VERIFY_FAILED")
            if hashlib.sha256(partial.read_bytes()).hexdigest() != args.sha256:
                raise ValueError("STAGE_VERIFY_FAILED")
            os.replace(partial, final)
            _fsync_dir(final.parent)
            print(json.dumps({"sealed": str(final), "sha256": args.sha256}))
            return 0
        if args.cmd == "run":
            prepared = prepare_legacy_r006(
                args.prepared,
                approved_local_root=args.approved_local_root,
                approved_remote_root=args.approved_remote_root,
                approved_dataset_root=args.approved_dataset_root,
                approved_pinned_runtime_root=args.approved_pinned_runtime_root,
                approved_pinned_runtime_manifest=args.approved_pinned_runtime_manifest,
            )
            result = execute_remote(prepared)
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.cmd == "verify-remote":
            receipt = verify_remote_receipt(args.receipt)
            binding = _runtime_binding_from_args(args)
            if any(receipt.get(key) != value for key, value in binding.items()):
                raise ValueError("RUNTIME_ARGV_BINDING_MISMATCH")
            print(json.dumps(receipt))
            return 0
        if args.cmd == "verify-final":
            result = verify_final_receipt(args.receipt, local_copy=args.local_copy)
            print(json.dumps(result))
            return 0
        if args.cmd in {"unlock", "guarded-unlock"} and args.if_dead:
            release_stale_lock(
                args.root, run_id=args.run_id, manifest_sha256=args.manifest_sha256
            )
            return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT["invalid"]
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return EXIT["execution"]
    return EXIT["invalid"]


if __name__ == "__main__":
    raise SystemExit(main())
