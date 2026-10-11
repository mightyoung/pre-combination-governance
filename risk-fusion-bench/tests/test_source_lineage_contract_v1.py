"""Pure-CPU contract tests for versioned observable source-lineage evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

try:
    from rfb.research import source_lineage_contract_v1 as contract
except ImportError:
    contract = None


BASE = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def stamp(seconds: int) -> str:
    return (BASE + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def evidence(
    ref: str,
    *,
    trust: str = "VERIFIED",
    actual_seconds: int = 0,
    known_seconds: int = 0,
    valid_until_seconds: int | None = 100,
):
    return contract.LineageEvidence(
        source_ref=ref,
        actual_available_at=stamp(actual_seconds),
        earliest_known_at=stamp(known_seconds),
        trust_status=trust,
        valid_until=stamp(valid_until_seconds) if valid_until_seconds is not None else None,
    )


def node(node_id: str, *, node_type: str = "PROCESS", source_ref: str | None = None):
    return contract.LineageNode(
        node_id=node_id,
        node_type=node_type,
        evidence=evidence(source_ref or f"synthetic://node/{node_id}"),
    )


def edge(
    edge_id: str,
    upstream: str,
    downstream: str,
    *,
    trust: str = "VERIFIED",
    known_seconds: int = 0,
    valid_until_seconds: int | None = 100,
):
    return contract.LineageEdge(
        edge_id=edge_id,
        upstream_node_id=upstream,
        downstream_node_id=downstream,
        evidence=evidence(
            f"synthetic://edge/{edge_id}",
            trust=trust,
            known_seconds=known_seconds,
            valid_until_seconds=valid_until_seconds,
        ),
    )


def lineage(
    observation_id: str,
    *,
    root_id: str | None,
    terminal: str,
    nodes: tuple = (),
    edges: tuple = (),
    complete: bool = True,
    completeness_trust: str = "VERIFIED",
):
    return contract.ObservationLineage(
        observation_id=observation_id,
        declared_root_id=root_id,
        terminal_node_id=terminal,
        trace_complete=complete,
        completeness_evidence=evidence(
            f"synthetic://completion/{observation_id}", trust=completeness_trust
        ),
        nodes=nodes,
        edges=edges,
    )


def shared_pair(*, root_a: str = "ROOT-A", root_b: str = "ROOT-B"):
    shared = node("UPSTREAM-EVIDENCE-1", node_type="SOURCE")
    a_root, a_obs = node("ACQ-A", node_type="ACQUISITION"), node("OBS-A", node_type="OBSERVATION")
    b_root, b_obs = node("ACQ-B", node_type="ACQUISITION"), node("OBS-B", node_type="OBSERVATION")
    left = lineage(
        "OBS-A",
        root_id=root_a,
        terminal="OBS-A",
        nodes=(shared, a_root, a_obs),
        edges=(edge("EA1", shared.node_id, a_root.node_id), edge("EA2", a_root.node_id, a_obs.node_id)),
    )
    right = lineage(
        "OBS-B",
        root_id=root_b,
        terminal="OBS-B",
        nodes=(shared, b_root, b_obs),
        edges=(edge("EB1", shared.node_id, b_root.node_id), edge("EB2", b_root.node_id, b_obs.node_id)),
    )
    return left, right


def disjoint_pair(*, root_a: str = "ROOT-A", root_b: str = "ROOT-B"):
    a_root, a_obs = node("SOURCE-A", node_type="SOURCE"), node("OBS-A", node_type="OBSERVATION")
    b_root, b_obs = node("SOURCE-B", node_type="SOURCE"), node("OBS-B", node_type="OBSERVATION")
    left = lineage(
        "OBS-A", root_id=root_a, terminal="OBS-A", nodes=(a_root, a_obs),
        edges=(edge("EA", a_root.node_id, a_obs.node_id),),
    )
    right = lineage(
        "OBS-B", root_id=root_b, terminal="OBS-B", nodes=(b_root, b_obs),
        edges=(edge("EB", b_root.node_id, b_obs.node_id),),
    )
    return left, right


class SourceLineageContractV1Tests(unittest.TestCase):
    def require_api(self):
        self.assertIsNotNone(
            contract,
            "versioned source-lineage contract v1 is not implemented",
        )

    def setUp(self):
        self.require_api()

    def assess(self, left, right, *, at_seconds: int = 10):
        self.require_api()
        return contract.assess_source_lineage(left, right, as_of=stamp(at_seconds))

    def test_root_ids_alone_do_not_establish_dependence_or_independence(self):
        left = lineage("OBS-A", root_id="ROOT-A", terminal="OBS-A", complete=False)
        right = lineage("OBS-B", root_id="ROOT-B", terminal="OBS-B", complete=False)

        result = self.assess(left, right)

        self.assertEqual(result.status, contract.SourceDependenceStatus.UNKNOWN)
        self.assertEqual(result.declared_root_id_relation, contract.RootIdRelation.DISTINCT_IDS)
        self.assertIn("TRACE_INCOMPLETE", result.reason_codes)
        self.assertFalse(result.statistical_independence_established)

    def test_shared_verified_ancestor_groups_evidence_without_claiming_event_identity(self):
        left, right = shared_pair()

        result = self.assess(left, right)

        self.assertEqual(result.status, contract.SourceDependenceStatus.SHARED_KNOWN_ANCESTOR)
        self.assertEqual(result.declared_root_id_relation, contract.RootIdRelation.DISTINCT_IDS)
        self.assertEqual(result.shared_ancestor_node_ids, ("UPSTREAM-EVIDENCE-1",))
        self.assertIn("synthetic://edge/EA1", result.evidence_refs)
        self.assertFalse(result.statistical_independence_established)
        self.assertFalse(hasattr(result, "event_relation"))

    def test_complete_disjoint_observed_graph_is_not_called_statistically_independent(self):
        left, right = disjoint_pair()

        result = self.assess(left, right)

        self.assertEqual(result.status, contract.SourceDependenceStatus.NO_SHARED_KNOWN_ANCESTOR)
        self.assertEqual(result.shared_ancestor_node_ids, ())
        self.assertFalse(result.statistical_independence_established)
        self.assertIn("NO_STATISTICAL_INDEPENDENCE_CLAIM", result.reason_codes)

    def test_same_declared_root_id_is_reported_separately_from_lineage_and_event_identity(self):
        left, right = disjoint_pair(root_a="ROOT-SAME", root_b="ROOT-SAME")

        result = self.assess(left, right)

        self.assertEqual(result.declared_root_id_relation, contract.RootIdRelation.SAME_ID)
        self.assertEqual(result.status, contract.SourceDependenceStatus.NO_SHARED_KNOWN_ANCESTOR)
        self.assertFalse(hasattr(result, "event_relation"))

    def test_exact_duplicate_node_and_edge_assertions_are_idempotent(self):
        left, right = shared_pair()
        left = replace(
            left,
            nodes=left.nodes + (left.nodes[0],),
            edges=left.edges + (left.edges[0],),
        )

        result = self.assess(left, right)

        self.assertEqual(result.status, contract.SourceDependenceStatus.SHARED_KNOWN_ANCESTOR)
        self.assertEqual(result.unique_edge_count, 4)
        self.assertEqual(len(result.evidence_refs), len(set(result.evidence_refs)))

    def test_conflicting_duplicate_edge_id_fails_closed(self):
        left, right = shared_pair()
        conflicting = replace(
            left.edges[0],
            downstream_node_id="OBS-A",
        )
        left = replace(left, edges=left.edges + (conflicting,))

        result = self.assess(left, right)

        self.assertEqual(result.status, contract.SourceDependenceStatus.UNKNOWN)
        self.assertIn("CONFLICTING_EDGE_ID", result.reason_codes)

    def test_stale_lineage_evidence_is_unknown(self):
        left, right = shared_pair()
        stale = replace(
            left.edges[0],
            evidence=evidence("synthetic://edge/stale", valid_until_seconds=5),
        )
        left = replace(left, edges=(stale,) + left.edges[1:])

        result = self.assess(left, right, at_seconds=10)

        self.assertEqual(result.status, contract.SourceDependenceStatus.UNKNOWN)
        self.assertIn("STALE_EVIDENCE", result.reason_codes)

    def test_future_known_lineage_evidence_is_unknown_at_earlier_cutoff(self):
        left, right = shared_pair()
        future = replace(
            left.edges[0],
            evidence=evidence("synthetic://edge/future", known_seconds=20),
        )
        left = replace(left, edges=(future,) + left.edges[1:])

        result = self.assess(left, right, at_seconds=10)

        self.assertEqual(result.status, contract.SourceDependenceStatus.UNKNOWN)
        self.assertIn("EVIDENCE_NOT_YET_KNOWN", result.reason_codes)

    def test_unverified_or_conflicting_claim_is_unknown(self):
        left, right = shared_pair()
        unverified = replace(
            left.edges[0],
            evidence=evidence("synthetic://edge/unverified", trust="UNVERIFIED"),
        )
        left_unverified = replace(left, edges=(unverified,) + left.edges[1:])
        conflicting = replace(
            left.edges[0],
            evidence=evidence("synthetic://edge/conflict", trust="CONFLICTING"),
        )
        left_conflicting = replace(left, edges=(conflicting,) + left.edges[1:])

        unverified_result = self.assess(left_unverified, right)
        conflict_result = self.assess(left_conflicting, right)

        self.assertEqual(unverified_result.status, contract.SourceDependenceStatus.UNKNOWN)
        self.assertIn("UNVERIFIED_EVIDENCE", unverified_result.reason_codes)
        self.assertEqual(conflict_result.status, contract.SourceDependenceStatus.UNKNOWN)
        self.assertIn("CONFLICTING_EVIDENCE", conflict_result.reason_codes)

    def test_cycle_is_reported_as_invalid_instead_of_ignored(self):
        a, b = node("A"), node("B")
        left = lineage(
            "OBS-A", root_id="ROOT-A", terminal="B", nodes=(a, b),
            edges=(edge("E1", "A", "B"), edge("E2", "B", "A")),
        )
        c, d = node("C"), node("OBS-B", node_type="OBSERVATION")
        right = lineage(
            "OBS-B", root_id="ROOT-B", terminal="OBS-B", nodes=(c, d),
            edges=(edge("E3", "C", "OBS-B"),),
        )

        result = self.assess(left, right)

        self.assertEqual(result.status, contract.SourceDependenceStatus.INVALID_CYCLE)
        self.assertIn("LINEAGE_CYCLE", result.reason_codes)

    def test_edge_referencing_missing_node_is_unknown(self):
        terminal = node("OBS-A", node_type="OBSERVATION")
        left = lineage(
            "OBS-A", root_id="ROOT-A", terminal="OBS-A", nodes=(terminal,),
            edges=(edge("E1", "MISSING", "OBS-A"),),
        )
        other_root, other = node("SOURCE-B"), node("OBS-B", node_type="OBSERVATION")
        right = lineage(
            "OBS-B", root_id="ROOT-B", terminal="OBS-B", nodes=(other_root, other),
            edges=(edge("E2", "SOURCE-B", "OBS-B"),),
        )

        result = self.assess(left, right)

        self.assertEqual(result.status, contract.SourceDependenceStatus.UNKNOWN)
        self.assertIn("MISSING_LINEAGE_NODE", result.reason_codes)

    def test_evidence_timestamp_order_is_validated(self):
        self.require_api()
        with self.assertRaisesRegex(ValueError, "earliest_known_at"):
            evidence("synthetic://bad", actual_seconds=5, known_seconds=4)

    def test_hidden_source_family_cannot_be_passed_as_method_contract_input(self):
        self.require_api()
        with self.assertRaises(TypeError):
            lineage(
                "OBS-A",
                root_id="ROOT-A",
                terminal="OBS-A",
                source_family="SCORER-ONLY-FAMILY",
            )


if __name__ == "__main__":
    unittest.main()
