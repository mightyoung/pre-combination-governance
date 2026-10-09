"""Independent specification-state-table implementation for G017 IUT.

Only Python standard-library values are used.  No runtime, method algorithm,
production lifecycle, token, ledger, canonicalization or DST module is imported.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any


def _encode(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")


def _digest(value: Any) -> str:
    return hashlib.sha256(_encode(value)).hexdigest()


def _class_of(table: dict[str, dict[str, Any]], root: str) -> str:
    for key, row in table.items():
        if root in row["members"]:
            return key
    table[root] = {"members": {root}, "canonical": root}
    return root


def _join(
    table: dict[str, dict[str, Any]], roots: Sequence[str], canonical: str | None
) -> None:
    keys = {_class_of(table, root) for root in roots}
    members = set(roots)
    inherited = []
    for key in keys:
        members.update(table[key]["members"])
        inherited.append(str(table[key]["canonical"]))
        del table[key]
    chosen = canonical or min(inherited)
    table[chosen] = {"members": members, "canonical": chosen}


def _materialize(
    classes: dict[str, dict[str, Any]],
    contributions: dict[str, dict[str, Any]],
    retired: set[str],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for root, token in contributions.items():
        if root not in retired:
            grouped.setdefault(_class_of(classes, root), []).append(token)
    output = []
    for canonical in sorted(grouped):
        # Cross-root class choice is lexicographic on version, support and ID;
        # within one root the state table has already retained only max version.
        chosen = max(
            grouped[canonical],
            key=lambda row: (row["version"], row["support"], row["event_id"]),
        )
        output.append(
            {
                "canonical_root": canonical,
                "roots": sorted(classes[canonical]["members"]),
                "lifecycle": "ACTIVE",
                "effective_version": chosen["version"],
                "contribution_count": 1,
                "selected_event_id": chosen["message_id"],
                "contribution_amount": chosen["amount"],
                "support": round(chosen["support"], 12),
            }
        )
    return output


def _scientific(state: Mapping[str, Any]) -> str:
    return _digest(
        {
            "classes": state["audit_classes"],
            "root_lifecycle": state["root_lifecycle"],
            "effective_versions": state["effective_versions"],
            "contribution_budget": state["contribution_budget"],
            "processing_spend": state["processing_spend"],
        }
    )


def evaluate_prefix(
    actions: Sequence[Mapping[str, Any]], *, cap: int, budget: float = 1_000_000.0
) -> dict[str, Any]:
    classes: dict[str, dict[str, Any]] = {}
    contributions: dict[str, dict[str, Any]] = {}
    seen: dict[tuple[str, int], tuple[Any, ...]] = {}
    retired: set[str] = set()
    root_lifecycle: dict[str, str] = {}
    duplicate_count = stale_count = rebuild_count = 0
    processing_spend = 0.0
    status, reason, failure = "RUNNING", None, None
    last_legal: dict[str, Any] | None = None
    before_binding = "0" * 64
    ledger_head = "0" * 64
    final: dict[str, Any] | None = None

    for revision, raw in enumerate(actions, 1):
        row = dict(raw)
        op = str(row["op"]).upper()
        if status != "SAFE_HALT":
            if op in {"SAFE_HALT", "REPLAY_VALIDATION_FAILED"}:
                status = "SAFE_HALT"
                reason = failure = (
                    "REPLAY_VALIDATION_FAILED"
                    if op == "REPLAY_VALIDATION_FAILED"
                    else "EXPLICIT_SAFE_HALT"
                )
            elif op == "INITIALIZE":
                message = str(row["message_id"])
                version = int(row["version"])
                root = str(row["root_id"])
                support = float(row["support"]) * float(row.get("reliability", 1.0))
                signature = (
                    root,
                    support,
                    float(row.get("contribution_amount", 1.0)),
                    float(row.get("processing_cost", 1.0)),
                )
                key = (message, version)
                if key in seen:
                    if seen[key] == signature:
                        duplicate_count += 1
                    else:
                        status = "SAFE_HALT"
                        reason = failure = "EVENT_ID_EQUIVOCATION"
                else:
                    seen[key] = signature
                    processing_spend += float(row.get("processing_cost", 1.0))
                    _class_of(classes, root)
                    root_lifecycle.setdefault(root, "ACTIVE")
                    current = contributions.get(root)
                    token = {
                        "message_id": message,
                        "event_id": f"{message}@{version}",
                        "version": version,
                        "support": support,
                        "amount": float(row.get("contribution_amount", 1.0)),
                    }
                    if current is None:
                        contributions[root] = token
                    elif version > current["version"]:
                        token["amount"] = current["amount"]
                        contributions[root] = token
                    else:
                        stale_count += 1
            elif op in {"EQUIVALENCE", "MERGE"}:
                roots = [str(item) for item in row["roots"]]
                occupied = {
                    _class_of(classes, root)
                    for root in roots
                    if root in contributions and root not in retired
                }
                rebuild_count += int(len(occupied) > 1)
                _join(classes, roots, row.get("canonical_root"))
                canonical = _class_of(
                    classes, str(row.get("canonical_root") or roots[0])
                )
                for root in classes[canonical]["members"]:
                    root_lifecycle[root] = "ACTIVE" if root == canonical else "MERGED"
            elif op == "SUPERSEDE":
                roots = [str(item) for item in row["roots"]]
                replacement = str(row["replacement_root"])
                rebuild_count += int(
                    any(root in contributions and root not in retired for root in roots)
                )
                _join(classes, [*roots, replacement], replacement)
                for root in roots:
                    retired.add(root)
                    root_lifecycle[root] = "SUPERSEDED"
                root_lifecycle[replacement] = "ACTIVE"
            elif op == "RETIRE":
                roots = [str(item) for item in row["roots"]]
                rebuild_count += int(
                    any(root in contributions and root not in retired for root in roots)
                )
                retiring = set(roots)
                for root in roots:
                    key = _class_of(classes, root)
                    retiring.update(classes[key]["members"])
                retired.update(retiring)
                root_lifecycle.update({root: "RETIRED" for root in retiring})

        audit_classes = _materialize(classes, contributions, retired)
        contribution_budget = float(
            sum(item["contribution_amount"] for item in audit_classes)
        )
        if status != "SAFE_HALT" and len(audit_classes) > cap:
            status = "SAFE_HALT"
            reason = failure = "ACTIVE_CONTRIBUTION_CAP"
        if status != "SAFE_HALT" and contribution_budget > budget:
            status = "SAFE_HALT"
            reason = failure = "CONTRIBUTION_BUDGET_CAP"
        current = {
            "authority": "LIFECYCLE_ENGINE",
            "status": status,
            "reason": reason,
            "failure_code": failure,
            "availability": "UNAVAILABLE" if status == "SAFE_HALT" else "AVAILABLE",
            "gate": "CLOSED" if status == "SAFE_HALT" else "OPEN",
            "action": "FAIL_CLOSED" if status == "SAFE_HALT" else op,
            "replay_current": op == "REPLAY",
            "risk_score": None
            if status == "SAFE_HALT"
            else round(
                1.0 - math.prod(1.0 - item["support"] for item in audit_classes), 12
            ),
            "contribution_budget": contribution_budget,
            "processing_spend": processing_spend,
            "duplicate_count": duplicate_count,
            "stale_count": stale_count,
            "eliminated_count": max(0, len(contributions) - len(audit_classes)),
            "rebuild_count": rebuild_count,
            "root_lifecycle": [list(item) for item in sorted(root_lifecycle.items())],
            "effective_versions": [
                [item["canonical_root"], item["effective_version"]]
                for item in audit_classes
                if item["effective_version"] is not None
            ],
            "audit_effective_versions": [
                list(item)
                for item in sorted(
                    (root, token["version"]) for root, token in contributions.items()
                )
            ],
            "audit_classes": audit_classes,
            "classes": [] if status == "SAFE_HALT" else audit_classes,
        }
        if status == "SAFE_HALT" and last_legal is not None:
            for key in (
                "contribution_budget",
                "root_lifecycle",
                "effective_versions",
                "audit_effective_versions",
                "audit_classes",
            ):
                current[key] = last_legal[key]
            current["classes"] = []
        after_binding = _scientific(current)
        body = {
            "revision": revision,
            "action_id": str(row["action_id"]),
            "op": op,
            "before_scientific_binding": before_binding,
            "after_scientific_binding": after_binding,
            "previous_hash": ledger_head,
        }
        ledger_head = _digest(body)
        current["scientific_binding"] = after_binding
        current["ledger_head"] = ledger_head
        before_binding = after_binding
        final = current
        if status != "SAFE_HALT":
            last_legal = current

    if final is None:
        raise ValueError("reference prefix must be non-empty")
    return final


__all__ = ["evaluate_prefix"]
