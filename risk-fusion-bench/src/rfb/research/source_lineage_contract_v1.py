"""Versioned observable source-lineage evidence contract.

This module assesses declared provenance relationships only. It does not
infer event identity or statistical independence, and it does not modify the
existing association rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


def _timestamp(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be an ISO-8601 timestamp with UTC offset")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"{label} must be an ISO-8601 timestamp with UTC offset"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    precision = "microseconds" if value.microsecond else "seconds"
    return value.astimezone(timezone.utc).isoformat(timespec=precision).replace(
        "+00:00", "Z"
    )


def _non_empty(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


class LineageTrustStatus(StrEnum):
    """Trust assigned to a particular observable lineage assertion."""

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    CONFLICTING = "CONFLICTING"


class RootIdRelation(StrEnum):
    """String comparison only; neither value asserts source independence."""

    SAME_ID = "SAME_DECLARED_ID"
    DISTINCT_IDS = "DISTINCT_DECLARED_IDS"
    UNKNOWN = "ROOT_ID_UNKNOWN"


class SourceDependenceStatus(StrEnum):
    """Observed ancestry result, not an event-identity or statistical claim."""

    SHARED_KNOWN_ANCESTOR = "SHARED_KNOWN_ANCESTOR"
    NO_SHARED_KNOWN_ANCESTOR = "NO_SHARED_KNOWN_ANCESTOR"
    UNKNOWN = "UNKNOWN"
    INVALID_CYCLE = "INVALID_CYCLE"


@dataclass(frozen=True, slots=True)
class LineageEvidence:
    """Source, time, freshness and trust attached to one lineage assertion."""

    source_ref: str
    actual_available_at: str
    earliest_known_at: str
    trust_status: LineageTrustStatus | str
    valid_until: str | None = None

    def __post_init__(self) -> None:
        _non_empty(self.source_ref, "source_ref")
        actual = _timestamp(self.actual_available_at, "actual_available_at")
        known = _timestamp(self.earliest_known_at, "earliest_known_at")
        if known < actual:
            raise ValueError("earliest_known_at cannot precede actual_available_at")
        try:
            trust = LineageTrustStatus(self.trust_status)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported lineage trust_status") from exc
        valid_until = self.valid_until
        if valid_until is not None:
            expiry = _timestamp(valid_until, "valid_until")
            if expiry < actual:
                raise ValueError("valid_until cannot precede actual_available_at")
            valid_until = _format_timestamp(expiry)
        object.__setattr__(self, "actual_available_at", _format_timestamp(actual))
        object.__setattr__(self, "earliest_known_at", _format_timestamp(known))
        object.__setattr__(self, "trust_status", trust)
        object.__setattr__(self, "valid_until", valid_until)


@dataclass(frozen=True, slots=True)
class LineageNode:
    """Observable upstream source, acquisition, transform, relay, or observation."""

    node_id: str
    node_type: str
    evidence: LineageEvidence

    def __post_init__(self) -> None:
        _non_empty(self.node_id, "node_id")
        _non_empty(self.node_type, "node_type")
        if not isinstance(self.evidence, LineageEvidence):
            raise TypeError("node evidence must be LineageEvidence")


@dataclass(frozen=True, slots=True)
class LineageEdge:
    """A directed, evidence-backed upstream-to-downstream relation."""

    edge_id: str
    upstream_node_id: str
    downstream_node_id: str
    evidence: LineageEvidence

    def __post_init__(self) -> None:
        _non_empty(self.edge_id, "edge_id")
        _non_empty(self.upstream_node_id, "upstream_node_id")
        _non_empty(self.downstream_node_id, "downstream_node_id")
        if not isinstance(self.evidence, LineageEvidence):
            raise TypeError("edge evidence must be LineageEvidence")


@dataclass(frozen=True, slots=True)
class ObservationLineage:
    """One observation's visible root declaration and provenance graph claim."""

    observation_id: str
    declared_root_id: str | None
    terminal_node_id: str
    trace_complete: bool
    completeness_evidence: LineageEvidence
    nodes: tuple[LineageNode, ...]
    edges: tuple[LineageEdge, ...]

    def __post_init__(self) -> None:
        _non_empty(self.observation_id, "observation_id")
        _non_empty(self.terminal_node_id, "terminal_node_id")
        if self.declared_root_id is not None:
            _non_empty(self.declared_root_id, "declared_root_id")
        if type(self.trace_complete) is not bool:
            raise ValueError("trace_complete must be bool")
        if not isinstance(self.completeness_evidence, LineageEvidence):
            raise TypeError("completeness_evidence must be LineageEvidence")
        if not isinstance(self.nodes, tuple) or any(
            not isinstance(node, LineageNode) for node in self.nodes
        ):
            raise ValueError("nodes must be a tuple of LineageNode")
        if not isinstance(self.edges, tuple) or any(
            not isinstance(edge, LineageEdge) for edge in self.edges
        ):
            raise ValueError("edges must be a tuple of LineageEdge")


