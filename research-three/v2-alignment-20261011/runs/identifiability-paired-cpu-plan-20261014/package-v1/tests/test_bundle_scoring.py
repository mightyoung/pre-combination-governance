import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


PACKAGE = Path(__file__).resolve().parents[1]
CASE_IDS = (
    "38e02496822f1a85849b6a39f698e50d", "33fadeeedeed902bd0ab9dfae5420213",
    "42474559127419126b713096e9f4d3ee", "81050a121e028f59f1e6940d7c5eb477",
)
METHODS = ("M0", "M1", "M2", "M3")


def load_module(name):
    if name in sys.modules:
        return sys.modules[name]
    module_path = PACKAGE / (name + ".py")
    if not module_path.is_file():
        raise AssertionError("missing feature: " + name + " is not implemented")
    if str(PACKAGE) not in sys.path:
        sys.path.insert(0, str(PACKAGE))
    spec = importlib.util.spec_from_file_location("pcg_pair_" + name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if name not in sys.modules:
        sys.modules[name] = module
    return module


def fake_oracle():
    return {"traces": {
        "I1_NO_INFO_CONTINUING": {
            "must_notify": [1], "must_first_alert": [1],
            "alarm_episodes": {"a": "E1", "b": "E1", "c": "E1", "d": "E1", "e": "E1"},
        },
        "I2_NO_INFO_NEW": {
            "must_notify": [1, 5], "must_first_alert": [1, 5],
            "alarm_episodes": {"a": "E1", "b": "E1", "c": "E1", "d": "E1", "e": "E2"},
        },
    }}


def synthetic_slots():
    rows = []
    case_rows = [{"id": key, "alarm": True} for key in "abcde"]
    for case_id in CASE_IDS:
        old_by_method = {method: {} for method in METHODS}
        for prefix in range(1, 6):
            for method in METHODS:
                visible_ids = list("abcde"[:prefix])
                result = {
                    "cards": {key: "card-" + key for key in visible_ids},
                    "possible": [],
                    "notification_reasons": [],
                    "risk": "EXPOSURE",
                    "priority": "REVIEW",
                    "notify": False,
                    "fused": {},
                    "independent_evidence": 0,
                    "role": "event rules shared; DS motion fusion diagnostic only",
                    "context_evidence": {"status": "ABSENT", "accepted": [], "rejected": []},
                    "card_updates": [],
                    "risk_state_update": None,
                    "review_notification_reasons": [],
                }
                payload = {"method": method, "prefix": case_rows[:prefix],
                           "old": old_by_method[method]}
                input_hash = hashlib.sha256(
                    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                output_hash = hashlib.sha256(
                    json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                rows.append({"case_id": case_id, "prefix": prefix,
                             "method": method, "input_sha256": input_hash,
                             "output_sha256": output_hash, "result": result})
                old_by_method[method] = {key: result[key] for key in ("cards", "risk", "priority")}
    return rows


class FrozenBundleScoringTests(unittest.TestCase):
    def test_partial_slot_file_can_be_frozen_without_overwrite(self):
        bundle = load_module("bundle")
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            run_dir.mkdir()
            slot = {
                "case_id": CASE_IDS[0], "prefix": 1, "method": "M0",
                "input_sha256": "a" * 64, "output_sha256": "b" * 64,
                "result": {"cards": {"a": "card-a"}},
            }
            progress = run_dir / "slots.progress.jsonl"
            progress.write_bytes(bundle.canonical_bytes(slot) + b"\n")
            progress.rename(run_dir / "slots.partial.jsonl")
            attempt = {
                "run_id": "synthetic-prewritten", "attempt_count": 1,
                "task_id": "PCG-IDENTIFIABILITY-PAIRED-CPU-001",
                "task_status": "FAIL", "research_acceptance": "NOT_EVALUATED",
                "planned_method_invocations": 80, "method_start_requests": 2,
                "method_invocations_started": 2,
                "completed_method_invocations": 1, "partial": True,
                "stop_reason": "synthetic failure", "terminal_exit_code": 30,
                "case_ids": list(CASE_IDS),
                "method_order": list(METHODS),
            }
            receipt = bundle.freeze_bundle(run_dir, [slot], attempt)
            self.assertEqual(1, bundle.verify_frozen_bundle(run_dir).freeze["rows"])
            self.assertEqual("slots.partial.jsonl", receipt["output_file"])

    def test_incomplete_bundle_is_rejected_before_oracle_is_read(self):
        bundle = load_module("bundle")
        scorer = load_module("scorer")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "run"
            run_dir.mkdir()
            (run_dir / "attempt.json").write_text(json.dumps({
                "task_status": "PASS", "planned_method_invocations": 80,
                "completed_method_invocations": 80,
            }))
            manifest_path = root / "manifest.json"
            oracle_path = root / "oracle.json"
            manifest_path.write_text("{}")
            oracle_path.write_text("this is intentionally not JSON")
            with self.assertRaisesRegex(bundle.BundleError, "output freeze"):
                scorer.score_bundle(run_dir, manifest_path, oracle_path,
                                    root / "case-map.json", root / "score.json")

    def test_execution_pass_is_independent_of_research_acceptance(self):
        bundle = load_module("bundle")
        scorer = load_module("scorer")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "run"
            run_dir.mkdir()
            oracle = fake_oracle()
            oracle_bytes = json.dumps(oracle, sort_keys=True, separators=(",", ":")).encode()
            oracle_path = root / "oracle.json"
            oracle_path.write_bytes(oracle_bytes)
            ids = CASE_IDS
            case_map = {"schema_version": 1, "oracle_trace_for_case": {
                ids[0]: "I1_NO_INFO_CONTINUING", ids[1]: "I2_NO_INFO_NEW",
                ids[2]: "I2_NO_INFO_NEW", ids[3]: "I2_NO_INFO_NEW",
            }}
            map_path = root / "case-map.json"
            map_bytes = json.dumps(case_map, sort_keys=True, separators=(",", ":")).encode()
            map_path.write_bytes(map_bytes)
            pair_cases = [{"case_id": case_id,
                           "rows": [{"id": key, "alarm": True} for key in "abcde"]}
                          for case_id in ids]
            pair_path = root / "PAIR_METHOD_INPUTS.json"
            pair_bytes = json.dumps({"schema_version": 1, "cases": pair_cases},
                                    sort_keys=True, separators=(",", ":")).encode()
            pair_path.write_bytes(pair_bytes)
            manifest = {
                "task_id": "PCG-IDENTIFIABILITY-PAIRED-CPU-001",
                "planned_method_invocations": 80,
                "method_order": list(METHODS),
                "case_ids": list(ids),
                "pair_inputs_path": "PAIR_METHOD_INPUTS.json",
                "pair_inputs_sha256": hashlib.sha256(pair_bytes).hexdigest(),
                "oracle_case_map_sha256": hashlib.sha256(map_bytes).hexdigest(),
                "oracle_sha256": hashlib.sha256(oracle_bytes).hexdigest(),
                "plan_sha256": "f" * 64,
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, sort_keys=True))
            attempt = {
                "run_id": "synthetic-score-case",
                "task_id": "PCG-IDENTIFIABILITY-PAIRED-CPU-001",
                "attempt_count": 1,
                "task_status": "PASS",
                "research_acceptance": "NOT_EVALUATED",
                "planned_method_invocations": 80,
                "method_start_requests": 80,
                "method_invocations_started": 80,
                "completed_method_invocations": 80,
                "partial": False,
                "stop_reason": None,
                "terminal_exit_code": 0,
                "case_ids": list(ids),
                "method_order": list(METHODS),
                "task_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "oracle_sha256": hashlib.sha256(oracle_bytes).hexdigest(),
                "oracle_case_map_sha256": hashlib.sha256(map_bytes).hexdigest(),
                "plan_sha256": "f" * 64,
            }
            bundle.freeze_bundle(run_dir, synthetic_slots(), attempt)
            result = scorer.score_bundle(run_dir, manifest_path, oracle_path,
                                         map_path, root / "score.json")
            self.assertEqual("PASS", result["task_status"])
            self.assertEqual("FALSE", result["research_acceptance"])
            self.assertEqual(80, result["completed_method_invocations"])
            self.assertEqual(16, len(result["first_alert_checks"]))
            self.assertTrue(all(check["missed"] for check in result["first_alert_checks"]))

            # A rehashed, known-trace remapping must still fail the scorer's
            # plan pin instead of changing which physical trace is scored.
            changed_map = {"schema_version": 1, "oracle_trace_for_case": {
                ids[0]: "I2_NO_INFO_NEW", ids[1]: "I1_NO_INFO_CONTINUING",
                ids[2]: "I2_NO_INFO_NEW", ids[3]: "I2_NO_INFO_NEW",
            }}
            changed_map_bytes = json.dumps(
                changed_map, sort_keys=True, separators=(",", ":")
            ).encode()
            map_path.write_bytes(changed_map_bytes)
            manifest["oracle_case_map_sha256"] = hashlib.sha256(changed_map_bytes).hexdigest()
            manifest_path.write_text(json.dumps(manifest, sort_keys=True))
            attempt_path = run_dir / "attempt.json"
            frozen_attempt = json.loads(attempt_path.read_text())
            frozen_attempt["task_manifest_sha256"] = hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest()
            frozen_attempt["oracle_case_map_sha256"] = manifest["oracle_case_map_sha256"]
            attempt_path.write_text(json.dumps(frozen_attempt, sort_keys=True,
                                               separators=(",", ":")) + "\n")
            with self.assertRaisesRegex(bundle.BundleError, "mapping differs from the reviewed plan"):
                scorer.score_bundle(bundle_dir=run_dir, manifest_path=manifest_path,
                                    oracle_path=oracle_path,
                                    oracle_case_map_path=map_path,
                                    score_path=root / "changed-map-score.json")

    def test_scorer_rejects_paired_case_output_mismatch(self):
        bundle = load_module("bundle")
        scorer = load_module("scorer")
        case_rows = {case_id: [{"id": "a", "alarm": True}] for case_id in CASE_IDS}
        slots = {}
        for case_id in CASE_IDS:
            for prefix in range(1, 6):
                for method in METHODS:
                    result = {"cards": {"a": "same-card"}, "possible": []}
                    slots[(case_id, prefix, method)] = {
                        "input_sha256": "a" * 64,
                        "result": result,
                    }
        slots[(CASE_IDS[1], 3, "M2")]["result"] = {
            "cards": {"a": "different-card"}, "possible": []
        }
        with self.assertRaisesRegex(bundle.BundleError, "A/B protocol failure"):
            scorer._validate_ab_consistency(case_rows, slots, CASE_IDS)

    def test_pass_cannot_claim_fewer_than_eighty_completed_slots(self):
        bundle = load_module("bundle")
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            run_dir.mkdir()
            attempt = {
                "run_id": "synthetic-short-pass", "attempt_count": 1,
                "task_id": "PCG-IDENTIFIABILITY-PAIRED-CPU-001",
                "task_status": "PASS", "research_acceptance": "NOT_EVALUATED",
                "planned_method_invocations": 80, "method_start_requests": 79,
                "method_invocations_started": 79,
                "completed_method_invocations": 79, "partial": True,
                "stop_reason": "synthetic failure", "terminal_exit_code": 0,
                "case_ids": list(CASE_IDS),
                "method_order": list(METHODS),
            }
            with self.assertRaisesRegex(bundle.BundleError, "80 planned slots"):
                bundle.freeze_bundle(run_dir, synthetic_slots()[:79], attempt)


if __name__ == "__main__":
    unittest.main()
