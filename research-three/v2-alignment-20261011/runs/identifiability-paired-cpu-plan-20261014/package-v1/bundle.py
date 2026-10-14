"""Write and verify frozen method-output bundles without opening the oracle."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


PLANNED_METHOD_INVOCATIONS = 80
EXPECTED_METHOD_ORDER = ("M0", "M1", "M2", "M3")


class BundleError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedBundle:
    attempt: dict
    freeze: dict
    slots: tuple[dict, ...]


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()


def _validate_attempt(attempt: dict, slots: list[dict]) -> None:
    if attempt.get("task_id") != "PCG-IDENTIFIABILITY-PAIRED-CPU-001":
        raise BundleError("attempt task ID differs from the frozen plan")
    if attempt.get("attempt_count") != 1:
        raise BundleError("run ID must have exactly one attempt")
    run_id = attempt.get("run_id")
    if (not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", run_id)
            or ".." in run_id):
        raise BundleError("attempt run ID is invalid")
    if attempt.get("planned_method_invocations") != PLANNED_METHOD_INVOCATIONS:
        raise BundleError("planned slot count must remain 80")
    if attempt.get("method_order") != list(EXPECTED_METHOD_ORDER):
        raise BundleError("method order must remain M0-M3")
    case_ids = attempt.get("case_ids")
    if (not isinstance(case_ids, list) or len(case_ids) != 4
            or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value)
                   for value in case_ids)
            or len(set(case_ids)) != 4):
        raise BundleError("bundle must bind four unique opaque case IDs")

    start_requests = attempt.get("method_start_requests")
    started = attempt.get("method_invocations_started")
    completed = attempt.get("completed_method_invocations")
    if (isinstance(start_requests, bool) or not isinstance(start_requests, int)
            or not 0 <= start_requests <= PLANNED_METHOD_INVOCATIONS):
        raise BundleError("method start request count must be an actual integer from 0 to 80")
    if (isinstance(started, bool) or not isinstance(started, int)
            or not 0 <= started <= start_requests):
        raise BundleError("started slot count must be an actual integer from 0 to 80")
    if (isinstance(completed, bool) or not isinstance(completed, int)
            or not 0 <= completed <= started):
        raise BundleError("completed slot count must not exceed actual starts")
    if completed != len(slots):
        raise BundleError("completed slot count does not match preserved output rows")

    status = attempt.get("task_status")
    acceptance = attempt.get("research_acceptance")
    if status == "PASS":
        if (start_requests != PLANNED_METHOD_INVOCATIONS
                or started != PLANNED_METHOD_INVOCATIONS
                or completed != PLANNED_METHOD_INVOCATIONS
                or attempt.get("partial") is not False
                or attempt.get("stop_reason") is not None):
            raise BundleError("PASS requires all 80 planned slots and a complete bundle")
        if acceptance != "NOT_EVALUATED":
            raise BundleError("execution receipt must leave research acceptance NOT_EVALUATED")
    elif status in ("FAIL", "BLOCKED"):
        if acceptance != "NOT_EVALUATED":
            raise BundleError("interrupted execution must be NOT_EVALUATED")
        if (attempt.get("partial") is not True
                or not isinstance(attempt.get("stop_reason"), str)
                or not attempt.get("stop_reason")):
            raise BundleError("FAIL/BLOCKED must preserve a partial state and stop reason")
        expected_exit = 20 if status == "BLOCKED" else 30
        if attempt.get("terminal_exit_code") != expected_exit:
            raise BundleError("interrupted execution must preserve its blocked/failed terminal exit")
    else:
        raise BundleError("task_status must be PASS, FAIL, or BLOCKED")
    if status == "PASS" and attempt.get("terminal_exit_code") != 0:
        raise BundleError("PASS must preserve a zero terminal exit code")

    seen = set()
    for slot in slots:
        key = (slot.get("case_id"), slot.get("prefix"), slot.get("method"))
        if key in seen:
            raise BundleError("duplicate case/prefix/method slot")
        seen.add(key)
        if key[0] not in case_ids or key[2] not in EXPECTED_METHOD_ORDER:
            raise BundleError("output slot uses an unregistered case or method")
        if isinstance(key[1], bool) or key[1] not in (1, 2, 3, 4, 5):
            raise BundleError("output slot prefix must be 1 through 5")
        for hash_name in ("input_sha256", "output_sha256"):
            value = slot.get(hash_name)
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise BundleError("slot is missing a SHA-256 field: " + hash_name)
    planned_order = [
        (case_id, prefix, method)
        for case_id in case_ids
        for prefix in (1, 2, 3, 4, 5)
        for method in EXPECTED_METHOD_ORDER
    ]
    actual_order = [
        (slot.get("case_id"), slot.get("prefix"), slot.get("method"))
        for slot in slots
    ]
    if actual_order != planned_order[:len(actual_order)]:
        raise BundleError("slot output rows must preserve the frozen sequential plan order")
    if status == "PASS":
        expected = {
            (case_id, prefix, method)
            for case_id in case_ids
            for prefix in (1, 2, 3, 4, 5)
            for method in EXPECTED_METHOD_ORDER
        }
        if seen != expected or len(slots) != len(expected):
            raise BundleError("PASS requires exactly all 80 planned slots")


def freeze_bundle(bundle_dir, slots: list[dict], attempt: dict) -> dict:
    """Freeze outputs first, then write a receipt that binds the freeze hash."""
    root = Path(bundle_dir)
    if not root.is_dir():
        raise BundleError("attempt directory must already be exclusively reserved")
    _validate_attempt(attempt, slots)
    filename = "slots.jsonl" if attempt["task_status"] == "PASS" else "slots.partial.jsonl"
    payload = b"".join(canonical_bytes(row) + b"\n" for row in slots)
    output_path = root / filename
    if output_path.exists():
        if output_path.read_bytes() != payload:
            raise BundleError("prewritten slot output differs; refusing to overwrite")
    else:
        _write_exclusive(output_path, payload)
    freeze = {
        "schema_version": 1,
        "file": filename,
        "bytes": len(payload),
        "sha256": sha256_bytes(payload),
        "rows": len(slots),
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    freeze_bytes = canonical_bytes(freeze) + b"\n"
    _write_exclusive(root / "OUTPUT_FREEZE.json", freeze_bytes)
    receipt = dict(attempt)
    receipt["output_file"] = filename
    receipt["output_sha256"] = freeze["sha256"]
    receipt["output_freeze_sha256"] = sha256_bytes(freeze_bytes)
    receipt_bytes = canonical_bytes(receipt) + b"\n"
    _write_exclusive(root / "attempt.json", receipt_bytes)
    return receipt


def verify_frozen_bundle(bundle_dir, require_complete=False) -> VerifiedBundle:
    root = Path(bundle_dir)
    attempt_path = root / "attempt.json"
    freeze_path = root / "OUTPUT_FREEZE.json"
    if not freeze_path.is_file() or not attempt_path.is_file():
        raise BundleError("output freeze or attempt receipt is missing")
    try:
        attempt_bytes = attempt_path.read_bytes()
        freeze_bytes = freeze_path.read_bytes()
        attempt = json.loads(attempt_bytes)
        freeze = json.loads(freeze_bytes)
    except (OSError, json.JSONDecodeError) as error:
        raise BundleError("output freeze or attempt receipt is unreadable") from error
    if sha256_bytes(freeze_bytes) != attempt.get("output_freeze_sha256"):
        raise BundleError("output freeze receipt hash mismatch")
    filename = freeze.get("file")
    if filename not in ("slots.jsonl", "slots.partial.jsonl"):
        raise BundleError("output freeze names an unsupported artifact")
    try:
        output_bytes = (root / filename).read_bytes()
    except OSError as error:
        raise BundleError("frozen output artifact is missing") from error
    if (len(output_bytes) != freeze.get("bytes")
            or sha256_bytes(output_bytes) != freeze.get("sha256")
            or attempt.get("output_sha256") != freeze.get("sha256")):
        raise BundleError("frozen output bytes or SHA-256 mismatch")
    slots = []
    try:
        for line in output_bytes.splitlines():
            if line:
                slots.append(json.loads(line))
    except json.JSONDecodeError as error:
        raise BundleError("frozen slot output is invalid JSONL") from error
    if freeze.get("rows") != len(slots):
        raise BundleError("frozen slot row count mismatch")
    _validate_attempt(attempt, slots)
    if require_complete and attempt["task_status"] != "PASS":
        raise BundleError("only an execution PASS bundle can be scored")
    return VerifiedBundle(attempt, freeze, tuple(slots))