@dataclass(frozen=True, slots=True)
class SourceLineageAssessment:
    """A bounded lineage result that never asserts statistical independence."""

    status: SourceDependenceStatus
    declared_root_id_relation: RootIdRelation
    shared_ancestor_node_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    unique_edge_count: int
    statistical_independence_established: bool = False

    def __post_init__(self) -> None:
        if self.statistical_independence_established:
            raise ValueError("this contract cannot establish statistical independence")


def _root_relation(
    left: ObservationLineage, right: ObservationLineage
) -> RootIdRelation:
    if left.declared_root_id is None or right.declared_root_id is None:
        return RootIdRelation.UNKNOWN
    if left.declared_root_id == right.declared_root_id:
        return RootIdRelation.SAME_ID
    return RootIdRelation.DISTINCT_IDS


def _all_evidence(
    left: ObservationLineage,
    right: ObservationLineage,
) -> tuple[LineageEvidence, ...]:
    values = [left.completeness_evidence, right.completeness_evidence]
    for claim in (left, right):
        values.extend(node.evidence for node in claim.nodes)
        values.extend(edge.evidence for edge in claim.edges)
    return tuple(values)


def _result(
    status: SourceDependenceStatus,
    root_relation: RootIdRelation,
    *,
    shared: tuple[str, ...] = (),
    reasons: tuple[str, ...],
    refs: tuple[str, ...],
    edge_count: int = 0,
) -> SourceLineageAssessment:
    return SourceLineageAssessment(
        status=status,
        declared_root_id_relation=root_relation,
        shared_ancestor_node_ids=shared,
        reason_codes=tuple(sorted(set(reasons))),
        evidence_refs=tuple(sorted(set(refs))),
        unique_edge_count=edge_count,
        statistical_independence_established=False,
    )


def _validate_evidence(
    evidence: tuple[LineageEvidence, ...], *, as_of: datetime
) -> tuple[str, ...]:
    reasons: set[str] = set()
    for claim in evidence:
        if claim.earliest_known_at > _format_timestamp(as_of):
            reasons.add("EVIDENCE_NOT_YET_KNOWN")
        if claim.valid_until is not None and _timestamp(
            claim.valid_until, "valid_until"
        ) < as_of:
            reasons.add("STALE_EVIDENCE")
        if claim.trust_status == LineageTrustStatus.UNVERIFIED:
            reasons.add("UNVERIFIED_EVIDENCE")
        elif claim.trust_status == LineageTrustStatus.CONFLICTING:
            reasons.add("CONFLICTING_EVIDENCE")
    return tuple(sorted(reasons))


def _unique_graph(
    left: ObservationLineage,
    right: ObservationLineage,
) -> tuple[dict[str, LineageNode], dict[str, LineageEdge], tuple[str, ...]]:
    nodes: dict[str, LineageNode] = {}
    edges: dict[str, LineageEdge] = {}
    conflicts: set[str] = set()
    for claim in (left, right):
        for item in claim.nodes:
            previous = nodes.get(item.node_id)
            if previous is not None and previous != item:
                conflicts.add("CONFLICTING_NODE_ID")
            else:
                nodes[item.node_id] = item
        for item in claim.edges:
            previous = edges.get(item.edge_id)
            if previous is not None and previous != item:
                conflicts.add("CONFLICTING_EDGE_ID")
            else:
                edges[item.edge_id] = item
    return nodes, edges, tuple(sorted(conflicts))


def _has_cycle(edges: tuple[LineageEdge, ...]) -> bool:
    children: dict[str, list[str]] = {}
    indegree: dict[str, int] = {}
    for edge in edges:
        children.setdefault(edge.upstream_node_id, []).append(edge.downstream_node_id)
        indegree.setdefault(edge.upstream_node_id, 0)
        indegree[edge.downstream_node_id] = indegree.get(edge.downstream_node_id, 0) + 1
    ready = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        node_id = ready.pop()
        visited += 1
        for child in children.get(node_id, ()):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    return visited != len(indegree)


