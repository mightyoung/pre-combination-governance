"""Immutable scientific state for the Stage-2 transaction kernel.

This module deliberately does not mutate :mod:`rfb.temporal`.  The older
canary stays available through an explicit non-formal adapter while the shared
runtime uses closed, canonical value objects and immutable aggregate states.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .. import dst
from ..contracts.canonical_json import canonical_bytes, sha256_hex


MassTuple = tuple[tuple[int, float], ...]
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GATE_STATUSES = frozenset({"OPEN", "CLOSED"})
_ACTION_STATUSES = frozenset(
    {
        "IDLE",
        "ACCEPT_CONTRIBUTION",
        "SUPERSEDE_CONTRIBUTION",
        "AUDIT_ONLY",
        "FAIL_CLOSED",
    }
)
_AVAILABILITY_STATUSES = frozenset({"AVAILABLE", "UNAVAILABLE"})


def _nonempty_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise ValueError(f"{field_name} contains a lone surrogate")
    return value


def _finite_nonnegative(value: float | int, field_name: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    if not math.isfinite(float(value)) or value < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return value


def _sha256_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")
    return value


def freeze_mass(value: Mapping[int, float] | Iterable[tuple[int, float]]) -> MassTuple:
    """Return a sorted, normalized and deeply immutable BPA."""

    items = value.items() if isinstance(value, Mapping) else value
    combined: dict[int, float] = {}
    for focal_set, amount in items:
        if (
            isinstance(focal_set, bool)
            or not isinstance(focal_set, int)
            or focal_set <= 0
        ):
            raise ValueError("mass focal sets must be positive integer bit masks")
        _finite_nonnegative(amount, "mass amount")
        combined[focal_set] = combined.get(focal_set, 0.0) + float(amount)
    combined = {key: amount for key, amount in combined.items() if amount > 1e-12}
    total = sum(combined.values())
    if total <= 0:
        combined = dst.vacuous()
        total = 1.0
    return tuple((key, amount / total) for key, amount in sorted(combined.items()))


def mass_dict(value: MassTuple) -> dict[int, float]:
    """Return a fresh mutable view of an immutable BPA."""

    return {key: amount for key, amount in value}


def _mass_is_close(left: MassTuple, right: MassTuple) -> bool:
    if tuple(key for key, _ in left) != tuple(key for key, _ in right):
        return False
    return all(
        math.isclose(left_amount, right_amount, rel_tol=0.0, abs_tol=1e-12)
        for (_, left_amount), (_, right_amount) in zip(left, right)
    )


def _mass_json(value: MassTuple) -> list[dict[str, int | float]]:
    return [{"focal_set": key, "mass": amount} for key, amount in value]


def _mass_from_json(value: Sequence[Mapping[str, Any]]) -> MassTuple:
    return freeze_mass((int(item["focal_set"]), float(item["mass"])) for item in value)


def resource_token_for(identity: str, resource_type: str) -> str:
    """Return ``H(identity, resource_type)`` using the repository canonical JSON."""

    _nonempty_text(identity, "identity")
    _nonempty_text(resource_type, "resource_type")
    return sha256_hex(canonical_bytes([identity, resource_type]))


def processing_token_for(event_id: str) -> str:
    """Processing tokens are independently keyed from belief contributions."""

    return resource_token_for(event_id, "PROCESSING")


def contribution_token_for(root_id: str) -> str:
    return resource_token_for(root_id, "CONTRIBUTION")


def charge_id_for(processing_token: str) -> str:
    return resource_token_for(processing_token, "CHARGE")


@dataclass(frozen=True, slots=True)
class Root:
    root_id: str
    root_type: str = "GENERIC"

    def __post_init__(self) -> None:
        _nonempty_text(self.root_id, "root_id")
        _nonempty_text(self.root_type, "root_type")

    def to_dict(self) -> dict[str, str]:
        return {"root_id": self.root_id, "root_type": self.root_type}


@dataclass(frozen=True, slots=True)
class Version:
    bundle_version: int
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if (
            isinstance(self.bundle_version, bool)
            or not isinstance(self.bundle_version, int)
            or self.bundle_version < 0
        ):
            raise ValueError("bundle_version must be a non-negative integer")
        _nonempty_text(self.schema_version, "schema_version")

    def to_dict(self) -> dict[str, int | str]:
        return {
            "bundle_version": self.bundle_version,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class Event:
    event_id: str
    root: Root
    version: Version
    mass: MassTuple
    occurred_at: float = 0.0
    view_id: str = "PRIMARY"
    processing_cost: float | int = 1
    contribution_amount: float = 1.0

    def __post_init__(self) -> None:
        _nonempty_text(self.event_id, "event_id")
        if not isinstance(self.root, Root):
            raise ValueError("root must be a Root")
        if not isinstance(self.version, Version):
            raise ValueError("version must be a Version")
        object.__setattr__(self, "mass", freeze_mass(self.mass))
        if not math.isfinite(float(self.occurred_at)):
            raise ValueError("occurred_at must be finite")
        _nonempty_text(self.view_id, "view_id")
        _finite_nonnegative(self.processing_cost, "processing_cost")
        _finite_nonnegative(self.contribution_amount, "contribution_amount")

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        root: Root,
        version: Version,
        mass: Mapping[int, float] | Iterable[tuple[int, float]],
        occurred_at: float = 0.0,
        view_id: str = "PRIMARY",
        processing_cost: float | int = 1,
        contribution_amount: float = 1.0,
    ) -> "Event":
        return cls(
            event_id=event_id,
            root=root,
            version=version,
            mass=freeze_mass(mass),
            occurred_at=occurred_at,
            view_id=view_id,
            processing_cost=processing_cost,
            contribution_amount=contribution_amount,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "root": self.root.to_dict(),
            "version": self.version.to_dict(),
            "mass": _mass_json(self.mass),
            "occurred_at": self.occurred_at,
            "view_id": self.view_id,
            "processing_cost": self.processing_cost,
            "contribution_amount": self.contribution_amount,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Event":
        root = value["root"]
        version = value["version"]
        return cls(
            event_id=str(value["event_id"]),
            root=Root(str(root["root_id"]), str(root["root_type"])),
            version=Version(
                int(version["bundle_version"]), str(version["schema_version"])
            ),
            mass=_mass_from_json(value["mass"]),
            occurred_at=float(value["occurred_at"]),
            view_id=str(value["view_id"]),
            processing_cost=value["processing_cost"],
            contribution_amount=float(value["contribution_amount"]),
        )

    @property
    def event_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.to_dict()))


@dataclass(frozen=True, slots=True)
class ContributionToken:
    token_id: str
    root_id: str
    first_event_id: str
    effective_event_id: str
    bundle_version: int
    amount: float
    mass: MassTuple

    def __post_init__(self) -> None:
        _sha256_text(self.token_id, "token_id")
        _nonempty_text(self.root_id, "root_id")
        _nonempty_text(self.first_event_id, "first_event_id")
        _nonempty_text(self.effective_event_id, "effective_event_id")
        if isinstance(self.bundle_version, bool) or not isinstance(
            self.bundle_version, int
        ):
            raise ValueError("bundle_version must be an integer")
        if self.bundle_version < 0:
            raise ValueError("bundle_version must be non-negative")
        _finite_nonnegative(self.amount, "amount")
        object.__setattr__(self, "mass", freeze_mass(self.mass))

    def to_dict(self) -> dict[str, Any]:
        return {
            "token_id": self.token_id,
            "root_id": self.root_id,
            "first_event_id": self.first_event_id,
            "effective_event_id": self.effective_event_id,
            "bundle_version": self.bundle_version,
            "amount": self.amount,
            "mass": _mass_json(self.mass),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContributionToken":
        return cls(
            token_id=str(value["token_id"]),
            root_id=str(value["root_id"]),
            first_event_id=str(value["first_event_id"]),
            effective_event_id=str(value["effective_event_id"]),
            bundle_version=int(value["bundle_version"]),
            amount=float(value["amount"]),
            mass=_mass_from_json(value["mass"]),
        )


@dataclass(frozen=True, slots=True)
class ChargeFact:
    charge_id: str
    processing_token: str
    event_id: str
    resource_type: str
    amount: float | int

    def __post_init__(self) -> None:
        _sha256_text(self.charge_id, "charge_id")
        _sha256_text(self.processing_token, "processing_token")
        _nonempty_text(self.event_id, "event_id")
        _nonempty_text(self.resource_type, "resource_type")
        _finite_nonnegative(self.amount, "amount")

    def to_dict(self) -> dict[str, Any]:
        return {
            "charge_id": self.charge_id,
            "processing_token": self.processing_token,
            "event_id": self.event_id,
            "resource_type": self.resource_type,
            "amount": self.amount,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ChargeFact":
        return cls(
            charge_id=str(value["charge_id"]),
            processing_token=str(value["processing_token"]),
            event_id=str(value["event_id"]),
            resource_type=str(value["resource_type"]),
            amount=value["amount"],
        )


@dataclass(frozen=True, slots=True)
class GateState:
    status: str = "OPEN"
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in _GATE_STATUSES:
            raise ValueError(f"invalid gate status {self.status!r}")
        if self.reason is not None:
            _nonempty_text(self.reason, "gate reason")

    def to_dict(self) -> dict[str, str | None]:
        return {"status": self.status, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class ActionState:
    status: str = "IDLE"
    event_id: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in _ACTION_STATUSES:
            raise ValueError(f"invalid action status {self.status!r}")
        if self.event_id is not None:
            _nonempty_text(self.event_id, "action event_id")
        if self.reason is not None:
            _nonempty_text(self.reason, "action reason")

    def to_dict(self) -> dict[str, str | None]:
        return {"status": self.status, "event_id": self.event_id, "reason": self.reason}


def combine_contributions(tokens: Iterable[ContributionToken]) -> MassTuple:
    belief = dst.vacuous()
    for token in sorted(tokens, key=lambda item: (item.root_id, item.token_id)):
        belief = dst.dempster_combine(belief, mass_dict(token.mass))
    return freeze_mass(belief)


def _assert_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)


@dataclass(frozen=True, slots=True)
class RuntimeState:
    belief: MassTuple = ((dst.THETA, 1.0),)
    roots: tuple[Root, ...] = ()
    versions: tuple[tuple[str, Version], ...] = ()
    contribution_tokens: tuple[ContributionToken, ...] = ()
    charge_facts: tuple[ChargeFact, ...] = ()
    event_hashes: tuple[tuple[str, str], ...] = ()
    processing_tokens: tuple[str, ...] = ()
    budget_total: float | int = 1_000_000
    budget_used: float | int = 0
    availability: str = "AVAILABLE"
    gate: GateState = GateState()
    action: ActionState = ActionState()

    def __post_init__(self) -> None:
        object.__setattr__(self, "belief", freeze_mass(self.belief))
        roots = tuple(sorted(self.roots, key=lambda item: item.root_id))
        _assert_unique((item.root_id for item in roots), "root_id")
        object.__setattr__(self, "roots", roots)

        versions = tuple(sorted(self.versions, key=lambda item: item[0]))
        _assert_unique((root_id for root_id, _ in versions), "version root_id")
        for root_id, version in versions:
            _nonempty_text(root_id, "version root_id")
            if not isinstance(version, Version):
                raise ValueError("versions must contain Version values")
        object.__setattr__(self, "versions", versions)

        tokens = tuple(sorted(self.contribution_tokens, key=lambda item: item.token_id))
        _assert_unique((item.token_id for item in tokens), "contribution token_id")
        _assert_unique((item.root_id for item in tokens), "contribution root_id")
        object.__setattr__(self, "contribution_tokens", tokens)

        charges = tuple(sorted(self.charge_facts, key=lambda item: item.charge_id))
        _assert_unique((item.charge_id for item in charges), "charge_id")
        _assert_unique(
            (item.processing_token for item in charges), "charge processing_token"
        )
        object.__setattr__(self, "charge_facts", charges)

        event_hashes = tuple(sorted(self.event_hashes, key=lambda item: item[0]))
        _assert_unique((event_id for event_id, _ in event_hashes), "event_id")
        for event_id, digest in event_hashes:
            _nonempty_text(event_id, "event_id")
            _sha256_text(digest, "event hash")
        object.__setattr__(self, "event_hashes", event_hashes)

        processing_tokens = tuple(sorted(self.processing_tokens))
        _assert_unique(processing_tokens, "processing token")
        for processing_token in processing_tokens:
            _sha256_text(processing_token, "processing token")
        object.__setattr__(self, "processing_tokens", processing_tokens)

        _finite_nonnegative(self.budget_total, "budget_total")
        _finite_nonnegative(self.budget_used, "budget_used")
        committed = sum(item.amount for item in tokens)
        if not math.isclose(
            float(committed), float(self.budget_used), rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError(
                "budget_used must equal the immutable contribution commitments"
            )
        if committed > self.budget_total:
            raise ValueError("budget_used cannot exceed budget_total")
        object.__setattr__(self, "budget_used", committed)
        if {item.processing_token for item in charges} != set(processing_tokens):
            raise ValueError("processing tokens must match immutable charge facts")

        root_ids = {item.root_id for item in roots}
        version_by_root = dict(versions)
        if set(version_by_root) != root_ids:
            raise ValueError("versions must contain exactly one entry per root")
        if not {item.root_id for item in tokens}.issubset(root_ids):
            raise ValueError("contribution token references an unknown root")
        event_ids = {event_id for event_id, _ in event_hashes}
        for token in tokens:
            if token.token_id != contribution_token_for(token.root_id):
                raise ValueError("contribution token_id is not derived from root_id")
            if token.bundle_version != version_by_root[token.root_id].bundle_version:
                raise ValueError(
                    "contribution token bundle_version does not match root version"
                )
            if (
                token.first_event_id not in event_ids
                or token.effective_event_id not in event_ids
            ):
                raise ValueError("contribution token references an unknown event")
        expected_belief = combine_contributions(tokens)
        if not _mass_is_close(self.belief, expected_belief):
            raise ValueError("belief must equal the recombined contribution tokens")
        object.__setattr__(self, "belief", expected_belief)
        for charge in charges:
            if charge.resource_type != "PROCESSING":
                raise ValueError("charge resource_type must be PROCESSING")
            if charge.processing_token != processing_token_for(charge.event_id):
                raise ValueError("charge processing_token is not derived from event_id")
            if charge.charge_id != charge_id_for(charge.processing_token):
                raise ValueError("charge_id is not derived from processing_token")
            if charge.event_id not in event_ids:
                raise ValueError("charge fact references an unknown event")
        if {charge.event_id for charge in charges} != event_ids:
            raise ValueError("event hashes must match immutable charge facts")
        if self.availability not in _AVAILABILITY_STATUSES:
            raise ValueError(f"invalid availability {self.availability!r}")
        if not isinstance(self.gate, GateState):
            raise ValueError("gate must be a GateState")
        if not isinstance(self.action, ActionState):
            raise ValueError("action must be an ActionState")

    @classmethod
    def initial(cls, *, budget_total: float | int = 1_000_000) -> "RuntimeState":
        return cls(budget_total=budget_total)

    @property
    def belief_mass(self) -> dict[int, float]:
        return mass_dict(self.belief)

    @property
    def processing_spend(self) -> float | int:
        """Non-refundable processing spend, separate from contribution budget."""

        return sum(item.amount for item in self.charge_facts)

    def event_hash_for(self, event_id: str) -> str | None:
        return dict(self.event_hashes).get(event_id)

    def version_for(self, root_id: str) -> Version | None:
        return dict(self.versions).get(root_id)

    def contribution_for(self, root_id: str) -> ContributionToken | None:
        return next(
            (item for item in self.contribution_tokens if item.root_id == root_id), None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "belief": _mass_json(self.belief),
            "roots": [item.to_dict() for item in self.roots],
            "versions": [
                {"root_id": root_id, "version": version.to_dict()}
                for root_id, version in self.versions
            ],
            "contribution_tokens": [
                item.to_dict() for item in self.contribution_tokens
            ],
            "charge_facts": [item.to_dict() for item in self.charge_facts],
            "event_hashes": [
                {"event_id": event_id, "event_hash": digest}
                for event_id, digest in self.event_hashes
            ],
            "processing_tokens": list(self.processing_tokens),
            "budget_total": self.budget_total,
            "budget_used": self.budget_used,
            "availability": self.availability,
            "gate": self.gate.to_dict(),
            "action": self.action.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RuntimeState":
        return cls(
            belief=_mass_from_json(value["belief"]),
            roots=tuple(
                Root(str(item["root_id"]), str(item["root_type"]))
                for item in value["roots"]
            ),
            versions=tuple(
                (
                    str(item["root_id"]),
                    Version(
                        int(item["version"]["bundle_version"]),
                        str(item["version"]["schema_version"]),
                    ),
                )
                for item in value["versions"]
            ),
            contribution_tokens=tuple(
                ContributionToken.from_dict(item)
                for item in value["contribution_tokens"]
            ),
            charge_facts=tuple(
                ChargeFact.from_dict(item) for item in value["charge_facts"]
            ),
            event_hashes=tuple(
                (str(item["event_id"]), str(item["event_hash"]))
                for item in value["event_hashes"]
            ),
            processing_tokens=tuple(str(item) for item in value["processing_tokens"]),
            budget_total=value["budget_total"],
            budget_used=value["budget_used"],
            availability=str(value["availability"]),
            gate=GateState(str(value["gate"]["status"]), value["gate"].get("reason")),
            action=ActionState(
                str(value["action"]["status"]),
                value["action"].get("event_id"),
                value["action"].get("reason"),
            ),
        )

    @property
    def scientific_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.to_dict()))

    @property
    def state_hash(self) -> str:
        """Compatibility name for the scientific-state hash."""

        return self.scientific_hash
