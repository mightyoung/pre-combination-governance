"""Closed formal transaction lifecycle with row-hash replay."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from ..contracts.canonical_json import canonical_bytes, sha256_hex


class LifecycleError(RuntimeError):
    """The formal transaction lifecycle has been violated."""


class LifecycleState(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    SKIPPED_POLICY = "SKIPPED_POLICY"
    SEALED = "SEALED"


TERMINALS = frozenset(
    {
        LifecycleState.SUCCEEDED,
        LifecycleState.FAILED,
        LifecycleState.TIMEOUT,
        LifecycleState.SKIPPED_POLICY,
    }
)


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    sequence: int
    state: LifecycleState
    transaction_id: str
    payload: Mapping[str, Any]
    previous_hash: str
    event_hash: str

    @classmethod
    def build(
        cls,
        sequence: int,
        state: LifecycleState,
        transaction_id: str,
        payload: Mapping[str, Any],
        previous_hash: str,
    ) -> "LifecycleEvent":
        stable_payload = _freeze_json(payload)
        body = {
            "sequence": sequence,
            "state": state.value,
            "transaction_id": transaction_id,
            "payload": stable_payload,
            "previous_hash": previous_hash,
        }
        return cls(
            sequence=sequence,
            state=state,
            transaction_id=transaction_id,
            payload=stable_payload,
            previous_hash=previous_hash,
            event_hash=sha256_hex(canonical_bytes(body)),
        )

    def body(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "state": self.state.value,
            "transaction_id": self.transaction_id,
            "payload": _thaw_json(self.payload),
            "previous_hash": self.previous_hash,
        }


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(child) for key, child in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(child) for child in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(child) for child in value]
    return value


def _row_key(row_id: Any) -> str:
    if isinstance(row_id, tuple):
        return "|".join(str(part) for part in row_id)
    return str(row_id)


class FormalLifecycle:
    """Formal PLANNED -> RUNNING -> terminal -> SEALED lifecycle.

    Output rows are hash-chain events, not side data. Successful seal requires
    the exact expected row set: no missing rows and no unexpected rows.
    """

    def __init__(self, transaction_id: str, expected_rows: Iterable[Any] = ()) -> None:
        if not transaction_id:
            raise ValueError("transaction_id required")
        self.transaction_id = transaction_id
        self.expected_rows = frozenset(_row_key(row) for row in expected_rows)
        self._events: list[LifecycleEvent] = []
        self._rows: dict[str, Mapping[str, Any]] = {}

    @property
    def state(self) -> LifecycleState:
        return self._events[-1].state if self._events else LifecycleState.PLANNED

    @property
    def head_hash(self) -> str:
        return self._events[-1].event_hash if self._events else "0" * 64

    @property
    def events(self) -> tuple[LifecycleEvent, ...]:
        return tuple(self._events)

    @property
    def rows(self) -> dict[str, dict[str, Any]]:
        return {key: _thaw_json(value) for key, value in self._rows.items()}

    def _append(
        self, state: LifecycleState, payload: Mapping[str, Any] | None = None
    ) -> LifecycleEvent:
        allowed = {
            LifecycleState.PLANNED: {LifecycleState.RUNNING},
            LifecycleState.RUNNING: TERMINALS | {LifecycleState.RUNNING},
            **{terminal: {LifecycleState.SEALED} for terminal in TERMINALS},
            LifecycleState.SEALED: frozenset(),
        }
        if state not in allowed[self.state]:
            raise LifecycleError(
                f"illegal transition {self.state.value}->{state.value}"
            )
        event = LifecycleEvent.build(
            len(self._events) + 1,
            state,
            self.transaction_id,
            payload or {},
            self.head_hash,
        )
        self._events.append(event)
        return event

    def start(self) -> "FormalLifecycle":
        self._append(LifecycleState.RUNNING, {"event": "start"})
        return self

    def record_row(self, row_id: Any, output: Mapping[str, Any]) -> bool:
        if self.state is not LifecycleState.RUNNING:
            raise LifecycleError("rows require RUNNING")
        key = _row_key(row_id)
        value = _freeze_json(output)
        if key in self._rows:
            if self._rows[key] == value:
                return False
            raise LifecycleError("duplicate row with different output")
        self._rows[key] = value
        self._append(
            LifecycleState.RUNNING,
            {
                "event": "row_recorded",
                "row_id": key,
                "row_sha256": sha256_hex(canonical_bytes(_thaw_json(value))),
            },
        )
        return True

    def finish(self, state: LifecycleState, **payload: Any) -> "FormalLifecycle":
        if state not in TERMINALS:
            raise ValueError("finish requires terminal state")
        self._append(state, payload)
        return self

    def seal(self) -> "FormalLifecycle":
        if self.state not in TERMINALS:
            raise LifecycleError("cannot seal before terminal state")
        actual = frozenset(self._rows)
        missing = sorted(self.expected_rows - actual)
        unexpected = sorted(actual - self.expected_rows)
        if self.state is LifecycleState.SUCCEEDED and (missing or unexpected):
            raise LifecycleError(
                f"missing expected rows: {missing}; unexpected rows: {unexpected}"
            )
        self._append(
            LifecycleState.SEALED,
            {
                "row_count": len(self._rows),
                "row_set_sha256": sha256_hex(canonical_bytes(sorted(self._rows))),
            },
        )
        return self

    def validate(self) -> bool:
        previous = "0" * 64
        for index, event in enumerate(self._events, 1):
            if event.sequence != index or event.previous_hash != previous:
                return False
            if event.transaction_id != self.transaction_id:
                return False
            if event.event_hash != sha256_hex(canonical_bytes(event.body())):
                return False
            previous = event.event_hash
        return True

    @classmethod
    def replay(
        cls,
        transaction_id: str,
        events: Iterable[LifecycleEvent],
        expected_rows: Iterable[Any] = (),
    ) -> "FormalLifecycle":
        obj = cls(transaction_id, expected_rows)
        previous = "0" * 64
        terminal_seen = False
        for index, event in enumerate(events, 1):
            if event.sequence != index or event.previous_hash != previous:
                raise LifecycleError("invalid replay order")
            if event.transaction_id != transaction_id:
                raise LifecycleError("invalid replay transaction")
            if event.event_hash != sha256_hex(canonical_bytes(event.body())):
                raise LifecycleError("invalid replay event")
            if event.state is LifecycleState.RUNNING:
                if (
                    obj.state not in {LifecycleState.PLANNED, LifecycleState.RUNNING}
                    or terminal_seen
                ):
                    raise LifecycleError("invalid replay state transition")
            elif event.state in TERMINALS:
                if obj.state is not LifecycleState.RUNNING or terminal_seen:
                    raise LifecycleError("invalid replay terminal transition")
                terminal_seen = True
            elif event.state is LifecycleState.SEALED:
                if not terminal_seen or obj.state not in TERMINALS:
                    raise LifecycleError("invalid replay seal transition")
                payload_count = event.payload.get("row_count")
                if payload_count != len(obj._rows):
                    raise LifecycleError("invalid replay row count")
                actual = frozenset(obj._rows)
                if obj.expected_rows and actual != obj.expected_rows:
                    raise LifecycleError("invalid replay row set")
            else:
                raise LifecycleError("invalid replay state")
            obj._events.append(event)
            payload = event.payload
            if (
                event.state is LifecycleState.RUNNING
                and payload.get("event") == "row_recorded"
            ):
                row_id = str(payload["row_id"])
                if row_id in obj._rows:
                    raise LifecycleError("duplicate replay row")
                obj._rows[row_id] = MappingProxyType(
                    {"row_sha256": str(payload["row_sha256"])}
                )
            previous = event.event_hash
        if obj.state is not LifecycleState.SEALED:
            raise LifecycleError("replay did not reach SEALED")
        return obj