def _ancestor_set(terminal_node_id: str, edges: tuple[LineageEdge, ...]) -> set[str]:
    parents: dict[str, list[str]] = {}
    for edge in edges:
        parents.setdefault(edge.downstream_node_id, []).append(edge.upstream_node_id)
    ancestors = {terminal_node_id}
    pending = [terminal_node_id]
    while pending:
        current = pending.pop()
        for parent in parents.get(current, ()):
            if parent not in ancestors:
                ancestors.add(parent)
                pending.append(parent)
    return ancestors


def assess_source_lineage(
    left: ObservationLineage,
    right: ObservationLineage,
    *,
    as_of: str,
) -> SourceLineageAssessment:
    """Assess only shared ancestry supported by complete, current evidence.

    ``NO_SHARED_KNOWN_ANCESTOR`` means only that the two supplied complete
    graphs do not overlap. It is never statistical independence. Callers may
    group or discount evidence for a shared ancestor; choosing a discount
    magnitude and deciding event identity are outside this contract.
    """
    if not isinstance(left, ObservationLineage) or not isinstance(
        right, ObservationLineage
    ):
        raise TypeError("left and right must be ObservationLineage values")
    cutoff = _timestamp(as_of, "as_of")
    root_relation = _root_relation(left, right)
    all_evidence = _all_evidence(left, right)
    refs = tuple(claim.source_ref for claim in all_evidence)

    if not left.trace_complete or not right.trace_complete:
        return _result(
            SourceDependenceStatus.UNKNOWN,
            root_relation,
            reasons=("TRACE_INCOMPLETE",),
            refs=refs,
        )

    nodes, edges, graph_conflicts = _unique_graph(left, right)
    if graph_conflicts:
        return _result(
            SourceDependenceStatus.UNKNOWN,
            root_relation,
            reasons=graph_conflicts,
            refs=refs,
            edge_count=len(edges),
        )

    evidence_reasons = _validate_evidence(all_evidence, as_of=cutoff)
    if evidence_reasons:
        return _result(
            SourceDependenceStatus.UNKNOWN,
            root_relation,
            reasons=evidence_reasons,
            refs=refs,
            edge_count=len(edges),
        )

    missing_nodes = {
        claim.terminal_node_id for claim in (left, right) if claim.terminal_node_id not in nodes
    }
    for edge in edges.values():
        if edge.upstream_node_id not in nodes:
            missing_nodes.add(edge.upstream_node_id)
        if edge.downstream_node_id not in nodes:
            missing_nodes.add(edge.downstream_node_id)
    if missing_nodes:
        return _result(
            SourceDependenceStatus.UNKNOWN,
            root_relation,
            reasons=("MISSING_LINEAGE_NODE",),
            refs=refs,
            edge_count=len(edges),
        )

    unique_edges = tuple(edges.values())
    if _has_cycle(unique_edges):
        return _result(
            SourceDependenceStatus.INVALID_CYCLE,
            root_relation,
            reasons=("LINEAGE_CYCLE",),
            refs=refs,
            edge_count=len(edges),
        )

    shared = tuple(
        sorted(
            _ancestor_set(left.terminal_node_id, unique_edges)
            & _ancestor_set(right.terminal_node_id, unique_edges)
        )
    )
    if shared:
        return _result(
            SourceDependenceStatus.SHARED_KNOWN_ANCESTOR,
            root_relation,
            shared=shared,
            reasons=("SHARED_KNOWN_ANCESTOR", "GROUP_OR_DISCOUNT_SHARED_EVIDENCE"),
            refs=refs,
            edge_count=len(edges),
        )
    return _result(
        SourceDependenceStatus.NO_SHARED_KNOWN_ANCESTOR,
        root_relation,
        reasons=("NO_SHARED_KNOWN_ANCESTOR", "NO_STATISTICAL_INDEPENDENCE_CLAIM"),
        refs=refs,
        edge_count=len(edges),
    )


__all__ = [
    "LineageTrustStatus",
    "RootIdRelation",
    "SourceDependenceStatus",
    "LineageEvidence",
    "LineageNode",
    "LineageEdge",
    "ObservationLineage",
    "SourceLineageAssessment",
    "assess_source_lineage",
]
