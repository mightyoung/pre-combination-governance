"""Canonical append-only audit ledger for Stage-2 runtime transactions."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ..contracts.canonical_json import canonical_bytes, canonical_text, sha256_hex


GENESIS_LEDGER_HASH = "0" * 64
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LEDGER_RECORD_TYPES = frozenset(
    {
        "ACCEPTED",
        "SUPERSEDED",
        "ALTERNATE_VIEW_AUDIT",
        "STALE_VERSION_AUDIT",
        "DUPLICATE_AUDIT",
        "EVENT_ID_EQUIVOCATION",
        "HALTED_AUDIT",
        "BUDGET_CAP_AUDIT",
        "FULL_CONFLICT_AUDIT",
        "ROOT_IDENTITY_CONFLICT_AUDIT",
    }
)
_CONTRIBUTION_RECORD_TYPES = frozenset({"ACCEPTED", "SUPERSEDED"})
_AUDIT_CONTRIBUTION_RECORD_TYPES = frozenset(
    {"ALTERNATE_VIEW_AUDIT", "STALE_VERSION_AUDIT"}
)
_DOMAIN_REASON_BY_TYPE = {
    "BUDGET_CAP_AUDIT": "BUDGET_CAP",
    "FULL_CONFLICT_AUDIT": "FULL_CONFLICT",
    "ROOT_IDENTITY_CONFLICT_AUDIT": "ROOT_IDENTITY_CONFLICT",
}
_SUCCESS_DETAIL_KEYS = frozenset(
    {
        "belief_changed",
        "budget_used",
        "charge_applied",
        "contribution_token",
        "processing_charge",
        "processing_spend",
        "scientific_state_changed",
    }
)
_DUPLICATE_DETAIL_KEYS = frozenset(
    {"charge_applied", "reason", "scientific_state_changed"}
)
_EQUIVOCATION_DETAIL_KEYS = frozenset(
    {
        "belief_changed",
        "budget_changed",
        "charge_applied",
        "committed_event_hash",
        "received_event_hash",
        "reason",
        "scientific_state_changed",
    }
)
_DOMAIN_DETAIL_KEYS = frozenset(
    {
        "belief_changed",
        "budget_changed",
        "budget_used",
        "charge_applied",
        "contribution_token",
        "processing_charge",
        "processing_spend",
        "reason",
        "scientific_state_changed",
    }
)


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_hash(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")


def _reject_sensitive_details(value: Any, path: str = "details") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            folded = key.casefold()
            if (
                "truth" in folded
                or "payload" in folded
                or folded == "raw"
                or folded.startswith("raw_")
                or folded.endswith("_raw")
            ):
                raise ValueError(
                    f"sensitive ledger detail field is forbidden: {path}.{key}"
                )
            _reject_sensitive_details(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_sensitive_details(nested, f"{path}[{index}]")


def _require_exact_detail_keys(
    record_type: str,
    details: Mapping[str, Any],
    expected: frozenset[str],
) -> None:
    actual = set(details)
    missing = expected - actual
    if missing:
        raise ValueError(f"details for {record_type} missing fields: {sorted(missing)}")
    extra = actual - expected
    if extra:
        raise ValueError(f"unexpected detail fields for {record_type}: {sorted(extra)}")


def _require_detail_bool(
    details: Mapping[str, Any],
    key: str,
    expected: bool | None = None,
) -> None:
    value = details[key]
    if not isinstance(value, bool):
        raise ValueError(f"ledger detail {key} must be boolean")
    if expected is not None and value is not expected:
        raise ValueError(f"ledger detail {key} must be {expected}")


def _require_detail_number(details: Mapping[str, Any], key: str) -> None:
    value = details[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"ledger detail {key} must be numeric")
    if not math.isfinite(float(value)) or value < 0:
        raise ValueError(f"ledger detail {key} must be finite and non-negative")


def _validate_details(
    record_type: str,
    details: Mapping[str, Any],
    *,
    scientific_state_changed: bool,
) -> None:
    if record_type in _CONTRIBUTION_RECORD_TYPES | _AUDIT_CONTRIBUTION_RECORD_TYPES:
        _require_exact_detail_keys(record_type, details, _SUCCESS_DETAIL_KEYS)
        _require_detail_bool(details, "belief_changed")
        _require_detail_bool(details, "charge_applied", True)
        _require_detail_bool(
            details,
            "scientific_state_changed",
            scientific_state_changed,
        )
        _require_detail_number(details, "budget_used")
        _require_detail_number(details, "processing_charge")
        _require_detail_number(details, "processing_spend")
        token = details["contribution_token"]
        if token is None and record_type in _CONTRIBUTION_RECORD_TYPES:
            raise ValueError(f"details for {record_type} require contribution_token")
        if token is not None:
            _require_hash(token, "contribution_token")
        return
    if record_type == "DUPLICATE_AUDIT":
        _require_exact_detail_keys(record_type, details, _DUPLICATE_DETAIL_KEYS)
        _require_detail_bool(details, "charge_applied", False)
        _require_detail_bool(details, "scientific_state_changed", False)
        if details["reason"] != "EXACT_EVENT_DUPLICATE":
            raise ValueError("details for DUPLICATE_AUDIT have invalid reason")
        return
    if record_type == "HALTED_AUDIT":
        _require_exact_detail_keys(record_type, details, _DUPLICATE_DETAIL_KEYS)
        _require_detail_bool(details, "charge_applied", False)
        _require_detail_bool(details, "scientific_state_changed", False)
        _require_text(details["reason"], "halted reason")
        if details["reason"] not in {
            "EVENT_ID_EQUIVOCATION",
            "RUNTIME_UNAVAILABLE",
        }:
            raise ValueError("details for HALTED_AUDIT have invalid reason")
        return
    if record_type == "EVENT_ID_EQUIVOCATION":
        _require_exact_detail_keys(record_type, details, _EQUIVOCATION_DETAIL_KEYS)
        _require_detail_bool(details, "belief_changed", False)
        _require_detail_bool(details, "budget_changed", False)
        _require_detail_bool(details, "charge_applied", False)
        _require_detail_bool(
            details,
            "scientific_state_changed",
            scientific_state_changed,
        )
        _require_hash(details["committed_event_hash"], "committed_event_hash")
        _require_hash(details["received_event_hash"], "received_event_hash")
        if details["reason"] != "EVENT_ID_EQUIVOCATION":
            raise ValueError("details for EVENT_ID_EQUIVOCATION have invalid reason")
        return
    if record_type in _DOMAIN_REASON_BY_TYPE:
        _require_exact_detail_keys(record_type, details, _DOMAIN_DETAIL_KEYS)
        _require_detail_bool(details, "belief_changed", False)
        _require_detail_bool(details, "budget_changed", False)
        _require_detail_bool(details, "charge_applied", True)
        _require_detail_bool(
            details,
            "scientific_state_changed",
            scientific_state_changed,
        )
        _require_detail_number(details, "budget_used")
        _require_detail_number(details, "processing_charge")
        _require_detail_number(details, "processing_spend")
        if details["contribution_token"] is not None:
            raise ValueError(
                f"details for {record_type} require a null contribution_token"
            )
        if details["reason"] != _DOMAIN_REASON_BY_TYPE[record_type]:
            raise ValueError(f"details for {record_type} have invalid reason")
        return
    raise ValueError(f"invalid record_type {record_type!r}")


@dataclass(frozen=True, slots=True)
class LedgerRecord:
    sequence: int
    record_type: str
    event_id: str
    event_hash: str
    processing_token: str
    before_scientific_hash: str
    after_scientific_hash: str
    details_json: str
    previous_hash: str
    record_hash: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 1
        ):
            raise ValueError("sequence must be a positive integer")
        _require_text(self.record_type, "record_type")
        if self.record_type not in LEDGER_RECORD_TYPES:
            raise ValueError(f"invalid record_type {self.record_type!r}")
        _require_text(self.event_id, "event_id")
        _require_hash(self.event_hash, "event_hash")
        _require_hash(self.processing_token, "processing_token")
        _require_hash(self.before_scientific_hash, "before_scientific_hash")
        _require_hash(self.after_scientific_hash, "after_scientific_hash")
        _require_hash(self.previous_hash, "previous_hash")
        _require_hash(self.record_hash, "record_hash")
        decoded = json.loads(self.details_json)
        if not isinstance(decoded, dict):
            raise ValueError("ledger details must be a JSON object")
        _reject_sensitive_details(decoded)
        if canonical_text(decoded) != self.details_json:
            raise ValueError("ledger details_json must already be canonical")
        _validate_details(
            self.record_type,
            decoded,
            scientific_state_changed=(
                self.before_scientific_hash != self.after_scientific_hash
            ),
        )

    @classmethod
    def build(
        cls,
        *,
        sequence: int,
        record_type: str,
        event_id: str,
        event_hash: str,
        processing_token: str,
        before_scientific_hash: str,
        after_scientific_hash: str,
        details: Mapping[str, Any],
        previous_hash: str,
    ) -> "LedgerRecord":
        details_json = canonical_text(dict(details))
        body = {
            "sequence": sequence,
            "record_type": record_type,
            "event_id": event_id,
            "event_hash": event_hash,
            "processing_token": processing_token,
            "before_scientific_hash": before_scientific_hash,
            "after_scientific_hash": after_scientific_hash,
            "details": json.loads(details_json),
            "previous_hash": previous_hash,
        }
        return cls(
            sequence=sequence,
            record_type=record_type,
            event_id=event_id,
            event_hash=event_hash,
            processing_token=processing_token,
            before_scientific_hash=before_scientific_hash,
            after_scientific_hash=after_scientific_hash,
            details_json=details_json,
            previous_hash=previous_hash,
            record_hash=sha256_hex(canonical_bytes(body)),
        )

    @property
    def details(self) -> Mapping[str, Any]:
        """Return a detached read-only view; callers cannot mutate the record."""

        return MappingProxyType(json.loads(self.details_json))

    def body_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "record_type": self.record_type,
            "event_id": self.event_id,
            "event_hash": self.event_hash,
            "processing_token": self.processing_token,
            "before_scientific_hash": self.before_scientific_hash,
            "after_scientific_hash": self.after_scientific_hash,
            "details": json.loads(self.details_json),
            "previous_hash": self.previous_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body_dict(), "record_hash": self.record_hash}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LedgerRecord":
        return cls(
            sequence=int(value["sequence"]),
            record_type=str(value["record_type"]),
            event_id=str(value["event_id"]),
            event_hash=str(value["event_hash"]),
            processing_token=str(value["processing_token"]),
            before_scientific_hash=str(value["before_scientific_hash"]),
            after_scientific_hash=str(value["after_scientific_hash"]),
            details_json=canonical_text(value["details"]),
            previous_hash=str(value["previous_hash"]),
            record_hash=str(value["record_hash"]),
        )

    def hash_is_valid(self) -> bool:
        return sha256_hex(canonical_bytes(self.body_dict())) == self.record_hash

    def validate(self) -> bool:
        try:
            self.__post_init__()
        except (KeyError, TypeError, ValueError):
            return False
        return self.hash_is_valid()


@dataclass(frozen=True, slots=True)
class AppendOnlyLedger:
    records: tuple[LedgerRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))

    @property
    def head_hash(self) -> str:
        return self.records[-1].record_hash if self.records else GENESIS_LEDGER_HASH

    @property
    def canonical_log_bytes(self) -> bytes:
        return b"\n".join(canonical_bytes(record.to_dict()) for record in self.records)

    def append(
        self,
        *,
        record_type: str,
        event_id: str,
        event_hash: str,
        processing_token: str,
        before_scientific_hash: str,
        after_scientific_hash: str,
        details: Mapping[str, Any],
    ) -> "AppendOnlyLedger":
        record = LedgerRecord.build(
            sequence=len(self.records) + 1,
            record_type=record_type,
            event_id=event_id,
            event_hash=event_hash,
            processing_token=processing_token,
            before_scientific_hash=before_scientific_hash,
            after_scientific_hash=after_scientific_hash,
            details=details,
            previous_hash=self.head_hash,
        )
        return AppendOnlyLedger(self.records + (record,))

    def validate(self) -> bool:
        previous = GENESIS_LEDGER_HASH
        previous_scientific_hash: str | None = None
        for expected_sequence, record in enumerate(self.records, start=1):
            if record.sequence != expected_sequence:
                return False
            if record.previous_hash != previous or not record.validate():
                return False
            if (
                previous_scientific_hash is not None
                and record.before_scientific_hash != previous_scientific_hash
            ):
                return False
            previous = record.record_hash
            previous_scientific_hash = record.after_scientific_hash
        return True

    def to_list(self) -> list[dict[str, Any]]:
        return [record.to_dict() for record in self.records]

    @classmethod
    def from_list(cls, value: Sequence[Mapping[str, Any]]) -> "AppendOnlyLedger":
        return cls(tuple(LedgerRecord.from_dict(item) for item in value))
