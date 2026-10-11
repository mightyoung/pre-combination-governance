"""Constructive tests for finite synthetic association evaluation contracts."""

from __future__ import annotations

import json
import unittest
from dataclasses import fields
from datetime import datetime, timedelta, timezone

try:
    from rfb.research import observable_association as association
    from rfb.research import observable_association_evaluation as evaluation
except ImportError:
    association = None
    evaluation = None


BASE = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def stamp(seconds: int) -> str:
    return (BASE + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def require_api(test: unittest.TestCase) -> None:
    test.assertIsNotNone(evaluation, "finite synthetic evaluation module is missing")
    test.assertIsNotNone(association, "observable association API is missing")


def make_step(method: str, cutoff: str, actions, *, pairs=None, prefix_hash="a" * 64):
    proposals = tuple(
        association.AssociationProposal(
            method=method,
            pair=pair,
            action=action,
            reason_codes=("CONTRACT_TEST",),
            evidence_refs=(f"synthetic://pair/{index}",),
            independent_lineage_root_count=2,
            decided_at=cutoff,
        )
        for index, (pair, action) in enumerate(actions)
    )
    candidate_pairs = tuple(pairs) if pairs is not None else tuple(pair for pair, _ in actions)
    return evaluation.FrozenArmStep(
        method=method,
        cutoff=cutoff,
        candidate_pairs=candidate_pairs,
        input_prefix_sha256=prefix_hash,
        output=association.freeze_proposals(proposals),
    )


class ObservableAssociationEvaluationTests(unittest.TestCase):
    def test_split_plan_is_finite_balanced_and_heldout_generation_is_gated(self):
        require_api(self)
        development = evaluation.get_split_plan("development")
        heldout = evaluation.get_split_plan("heldout")

        self.assertEqual(development.seed, 2026101101)
        self.assertEqual(development.world_budget, 12)
        self.assertEqual(development.worlds_per_stratum, 3)
        self.assertEqual(heldout.seed, 2026101102)
        self.assertEqual(heldout.world_budget, 24)
        self.assertEqual(heldout.worlds_per_stratum, 6)
        self.assertNotEqual(development.seed, heldout.seed)
        self.assertEqual(development.search_configs_per_method, 0)
        self.assertEqual(heldout.search_configs_per_method, 0)
        with self.assertRaises(PermissionError):
            evaluation.generate_protocol_split("heldout")
        with self.assertRaises(PermissionError):
            evaluation.generate_synthetic_world(
                seed=heldout.seed,
                world_index=0,
                stratum=evaluation.SyntheticStratum.INDEPENDENT_SAME_EVENT,
                split_name="heldout",
            )

    def test_contract_world_is_deterministic_and_keeps_truth_out_of_method_input(self):
        require_api(self)
        first = evaluation.generate_synthetic_world(
            seed=1729,
            world_index=0,
            stratum=evaluation.SyntheticStratum.DEPENDENT_REPLAY_UNKNOWN,
        )
        repeated = evaluation.generate_synthetic_world(
            seed=1729,
            world_index=0,
            stratum=evaluation.SyntheticStratum.DEPENDENT_REPLAY_UNKNOWN,
        )

        self.assertEqual(first.observable, repeated.observable)
        self.assertEqual(first.scorer_only, repeated.scorer_only)
        self.assertEqual(
            {item.name for item in fields(first.observable)}, {"records", "cutoffs"}
        )
        observable_json = evaluation.serialize_observable_trajectory(first.observable)
        self.assertNotIn(b"world_group", observable_json)
        self.assertNotIn(b"stratum", observable_json)
        self.assertNotIn(b"first_sufficient_evidence_at", observable_json)
        self.assertNotIn(b"UNKNOWN", observable_json)
        self.assertTrue(
            any(
                field.earliest_known_at > field.actual_available_at
                for record in first.observable.records
                for field in record.fields
            ),
            "contract worlds must include a late-known fact whose source time is earlier",
        )
        self.assertEqual(len(first.scorer_only.pair_truths), 6)
        self.assertEqual(
            sum(
                truth.label is evaluation.PairTruthLabel.UNKNOWN
                for truth in first.scorer_only.pair_truths
            ),
            1,
        )

        steps = evaluation.run_two_methods(first.observable)
        with self.assertRaises(TypeError):
            evaluation.run_two_methods(first.scorer_only)
        escalation_score = evaluation.score_world(
            steps, first.scorer_only, alert_actions=()
        )["alert_escalation"]
        self.assertEqual(escalation_score["status"], "EVALUATED")
        self.assertEqual(escalation_score["denominator"], 1)
        self.assertEqual(escalation_score["missed_count"], 1)
        by_cutoff = {}
        for step in steps:
            by_cutoff.setdefault(step.cutoff, []).append(step)
        self.assertEqual(len(by_cutoff), len(first.observable.cutoffs))
        for same_cutoff_steps in by_cutoff.values():
            self.assertEqual(len(same_cutoff_steps), 2)
            self.assertEqual(
                same_cutoff_steps[0].input_prefix_sha256,
                same_cutoff_steps[1].input_prefix_sha256,
            )
            self.assertEqual(
                same_cutoff_steps[0].candidate_pairs,
                same_cutoff_steps[1].candidate_pairs,
            )
            for step in same_cutoff_steps:
                self.assertNotIn(b"world_group", step.output.canonical_json)
                self.assertNotIn(b"first_sufficient_evidence_at", step.output.canonical_json)

        final_prefix = association.freeze_observable_prefix(
            first.observable.records, as_of=first.observable.cutoffs[-1]
        )
        self.assertEqual(len(final_prefix.observations), 4)
        final_multi = next(
            step
            for step in steps
            if step.method == "MULTI_EVIDENCE_RULE"
            and step.cutoff == first.observable.cutoffs[-1]
        )
        final_proposals = json.loads(final_multi.output.canonical_json)["proposals"]
        self.assertIn(
            1,
            [row["independent_lineage_root_count"] for row in final_proposals],
        )

        other = evaluation.generate_synthetic_world(
            seed=1729,
            world_index=1,
            stratum=evaluation.SyntheticStratum.DEPENDENT_REPLAY_UNKNOWN,
        )
        self.assertNotEqual(first.scorer_only.world_group_id, other.scorer_only.world_group_id)
        first_ids = {record.observation_id for record in first.observable.records}
        other_ids = {record.observation_id for record in other.observable.records}
        self.assertTrue(first_ids.isdisjoint(other_ids))
        first_roots = {
            field.value[0]
            for record in first.observable.records
            for field in record.fields
            if field.name == "acquisition_lineage"
        }
        other_roots = {
            field.value[0]
            for record in other.observable.records
            for field in record.fields
            if field.name == "acquisition_lineage"
        }
        self.assertTrue(first_roots.isdisjoint(other_roots))

    def test_scorer_uses_unknown_in_coverage_but_not_error_denominators(self):
        require_api(self)
        world = evaluation.generate_synthetic_world(
            seed=82,
            world_index=2,
            stratum=evaluation.SyntheticStratum.DEPENDENT_REPLAY_UNKNOWN,
        )
        truth_rows = world.scorer_only.pair_truths
        same_pair = next(row.pair for row in truth_rows if row.label is evaluation.PairTruthLabel.SAME)
        different_pair = next(
            row.pair for row in truth_rows if row.label is evaluation.PairTruthLabel.DIFFERENT
        )
        unknown_pair = next(
            row.pair for row in truth_rows if row.label is evaluation.PairTruthLabel.UNKNOWN
        )
        other_pairs = tuple(
            row.pair
            for row in truth_rows
            if row.pair not in {same_pair, different_pair, unknown_pair}
        )
        all_pairs = tuple(row.pair for row in truth_rows)
        actions = (
            (same_pair, association.ProposalAction.RETAIN_SEPARATELY),
            (different_pair, association.ProposalAction.LINK_CANDIDATES),
            (unknown_pair, association.ProposalAction.LINK_CANDIDATES),
            *((pair, association.ProposalAction.ABSTAIN) for pair in other_pairs),
        )
        terminal = world.scorer_only.evaluation_cutoff
        steps = (
            make_step("TIME_ASSET_RULE", terminal, actions, pairs=all_pairs),
            make_step(
                "MULTI_EVIDENCE_RULE",
                terminal,
                tuple((pair, association.ProposalAction.ABSTAIN) for pair in all_pairs),
                pairs=all_pairs,
            ),
        )

        scored = evaluation.score_world(steps, world.scorer_only)
        baseline = scored["methods"]["TIME_ASSET_RULE"]
        self.assertEqual(baseline["fixed_pair_denominator"], 6)
        self.assertEqual(baseline["same_pair_denominator"], 2)
        self.assertEqual(baseline["different_pair_denominator"], 3)
        self.assertEqual(baseline["unknown_pair_count"], 1)
        self.assertEqual(baseline["false_split_count"], 1)
        self.assertEqual(baseline["false_merge_count"], 1)
        self.assertEqual(baseline["coverage_count"], 3)
        self.assertEqual(baseline["coverage_denominator"], 6)
        self.assertEqual(baseline["non_abstaining_unknown_count"], 1)
        self.assertEqual(
            scored["methods"]["MULTI_EVIDENCE_RULE"]["coverage_count"], 0
        )

        with self.assertRaises(ValueError):
            evaluation.ScorerSidecar(
                world_group_id="WORLD-INCOMPLETE-FORMAL",
                stratum=world.scorer_only.stratum,
                pair_truths=truth_rows[:-1],
                evaluation_cutoff=world.scorer_only.evaluation_cutoff,
                escalation_opportunities=world.scorer_only.escalation_opportunities,
                split_name="development",
            )

    def test_all_registered_strata_generate_bounded_contract_worlds(self):
        require_api(self)
        for index, stratum in enumerate(evaluation.SyntheticStratum):
            with self.subTest(stratum=stratum.value):
                world = evaluation.generate_synthetic_world(
                    seed=9917,
                    world_index=index,
                    stratum=stratum,
                )
                self.assertLessEqual(len(world.observable.records), 7)
                self.assertLessEqual(len(world.observable.cutoffs), 8)
                self.assertEqual(len(world.scorer_only.pair_truths), 6)
                self.assertEqual(len(evaluation.run_two_methods(world.observable)), 2 * len(world.observable.cutoffs))

    def test_wrong_early_decision_does_not_end_valid_decision_time(self):
        require_api(self)
        pair = association.CandidatePair("OBS-A", "OBS-B")
        sidecar = evaluation.ScorerSidecar(
            world_group_id="WORLD-CONTRACT-TIMING",
            stratum=evaluation.SyntheticStratum.INDEPENDENT_SAME_EVENT,
            pair_truths=(
                evaluation.PairTruth(
                    pair=pair,
                    label=evaluation.PairTruthLabel.SAME,
                    first_sufficient_evidence_at=stamp(10),
                ),
            ),
            evaluation_cutoff=stamp(20),
            escalation_opportunities=(),
        )
        candidate_pairs = (pair,)
        time_asset_steps = (
            make_step(
                "TIME_ASSET_RULE", stamp(5),
                ((pair, association.ProposalAction.RETAIN_SEPARATELY),),
                pairs=candidate_pairs, prefix_hash="b" * 64,
            ),
            make_step(
                "TIME_ASSET_RULE", stamp(12),
                ((pair, association.ProposalAction.LINK_CANDIDATES),),
                pairs=candidate_pairs, prefix_hash="c" * 64,
            ),
            make_step(
                "TIME_ASSET_RULE", stamp(20),
                ((pair, association.ProposalAction.LINK_CANDIDATES),),
                pairs=candidate_pairs, prefix_hash="d" * 64,
            ),
        )
        multi_steps = tuple(
            make_step(
                "MULTI_EVIDENCE_RULE", cutoff,
                ((pair, association.ProposalAction.ABSTAIN),),
                pairs=candidate_pairs, prefix_hash=prefix_hash,
            )
            for cutoff, prefix_hash in ((stamp(5), "b" * 64), (stamp(12), "c" * 64), (stamp(20), "d" * 64))
        )

        scored = evaluation.score_world((*time_asset_steps, *multi_steps), sidecar)
        timing = scored["methods"]["TIME_ASSET_RULE"]["decision_timing"][0]
        self.assertTrue(timing["event_observed"])
        self.assertEqual(timing["valid_decision_at"], stamp(12))
        self.assertEqual(timing["duration_seconds"], 2)
        censored = scored["methods"]["MULTI_EVIDENCE_RULE"]["decision_timing"][0]
        self.assertFalse(censored["event_observed"])
        self.assertEqual(censored["censor_stage"], "AFTER_SUFFICIENT_EVIDENCE")
        self.assertEqual(censored["duration_seconds"], 10)

    def test_alert_escalation_metric_is_separate_and_never_inferred_from_rule_action(self):
        require_api(self)
        opportunity = evaluation.AlertEscalationOpportunity(
            observation_id="OBS-RISK",
            risk_flag_known_at=stamp(10),
            evaluation_cutoff=stamp(30),
            required_severity="CRITICAL",
        )
        not_evaluated = evaluation.score_alert_escalation_misses((opportunity,), None)
        self.assertEqual(not_evaluated["status"], "NOT_EVALUATED")
        self.assertEqual(not_evaluated["denominator"], 0)
        self.assertIsNone(not_evaluated["miss_rate"])

        result = evaluation.score_alert_escalation_misses((opportunity,), ())
        self.assertEqual(result["status"], "EVALUATED")
        self.assertEqual(result["denominator"], 1)
        self.assertEqual(result["missed_count"], 1)
        self.assertEqual(result["miss_rate"], 1.0)

        timely = evaluation.AlertAction(
            observation_id="OBS-RISK", severity="CRITICAL", decided_at=stamp(15)
        )
        result = evaluation.score_alert_escalation_misses((opportunity,), (timely,))
        self.assertEqual(result["missed_count"], 0)
        self.assertEqual(result["delays_seconds"], (5,))

    def test_aggregation_counts_independent_world_groups_once(self):
        require_api(self)
        world = evaluation.generate_synthetic_world(
            seed=213,
            world_index=0,
            stratum=evaluation.SyntheticStratum.INDEPENDENT_SAME_EVENT,
        )
        steps = evaluation.run_two_methods(world.observable)
        score = evaluation.score_world(steps, world.scorer_only)
        aggregate = evaluation.aggregate_world_scores((score,))
        self.assertEqual(aggregate["independent_world_count"], 1)
        with self.assertRaises(ValueError):
            evaluation.aggregate_world_scores((score, score))

        development_score = dict(score, split_name="development")
        heldout_score = dict(
            score,
            split_name="heldout",
            world_group_id="WORLD-OTHER-SPLIT",
        )
        with self.assertRaises(ValueError):
            evaluation.aggregate_world_scores((development_score, heldout_score))


if __name__ == "__main__":
    unittest.main()
