"""Small synthetic tests for observable-only candidate association rules."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import unittest

try:
    from rfb.research import observable_association as association
except ImportError:
    association = None

try:
    from rfb.research.alert_governance import AlertLedger, CandidateEvent
except ImportError:
    AlertLedger = None
    CandidateEvent = None


BASE = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def stamp(seconds: int) -> str:
    return (BASE + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def record(
    observation_id: str,
    *,
    asset_id: str = "PUMP-A",
    binding: str = "VERIFIED",
    modality: str = "TEMPERATURE",
    source_seconds: int = 0,
    received_seconds: int = 0,
    known_seconds: int | None = None,
    value: float = 80.0,
    unit: str = "degC",
    value_error: float = 0.5,
    position: tuple[float, float] = (0.0, 0.0),
    position_error: float = 0.5,
    quality: str = "GOOD",
    calibration: str = "CURRENT",
    risk_flag: str = "EXPOSURE",
    lineage_root: str = "ROOT-TEMP",
    lineage_path: tuple[str, ...] = ("edge-A", "relay-A"),
):
    if association is None:
        return None
    known = received_seconds if known_seconds is None else known_seconds
    actual = stamp(source_seconds)
    fields = (
        association.KnownField("asset_id", asset_id, actual, stamp(known)),
        association.KnownField("asset_binding_status", binding, actual, stamp(known)),
        association.KnownField("modality", modality, actual, stamp(known)),
        association.KnownField("value", value, actual, stamp(known)),
        association.KnownField("unit", unit, actual, stamp(known)),
        association.KnownField("value_error", value_error, actual, stamp(known)),
        association.KnownField("position_m", position, actual, stamp(known)),
        association.KnownField("position_error_m", position_error, actual, stamp(known)),
        association.KnownField("quality_status", quality, actual, stamp(known)),
        association.KnownField("calibration_status", calibration, actual, stamp(known)),
        association.KnownField("source_time", stamp(source_seconds), actual, stamp(known)),
        association.KnownField("risk_flag", risk_flag, actual, stamp(known)),
        association.KnownField(
            "acquisition_lineage",
            (lineage_root, *lineage_path),
            actual,
            stamp(known),
        ),
    )
    return association.ObservationRecord(
        observation_id=observation_id,
        id_actual_available_at=actual,
        id_earliest_known_at=stamp(known),
        received_at=stamp(received_seconds),
        fields=fields,
    )


def risk_update(
    observation_id: str,
    *,
    source_seconds: int,
    received_seconds: int,
    risk_flag: str = "EXPOSURE_HIGH",
):
    if association is None:
        return None
    actual = stamp(source_seconds)
    known = stamp(received_seconds)
    return association.ObservationRecord(
        observation_id=observation_id,
        id_actual_available_at=actual,
        id_earliest_known_at=actual,
        received_at=known,
        fields=(
            association.KnownField("risk_flag", risk_flag, actual, known),
        ),
    )


def freeze(records, *, at_seconds: int):
    return association.freeze_observable_prefix(records, as_of=stamp(at_seconds))


def run_arm(prefix, method):
    config = association.InferenceConfig()
    pairs = association.build_candidate_universe(prefix, config=config)
    proposals = tuple(
        method(prefix, pair, config=config) for pair in pairs
    )
    return pairs, proposals


def normalized_proposals(proposals):
    return sorted(
        (
            proposal.action.value,
            tuple(sorted(proposal.reason_codes)),
            proposal.independent_lineage_root_count,
        )
        for proposal in proposals
    )


class ObservableAssociationTests(unittest.TestCase):
    def require_api(self):
        self.assertIsNotNone(
            association,
            "observable-only association boundary and rule methods are not implemented",
        )

    def require_inference_api(self):
        self.require_api()
        expected = (
            "InferenceConfig",
            "CandidatePair",
            "ProposalAction",
            "AssociationProposal",
            "AssociationMethod",
            "build_candidate_universe",
            "time_asset_rule",
            "multi_evidence_rule",
            "freeze_proposals",
            "apply_proposal_to_alert_ledger",
        )
        self.assertTrue(
            all(hasattr(association, name) for name in expected),
            "candidate inference and ledger handoff API is incomplete",
        )

    def test_rejects_forbidden_fields_and_metadata(self):
        self.require_api()
        for name in (
            "event_id",
            "episode_id",
            "card_id",
            "association_id",
            "scenario_id",
            "world_group",
            "ground_truth",
            "future_endpoint",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                association.KnownField(name, "hidden", stamp(0), stamp(0))
        with self.assertRaises(ValueError):
            association.KnownField("risk_flag", "SAME", stamp(0), stamp(0))
        with self.assertRaises(TypeError):
            association.ObservationRecord(
                observation_id="OBS-1",
                id_actual_available_at=stamp(0),
                id_earliest_known_at=stamp(0),
                received_at=stamp(0),
                fields=(),
                scenario_id="WORLD-1",
            )

    def test_rejects_earliest_known_before_actual_availability(self):
        self.require_api()
        with self.assertRaisesRegex(ValueError, "earliest_known_at"):
            association.KnownField(
                "value",
                80.0,
                actual_available_at=stamp(10),
                earliest_known_at=stamp(9),
            )

    def test_late_source_fact_is_hidden_until_received(self):
        self.require_api()
        late = record(
            "OBS-LATE-THERMAL",
            modality="THERMAL_IMAGE",
            source_seconds=5,
            received_seconds=90,
            lineage_root="ROOT-THERMAL",
        )

        before_arrival = freeze((late,), at_seconds=60)
        after_arrival = freeze((late,), at_seconds=100)

        self.assertEqual(before_arrival.observations, ())
        self.assertEqual(len(after_arrival.observations), 1)
        visible = after_arrival.observations[0]
        self.assertEqual(visible.value("source_time"), stamp(5))
        self.assertEqual(visible.received_at, stamp(90))

    def test_same_cutoff_output_is_independent_of_future_suffix(self):
        self.require_inference_api()
        common = (
            record("OBS-TEMP-A", lineage_root="ROOT-TEMP"),
            record(
                "OBS-THERM-A",
                modality="THERMAL_IMAGE",
                source_seconds=5,
                received_seconds=5,
                value=81.0,
                lineage_root="ROOT-THERMAL",
            ),
        )
        future_first = common + (
            risk_update("OBS-TEMP-A", source_seconds=0, received_seconds=100),
            record(
                "OBS-FUTURE-A",
                asset_id="PUMP-A",
                modality="THERMAL_IMAGE",
                source_seconds=20,
                received_seconds=100,
                lineage_root="ROOT-THERMAL",
            ),
        )
        future_second = common + (
            risk_update("OBS-TEMP-A", source_seconds=0, received_seconds=100),
            record(
                "OBS-FUTURE-B",
                asset_id="PUMP-B",
                modality="VIBRATION",
                source_seconds=20,
                received_seconds=100,
                lineage_root="ROOT-VIBRATION",
            ),
        )

        outputs = []
        for trajectory in (future_first, future_second):
            prefix = freeze(trajectory, at_seconds=50)
            arms = []
            for method in (association.time_asset_rule, association.multi_evidence_rule):
                pairs, proposals = run_arm(prefix, method)
                arms.append((pairs, association.freeze_proposals(proposals).sha256))
            outputs.append((prefix, arms))

        self.assertEqual(outputs[0][0], outputs[1][0])
        self.assertEqual(outputs[0][1], outputs[1][1])

    def test_opaque_identifier_bijection_preserves_normalized_proposals(self):
        self.require_inference_api()
        original_records = (
            record("OBS-TEMP-A", asset_id="PUMP-A", lineage_root="ROOT-TEMP"),
            record(
                "OBS-THERM-A",
                asset_id="PUMP-A",
                modality="THERMAL_IMAGE",
                source_seconds=5,
                received_seconds=5,
                value=81.0,
                lineage_root="ROOT-THERMAL",
            ),
        )
        renames = {
            "OBS-TEMP-A": "x-91",
            "OBS-THERM-A": "x-18",
            "PUMP-A": "asset-z",
            "ROOT-TEMP": "src-foo",
            "ROOT-THERMAL": "src-bar",
        }
        renamed_records = []
        for item in original_records:
            renamed_fields = []
            for fact in item.fields:
                value = fact.value
                if fact.name == "asset_id":
                    value = renames[value]
                elif fact.name == "acquisition_lineage":
                    value = tuple(renames.get(part, part) for part in value)
                renamed_fields.append(replace(fact, value=value))
            renamed_records.append(
                replace(
                    item,
                    observation_id=renames[item.observation_id],
                    fields=tuple(renamed_fields),
                )
            )

        original = freeze(original_records, at_seconds=20)
        renamed = freeze(renamed_records, at_seconds=20)
        for method in (association.time_asset_rule, association.multi_evidence_rule):
            self.assertEqual(
                normalized_proposals(run_arm(original, method)[1]),
                normalized_proposals(run_arm(renamed, method)[1]),
            )

    def test_duplicate_forwarding_does_not_increase_lineage_support(self):
        self.require_inference_api()
        first = record("OBS-TEMP-A", lineage_root="ROOT-TEMP")
        thermal = record(
            "OBS-THERM-A",
            modality="THERMAL_IMAGE",
            source_seconds=5,
            received_seconds=5,
            value=81.0,
            lineage_root="ROOT-THERMAL",
        )
        forwarded_replay = record(
            "OBS-TEMP-A",
            received_seconds=40,
            known_seconds=0,
            lineage_root="ROOT-TEMP",
            lineage_path=("edge-A", "relay-B", "relay-C"),
        )
        prefix = freeze((first, thermal, forwarded_replay), at_seconds=50)

        self.assertEqual(len(prefix.observations), 2)
        pairs, proposals = run_arm(prefix, association.multi_evidence_rule)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(proposals[0].action, association.ProposalAction.LINK_CANDIDATES)
        self.assertEqual(proposals[0].independent_lineage_root_count, 2)

    def test_persistent_cross_modal_same_asset_becomes_link_candidate(self):
        self.require_inference_api()
        prefix = freeze(
            (
                record("OBS-TEMP-1", lineage_root="ROOT-TEMP"),
                record(
                    "OBS-THERM-1",
                    modality="THERMAL_IMAGE",
                    source_seconds=5,
                    received_seconds=5,
                    value=81.0,
                    lineage_root="ROOT-THERMAL",
                ),
            ),
            at_seconds=10,
        )
        pairs, proposals = run_arm(prefix, association.multi_evidence_rule)
        baseline_pairs, baseline_proposals = run_arm(prefix, association.time_asset_rule)

        self.assertEqual(len(pairs), 1)
        self.assertEqual(proposals[0].action, association.ProposalAction.LINK_CANDIDATES)
        self.assertIn("CROSS_MODAL_SUPPORT", proposals[0].reason_codes)
        self.assertEqual(baseline_pairs, pairs)
        self.assertEqual(
            baseline_proposals[0].action, association.ProposalAction.LINK_CANDIDATES
        )
        self.assertEqual(
            baseline_proposals[0].reason_codes,
            ("VERIFIED_ASSET_MATCH", "TIME_AND_POSITION_COMPATIBLE"),
        )

    def test_persistent_sensor_world_with_forward_replay_late_arrival_and_flag_escalation(self):
        self.require_inference_api()
        temp_first = record("OBS-TEMP-0", source_seconds=0, received_seconds=0)
        thermal_first = record(
            "OBS-THERM-0",
            modality="THERMAL_IMAGE",
            source_seconds=5,
            received_seconds=5,
            value=81.0,
            lineage_root="ROOT-THERMAL",
        )
        temp_second = record(
            "OBS-TEMP-1",
            source_seconds=30,
            received_seconds=30,
            value=80.5,
            lineage_root="ROOT-TEMP",
        )
        thermal_second = record(
            "OBS-THERM-1",
            modality="THERMAL_IMAGE",
            source_seconds=35,
            received_seconds=35,
            value=81.5,
            lineage_root="ROOT-THERMAL",
        )
        forwarded_replay = record(
            "OBS-TEMP-0",
            received_seconds=40,
            known_seconds=0,
            lineage_root="ROOT-TEMP",
            lineage_path=("edge-A", "relay-B", "relay-C"),
        )
        delayed_thermal = record(
            "OBS-THERM-LATE",
            modality="THERMAL_IMAGE",
            source_seconds=25,
            received_seconds=90,
            value=80.25,
            lineage_root="ROOT-THERMAL",
        )
        flag_escalation = risk_update(
            "OBS-TEMP-0", source_seconds=0, received_seconds=50
        )
        trajectory = (
            temp_first,
            thermal_first,
            temp_second,
            thermal_second,
            forwarded_replay,
            delayed_thermal,
            flag_escalation,
        )

        visible_before_late_arrival = freeze(trajectory, at_seconds=80)
        visible_after_late_arrival = freeze(trajectory, at_seconds=100)
        self.assertEqual(len(visible_before_late_arrival.observations), 4)
        self.assertEqual(len(visible_after_late_arrival.observations), 5)
        self.assertEqual(
            visible_before_late_arrival.observation("OBS-TEMP-0").value("risk_flag"),
            "EXPOSURE_HIGH",
        )
        self.assertEqual(
            visible_after_late_arrival.observation("OBS-THERM-LATE").received_at,
            stamp(90),
        )

        pairs, proposals = run_arm(
            visible_before_late_arrival, association.multi_evidence_rule
        )
        linked_cross_modal = [
            proposal
            for proposal in proposals
            if proposal.action is association.ProposalAction.LINK_CANDIDATES
        ]
        self.assertEqual(len(pairs), 6)
        self.assertEqual(len(linked_cross_modal), 4)
        self.assertTrue(
            all(proposal.independent_lineage_root_count == 2 for proposal in linked_cross_modal)
        )

    def test_single_source_risk_flag_escalation_does_not_add_support(self):
        self.require_inference_api()
        temp = record("OBS-TEMP-1", lineage_root="ROOT-TEMP")
        thermal = record(
            "OBS-THERM-1",
            modality="THERMAL_IMAGE",
            source_seconds=5,
            received_seconds=5,
            value=81.0,
            lineage_root="ROOT-THERMAL",
        )
        before = freeze((temp, thermal), at_seconds=10)
        after = freeze(
            (temp, thermal, risk_update("OBS-TEMP-1", source_seconds=0, received_seconds=30)),
            at_seconds=40,
        )
        before_proposal = run_arm(before, association.multi_evidence_rule)[1][0]
        after_proposal = run_arm(after, association.multi_evidence_rule)[1][0]

        self.assertEqual(before_proposal.action, association.ProposalAction.LINK_CANDIDATES)
        self.assertEqual(after_proposal.action, before_proposal.action)
        self.assertEqual(
            after_proposal.independent_lineage_root_count,
            before_proposal.independent_lineage_root_count,
        )
        self.assertEqual(len(after.observations), 2)
        self.assertEqual(after.observation("OBS-TEMP-1").value("risk_flag"), "EXPOSURE_HIGH")

    def test_adjacent_verified_assets_are_retained_separately(self):
        self.require_inference_api()
        prefix = freeze(
            (
                record("OBS-PUMP-A", asset_id="PUMP-A", position=(0.0, 0.0)),
                record(
                    "OBS-PUMP-B",
                    asset_id="PUMP-B",
                    position=(3.0, 0.0),
                    lineage_root="ROOT-TEMP-B",
                ),
            ),
            at_seconds=10,
        )
        pairs = association.build_candidate_universe(
            prefix, config=association.InferenceConfig()
        )
        self.assertEqual(len(pairs), 1)
        for method in (association.time_asset_rule, association.multi_evidence_rule):
            proposal = method(prefix, pairs[0], config=association.InferenceConfig())
            self.assertEqual(proposal.action, association.ProposalAction.RETAIN_SEPARATELY)
            self.assertIn("VERIFIED_ASSET_MISMATCH", proposal.reason_codes)

    def test_uncertain_asset_binding_and_degraded_quality_abstain(self):
        self.require_inference_api()
        uncertain_prefix = freeze(
            (
                record("OBS-UNKNOWN-A", binding="UNKNOWN", position=(0.0, 0.0)),
                record(
                    "OBS-UNKNOWN-B",
                    binding="UNKNOWN",
                    position=(1.0, 0.0),
                    lineage_root="ROOT-THERMAL",
                    modality="THERMAL_IMAGE",
                ),
            ),
            at_seconds=10,
        )
        uncertain_pairs = association.build_candidate_universe(
            uncertain_prefix, config=association.InferenceConfig()
        )
        self.assertEqual(len(uncertain_pairs), 1)
        for method in (association.time_asset_rule, association.multi_evidence_rule):
            proposal = method(
                uncertain_prefix,
                uncertain_pairs[0],
                config=association.InferenceConfig(),
            )
            self.assertEqual(proposal.action, association.ProposalAction.ABSTAIN)

        degraded_prefix = freeze(
            (
                record("OBS-DEGRADED-A"),
                record(
                    "OBS-DEGRADED-B",
                    modality="THERMAL_IMAGE",
                    source_seconds=5,
                    received_seconds=5,
                    value=81.0,
                    quality="DEGRADED",
                    lineage_root="ROOT-THERMAL",
                ),
            ),
            at_seconds=10,
        )
        _, degraded_proposals = run_arm(
            degraded_prefix, association.multi_evidence_rule
        )
        self.assertEqual(len(degraded_proposals), 1)
        self.assertEqual(
            degraded_proposals[0].action, association.ProposalAction.ABSTAIN
        )
        self.assertIn(
            "QUALITY_OR_CALIBRATION_NOT_VERIFIED",
            degraded_proposals[0].reason_codes,
        )

    def test_changed_measurement_under_same_observation_id_fails_closed(self):
        self.require_api()
        first = record("OBS-CONFLICTING")
        conflicting_fields = tuple(
            replace(fact, value=82.0) if fact.name == "value" else fact
            for fact in first.fields
        )
        conflicting = replace(first, fields=conflicting_fields)
        with self.assertRaisesRegex(ValueError, "conflicting immutable field value"):
            freeze((first, conflicting), at_seconds=10)

    def test_recovery_boundary_retains_reappearing_anomaly_separately(self):
        self.require_inference_api()
        first = record("OBS-ANOMALY-1", source_seconds=0, received_seconds=0)
        recovery = record(
            "OBS-RECOVERY",
            source_seconds=40,
            received_seconds=40,
            risk_flag="RECOVERY",
            lineage_root="ROOT-TEMP",
        )
        reappeared = record(
            "OBS-ANOMALY-2",
            source_seconds=80,
            received_seconds=80,
            modality="THERMAL_IMAGE",
            lineage_root="ROOT-THERMAL",
        )
        prefix = freeze((first, recovery, reappeared), at_seconds=100)
        pairs = association.build_candidate_universe(
            prefix, config=association.InferenceConfig()
        )
        target = next(
            pair for pair in pairs
            if {pair.left_observation_id, pair.right_observation_id}
            == {"OBS-ANOMALY-1", "OBS-ANOMALY-2"}
        )

        for method in (association.time_asset_rule, association.multi_evidence_rule):
            proposal = method(prefix, target, config=association.InferenceConfig())
            self.assertEqual(proposal.action, association.ProposalAction.RETAIN_SEPARATELY)
            self.assertIn("OBSERVED_RECOVERY_BOUNDARY", proposal.reason_codes)

    def test_methods_share_exact_candidate_universe(self):
        self.require_inference_api()
        prefix = freeze(
            (
                record("OBS-TEMP-A", asset_id="PUMP-A"),
                record(
                    "OBS-THERM-A",
                    asset_id="PUMP-A",
                    modality="THERMAL_IMAGE",
                    source_seconds=5,
                    received_seconds=5,
                    lineage_root="ROOT-THERMAL",
                ),
                record(
                    "OBS-PUMP-B",
                    asset_id="PUMP-B",
                    position=(3.0, 0.0),
                    lineage_root="ROOT-TEMP-B",
                ),
            ),
            at_seconds=10,
        )
        shared = association.build_candidate_universe(
            prefix, config=association.InferenceConfig()
        )
        config = association.InferenceConfig()
        baseline_proposals = tuple(
            association.time_asset_rule(prefix, pair, config=config)
            for pair in shared
        )
        evidence_proposals = tuple(
            association.multi_evidence_rule(prefix, pair, config=config)
            for pair in shared
        )
        baseline_pairs = tuple(proposal.pair for proposal in baseline_proposals)
        evidence_pairs = tuple(proposal.pair for proposal in evidence_proposals)

        self.assertEqual(baseline_pairs, shared)
        self.assertEqual(evidence_pairs, shared)
        self.assertIsInstance(association.time_asset_rule, association.AssociationMethod)
        self.assertIsInstance(association.multi_evidence_rule, association.AssociationMethod)

    def test_link_proposal_only_creates_pending_alert_ledger_association(self):
        self.require_inference_api()
        self.assertIsNotNone(AlertLedger)
        self.assertIsNotNone(CandidateEvent)
        temp = record("OBS-TEMP-A", received_seconds=1, lineage_root="ROOT-TEMP")
        thermal = record(
            "OBS-THERM-A",
            modality="THERMAL_IMAGE",
            source_seconds=2,
            received_seconds=2,
            value=81.0,
            lineage_root="ROOT-THERMAL",
        )
        prefix = freeze((temp, thermal), at_seconds=5)
        proposal = run_arm(prefix, association.multi_evidence_rule)[1][0]
        ledger = AlertLedger()
        for item in (temp, thermal):
            fields = {field.name: field.value for field in item.fields}
            ledger.add_candidate(
                CandidateEvent(
                    candidate_id=item.observation_id,
                    event_time=fields["source_time"],
                    observed_at=item.received_at,
                    summary="Synthetic observable anomaly",
                    source_id=fields["acquisition_lineage"][0],
                    evidence_refs=(f"synthetic://observation/{item.observation_id}",),
                    risk_flag=fields["risk_flag"],
                ),
                alerted_at=item.received_at,
            )
        alerts_before = ledger.alerts

        association_record = association.apply_proposal_to_alert_ledger(proposal, ledger)

        self.assertIsNotNone(association_record)
        self.assertEqual(association_record.status, "PENDING")
        self.assertIsNone(association_record.canonical_card_id)
        self.assertEqual(ledger.alerts[:len(alerts_before)], alerts_before)
        self.assertEqual(len(ledger.cards), 2)
        before = (ledger.cards, ledger.associations, ledger.alerts)
        retained = replace(proposal, action=association.ProposalAction.RETAIN_SEPARATELY)
        abstained = replace(proposal, action=association.ProposalAction.ABSTAIN)
        self.assertIsNone(association.apply_proposal_to_alert_ledger(retained, ledger))
        self.assertIsNone(association.apply_proposal_to_alert_ledger(abstained, ledger))
        self.assertEqual((ledger.cards, ledger.associations, ledger.alerts), before)

    def test_frozen_output_scorer_uses_full_universe_denominators(self):
        self.require_inference_api()
        pairs = (
            association.CandidatePair("OBS-A", "OBS-B"),
            association.CandidatePair("OBS-C", "OBS-D"),
            association.CandidatePair("OBS-E", "OBS-F"),
        )
        proposals = (
            association.AssociationProposal(
                method="RULE_BASELINE",
                pair=pairs[0],
                action=association.ProposalAction.LINK_CANDIDATES,
                reason_codes=("TEST_ONLY_OUTPUT",),
                evidence_refs=("synthetic://pair/ab",),
                independent_lineage_root_count=2,
                decided_at=stamp(10),
            ),
            association.AssociationProposal(
                method="RULE_BASELINE",
                pair=pairs[1],
                action=association.ProposalAction.RETAIN_SEPARATELY,
                reason_codes=("TEST_ONLY_OUTPUT",),
                evidence_refs=("synthetic://pair/cd",),
                independent_lineage_root_count=1,
                decided_at=stamp(10),
            ),
            association.AssociationProposal(
                method="RULE_BASELINE",
                pair=pairs[2],
                action=association.ProposalAction.ABSTAIN,
                reason_codes=("TEST_ONLY_OUTPUT",),
                evidence_refs=(),
                independent_lineage_root_count=0,
                decided_at=stamp(10),
            ),
        )
        frozen = association.freeze_proposals(proposals)
        self.assertEqual(len(frozen.sha256), 64)
        output_doc = json.loads(frozen.canonical_json)
        self.assertNotIn("world_group", frozen.canonical_json.decode("utf-8"))
        self.assertNotIn("first_sufficient_evidence_at", frozen.canonical_json.decode("utf-8"))

        # Scorer-only truth is deliberately introduced after the output is frozen.
        hidden_truth = {
            pairs[0]: {"are_related": False, "world_group": "WORLD-1", "first_sufficient_evidence_at": stamp(8)},
            pairs[1]: {"are_related": True, "world_group": "WORLD-1", "first_sufficient_evidence_at": stamp(8)},
            pairs[2]: {"are_related": True, "world_group": "WORLD-2", "first_sufficient_evidence_at": stamp(9)},
        }

        def score(frozen_output, fixed_pairs, truth):
            prediction_rows = json.loads(frozen_output.canonical_json)["proposals"]
            predicted = {
                frozenset((row["pair"]["left_observation_id"], row["pair"]["right_observation_id"])): row["action"]
                for row in prediction_rows
            }
            actions = [
                predicted.get(frozenset((pair.left_observation_id, pair.right_observation_id)), "ABSTAIN")
                for pair in fixed_pairs
            ]
            errors = [
                (action == "LINK_CANDIDATES" and not truth[pair]["are_related"])
                or (action == "RETAIN_SEPARATELY" and truth[pair]["are_related"])
                for pair, action in zip(fixed_pairs, actions)
            ]
            denominator = len(fixed_pairs)
            return {
                "denominator": denominator,
                "false_merge_rate": sum(
                    action == "LINK_CANDIDATES" and not truth[pair]["are_related"]
                    for pair, action in zip(fixed_pairs, actions)
                ) / denominator,
                "false_split_rate": sum(
                    action == "RETAIN_SEPARATELY" and truth[pair]["are_related"]
                    for pair, action in zip(fixed_pairs, actions)
                ) / denominator,
                "unresolved_count": sum(action == "ABSTAIN" for action in actions),
                "coverage": sum(action != "ABSTAIN" for action in actions) / denominator,
                "independent_world_count": len({truth[pair]["world_group"] for pair in fixed_pairs}),
                "scored_errors": sum(errors),
            }

        scored = score(frozen, pairs, hidden_truth)
        self.assertEqual(scored["denominator"], 3)
        self.assertEqual(scored["false_merge_rate"], 1 / 3)
        self.assertEqual(scored["false_split_rate"], 1 / 3)
        self.assertEqual(scored["unresolved_count"], 1)
        self.assertAlmostEqual(scored["coverage"], 2 / 3)
        self.assertEqual(scored["independent_world_count"], 2)

        all_abstain = association.freeze_proposals(
            tuple(replace(proposal, action=association.ProposalAction.ABSTAIN) for proposal in proposals)
        )
        abstain_score = score(all_abstain, pairs, hidden_truth)
        self.assertEqual(abstain_score["denominator"], 3)
        self.assertEqual(abstain_score["unresolved_count"], 3)
        self.assertEqual(abstain_score["coverage"], 0.0)
        self.assertEqual(abstain_score["scored_errors"], 0)


if __name__ == "__main__":
    unittest.main()
